"""Acciones pendientes de confirmación (Fase 5). TODA consulta filtra por `(sistema_id, usuario_ref)`:
una acción ajena es indistinguible de una inexistente.

Las transiciones de estado son un único UPDATE condicional, así dos confirmaciones concurrentes
(doble clic, dos pestañas) nunca ejecutan dos veces.
"""

import uuid
from collections.abc import Callable
from datetime import UTC, datetime, timedelta
from typing import Any

from sqlalchemy import delete, func, select, update
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from asistente.core.ports import AccionCreada, Contexto, LimiteExcedido, ResultadoPropuesta
from asistente.store.models import Accion

MAX_PROPUESTAS_POR_HORA = 20
TTL_DESTRUCTIVA_S = 60  # una destructiva se decide ya: no queda esperando en pantalla


class AccionesSql:
    def __init__(
        self,
        sesiones: async_sessionmaker[AsyncSession],
        max_por_hora: int = MAX_PROPUESTAS_POR_HORA,
        reloj: Callable[[], datetime] = lambda: datetime.now(UTC),
    ) -> None:
        self._sesiones, self._max_por_hora, self._reloj = sesiones, max_por_hora, reloj

    @staticmethod
    def _propia(sistema_id: str, usuario_ref: str, accion_id: uuid.UUID):
        return (
            Accion.id == accion_id,
            Accion.sistema_id == sistema_id,
            Accion.usuario_ref == usuario_ref,
        )

    async def crear(
        self, ctx: Contexto, conversacion_id: Any, tool: str, parametros: dict,
        propuesta: ResultadoPropuesta, *, destructiva: bool = False,
        inicio_turno: datetime | None = None,
    ) -> AccionCreada:
        ahora = self._reloj()
        async with self._sesiones.begin() as s:
            ultima_hora = (Accion.sistema_id == ctx.sistema_id, Accion.usuario_ref == ctx.usuario_ref,
                           Accion.creada > ahora - timedelta(hours=1))
            recientes = (await s.execute(select(func.count()).select_from(Accion).where(*ultima_hora))).scalar_one()
            if recientes >= self._max_por_hora:
                raise LimiteExcedido("acciones_hora")
            if destructiva:
                n = (await s.execute(select(func.count()).select_from(Accion).where(
                    *ultima_hora, Accion.destructiva.is_(True)))).scalar_one()
                if n >= ctx.limites.destructivas_por_hora:
                    raise LimiteExcedido("destructivas_hora")
            de_conversacion = (Accion.sistema_id == ctx.sistema_id, Accion.usuario_ref == ctx.usuario_ref,
                               Accion.conversacion_id == conversacion_id, Accion.estado == "pendiente")
            if inicio_turno is not None:
                # La misma propuesta dos veces en el turno se ejecutaría dos veces en el anfitrión.
                igual = (await s.execute(select(func.count()).select_from(Accion).where(
                    *de_conversacion, Accion.creada >= inicio_turno, Accion.tool == tool[:64],
                    Accion.huella == propuesta.huella))).scalar_one()
                if igual:
                    raise LimiteExcedido("propuesta_duplicada")
            # La tanda de un turno nuevo reemplaza a la anterior; las hermanas del mismo turno conviven.
            # shortcut: el agente serializa las `crear` de un turno; dos pestañas a la vez aún pueden pasar el tope por 1.
            await s.execute(
                update(Accion)
                .where(*de_conversacion, *((Accion.creada < inicio_turno,) if inicio_turno is not None else ()))
                .values(estado="reemplazada", decidida=ahora)
            )
            fila = Accion(
                id=uuid.uuid4(), sistema_id=ctx.sistema_id, usuario_ref=ctx.usuario_ref,
                conversacion_id=conversacion_id, tool=tool[:64], parametros=parametros,
                huella=propuesta.huella, resumen=propuesta.resumen, lineas=list(propuesta.lineas),
                estado="pendiente", creada=ahora, destructiva=destructiva,
                expira=ahora + timedelta(seconds=min(propuesta.expira_s, TTL_DESTRUCTIVA_S)
                                         if destructiva else propuesta.expira_s),
            )
            s.add(fila)
        return AccionCreada(str(fila.id), fila.expira.isoformat())

    async def obtener(self, sistema_id: str, usuario_ref: str, accion_id: uuid.UUID) -> Accion | None:
        """La acción, con el vencimiento ya aplicado (una pendiente vencida figura como `expirada`)."""
        ahora = self._reloj()
        async with self._sesiones.begin() as s:
            await s.execute(
                update(Accion)
                .where(*self._propia(sistema_id, usuario_ref, accion_id),
                       Accion.estado == "pendiente", Accion.expira <= ahora)
                .values(estado="expirada", decidida=ahora)
            )
            return (await s.execute(
                select(Accion).where(*self._propia(sistema_id, usuario_ref, accion_id))
            )).scalar_one_or_none()

    async def pendientes_de(
        self, sistema_id: str, usuario_ref: str, conversacion_id: uuid.UUID
    ) -> list[Accion]:
        """Las acciones pendientes y vigentes de la conversación, de la más antigua a la más reciente
        (para restaurar las tarjetas al recargar)."""
        ahora = self._reloj()
        async with self._sesiones.begin() as s:
            return list((await s.execute(
                select(Accion)
                .where(Accion.sistema_id == sistema_id, Accion.usuario_ref == usuario_ref,
                       Accion.conversacion_id == conversacion_id, Accion.estado == "pendiente",
                       Accion.expira > ahora)
                .order_by(Accion.creada.asc())
            )).scalars())

    async def reclamar(
        self, sistema_id: str, usuario_ref: str, accion_id: uuid.UUID, jti: str
    ) -> Accion | None:
        """pendiente → confirmada, de forma atómica. `None` si no estaba pendiente y vigente:
        solo el primer llamador gana."""
        ahora = self._reloj()
        async with self._sesiones.begin() as s:
            return (await s.execute(
                update(Accion)
                .where(*self._propia(sistema_id, usuario_ref, accion_id),
                       Accion.estado == "pendiente", Accion.expira > ahora)
                .values(estado="confirmada", decidida=ahora, jti_confirmacion=jti[:128])
                .returning(Accion)
            )).scalar_one_or_none()

    async def cancelar(self, sistema_id: str, usuario_ref: str, accion_id: uuid.UUID) -> bool:
        ahora = self._reloj()
        async with self._sesiones.begin() as s:
            r = await s.execute(
                update(Accion)
                .where(*self._propia(sistema_id, usuario_ref, accion_id),
                       Accion.estado == "pendiente", Accion.expira > ahora)
                .values(estado="cancelada", decidida=ahora)
            )
            return r.rowcount > 0

    async def finalizar(
        self, accion_id: uuid.UUID, *, ok: bool, error: str | None, status_http: int | None
    ) -> None:
        async with self._sesiones.begin() as s:
            await s.execute(
                update(Accion)
                .where(Accion.id == accion_id, Accion.estado == "confirmada")
                .values(estado="ejecutada" if ok else "fallida", ok=ok,
                        error=(error or None) and error[:500], status_http=status_http)
            )

    async def purgar(self, sistema_id: str, retencion_dias: int, ahora: datetime | None = None) -> int:
        limite = (ahora or self._reloj()) - timedelta(days=retencion_dias)
        async with self._sesiones.begin() as s:
            r = await s.execute(
                delete(Accion).where(Accion.sistema_id == sistema_id, Accion.creada < limite)
            )
            return r.rowcount
