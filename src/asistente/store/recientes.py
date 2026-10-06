"""Consultas recientes del usuario, leídas de la auditoría (`llamadas_tool`): tool y parámetros, nunca
resultados. TODA consulta filtra por `(sistema_id, usuario_ref)`."""

import json
from collections.abc import Collection
from datetime import datetime

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from asistente.core.ports import ConsultaPrevia, Contexto
from asistente.store.models import LlamadaTool

# Filas que se leen antes de agrupar: acota el trabajo de un usuario muy activo.
MAX_FILAS = 500


class RecientesSql:
    def __init__(self, sesiones: async_sessionmaker[AsyncSession]) -> None:
        self._sesiones = sesiones

    async def consultas(
        self, ctx: Contexto, tools: Collection[str], desde: datetime, limite: int
    ) -> list[ConsultaPrevia]:
        if not tools:
            return []
        async with self._sesiones() as s:
            filas = (await s.execute(
                select(LlamadaTool)
                .where(LlamadaTool.sistema_id == ctx.sistema_id, LlamadaTool.usuario_ref == ctx.usuario_ref,
                       LlamadaTool.ok.is_(True), LlamadaTool.tool.in_(tools), LlamadaTool.creada >= desde)
                .order_by(LlamadaTool.creada.desc(), LlamadaTool.id.desc())
                .limit(MAX_FILAS)
            )).scalars().all()
        # La primera de cada grupo es la más reciente: de ella salen la hora y la zona.
        grupos: dict[tuple[str, str], list] = {}
        for f in filas:
            parametros = f.parametros or {}
            clave = (f.tool, json.dumps(parametros, sort_keys=True, ensure_ascii=False))
            grupo = grupos.setdefault(clave, [f, parametros, 0])
            grupo[2] += 1
        return [
            ConsultaPrevia(f.tool, parametros, f.creada, veces, f.zona_horaria)
            for f, parametros, veces in list(grupos.values())[:limite]
        ]
