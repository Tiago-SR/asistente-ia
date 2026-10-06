"""Auditoría de tools en `llamadas_tool`: metadatos, nunca el resultado."""

from datetime import UTC, datetime, timedelta
from typing import Any

from sqlalchemy import delete
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from asistente.core.ports import Contexto, ResultadoTool
from asistente.store.models import LlamadaTool


class AuditoriaSql:
    def __init__(self, sesiones: async_sessionmaker[AsyncSession]) -> None:
        self._sesiones = sesiones

    async def registrar_tool(
        self, ctx: Contexto, conversacion_id: Any, tool: str, parametros: dict,
        resultado: ResultadoTool, duracion_ms: int,
    ) -> None:
        async with self._sesiones.begin() as s:
            s.add(
                LlamadaTool(
                    conversacion_id=conversacion_id,
                    sistema_id=ctx.sistema_id,
                    usuario_ref=ctx.usuario_ref,
                    jti=ctx.jti,
                    tool=tool[:128],
                    parametros=parametros,
                    ok=resultado.ok,
                    error=(resultado.error or None) and resultado.error[:500],
                    status_http=resultado.status_http,
                    duracion_ms=duracion_ms,
                    bytes_respuesta=resultado.bytes_respuesta,
                    zona_horaria=ctx.zona_horaria[:64],
                )
            )

    async def purgar(self, sistema_id: str, retencion_dias: int, ahora: datetime | None = None) -> int:
        """Borra las llamadas más antiguas que la retención del sistema (los parámetros pueden traer
        datos de negocio)."""
        limite = (ahora or datetime.now(UTC)) - timedelta(days=retencion_dias)
        async with self._sesiones.begin() as s:
            r = await s.execute(
                delete(LlamadaTool).where(LlamadaTool.sistema_id == sistema_id, LlamadaTool.creada < limite)
            )
            return r.rowcount
