import asyncio
import importlib.util
import os
import time
import uuid
from pathlib import Path

import httpx
import jwt
import pytest
import yaml
from sqlalchemy.engine import make_url

from asistente.sistemas.registro import RegistroSistemas, entradas_desde_yaml

RAIZ = Path(__file__).resolve().parent.parent
MOCK = RAIZ / "ejemplos" / "sistema-mock" / "app.py"


# ── BD de pruebas aparte ──
# Varios tests limpian tablas (sistema, admin_usuario, auditoría…). Contra la BD de desarrollo borrarían el
# registro y los usuarios admin del servidor dev, así que la suite SIEMPRE usa `<bd>_test`, recreada al empezar.
# Se reescribe ASISTENTE_DATABASE_URL aquí, al importar el conftest, antes de que los módulos de test la lean.
def _url_de_pruebas() -> str | None:
    explicita = os.environ.get("ASISTENTE_TEST_DATABASE_URL")
    base = explicita or os.environ.get("ASISTENTE_DATABASE_URL")
    if not base:
        return None
    url = make_url(base)
    if not (url.database or "").endswith("_test"):
        if explicita:
            raise pytest.UsageError("ASISTENTE_TEST_DATABASE_URL debe apuntar a una BD cuyo nombre termine en _test")
        url = url.set(database=f"{url.database}_test")
    return url.render_as_string(hide_password=False)


_URL_PRUEBAS = _url_de_pruebas()
if _URL_PRUEBAS:
    os.environ["ASISTENTE_DATABASE_URL"] = _URL_PRUEBAS


def pytest_sessionstart(session):
    if not _URL_PRUEBAS:
        return
    import asyncpg

    url = make_url(_URL_PRUEBAS)
    assert url.database and url.database.endswith("_test"), "la BD de pruebas debe terminar en _test"

    async def recrear() -> None:
        c = await asyncpg.connect(
            host=url.host, port=url.port, user=url.username, password=url.password, database="postgres"
        )
        try:
            await c.execute(f'DROP DATABASE IF EXISTS "{url.database}" WITH (FORCE)')
            await c.execute(f'CREATE DATABASE "{url.database}"')
        finally:
            await c.close()

    asyncio.run(recrear())


def cargar_mock(monkeypatch, id_: str):
    """Instancia independiente del sistema mock (lee su configuración al importarse)."""
    monkeypatch.setenv("MOCK_ID", id_)
    monkeypatch.setenv("MOCK_NOMBRE", id_.upper())
    monkeypatch.setenv("MOCK_SECRETO", f"secreto-{id_}-" + "x" * 32)
    monkeypatch.setenv("MOCK_TOKEN_MANIFIESTO", f"manifiesto-{id_}")
    spec = importlib.util.spec_from_file_location(f"mock_{id_.replace('-', '_')}", MOCK)
    modulo = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(modulo)
    return modulo


def entrada_sistema(id_: str, **cambios) -> dict:
    e = {
        "id": id_,
        "nombre": id_.upper(),
        "base_url": f"http://{id_}",
        "auth": {"algoritmo": "HS256", "secreto_env": f"{id_}_SECRETO"},
        "conector": {"token_manifiesto_env": f"{id_}_MANIFEST"},
    }
    e.update(cambios)
    return e


def entorno(*ids: str) -> dict:
    env = {}
    for i in ids:
        env[f"{i}_SECRETO"] = f"secreto-{i}-" + "x" * 32
        env[f"{i}_MANIFEST"] = f"manifiesto-{i}"
    return env


def escribir_registro(ruta: Path, entradas: list[dict]) -> Path:
    ruta.write_text(yaml.safe_dump({"sistemas": entradas}), encoding="utf-8")
    return ruta


def firmar(id_: str, sub: str = "ana", **claims) -> str:
    ahora = int(time.time())
    base = {
        "iss": id_,
        "aud": "asistente",
        "sub": sub,
        "iat": ahora,
        "exp": ahora + 600,
        "jti": uuid.uuid4().hex,
        "scope": "asistente:lectura",
    }
    base.update(claims)
    clave = base.pop("_clave", f"secreto-{id_}-" + "x" * 32)
    base = {k: v for k, v in base.items() if v is not None}
    return jwt.encode(base, clave, algorithm="HS256")


def registro_desde_yaml(ruta: Path, env: dict | None = None) -> RegistroSistemas:
    """Registro en memoria cargado de un YAML (solo tests): el mismo `aplicar` que usa la fuente BD en runtime."""
    r = RegistroSistemas()
    r.aplicar(entradas_desde_yaml(ruta, env))
    return r


@pytest.fixture
def registro_dos(tmp_path) -> RegistroSistemas:
    ruta = escribir_registro(tmp_path / "s.yaml", [entrada_sistema("mock-a"), entrada_sistema("mock-b")])
    return registro_desde_yaml(ruta, env=entorno("mock-a", "mock-b"))


@pytest.fixture
def mock_a(monkeypatch):
    return cargar_mock(monkeypatch, "mock-a")


@pytest.fixture
def mock_b(monkeypatch):
    return cargar_mock(monkeypatch, "mock-b")


@pytest.fixture
async def cliente_mocks(mock_a, mock_b):
    """Cliente httpx que enruta http://mock-a y http://mock-b a cada app en memoria."""
    apps = {"mock-a": mock_a.app, "mock-b": mock_b.app}

    class Router(httpx.AsyncBaseTransport):
        async def handle_async_request(self, request):
            return await httpx.ASGITransport(app=apps[request.url.host]).handle_async_request(
                request
            )

    async with httpx.AsyncClient(transport=Router(), follow_redirects=False) as c:
        yield c
