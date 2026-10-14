"""`/admin` y `/panel` solo por acceso directo (túnel ssh): rechazo de proxies y de hosts ajenos."""

from types import SimpleNamespace

import httpx
import pytest
from fastapi import FastAPI

from asistente.api.acceso_admin import AccesoAdmin
from asistente.api.admin import _ip_distinguible


def _app(admin_hosts: str) -> FastAPI:
    app = FastAPI()
    app.state.servicios = SimpleNamespace(settings=SimpleNamespace(admin_hosts=admin_hosts))
    app.add_middleware(AccesoAdmin)

    @app.get("/admin/api/yo")
    async def yo():
        return {"ok": True}

    @app.get("/panel/")
    async def panel():
        return {"ok": True}

    @app.get("/salud")
    async def salud():
        return {"ok": True}

    return app


def _cliente(app: FastAPI, host: str) -> httpx.AsyncClient:
    return httpx.AsyncClient(transport=httpx.ASGITransport(app=app), base_url=f"http://{host}")


@pytest.mark.parametrize("ruta", ["/admin/api/yo", "/panel/"])
async def test_acceso_directo_con_host_permitido(ruta):
    async with _cliente(_app("localhost:8001,127.0.0.1:8000"), "localhost:8001") as c:
        assert (await c.get(ruta)).status_code == 200


@pytest.mark.parametrize("ruta", ["/admin/api/yo", "/panel/"])
async def test_host_ajeno_da_404(ruta):
    async with _cliente(_app("localhost:8001"), "asistente.midominio.com") as c:
        assert (await c.get(ruta)).status_code == 404


@pytest.mark.parametrize("cabecera", ["X-Forwarded-For", "X-Forwarded-Host", "X-Real-IP", "Forwarded"])
async def test_cabeceras_de_proxy_dan_404_aunque_el_host_coincida(cabecera):
    async with _cliente(_app("localhost:8001"), "localhost:8001") as c:
        assert (await c.get("/admin/api/yo", headers={cabecera: "203.0.113.9"})).status_code == 404


async def test_rutas_publicas_no_se_tocan():
    async with _cliente(_app("localhost:8001"), "asistente.midominio.com") as c:
        assert (await c.get("/salud", headers={"X-Forwarded-For": "203.0.113.9"})).status_code == 200


async def test_sin_lista_no_restringe():
    async with _cliente(_app(""), "asistente.midominio.com") as c:
        assert (await c.get("/admin/api/yo", headers={"X-Forwarded-For": "203.0.113.9"})).status_code == 200


@pytest.mark.parametrize("ip,esperado", [
    ("203.0.113.9", False),  # documentación: no es global
    ("8.8.8.8", True),
    ("127.0.0.1", False),
    ("172.18.0.1", False),
    ("::1", False),
    ("testclient", False),
    (None, False),
])
def test_ip_distinguible(ip, esperado):
    assert _ip_distinguible(ip) is esperado
