"""Fase 5, piezas sueltas: manifiesto, registro y purga de acciones."""

import os
import uuid
from datetime import UTC, datetime, timedelta

import pytest
from pydantic import ValidationError
from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import async_sessionmaker, create_async_engine

from asistente.sistemas.manifiesto import ManifiestoInvalido, parsear_manifiesto
from asistente.sistemas.registro import RegistroSistemas, Sistema
from asistente.store.acciones import AccionesSql
from asistente.store.models import Accion, Base
from conftest import entorno, entrada_sistema, escribir_registro

PARAMS = {"type": "object", "properties": {}}


def tool(nombre="t", **extra) -> dict:
    return {"nombre": nombre, "descripcion": "d", "parametros": PARAMS, "efecto": "escritura", **extra}


def manifiesto(*tools):
    return parsear_manifiesto({"contrato": "1", "sistema": {"nombre": "S"}, "tools": list(tools)})


def test_solo_es_accionable_la_escritura_con_confirmacion_y_no_destructiva():
    m = manifiesto(
        tool("con_conf", confirmacion={"ttl_s": 60}),
        tool("sin_conf"),
        tool("borrar", confirmacion={}, destructiva=True),
        {**tool("leer"), "efecto": "lectura"},
    )
    assert m.tools["con_conf"].confirmacion_ttl_s == 60
    assert [t.nombre for t in m.tools.values() if t.accionable] == ["con_conf"]


def test_tools_accion_respeta_la_lista_del_operador():
    m = manifiesto(tool("a", confirmacion={}), tool("b", confirmacion={}))
    assert m.tools_accion(()) == []
    assert [t.nombre for t in m.tools_accion(["b", "no_existe"])] == ["b"]
    assert m.tools["a"].confirmacion_ttl_s == 120  # por defecto


def test_la_lectura_nunca_aparece_como_accion():
    m = manifiesto({**tool("leer"), "efecto": "lectura"})
    assert m.tools_accion(["leer"]) == []


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
    reg = RegistroSistemas(ruta, env=entorno("a", "b"))
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
