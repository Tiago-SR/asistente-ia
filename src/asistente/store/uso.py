"""Lectura del consumo por sistema, mes y modelo (tabla `uso_modelo`)."""

from datetime import datetime

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from asistente.store.models import UsoModelo


async def consumo_del_mes(sesiones: async_sessionmaker[AsyncSession], mes: datetime) -> list[UsoModelo]:
    """Filas de un mes (`mes` = primer instante del mes en UTC), ordenadas por sistema y modelo."""
    async with sesiones() as s:
        stmt = select(UsoModelo).where(UsoModelo.mes == mes).order_by(UsoModelo.sistema_id, UsoModelo.modelo)
        return list((await s.execute(stmt)).scalars())
