"""API de escritura del panel (/admin/api/sistemas...): permisos, CSRF y sin eco de secretos."""

import base64
import os

import httpx
import pytest
from sqlalchemy import delete, select

from asistente.config import Settings
from asistente.core.prompts import Prompts
from asistente.limits import LimitesPostgres
from asistente.main import create_app
from asistente.servicios import Servicios
from asistente.sistemas.auth import Autenticador
from asistente.sistemas.cifrado import Cifrador
from asistente.sistemas.conector_http import ConectorHttp
from asistente.sistemas.manifiesto import CacheManifiestos
from asistente.sistemas.registro import RegistroSistemas
from asistente.sistemas.registro_bd import FuenteBD
from asistente.store.admin import AdminSql
from asistente.store.auditoria import AuditoriaSql
from asistente.store.models import (
    AdminAuditoria,
    AdminSesion,
    AdminUsuario,
    RegistroVersion,
    SistemaRegistro,
)
from asistente.store.repo import Repo
from test_api import sesiones  # noqa: F401

URL = os.environ.get("ASISTENTE_DATABASE_URL")
pytestmark = pytest.mark.skipif(not URL, reason="sin ASISTENTE_DATABASE_URL")

CLAVE = "una-clave-larga-123"
ORIGEN = {"Origin": "http://asistente"}
CIFRADOR = Cifrador.desde_texto("k1:" + base64.b64encode(bytes([5]) * 32).decode())
SECRETO = "token-manifiesto-ultra-secreto"
CONFIG = {"id": "acme", "nombre": "Acme", "base_url": "https://acme.example", "conector": {},
          "auth": {"algoritmo": "RS256", "jwks_url": "https://acme.example/jwks"}}


@pytest.fixture
async def limpio(sesiones):  # noqa: F811
    async def _limpiar():
        async with sesiones.begin() as s:
            for m in (AdminSesion, AdminUsuario, AdminAuditoria, SistemaRegistro, RegistroVersion):
                await s.execute(delete(m))
    await _limpiar()
    yield sesiones
    await _limpiar()


def _app(sesiones, tmp_path):  # noqa: F811
    (tmp_path / "base.md").write_text("Reglas base.", encoding="utf-8")
    (tmp_path / "voz.md").write_text("Resumen hablado.", encoding="utf-8")
    registro = RegistroSistemas()
    FuenteBD(registro, sesiones, CIFRADOR)
    manifiestos = CacheManifiestos(registro)
    svc = Servicios(
        settings=Settings(database_url=URL, admin_token="adm1n"),
        registro=registro, autenticador=Autenticador(registro), manifiestos=manifiestos,
        conector=ConectorHttp(registro, manifiestos), repo=Repo(sesiones),
        limites=LimitesPostgres(sesiones), auditoria=AuditoriaSql(sesiones),
        prompts=Prompts(tmp_path), llm_para=lambda s: None, sesiones=sesiones,
        admin=AdminSql(sesiones), cifrador=CIFRADOR,
    )
    return httpx.AsyncClient(transport=httpx.ASGITransport(app=create_app(svc)), base_url="http://asistente")


@pytest.fixture
def cliente(limpio, tmp_path):
    return lambda: _app(limpio, tmp_path)


async def _sesion(c, limpio, rol):
    await AdminSql(limpio).crear_usuario(f"{rol}@ejemplo.com", CLAVE, rol)
    r = await c.post("/admin/api/login", json={"email": f"{rol}@ejemplo.com", "clave": CLAVE}, headers=ORIGEN)
    assert r.status_code == 200
    return {"Cookie": f"__Host-admin={r.cookies.get('__Host-admin')}", "X-CSRF": r.json()["csrf"], **ORIGEN}


async def test_operador_y_token_estatico_no_escriben(cliente, limpio):
    async with cliente() as c:
        h = await _sesion(c, limpio, "operador")
        assert (await c.post("/admin/api/sistemas", json={"config": CONFIG}, headers=h)).status_code == 403
        t = {"Authorization": "Bearer adm1n"}
        r = await c.post("/admin/api/sistemas", json={"config": CONFIG}, headers=t)
        assert (r.status_code, r.json()["error"]) == (403, "permiso_insuficiente")
        # el operador sí lee
        assert (await c.get("/admin/api/sistemas", headers=h)).status_code == 200


async def test_admin_crea_edita_y_el_csrf_cubre_put_y_delete(cliente, limpio):
    async with cliente() as c:
        h = await _sesion(c, limpio, "admin")
        r = await c.post("/admin/api/sistemas", json={"config": CONFIG}, headers=h)
        assert r.status_code == 201 and r.json()["version"] == 1

        sin_csrf = {k: v for k, v in h.items() if k != "X-CSRF"}
        cuerpo = {"version": 1, "config": {**r.json()["config"], "habilitado": True},
                  "secretos": {"token_manifiesto": SECRETO}}
        assert (await c.put("/admin/api/sistemas/acme", json=cuerpo, headers=sin_csrf)).status_code == 403
        assert (await c.delete("/admin/api/sistemas/acme/secretos/token_manifiesto?version=1",
                               headers=sin_csrf)).status_code == 403

        r = await c.put("/admin/api/sistemas/acme", json=cuerpo, headers=h)
        assert r.status_code == 200 and r.json()["version"] == 2
        assert SECRETO not in r.text
        assert r.json()["secretos"]["token_manifiesto"]["configurado"] is True
        assert "aviso" not in r.json()

        g = await c.get("/admin/api/sistemas/acme", headers=h)
        assert SECRETO not in g.text and g.json()["activo"] is True
        lista = (await c.get("/admin/api/sistemas", headers=h)).json()["sistemas"]
        assert [x["id"] for x in lista] == ["acme"] and lista[0]["activo"] is True

        # versión vieja: 409 con la actual para que el panel recargue
        r = await c.put("/admin/api/sistemas/acme", json=cuerpo, headers=h)
        assert (r.status_code, r.json()) == (409, {"error": "version_obsoleta", "version": 2})


async def test_la_lista_no_espera_manifiestos_y_su_estado_va_aparte(cliente, limpio, monkeypatch):
    import asyncio

    from asistente.api import admin as api_admin
    from asistente.sistemas.manifiesto import CacheManifiestos, ManifiestoInvalido

    llamadas = []

    async def obtener(self, sistema_id):
        llamadas.append(sistema_id)
        if sistema_id == "lento":
            await asyncio.sleep(5)
        raise ManifiestoInvalido("sin credencial")

    monkeypatch.setattr(CacheManifiestos, "obtener", obtener)
    monkeypatch.setattr(api_admin, "_ESPERA_MANIFIESTO_S", 0.05)
    async with cliente() as c:
        h = await _sesion(c, limpio, "admin")
        for id_ in ("acme", "lento"):
            r = await c.post("/admin/api/sistemas", json={"config": {**CONFIG, "id": id_}}, headers=h)
            cuerpo = {"version": 1, "config": {**r.json()["config"], "habilitado": True},
                      "secretos": {"token_manifiesto": SECRETO}}
            assert (await c.put(f"/admin/api/sistemas/{id_}", json=cuerpo, headers=h)).status_code == 200

        # la lista sale de la BD: no toca la red ni trae campos de manifiesto
        lista = (await c.get("/admin/api/sistemas", headers=h)).json()["sistemas"]
        assert llamadas == []
        assert {x["id"] for x in lista} == {"acme", "lento"}
        assert all("manifiesto_ok" not in x and "tools_lectura" not in x for x in lista)

        r = await c.get("/admin/api/manifiestos", headers=h)
        assert r.status_code == 200
        m = r.json()["manifiestos"]
        assert m["acme"] == {"ok": False, "error": "sin credencial", "tools_lectura": 0}
        assert m["lento"]["ok"] is False and "a tiempo" in m["lento"]["error"]


async def test_el_error_de_validacion_no_repite_el_secreto(cliente, limpio):
    async with cliente() as c:
        h = await _sesion(c, limpio, "admin")
        await c.post("/admin/api/sistemas", json={"config": CONFIG}, headers=h)
        # `secretos` con un campo desconocido: FastAPI lo rechaza; el cuerpo no debe volver en la respuesta
        r = await c.put("/admin/api/sistemas/acme", headers=h, json={
            "version": 1, "config": CONFIG, "secretos": {"token_manifiesto": SECRETO, "otro": SECRETO}})
        assert r.status_code == 422 and SECRETO not in r.text
        r = await c.put("/admin/api/sistemas/acme/secretos/token_manifiesto", headers=h,
                        json={"version": "x", "valor": SECRETO})
        assert r.status_code == 422 and SECRETO not in r.text


async def test_tool_y_auditoria_con_el_actor(cliente, limpio):
    async with cliente() as c:
        h = await _sesion(c, limpio, "admin")
        await c.post("/admin/api/sistemas", json={"config": CONFIG}, headers=h)
        r = await c.put("/admin/api/sistemas/acme/tools/agregar_nota", json={"habilitada": True}, headers=h)
        assert r.status_code == 200 and r.json()["tool_estado"] == {"agregar_nota": True}
        t = await c.get("/admin/api/sistemas/acme/tools", headers=h)  # deshabilitado: sin manifiesto
        assert t.json()["manifiesto_ok"] is False and t.json()["huerfanas"] == [
            {"nombre": "agregar_nota", "habilitada": True}]
    async with limpio() as s:
        acciones = {(f.actor, f.accion) for f in (await s.execute(select(AdminAuditoria))).scalars()}
    assert {("admin@ejemplo.com", "sistema_crear"), ("admin@ejemplo.com", "tool_fijar")} <= acciones


async def test_usuarios_solo_admin_y_nunca_queda_sin_admin(cliente, limpio):
    async with cliente() as c:
        op = await _sesion(c, limpio, "operador")
        assert (await c.get("/admin/api/usuarios", headers=op)).status_code == 403
        h = await _sesion(c, limpio, "admin")
        lista = (await c.get("/admin/api/usuarios", headers=h)).json()["usuarios"]
        yo = next(u for u in lista if u["rol"] == "admin")
        assert "hash" not in str(lista)

        # nadie se quita a sí mismo el acceso (aunque otro admin exista)
        r = await c.post("/admin/api/usuarios", headers=h, json={
            "email": "otro@ejemplo.com", "clave": CLAVE, "rol": "admin"})
        assert r.status_code == 201
        r = await c.patch(f"/admin/api/usuarios/{yo['id']}", json={"rol": "operador"}, headers=h)
        assert (r.status_code, r.json()["error"]) == (409, "auto_cambio")

        # el otro admin sí puede ser degradado por mí, y entonces yo soy el único: no me pueden desactivar
        otro = next(u for u in (await c.get("/admin/api/usuarios", headers=h)).json()["usuarios"]
                    if u["email"] == "otro@ejemplo.com")
        assert (await c.patch(f"/admin/api/usuarios/{otro['id']}", json={"rol": "operador"},
                              headers=h)).status_code == 200
        async with limpio() as s:
            quedan = (await s.execute(select(AdminUsuario).where(
                AdminUsuario.rol == "admin", AdminUsuario.activo.is_(True)))).scalars().all()
        assert [u.email for u in quedan] == ["admin@ejemplo.com"]


async def test_cambiar_rol_o_clave_revoca_las_sesiones(cliente, limpio):
    async with cliente() as c:
        h = await _sesion(c, limpio, "admin")
        op = await _sesion(c, limpio, "operador")
        uid = next(u["id"] for u in (await c.get("/admin/api/usuarios", headers=h)).json()["usuarios"]
                   if u["rol"] == "operador")
        assert (await c.get("/admin/api/yo", headers=op)).status_code == 200
        assert (await c.patch(f"/admin/api/usuarios/{uid}", json={"activo": False}, headers=h)).status_code == 200
        assert (await c.get("/admin/api/yo", headers=op)).status_code == 401
        r = await c.post(f"/admin/api/usuarios/{uid}/clave", json={"clave": "corta"}, headers=h)
        assert r.status_code == 422 and "corta" not in r.text


async def test_el_panel_se_sirve_con_csp_y_sin_cors(tmp_path):
    from fastapi import FastAPI

    from asistente.api import panel

    (tmp_path / "assets").mkdir()
    (tmp_path / "index.html").write_text("<html>panel</html>")
    (tmp_path / "assets" / "app-abc.js").write_text("1")
    app = FastAPI()
    assert panel.montar(app, tmp_path) is True
    async with httpx.AsyncClient(transport=httpx.ASGITransport(app=app), base_url="http://x") as c:
        r = await c.get("/panel/")
        assert r.status_code == 200 and "panel" in r.text
        assert "default-src 'self'" in r.headers["content-security-policy"]
        assert r.headers["x-frame-options"] == "DENY"
        a = await c.get("/panel/assets/app-abc.js")
        assert "immutable" in a.headers["cache-control"]
    assert panel.montar(FastAPI(), tmp_path / "no-existe") is False


@pytest.mark.parametrize("campo,cambios", [
    ("base_url", {"base_url": "http://127.0.0.1:8000"}),
    ("base_url", {"base_url": "http://169.254.169.254/latest"}),
    ("base_url", {"base_url": "http://10.0.0.5"}),
    ("auth.jwks_url", {"auth": {"algoritmo": "RS256", "jwks_url": "http://[::1]/jwks"}}),
    ("llm.base_url", {"llm": {"base_url": "http://192.168.1.10:8090/v1"}}),
])
async def test_destinos_privados_se_rechazan_al_guardar(cliente, limpio, campo, cambios):
    async with cliente() as c:
        h = await _sesion(c, limpio, "admin")
        r = await c.post("/admin/api/sistemas", json={"config": {**CONFIG, **cambios}}, headers=h)
        assert (r.status_code, r.json()["error"]) == (422, "destino_no_permitido")
        assert r.json()["mensaje"].startswith(campo)
    async with limpio() as s:
        assert (await s.execute(select(SistemaRegistro))).first() is None


async def test_destino_privado_de_la_lista_de_permitidos_se_acepta(limpio, tmp_path):
    c = _app(limpio, tmp_path)
    c._transport.app.state.servicios.settings.hosts_internos_permitidos = "10.0.5.0/24"
    async with c:
        h = await _sesion(c, limpio, "admin")
        r = await c.post("/admin/api/sistemas", json={"config": {**CONFIG, "base_url": "http://10.0.5.7:8000"}},
                         headers=h)
        assert r.status_code == 201
        r = await c.post("/admin/api/sistemas", json={"config": {**CONFIG, "id": "otro",
                                                                  "base_url": "http://10.0.6.7:8000"}}, headers=h)
        assert r.status_code == 422


async def test_destructiva_exige_nombre_manifiesto_y_se_apaga_si_cambia(cliente, limpio, monkeypatch):
    from asistente.sistemas.manifiesto import (
        CacheManifiestos,
        ManifiestoInvalido,
        parsear_manifiesto,
    )

    def manifiesto(descripcion):
        return parsear_manifiesto({"contrato": "1", "sistema": {"nombre": "S"}, "tools": [
            {"nombre": "borrar_nota", "descripcion": descripcion, "efecto": "escritura",
             "parametros": {"type": "object", "properties": {}}, "confirmacion": {"ttl_s": 60}}]})

    actual = {"m": None}

    async def obtener(self, sistema_id):
        if actual["m"] is None:
            raise ManifiestoInvalido("sin manifiesto")
        return actual["m"]

    monkeypatch.setattr(CacheManifiestos, "obtener", obtener)
    monkeypatch.setattr(CacheManifiestos, "recargar", obtener)
    url = "/admin/api/sistemas/acme/tools/borrar_nota"
    async with cliente() as c:
        h = await _sesion(c, limpio, "admin")
        r = await c.post("/admin/api/sistemas", json={"config": CONFIG}, headers=h)
        cuerpo = {"version": 1, "config": {**r.json()["config"], "habilitado": True},
                  "secretos": {"token_manifiesto": SECRETO}}
        assert (await c.put("/admin/api/sistemas/acme", json=cuerpo, headers=h)).status_code == 200

        # sin manifiesto no se puede saber qué se aprueba
        r = await c.put(url, json={"habilitada": True, "confirmo_nombre": "borrar_nota"}, headers=h)
        assert (r.status_code, r.json()["error"]) == (409, "manifiesto_requerido")

        actual["m"] = manifiesto("v1")
        r = await c.put(url, json={"habilitada": True}, headers=h)
        assert (r.status_code, r.json()["error"]) == (422, "confirmacion_nombre")
        r = await c.put(url, json={"habilitada": True, "confirmo_nombre": "otra"}, headers=h)
        assert r.status_code == 422

        op = await _sesion(c, limpio, "operador")
        r = await c.put(url, json={"habilitada": True, "confirmo_nombre": "borrar_nota"}, headers=op)
        assert r.status_code == 403

        r = await c.put(url, json={"habilitada": True, "confirmo_nombre": "borrar_nota"}, headers=h)
        assert r.status_code == 200
        t = (await c.get("/admin/api/sistemas/acme/tools", headers=h)).json()["tools"][0]
        assert (t["destructiva"], t["habilitada"], t["aprobacion"]) == (True, True, "vigente")

        # el sistema cliente cambia la definición: se apaga sola y pide reaprobación
        actual["m"] = manifiesto("v2, ahora borra todo")
        t = (await c.get("/admin/api/sistemas/acme/tools", headers=h)).json()["tools"][0]
        assert (t["habilitada"], t["aprobacion"]) == (False, "obsoleta")

        # deshabilitar borra la fila (y con ella la aprobación)
        r = await c.put(url, json={"habilitada": False}, headers=h)
        assert r.status_code == 200 and r.json()["tool_estado"] == {}
        t = (await c.get("/admin/api/sistemas/acme/tools", headers=h)).json()["tools"][0]
        assert (t["habilitada"], t["aprobacion"]) == (False, None)
    async with limpio() as s:
        fijar = [f.despues for f in (await s.execute(select(AdminAuditoria))).scalars() if f.accion == "tool_fijar"]
    assert {"tool": "borrar_nota", "habilitada": True, "destructiva": True}.items() <= fijar[0].items()
    assert fijar[0]["huella"]
