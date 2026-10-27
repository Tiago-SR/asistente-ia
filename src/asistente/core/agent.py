"""Loop del agente.

`run_turn` no persiste: devuelve los mensajes nuevos y el llamador (API) los guarda
solo si el turno terminó bien. Así un turno cortado no deja historial a medias.
"""

import asyncio
import json
import logging
import time
from dataclasses import dataclass, field, replace
from datetime import UTC, datetime
from typing import Any

from asistente.core import events
from asistente.core import excel as excels
from asistente.core import memoria as memorias
from asistente.core import recientes as consultas
from asistente.core.llm.base import Adjunto, LlamadaTool, LLMError, Mensaje, Uso
from asistente.core.ports import (
    LLM,
    Acciones,
    Archivos,
    Auditoria,
    Conector,
    Contexto,
    EventoMetrica,
    LimiteExcedido,
    Limites,
    Memoria,
    Metricas,
    Recientes,
    ResultadoTool,
    TurnoMemoria,
    Web,
)
from asistente.core.voz_resumen import FiltroVoz, limpiar
from asistente.core.web import herramientas as webtools

log = logging.getLogger(__name__)

# Descripción legible para el evento `tool`; sin parámetros, que pueden ser datos de negocio.
MAX_PROPUESTAS_TURNO = 3  # tarjetas independientes por turno (solo escrituras normales)
_LEGIBLE = "Consultando {nombre}"
_LEGIBLE_ACCION = "Preparando {nombre}"
_LEGIBLE_WEB = {webtools.BUSCAR: "Buscando en la web", webtools.LEER: "Leyendo una página web"}
_AVISO_CORTADA = "\n\n_(La respuesta se cortó por ser demasiado larga. Pedime que siga o que sea más breve.)_"

# Lo que ve el modelo tras proponer una acción: no se ejecutó y no debe decir que sí.
_PENDIENTE = (
    "La acción NO se ha ejecutado. El usuario la verá en pantalla con un botón para confirmarla o "
    "cancelarla. Dile en una frase qué le pediste confirmar y espera; no afirmes que se hizo."
)


@dataclass(frozen=True)
class ConfigTurno:
    max_iter: int = 8
    max_output_tokens: int = 4096
    # Debe ser menor que la vida del token del usuario.
    timeout_turno_s: float = 120.0
    timeout_tool_s: float = 30.0
    max_tools_concurrentes: int = 4
    max_llamadas_por_iteracion: int = 8
    # Canal de voz: el modelo abre su respuesta con un bloque `<voz>` que se emite aparte (evento `voz`).
    resumen_voz: bool = False
    # Búsqueda web (tools locales `buscar_web` y `leer_pagina`): topes por usuario y texto máximo de una página.
    web_max_por_min: int = 10
    web_max_por_dia: int = 100
    web_max_por_dia_sistema: int = 1000
    web_max_pagina_chars: int = 12_000
    web_max_por_turno: int = 4  # búsquedas + lecturas: el cupo del proveedor es chico y compartido
    # Excel descargable (tool local `generar_excel`): topes de una tabla.
    excel_max_filas: int = 5000
    excel_max_columnas: int = 50
    excel_max_kb: int = 2048


@dataclass
class ResultadoTurno:
    motivo: str  # fin | error | token_expirado
    nuevos: list[Mensaje] = field(default_factory=list)
    texto: str = ""
    uso: Uso = field(default_factory=Uso)
    # Milisegundos desde que empezó el turno: primer texto (`primer_delta`), resumen hablado (`voz`) y fin (`total`).
    tiempos: dict[str, int] = field(default_factory=dict)
    # Llamadas al LLM de este turno (incluidas las fallidas) y el tiempo que se pasó esperándolas, sin tools.
    llamadas_llm: int = 0
    latencia_llm_ms: int = 0

    @property
    def completo(self) -> bool:
        return self.motivo == "fin"


async def run_turn(
    ctx: Contexto,
    llm: LLM,
    conector: Conector,
    auditoria: Auditoria,
    limites: Limites,
    historial: list[Mensaje],
    texto: str,
    emit: events.Emit,
    conversacion_id: Any = None,
    config: ConfigTurno | None = None,
    acciones: Acciones | None = None,
    recientes: Recientes | None = None,
    memoria: Memoria | None = None,
    adjuntos: tuple[Adjunto, ...] = (),
    web: Web | None = None,
    metricas: Metricas | None = None,
    excel: Archivos | None = None,
    reservar: bool = True,  # False: el llamador ya reservó el mensaje (`reservar_cuota`) antes de gastar en medios
) -> ResultadoTurno:
    config = config or ConfigTurno()
    estado = ResultadoTurno("error")
    estado.tiempos["_t0"] = time.monotonic_ns() // 1_000_000
    errores: list[str] = []  # los códigos de error que se le dijeron al usuario: son el motivo en las métricas
    limite: str | None = None

    async def emitir(evento: str, datos: Any = None) -> None:
        if evento == events.ERROR and isinstance(datos, str):
            errores.append(datos)
        await emit(evento, datos)

    try:  # el `finally` también corre si el cliente corta (CancelledError): el turno se cuenta igual
        try:
            if reservar:
                await limites.reservar_mensaje(ctx)
        except LimiteExcedido as e:
            limite = e.cual
            await emitir(events.ERROR, e.cual)
            return estado
        try:
            async with asyncio.timeout(config.timeout_turno_s):
                await _loop(ctx, llm, conector, auditoria, limites, historial, texto, emitir,
                            conversacion_id, config, estado, acciones, recientes, memoria, adjuntos, web, excel)
        except TimeoutError:
            estado.motivo, estado.nuevos = "error", []
            await emitir(events.ERROR, "timeout_turno")
        return estado
    finally:
        if metricas is not None:
            _medir(metricas, ctx, config, estado, errores, limite, adjuntos)


async def reservar_cuota(ctx: Contexto, limites: Limites, metricas: Metricas | None) -> str | None:
    """Reserva el mensaje antes de descargar o leer medios (luego `run_turn(reservar=False)`).
    Devuelve el tope excedido, o None si hay cupo; un rechazo queda en las métricas igual que en `run_turn`."""
    try:
        await limites.reservar_mensaje(ctx)
    except LimiteExcedido as e:
        if metricas is not None:
            metricas.registrar(EventoMetrica(sistema_id=ctx.sistema_id, usuario_ref=ctx.usuario_ref, tipo="llm",
                                             resultado="limite", motivo=e.cual, modelo=ctx.modelo))
        return e.cual
    return None


def _medir(metricas: Metricas, ctx: Contexto, config: ConfigTurno, estado: ResultadoTurno,
           errores: list[str], limite: str | None, adjuntos: tuple[Adjunto, ...] = ()) -> None:
    """Un evento por turno. Nunca lanza: observar no puede romper la respuesta."""
    try:
        if limite is not None:
            resultado, motivo = "limite", limite
        elif estado.motivo == "fin":
            resultado, motivo = "ok", ""
        elif estado.motivo == "token_expirado":
            resultado, motivo = "error", "token_expirado"
        else:  # sin error emitido = el turno se cortó (el cliente cerró la conexión)
            resultado, motivo = "error", errores[-1] if errores else "cancelado"
        duracion = time.monotonic_ns() // 1_000_000 - estado.tiempos["_t0"]
        metricas.registrar(EventoMetrica(
            sistema_id=ctx.sistema_id, usuario_ref=ctx.usuario_ref, tipo="llm", resultado=resultado,
            motivo=motivo, modelo=ctx.modelo, canal="voz" if config.resumen_voz else "texto",
            tokens_in=estado.uso.tokens_in, tokens_in_cache=estado.uso.tokens_in_cache,
            tokens_out=estado.uso.tokens_out, llamadas_llm=estado.llamadas_llm,
            latencia_llm_ms=estado.latencia_llm_ms if estado.llamadas_llm else None,
            ttft_ms=estado.tiempos.get("primer_delta"), duracion_ms=duracion, imagenes=len(adjuntos),
            imagen_max_kb=-(-max(a.bytes for a in adjuntos) // 1024) if adjuntos else None,
        ))
    except Exception:
        log.warning("[%s] no se pudo registrar la métrica del turno", ctx.request_id, exc_info=True)


async def _loop(ctx, llm, conector, auditoria, limites, historial, texto, emit,
                conversacion_id, config, estado, acciones=None, recientes=None, memoria=None,
                adjuntos=(), web=None, excel=None) -> None:
    tools = await conector.tools()
    escrituras = {t.nombre for t in tools if t.escritura}
    destructivas = {t.nombre for t in tools if t.destructiva}
    lectura = {t.nombre for t in tools if not t.escritura}
    if recientes is not None:
        tools = [*tools, consultas.TOOL]  # tool local del asistente: no existe en el sistema
    if memoria is not None:
        tools = [*tools, *memorias.TOOLS]  # `recordar` y `olvidar`: locales, siempre con botón
    if web is not None:
        tools = [*tools, *webtools.TOOLS]  # `buscar_web` y `leer_pagina`: internet, aparte de los datos del sistema
    if excel is not None:
        tools = [*tools, excels.TOOL]  # `generar_excel`: un archivo para descargar, no toca al sistema
    propuestas = 0  # propuestas de este turno (cruza las iteraciones)
    exclusiva = False  # una destructiva o local va sola: nada más se propone en el turno
    guardar = asyncio.Lock()  # las `crear` del turno corren en serie: así el duplicado y el tope horario se ven
    inicio_turno = datetime.now(UTC)  # las pendientes anteriores a él se reemplazan; las del turno conviven
    web_usadas = 0  # búsquedas y lecturas web de este turno
    datos_sistema = False  # el turno ya trajo resultados de tools del sistema (o de recientes)
    leyo_web = False  # el turno ya leyó una página: su texto no es confiable y podría inducir una búsqueda con datos
    reintento_vacio = False  # una respuesta vacía se pide de nuevo una vez
    nuevos = [Mensaje("user", texto, adjuntos=adjuntos)]
    usar_paralelas = llm.capacidades.soporta_tools_paralelas
    sem = asyncio.Semaphore(config.max_tools_concurrentes if usar_paralelas else 1)

    def marca(nombre: str) -> None:
        """Registra, una sola vez por turno, cuánto tardó en llegar `nombre` (para medir la latencia percibida)."""
        if nombre not in estado.tiempos:
            estado.tiempos[nombre] = time.monotonic_ns() // 1_000_000 - estado.tiempos["_t0"]

    for _ in range(config.max_iter):
        filtro = FiltroVoz() if config.resumen_voz else None

        async def delta(t: str, filtro=filtro) -> None:
            if filtro is None:
                marca("primer_delta")
                await emit(events.DELTA, t)
                return
            visible, resumen = filtro.alimentar(t)
            if resumen:
                marca("voz")
                await emit(events.VOZ, resumen)
            if visible:
                marca("primer_delta")
                await emit(events.DELTA, visible)

        t_llm = time.monotonic_ns()
        estado.llamadas_llm += 1
        try:
            resp = await llm.stream(
                modelo=ctx.modelo,
                system=ctx.prompt_system,
                tools=tools,
                messages=[*historial, *nuevos],
                max_tokens=config.max_output_tokens,
                on_delta=delta,
            )
        except LLMError as e:
            log.error("[%s] fallo del LLM: %s", ctx.request_id, e)
            estado.motivo = "error"
            await emit(events.ERROR, "llm_no_disponible")
            return
        finally:
            estado.latencia_llm_ms += (time.monotonic_ns() - t_llm) // 1_000_000
        estado.uso += resp.uso
        try:  # contabilidad: si falla no se pierde la respuesta ya generada
            await limites.registrar_uso(ctx, resp.uso)
        except Exception:
            log.warning("[%s] no se pudo registrar el uso de tokens", ctx.request_id, exc_info=True)
        if filtro is not None:
            resto = filtro.cerrar()
            if resto:
                await emit(events.DELTA, resto)
            resp = replace(resp, texto=limpiar(resp.texto))  # el bloque `<voz>` no se guarda ni se reenvía al modelo

        if resp.motivo_fin != "tool":
            if resp.motivo_fin == "limite":
                log.warning("[%s] respuesta cortada por max_output_tokens=%d (salida=%d tokens, %d caracteres)",
                            ctx.request_id, config.max_output_tokens, resp.uso.tokens_out, len(resp.texto))
            if not resp.texto.strip():
                # Sin texto ni tools: el usuario no vería nada. Con `limite` el razonamiento se comió el tope
                # (repetir daría lo mismo); en otro caso suele ser transitorio y se repite una vez.
                log.warning("[%s] el modelo no devolvió texto (motivo=%s, salida=%d tokens)",
                            ctx.request_id, resp.motivo_fin, resp.uso.tokens_out)
                if resp.motivo_fin != "limite" and not reintento_vacio:
                    reintento_vacio = True
                    continue
                estado.motivo = "error"
                await emit(events.ERROR, "respuesta_cortada" if resp.motivo_fin == "limite" else "respuesta_vacia")
                return
            if resp.motivo_fin == "limite":
                await emit(events.DELTA, _AVISO_CORTADA)  # se ve en pantalla; no se guarda en el historial
            nuevos.append(resp.como_mensaje())
            estado.motivo, estado.nuevos, estado.texto = "fin", nuevos, resp.texto
            marca("total")
            await emit(events.DONE, {"conversacion_id": conversacion_id})
            return

        llamadas = resp.llamadas[: config.max_llamadas_por_iteracion]
        # Se reenvía solo lo atendido: todo tool_call enviado debe tener su resultado.
        nuevos.append(Mensaje("assistant", resp.texto, llamadas))
        await emit(events.TOOL, [
            _LEGIBLE_WEB[c.nombre] if web is not None and c.nombre in webtools.NOMBRES
            else "Generando el Excel" if excel is not None and c.nombre == excels.NOMBRE
            else (_LEGIBLE_ACCION if c.nombre in escrituras or (memoria is not None and c.nombre in memorias.NOMBRES)
                  else _LEGIBLE).format(nombre=c.nombre)
            for c in llamadas
        ])
        atenciones = []
        for c in llamadas:
            local = memoria is not None and c.nombre in memorias.NOMBRES
            if c.nombre in escrituras or local:
                # Se decide antes de cualquier await: dos escrituras en la misma iteración no compiten.
                solitaria = local or c.nombre in destructivas
                if exclusiva or (solitaria and propuestas) or propuestas >= MAX_PROPUESTAS_TURNO:
                    atenciones.append(_rechazar_extra(c, exclusiva or solitaria))
                    continue
                propuestas += 1
                exclusiva = solitaria
                # Ninguna escritura se propone en un turno que ya leyó la web (ni en la misma tanda que una).
                con_web = web_usadas > 0 or any(x.nombre in webtools.NOMBRES for x in llamadas)
                turno = TurnoMemoria(tuple(nuevos), frozenset(lectura), conector) if local else None
                atenciones.append(_proponer(ctx, conector, acciones, auditoria, conversacion_id,
                                            c, config, emit, memoria if local else None, turno,
                                            c.nombre in destructivas, con_web, inicio_turno, guardar))
            elif web is not None and c.nombre in webtools.NOMBRES:
                web_usadas += 1
                if web_usadas > config.web_max_por_turno:
                    atenciones.append(_tope_web(config))
                    continue
                if c.nombre == webtools.BUSCAR and (leyo_web or datos_sistema or any(_es_dato_sistema(x.nombre, excel, recientes, memoria) for x in llamadas)):
                    atenciones.append(_web_tras_datos())
                    continue
                atenciones.append(_web(ctx, web, limites, auditoria, conversacion_id, c, config, emit,
                                       [*historial, *nuevos]))
            elif excel is not None and c.nombre == excels.NOMBRE:
                atenciones.append(_generar_excel(ctx, excel, auditoria, conversacion_id, c, config))
            elif recientes is not None and c.nombre == consultas.NOMBRE:
                atenciones.append(_consultar_recientes(ctx, recientes, lectura, auditoria, conversacion_id, c))
            else:
                atenciones.append(_ejecutar(ctx, conector, auditoria, conversacion_id, c, sem, config))
        leyo_web = leyo_web or any(c.nombre == webtools.LEER for c in llamadas)
        datos_sistema = datos_sistema or any(_es_dato_sistema(c.nombre, excel, recientes, memoria) for c in llamadas)
        resultados = await asyncio.gather(*atenciones)
        for c, r in zip(llamadas, resultados, strict=True):
            if r.token_expirado:
                estado.motivo, estado.nuevos = "token_expirado", []
                await emit(events.TOKEN_EXPIRADO, None)
                return
            if r.ui:
                await emit(events.UI, r.ui)  # el modelo no ve `ui`
            nuevos.append(
                Mensaje("tool", json.dumps(r.para_modelo(), ensure_ascii=False), llamada_id=c.id)
            )

    estado.motivo = "error"
    await emit(events.ERROR, "demasiadas_iteraciones")


async def _ejecutar(ctx, conector, auditoria, conversacion_id, c: LlamadaTool, sem, config) -> ResultadoTool:
    inicio = time.monotonic()
    if c.argumentos_invalidos:
        r = ResultadoTool(False, error="parametros_invalidos", detalle="los argumentos no son un objeto JSON")
    else:
        async with sem:
            try:
                r = await asyncio.wait_for(
                    conector.ejecutar(c.nombre, c.parametros), config.timeout_tool_s
                )
            except TimeoutError:
                r = ResultadoTool(False, error="timeout", detalle="la consulta tardó demasiado")
            except Exception:  # el contrato dice que no lanza; si lo hace, no se cae el turno
                log.exception("[%s] el conector lanzó en %s", ctx.request_id, c.nombre)
                r = ResultadoTool(False, error="error_sistema", detalle="falla interna del conector")
    ms = int((time.monotonic() - inicio) * 1000)
    try:
        await auditoria.registrar_tool(ctx, conversacion_id, c.nombre, c.parametros, r, ms)
    except Exception:
        log.exception("[%s] no se pudo auditar %s", ctx.request_id, c.nombre)
    return r


async def _consultar_recientes(ctx, recientes, lectura, auditoria, conversacion_id, c: LlamadaTool) -> ResultadoTool:
    """Tool local: lee el historial de consultas del propio usuario. No toca al sistema ni el conector."""
    inicio = time.monotonic()
    if c.argumentos_invalidos:
        r = ResultadoTool(False, error="parametros_invalidos", detalle="los argumentos no son un objeto JSON")
    else:
        try:
            r = await consultas.ejecutar(ctx, recientes, lectura, c.parametros)
        except Exception:
            log.exception("[%s] falló %s", ctx.request_id, c.nombre)
            r = ResultadoTool(False, error="error_sistema", detalle="no se pudo leer el historial de consultas")
    ms = int((time.monotonic() - inicio) * 1000)
    try:
        await auditoria.registrar_tool(ctx, conversacion_id, c.nombre, c.parametros, r, ms)
    except Exception:
        log.exception("[%s] no se pudo auditar %s", ctx.request_id, c.nombre)
    return r


async def _generar_excel(ctx, archivos, auditoria, conversacion_id, c: LlamadaTool, config) -> ResultadoTool:
    """Tool local: arma el .xlsx y lo guarda. Se audita sin las filas (datos de negocio): solo nombre y tamaño."""
    inicio = time.monotonic()
    if c.argumentos_invalidos:
        r = ResultadoTool(False, error="parametros_invalidos", detalle="los argumentos no son un objeto JSON")
    else:
        try:
            r = await asyncio.wait_for(
                excels.ejecutar(ctx, archivos, conversacion_id, c.parametros, max_filas=config.excel_max_filas,
                                max_columnas=config.excel_max_columnas, max_kb=config.excel_max_kb),
                config.timeout_tool_s)
        except TimeoutError:
            r = ResultadoTool(False, error="timeout", detalle="el archivo tardó demasiado en generarse")
        except Exception:
            log.exception("[%s] falló %s", ctx.request_id, c.nombre)
            r = ResultadoTool(False, error="error_sistema", detalle="no se pudo generar el archivo")
    ms = int((time.monotonic() - inicio) * 1000)
    try:
        await auditoria.registrar_tool(ctx, conversacion_id, c.nombre, excels.compactar_parametros(c.nombre, c.parametros), r, ms)
    except Exception:
        log.exception("[%s] no se pudo auditar %s", ctx.request_id, c.nombre)
    return r


async def _web(ctx, web, limites, auditoria, conversacion_id, c: LlamadaTool, config, emit, vistos) -> ResultadoTool:
    """Tools locales de internet. Lo buscado o leído se muestra al usuario (evento `web`) y se audita con sus
    parámetros: así una fuga de datos del sistema en la consulta queda a la vista."""
    inicio = time.monotonic()
    salio = False  # solo se muestra lo que llegó a salir hacia internet
    if c.argumentos_invalidos:
        r = ResultadoTool(False, error="parametros_invalidos", detalle="los argumentos no son un objeto JSON")
    elif (r := webtools.validar(c.nombre, c.parametros)) is None:
        try:
            await limites.reservar_web(ctx.sistema_id, ctx.usuario_ref, config.web_max_por_min, config.web_max_por_dia)
            # ref vacío = contador global del sistema (ningún `sub` es vacío)
            await limites.reservar_web(ctx.sistema_id, "", config.web_max_por_dia_sistema, config.web_max_por_dia_sistema)
        except LimiteExcedido as e:
            r = ResultadoTool(False, error=e.cual, detalle="demasiadas búsquedas web; intenta más tarde")
        else:
            try:
                if c.nombre == webtools.BUSCAR:
                    trabajo = webtools.buscar(web, c.parametros, webtools.idioma_de(ctx.locale))
                else:
                    trabajo = webtools.leer(web, c.parametros, webtools.urls_permitidas(vistos),
                                            config.web_max_pagina_chars)
                salio = True
                r = await asyncio.wait_for(trabajo, config.timeout_tool_s)
            except TimeoutError:
                r = ResultadoTool(False, error="timeout", detalle="la web tardó demasiado")
            except Exception:
                log.exception("[%s] falló %s", ctx.request_id, c.nombre)
                r = ResultadoTool(False, error="web_no_disponible", detalle="falla interna de la búsqueda web")
    if salio and r.error != "url_no_permitida":
        await emit(events.WEB, webtools.evento(c.nombre, c.parametros, r))
    ms = int((time.monotonic() - inicio) * 1000)
    try:
        await auditoria.registrar_tool(ctx, conversacion_id, c.nombre, c.parametros, r, ms)
    except Exception:
        log.exception("[%s] no se pudo auditar %s", ctx.request_id, c.nombre)
    return r


async def _tope_web(config) -> ResultadoTool:
    return ResultadoTool(False, error="tope_web_turno",
                         detalle=f"ya se hicieron {config.web_max_por_turno} búsquedas o lecturas web en este turno: "
                                 "responde con lo que tienes")


def _es_dato_sistema(nombre: str, excel, recientes, memoria) -> bool:
    """Una tool que devuelve datos del sistema: ni web, ni Excel, ni memoria local."""
    return not (nombre in webtools.NOMBRES or (excel is not None and nombre == excels.NOMBRE)
                or (memoria is not None and nombre in memorias.NOMBRES))


async def _web_tras_datos() -> ResultadoTool:
    return ResultadoTool(False, error="web_tras_datos",
                         detalle="no se busca en la web tras leer una página ni en un turno con datos del sistema: "
                                 "la consulta saldría a un tercero; responde con lo que tienes")


async def _rechazar_extra(c: LlamadaTool, sola: bool) -> ResultadoTool:
    if sola:
        return ResultadoTool(False, error="una_accion_a_la_vez",
                             detalle="un borrado o un recuerdo se propone solo; propón lo demás después")
    return ResultadoTool(False, error="tope_propuestas_turno",
                         detalle=f"solo se pueden proponer {MAX_PROPUESTAS_TURNO} acciones por turno; "
                                 "propón las demás después")


async def _proponer(ctx, conector, acciones, auditoria, conversacion_id, c: LlamadaTool, config,
                    emit, memoria: Memoria | None = None, turno: TurnoMemoria | None = None,
                    destructiva: bool = False, con_web: bool = False,
                    inicio_turno: datetime | None = None, guardar: asyncio.Lock | None = None) -> ResultadoTool:
    """Una tool de escritura nunca se ejecuta aquí: se pide al sistema un resumen, se guarda como
    pendiente y se avisa al widget para que el usuario confirme. El modelo recibe «pendiente».
    Con `memoria` (tools locales `recordar` y `olvidar`) el resumen lo redacta el servidor, no el sistema."""
    local = memoria is not None
    inicio = time.monotonic()
    if acciones is None:
        r = ResultadoTool(False, error="no_disponible", detalle="las acciones no están habilitadas")
    elif con_web:
        r = ResultadoTool(False, error="escritura_tras_web",
                          detalle="no se puede proponer una escritura en un turno con contenido de la web")
    elif c.argumentos_invalidos:
        r = ResultadoTool(False, error="parametros_invalidos", detalle="los argumentos no son un objeto JSON")
    else:
        try:
            if local:
                p = await asyncio.wait_for(memoria.proponer(ctx, c.nombre, c.parametros, turno), config.timeout_tool_s)
            else:
                p = await asyncio.wait_for(conector.proponer(c.nombre, c.parametros), config.timeout_tool_s)
        except TimeoutError:
            r = ResultadoTool(False, error="timeout", detalle="el sistema tardó demasiado")
        except Exception:
            log.exception("[%s] el conector lanzó en la propuesta de %s", ctx.request_id, c.nombre)
            r = ResultadoTool(False, error="error_sistema", detalle="falla interna del conector")
        else:
            if not p.ok:
                r = ResultadoTool(False, error=p.error, detalle=p.detalle_error, status_http=p.status_http)
            elif destructiva and not p.lineas:
                # Sin el estado actual de la entidad el usuario confirmaría a ciegas.
                r = ResultadoTool(False, error="propuesta_sin_detalle",
                                  detalle="el sistema no informó qué se va a borrar")
            else:
                try:
                    guardados = p.parametros_finales if p.parametros_finales is not None else c.parametros
                    async with guardar or asyncio.Lock():
                        creada = await acciones.crear(ctx, conversacion_id, c.nombre, guardados, p,
                                                      destructiva=destructiva, inicio_turno=inicio_turno)
                except LimiteExcedido as e:
                    r = ResultadoTool(False, error=e.cual, detalle=(
                        "ya está propuesta en este turno" if e.cual == "propuesta_duplicada"
                        else "demasiadas propuestas; intenta más tarde"))
                except Exception:
                    log.exception("[%s] no se pudo guardar la propuesta de %s", ctx.request_id, c.nombre)
                    r = ResultadoTool(False, error="error_sistema", detalle="no se pudo preparar la acción")
                else:
                    tarjeta = {
                        "id": creada.id, "tool": c.nombre, "resumen": p.resumen,
                        "lineas": list(p.lineas), "huella": p.huella, "expira": creada.expira,
                    }
                    if destructiva:
                        tarjeta["destructiva"] = True
                    if local:
                        tarjeta["local"] = True  # el widget no pide token al anfitrión: confirma con su sesión
                    await emit(events.CONFIRMACION, tarjeta)
                    r = ResultadoTool(
                        True, {"estado": "pendiente_de_confirmacion", "resumen": p.resumen,
                               "instruccion": _PENDIENTE}, status_http=p.status_http)
    ms = int((time.monotonic() - inicio) * 1000)
    try:
        await auditoria.registrar_tool(ctx, conversacion_id, f"{c.nombre}#propuesta", c.parametros, r, ms)
    except Exception:
        log.exception("[%s] no se pudo auditar la propuesta de %s", ctx.request_id, c.nombre)
    return r
