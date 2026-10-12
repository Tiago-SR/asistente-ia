"""Usuarios del panel: login, sesión, CSRF, bloqueo, roles y auditoría (Fase 2)."""

import os
from datetime import UTC, datetime, timedelta

import pytest
from sqlalchemy import delete, select

from asistente.store.admin import FALLOS_MAX, INACTIVIDAD, AdminSql, ErrorAdmin
from asistente.store.models import AdminAuditoria, AdminSesion, AdminUsuario
from test_api import ORIGEN_A, construir_app, llm, sesiones  # noqa: F401

URL = os.environ.get("ASISTENTE_DATABASE_URL")
pytestmark = pytest.mark.skipif(not URL, reason="sin ASISTENTE_DATABASE_URL")

CLAVE = "una-clave-larga-123"
ORIGEN = {"Origin": "http://asistente"}


@pytest.fixture
async def limpio(sesiones):  # noqa: F811
    async def _limpiar():
        async with sesiones.begin() as s:
            for m in (AdminSesion, AdminUsuario, AdminAuditoria):
                await s.execute(delete(m))
    await _limpiar()
    yield sesiones
    await _limpiar()


async def entrar(c, email="ana@ejemplo.com", clave=CLAVE):
    r = await c.post("/admin/api/login", json={"email": email, "clave": clave}, headers=ORIGEN)
    cookie = r.cookies.get("__Host-admin") if r.status_code == 200 else None
    return r, ({"Cookie": f"__Host-admin={cookie}"} if cookie else {})


async def test_login_y_sesion_leen_pero_no_escriben_sin_csrf(construir_app, limpio):  # noqa: F811
    await AdminSql(limpio).crear_usuario("Ana@Ejemplo.com", CLAVE, "operador")
    async with construir_app() as c:
        r, h = await entrar(c)
        assert r.status_code == 200 and r.json()["rol"] == "operador"
        assert "httponly" in r.headers["set-cookie"].lower() and "samesite=strict" in r.headers["set-cookie"].lower()
        csrf = r.json()["csrf"]
        assert (await c.get("/admin/api/yo", headers=h)).json()["email"] == "ana@ejemplo.com"
        assert (await c.get("/admin/api/sistemas", headers=h)).status_code == 200
        # POST sin CSRF, con CSRF pero sin Origin, y con Origin ajeno: rechazados
        assert (await c.post("/admin/api/recargar", headers=h)).status_code == 403
        assert (await c.post("/admin/api/recargar", headers={**h, "X-CSRF": csrf})).status_code == 403
        ajeno = {**h, "X-CSRF": csrf, "Origin": "http://malo.example"}
        assert (await c.post("/admin/api/recargar", headers=ajeno)).status_code == 403
        ok = {**h, "X-CSRF": csrf, **ORIGEN}
        assert (await c.post("/admin/api/recargar", headers=ok)).status_code == 200
        assert (await c.post("/admin/api/logout", headers=ok)).status_code == 200
        assert (await c.get("/admin/api/yo", headers=h)).status_code == 401


async def test_login_fallido_es_indistinguible(construir_app, limpio):  # noqa: F811
    await AdminSql(limpio).crear_usuario("ana@ejemplo.com", CLAVE, "admin")
    async with construir_app() as c:
        a, _ = await entrar(c, clave="incorrecta-incorrecta")
        b, _ = await entrar(c, email="nadie@ejemplo.com")
        assert (a.status_code, a.json()) == (b.status_code, b.json()) == (401, {"error": "credenciales_invalidas"})
        # sin Origin propio ni siquiera se intenta
        r = await c.post("/admin/api/login", json={"email": "ana@ejemplo.com", "clave": CLAVE})
        assert r.status_code == 403


async def test_bloqueo_tras_varios_fallos_aunque_acierte_despues(limpio):
    a = AdminSql(limpio)
    await a.crear_usuario("ana@ejemplo.com", CLAVE, "admin")
    for _ in range(FALLOS_MAX):
        assert await a.login("ana@ejemplo.com", "mal-mal-mal-mal") is None
    assert await a.login("ana@ejemplo.com", CLAVE) is None  # bloqueada
    ahora = datetime.now(UTC) + timedelta(minutes=16)
    assert await AdminSql(limpio, ahora=lambda: ahora).login("ana@ejemplo.com", CLAVE) is not None


async def test_sesion_caduca_por_inactividad_y_cambiar_clave_la_revoca(limpio):
    a = AdminSql(limpio)
    await a.crear_usuario("ana@ejemplo.com", CLAVE, "admin")
    token, _ = await a.login("ana@ejemplo.com", CLAVE)
    assert await a.sesion(token) is not None
    tarde = datetime.now(UTC) + INACTIVIDAD + timedelta(minutes=1)
    assert await AdminSql(limpio, ahora=lambda: tarde).sesion(token) is None
    token, _ = await a.login("ana@ejemplo.com", CLAVE)
    await a.cambiar_clave("ana@ejemplo.com", "otra-clave-larga-456")
    assert await a.sesion(token) is None
    assert await a.login("ana@ejemplo.com", CLAVE) is None
    assert await a.login("ana@ejemplo.com", "otra-clave-larga-456") is not None


async def test_alta_valida_y_no_guarda_la_clave_en_claro(limpio):
    a = AdminSql(limpio)
    with pytest.raises(ErrorAdmin):
        await a.crear_usuario("ana@ejemplo.com", "corta", "admin")
    with pytest.raises(ErrorAdmin):
        await a.crear_usuario("ana@ejemplo.com", CLAVE, "root")
    await a.crear_usuario("ana@ejemplo.com", CLAVE, "admin")
    with pytest.raises(ErrorAdmin):
        await a.crear_usuario("ANA@ejemplo.com", CLAVE, "admin")
    async with limpio() as s:
        u = (await s.execute(select(AdminUsuario))).scalar_one()
    assert u.hash.startswith("$argon2id$") and CLAVE not in u.hash


async def test_token_estatico_sigue_valiendo_sin_csrf_y_se_audita(construir_app, limpio):  # noqa: F811
    async with construir_app(admin_token="adm1n") as c:
        r = await c.post("/admin/api/recargar", headers={"Authorization": "Bearer adm1n"})
        assert r.status_code == 200
    async with limpio() as s:
        fila = (await s.execute(select(AdminAuditoria))).scalar_one()
    assert (fila.actor, fila.accion) == ("token", "recargar")


async def test_el_cors_de_los_sistemas_no_aplica_al_panel(construir_app):  # noqa: F811
    async with construir_app() as c:
        r = await c.get("/admin/api/yo", headers={"Origin": ORIGEN_A})
        assert "access-control-allow-origin" not in r.headers


async def test_cambiar_clave_propia_exige_la_actual_y_conserva_solo_la_sesion_actual(construir_app, limpio):  # noqa: F811
    await AdminSql(limpio).crear_usuario("ana@ejemplo.com", CLAVE, "operador")  # cualquier rol puede
    nueva = "otra-clave-larga-456"
    async with construir_app() as c:
        r, h = await entrar(c)
        _, otra = await entrar(c)  # segunda sesión de la misma persona
        csrf = r.json()["csrf"]
        post = {**h, "X-CSRF": csrf, **ORIGEN}
        # actual incorrecta: 403, no cambia nada y cuenta como fallo
        mal = await c.post("/admin/api/yo/clave", json={"actual": "incorrecta-larga-1", "nueva": nueva}, headers=post)
        assert (mal.status_code, mal.json()["error"]) == (403, "clave_actual_incorrecta")
        # nueva igual a la actual o corta: 422
        assert (await c.post("/admin/api/yo/clave", json={"actual": CLAVE, "nueva": CLAVE}, headers=post)).status_code == 422
        assert (await c.post("/admin/api/yo/clave", json={"actual": CLAVE, "nueva": "corta"}, headers=post)).status_code == 422
        ok = await c.post("/admin/api/yo/clave", json={"actual": CLAVE, "nueva": nueva}, headers=post)
        assert ok.status_code == 200
        assert (await c.get("/admin/api/yo", headers=h)).status_code == 200      # la sesión que cambia sigue
        assert (await c.get("/admin/api/yo", headers=otra)).status_code == 401   # las demás se revocan
        assert (await entrar(c, clave=CLAVE))[0].status_code == 401
        assert (await entrar(c, clave=nueva))[0].status_code == 200
    async with limpio() as s:
        acciones = [f.accion for f in (await s.execute(select(AdminAuditoria).order_by(AdminAuditoria.id))).scalars()]
    assert "clave_propia_fallida" in acciones and "clave_propia" in acciones
    assert nueva not in str(acciones)


async def test_cambiar_clave_propia_rechaza_el_token_estatico_y_sin_csrf(construir_app, limpio):  # noqa: F811
    await AdminSql(limpio).crear_usuario("ana@ejemplo.com", CLAVE, "admin")
    async with construir_app(admin_token="adm1n") as c:
        r = await c.post("/admin/api/yo/clave", json={"actual": CLAVE, "nueva": "otra-clave-larga-456"},
                         headers={"Authorization": "Bearer adm1n"})
        assert r.status_code == 403
        _, h = await entrar(c)
        r = await c.post("/admin/api/yo/clave", json={"actual": CLAVE, "nueva": "otra-clave-larga-456"}, headers=h)
        assert r.status_code == 403  # sin X-CSRF


async def test_fallos_de_la_actual_bloquean_la_cuenta(limpio):
    a = AdminSql(limpio)
    await a.crear_usuario("ana@ejemplo.com", CLAVE, "admin")
    token, _ = await a.login("ana@ejemplo.com", CLAVE)
    for _ in range(FALLOS_MAX):
        with pytest.raises(ErrorAdmin):
            await a.cambiar_clave_propia("ana@ejemplo.com", "incorrecta-larga-1", "otra-clave-larga-456", token)
    with pytest.raises(ErrorAdmin):  # ya bloqueada: ni con la correcta
        await a.cambiar_clave_propia("ana@ejemplo.com", CLAVE, "otra-clave-larga-456", token)


async def test_purgar_auditoria_borra_solo_lo_vencido(limpio):
    a = AdminSql(limpio)
    await a.auditar("ana@ejemplo.com", "login")
    async with limpio.begin() as s:
        s.add(AdminAuditoria(actor="ana@ejemplo.com", accion="vieja",
                             fecha=datetime.now(UTC) - timedelta(days=400)))
    assert await a.purgar_auditoria(0) == 0  # 0 = no purgar
    assert await a.purgar_auditoria(365) == 1
    async with limpio() as s:
        acciones = [f.accion for f in (await s.execute(select(AdminAuditoria))).scalars()]
    assert acciones == ["login"]
