"""Registro de sistemas en Postgres: importar/exportar, secretos cifrados, réplicas y rotación."""

import base64
import os

import pytest
import yaml
from sqlalchemy import delete, select, update
from sqlalchemy.ext.asyncio import async_sessionmaker, create_async_engine

from asistente.sistemas import registro_bd
from asistente.sistemas.auth import Autenticador, TokenInvalido
from asistente.sistemas.cifrado import Cifrador
from asistente.sistemas.manifiesto import Tool
from asistente.sistemas.permisos import tool_permitida
from asistente.sistemas.registro import RegistroSistemas, entradas_desde_yaml
from asistente.sistemas.registro_bd import ErrorRegistro, FuenteBD
from asistente.store.models import (
    Base,
    RegistroVersion,
    SistemaRegistro,
    SistemaSecreto,
    ToolEstado,
)
from conftest import entorno, entrada_sistema, escribir_registro, firmar, registro_desde_yaml

pytestmark = pytest.mark.skipif(
    not os.environ.get("ASISTENTE_DATABASE_URL"), reason="requiere Postgres (ASISTENTE_DATABASE_URL)"
)


def _clave(b: int) -> str:
    return base64.b64encode(bytes([b]) * 32).decode()


K1 = Cifrador.desde_texto(f"k1:{_clave(1)}")
K2_K1 = Cifrador.desde_texto(f"k2:{_clave(2)},k1:{_clave(1)}")
K9 = Cifrador.desde_texto(f"k9:{_clave(9)}")
ESCRITURA = Tool("agregar_nota", "d", {}, "escritura", confirmacion_ttl_s=120)
LECTURA = Tool("ver", "d", {}, "lectura")


@pytest.fixture
async def sesiones():
    motor = create_async_engine(os.environ["ASISTENTE_DATABASE_URL"])
    async with motor.begin() as c:
        await c.run_sync(Base.metadata.create_all)
    fabrica = async_sessionmaker(motor, expire_on_commit=False)

    async def limpiar():
        async with fabrica() as s, s.begin():
            await s.execute(delete(SistemaRegistro))  # secretos y tool_estado, en cascada
            await s.execute(delete(RegistroVersion))

    await limpiar()
    yield fabrica
    await limpiar()
    await motor.dispose()


@pytest.fixture
def yaml_dos(tmp_path):
    ruta = escribir_registro(tmp_path / "s.yaml", [
        entrada_sistema("a", acciones_habilitadas=["agregar_nota"]),
        entrada_sistema("b", llm={"modelo": "m", "api_key_env": "b_LLM"}),
    ])
    return ruta, {**entorno("a", "b"), "b_LLM": "clave-llm-b"}


async def _registro(sesiones, cifrador=K1):
    r = RegistroSistemas()
    f = FuenteBD(r, sesiones, cifrador)
    await f.cargar()
    return r, f


async def test_importar_y_cargar_equivale_al_yaml(sesiones, yaml_dos):
    ruta, env = yaml_dos
    assert await registro_bd.importar_yaml(sesiones, K1, ruta, env) == 2
    desde_bd, _ = await _registro(sesiones)
    desde_yaml = registro_desde_yaml(ruta, env=env)
    assert desde_bd.errores == {} and {s.id for s in desde_bd.todos()} == {"a", "b"}
    for sid in ("a", "b"):
        for campo in ("auth_hs256", "token_manifiesto", "llm_api_key"):
            assert desde_bd.secreto(sid, campo) == desde_yaml.secreto(sid, campo)
        for tool in (ESCRITURA, LECTURA):
            assert tool_permitida(desde_bd.obtener(sid), tool) == tool_permitida(desde_yaml.obtener(sid), tool)
    assert tool_permitida(desde_bd.obtener("a"), ESCRITURA) and not tool_permitida(desde_bd.obtener("b"), ESCRITURA)
    assert desde_bd.obtener("b").llm.modelo == "m"


async def test_los_secretos_van_cifrados_y_no_en_config(sesiones, yaml_dos):
    ruta, env = yaml_dos
    await registro_bd.importar_yaml(sesiones, K1, ruta, env)
    async with sesiones() as s:
        filas = (await s.execute(select(SistemaSecreto))).scalars().all()
        configs = (await s.execute(select(SistemaRegistro.config))).scalars().all()
    assert len(filas) == 5
    for f in filas:
        assert all(v.encode() not in f.cifrado for v in env.values())
    assert all(v not in repr(configs) for v in env.values())


async def test_exportar_no_incluye_secretos_y_reimporta_igual(sesiones, yaml_dos, tmp_path):
    ruta, env = yaml_dos
    await registro_bd.importar_yaml(sesiones, K1, ruta, env)
    exportado = yaml.safe_dump(await registro_bd.exportar_yaml(sesiones))
    assert not any(v in exportado for v in env.values())
    salida = tmp_path / "export.yaml"
    salida.write_text(exportado)
    # las referencias *_env derivadas se resuelven con las mismas variables bajo otros nombres
    nuevo_env = {"A_AUTH_HS256": env["a_SECRETO"], "A_TOKEN_MANIFIESTO": env["a_MANIFEST"],
                 "B_AUTH_HS256": env["b_SECRETO"], "B_TOKEN_MANIFIESTO": env["b_MANIFEST"],
                 "B_LLM_API_KEY": env["b_LLM"]}
    r2 = registro_desde_yaml(salida, env=nuevo_env)
    r1 = registro_desde_yaml(ruta, env=env)
    assert r2.errores == {}
    for sid in ("a", "b"):
        for tool in (ESCRITURA, LECTURA):
            assert tool_permitida(r2.obtener(sid), tool) == tool_permitida(r1.obtener(sid), tool)
        assert r2.secreto(sid, "token_manifiesto") == r1.secreto(sid, "token_manifiesto")


async def test_importar_exige_reemplazar_y_es_todo_o_nada(sesiones, yaml_dos, tmp_path):
    ruta, env = yaml_dos
    await registro_bd.importar_yaml(sesiones, K1, ruta, env)
    with pytest.raises(ErrorRegistro, match="reemplazar"):
        await registro_bd.importar_yaml(sesiones, K1, ruta, env)
    malo = escribir_registro(tmp_path / "m.yaml", [entrada_sistema("c"), entrada_sistema("d", base_url="ftp://x")])
    with pytest.raises(ErrorRegistro, match="no se importó nada"):
        await registro_bd.importar_yaml(sesiones, K1, malo, entorno("c", "d"), reemplazar=True)
    r, _ = await _registro(sesiones)
    assert {s.id for s in r.todos()} == {"a", "b"}  # intacto


async def test_clave_equivocada_deja_a_ese_sistema_en_errores(sesiones, yaml_dos):
    ruta, env = yaml_dos
    await registro_bd.importar_yaml(sesiones, K1, ruta, env)
    r, _ = await _registro(sesiones, K9)
    assert r.todos() == [] and set(r.errores) == {"a", "b"}
    assert "k1" in r.errores["a"] and env["a_SECRETO"] not in r.errores["a"]


async def test_sin_variables_de_entorno_el_modo_bd_no_cae_al_entorno(sesiones, yaml_dos, monkeypatch):
    ruta, env = yaml_dos
    await registro_bd.importar_yaml(sesiones, K1, ruta, env)
    await registro_bd.importar_yaml(sesiones, K1, ruta, env, reemplazar=True)
    async with sesiones() as s, s.begin():
        await s.execute(delete(SistemaSecreto).where(SistemaSecreto.sistema_id == "a",
                                                     SistemaSecreto.campo == "token_manifiesto"))
    monkeypatch.setenv("a_MANIFEST", "del-entorno")
    r, _ = await _registro(sesiones)
    assert r.obtener("a") is None and "token_manifiesto" in r.errores["a"]


async def test_dos_replicas_ven_el_cambio_y_descartan_cachés(sesiones, yaml_dos, tmp_path):
    ruta, env = yaml_dos
    await registro_bd.importar_yaml(sesiones, K1, ruta, env)
    r1, f1 = await _registro(sesiones)
    r2, f2 = await _registro(sesiones)
    descartados = []
    r2.suscribir(descartados.append)
    await f2.sondear()
    assert descartados == [] and f2.version == f1.version  # sin cambios, sin recarga

    # «deshabilitar a» en la BD (lo que hará el panel): config + versión en la misma transacción
    async with sesiones() as s, s.begin():
        await s.execute(update(SistemaRegistro).where(SistemaRegistro.id == "a").values(habilitado=False))
        await registro_bd.incrementar_version(s)
    assert r2.obtener("a") is not None
    await f2.sondear()
    assert r2.obtener("a") is None and r2.obtener("b") is not None
    assert descartados == [{"a"}]
    with pytest.raises(TokenInvalido):
        await Autenticador(r2).validar(firmar("a"))
    assert r1.obtener("a") is not None  # r1 aún no sondeó


async def test_registro_no_listo_hasta_cargar(sesiones):
    f = FuenteBD(RegistroSistemas(), sesiones, K1)
    assert f.listo is False
    await f.cargar()
    assert f.listo is True


async def test_rotar_clave(sesiones, yaml_dos):
    ruta, env = yaml_dos
    await registro_bd.importar_yaml(sesiones, K1, ruta, env)
    assert await registro_bd.rotar_clave(sesiones, K2_K1) == 5
    assert await registro_bd.rotar_clave(sesiones, K2_K1) == 0
    solo_nueva = Cifrador.desde_texto(f"k2:{_clave(2)}")
    r, _ = await _registro(sesiones, solo_nueva)  # la vieja ya se puede retirar
    assert r.errores == {} and r.secreto("a", "token_manifiesto") == env["a_MANIFEST"]


async def test_rotar_no_escribe_nada_si_falta_la_clave_vieja(sesiones, yaml_dos):
    ruta, env = yaml_dos
    await registro_bd.importar_yaml(sesiones, K1, ruta, env)
    with pytest.raises(Exception):  # noqa: B017 - ClaveAusente
        await registro_bd.rotar_clave(sesiones, K9)
    async with sesiones() as s:
        assert {x.kid for x in (await s.execute(select(SistemaSecreto))).scalars()} == {"k1"}


async def test_acciones_habilitadas_pasan_a_tool_estado(sesiones, yaml_dos):
    ruta, env = yaml_dos
    await registro_bd.importar_yaml(sesiones, K1, ruta, env)
    async with sesiones() as s:
        filas = (await s.execute(select(ToolEstado))).scalars().all()
        config = (await s.execute(select(SistemaRegistro.config).where(SistemaRegistro.id == "a"))).scalar_one()
    assert [(f.sistema_id, f.tool, f.habilitada) for f in filas] == [("a", "agregar_nota", True)]
    assert "acciones_habilitadas" not in config


def test_entradas_desde_yaml_no_expone_secretos_en_repr(yaml_dos):
    ruta, env = yaml_dos
    assert not any(v in repr(entradas_desde_yaml(ruta, env)) for v in env.values())
