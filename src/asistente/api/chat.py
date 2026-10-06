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
from asistente.core import events, zona
from asistente.core.agent import ConfigTurno, run_turn
from asistente.core.ports import Contexto, LimitesUso
from asistente.servicios import LLMNoConfigurado, Servicios

log = logging.getLogger(__name__)
router = APIRouter()


class ChatIn(BaseModel):
    conversacion_id: uuid.UUID | None = None
    mensaje: str
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


@router.post("/v1/chat")
async def chat(
    body: ChatIn,
    sesion: Sesion = Depends(sesion_actual),
    svc: Servicios = Depends(servicios),
) -> StreamingResponse:
    cfg = svc.settings
    texto = body.mensaje.strip()
    if not texto or len(texto) > cfg.max_mensaje_chars:
        raise ErrorApi(422, "mensaje_invalido")

    u, sistema = sesion.usuario, sesion.sistema
    try:
        llm, modelo = svc.llm_para(sistema)
    except LLMNoConfigurado as e:
        log.error("LLM sin configurar para %s: %s", sistema.id, e)
        raise ErrorApi(503, "llm_no_configurado") from e

    if body.conversacion_id is not None:
        # Ajena o inexistente: misma respuesta, para no revelar ids de otros.
        if not await svc.repo.existe(u.sistema_id, u.usuario_ref, body.conversacion_id):
            raise ErrorApi(404, "conversacion_no_encontrada")
        conv_id, nueva = body.conversacion_id, False
    else:
        conv_id, nueva = uuid.uuid4(), True

    request_id = uuid.uuid4().hex
    zona_usuario = zona.resolver(body.zona_horaria, sistema.zona_horaria)
    prompt, version = svc.prompts.componer(
        sistema_nombre=sistema.nombre, prompt_dominio=sistema.prompt_dominio,
        usuario_nombre=u.nombre, locale=u.locale, hoy=datetime.now(ZoneInfo(zona_usuario)).date(),
        canal=body.canal,
    )
    lim = sistema.limites
    ctx = Contexto(
        sistema_id=u.sistema_id, sistema_nombre=sistema.nombre, usuario_ref=u.usuario_ref,
        jti=u.jti, request_id=request_id, modelo=modelo, prompt_system=prompt, prompt_version=version,
        limites=LimitesUso(lim.mensajes_por_usuario_min, lim.mensajes_por_usuario_dia, lim.tokens_por_mes),
        zona_horaria=zona_usuario, retencion_dias=sistema.retencion_dias,
    )
    historial = [] if nueva else await svc.repo.historial(
        u.sistema_id, u.usuario_ref, conv_id, cfg.max_turnos_historial
    )
    config = ConfigTurno(max_iter=cfg.max_iter, max_output_tokens=cfg.max_output_tokens,
                         timeout_turno_s=cfg.timeout_turno_s, resumen_voz=body.canal == "voz")
    conector = svc.conector.para(u, request_id)

    cola: asyncio.Queue = asyncio.Queue()

    async def emit(evento: str, datos) -> None:
        await cola.put((evento, datos))

    async def turno() -> None:
        try:
            async def filtrado(evento: str, datos) -> None:
                if evento != events.DONE:  # `done` se emite recién cuando el turno está guardado
                    await emit(evento, datos)

            res = await run_turn(ctx, llm, conector, svc.auditoria, svc.limites, historial,
                                 texto, filtrado, conv_id, config, acciones=svc.acciones,
                                 recientes=svc.recientes if sistema.consultas_recientes else None)
            if res.completo:
                try:
                    await asyncio.shield(svc.repo.guardar_turno(
                        u.sistema_id, u.usuario_ref, conv_id, texto[:60], res.nuevos,
                        res.uso, modelo, version))
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


