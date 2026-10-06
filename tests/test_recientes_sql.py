"""`RecientesSql` y la purga de la auditoría contra Postgres real."""

import os
import uuid
from datetime import UTC, datetime, timedelta

import pytest
from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import async_sessionmaker, create_async_engine

from asistente.core.ports import Contexto, LimitesUso, ResultadoTool
from asistente.store.auditoria import AuditoriaSql
from asistente.store.models import Base, LlamadaTool
from asistente.store.recientes import RecientesSql

URL = os.environ.get("ASISTENTE_DATABASE_URL")
pytestmark = pytest.mark.skipif(not URL, reason="sin ASISTENTE_DATABASE_URL")

AHORA = datetime(2026, 10, 6, 15, 0, tzinfo=UTC)
LECTURA = {"resumen_por_cultivo", "listar_establecimientos"}


@pytest.fixture
async def sesiones():
    motor = create_async_engine(URL)
    async with motor.begin() as c:
        await c.run_sync(Base.metadata.create_all)
    yield async_sessionmaker(motor, expire_on_commit=False)
    await motor.dispose()


@pytest.fixture
def sistema() -> str:
    return f"t-{uuid.uuid4().hex[:12]}"


def ctx(sistema, usuario="ana", **kw) -> Contexto:
    return Contexto(sistema_id=sistema, sistema_nombre="T", usuario_ref=usuario, jti="j", request_id="r",
                    modelo="m", prompt_system="s", prompt_version="v", limites=LimitesUso(10, 10, 10), **kw)


async def anotar(sesiones, sistema, usuario="ana", tool="resumen_por_cultivo", parametros=None, hace_dias=0.0,
                 ok=True, zona="America/Montevideo"):
    async with sesiones.begin() as s:
        s.add(LlamadaTool(sistema_id=sistema, usuario_ref=usuario, jti="j", tool=tool,
                          parametros={} if parametros is None else parametros, ok=ok, zona_horaria=zona,
                          creada=AHORA - timedelta(days=hace_dias)))


async def pedir(sesiones, sistema, usuario="ana", tools=LECTURA, dias=30, limite=10):
    return await RecientesSql(sesiones).consultas(ctx(sistema, usuario), tools, AHORA - timedelta(days=dias), limite)


async def test_agrupa_las_repetidas_y_ordena_de_la_mas_reciente_a_la_mas_antigua(sesiones, sistema):
    soja = {"cultivo": "soja"}
    await anotar(sesiones, sistema, parametros=soja, hace_dias=5, zona="Europe/Madrid")
    await anotar(sesiones, sistema, parametros=soja, hace_dias=1, zona="America/Montevideo")
    await anotar(sesiones, sistema, parametros=soja, hace_dias=3)
    await anotar(sesiones, sistema, tool="listar_establecimientos", hace_dias=2)
    r = await pedir(sesiones, sistema)
    assert [(c.tool, c.veces) for c in r] == [("resumen_por_cultivo", 3), ("listar_establecimientos", 1)]
    assert r[0].parametros == soja and r[0].ultima_vez == AHORA - timedelta(days=1)
    assert r[0].zona_horaria == "America/Montevideo"  # la de la más reciente
    # el orden de las claves del JSON no crea grupos distintos
    await anotar(sesiones, sistema, parametros={"a": 1, "b": 2}, hace_dias=0.5)
    await anotar(sesiones, sistema, parametros={"b": 2, "a": 1}, hace_dias=0.4)
    assert (await pedir(sesiones, sistema))[0].veces == 2


async def test_parametros_distintos_son_consultas_distintas(sesiones, sistema):
    await anotar(sesiones, sistema, parametros={"cultivo": "soja"})
    await anotar(sesiones, sistema, parametros={"cultivo": "maiz"})
    assert len(await pedir(sesiones, sistema)) == 2


async def test_solo_ve_las_del_usuario_y_el_sistema(sesiones, sistema):
    otro = f"t-{uuid.uuid4().hex[:12]}"
    await anotar(sesiones, sistema, usuario="ana")
    await anotar(sesiones, sistema, usuario="beto", parametros={"de": "beto"})
    await anotar(sesiones, otro, usuario="ana", parametros={"de": "otro sistema"})
    r = await pedir(sesiones, sistema, "ana")
    assert [c.parametros for c in r] == [{}]
    assert [c.parametros for c in await pedir(sesiones, sistema, "beto")] == [{"de": "beto"}]
    assert [c.parametros for c in await pedir(sesiones, otro, "ana")] == [{"de": "otro sistema"}]


async def test_ignora_fallidas_otras_tools_y_lo_que_esta_fuera_de_la_ventana(sesiones, sistema):
    await anotar(sesiones, sistema, parametros={"v": "ok"})
    await anotar(sesiones, sistema, parametros={"v": "fallida"}, ok=False)
    await anotar(sesiones, sistema, tool="agregar_nota", parametros={"v": "escritura"})
    await anotar(sesiones, sistema, tool="resumen_por_cultivo#propuesta", parametros={"v": "propuesta"})
    await anotar(sesiones, sistema, parametros={"v": "vieja"}, hace_dias=45)
    assert [c.parametros for c in await pedir(sesiones, sistema)] == [{"v": "ok"}]
    assert await pedir(sesiones, sistema, tools=set()) == []


async def test_limite_y_filas_sin_parametros(sesiones, sistema):
    for i in range(5):
        await anotar(sesiones, sistema, parametros={"i": i}, hace_dias=i)
    async with sesiones.begin() as s:  # parametros NULL (filas viejas): no debe fallar
        s.add(LlamadaTool(sistema_id=sistema, usuario_ref="ana", jti="j", tool="listar_establecimientos",
                          parametros=None, ok=True, creada=AHORA - timedelta(days=6)))
    r = await pedir(sesiones, sistema, limite=3)
    assert [c.parametros["i"] for c in r] == [0, 1, 2]
    vieja = next(c for c in await pedir(sesiones, sistema) if c.tool == "listar_establecimientos")
    assert vieja.parametros == {} and vieja.zona_horaria is None


async def test_la_auditoria_guarda_la_zona_del_usuario(sesiones, sistema):
    c = ctx(sistema, zona_horaria="America/Montevideo")
    await AuditoriaSql(sesiones).registrar_tool(c, None, "listar_establecimientos", {}, ResultadoTool(True, []), 3)
    async with sesiones() as s:
        fila = (await s.execute(select(LlamadaTool).where(LlamadaTool.sistema_id == sistema))).scalar_one()
    assert fila.zona_horaria == "America/Montevideo"


async def test_la_purga_borra_lo_vencido_solo_del_sistema(sesiones, sistema):
    otro = f"t-{uuid.uuid4().hex[:12]}"
    await anotar(sesiones, sistema, hace_dias=40)
    await anotar(sesiones, sistema, hace_dias=29)
    await anotar(sesiones, otro, hace_dias=40)
    assert await AuditoriaSql(sesiones).purgar(sistema, 30, ahora=AHORA) == 1

    async def cuantas(sis):
        async with sesiones() as s:
            return (await s.execute(
                select(func.count()).select_from(LlamadaTool).where(LlamadaTool.sistema_id == sis))).scalar_one()

    assert await cuantas(sistema) == 1 and await cuantas(otro) == 1  # el otro sistema usa su propia retención
