"""Loop del agente (sección 7.4 del plan).

`run_turn` no persiste: devuelve los mensajes nuevos y el llamador (API) los guarda
solo si el turno terminó bien. Así un turno cortado no deja historial a medias.
"""

import asyncio
import json
import logging
import time
from dataclasses import dataclass, field
from typing import Any

from asistente.core import events
from asistente.core.llm.base import LlamadaTool, LLMError, Mensaje, Uso
from asistente.core.ports import (
    LLM,
    Auditoria,
    Conector,
    Contexto,
    LimiteExcedido,
    Limites,
    ResultadoTool,
)

log = logging.getLogger(__name__)

# Descripción legible para el evento `tool`; sin parámetros, que pueden ser datos de negocio.
_LEGIBLE = "Consultando {nombre}"


@dataclass(frozen=True)
class ConfigTurno:
    max_iter: int = 8
    max_output_tokens: int = 1500
    # Debe ser menor que la vida del token del usuario (sección 7.4).
    timeout_turno_s: float = 120.0
    timeout_tool_s: float = 30.0
    max_tools_concurrentes: int = 4
    max_llamadas_por_iteracion: int = 8


@dataclass
class ResultadoTurno:
    motivo: str  # fin | error | token_expirado
    nuevos: list[Mensaje] = field(default_factory=list)
    texto: str = ""
    uso: Uso = field(default_factory=Uso)

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
) -> ResultadoTurno:
    config = config or ConfigTurno()
    estado = ResultadoTurno("error")
    try:
        await limites.reservar_mensaje(ctx)
    except LimiteExcedido as e:
        await emit(events.ERROR, e.cual)
        return estado
    try:
        async with asyncio.timeout(config.timeout_turno_s):
            await _loop(ctx, llm, conector, auditoria, limites, historial, texto, emit,
                        conversacion_id, config, estado)
    except TimeoutError:
        estado.motivo, estado.nuevos = "error", []
        await emit(events.ERROR, "timeout_turno")
    return estado


async def _loop(ctx, llm, conector, auditoria, limites, historial, texto, emit,
                conversacion_id, config, estado) -> None:
    tools = await conector.tools()
    nuevos = [Mensaje("user", texto)]
    usar_paralelas = llm.capacidades.soporta_tools_paralelas
    sem = asyncio.Semaphore(config.max_tools_concurrentes if usar_paralelas else 1)

    async def delta(t: str) -> None:
        await emit(events.DELTA, t)

    for _ in range(config.max_iter):
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

        if resp.motivo_fin != "tool":
            nuevos.append(resp.como_mensaje())
            estado.motivo, estado.nuevos, estado.texto = "fin", nuevos, resp.texto
            await emit(events.DONE, {"conversacion_id": conversacion_id})
            return

        llamadas = resp.llamadas[: config.max_llamadas_por_iteracion]
        # Se reenvía solo lo atendido: todo tool_call enviado debe tener su resultado.
        nuevos.append(Mensaje("assistant", resp.texto, llamadas))
        await emit(events.TOOL, [_LEGIBLE.format(nombre=c.nombre) for c in llamadas])
        resultados = await asyncio.gather(
            *(_ejecutar(ctx, conector, auditoria, conversacion_id, c, sem, config) for c in llamadas)
        )
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
