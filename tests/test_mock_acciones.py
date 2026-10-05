"""Contrato de las acciones con confirmación (sección 8) contra el sistema mock, sin el asistente.

Cada regla que el sistema debe cumplir tiene su prueba, y cada defecto deliberado del mock
(`MOCK_DEFECTO`) la rompe: son las comprobaciones del verificador de conformidad.
"""

import time

import httpx
import jwt
import pytest

from conftest import cargar_mock, firmar

ANA = "ana"
AGREGAR = {"establecimiento_id": "1", "texto": "Helada"}


def montar(monkeypatch, defecto: str = ""):
    monkeypatch.setenv("MOCK_DEFECTO", defecto)
    m = cargar_mock(monkeypatch, "mock-a")
    cliente = httpx.AsyncClient(transport=httpx.ASGITransport(app=m.app), base_url="http://mock-a")
    return m, cliente


def lectura() -> dict:
    return {"Authorization": f"Bearer {firmar('mock-a', ANA)}", "X-Asistente-Contrato": "1"}


async def proponer(c, nombre="agregar_nota", params=None):
    r = await c.post(f"/asistente/tools/{nombre}/propuesta", headers=lectura(),
                     json={"parametros": params or AGREGAR})
    assert r.status_code == 200, r.text
    return r.json()


async def token_escritura(c, huella, cid="c-1"):
    r = await c.get("/asistente/token", params={"usuario": ANA, "confirmacion": cid, "huella": huella})
    return r


def cab(token, clave="k1") -> dict:
    return {"Authorization": f"Bearer {token}", "X-Asistente-Contrato": "1", "Idempotency-Key": clave}


async def ejecutar(c, nombre, token, params=None, clave="k1"):
    return await c.post(f"/asistente/tools/{nombre}", headers=cab(token, clave),
                        json={"parametros": params or AGREGAR})


async def listo(c, nombre="agregar_nota", params=None):
    """Propone y obtiene el token de escritura: lo que haría el usuario al confirmar."""
    p = await proponer(c, nombre, params)
    return p, (await token_escritura(c, p["huella"])).json()["token"]


# --- el mock conforme ------------------------------------------------------------------------------


async def test_la_propuesta_no_tiene_efectos_y_trae_resumen_y_huella(monkeypatch):
    m, c = montar(monkeypatch)
    antes = list(m.NOTAS[ANA])
    p = await proponer(c)
    assert p["ok"] and p["resumen"] and len(p["huella"]) == 64 and p["expira_s"] <= 300
    assert m.NOTAS[ANA] == antes


async def test_la_escritura_con_token_de_lectura_se_rechaza(monkeypatch):
    m, c = montar(monkeypatch)
    r = await c.post("/asistente/tools/agregar_nota", headers={**lectura(), "Idempotency-Key": "k"},
                     json={"parametros": AGREGAR})
    assert r.status_code == 403 and len(m.NOTAS[ANA]) == 1


async def test_la_propuesta_con_token_de_escritura_se_rechaza(monkeypatch):
    _, c = montar(monkeypatch)
    _, tok = await listo(c)
    r = await c.post("/asistente/tools/agregar_nota/propuesta", headers=cab(tok), json={"parametros": AGREGAR})
    assert r.status_code == 403


async def test_el_sistema_no_emite_token_para_una_huella_que_no_conoce_ni_de_otro_usuario(monkeypatch):
    m, c = montar(monkeypatch)
    assert (await token_escritura(c, "f" * 64)).status_code == 403
    p = await proponer(c)
    m.DATOS["beto"] = []
    r = await c.get("/asistente/token", params={"usuario": "beto", "confirmacion": "c", "huella": p["huella"]})
    assert r.status_code == 403
    assert (await c.get("/asistente/token", params={"usuario": ANA, "huella": p["huella"]})).status_code == 400


async def test_token_de_escritura_corto_y_atado_a_tool_huella_y_confirmacion(monkeypatch):
    _, c = montar(monkeypatch)
    p, tok = await listo(c)
    cl = jwt.decode(tok, options={"verify_signature": False})
    assert cl["scope"] == "asistente:escritura" and cl["act"] == "agregar_nota"
    assert cl["ph"] == p["huella"] and cl["cid"] == "c-1" and cl["exp"] - cl["iat"] <= 120


async def test_ejecucion_conforme_e_idempotente(monkeypatch):
    m, c = montar(monkeypatch)
    p, tok = await listo(c)
    r1 = await ejecutar(c, "agregar_nota", tok)
    assert r1.status_code == 200 and r1.json()["ok"] and len(m.NOTAS[ANA]) == 2
    # reintento con la misma clave (con otro token, p. ej. si el primero se perdió): no reejecuta
    tok2 = (await token_escritura(c, p["huella"])).json()["token"]
    r2 = await ejecutar(c, "agregar_nota", tok2)
    assert r2.json() == r1.json() and len(m.NOTAS[ANA]) == 2


async def test_el_token_de_escritura_no_se_reutiliza(monkeypatch):
    m, c = montar(monkeypatch)
    _, tok = await listo(c)
    assert (await ejecutar(c, "agregar_nota", tok, clave="k1")).status_code == 200
    assert (await ejecutar(c, "agregar_nota", tok, clave="k2")).status_code == 403
    assert len(m.NOTAS[ANA]) == 2


async def test_el_token_no_sirve_para_otra_tool_ni_otros_parametros(monkeypatch):
    m, c = montar(monkeypatch)
    _, tok = await listo(c)
    otra = await ejecutar(c, "modificar_nota", tok, {"nota_id": m.NOTAS[ANA][0]["id"], "texto": "x"})
    assert otra.status_code == 403
    _, tok = await listo(c)
    cambiados = await ejecutar(c, "agregar_nota", tok, {**AGREGAR, "texto": "OTRO TEXTO"}, clave="k9")
    assert cambiados.status_code == 403 and len(m.NOTAS[ANA]) == 1


async def test_sin_idempotency_key_se_rechaza(monkeypatch):
    _, c = montar(monkeypatch)
    _, tok = await listo(c)
    r = await c.post("/asistente/tools/agregar_nota", json={"parametros": AGREGAR},
                     headers={"Authorization": f"Bearer {tok}", "X-Asistente-Contrato": "1"})
    assert r.status_code == 400


async def test_un_token_de_escritura_vencido_se_rechaza(monkeypatch):
    _, c = montar(monkeypatch)
    p = await proponer(c)
    ahora = int(time.time())
    viejo = firmar("mock-a", ANA, scope="asistente:escritura", act="agregar_nota", ph=p["huella"],
                   cid="c", iat=ahora - 200, exp=ahora - 100)
    assert (await ejecutar(c, "agregar_nota", viejo)).status_code == 401


async def test_modificar_detecta_que_el_dato_cambio(monkeypatch):
    m, c = montar(monkeypatch)
    nota = m.NOTAS[ANA][0]
    params = {"nota_id": nota["id"], "texto": "nuevo"}
    _, tok = await listo(c, "modificar_nota", params)
    nota["version"] += 1  # alguien más la tocó entre la propuesta y la confirmación
    r = await ejecutar(c, "modificar_nota", tok, params)
    assert r.status_code == 200 and r.json()["error"] == "conflicto" and nota["texto"] != "nuevo"


# --- defectos deliberados: cada uno rompe una regla ----------------------------------------------------


async def test_defecto_propuesta_con_efectos(monkeypatch):
    m, c = montar(monkeypatch, "propuesta_con_efectos")
    await proponer(c)
    assert len(m.NOTAS[ANA]) == 2  # la propuesta ya escribió


async def test_defecto_ph_ignorado(monkeypatch):
    m, c = montar(monkeypatch, "ph_ignorado")
    _, tok = await listo(c)
    r = await ejecutar(c, "agregar_nota", tok, {**AGREGAR, "texto": "OTRO TEXTO"})
    assert r.status_code == 200 and m.NOTAS[ANA][-1]["texto"] == "OTRO TEXTO"


async def test_defecto_replay_aceptado(monkeypatch):
    m, c = montar(monkeypatch, "replay_aceptado")
    _, tok = await listo(c)
    assert (await ejecutar(c, "agregar_nota", tok, clave="k1")).status_code == 200
    assert (await ejecutar(c, "agregar_nota", tok, clave="k2")).status_code == 200
    assert len(m.NOTAS[ANA]) == 3


async def test_defecto_token_otra_tool(monkeypatch):
    m, c = montar(monkeypatch, "token_otra_tool")
    _, tok = await listo(c)
    r = await ejecutar(c, "modificar_nota", tok, {"nota_id": m.NOTAS[ANA][0]["id"], "texto": "x"})
    assert r.status_code == 200 and m.NOTAS[ANA][0]["texto"] == "x"


async def test_defecto_sin_idempotencia(monkeypatch):
    m, c = montar(monkeypatch, "sin_idempotencia")
    p, tok = await listo(c)
    await ejecutar(c, "agregar_nota", tok)
    tok2 = (await token_escritura(c, p["huella"])).json()["token"]
    await ejecutar(c, "agregar_nota", tok2)  # misma clave: reejecuta
    assert len(m.NOTAS[ANA]) == 3


async def test_defecto_token_escritura_largo(monkeypatch):
    _, c = montar(monkeypatch, "token_escritura_largo")
    _, tok = await listo(c)
    cl = jwt.decode(tok, options={"verify_signature": False})
    assert cl["exp"] - cl["iat"] > 120


@pytest.mark.parametrize("defecto", ["propuesta_con_efectos", "ph_ignorado", "replay_aceptado",
                                     "token_otra_tool", "sin_idempotencia", "token_escritura_largo"])
def test_los_defectos_de_la_fase_5_estan_declarados(monkeypatch, defecto):
    assert defecto in montar(monkeypatch, defecto)[0].DEFECTOS
