"""Rate limit y cuotas sobre Postgres (sección 7.1/6 del plan).

Contadores atómicos con `INSERT .. ON CONFLICT DO UPDATE .. RETURNING`: sin carreras
entre réplicas. Los de usuario cuentan por `(sistema_id, usuario_ref)`; el total de
tokens del mes es por sistema (`usuario_ref = ''`).
"""

from datetime import UTC, datetime

from sqlalchemy import select
from sqlalchemy.dialects.postgresql import insert
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from asistente.core.llm.base import Uso
from asistente.core.ports import Contexto, LimiteExcedido
from asistente.store.models import ContadorUso


def _ventanas(ahora: datetime) -> dict[str, datetime]:
    return {
        "min": ahora.replace(second=0, microsecond=0),
        "dia": ahora.replace(hour=0, minute=0, second=0, microsecond=0),
        "mes": ahora.replace(day=1, hour=0, minute=0, second=0, microsecond=0),
    }


async def _sumar(
    s: AsyncSession, sistema_id: str, usuario_ref: str, ventana: str, inicio: datetime,
    mensajes: int, tokens: int,
) -> ContadorUso:
    stmt = (
        insert(ContadorUso)
        .values(sistema_id=sistema_id, usuario_ref=usuario_ref, ventana=ventana, inicio=inicio,
                mensajes=mensajes, tokens=tokens)
        .on_conflict_do_update(
            index_elements=["sistema_id", "usuario_ref", "ventana", "inicio"],
            set_={
                "mensajes": ContadorUso.mensajes + mensajes,
                "tokens": ContadorUso.tokens + tokens,
            },
        )
        .returning(ContadorUso)
    )
    return (await s.execute(stmt)).scalar_one()


class LimitesPostgres:
    def __init__(self, sesiones: async_sessionmaker[AsyncSession], reloj=lambda: datetime.now(UTC)):
        self._sesiones = sesiones
        self._reloj = reloj

    async def reservar_mensaje(self, ctx: Contexto) -> None:
        v = _ventanas(self._reloj())
        async with self._sesiones.begin() as s:
            # Cuota del mes del sistema: se consulta antes de contar el mensaje.
            usado = (
                await s.execute(
                    select(ContadorUso.tokens).where(
                        ContadorUso.sistema_id == ctx.sistema_id,
                        ContadorUso.usuario_ref == "",
                        ContadorUso.ventana == "mes",
                        ContadorUso.inicio == v["mes"],
                    )
                )
            ).scalar_one_or_none()
            if usado is not None and usado >= ctx.limites.tokens_por_mes:
                raise LimiteExcedido("tokens_mes")

            por_min = await _sumar(s, ctx.sistema_id, ctx.usuario_ref, "min", v["min"], 1, 0)
            por_dia = await _sumar(s, ctx.sistema_id, ctx.usuario_ref, "dia", v["dia"], 1, 0)
            # Un rechazo también cuenta: reintentar en bucle no libera el tope.
            if por_min.mensajes > ctx.limites.mensajes_por_usuario_min:
                excedido = "mensajes_min"
            elif por_dia.mensajes > ctx.limites.mensajes_por_usuario_dia:
                excedido = "mensajes_dia"
            else:
                return
        raise LimiteExcedido(excedido)

    async def registrar_uso(self, ctx: Contexto, uso: Uso) -> None:
        if uso.total <= 0:
            return
        v = _ventanas(self._reloj())
        async with self._sesiones.begin() as s:
            await _sumar(s, ctx.sistema_id, "", "mes", v["mes"], 0, uso.total)
            await _sumar(s, ctx.sistema_id, ctx.usuario_ref, "dia", v["dia"], 0, uso.total)
