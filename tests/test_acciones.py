# ruff: noqa: F811  (se reutilizan fixtures de test_api.py por importación)
"""Fase 5: acciones con confirmación, de punta a punta (asistente + mock + Postgres).

El modelo solo propone; el usuario confirma con un token de escritura que emite el SISTEMA para esa
confirmación. Reutiliza las fixtures de `test_api.py`.
"""

import asyncio
import json
import os
import uuid
from datetime import UTC, datetime, timedelta

import pytest
from sqlalchemy import select, update

from asistente.core.llm.base import LlamadaTool
from asistente.core.llm.falso import pide, texto
from asistente.store.models import Accion
from asistente.store.models import LlamadaTool as FilaLlamada
from conftest import firmar as _firmar
from test_aislamiento import resultado_de_tool, trafico  # noqa: F401
from test_api import (  # noqa: F401  (fixtures y helpers de la API de punta a punta)
    api,
    auth,
    chatear,
    construir_app,
    llm,
    sesiones,
    sse,
    sub,
)

pytestmark = pytest.mark.skipif(
    not os.environ.get("ASISTENTE_DATABASE_URL"), reason="sin ASISTENTE_DATABASE_URL"
)

def firmar(*a, **kw):
    if kw.get("scope") == "asistente:escritura":
        kw.setdefault("exp", int(datetime.now(UTC).timestamp()) + 60)
    return _firmar(*a, **kw)


HABILITADAS = ("agregar_nota", "modificar_nota")


def agregar(texto_nota="Helada en el potrero", est="1", id_="c1") -> LlamadaTool:
    return LlamadaTool(id_, "agregar_nota", {"establecimiento_id": est, "texto": texto_nota})


def modificar(nota_id, texto_nota="Texto nuevo", id_="c1") -> LlamadaTool:
    return LlamadaTool(id_, "modificar_nota", {"nota_id": nota_id, "texto": texto_nota})


@pytest.fixture
async def acc(construir_app):
    async with construir_app(acciones_habilitadas=HABILITADAS) as c:
        yield c


@pytest.fixture
def ana(mock_a):
    u = sub()
    mock_a.DATOS[u] = [{"id": "1", "nombre": "El Matorral", "superficie_ha": 10.0, "cultivo": "soja"}]
    mock_a.NOTAS[u] = [{"id": f"n-{u}", "establecimiento_id": "1", "texto": "Texto viejo", "version": 1}]
    return u


async def proponer(cliente, llm, usuario, llamada, conv=None):
    """Chatea hasta que el modelo propone una acción; devuelve (evento confirmacion, eventos)."""
    llm.usar(pide(llamada), texto("Te pedí confirmar la acción."))
    ev = sse(await chatear(cliente, "hacelo", conv=conv, usuario=usuario))
    conf = [d for e, d in ev if e == "confirmacion"]
    return (conf[0] if conf else None), ev


async def token_escritura(cliente_mocks, usuario, conf, **cambios):
    """El token que emite el sistema (no el asistente) cuando el usuario hace clic en Confirmar."""
    r = await cliente_mocks.get("http://mock-a/asistente/token", params={
        "usuario": usuario, "confirmacion": cambios.get("cid", conf["id"]), "huella": conf["huella"]})
    assert r.status_code == 200, r.text
    return r.json()["token"]


async def confirmar(cliente, conf, token, **kw):
    return await cliente.post(f"/v1/confirmaciones/{conf['id']}/confirmar",
                              headers={"Authorization": f"Bearer {token}"}, **kw)


# --- flujo feliz ------------------------------------------------------------------------------------


async def test_proponer_no_escribe_y_confirmar_si(acc, llm, mock_a, ana, cliente_mocks, sesiones, trafico):
    conf, ev = await proponer(acc, llm, ana, agregar())
    assert conf["tool"] == "agregar_nota"
    # el resumen salió del sistema, con su formato, no del modelo
    assert conf["resumen"] == "Agregar una nota al establecimiento «El Matorral»"
    assert conf["lineas"] == ["Texto: Helada en el potrero"]
    assert ev[-1][0] == "done"
    guion_modelo = resultado_de_tool(llm.actual, 1)
    assert guion_modelo["datos"]["estado"] == "pendiente_de_confirmacion"
    assert "NO se ha ejecutado" in guion_modelo["datos"]["instruccion"]

    # nada se escribió, y el asistente solo llamó a /propuesta (nunca a la ejecución)
    assert [n["id"] for n in mock_a.NOTAS[ana]] == [f"n-{ana}"]
    rutas = [r.url.path for r in trafico if r.method == "POST"]
    assert rutas == ["/asistente/tools/agregar_nota/propuesta"]

    token = await token_escritura(cliente_mocks, ana, conf)
    r = await confirmar(acc, conf, token)
    assert r.status_code == 200, r.text
    assert r.json()["estado"] == "ejecutada" and r.json()["mensaje"] == "Nota agregada."
    assert [n["texto"] for n in mock_a.NOTAS[ana]][-1] == "Helada en el potrero"

    # estado, auditoría (propuesta y ejecución) e historial
    async with sesiones() as s:
        fila = (await s.execute(select(Accion).where(Accion.id == uuid.UUID(conf["id"])))).scalar_one()
        tools = (await s.execute(
            select(FilaLlamada.tool).where(FilaLlamada.usuario_ref == ana).order_by(FilaLlamada.id)
        )).scalars().all()
    assert fila.estado == "ejecutada" and fila.ok is True
    assert tools == ["agregar_nota#propuesta", "agregar_nota"]
    conv = ev[-1][1]["conversacion_id"]
    hist = (await acc.get(f"/v1/conversaciones/{conv}", headers=auth(usuario=ana))).json()["mensajes"]
    assert hist[-1]["texto"].startswith("[Aviso del sistema] Acción realizada: Agregar una nota")


async def test_modificar_muestra_antes_y_despues(acc, llm, mock_a, ana, cliente_mocks):
    conf, _ = await proponer(acc, llm, ana, modificar(f"n-{ana}", "Texto nuevo"))
    assert conf["lineas"] == ["Antes: Texto viejo", "Después: Texto nuevo"]
    r = await confirmar(acc, conf, await token_escritura(cliente_mocks, ana, conf))
    assert r.json()["estado"] == "ejecutada"
    assert mock_a.NOTAS[ana][0]["texto"] == "Texto nuevo" and mock_a.NOTAS[ana][0]["version"] == 2


async def test_modificar_con_dato_cambiado_da_conflicto(acc, llm, mock_a, ana, cliente_mocks):
    conf, _ = await proponer(acc, llm, ana, modificar(f"n-{ana}"))
    mock_a.NOTAS[ana][0].update(texto="Cambiada por otra persona", version=2)  # cambió tras la propuesta
    r = await confirmar(acc, conf, await token_escritura(cliente_mocks, ana, conf))
    assert r.json() == {"estado": "fallida", "ok": False, "error": "conflicto",
                        "detalle": "La nota cambió desde que se propuso"}
    assert mock_a.NOTAS[ana][0]["texto"] == "Cambiada por otra persona"


# --- habilitación ----------------------------------------------------------------------------------


async def test_sin_acciones_habilitadas_el_modelo_no_ve_la_escritura(api, llm, ana):
    llm.usar(pide(agregar()), texto("No puedo."))
    ev = sse(await chatear(api, "anotá algo", usuario=ana))
    assert "agregar_nota" not in [t.nombre for t in llm.actual.llamadas[0].tools]
    assert "confirmacion" not in [e for e, _ in ev]
    assert resultado_de_tool(llm.actual, 1)["error"] == "no_disponible"


async def test_una_escritura_sin_declarar_confirmacion_no_se_ofrece(construir_app, llm, ana):
    async with construir_app(acciones_habilitadas=("eliminar_establecimiento", *HABILITADAS)) as c:
        llm.usar(pide(LlamadaTool("c1", "eliminar_establecimiento", {"id": "1"})), texto("No."))
        ev = sse(await chatear(c, "borrá", usuario=ana))
    nombres = [t.nombre for t in llm.actual.llamadas[0].tools]
    assert "eliminar_establecimiento" not in nombres and "agregar_nota" in nombres
    assert "confirmacion" not in [e for e, _ in ev]


# --- una por turno, reemplazo y límite -----------------------------------------------------------


async def test_dos_escrituras_en_un_turno_solo_proponen_la_primera(acc, llm, ana):
    llm.usar(pide(agregar(id_="c1"), agregar("otra", id_="c2")), texto("Una a la vez."))
    ev = sse(await chatear(acc, "dos notas", usuario=ana))
    assert [e for e, _ in ev].count("confirmacion") == 1
    msgs = [m for m in llm.actual.llamadas[1].messages if m.rol == "tool"]
    assert json.loads(msgs[1].texto)["error"] == "una_accion_a_la_vez"


async def test_una_propuesta_nueva_reemplaza_a_la_pendiente(acc, llm, ana, cliente_mocks, sesiones):
    primera, ev = await proponer(acc, llm, ana, agregar("primera"))
    conv = ev[-1][1]["conversacion_id"]
    segunda, _ = await proponer(acc, llm, ana, agregar("segunda"), conv=conv)
    r = await confirmar(acc, primera, await token_escritura(cliente_mocks, ana, primera))
    assert r.status_code == 409 and r.json() == {"error": "accion_no_pendiente", "estado": "reemplazada"}
    r = await confirmar(acc, segunda, await token_escritura(cliente_mocks, ana, segunda))
    assert r.json()["estado"] == "ejecutada"


async def test_tope_de_propuestas_por_hora(construir_app, llm, ana):
    async with construir_app(acciones_habilitadas=HABILITADAS, max_acciones_hora=2) as c:
        for i in range(2):
            conf, _ = await proponer(c, llm, ana, agregar(f"n{i}"))
            assert conf
        conf, _ = await proponer(c, llm, ana, agregar("n3"))
    assert conf is None
    assert resultado_de_tool(llm.actual, 1)["error"] == "acciones_hora"


# --- un solo uso, vencimiento y cancelación -------------------------------------------------------------


async def test_doble_confirmacion_concurrente_ejecuta_una_sola_vez(acc, llm, mock_a, ana, cliente_mocks):
    conf, _ = await proponer(acc, llm, ana, agregar())
    token = await token_escritura(cliente_mocks, ana, conf)
    r1, r2 = await asyncio.gather(confirmar(acc, conf, token), confirmar(acc, conf, token))
    assert sorted([r1.status_code, r2.status_code]) == [200, 409]
    assert len(mock_a.NOTAS[ana]) == 2  # la original y una sola nota nueva
    r3 = await confirmar(acc, conf, token)
    assert r3.status_code == 409 and r3.json()["estado"] == "ejecutada"


async def test_confirmacion_vencida(acc, llm, mock_a, ana, cliente_mocks, sesiones):
    conf, _ = await proponer(acc, llm, ana, agregar())
    async with sesiones.begin() as s:
        await s.execute(update(Accion).where(Accion.id == uuid.UUID(conf["id"]))
                        .values(expira=datetime.now(UTC) - timedelta(seconds=1)))
    r = await confirmar(acc, conf, await token_escritura(cliente_mocks, ana, conf))
    assert r.status_code == 409 and r.json()["estado"] == "expirada"
    assert len(mock_a.NOTAS[ana]) == 1


async def test_cancelar(acc, llm, mock_a, ana, cliente_mocks):
    conf, ev = await proponer(acc, llm, ana, agregar())
    r = await acc.post(f"/v1/confirmaciones/{conf['id']}/cancelar", headers=auth(usuario=ana))
    assert r.status_code == 200 and r.json() == {"estado": "cancelada"}
    r = await confirmar(acc, conf, await token_escritura(cliente_mocks, ana, conf))
    assert r.status_code == 409 and r.json()["estado"] == "cancelada"
    assert len(mock_a.NOTAS[ana]) == 1
    conv = ev[-1][1]["conversacion_id"]
    hist = (await acc.get(f"/v1/conversaciones/{conv}", headers=auth(usuario=ana))).json()["mensajes"]
    assert hist[-1]["texto"].startswith("[Aviso del sistema] Acción cancelada por el usuario")


# --- el token y el aislamiento ------------------------------------------------------------------------


async def test_un_token_de_lectura_no_confirma(acc, llm, mock_a, ana):
    conf, _ = await proponer(acc, llm, ana, agregar())
    r = await acc.post(f"/v1/confirmaciones/{conf['id']}/confirmar", headers=auth(usuario=ana))
    assert r.status_code == 401
    assert len(mock_a.NOTAS[ana]) == 1


async def test_token_de_escritura_de_otra_confirmacion_o_huella_no_sirve_y_no_gasta_la_accion(
    acc, llm, mock_a, ana, cliente_mocks
):
    conf, _ = await proponer(acc, llm, ana, agregar())
    otro_id = firmar("mock-a", ana, scope="asistente:escritura", act="agregar_nota",
                     ph=conf["huella"], cid=str(uuid.uuid4()))
    otra_huella = firmar("mock-a", ana, scope="asistente:escritura", act="agregar_nota",
                         ph="0" * 64, cid=conf["id"])
    otra_tool = firmar("mock-a", ana, scope="asistente:escritura", act="modificar_nota",
                       ph=conf["huella"], cid=conf["id"])
    for malo in (otro_id, otra_huella, otra_tool):
        r = await confirmar(acc, conf, malo)
        assert r.status_code == 403 and r.json() == {"error": "confirmacion_invalida"}
    assert len(mock_a.NOTAS[ana]) == 1
    # sigue pendiente: el token correcto todavía funciona
    r = await confirmar(acc, conf, await token_escritura(cliente_mocks, ana, conf))
    assert r.json()["estado"] == "ejecutada"


async def test_el_token_de_escritura_sin_act_ph_cid_se_rechaza(acc, llm, ana):
    conf, _ = await proponer(acc, llm, ana, agregar())
    sin_claims = firmar("mock-a", ana, scope="asistente:escritura")
    assert (await confirmar(acc, conf, sin_claims)).status_code == 401


async def test_el_token_de_escritura_de_vida_larga_se_rechaza(acc, llm, ana):
    conf, _ = await proponer(acc, llm, ana, agregar())
    largo = firmar("mock-a", ana, scope="asistente:escritura", act="agregar_nota", ph=conf["huella"],
                   cid=conf["id"], exp=int(datetime.now(UTC).timestamp()) + 3600)
    assert (await confirmar(acc, conf, largo)).status_code == 401


async def test_otro_usuario_u_otro_sistema_no_ven_ni_confirman_la_accion(acc, llm, mock_a, ana, cliente_mocks):
    conf, _ = await proponer(acc, llm, ana, agregar())
    beto = sub()
    mock_a.DATOS[beto] = []
    # el sistema no emite a beto un token para la huella de ana
    r = await cliente_mocks.get("http://mock-a/asistente/token", params={
        "usuario": beto, "confirmacion": conf["id"], "huella": conf["huella"]})
    assert r.status_code == 403
    # y aunque tuviera un token de escritura válido propio, la acción de ana no existe para él
    tok_beto = firmar("mock-a", beto, scope="asistente:escritura", act="agregar_nota",
                      ph=conf["huella"], cid=conf["id"])
    assert (await confirmar(acc, conf, tok_beto)).status_code == 404
    assert (await acc.post(f"/v1/confirmaciones/{conf['id']}/cancelar", headers=auth(usuario=beto))
            ).status_code == 404
    assert (await acc.get(f"/v1/confirmaciones/{conf['id']}", headers=auth(usuario=beto))).status_code == 404
    # otro sistema (mock-b), mismo sub
    tok_b = firmar("mock-b", ana, scope="asistente:escritura", act="agregar_nota",
                   ph=conf["huella"], cid=conf["id"])
    assert (await confirmar(acc, conf, tok_b)).status_code == 404
    assert len(mock_a.NOTAS[ana]) == 1


async def test_ver_la_accion_propia(acc, llm, ana):
    conf, _ = await proponer(acc, llm, ana, agregar())
    r = await acc.get(f"/v1/confirmaciones/{conf['id']}", headers=auth(usuario=ana))
    assert r.status_code == 200 and r.json()["estado"] == "pendiente"
    assert r.json()["resumen"] == conf["resumen"]


async def test_un_origen_no_permitido_no_confirma(acc, llm, ana, cliente_mocks):
    conf, _ = await proponer(acc, llm, ana, agregar())
    token = await token_escritura(cliente_mocks, ana, conf)
    r = await acc.post(
        f"/v1/confirmaciones/{conf['id']}/confirmar",
        headers={"Authorization": f"Bearer {token}", "Origin": "https://malo.example"})
    assert r.status_code == 403
