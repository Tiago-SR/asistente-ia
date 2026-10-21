"""Escrituras del panel sobre el registro en BD: versión, secretos, regla de `base_url`, tools y auditoría."""

import base64
import os

import pytest
from sqlalchemy import delete, select
from sqlalchemy.ext.asyncio import async_sessionmaker, create_async_engine

from asistente.sistemas import escritura
from asistente.sistemas.cifrado import Cifrador
from asistente.sistemas.escritura import ErrorEscritura
from asistente.sistemas.registro_bd import leer_registro
from asistente.store.models import (
    AdminAuditoria,
    Base,
    RegistroVersion,
    SistemaRegistro,
    SistemaSecreto,
    ToolEstado,
)

pytestmark = pytest.mark.skipif(
    not os.environ.get("ASISTENTE_DATABASE_URL"), reason="requiere Postgres (ASISTENTE_DATABASE_URL)"
)

CIFRADOR = Cifrador.desde_texto("k1:" + base64.b64encode(bytes([7]) * 32).decode())
TOKEN = "token-manifiesto-" + "x" * 8
CONFIG = {
    "id": "acme", "nombre": "Acme", "base_url": "https://acme.example",
    "auth": {"algoritmo": "RS256", "jwks_url": "https://acme.example/jwks"}, "conector": {},
}


@pytest.fixture
async def sesiones():
    motor = create_async_engine(os.environ["ASISTENTE_DATABASE_URL"])
    async with motor.begin() as c:
        await c.run_sync(Base.metadata.create_all)
    fabrica = async_sessionmaker(motor, expire_on_commit=False)

    async def limpiar():
        async with fabrica() as s, s.begin():
            await s.execute(delete(SistemaRegistro))
            await s.execute(delete(RegistroVersion))
            await s.execute(delete(AdminAuditoria))

    await limpiar()
    yield fabrica
    await limpiar()
    await motor.dispose()


async def _creado(sesiones, **cambios) -> dict:
    return await escritura.crear_sistema(sesiones, {**CONFIG, **cambios}, por="ana")


def _cuerpo(vista: dict, **cambios) -> dict:
    return {**vista["config"], **cambios}


async def _habilitado(sesiones) -> dict:
    """Sistema ya habilitado y con token (el estado normal de producción)."""
    v = await _creado(sesiones)
    return await escritura.actualizar_sistema(
        sesiones, CIFRADOR, "acme", _cuerpo(v, habilitado=True), v["version"],
        token_manifiesto=TOKEN, por="ana")


async def _codigo(coro) -> ErrorEscritura:
    with pytest.raises(ErrorEscritura) as e:
        await coro
    return e.value


async def test_crear_es_deshabilitado_y_no_duplica(sesiones):
    v = await _creado(sesiones, habilitado=True)  # pedir habilitado no se respeta
    assert v["config"]["habilitado"] is False and v["version"] == 1
    assert (await _codigo(_creado(sesiones))).codigo == "sistema_existente"


async def test_crear_rechaza_config_invalida_sin_eco_de_valores(sesiones):
    e = await _codigo(_creado(sesiones, base_url="https://u:clave-secreta@x.example"))
    assert e.estado == 422 and "clave-secreta" not in str(e.datos)


async def test_actualizar_exige_version_y_devuelve_la_actual(sesiones):
    v = await _habilitado(sesiones)
    e = await _codigo(escritura.actualizar_sistema(
        sesiones, CIFRADOR, "acme", _cuerpo(v), 1, por="ana"))
    assert (e.estado, e.codigo, e.datos) == (409, "version_obsoleta", {"version": v["version"]})


async def test_habilitar_sin_token_se_rechaza(sesiones):
    v = await _creado(sesiones)
    e = await _codigo(escritura.actualizar_sistema(
        sesiones, CIFRADOR, "acme", _cuerpo(v, habilitado=True), v["version"], por="ana"))
    assert e.codigo == "faltan_secretos" and e.datos == {"faltan": ["token_manifiesto"]}


async def test_cambiar_base_url_sin_token_no_apaga_en_silencio(sesiones):
    v = await _habilitado(sesiones)
    e = await _codigo(escritura.actualizar_sistema(
        sesiones, CIFRADOR, "acme", _cuerpo(v, base_url="https://otro.example"), v["version"], por="ana"))
    assert e.codigo == "base_url_requiere_token"
    # nada cambió, y el token sigue ahí
    assert (await escritura.leer(sesiones, "acme"))["secretos"]["token_manifiesto"]["configurado"]


async def test_cambiar_base_url_con_token_nuevo_es_atomico(sesiones):
    v = await _habilitado(sesiones)
    h0 = v["secretos"]["token_manifiesto"]["huella"]
    n = await escritura.actualizar_sistema(
        sesiones, CIFRADOR, "acme", _cuerpo(v, base_url="https://otro.example"), v["version"],
        token_manifiesto="otro-token-manifiesto", por="ana")
    assert n["config"]["base_url"] == "https://otro.example" and n["config"]["habilitado"] is True
    assert n["secretos"]["token_manifiesto"]["huella"] != h0 and n["version"] == v["version"] + 1


async def test_cambiar_base_url_deshabilitando_borra_el_token(sesiones):
    v = await _habilitado(sesiones)
    n = await escritura.actualizar_sistema(
        sesiones, CIFRADOR, "acme", _cuerpo(v, base_url="https://otro.example", habilitado=False),
        v["version"], por="ana")
    assert n["secretos"]["token_manifiesto"] == {"configurado": False}


async def test_cambiar_llm_base_url_borra_la_clave_del_llm(sesiones):
    v = await _habilitado(sesiones)
    v = await escritura.guardar_secreto(sesiones, CIFRADOR, "acme", "llm_api_key", "sk-propia", v["version"],
                                        por="ana")
    n = await escritura.actualizar_sistema(
        sesiones, CIFRADOR, "acme", _cuerpo(v, llm={"base_url": "https://llm.malo.example"}), v["version"],
        por="ana")
    assert n["secretos"]["llm_api_key"] == {"configurado": False}
    assert n["secretos"]["token_manifiesto"]["configurado"]  # el otro secreto no se toca


async def test_los_secretos_nunca_salen_ni_se_auditan(sesiones):
    v = await _habilitado(sesiones)
    assert TOKEN not in str(v)
    async with sesiones() as s:
        filas = (await s.execute(select(AdminAuditoria))).scalars().all()
        cifrado = (await s.execute(select(SistemaSecreto))).scalars().one()
    assert filas and all(TOKEN not in f"{f.antes}{f.despues}" for f in filas)
    assert TOKEN.encode() not in cifrado.cifrado
    assert any(f.accion == "secretos_cambiados" and f.despues == {"cargados": ["token_manifiesto"], "borrados": []}
               for f in filas)


async def test_secretos_se_validan(sesiones):
    v = await _creado(sesiones, auth={"algoritmo": "HS256"})
    for valor, codigo in (("", "secreto_invalido"), (" x ", "secreto_invalido"), ("corto", "secreto_corto")):
        e = await _codigo(escritura.guardar_secreto(sesiones, CIFRADOR, "acme", "auth_hs256", valor,
                                                    v["version"], por="ana"))
        assert e.codigo == codigo
    e = await _codigo(escritura.guardar_secreto(sesiones, CIFRADOR, "acme", "otro", "valor", v["version"],
                                                por="ana"))
    assert e.codigo == "campo_desconocido"
    ok = await escritura.guardar_secreto(sesiones, CIFRADOR, "acme", "auth_hs256", "h" * 32, v["version"],
                                         por="ana")
    assert ok["secretos"]["auth_hs256"]["configurado"]


async def test_pasar_de_hs256_a_rs256_borra_el_secreto_huerfano(sesiones):
    v = await _creado(sesiones, auth={"algoritmo": "HS256"})
    v = await escritura.guardar_secreto(sesiones, CIFRADOR, "acme", "auth_hs256", "h" * 32, v["version"],
                                        por="ana")
    n = await escritura.actualizar_sistema(
        sesiones, CIFRADOR, "acme",
        _cuerpo(v, auth={"algoritmo": "RS256", "jwks_url": "https://acme.example/jwks"}), v["version"], por="ana")
    assert n["secretos"]["auth_hs256"] == {"configurado": False}


async def test_pasar_a_hs256_con_secreto_en_un_solo_guardado(sesiones):
    v = await _creado(sesiones)  # RS256 + jwks_url
    n = await escritura.actualizar_sistema(
        sesiones, CIFRADOR, "acme", _cuerpo(v, auth={"algoritmo": "HS256"}), v["version"],
        auth_hs256="h" * 32, por="ana")
    assert n["secretos"]["auth_hs256"]["configurado"]


async def test_secreto_hs256_con_otro_algoritmo_no_aplica(sesiones):
    v = await _creado(sesiones)
    e = await _codigo(escritura.actualizar_sistema(
        sesiones, CIFRADOR, "acme", _cuerpo(v), v["version"], auth_hs256="h" * 32, por="ana"))
    assert e.codigo == "secreto_no_aplica"


async def test_borrar_secreto_requerido_de_un_sistema_habilitado_se_rechaza(sesiones):
    v = await _habilitado(sesiones)
    e = await _codigo(escritura.borrar_secreto(sesiones, "acme", "token_manifiesto", v["version"], por="ana"))
    assert e.codigo == "secreto_requerido"


async def test_dos_escrituras_con_la_misma_version_una_pierde(sesiones):
    v = await _habilitado(sesiones)
    await escritura.actualizar_sistema(sesiones, CIFRADOR, "acme", _cuerpo(v, nombre="Uno"), v["version"],
                                       por="ana")
    e = await _codigo(escritura.actualizar_sistema(sesiones, CIFRADOR, "acme", _cuerpo(v, nombre="Dos"),
                                                   v["version"], por="ana"))
    assert e.codigo == "version_obsoleta"


async def test_campos_reservados_no_se_editan_por_el_put(sesiones):
    v = await _creado(sesiones)
    for extra in ({"id": "otro"}, {"tool_estado": {"x": True}}, {"acciones_habilitadas": ["x"]}):
        e = await _codigo(escritura.actualizar_sistema(
            sesiones, CIFRADOR, "acme", _cuerpo(v, **extra), v["version"], por="ana"))
        assert e.codigo == "campo_reservado"


async def test_tool_guarda_solo_excepciones_y_aparece_en_el_registro(sesiones):
    await _habilitado(sesiones)
    est = await escritura.fijar_tool(sesiones, "acme", "agregar_nota", True, False, por="ana")
    assert est == {"agregar_nota": True}
    est = await escritura.fijar_tool(sesiones, "acme", "ver", False, True, por="ana")
    assert est == {"agregar_nota": True, "ver": False}
    # volver al valor por defecto borra la fila
    est = await escritura.fijar_tool(sesiones, "acme", "agregar_nota", False, False, por="ana")
    assert est == {"ver": False}
    async with sesiones() as s:
        assert len((await s.execute(select(ToolEstado))).scalars().all()) == 1
    _, entradas = await leer_registro(sesiones, CIFRADOR)
    assert entradas[0].config["tool_estado"] == {"ver": False}
    assert (await _codigo(escritura.fijar_tool(sesiones, "acme", "mal nombre", True, False, por="ana"))).estado == 422
    assert (await _codigo(escritura.fijar_tool(sesiones, "no", "ver", True, True, por="ana"))).estado == 404


async def test_cada_escritura_sube_la_version_del_registro(sesiones):
    async def version():
        async with sesiones() as s:
            return (await s.execute(select(RegistroVersion.version))).scalar_one()

    v = await _creado(sesiones)
    v1 = await version()
    await escritura.fijar_tool(sesiones, "acme", "ver", False, True, por="ana")
    assert await version() == v1 + 1
    await escritura.guardar_secreto(sesiones, CIFRADOR, "acme", "token_manifiesto", TOKEN, v["version"], por="ana")
    assert await version() == v1 + 2
