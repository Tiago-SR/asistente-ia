"""POST /v1/chat: respuesta SSE. El turno corre en una tarea aparte y se
cancela si el cliente corta."""

import asyncio
import json
import logging
import uuid
from datetime import datetime
from typing import Literal
from zoneinfo import ZoneInfo

from fastapi import APIRouter, Depends
from fastapi.responses import StreamingResponse
from pydantic import BaseModel

from asistente.api.deps import Sesion, servicios, sesion_actual
from asistente.api.errores import ErrorApi
from asistente.core import adjuntos as adj
from asistente.core import events, zona
from asistente.core.agent import ConfigTurno, reservar_cuota, run_turn
from asistente.core.llm.base import Uso
from asistente.core.memoria import ServicioMemoria
from asistente.core.ports import Contexto, EventoMetrica, LimitesUso
from asistente.servicios import LLMNoConfigurado, Servicios

log = logging.getLogger(__name__)
router = APIRouter()


class ImagenIn(BaseModel):
    tipo: str  # image/jpeg | image/png
    datos: str  # base64 estricto, sin prefijo `data:`


class ChatIn(BaseModel):
    conversacion_id: uuid.UUID | None = None
    mensaje: str = ""
    # Imágenes de referencia (solo si `GET /v1/estado` informa `imagenes`). Viajan en el turno y no se guardan.
    imagenes: list[ImagenIn] = []
    # «voz»: el modelo agrega un resumen hablado (evento `voz`); la respuesta completa no cambia.
    canal: Literal["texto", "voz"] = "texto"
    # Zona del navegador (IANA). Opcional y nunca bloquea: una inválida se ignora y rige la del sistema, luego UTC.
    zona_horaria: str | None = None


def _frame(evento: str, datos) -> bytes:
    cuerpo = {
        events.DELTA: lambda d: {"texto": d},
        events.TOOL: lambda d: {"herramientas": d},
        events.UI: lambda d: {"acciones": d},
        events.VOZ: lambda d: {"texto": d},
        events.ERROR: lambda d: {"codigo": d},
    }.get(evento, lambda d: d or {})(datos)
    return f"event: {evento}\ndata: {json.dumps(cuerpo, ensure_ascii=False)}\n\n".encode()


async def armar_turno(svc: Servicios, sistema, u, modelo: str, request_id: str, *,
                      canal: Literal["texto", "voz", "whatsapp"] = "texto", zona_cliente: str | None = None):
    """Lo común a todo turno (chat web y canales de mensajería): zona, memoria, prompt, contexto y config.
    Devuelve (ctx, config, memoria, web, excel, version del prompt)."""
    cfg = svc.settings
    zona_usuario = zona.resolver(zona_cliente, sistema.zona_horaria)
    # Memoria por usuario: solo con el flag del sistema. Un fallo al leerla no tumba el chat.
    memoria, recuerdos = None, []
    if sistema.memoria_habilitada and svc.memoria is not None:
        memoria = ServicioMemoria(svc.memoria)
        try:
            recuerdos = await svc.memoria.listar(u.sistema_id, u.usuario_ref, renovar=True)
        except Exception:
            log.exception("[%s] no se pudo leer la memoria del usuario", request_id)
    web = svc.web if sistema.busqueda_web else None
    excel = sistema.exportar_excel and svc.archivos is not None
    prompt, version = svc.prompts.componer(
        sistema_nombre=sistema.nombre, prompt_dominio=sistema.prompt_dominio,
        usuario_nombre=u.nombre, locale=u.locale, hoy=datetime.now(ZoneInfo(zona_usuario)).date(),
        canal=canal, memoria=recuerdos, web=web is not None,
        leer_imagenes=sistema.leer_imagenes, excel=excel,
    )
    lim = sistema.limites
    ctx = Contexto(
        sistema_id=u.sistema_id, sistema_nombre=sistema.nombre, usuario_ref=u.usuario_ref,
        jti=u.jti, request_id=request_id, modelo=modelo, prompt_system=prompt, prompt_version=version,
        limites=LimitesUso(lim.mensajes_por_usuario_min, lim.mensajes_por_usuario_dia, lim.tokens_por_mes,
                           lim.destructivas_por_usuario_hora),
        zona_horaria=zona_usuario, retencion_dias=sistema.retencion_dias, locale=u.locale,
    )
    config = ConfigTurno(max_iter=cfg.max_iter, max_output_tokens=cfg.max_output_tokens,
                         timeout_turno_s=cfg.timeout_turno_s, resumen_voz=canal == "voz",
                         web_max_por_min=cfg.web_max_por_min, web_max_por_dia=cfg.web_max_por_dia,
                         web_max_por_dia_sistema=cfg.web_max_por_dia_sistema,
                         web_max_pagina_chars=cfg.web_max_pagina_chars, web_max_por_turno=cfg.web_max_por_turno,
                         excel_max_filas=cfg.excel_max_filas, excel_max_columnas=cfg.excel_max_columnas,
                         excel_max_kb=cfg.excel_max_kb)
    return ctx, config, memoria, web, excel, version


@router.post("/v1/chat")
async def chat(
    body: ChatIn,
    sesion: Sesion = Depends(sesion_actual),
    svc: Servicios = Depends(servicios),
) -> StreamingResponse:
    cfg = svc.settings
    texto = body.mensaje.strip()
    if (not texto and not body.imagenes) or len(texto) > cfg.max_mensaje_chars:
        raise ErrorApi(422, "mensaje_invalido")

    u, sistema = sesion.usuario, sesion.sistema
    try:
        llm, modelo = svc.llm_para(sistema)
    except LLMNoConfigurado as e:
        log.error("LLM sin configurar para %s: %s", sistema.id, e)
        raise ErrorApi(503, "llm_no_configurado") from e

    adjuntos: tuple = ()
    if body.imagenes:
        if not (llm.capacidades.soporta_imagenes and sistema.adjuntos.habilitado):
            raise ErrorApi(422, "imagenes_no_soportadas")
        try:
            adjuntos = adj.decodificar([(i.tipo, i.datos) for i in body.imagenes],
                                       max_imagenes=min(sistema.adjuntos.max_archivos or cfg.max_imagenes, cfg.max_imagenes),
                                       max_bytes=min(sistema.adjuntos.max_kb or cfg.max_imagen_kb, cfg.max_imagen_kb) * 1024)
        except adj.AdjuntoInvalido as e:
            if svc.metricas is not None:
                svc.metricas.registrar(EventoMetrica(sistema_id=u.sistema_id, usuario_ref=u.usuario_ref,
                                                     tipo="llm", resultado="limite", motivo=e.codigo, modelo=modelo))
            raise ErrorApi(413 if e.codigo == "imagen_demasiado_grande" else 422, e.codigo) from e

    if body.conversacion_id is not None:
        # Ajena o inexistente: misma respuesta, para no revelar ids de otros.
        if not await svc.repo.existe(u.sistema_id, u.usuario_ref, body.conversacion_id):
            raise ErrorApi(404, "conversacion_no_encontrada")
        conv_id, nueva = body.conversacion_id, False
    else:
        conv_id, nueva = uuid.uuid4(), True

    request_id = uuid.uuid4().hex
    ctx, config, memoria, web, excel, version = await armar_turno(
        svc, sistema, u, modelo, request_id, canal=body.canal, zona_cliente=body.zona_horaria)
    historial = [] if nueva else await svc.repo.historial(
        u.sistema_id, u.usuario_ref, conv_id, cfg.max_turnos_historial
    )
    conector = svc.conector.para(u, request_id)

    cola: asyncio.Queue = asyncio.Queue()

    async def emit(evento: str, datos) -> None:
        await cola.put((evento, datos))

    # Con `leer_imagenes`, el texto de la imagen se lee en paralelo al turno (llamada aparte, sin tools) y se guarda
    # junto al mensaje: así los turnos siguientes pueden usarlo sin reenviar la imagen.
    lectura: asyncio.Task | None = None  # se lanza tras reservar la cuota: leer la imagen es lo caro

    generados: list[dict] = []  # tarjetas de descarga del turno: se guardan en el mensaje final para rehidratarlas

    async def turno() -> None:
        nonlocal lectura
        try:
            if limite := await reservar_cuota(ctx, svc.limites, svc.metricas):
                await emit(events.ERROR, limite)
                return
            if adjuntos and sistema.leer_imagenes:
                lectura = asyncio.create_task(adj.leer(llm, modelo, adjuntos, cfg.max_output_tokens))

            async def filtrado(evento: str, datos) -> None:
                if evento == events.UI:
                    generados.extend({"id": a["id"], "nombre": a["nombre"]} for a in datos if a.get("tipo") == "descarga")
                if evento != events.DONE:  # `done` se emite recién cuando el turno está guardado
                    await emit(evento, datos)

            res = await run_turn(ctx, llm, conector, svc.auditoria, svc.limites, historial,
                                 texto, filtrado, conv_id, config, acciones=svc.acciones,
                                 recientes=svc.recientes if sistema.consultas_recientes else None,
                                 memoria=memoria, adjuntos=adjuntos, web=web, metricas=svc.metricas,
                                 excel=svc.archivos if excel else None, reservar=False)
            if res.completo:
                try:
                    leidos, uso_lectura = await lectura if lectura else ([], Uso())
                    # la imagen no se guarda: queda la marca, la metadata y, si se leyó, su texto (core/adjuntos.py)
                    nuevos = [await adj.para_guardar(m, svc.adjuntos, u.sistema_id, u.usuario_ref, leidos)
                              for m in res.nuevos]
                    await asyncio.shield(svc.repo.guardar_turno(
                        u.sistema_id, u.usuario_ref, conv_id, (texto or "Imagen")[:60], nuevos,
                        res.uso + uso_lectura, modelo, version, generados))
                except Exception:
                    log.exception("[%s] no se pudo guardar el turno", request_id)
                    await emit(events.ERROR, "no_se_pudo_guardar")
                else:
                    tiempos = {k: v for k, v in res.tiempos.items() if not k.startswith("_")}
                    log.info("[%s] turno canal=%s tiempos_ms=%s", request_id, body.canal, tiempos)
                    await emit(events.DONE, {
                        "conversacion_id": str(conv_id),
                        "tiempos_ms": tiempos,
                        "uso": {"tokens_in": res.uso.tokens_in, "tokens_out": res.uso.tokens_out,
                                "tokens_in_cache": res.uso.tokens_in_cache},
                    })
        except Exception:
            log.exception("[%s] error inesperado en el turno", request_id)
            await emit(events.ERROR, "error_interno")
        finally:
            if lectura and not lectura.done():  # turno cortado o fallido: no se sigue gastando en leer la imagen
                lectura.cancel()
            await cola.put(None)

    async def flujo():
        tarea = asyncio.create_task(turno())
        try:
            while True:
                try:
                    item = await asyncio.wait_for(cola.get(), cfg.heartbeat_s)
                except TimeoutError:
                    yield b": ping\n\n"
                    continue
                if item is None:
                    return
                yield _frame(*item)
        finally:
            if not tarea.done():  # el cliente cortó: se cancela y el turno no se guarda
                tarea.cancel()

    return StreamingResponse(
        flujo(), media_type="text/event-stream",
        headers={"Cache-Control": "no-cache", "X-Accel-Buffering": "no"},
    )


