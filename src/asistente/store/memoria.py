"""Memoria por usuario (Fase 1). TODA consulta filtra por `(sistema_id, usuario_ref)`: un recuerdo ajeno es
indistinguible de uno inexistente. Lo vencido (sin uso en `dias_sin_uso` días) no se ve aunque la purga no haya
corrido."""

import uuid
from collections.abc import Callable
from datetime import UTC, datetime, timedelta
from typing import Any

from sqlalchemy import delete, func, select, text, update
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from asistente.core.memoria import MAX_RECUERDOS
from asistente.core.ports import Recuerdo, TopeMemoria
from asistente.store.models import MemoriaUsuario

# Una lectura renueva `ultimo_uso` a lo sumo una vez al día por recuerdo: no se escribe en cada turno.
RENOVAR_CADA = timedelta(days=1)


def _recuerdo(f: MemoriaUsuario) -> Recuerdo:
    return Recuerdo(str(f.id), f.tipo, f.clave, f.valor, f.creada, f.actualizada, f.ultimo_uso)


class MemoriaSql:
    def __init__(
        self,
        sesiones: async_sessionmaker[AsyncSession],
        dias_sin_uso: int = 30,
        reloj: Callable[[], datetime] = lambda: datetime.now(UTC),
    ) -> None:
        self._sesiones, self._dias, self._reloj = sesiones, dias_sin_uso, reloj

    def _vigente(self, ahora: datetime):
        return MemoriaUsuario.ultimo_uso >= ahora - timedelta(days=self._dias)

    @staticmethod
    def _de(sistema_id: str, usuario_ref: str):
        return MemoriaUsuario.sistema_id == sistema_id, MemoriaUsuario.usuario_ref == usuario_ref

    async def listar(self, sistema_id: str, usuario_ref: str, *, renovar: bool = False) -> list[Recuerdo]:
        ahora = self._reloj()
        async with self._sesiones.begin() as s:
            filas = (await s.execute(
                select(MemoriaUsuario)
                .where(*self._de(sistema_id, usuario_ref), self._vigente(ahora))
                .order_by(MemoriaUsuario.tipo, MemoriaUsuario.clave)
            )).scalars().all()
            if renovar:
                a_renovar = [f.id for f in filas if f.ultimo_uso < ahora - RENOVAR_CADA]
                if a_renovar:
                    await s.execute(
                        update(MemoriaUsuario)
                        .where(*self._de(sistema_id, usuario_ref), MemoriaUsuario.id.in_(a_renovar))
                        .values(ultimo_uso=ahora)
                    )
            return [_recuerdo(f) for f in filas]

    async def obtener(self, sistema_id: str, usuario_ref: str, tipo: str, clave: str) -> Recuerdo | None:
        ahora = self._reloj()
        async with self._sesiones() as s:
            f = (await s.execute(
                select(MemoriaUsuario).where(
                    *self._de(sistema_id, usuario_ref), MemoriaUsuario.tipo == tipo,
                    MemoriaUsuario.clave == clave, self._vigente(ahora))
            )).scalar_one_or_none()
            return _recuerdo(f) if f else None

    async def contar(self, sistema_id: str, usuario_ref: str) -> int:
        ahora = self._reloj()
        async with self._sesiones() as s:
            return (await s.execute(
                select(func.count()).select_from(MemoriaUsuario)
                .where(*self._de(sistema_id, usuario_ref), self._vigente(ahora))
            )).scalar_one()

    async def guardar(self, sistema_id: str, usuario_ref: str, tipo: str, clave: str, valor: Any) -> Recuerdo:
        """Crea o reemplaza (misma clave). El tope se comprueba bajo un lock por usuario: dos confirmaciones
        simultáneas no lo superan."""
        ahora = self._reloj()
        async with self._sesiones.begin() as s:
            await s.execute(
                text("select pg_advisory_xact_lock(hashtextextended(:k, 0))"),
                {"k": f"memoria:{sistema_id}:{usuario_ref}"},
            )
            f = (await s.execute(
                select(MemoriaUsuario).where(
                    *self._de(sistema_id, usuario_ref), MemoriaUsuario.tipo == tipo, MemoriaUsuario.clave == clave)
            )).scalar_one_or_none()
            if f is not None:  # incluso si estaba vencida: se reutiliza la fila
                f.valor, f.actualizada, f.ultimo_uso = valor, ahora, ahora
            else:
                hay = (await s.execute(
                    select(func.count()).select_from(MemoriaUsuario)
                    .where(*self._de(sistema_id, usuario_ref), self._vigente(ahora))
                )).scalar_one()
                if hay >= MAX_RECUERDOS:
                    raise TopeMemoria
                f = MemoriaUsuario(id=uuid.uuid4(), sistema_id=sistema_id, usuario_ref=usuario_ref, tipo=tipo,
                                   clave=clave, valor=valor, creada=ahora, actualizada=ahora, ultimo_uso=ahora)
                s.add(f)
            return _recuerdo(f)

    async def borrar_clave(self, sistema_id: str, usuario_ref: str, tipo: str, clave: str) -> bool:
        async with self._sesiones.begin() as s:
            r = await s.execute(delete(MemoriaUsuario).where(
                *self._de(sistema_id, usuario_ref), MemoriaUsuario.tipo == tipo, MemoriaUsuario.clave == clave))
            return r.rowcount > 0

    async def borrar(self, sistema_id: str, usuario_ref: str, recuerdo_id: uuid.UUID) -> bool:
        async with self._sesiones.begin() as s:
            r = await s.execute(delete(MemoriaUsuario).where(
                *self._de(sistema_id, usuario_ref), MemoriaUsuario.id == recuerdo_id))
            return r.rowcount > 0

    async def borrar_todo(self, sistema_id: str, usuario_ref: str) -> int:
        async with self._sesiones.begin() as s:
            r = await s.execute(delete(MemoriaUsuario).where(*self._de(sistema_id, usuario_ref)))
            return r.rowcount

    async def purgar(self, sistema_id: str, ahora: datetime | None = None) -> int:
        """Borra los recuerdos sin uso en `dias_sin_uso` días (también los de un sistema con la memoria apagada)."""
        limite = (ahora or self._reloj()) - timedelta(days=self._dias)
        async with self._sesiones.begin() as s:
            r = await s.execute(delete(MemoriaUsuario).where(
                MemoriaUsuario.sistema_id == sistema_id, MemoriaUsuario.ultimo_uso < limite))
            return r.rowcount
