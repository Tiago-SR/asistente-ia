"""Validación de JWT de usuario por sistema (secciones 1 y 6 del contrato).

El sistema se deduce del claim `iss` del propio token: `iss` → registro → clave y
algoritmo de ese sistema. Nunca se acepta un algoritmo que no sea el configurado
(así se rechazan `none` y los ataques de confusión de algoritmo).
"""

import asyncio
import logging
from dataclasses import dataclass

import jwt
from jwt import PyJWKClient

from asistente.sistemas.registro import RegistroSistemas, Sistema

log = logging.getLogger(__name__)

SCOPE_LECTURA = "asistente:lectura"
SCOPE_ESCRITURA = "asistente:escritura"
# Un token de escritura es de un solo uso y de vida muy corta (lo emite el sistema para una confirmación).
MAX_VIDA_ESCRITURA_S = 120
CLAIMS_OBLIGATORIOS = ["iss", "aud", "sub", "iat", "exp", "jti", "scope"]


class TokenInvalido(Exception):
    """Token rechazado. `expirado` permite al widget renovar y reintentar."""

    def __init__(self, motivo: str, *, expirado: bool = False) -> None:
        super().__init__(motivo)
        self.expirado = expirado


@dataclass(frozen=True)
class AccionClaims:
    """Claims propios del token de escritura: solo sirve para esa tool, esos parámetros y esa confirmación."""

    act: str  # nombre de la tool
    ph: str   # huella de los parámetros, emitida por el sistema
    cid: str  # id de la confirmación


@dataclass(frozen=True)
class Usuario:
    sistema_id: str
    usuario_ref: str
    jti: str
    nombre: str | None
    tenants: tuple[str, ...]
    locale: str | None
    token: str  # credencial para llamar al sistema; nunca se loguea ni se persiste
    accion: AccionClaims | None = None  # solo con scope de escritura


class Autenticador:
    def __init__(self, registro: RegistroSistemas) -> None:
        self._registro = registro
        self._jwks: dict[str, PyJWKClient] = {}

    async def validar(self, token: str, scope: str = SCOPE_LECTURA) -> Usuario:
        sistema = self._sistema_del_token(token)
        clave = await self._clave(sistema, token)
        auth = sistema.auth
        try:
            claims = jwt.decode(
                token,
                clave,
                algorithms=[auth.algoritmo],
                audience=auth.audiencia,
                issuer=sistema.id,
                leeway=auth.tolerancia_reloj_s,
                options={"require": CLAIMS_OBLIGATORIOS},
            )
        except jwt.ExpiredSignatureError as e:
            raise TokenInvalido("token vencido", expirado=True) from e
        except jwt.PyJWTError as e:
            raise TokenInvalido(f"token inválido: {type(e).__name__}") from e

        if claims["scope"] != scope:
            raise TokenInvalido("scope insuficiente")
        sub, jti = claims["sub"], claims["jti"]
        if not isinstance(sub, str) or not sub or not isinstance(jti, str) or not jti:
            raise TokenInvalido("sub/jti inválidos")

        accion = None
        if scope == SCOPE_ESCRITURA:
            accion = _claims_accion(claims)
        tenants = claims.get("tenants") or []
        return Usuario(
            sistema_id=sistema.id,
            usuario_ref=sub,
            jti=jti,
            nombre=_str_o_none(claims.get("nombre")),
            tenants=tuple(str(t) for t in tenants) if isinstance(tenants, list) else (),
            locale=_str_o_none(claims.get("locale")),
            token=token,
            accion=accion,
        )

    def _sistema_del_token(self, token: str) -> Sistema:
        try:
            iss = jwt.decode(token, options={"verify_signature": False}).get("iss")
        except jwt.PyJWTError as e:
            raise TokenInvalido("token malformado") from e
        # Mensaje único para "iss desconocido" y "sistema deshabilitado": no revela cuáles existen.
        sistema = self._registro.obtener(iss) if isinstance(iss, str) else None
        if sistema is None:
            raise TokenInvalido("emisor desconocido")
        return sistema

    async def _clave(self, sistema: Sistema, token: str):
        auth = sistema.auth
        env = self._registro.env
        if auth.secreto_env:
            return sistema.secreto(auth.secreto_env, env)
        if auth.clave_publica_env:
            return sistema.secreto(auth.clave_publica_env, env)
        assert auth.jwks_url
        cliente = self._jwks.setdefault(sistema.id, PyJWKClient(auth.jwks_url, timeout=5))
        try:
            return (await asyncio.to_thread(cliente.get_signing_key_from_jwt, token)).key
        except jwt.PyJWTError as e:
            log.warning("no se pudo obtener la clave JWKS de %s: %s", sistema.id, e)
            raise TokenInvalido("clave de firma no disponible") from e


def _claims_accion(claims: dict) -> AccionClaims:
    act, ph, cid = claims.get("act"), claims.get("ph"), claims.get("cid")
    if not all(isinstance(v, str) and v for v in (act, ph, cid)):
        raise TokenInvalido("token de escritura sin act/ph/cid")
    if claims["exp"] - claims["iat"] > MAX_VIDA_ESCRITURA_S:
        raise TokenInvalido("token de escritura con vida demasiado larga")
    return AccionClaims(act, ph, cid)


def _str_o_none(valor: object) -> str | None:
    return valor if isinstance(valor, str) and valor else None
