"""Registro de mensajes de los canales de mensajería (sin contenido)."""

from sqlalchemy import update
from sqlalchemy.dialects.postgresql import insert as pg_insert
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from asistente.store.models import CanalMensaje


class MensajesCanal:
    def __init__(self, sesiones: async_sessionmaker[AsyncSession]) -> None:
        self._sesiones = sesiones

    async def registrar_entrada(self, sistema_id: str, mid: str, contacto: str, tipo: str) -> bool:
        """True si es nuevo; False si el proveedor lo reenvió (no se responde dos veces)."""
        async with self._sesiones.begin() as s:
            r = await s.execute(pg_insert(CanalMensaje).values(
                sistema_id=sistema_id, id=mid, contacto=contacto, direccion="entrada", tipo=tipo)
                .on_conflict_do_nothing())
            return r.rowcount == 1

    async def actualizar_estado(self, sistema_id: str, mid: str, estado: str) -> None:
        async with self._sesiones.begin() as s:
            await s.execute(update(CanalMensaje).where(
                CanalMensaje.sistema_id == sistema_id, CanalMensaje.id == mid).values(estado=estado))
