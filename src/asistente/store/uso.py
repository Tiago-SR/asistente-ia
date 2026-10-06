"""Consumo por sistema y mes: del LLM por modelo (`uso_modelo`) y de la voz del servidor (`uso_voz`)."""

from datetime import UTC, datetime

from sqlalchemy import select
from sqlalchemy.dialects.postgresql import insert
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from asistente.store.models import UsoModelo, UsoVoz


async def consumo_del_mes(sesiones: async_sessionmaker[AsyncSession], mes: datetime) -> list[UsoModelo]:
    """Filas de un mes (`mes` = primer instante del mes en UTC), ordenadas por sistema y modelo."""
    async with sesiones() as s:
        stmt = select(UsoModelo).where(UsoModelo.mes == mes).order_by(UsoModelo.sistema_id, UsoModelo.modelo)
        return list((await s.execute(stmt)).scalars())


async def consumo_voz_del_mes(sesiones: async_sessionmaker[AsyncSession], mes: datetime) -> list[UsoVoz]:
    """Filas de voz de un mes (`mes` = primer instante del mes en UTC), ordenadas por sistema y motor."""
    async with sesiones() as s:
        stmt = select(UsoVoz).where(UsoVoz.mes == mes).order_by(UsoVoz.sistema_id, UsoVoz.proveedor, UsoVoz.modelo)
        return list((await s.execute(stmt)).scalars())


async def sumar_uso_voz(
    sesiones: async_sessionmaker[AsyncSession], sistema_id: str, proveedor: str, modelo: str, caracteres: int,
    ahora: datetime | None = None,
) -> None:
    """Suma una síntesis (una llamada y sus caracteres) al mes en curso. Solo cuenta números: nunca el texto."""
    ahora = ahora or datetime.now(UTC)
    mes = ahora.replace(day=1, hour=0, minute=0, second=0, microsecond=0)
    stmt = insert(UsoVoz).values(sistema_id=sistema_id, mes=mes, proveedor=proveedor, modelo=modelo,
                                 llamadas=1, caracteres=caracteres)
    async with sesiones.begin() as s:
        await s.execute(stmt.on_conflict_do_update(
            index_elements=["sistema_id", "mes", "proveedor", "modelo"],
            set_={"llamadas": UsoVoz.llamadas + 1, "caracteres": UsoVoz.caracteres + caracteres},
        ))
