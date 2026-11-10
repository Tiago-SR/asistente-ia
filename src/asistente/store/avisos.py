"""Avisos salientes del sistema anfitrión: cola durable con idempotencia por `(sistema_id, id_evento)`.

Estados: `pendiente → enviando → enviado | fallido | incierto`. `enviando` se marca justo antes de llamar al canal, así que
un `enviando` con el lease vencido (el proceso murió) pudo haber salido: pasa a `incierto`, nunca se reintenta.
`enviado_en` es la hora del intento de envío (se pone al reclamar): de ahí salen el espaciado y los topes de 24 h."""

from datetime import UTC, datetime, timedelta

from sqlalchemy import delete, func, select, text, update
from sqlalchemy.dialects.postgresql import distinct_on
from sqlalchemy.dialects.postgresql import insert as pg_insert
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from asistente.store.models import Aviso

_CONSUMEN = ("enviando", "enviado", "incierto")  # los que cuentan para el espaciado y los topes
ERROR_MAX = 200


class AvisosSql:
    def __init__(self, sesiones: async_sessionmaker[AsyncSession]) -> None:
        self._sesiones = sesiones

    async def crear(self, valores: dict) -> tuple[Aviso, bool]:
        """`(aviso, nuevo)`. Si el `id_evento` ya existía devuelve el guardado (el llamador compara el hash)."""
        async with self._sesiones.begin() as s:
            fila = (await s.execute(pg_insert(Aviso).values(**valores).on_conflict_do_nothing(
                index_elements=["sistema_id", "id_evento"]).returning(Aviso))).scalar_one_or_none()
            if fila is not None:
                return fila, True
            existente = (await s.execute(select(Aviso).where(
                Aviso.sistema_id == valores["sistema_id"], Aviso.id_evento == valores["id_evento"]))).scalar_one()
            return existente, False

    async def obtener(self, sistema_id: str, id_evento: str) -> Aviso | None:
        async with self._sesiones() as s:
            return (await s.execute(select(Aviso).where(
                Aviso.sistema_id == sistema_id, Aviso.id_evento == id_evento))).scalar_one_or_none()

    async def pendientes_de(self, sistema_id: str, wa_id: str) -> int:
        async with self._sesiones() as s:
            return (await s.execute(select(func.count()).where(
                Aviso.sistema_id == sistema_id, Aviso.wa_id == wa_id,
                Aviso.estado.in_(("pendiente", "enviando"))))).scalar_one()

    # --- worker ---

    async def recuperar(self) -> int:
        """Los `enviando` con el lease vencido pasan a `incierto` (pudieron salir), y los `pendiente` que ya caducaron
        a `fallido`. Idempotente: lo puede correr cualquier réplica."""
        async with self._sesiones.begin() as s:
            r = await s.execute(update(Aviso).where(Aviso.estado == "enviando", Aviso.lease_hasta < func.now())
                                .values(estado="incierto", error="lease_vencido", texto=None, lease_hasta=None,
                                        actualizado_en=func.now()))
            await s.execute(update(Aviso).where(Aviso.estado == "pendiente", Aviso.caduca_en < func.now())
                            .values(estado="fallido", error="vencido", texto=None, actualizado_en=func.now()))
            return r.rowcount

    async def candidatos(self, limite: int = 50) -> list[Aviso]:
        """El más viejo ya vencido de espera de cada sistema (sin bloquearlo: `reclamar` lo hace). Uno por sistema:
        un sistema frenado por el espaciado o los topes no tapa a los demás."""
        async with self._sesiones() as s:
            return list((await s.execute(select(Aviso).where(
                Aviso.estado == "pendiente", Aviso.proximo_intento <= func.now())
                .ext(distinct_on(Aviso.sistema_id)).order_by(Aviso.sistema_id, Aviso.proximo_intento, Aviso.id)
                .limit(limite))).scalars())

    async def reclamar(self, aviso_id: int, lease_s: float) -> Aviso | None:
        """Lo toma para enviarlo (`FOR UPDATE SKIP LOCKED`): solo uno de varios workers lo consigue."""
        async with self._sesiones.begin() as s:
            tomado = (await s.execute(text(
                "UPDATE avisos SET estado='enviando', intentos=intentos+1, enviado_en=now(), actualizado_en=now(), "
                "lease_hasta=now() + make_interval(secs => :lease) "
                "WHERE id=(SELECT id FROM avisos WHERE id=:id AND estado='pendiente' FOR UPDATE SKIP LOCKED) "
                "RETURNING id"), {"id": aviso_id, "lease": lease_s})).scalar_one_or_none()
            return None if tomado is None else await s.get(Aviso, tomado, populate_existing=True)

    async def diferir(self, aviso_id: int, proximo: datetime) -> None:
        """Pospone un `pendiente` (tope diario alcanzado) sin reclamarlo ni gastar un intento."""
        async with self._sesiones.begin() as s:
            await s.execute(update(Aviso).where(Aviso.id == aviso_id, Aviso.estado == "pendiente").values(
                proximo_intento=proximo, actualizado_en=func.now()))

    async def ultimo_envio(self, sistema_id: str) -> datetime | None:
        async with self._sesiones() as s:
            return (await s.execute(select(func.max(Aviso.enviado_en)).where(
                Aviso.sistema_id == sistema_id, Aviso.estado.in_(_CONSUMEN)))).scalar_one()

    async def ultimo_envio_a(self, sistema_id: str, wa_id: str) -> datetime | None:
        async with self._sesiones() as s:
            return (await s.execute(select(func.max(Aviso.enviado_en)).where(
                Aviso.sistema_id == sistema_id, Aviso.wa_id == wa_id, Aviso.estado.in_(_CONSUMEN)))).scalar_one()

    async def enviados_24h(self, sistema_id: str, wa_id: str | None = None) -> int:
        desde = datetime.now(UTC) - timedelta(hours=24)
        async with self._sesiones() as s:
            q = select(func.count()).where(Aviso.sistema_id == sistema_id, Aviso.estado.in_(_CONSUMEN),
                                           Aviso.enviado_en > desde)
            if wa_id is not None:
                q = q.where(Aviso.wa_id == wa_id)
            return (await s.execute(q)).scalar_one()

    async def _terminar(self, aviso_id: int, **valores) -> bool:
        async with self._sesiones.begin() as s:
            r = await s.execute(update(Aviso).where(Aviso.id == aviso_id, Aviso.estado == "enviando").values(
                lease_hasta=None, actualizado_en=func.now(), **valores))
            return r.rowcount == 1

    async def enviado(self, aviso_id: int, mensaje_id: str) -> bool:
        return await self._terminar(aviso_id, estado="enviado", mensaje_id=mensaje_id, error=None, texto=None)

    async def incierto(self, aviso_id: int, error: str) -> bool:
        return await self._terminar(aviso_id, estado="incierto", error=error[:ERROR_MAX], texto=None)

    async def fallido(self, aviso_id: int, error: str) -> bool:
        return await self._terminar(aviso_id, estado="fallido", error=error[:ERROR_MAX], texto=None)

    async def reintentar(self, aviso_id: int, error: str, proximo: datetime, *, consume_intento: bool = True) -> bool:
        """Vuelve a la cola (error seguro de «no enviado», o diferido por un tope). Deja de contar como envío."""
        return await self._terminar(
            aviso_id, estado="pendiente", error=error[:ERROR_MAX], proximo_intento=proximo, enviado_en=None,
            **({} if consume_intento else {"intentos": Aviso.intentos - 1}))

    async def purgar(self, sistema_id: str, retencion_dias: int) -> int:
        """Borra los terminados con más de `retencion_dias`: pasado ese plazo el anfitrión no puede reintentar un
        `id_evento` (se trataría como nuevo)."""
        limite = datetime.now(UTC) - timedelta(days=retencion_dias)
        async with self._sesiones.begin() as s:
            r = await s.execute(delete(Aviso).where(
                Aviso.sistema_id == sistema_id, Aviso.creado_en < limite,
                Aviso.estado.in_(("enviado", "fallido", "incierto"))))
            return r.rowcount
