import os
import uuid
from datetime import UTC, datetime, timedelta

import pytest
from sqlalchemy import select
from sqlalchemy.ext.asyncio import async_sessionmaker, create_async_engine

from asistente.core.llm.base import Uso
from asistente.core.ports import Contexto, LimiteExcedido, LimitesUso, ResultadoTool
from asistente.limits import LimitesPostgres
from asistente.store.auditoria import AuditoriaSql
from asistente.store.models import Base, LlamadaTool

URL = os.environ.get("ASISTENTE_DATABASE_URL")
pytestmark = pytest.mark.skipif(not URL, reason="sin ASISTENTE_DATABASE_URL")


@pytest.fixture
async def sesiones():
    motor = create_async_engine(URL)
    async with motor.begin() as c:
        await c.run_sync(Base.metadata.create_all)
    yield async_sessionmaker(motor, expire_on_commit=False)
    await motor.dispose()


def ctx(usuario="ana", sistema=None, **lim) -> Contexto:
    topes = {"mensajes_por_usuario_min": 2, "mensajes_por_usuario_dia": 3, "tokens_por_mes": 100, **lim}
    return Contexto(
        sistema_id=sistema or f"t-{uuid.uuid4().hex[:12]}", sistema_nombre="T", usuario_ref=usuario,
        jti="j1", request_id="r", modelo="m", prompt_system="s", prompt_version="v",
        limites=LimitesUso(**topes),
    )


async def test_tope_por_minuto_y_por_usuario(sesiones):
    lim = LimitesPostgres(sesiones, reloj=lambda: datetime(2026, 1, 15, 10, 30, 5, tzinfo=UTC))
    c = ctx()
    await lim.reservar_mensaje(c)
    await lim.reservar_mensaje(c)
    with pytest.raises(LimiteExcedido) as e:
        await lim.reservar_mensaje(c)
    assert e.value.cual == "mensajes_min"
    # otro usuario del mismo sistema no se ve afectado
    await lim.reservar_mensaje(ctx("beto", sistema=c.sistema_id))


async def test_tope_diario_con_minutos_distintos(sesiones):
    t = [datetime(2026, 1, 15, 10, 0, 0, tzinfo=UTC)]
    lim = LimitesPostgres(sesiones, reloj=lambda: t[0])
    c = ctx(mensajes_por_usuario_min=5)
    for _ in range(3):
        await lim.reservar_mensaje(c)
        t[0] += timedelta(minutes=2)
    with pytest.raises(LimiteExcedido) as e:
        await lim.reservar_mensaje(c)
    assert e.value.cual == "mensajes_dia"
    t[0] += timedelta(days=1)  # nueva ventana
    await lim.reservar_mensaje(c)


async def test_cuota_mensual_de_tokens_es_por_sistema(sesiones):
    lim = LimitesPostgres(sesiones, reloj=lambda: datetime(2026, 1, 15, 10, 0, tzinfo=UTC))
    c = ctx(tokens_por_mes=100)
    await lim.registrar_uso(c, Uso(60, 40))
    with pytest.raises(LimiteExcedido) as e:
        await lim.reservar_mensaje(ctx("beto", sistema=c.sistema_id, tokens_por_mes=100))
    assert e.value.cual == "tokens_mes"
    # otro sistema no comparte cuota
    await lim.reservar_mensaje(ctx())


async def test_auditoria_guarda_metadatos_sin_resultado(sesiones):
    c = ctx()
    r = ResultadoTool(True, datos={"secreto": "no debe guardarse"}, status_http=200, bytes_respuesta=42)
    await AuditoriaSql(sesiones).registrar_tool(c, uuid.uuid4(), "lista", {"id": "1"}, r, 12)
    async with sesiones() as s:
        fila = (await s.execute(select(LlamadaTool).where(LlamadaTool.sistema_id == c.sistema_id))).scalar_one()
    assert (fila.tool, fila.ok, fila.status_http, fila.bytes_respuesta, fila.duracion_ms) == ("lista", True, 200, 42, 12)
    assert fila.usuario_ref == "ana" and fila.jti == "j1" and fila.parametros == {"id": "1"}
    assert "secreto" not in repr(fila.__dict__)
