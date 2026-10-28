"""Registro de mensajes de los canales de mensajería (sin contenido)."""

from datetime import UTC, datetime, timedelta

from sqlalchemy import delete, func, or_, select, update
from sqlalchemy.dialects.postgresql import insert as pg_insert
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from asistente.store.models import CanalMensaje, CanalVinculo


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

    async def registrar_salida(self, sistema_id: str, mid: str, contacto: str, tipo: str) -> None:
        """Un mensaje que enviamos: su estado (sent, delivered, failed) llega después por el webhook."""
        async with self._sesiones.begin() as s:
            await s.execute(pg_insert(CanalMensaje).values(
                sistema_id=sistema_id, id=mid, contacto=contacto, direccion="salida", tipo=tipo, estado="enviado")
                .on_conflict_do_nothing())

    async def actualizar_estado(self, sistema_id: str, mid: str, estado: str, error: str | None = None) -> None:
        async with self._sesiones.begin() as s:
            await s.execute(update(CanalMensaje).where(
                CanalMensaje.sistema_id == sistema_id, CanalMensaje.id == mid).values(estado=estado, error=error))

    async def fallidos(self, sistema_id: str, desde: datetime, limite: int = 20) -> list[CanalMensaje]:
        """Salientes que el proveedor reportó como fallidos, del más nuevo al más viejo."""
        async with self._sesiones() as s:
            return list((await s.execute(select(CanalMensaje).where(
                CanalMensaje.sistema_id == sistema_id, CanalMensaje.direccion == "salida",
                CanalMensaje.estado == "fallido", CanalMensaje.creado_en >= desde)
                .order_by(CanalMensaje.creado_en.desc()).limit(limite))).scalars())

    async def purgar(self, dias: int) -> int:
        """Quita los registros viejos: la deduplicación solo necesita el plazo de reintento del proveedor."""
        async with self._sesiones.begin() as s:
            r = await s.execute(delete(CanalMensaje).where(CanalMensaje.creado_en < datetime.now(UTC) - timedelta(days=dias)))
            return r.rowcount


class VinculosCanal:
    """Qué contactos están vinculados en cada sistema. No es autoritativo (lo es el sistema anfitrión): evita
    consultarle por cada número desconocido y deja pasar solo a quien ya vinculó."""

    def __init__(self, sesiones: async_sessionmaker[AsyncSession]) -> None:
        self._sesiones = sesiones

    async def activo(self, sistema_id: str, contacto: str) -> bool:
        async with self._sesiones() as s:
            q = select(CanalVinculo.activo).where(
                CanalVinculo.sistema_id == sistema_id, CanalVinculo.contacto == contacto)
            return bool((await s.execute(q)).scalar())

    async def guardar(self, sistema_id: str, contacto: str) -> None:
        async with self._sesiones.begin() as s:
            await s.execute(pg_insert(CanalVinculo).values(sistema_id=sistema_id, contacto=contacto, activo=True)
                            .on_conflict_do_update(index_elements=["sistema_id", "contacto"],
                                                   set_={"activo": True, "ultimo_uso": func.now()}))

    async def listar(self, sistema_id: str) -> list[CanalVinculo]:
        async with self._sesiones() as s:
            return list((await s.execute(select(CanalVinculo).where(CanalVinculo.sistema_id == sistema_id)
                                         .order_by(CanalVinculo.ultimo_uso.desc()))).scalars())

    async def desactivar(self, sistema_id: str, contacto: str) -> None:
        await self._poner(sistema_id, contacto, activo=False)

    async def tocar(self, sistema_id: str, contacto: str) -> None:
        await self._poner(sistema_id, contacto, ultimo_uso=func.now())

    async def _poner(self, sistema_id: str, contacto: str, **valores) -> None:
        async with self._sesiones.begin() as s:
            await s.execute(update(CanalVinculo).where(
                CanalVinculo.sistema_id == sistema_id, CanalVinculo.contacto == contacto).values(**valores))

    async def purgar(self, sistema_id: str, retencion_dias: int, inactivo_dias: int = 30) -> int:
        """Sin uso en `retencion_dias` (o desactivados y sin uso en `inactivo_dias`): quien siga puede vincular de nuevo."""
        ahora = datetime.now(UTC)
        async with self._sesiones.begin() as s:
            r = await s.execute(delete(CanalVinculo).where(
                CanalVinculo.sistema_id == sistema_id,
                or_(CanalVinculo.ultimo_uso < ahora - timedelta(days=retencion_dias),
                    (CanalVinculo.activo.is_(False)) & (CanalVinculo.ultimo_uso < ahora - timedelta(days=inactivo_dias)))))
            return r.rowcount
