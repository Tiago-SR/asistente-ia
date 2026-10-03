import importlib.util
import time
import uuid
from pathlib import Path

import httpx
import jwt
import pytest
import yaml

from asistente.sistemas.registro import RegistroSistemas

RAIZ = Path(__file__).resolve().parent.parent
MOCK = RAIZ / "ejemplos" / "sistema-mock" / "app.py"


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


@pytest.fixture
def registro_dos(tmp_path) -> RegistroSistemas:
    ruta = escribir_registro(tmp_path / "s.yaml", [entrada_sistema("mock-a"), entrada_sistema("mock-b")])
    return RegistroSistemas(ruta, env=entorno("mock-a", "mock-b"))


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
