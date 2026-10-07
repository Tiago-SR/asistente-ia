"""Loop del agente.

`run_turn` no persiste: devuelve los mensajes nuevos y el llamador (API) los guarda
solo si el turno terminó bien. Así un turno cortado no deja historial a medias.
"""

import asyncio
import json
import logging
import time
from dataclasses import dataclass, field, replace
from typing import Any

from asistente.core import events
from asistente.core import memoria as memorias
from asistente.core import recientes as consultas
from asistente.core.llm.base import LlamadaTool, LLMError, Mensaje, Uso
from asistente.core.ports import (
    LLM,
    Acciones,
    Auditoria,
    Conector,
    Contexto,
    LimiteExcedido,
    Limites,
    Memoria,
    Recientes,
    ResultadoTool,
    TurnoMemoria,
)
from asistente.core.voz_resumen import FiltroVoz, limpiar

log = logging.getLogger(__name__)

# Descripción legible para el evento `tool`; sin parámetros, que pueden ser datos de negocio.
_LEGIBLE = "Consultando {nombre}"
_LEGIBLE_ACCION = "Preparando {nombre}"
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


@dataclass
class ResultadoTurno:
    motivo: str  # fin | error | token_expirado
    nuevos: list[Mensaje] = field(default_factory=list)
    texto: str = ""
    uso: Uso = field(default_factory=Uso)
    # Milisegundos desde que empezó el turno: primer texto (`primer_delta`), resumen hablado (`voz`) y fin (`total`).
    tiempos: dict[str, int] = field(default_factory=dict)

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
) -> ResultadoTurno:
    config = config or ConfigTurno()
    estado = ResultadoTurno("error")
    estado.tiempos["_t0"] = time.monotonic_ns() // 1_000_000
    try:
        await limites.reservar_mensaje(ctx)
    except LimiteExcedido as e:
        await emit(events.ERROR, e.cual)
        return estado
    try:
        async with asyncio.timeout(config.timeout_turno_s):
            await _loop(ctx, llm, conector, auditoria, limites, historial, texto, emit,
                        conversacion_id, config, estado, acciones, recientes, memoria)
    except TimeoutError:
        estado.motivo, estado.nuevos = "error", []
        await emit(events.ERROR, "timeout_turno")
    return estado


async def _loop(ctx, llm, conector, auditoria, limites, historial, texto, emit,
                conversacion_id, config, estado, acciones=None, recientes=None, memoria=None) -> None:
    tools = await conector.tools()
    escrituras = {t.nombre for t in tools if t.escritura}
    lectura = {t.nombre for t in tools if not t.escritura}
    if recientes is not None:
        tools = [*tools, consultas.TOOL]  # tool local del asistente: no existe en el sistema
    if memoria is not None:
        tools = [*tools, *memorias.TOOLS]  # `recordar` y `olvidar`: locales, siempre con botón
    propuesta_hecha = False  # una sola propuesta por turno
    reintento_vacio = False  # una respuesta vacía se pide de nuevo una vez
    nuevos = [Mensaje("user", texto)]
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
        estado.uso += resp.uso
        await limites.registrar_uso(ctx, resp.uso)
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
            (_LEGIBLE_ACCION if c.nombre in escrituras or (memoria is not None and c.nombre in memorias.NOMBRES)
             else _LEGIBLE).format(nombre=c.nombre)
            for c in llamadas
        ])
        atenciones = []
        for c in llamadas:
            local = memoria is not None and c.nombre in memorias.NOMBRES
            if c.nombre in escrituras or local:
                # Se decide antes de cualquier await: dos escrituras en la misma iteración no compiten.
                if propuesta_hecha:
                    atenciones.append(_rechazar_extra(c))
                    continue
                propuesta_hecha = True
                turno = TurnoMemoria(tuple(nuevos), frozenset(lectura), conector) if local else None
                atenciones.append(_proponer(ctx, conector, acciones, auditoria, conversacion_id,
                                            c, config, emit, memoria if local else None, turno))
            elif recientes is not None and c.nombre == consultas.NOMBRE:
                atenciones.append(_consultar_recientes(ctx, recientes, lectura, auditoria, conversacion_id, c))
            else:
                atenciones.append(_ejecutar(ctx, conector, auditoria, conversacion_id, c, sem, config))
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


async def _rechazar_extra(c: LlamadaTool) -> ResultadoTool:
    return ResultadoTool(False, error="una_accion_a_la_vez",
                         detalle="solo se puede proponer una acción por turno; propón la siguiente después")


async def _proponer(ctx, conector, acciones, auditoria, conversacion_id, c: LlamadaTool, config,
                    emit, memoria: Memoria | None = None, turno: TurnoMemoria | None = None) -> ResultadoTool:
    """Una tool de escritura nunca se ejecuta aquí: se pide al sistema un resumen, se guarda como
    pendiente y se avisa al widget para que el usuario confirme. El modelo recibe «pendiente».
    Con `memoria` (tools locales `recordar` y `olvidar`) el resumen lo redacta el servidor, no el sistema."""
    local = memoria is not None
    inicio = time.monotonic()
    if acciones is None:
        r = ResultadoTool(False, error="no_disponible", detalle="las acciones no están habilitadas")
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
            else:
                try:
                    guardados = p.parametros_finales if p.parametros_finales is not None else c.parametros
                    creada = await acciones.crear(ctx, conversacion_id, c.nombre, guardados, p)
                except LimiteExcedido as e:
                    r = ResultadoTool(False, error=e.cual, detalle="demasiadas propuestas; intenta más tarde")
                except Exception:
                    log.exception("[%s] no se pudo guardar la propuesta de %s", ctx.request_id, c.nombre)
                    r = ResultadoTool(False, error="error_sistema", detalle="no se pudo preparar la acción")
                else:
                    tarjeta = {
                        "id": creada.id, "tool": c.nombre, "resumen": p.resumen,
                        "lineas": list(p.lineas), "huella": p.huella, "expira": creada.expira,
                    }
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
