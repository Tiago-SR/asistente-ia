"""Endpoints de lectura de métricas (/admin/api/metricas/...): permisos, rangos, serie sin huecos y cuotas."""

import uuid
from datetime import UTC, datetime, timedelta

import pytest

from asistente.store.models import ContadorUso, EventoUso, LlamadaTool
from asistente.store.resumen import ResumenSql
from test_admin_sistemas_api import CONFIG, URL, _sesion, cliente, limpio  # noqa: F401
from test_api import sesiones  # noqa: F401

pytestmark = pytest.mark.skipif(not URL, reason="sin ASISTENTE_DATABASE_URL")

BASE = "/admin/api/metricas"


def sid() -> str:
    return f"m-{uuid.uuid4().hex[:10]}"


def ev(s: str, dias_atras: int, **kw) -> EventoUso:
    base = {"sistema_id": s, "tipo": "llm", "resultado": "ok", "modelo": "m1", "usuario_ref": "ana",
            "canal": "texto", "tokens_in": 100, "tokens_out": 10, "duracion_ms": 1000,
            "costo_valle_usd": 0.5, "costo_pico_usd": 1.0,
            "creada": datetime.now(UTC) - timedelta(days=dias_atras, minutes=1)}
    return EventoUso(**{**base, **kw})


async def test_operador_lee_y_token_estatico_o_sin_sesion_no(cliente, limpio):  # noqa: F811
    async with cliente() as c:
        h = await _sesion(c, limpio, "operador")
        for ruta in ("series", "usuarios", "tools"):
            assert (await c.get(f"{BASE}/{ruta}", headers=h)).status_code == 200
        r = await c.get(f"{BASE}/series", headers={"Authorization": "Bearer adm1n"})
        assert (r.status_code, r.json()["error"]) == (403, "permiso_insuficiente")
        assert (await c.get(f"{BASE}/series")).status_code == 401


async def test_rangos_invalidos(cliente, limpio):  # noqa: F811
    async with cliente() as c:
        h = await _sesion(c, limpio, "admin")
        r = await c.get(f"{BASE}/usuarios", params={"desde": "2026-01-01", "hasta": "2026-06-01"}, headers=h)
        assert (r.status_code, r.json()) == (422, {"error": "rango_excedido", "max_dias": 90})
        r = await c.get(f"{BASE}/tools", params={"desde": "2026-06-01", "hasta": "2026-01-01"}, headers=h)
        assert r.json()["error"] == "rango_invalido"
        r = await c.get(f"{BASE}/series", params={"desde": "2020-01-01", "hasta": "2026-06-01"}, headers=h)
        assert r.json()["error"] == "rango_excedido"
        assert (await c.get(f"{BASE}/series", params={"tipo": "nada"}, headers=h)).status_code == 422


async def test_serie_sin_huecos_aunque_ayer_no_este_resumido(cliente, limpio, sesiones):  # noqa: F811
    s = sid()
    async with sesiones.begin() as ses:
        ses.add_all([ev(s, 3), ev(s, 1, usuario_ref="ana"), ev(s, 1, usuario_ref="luis", canal="voz"), ev(s, 0)])
    hoy = datetime.now(UTC).date()
    async with cliente() as c:
        h = await _sesion(c, limpio, "admin")
        r = await c.get(f"{BASE}/series", params={"sistema_id": s}, headers=h)
        j = r.json()
        assert (j["zona"], j["hasta"]) == ("UTC", hoy.isoformat())
        assert [(f["dia"], f["fuente"]) for f in j["filas"] if f["canal"] == "texto"] == [
            ((hoy - timedelta(days=d)).isoformat(), "crudos") for d in (3, 1, 0)]
        await ResumenSql(sesiones).resumir(s, 30)
        j = (await c.get(f"{BASE}/series", params={"sistema_id": s}, headers=h)).json()
        fuentes = {f["dia"]: f["fuente"] for f in j["filas"]}
        assert fuentes[(hoy - timedelta(days=1)).isoformat()] == "resumen"
        assert fuentes[hoy.isoformat()] == "crudos"  # hoy nunca está resumido
        assert j["cobertura"]["resumido_hasta"] == (hoy - timedelta(days=1)).isoformat()
        # Agrupar: ayer tiene dos canales, así que `usuarios` no se puede sumar y viene null.
        j = (await c.get(f"{BASE}/series", params={"sistema_id": s, "agrupar": "tipo"}, headers=h)).json()
        ayer = next(f for f in j["filas"] if f["dia"] == (hoy - timedelta(days=1)).isoformat())
        assert (ayer["n"], ayer["usuarios"], ayer["p95_ms"]) == (2, None, None)
        antes = next(f for f in j["filas"] if f["dia"] == (hoy - timedelta(days=3)).isoformat())
        assert (antes["n"], antes["usuarios"], antes["p95_ms"]) == (1, 1, 1000)


async def test_costo_sin_tarifa_es_null_y_se_cuenta(cliente, limpio, sesiones):  # noqa: F811
    s = sid()
    async with sesiones.begin() as ses:
        ses.add(ev(s, 0, costo_valle_usd=None, costo_pico_usd=None))
    async with cliente() as c:
        h = await _sesion(c, limpio, "admin")
        [f] = (await c.get(f"{BASE}/series", params={"sistema_id": s}, headers=h)).json()["filas"]
        assert (f["costo_valle_usd"], f["costo_pico_usd"], f["n_sin_tarifa"]) == (None, None, 1)


async def test_usuarios_con_cuota_restante_y_tools_con_percentiles(cliente, limpio, sesiones):  # noqa: F811
    s = sid()
    hoy0 = datetime.now(UTC).replace(hour=0, minute=0, second=0, microsecond=0)
    async with sesiones.begin() as ses:
        ses.add_all([ev(s, 0, usuario_ref="ana"), ev(s, 0, usuario_ref="ana"), ev(s, 0, usuario_ref="luis"),
                     ev(s, 0, usuario_ref="luis", resultado="limite", motivo="mensajes_dia", n=3),
                     ContadorUso(sistema_id=s, usuario_ref="ana", ventana="dia", inicio=hoy0, mensajes=5),
                     ContadorUso(sistema_id=s, usuario_ref="", ventana="mes",
                                 inicio=hoy0.replace(day=1), tokens=1234)])
        for ms in (100, 200, 300, 400):
            ses.add(LlamadaTool(sistema_id=s, usuario_ref="ana", jti="j", tool="consultar", ok=True,
                                duracion_ms=ms))
        ses.add(LlamadaTool(sistema_id=s, usuario_ref="ana", jti="j", tool="consultar", ok=False, duracion_ms=500))
    async with cliente() as c:
        h = await _sesion(c, limpio, "admin")
        r = await c.post("/admin/api/sistemas", json={"config": {**CONFIG, "id": s}}, headers=h)
        assert r.status_code == 201, r.text
        r = await c.put(f"/admin/api/sistemas/{s}", headers=h, json={
            "version": 1, "config": {**r.json()["config"], "habilitado": True},
            "secretos": {"token_manifiesto": "tok"}})
        assert r.status_code == 200, r.text
        j = (await c.get(f"{BASE}/usuarios", params={"sistema_id": s}, headers=h)).json()
        por = {f["usuario_ref"]: f for f in j["filas"]}
        assert [f["usuario_ref"] for f in j["filas"]] == ["ana", "luis"]  # por turnos (2 y 1)
        assert por["ana"]["cuota_dia"]["usados"] == 5
        assert por["ana"]["cuota_dia"]["restante"] == por["ana"]["cuota_dia"]["limite"] - 5
        assert (por["luis"]["rechazos"], por["luis"]["turnos"]) == (3, 1)
        assert por["luis"]["cuota_dia"]["usados"] == 0
        assert j["cuota_mes"][0]["usados"] == 1234
        j = (await c.get(f"{BASE}/usuarios", params={"sistema_id": s, "orden": "rechazos"}, headers=h)).json()
        assert j["filas"][0]["usuario_ref"] == "luis"
        j = (await c.get(f"{BASE}/tools", params={"sistema_id": s}, headers=h)).json()
        [t] = j["filas"]
        assert (t["tool"], t["n"], t["errores"], t["p50_ms"], t["max_ms"]) == ("consultar", 5, 1, 300, 500)
