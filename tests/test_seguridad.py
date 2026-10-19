"""Fronteras de seguridad con BD: bloqueo de login del panel y archivos de otro usuario."""

import os
import uuid
from datetime import UTC, datetime, timedelta

import pytest
from sqlalchemy import delete

from asistente.store.admin import FALLOS_MAX, AdminSql
from asistente.store.archivos import ArchivosSql
from asistente.store.models import AdminAuditoria, AdminSesion, AdminUsuario, Archivo
from test_agent import contexto
from test_api import sesiones  # noqa: F401

pytestmark = pytest.mark.skipif(not os.environ.get("ASISTENTE_DATABASE_URL"), reason="sin ASISTENTE_DATABASE_URL")

CLAVE = "una-clave-larga-123"


async def test_bloqueo_tras_varios_fallos_aunque_acierte_despues(sesiones):  # noqa: F811
    async with sesiones.begin() as s:
        for m in (AdminSesion, AdminUsuario, AdminAuditoria):
            await s.execute(delete(m))
    a = AdminSql(sesiones)
    await a.crear_usuario("ana@ejemplo.com", CLAVE, "admin")
    for _ in range(FALLOS_MAX):
        assert await a.login("ana@ejemplo.com", "mal-mal-mal-mal") is None
    assert await a.login("ana@ejemplo.com", CLAVE) is None  # bloqueada
    ahora = datetime.now(UTC) + timedelta(minutes=16)
    assert await AdminSql(sesiones, ahora=lambda: ahora).login("ana@ejemplo.com", CLAVE) is not None


async def test_un_archivo_ajeno_no_se_descarga(sesiones):  # noqa: F811
    archivos = ArchivosSql(sesiones, ttl_horas=1, max_por_dia=10)
    nombre = f"t-{uuid.uuid4().hex[:8]}"
    ctx = contexto(usuario_ref=nombre)
    id_ = uuid.UUID(await archivos.guardar(ctx, None, "a.xlsx", b"x", "application/octet-stream"))
    try:
        assert await archivos.obtener("mock-a", nombre, id_) is not None
        assert await archivos.obtener("mock-a", "otra-persona", id_) is None
        assert await archivos.obtener("mock-b", nombre, id_) is None
    finally:
        async with sesiones.begin() as s:
            await s.execute(delete(Archivo).where(Archivo.id == id_))
