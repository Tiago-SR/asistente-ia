"""Fase 5, piezas sueltas: manifiesto, registro y purga de acciones."""

import os
import uuid
from datetime import UTC, datetime, timedelta

import pytest
from pydantic import ValidationError
from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import async_sessionmaker, create_async_engine

from asistente.sistemas.manifiesto import ManifiestoInvalido, parsear_manifiesto
from asistente.sistemas.registro import Sistema
from asistente.store.acciones import AccionesSql
from asistente.store.models import Accion, Base
from conftest import entorno, entrada_sistema, escribir_registro, registro_desde_yaml

PARAMS = {"type": "object", "properties": {}}


def tool(nombre="t", **extra) -> dict:
    return {"nombre": nombre, "descripcion": "d", "parametros": PARAMS, "efecto": "escritura", **extra}


def manifiesto(*tools):
    return parsear_manifiesto({"contrato": "1", "sistema": {"nombre": "S"}, "tools": list(tools)})


def test_solo_es_accionable_la_escritura_con_confirmacion():
    m = manifiesto(
        tool("con_conf", confirmacion={"ttl_s": 60}),
        tool("sin_conf"),
        tool("borrar", confirmacion={}, destructiva=True),
        {**tool("leer"), "efecto": "lectura"},
    )
    assert m.tools["con_conf"].confirmacion_ttl_s == 60
    assert [t.nombre for t in m.tools.values() if t.accionable] == ["con_conf", "borrar"]
    assert m.tools["borrar"].destructiva
    assert manifiesto(tool("a", confirmacion={})).tools["a"].confirmacion_ttl_s == 120  # por defecto


@pytest.mark.parametrize("nombre,esperada", [
    ("borrar_nota", True), ("eliminar_establecimiento", True), ("nota_delete", True), ("dar_de_baja", True),
    ("dar_baja", True), ("anular", True), ("agregar_nota", False), ("trabajador", False),
])
def test_destructiva_por_nombre_aunque_no_la_declare(nombre, esperada):
    assert manifiesto(tool(nombre, confirmacion={})).tools[nombre].destructiva is esperada


def test_huella_estable_ante_el_orden_de_claves_y_cambia_con_la_definicion():
    a = tool("x", confirmacion={}, parametros={"type": "object", "properties": {"a": {}, "b": {}}})
    b = tool("x", confirmacion={}, parametros={"properties": {"b": {}, "a": {}}, "type": "object"})
    ha, hb = (manifiesto(t).tools["x"].huella for t in (a, b))
    assert ha == hb
    assert manifiesto({**a, "descripcion": "otra"}).tools["x"].huella != ha
    assert manifiesto({**a, "confirmacion": {"ttl_s": 30}}).tools["x"].huella != ha


def test_escritura_con_parametro_array_se_descarta_pero_la_lectura_no():
    params = {"type": "object", "properties": {"ids": {"type": "array"}}}
    m = manifiesto(tool("w", parametros=params), {**tool("r", parametros=params), "efecto": "lectura"})
    assert m.tools.keys() == {"r"}


@pytest.mark.parametrize("confirmacion", [{"ttl_s": 5}, {"ttl_s": 301}, {"ttl_s": "60"}, {"ttl_s": True}, "si"])
def test_confirmacion_invalida_descarta_la_tool(confirmacion):
    assert manifiesto(tool("x", confirmacion=confirmacion), tool("ok")).tools.keys() == {"ok"}


def test_confirmacion_en_una_lectura_o_destructiva_no_booleana_se_descarta():
    leer = {**tool("l", confirmacion={"ttl_s": 60}), "efecto": "lectura"}
    assert manifiesto(leer, tool("d", destructiva="si"), tool("ok")).tools.keys() == {"ok"}


def test_un_manifiesto_sin_tools_validas_sigue_siendo_valido():
    with pytest.raises(ManifiestoInvalido):
        parsear_manifiesto({"contrato": "1", "sistema": {"nombre": "S"}, "tools": "no"})


def test_registro_acciones_habilitadas_por_defecto_vacio_y_ruta_de_propuesta(tmp_path):
    ruta = escribir_registro(tmp_path / "s.yaml", [
        entrada_sistema("a"),
        entrada_sistema("b", acciones_habilitadas=["agregar_nota"]),
    ])
    reg = registro_desde_yaml(ruta, env=entorno("a", "b"))
    assert reg.obtener("a").acciones_habilitadas == ()
    assert reg.obtener("b").acciones_habilitadas == ("agregar_nota",)
    assert reg.obtener("a").conector.ruta_propuesta == "/asistente/tools/{nombre}/propuesta"
    malo = entrada_sistema("c")
    malo["conector"]["ruta_propuesta"] = "/sin/nombre"
    with pytest.raises(ValidationError):
        Sistema.model_validate(malo)


# --- purga (con Postgres) -------------------------------------------------------------------------

URL = os.environ.get("ASISTENTE_DATABASE_URL")


@pytest.mark.skipif(not URL, reason="sin ASISTENTE_DATABASE_URL")
async def test_la_purga_borra_acciones_viejas_solo_del_sistema_indicado():
    motor = create_async_engine(URL)
    async with motor.begin() as c:
        await c.run_sync(Base.metadata.create_all)
    sesiones = async_sessionmaker(motor, expire_on_commit=False)
    sid, otro = f"t-{uuid.uuid4().hex[:10]}", f"t-{uuid.uuid4().hex[:10]}"
    ahora = datetime.now(UTC)
    async with sesiones.begin() as s:
        for sistema, dias in ((sid, 40), (sid, 1), (otro, 40)):
            s.add(Accion(sistema_id=sistema, usuario_ref="ana", tool="t", parametros={}, huella="h" * 8,
                         resumen="r", lineas=[], estado="ejecutada", creada=ahora - timedelta(days=dias),
                         expira=ahora))
    try:
        assert await AccionesSql(sesiones).purgar(sid, 30) == 1
        async with sesiones() as s:
            quedan = lambda sistema: s.execute(
                select(func.count()).select_from(Accion).where(Accion.sistema_id == sistema))
            assert (await quedan(sid)).scalar_one() == 1
            assert (await quedan(otro)).scalar_one() == 1  # otro sistema: intacto
    finally:
        await motor.dispose()


@pytest.mark.skipif(not URL, reason="sin ASISTENTE_DATABASE_URL")
async def test_destructivas_tienen_tope_propio_ttl_corto_y_flag():
    from asistente.core.ports import Contexto, LimiteExcedido, LimitesUso, ResultadoPropuesta

    motor = create_async_engine(URL)
    async with motor.begin() as c:
        await c.run_sync(Base.metadata.create_all)
    sesiones = async_sessionmaker(motor, expire_on_commit=False)
    sid = f"t-{uuid.uuid4().hex[:10]}"
    ctx = Contexto(sistema_id=sid, sistema_nombre="S", usuario_ref="ana", jti="j", request_id="r", modelo="m",
                   prompt_system="s", prompt_version="v", limites=LimitesUso(10, 10, 10, destructivas_por_hora=2))
    p = ResultadoPropuesta(ok=True, resumen="r", lineas=("l",), huella="h" * 16, expira_s=300)
    acciones = AccionesSql(sesiones)
    try:
        for _ in range(2):
            creada = await acciones.crear(ctx, uuid.uuid4(), "borrar_nota", {}, p, destructiva=True)
        vida = datetime.fromisoformat(creada.expira) - datetime.now(UTC)
        assert vida <= timedelta(seconds=60)
        with pytest.raises(LimiteExcedido) as e:
            await acciones.crear(ctx, uuid.uuid4(), "borrar_nota", {}, p, destructiva=True)
        assert e.value.cual == "destructivas_hora"
        # las escrituras normales no gastan ni sufren ese tope, y conservan su TTL
        normal = await acciones.crear(ctx, uuid.uuid4(), "agregar_nota", {}, p)
        assert datetime.fromisoformat(normal.expira) - datetime.now(UTC) > timedelta(seconds=200)
        # otro usuario tiene su propio cupo
        otro = ctx.__class__(**{**ctx.__dict__, "usuario_ref": "beto"})
        await acciones.crear(otro, uuid.uuid4(), "borrar_nota", {}, p, destructiva=True)
        async with sesiones() as s:
            n = (await s.execute(select(func.count()).select_from(Accion).where(
                Accion.sistema_id == sid, Accion.destructiva.is_(True)))).scalar_one()
        assert n == 3
    finally:
        await motor.dispose()
