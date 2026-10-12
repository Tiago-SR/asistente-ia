import os
import uuid
from datetime import UTC, datetime, timedelta

import pytest
from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import async_sessionmaker, create_async_engine

from asistente.core.ports import EventoMetrica
from asistente.precios import Tarifas
from asistente.store.metricas import MetricasSql
from asistente.store.models import Base, EventoUso

URL = os.environ.get("ASISTENTE_DATABASE_URL")
pytestmark = pytest.mark.skipif(not URL, reason="sin ASISTENTE_DATABASE_URL")

TARIFA = {"m1": {
    "entrada_cache_hit": {"valle": 1.0, "pico": 2.0},
    "entrada_cache_miss": {"valle": 10.0, "pico": 20.0},
    "salida": {"valle": 100.0, "pico": 200.0},
}, "elevenlabs:v2": {"usd_por_1k_caracteres": 0.5}}


@pytest.fixture
async def sesiones():
    motor = create_async_engine(URL)
    async with motor.begin() as c:
        await c.run_sync(Base.metadata.create_all)
    yield async_sessionmaker(motor, expire_on_commit=False)
    await motor.dispose()


def sid() -> str:
    return f"t-{uuid.uuid4().hex[:12]}"


async def filas(sesiones, sistema: str) -> list[EventoUso]:
    async with sesiones() as s:
        r = await s.execute(select(EventoUso).where(EventoUso.sistema_id == sistema).order_by(EventoUso.id))
        return list(r.scalars())


async def test_escribe_en_lote_con_costo_valle_y_pico(sesiones):
    m = MetricasSql(sesiones, lambda: TARIFA)
    s = sid()
    m.registrar(EventoMetrica(sistema_id=s, tipo="llm", resultado="ok", modelo="m1", usuario_ref="ana",
                              tokens_in=1_000_000, tokens_in_cache=400_000, tokens_out=100_000,
                              llamadas_llm=2, latencia_llm_ms=900, ttft_ms=300, duracion_ms=1500))
    assert m.pendientes() == 1  # registrar no escribe: solo encola
    await m.vaciar()
    [f] = await filas(sesiones, s)
    assert f.costo_valle_usd == pytest.approx(600_000 * 10 / 1e6 + 400_000 * 1 / 1e6 + 100_000 * 100 / 1e6)
    assert f.costo_pico_usd == pytest.approx(600_000 * 20 / 1e6 + 400_000 * 2 / 1e6 + 100_000 * 200 / 1e6)
    assert (f.llamadas_llm, f.latencia_llm_ms, f.ttft_ms, f.duracion_ms) == (2, 900, 300, 1500)


async def test_modelo_sin_tarifa_deja_el_costo_en_null_no_en_cero(sesiones):
    m = MetricasSql(sesiones, lambda: TARIFA)
    s = sid()
    m.registrar(EventoMetrica(sistema_id=s, tipo="llm", resultado="ok", modelo="desconocido", tokens_in=10))
    m.registrar(EventoMetrica(sistema_id=s, tipo="stt", resultado="ok", modelo="x", unidades=1000))
    await m.vaciar()
    assert [(f.costo_valle_usd, f.costo_pico_usd) for f in await filas(sesiones, s)] == [(None, None)] * 2


async def test_tts_costo_por_caracteres(sesiones):
    m = MetricasSql(sesiones, lambda: TARIFA)
    s = sid()
    m.registrar(EventoMetrica(sistema_id=s, tipo="tts", resultado="ok", modelo="elevenlabs:v2", unidades=2000))
    await m.vaciar()
    [f] = await filas(sesiones, s)
    assert f.costo_valle_usd == f.costo_pico_usd == pytest.approx(1.0)


async def test_rechazos_iguales_del_mismo_minuto_se_agregan(sesiones):
    t = [datetime(2026, 10, 12, 10, 0, 5, tzinfo=UTC)]
    m = MetricasSql(sesiones, reloj=lambda: t[0])
    s = sid()
    rechazo = EventoMetrica(sistema_id=s, tipo="llm", resultado="limite", motivo="tokens_mes", usuario_ref="ana")
    for _ in range(50):
        m.registrar(rechazo)
    t[0] += timedelta(minutes=1)  # otro minuto: fila aparte
    m.registrar(rechazo)
    m.registrar(EventoMetrica(sistema_id=s, tipo="llm", resultado="limite", motivo="tokens_mes", usuario_ref="beto"))
    assert m.pendientes() == 3
    await m.vaciar()
    assert sorted(f.n for f in await filas(sesiones, s)) == [1, 1, 50]


async def test_cola_llena_descarta_y_cuenta_sin_lanzar(sesiones):
    m = MetricasSql(sesiones, max_cola=3)
    s = sid()
    for _ in range(5):
        m.registrar(EventoMetrica(sistema_id=s, tipo="llm", resultado="ok"))
    assert m.pendientes() == 3
    assert m.descartados == 2
    await m.vaciar()
    assert len(await filas(sesiones, s)) == 3


async def test_un_insert_que_falla_se_descarta_y_no_se_propaga(sesiones):
    m = MetricasSql(sesiones)
    s = sid()
    m.registrar(EventoMetrica(sistema_id=s, tipo="llm", resultado="ok"))
    m.registrar(EventoMetrica(sistema_id=s, tipo="no_existe", resultado="ok"))  # viola el CHECK del lote
    await m.vaciar()  # no lanza
    assert m.descartados == 2 and m.pendientes() == 0
    m.registrar(EventoMetrica(sistema_id=s, tipo="llm", resultado="ok"))
    await m.vaciar()  # sigue funcionando después del fallo
    assert len(await filas(sesiones, s)) == 1


async def test_un_evento_malformado_no_rompe_registrar(sesiones):
    m = MetricasSql(sesiones)
    m.registrar(None)  # type: ignore[arg-type]
    assert m.descartados == 1


async def test_recorta_campos_largos_para_no_romper_el_lote(sesiones):
    m = MetricasSql(sesiones)
    s = sid()
    m.registrar(EventoMetrica(sistema_id=s, tipo="llm", resultado="error", motivo="x" * 100, modelo="m" * 500))
    await m.vaciar()
    [f] = await filas(sesiones, s)
    assert len(f.motivo) == 32 and len(f.modelo) == 200


async def test_indices_y_total_de_filas_tras_varios_lotes(sesiones):
    m = MetricasSql(sesiones, lote=10)
    s = sid()
    for _ in range(25):
        m.registrar(EventoMetrica(sistema_id=s, tipo="llm", resultado="ok"))
    await m.vaciar()
    async with sesiones() as ses:
        total = (await ses.execute(select(func.count()).select_from(EventoUso)
                                   .where(EventoUso.sistema_id == s))).scalar_one()
    assert total == 25


def test_tarifas_relee_el_archivo_cuando_cambia(tmp_path):
    ruta = tmp_path / "p.yaml"
    ruta.write_text("m1: {salida: {valle: 1, pico: 2}}\n")
    t = Tarifas(ruta)
    assert "m1" in t()
    ruta.write_text("m2: {salida: {valle: 1, pico: 2}}\n")
    os.utime(ruta, (1, 1_900_000_000))
    assert "m2" in t() and "m1" not in t()
    ruta.unlink()
    assert Tarifas(tmp_path / "no_esta.yaml")() == {}
