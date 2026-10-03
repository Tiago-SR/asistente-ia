from fastapi.testclient import TestClient

from asistente.main import app


def test_salud():
    assert TestClient(app).get("/salud").json() == {"ok": True}
