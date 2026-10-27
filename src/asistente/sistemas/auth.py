"""Validación de JWT de usuario por sistema (secciones 1 y 6 del contrato).

El sistema se deduce del claim `iss` del propio token: `iss` → registro → clave y
algoritmo de ese sistema. Nunca se acepta un algoritmo que no sea el configurado
(así se rechazan `none` y los ataques de confusión de algoritmo).
"""

import asyncio
import json
import logging
import time
from dataclasses import dataclass

import httpx
import jwt
from jwt import PyJWKSet

from asistente.core.red import ReglasRed, TransporteSeguro
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


class ClienteJwks:
    """Claves públicas de un `jwks_url`, descargadas con el cliente httpx del servicio (el mismo control de
    destinos que el conector, sin redirecciones). Caché con TTL; si llega un `kid` que no está, se vuelve a
    descargar, como mucho una vez cada `_REFRESCO_MIN_S` (un atacante con kids al azar no multiplica las
    peticiones al emisor)."""

    _TTL_S = 300.0
    _REFRESCO_MIN_S = 30.0
    _MAX_BYTES = 256 * 1024
    _EDAD_MAX_S = 86_400.0  # tope de edad de las claves que se siguen usando si el emisor no responde

    def __init__(self, url: str, cliente: httpx.AsyncClient, timeout_s: float = 5.0, reloj=time.monotonic) -> None:
        self._url = url
        self._cliente = cliente
        self._timeout = timeout_s
        self._reloj = reloj
        self._set: PyJWKSet | None = None
        self._descargado = float("-inf")
        self._lock = asyncio.Lock()
        self._no_antes = float("-inf")  # tras un fallo con claves previas, no se reintenta antes de este instante

    async def _descargar(self) -> None:
        cuerpo = bytearray()
        try:
            async with self._cliente.stream("GET", self._url, timeout=self._timeout,
                                            headers={"Accept": "application/json"}) as r:
                if r.status_code != 200:
                    raise jwt.PyJWKClientError(f"JWKS inválido (HTTP {r.status_code})")
                async for trozo in r.aiter_bytes():
                    cuerpo += trozo
                    if len(cuerpo) > self._MAX_BYTES:  # se corta: no se descarga un cuerpo sin tope
                        raise jwt.PyJWKClientError("JWKS demasiado grande")
        except httpx.HTTPError as e:
            raise jwt.PyJWKClientError(f"JWKS no disponible: {type(e).__name__}") from e
        try:
            self._set = PyJWKSet.from_dict(json.loads(cuerpo))
        except (ValueError, jwt.PyJWTError) as e:
            raise jwt.PyJWKClientError("JWKS malformado") from e
        self._descargado = self._reloj()

    async def _refrescar(self, vigente) -> None:
        """Descarga una sola vez aunque lleguen N peticiones a la vez; `vigente()` se reevalúa dentro del lock.
        Si falla y hay claves previas más jóvenes que `_EDAD_MAX_S`, se siguen usando."""
        async with self._lock:
            if vigente():
                return
            try:
                await self._descargar()
            except jwt.PyJWKClientError as e:
                if self._set is None or self._reloj() - self._descargado > self._EDAD_MAX_S:
                    raise
                log.warning("JWKS %s no disponible, se siguen usando las claves previas: %s", self._url, e)
                self._no_antes = self._reloj() + self._REFRESCO_MIN_S

    async def clave(self, token: str):
        kid = jwt.get_unverified_header(token).get("kid")
        if self._set is None or self._reloj() - self._descargado > self._TTL_S:
            await self._refrescar(lambda: self._set is not None and (
                self._reloj() - self._descargado <= self._TTL_S or self._reloj() < self._no_antes))
        claves = {k.key_id: k for k in self._set.keys}  # type: ignore[union-attr]
        if kid not in claves and self._reloj() - self._descargado > self._REFRESCO_MIN_S:
            await self._refrescar(lambda: self._reloj() - self._descargado <= self._REFRESCO_MIN_S
                                  or self._reloj() < self._no_antes)
            claves = {k.key_id: k for k in self._set.keys}  # type: ignore[union-attr]
        if kid is None and len(claves) == 1:
            return next(iter(claves.values())).key
        if kid not in claves:
            raise jwt.PyJWKClientError("kid desconocido")
        return claves[kid].key


class Autenticador:
    def __init__(self, registro: RegistroSistemas, cliente: httpx.AsyncClient | None = None) -> None:
        self._registro = registro
        # Sin cliente, uno con el control anti-SSRF (solo destinos públicos): nunca uno desnudo.
        self._http = cliente or httpx.AsyncClient(transport=TransporteSeguro(ReglasRed()), follow_redirects=False)
        # sistema_id → (jwks_url con la que se creó, cliente). La URL va en el valor para que un cambio
        # de `jwks_url` no siga usando el cliente (y las claves) del emisor anterior.
        self._jwks: dict[str, tuple[str, ClienteJwks]] = {}

    def invalidar_jwks(self, sistema_id: str | None = None) -> None:
        """Descarta las claves JWKS en caché (de un sistema o de todos), p. ej. tras recargar el registro."""
        if sistema_id is None:
            self._jwks.clear()
        else:
            self._jwks.pop(sistema_id, None)

    def _cliente_jwks(self, sistema_id: str, url: str) -> ClienteJwks:
        hit = self._jwks.get(sistema_id)
        if hit is None or hit[0] != url:
            hit = (url, ClienteJwks(url, self._http))
            self._jwks[sistema_id] = hit
        return hit[1]

    async def validar(self, token: str, scope: str = SCOPE_LECTURA, canal: str | None = None) -> Usuario:
        """`canal` debe coincidir con el claim del token: uno web (sin claim) no sirve en un canal ni al revés."""
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
        if claims.get("canal") != canal:
            raise TokenInvalido("canal no corresponde")
        sub, jti = claims["sub"], claims["jti"]
        if not isinstance(sub, str) or not sub or len(sub) > 240 or not sub.isprintable() or not isinstance(jti, str) or not jti:
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
            locale=_str_o_none(claims.get("locale")) or sistema.locale_defecto,
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
        if auth.algoritmo == "HS256":
            return self._registro.secreto(sistema.id, "auth_hs256")
        if auth.clave_publica:
            return auth.clave_publica
        assert auth.jwks_url
        cliente = self._cliente_jwks(sistema.id, auth.jwks_url)
        try:
            return await cliente.clave(token)
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
