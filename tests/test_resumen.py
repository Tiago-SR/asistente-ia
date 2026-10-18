import os
import uuid
from datetime import UTC, datetime, timedelta

import pytest
from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import async_sessionmaker, create_async_engine

from asistente.store.models import Base, ContadorUso, EventoUso, LlamadaTool, UsoDiario
from asistente.store.resumen import ResumenSql

URL = os.environ.get("ASISTENTE_DATABASE_URL")
pytestmark = pytest.mark.skipif(not URL, reason="sin ASISTENTE_DATABASE_URL")

AHORA = datetime(2026, 10, 12, 15, 30, tzinfo=UTC)


@pytest.fixture
async def sesiones():
    motor = create_async_engine(URL)
    async with motor.begin() as c:
        await c.run_sync(Base.metadata.create_all)
    yield async_sessionmaker(motor, expire_on_commit=False)
    await motor.dispose()


def sid() -> str:
    return f"t-{uuid.uuid4().hex[:12]}"


def evento(s: str, dias_atras: int, **kw) -> EventoUso:
    base = {"sistema_id": s, "tipo": "llm", "resultado": "ok", "modelo": "m1", "usuario_ref": "ana", "n": 1,
            "tokens_in": 100, "tokens_out": 10, "duracion_ms": 1000, "costo_valle_usd": 0.5,
            "costo_pico_usd": 1.0, "creada": AHORA - timedelta(days=dias_atras, hours=1)}
    return EventoUso(**{**base, **kw})


async def diario(sesiones, s: str) -> list[UsoDiario]:
    async with sesiones() as ses:
        r = await ses.execute(select(UsoDiario).where(UsoDiario.sistema_id == s).order_by(UsoDiario.dia, UsoDiario.tipo))
        return list(r.scalars())


async def cuenta(sesiones, modelo, s: str) -> int:
    async with sesiones() as ses:
        return (await ses.execute(
            select(func.count()).select_from(modelo).where(modelo.sistema_id == s))).scalar_one()


async def test_resumen_agrega_por_dia_y_es_idempotente(sesiones):
    s = sid()
    async with sesiones.begin() as ses:
        ses.add_all([
            evento(s, 1, usuario_ref="ana", duracion_ms=1000),
            evento(s, 1, usuario_ref="ana", duracion_ms=3000),
            evento(s, 1, usuario_ref="luis", duracion_ms=2000, costo_valle_usd=None, costo_pico_usd=None),
            evento(s, 1, resultado="limite", motivo="cuota", usuario_ref="ana", n=4, duracion_ms=None),
        ])
    r = ResumenSql(sesiones)
    await r.resumir(s, 30, AHORA)
    primera = await diario(sesiones, s)
    await r.resumir(s, 30, AHORA)
    assert [(f.dia, f.resultado, f.n, f.usuarios) for f in await diario(sesiones, s)] == \
        [(f.dia, f.resultado, f.n, f.usuarios) for f in primera]
    ok = next(f for f in primera if f.resultado == "ok")
    assert (ok.n, ok.usuarios, ok.tokens_in, ok.latencia_max_ms, ok.p50_ms) == (3, 2, 300, 3000, 2000)
    assert ok.costo_valle_usd == pytest.approx(1.0)  # la suma ignora el evento sin tarifa...
    assert ok.n_sin_tarifa == 1  # ...y queda dicho que el costo es parcial
    lim = next(f for f in primera if f.resultado == "limite")
    assert (lim.n, lim.motivo, lim.p50_ms, lim.n_sin_tarifa) == (4, "cuota", None, 0)  # un rechazo no es «sin tarifa»


async def test_recalcular_sobrescribe_con_los_crudos_nuevos(sesiones):
    s = sid()
    async with sesiones.begin() as ses:
        ses.add(evento(s, 1))
    r = ResumenSql(sesiones)
    await r.resumir(s, 30, AHORA)
    async with sesiones.begin() as ses:
        ses.add(evento(s, 1))
    await r.resumir(s, 30, AHORA)
    [f] = await diario(sesiones, s)
    assert f.n == 2


async def test_ventana_no_incluye_hoy_ni_mas_de_7_dias(sesiones):
    s = sid()
    async with sesiones.begin() as ses:
        ses.add_all([evento(s, 0, creada=AHORA - timedelta(hours=1)), evento(s, 9)])
    await ResumenSql(sesiones).resumir(s, 90, AHORA)
    assert await diario(sesiones, s) == []


async def test_tools_van_a_uso_diario_con_el_nombre_en_modelo(sesiones):
    s = sid()
    creada = AHORA - timedelta(days=1, hours=1)
    async with sesiones.begin() as ses:
        for ok, ms in [(True, 100), (True, 300), (False, 50)]:
            ses.add(LlamadaTool(sistema_id=s, usuario_ref="ana", jti="j", tool="consultar_stock", ok=ok,
                                duracion_ms=ms, creada=creada))
    await ResumenSql(sesiones).resumir(s, 30, AHORA)
    filas = {f.resultado: f for f in await diario(sesiones, s)}
    assert filas["ok"].tipo == "tool" and filas["ok"].modelo == "consultar_stock"
    assert (filas["ok"].n, filas["ok"].p50_ms, filas["error"].n) == (2, 200, 1)


async def test_la_ventana_de_tools_es_menor_que_la_retencion(sesiones):
    s = sid()
    async with sesiones.begin() as ses:  # hace 3 días, con retención de 3: ya recortado por llamadas_tool
        ses.add(LlamadaTool(sistema_id=s, usuario_ref="ana", jti="j", tool="t", ok=True, duracion_ms=1,
                            creada=AHORA - timedelta(days=3, hours=-1)))
        ses.add(LlamadaTool(sistema_id=s, usuario_ref="ana", jti="j", tool="t", ok=True, duracion_ms=1,
                            creada=AHORA - timedelta(days=1, hours=1)))
    await ResumenSql(sesiones).resumir(s, 3, AHORA)  # ventana de tools = 2 días: hoy-2..ayer
    assert [f.n for f in await diario(sesiones, s)] == [1]
    await ResumenSql(sesiones).resumir(s, 1, AHORA)  # retención de 1 día: sin ventana de tools
    assert [f.n for f in await diario(sesiones, s)] == [1]


async def test_purga_solo_dias_completos_y_resumidos(sesiones):
    s = sid()
    async with sesiones.begin() as ses:
        ses.add_all([evento(s, 10) for _ in range(3)] + [evento(s, 2)])
    r = ResumenSql(sesiones)
    # El día de hace 10 días está fuera de la ventana de resumen: la purga lo resume antes de borrarlo.
    assert await r.purgar_eventos(s, 5, AHORA) == 3
    assert await cuenta(sesiones, EventoUso, s) == 1  # el de hace 2 días se conserva
    dias = await diario(sesiones, s)
    assert [(f.dia, f.n) for f in dias] == [((AHORA - timedelta(days=10, hours=1)).date(), 3)]


async def test_purga_respeta_el_tope_de_90_dias(sesiones):
    s = sid()
    async with sesiones.begin() as ses:
        ses.add_all([evento(s, 100), evento(s, 80)])
    await ResumenSql(sesiones).purgar_eventos(s, 365, AHORA)
    assert await cuenta(sesiones, EventoUso, s) == 1


async def test_purga_de_contadores_conserva_el_mes_y_lo_reciente(sesiones):
    s = sid()
    viejo = AHORA - timedelta(days=5)
    async with sesiones.begin() as ses:
        ses.add_all([
            ContadorUso(sistema_id=s, usuario_ref="ana", ventana="min", inicio=viejo),
            ContadorUso(sistema_id=s, usuario_ref="ana", ventana="dia", inicio=viejo),
            ContadorUso(sistema_id=s, usuario_ref="", ventana="mes", inicio=viejo),
            ContadorUso(sistema_id=s, usuario_ref="ana", ventana="dia", inicio=AHORA),
        ])
    await ResumenSql(sesiones).purgar_contadores(AHORA)
    async with sesiones() as ses:
        r = await ses.execute(select(ContadorUso.ventana).where(ContadorUso.sistema_id == s))
        assert sorted(r.scalars()) == ["dia", "mes"]


async def test_resumen_suma_imagenes_y_conserva_los_maximos(sesiones):
    s = sid()
    async with sesiones.begin() as ses:
        ses.add_all([
            evento(s, 1, imagenes=2, imagen_max_kb=300),
            evento(s, 1, imagenes=1, imagen_max_kb=900),
            evento(s, 1),
        ])
    await ResumenSql(sesiones).resumir(s, 30, AHORA)
    ok = next(f for f in await diario(sesiones, s) if f.resultado == "ok")
    assert (ok.imagenes, ok.imagenes_max_turno, ok.imagen_max_kb) == (3, 2, 900)
