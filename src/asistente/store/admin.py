"""Usuarios, sesiones y auditoría del panel de administración.

Contraseñas con argon2id. De la sesión solo se guarda el SHA-256 del token. Un login fallido no distingue
entre usuario inexistente, contraseña incorrecta, usuario inactivo o bloqueado (mismo resultado y mismo coste).
"""

import asyncio
import hashlib
import secrets
import uuid
from collections.abc import Callable
from dataclasses import dataclass
from datetime import UTC, datetime, timedelta

from argon2 import PasswordHasher
from argon2.exceptions import InvalidHashError, VerificationError
from sqlalchemy import delete, select, update
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from asistente.store.models import AdminAuditoria, AdminSesion, AdminUsuario

ROLES = ("admin", "operador")
CLAVE_MIN = 12
FALLOS_MAX = 5
BLOQUEO = timedelta(minutes=15)
INACTIVIDAD = timedelta(minutes=30)
DURACION_MAX = timedelta(hours=12)
_REFRESCO_USO = timedelta(seconds=60)  # no escribir `ultimo_uso` en cada petición

_hasher = PasswordHasher()
_HASH_FALSO = _hasher.hash("clave-que-no-existe-" + secrets.token_hex(8))  # iguala el coste si no hay usuario


class ErrorAdmin(Exception):
    pass


@dataclass(frozen=True)
class SesionAdmin:
    usuario_id: uuid.UUID
    email: str
    rol: str
    csrf: str


def _sha(token: str) -> str:
    return hashlib.sha256(token.encode()).hexdigest()


def _normalizar(email: str) -> str:
    return email.strip().lower()


class AdminSql:
    def __init__(self, sesiones: async_sessionmaker[AsyncSession],
                 ahora: Callable[[], datetime] = lambda: datetime.now(UTC)) -> None:
        self._sesiones = sesiones
        self._ahora = ahora

    # --- usuarios ---

    async def crear_usuario(self, email: str, clave: str, rol: str) -> None:
        email = _normalizar(email)
        if "@" not in email or len(email) > 320:
            raise ErrorAdmin("email inválido")
        if rol not in ROLES:
            raise ErrorAdmin(f"rol inválido (use {' o '.join(ROLES)})")
        if len(clave) < CLAVE_MIN:
            raise ErrorAdmin(f"la contraseña debe tener al menos {CLAVE_MIN} caracteres")
        hash_ = await asyncio.to_thread(_hasher.hash, clave)
        try:
            async with self._sesiones.begin() as s:
                s.add(AdminUsuario(email=email, hash=hash_, rol=rol))
        except IntegrityError as e:
            raise ErrorAdmin("ya existe un usuario con ese email") from e

    async def cambiar_clave(self, email: str, clave: str) -> None:
        """Revoca todas las sesiones del usuario y limpia el bloqueo."""
        if len(clave) < CLAVE_MIN:
            raise ErrorAdmin(f"la contraseña debe tener al menos {CLAVE_MIN} caracteres")
        hash_ = await asyncio.to_thread(_hasher.hash, clave)
        async with self._sesiones.begin() as s:
            uid = (await s.execute(
                update(AdminUsuario).where(AdminUsuario.email == _normalizar(email))
                .values(hash=hash_, fallos=0, bloqueado_hasta=None).returning(AdminUsuario.id)
            )).scalar_one_or_none()
            if uid is None:
                raise ErrorAdmin("usuario inexistente")
            await s.execute(delete(AdminSesion).where(AdminSesion.usuario_id == uid))

    # --- login y sesiones ---

    async def login(self, email: str, clave: str) -> tuple[str, SesionAdmin] | None:
        """Devuelve (token, sesión) o None. El token solo existe aquí y en la cookie."""
        ahora = self._ahora()
        async with self._sesiones() as s:
            u = (await s.execute(
                select(AdminUsuario).where(AdminUsuario.email == _normalizar(email))
            )).scalar_one_or_none()
        bloqueado = u is not None and u.bloqueado_hasta is not None and u.bloqueado_hasta > ahora
        ok = await self._verificar(u.hash if u else _HASH_FALSO, clave)
        if u is None:
            return None
        if bloqueado or not u.activo:
            return None
        if not ok:
            fallos = u.fallos + 1
            async with self._sesiones.begin() as s:
                await s.execute(update(AdminUsuario).where(AdminUsuario.id == u.id).values(
                    fallos=0 if fallos >= FALLOS_MAX else fallos,
                    bloqueado_hasta=ahora + BLOQUEO if fallos >= FALLOS_MAX else None))
            return None
        token, csrf = secrets.token_urlsafe(32), secrets.token_urlsafe(32)
        async with self._sesiones.begin() as s:
            await s.execute(update(AdminUsuario).where(AdminUsuario.id == u.id).values(
                fallos=0, bloqueado_hasta=None, ultimo_login=ahora))
            s.add(AdminSesion(token_hash=_sha(token), usuario_id=u.id, csrf=csrf,
                              creada=ahora, ultimo_uso=ahora, expira=ahora + DURACION_MAX))
            await s.execute(delete(AdminSesion).where(  # limpieza oportunista de las vencidas
                AdminSesion.expira < ahora))
        return token, SesionAdmin(u.id, u.email, u.rol, csrf)

    @staticmethod
    async def _verificar(hash_: str, clave: str) -> bool:
        def _v() -> bool:
            try:
                return _hasher.verify(hash_, clave)
            except (VerificationError, InvalidHashError):
                return False
        return await asyncio.to_thread(_v)

    async def sesion(self, token: str) -> SesionAdmin | None:
        ahora = self._ahora()
        clave = _sha(token)
        async with self._sesiones.begin() as s:
            fila = (await s.execute(
                select(AdminSesion, AdminUsuario).join(AdminUsuario, AdminUsuario.id == AdminSesion.usuario_id)
                .where(AdminSesion.token_hash == clave)
            )).first()
            if fila is None:
                return None
            ses, u = fila
            if ses.expira <= ahora or ahora - ses.ultimo_uso > INACTIVIDAD or not u.activo:
                await s.delete(ses)
                return None
            if ahora - ses.ultimo_uso > _REFRESCO_USO:
                ses.ultimo_uso = ahora
            return SesionAdmin(u.id, u.email, u.rol, ses.csrf)

    async def cerrar(self, token: str) -> None:
        async with self._sesiones.begin() as s:
            await s.execute(delete(AdminSesion).where(AdminSesion.token_hash == _sha(token)))

    # --- auditoría ---

    async def auditar(self, actor: str, accion: str, objetivo: str | None = None, *,
                      antes: dict | None = None, despues: dict | None = None, ip: str | None = None) -> None:
        async with self._sesiones.begin() as s:
            s.add(AdminAuditoria(actor=actor, accion=accion, objetivo=objetivo, antes=antes,
                                 despues=despues, ip=ip))
