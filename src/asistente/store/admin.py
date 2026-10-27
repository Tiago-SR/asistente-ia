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
    def __init__(self, mensaje: str, codigo: str = "invalido") -> None:
        super().__init__(mensaje)
        self.codigo = codigo


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

    async def cambiar_clave_propia(self, email: str, actual: str, nueva: str, token: str) -> None:
        """Cambio por el propio usuario: exige la contraseña actual (un fallo cuenta para el bloqueo de la cuenta,
        como en el login) y conserva solo la sesión desde la que se pide; revoca las demás."""
        if len(nueva) < CLAVE_MIN:
            raise ErrorAdmin(f"la contraseña debe tener al menos {CLAVE_MIN} caracteres")
        if nueva == actual:
            raise ErrorAdmin("la contraseña nueva debe ser distinta de la actual")
        ahora = self._ahora()
        async with self._sesiones() as s:
            u = (await s.execute(
                select(AdminUsuario).where(AdminUsuario.email == _normalizar(email))
            )).scalar_one_or_none()
        if u is None or not u.activo:
            raise ErrorAdmin("usuario inexistente", "usuario_inexistente")
        if u.bloqueado_hasta is not None and u.bloqueado_hasta > ahora:
            raise ErrorAdmin("cuenta bloqueada temporalmente", "clave_actual_incorrecta")
        if not await self._verificar(u.hash, actual):
            await self._registrar_fallo(u.id, u.email, ahora)
            raise ErrorAdmin("la contraseña actual no es correcta", "clave_actual_incorrecta")
        hash_ = await asyncio.to_thread(_hasher.hash, nueva)
        async with self._sesiones.begin() as s:
            await s.execute(update(AdminUsuario).where(AdminUsuario.id == u.id)
                            .values(hash=hash_, fallos=0, bloqueado_hasta=None))
            await s.execute(delete(AdminSesion).where(
                AdminSesion.usuario_id == u.id, AdminSesion.token_hash != _sha(token)))

    async def listar_usuarios(self) -> list[dict]:
        async with self._sesiones() as s:
            filas = (await s.execute(select(AdminUsuario).order_by(AdminUsuario.email))).scalars().all()
        ahora = self._ahora()
        return [{"id": str(u.id), "email": u.email, "rol": u.rol, "activo": u.activo,
                 "bloqueado": bool(u.bloqueado_hasta and u.bloqueado_hasta > ahora),
                 "ultimo_login": u.ultimo_login.isoformat() if u.ultimo_login else None} for u in filas]

    async def modificar_usuario(self, usuario_id: uuid.UUID, *, rol: str | None = None,
                                activo: bool | None = None, actor: str) -> dict:
        """Cambia rol y/o estado. Nunca deja al sistema sin un admin activo ni deja que alguien se quite a sí
        mismo el acceso. Revoca las sesiones del usuario (un rol o estado nuevo exige volver a entrar)."""
        if rol is not None and rol not in ROLES:
            raise ErrorAdmin(f"rol inválido (use {' o '.join(ROLES)})")
        async with self._sesiones.begin() as s:
            # Se bloquean todos los admin: dos cambios simultáneos no pueden dejar cero entre los dos.
            admins = (await s.execute(
                select(AdminUsuario).where(AdminUsuario.rol == "admin", AdminUsuario.activo.is_(True))
                .with_for_update())).scalars().all()
            u = (await s.execute(
                select(AdminUsuario).where(AdminUsuario.id == usuario_id).with_for_update()
            )).scalar_one_or_none()
            if u is None:
                raise ErrorAdmin("usuario inexistente", "usuario_inexistente")
            nuevo_rol = u.rol if rol is None else rol
            nuevo_activo = u.activo if activo is None else activo
            pierde_acceso_admin = u.rol == "admin" and u.activo and not (nuevo_rol == "admin" and nuevo_activo)
            if pierde_acceso_admin:
                if u.email == actor:
                    raise ErrorAdmin("no puede quitarse su propio acceso de admin", "auto_cambio")
                if len(admins) <= 1:
                    raise ErrorAdmin("debe quedar al menos un admin activo", "ultimo_admin")
            if (nuevo_rol, nuevo_activo) != (u.rol, u.activo):
                u.rol, u.activo = nuevo_rol, nuevo_activo
                await s.execute(delete(AdminSesion).where(AdminSesion.usuario_id == u.id))
            return {"id": str(u.id), "email": u.email, "rol": u.rol, "activo": u.activo}

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
            await self._registrar_fallo(u.id, u.email, ahora)
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

    async def _registrar_fallo(self, usuario_id: uuid.UUID, email: str, ahora: datetime) -> None:
        """Cuenta el fallo con un UPDATE atómico: leer-y-escribir dejaba que intentos en paralelo no sumaran."""
        async with self._sesiones.begin() as s:
            fallos = (await s.execute(
                update(AdminUsuario).where(AdminUsuario.id == usuario_id)
                .values(fallos=AdminUsuario.fallos + 1).returning(AdminUsuario.fallos))).scalar_one()
            if fallos >= FALLOS_MAX:
                await s.execute(update(AdminUsuario).where(AdminUsuario.id == usuario_id)
                                .values(fallos=0, bloqueado_hasta=ahora + BLOQUEO))
                s.add(AdminAuditoria(actor=email[:320], accion="cuenta_bloqueada", despues={"minutos": int(BLOQUEO.total_seconds() // 60)}))

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

    async def purgar_auditoria(self, dias: int) -> int:
        """Borra la auditoría del panel con más de `dias` días. `dias <= 0` no borra nada."""
        if dias <= 0:
            return 0
        corte = self._ahora() - timedelta(days=dias)
        async with self._sesiones.begin() as s:
            r = await s.execute(delete(AdminAuditoria).where(AdminAuditoria.fecha < corte))
        return r.rowcount or 0

    async def listar_auditoria(self, *, limite: int = 50, antes_id: int | None = None,
                               actor: str | None = None, accion: str | None = None) -> dict:
        """Más recientes primero, paginado por cursor (`antes_id`: solo filas con id menor). Pide una fila de
        más para saber si hay página siguiente sin contar toda la tabla."""
        limite = max(1, min(limite, 200))
        q = select(AdminAuditoria).order_by(AdminAuditoria.id.desc()).limit(limite + 1)
        if antes_id is not None:
            q = q.where(AdminAuditoria.id < antes_id)
        if actor:
            q = q.where(AdminAuditoria.actor == actor)
        if accion:
            q = q.where(AdminAuditoria.accion == accion)
        async with self._sesiones() as s:
            filas = list((await s.execute(q)).scalars().all())
        hay_mas = len(filas) > limite
        filas = filas[:limite]
        return {
            "eventos": [{"id": f.id, "fecha": f.fecha.isoformat(), "actor": f.actor, "accion": f.accion,
                         "objetivo": f.objetivo, "antes": f.antes, "despues": f.despues, "ip": f.ip}
                        for f in filas],
            "siguiente": filas[-1].id if hay_mas and filas else None,
        }

    async def auditar(self, actor: str, accion: str, objetivo: str | None = None, *,
                      antes: dict | None = None, despues: dict | None = None, ip: str | None = None) -> None:
        async with self._sesiones.begin() as s:
            s.add(AdminAuditoria(actor=actor, accion=accion, objetivo=objetivo, antes=antes,
                                 despues=despues, ip=ip))
