"""Archivos generados (Excel) en Postgres. TODA lectura filtra por `(sistema_id, usuario_ref)` y por vigencia: un
archivo ajeno, inexistente o vencido es indistinguible."""

import uuid
from datetime import UTC, datetime, timedelta
from typing import Any

from sqlalchemy import delete, func, select, text
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from asistente.core.ports import Contexto, LimiteExcedido
from asistente.store.models import Archivo


class ArchivosSql:
    def __init__(self, sesiones: async_sessionmaker[AsyncSession], ttl_horas: int, max_por_dia: int) -> None:
        self._sesiones = sesiones
        self._ttl = timedelta(hours=ttl_horas)
        self._max_por_dia = max_por_dia

    async def guardar(self, ctx: Contexto, conversacion_id: Any, nombre: str, datos: bytes, tipo_mime: str) -> str:
        ahora = datetime.now(UTC)
        async with self._sesiones.begin() as s:
            await s.execute(text("select pg_advisory_xact_lock(hashtextextended(:k, 0))"),
                            {"k": f"archivos:{ctx.sistema_id}:{ctx.usuario_ref}"})
            await s.execute(delete(Archivo).where(Archivo.expira_en < ahora))  # los vencidos no esperan a la purga
            hoy = (await s.execute(select(func.count()).select_from(Archivo).where(
                Archivo.sistema_id == ctx.sistema_id, Archivo.usuario_ref == ctx.usuario_ref,
                Archivo.creado > ahora - timedelta(hours=24)))).scalar_one()
            if hoy >= self._max_por_dia:
                raise LimiteExcedido("archivos_dia")
            fila = Archivo(sistema_id=ctx.sistema_id, usuario_ref=ctx.usuario_ref, conversacion_id=conversacion_id,
                           nombre=nombre[:120], tipo_mime=tipo_mime, bytes=len(datos), datos=datos,
                           creado=ahora, expira_en=ahora + self._ttl)
            s.add(fila)
            await s.flush()
            return str(fila.id)

    async def obtener(self, sistema_id: str, usuario_ref: str, archivo_id: uuid.UUID) -> Archivo | None:
        async with self._sesiones() as s:
            return (await s.execute(select(Archivo).where(
                Archivo.id == archivo_id, Archivo.sistema_id == sistema_id, Archivo.usuario_ref == usuario_ref,
                Archivo.expira_en > func.now()))).scalar_one_or_none()

    async def vigentes(self, sistema_id: str, usuario_ref: str, ids: list[uuid.UUID]) -> set[str]:
        if not ids:
            return set()
        async with self._sesiones() as s:
            filas = await s.execute(select(Archivo.id).where(
                Archivo.id.in_(ids), Archivo.sistema_id == sistema_id, Archivo.usuario_ref == usuario_ref,
                Archivo.expira_en > func.now()))
            return {str(i) for i in filas.scalars()}

    async def purgar(self) -> int:
        async with self._sesiones.begin() as s:
            return (await s.execute(delete(Archivo).where(Archivo.expira_en < func.now()))).rowcount
