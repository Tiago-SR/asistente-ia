"""Cifrado de secretos del registro (AES-256-GCM).

`ASISTENTE_CLAVES_MAESTRAS="k2:<base64>,k1:<base64>"`: la primera cifra, todas descifran, así una rotación es
añadir la nueva al principio, re-cifrar (`rotar-clave`) y retirar la vieja. Cada secreto guarda el `kid` con el que
se cifró. El AAD es `sistema_id:campo`: copiar el texto cifrado a otra fila no se puede descifrar.
Si se pierde la clave no hay recuperación: hay que re-emitir los secretos con cada cliente.
"""

import base64
import binascii
import hashlib
import os
import re
from dataclasses import dataclass

from cryptography.exceptions import InvalidTag
from cryptography.hazmat.primitives.ciphers.aead import AESGCM

KID_RE = re.compile(r"^[A-Za-z0-9_-]{1,32}$")
LONGITUD_CLAVE = 32
LONGITUD_NONCE = 12


class ErrorCifrado(Exception):
    """Base: el mensaje nunca incluye claves ni valores."""


class ClaveAusente(ErrorCifrado):
    """No hay clave maestra configurada, o no está la que cifró el secreto."""


class DescifradoFallido(ErrorCifrado):
    """El texto cifrado no corresponde a esa clave / sistema / campo, o está corrupto."""


@dataclass(frozen=True)
class Cifrado:
    kid: str
    nonce: bytes
    cifrado: bytes


def huella(valor: str) -> str:
    """4 caracteres de un SHA-256: sirve para reconocer «es el mismo secreto» sin exponerlo."""
    return hashlib.sha256(valor.encode()).hexdigest()[:4]


def _aad(sistema_id: str, campo: str) -> bytes:
    return f"{sistema_id}:{campo}".encode()


class Cifrador:
    def __init__(self, claves: list[tuple[str, bytes]]) -> None:
        if not claves:
            raise ClaveAusente("no hay claves maestras (ASISTENTE_CLAVES_MAESTRAS)")
        kids = [k for k, _ in claves]
        if len(set(kids)) != len(kids):
            raise ErrorCifrado("kid repetido en las claves maestras")
        for kid, clave in claves:
            if not KID_RE.match(kid):
                raise ErrorCifrado("kid inválido en las claves maestras")
            if len(clave) != LONGITUD_CLAVE:
                raise ErrorCifrado(f"la clave {kid!r} debe tener {LONGITUD_CLAVE} bytes")
        self._claves = {kid: AESGCM(clave) for kid, clave in claves}
        self._kid_activo = claves[0][0]

    @classmethod
    def desde_texto(cls, texto: str | None) -> "Cifrador":
        """Formato `kid:base64[,kid:base64...]`. Los errores no reproducen el valor."""
        claves: list[tuple[str, bytes]] = []
        for parte in (texto or "").split(","):
            parte = parte.strip()
            if not parte:
                continue
            kid, sep, b64 = parte.partition(":")
            if not sep:
                raise ErrorCifrado("formato de claves maestras inválido: se espera kid:base64")
            try:
                claves.append((kid, base64.b64decode(b64, validate=True)))
            except (binascii.Error, ValueError) as e:
                raise ErrorCifrado(f"la clave {kid!r} no es base64 válido") from e
        return cls(claves)

    @classmethod
    def desde_entorno(cls, env: dict[str, str] | None = None) -> "Cifrador":
        return cls.desde_texto((env if env is not None else os.environ).get("ASISTENTE_CLAVES_MAESTRAS"))

    @property
    def kid_activo(self) -> str:
        return self._kid_activo

    def cifrar(self, sistema_id: str, campo: str, valor: str) -> Cifrado:
        nonce = os.urandom(LONGITUD_NONCE)
        texto = self._claves[self._kid_activo].encrypt(nonce, valor.encode(), _aad(sistema_id, campo))
        return Cifrado(self._kid_activo, nonce, texto)

    def descifrar(self, sistema_id: str, campo: str, c: Cifrado) -> str:
        clave = self._claves.get(c.kid)
        if clave is None:
            raise ClaveAusente(f"falta la clave maestra {c.kid!r}")
        try:
            return clave.decrypt(c.nonce, c.cifrado, _aad(sistema_id, campo)).decode()
        except (InvalidTag, UnicodeDecodeError, ValueError) as e:
            raise DescifradoFallido(f"no se pudo descifrar {campo!r} de {sistema_id!r}") from e

    def necesita_rotar(self, c: Cifrado) -> bool:
        return c.kid != self._kid_activo

    def rotar(self, sistema_id: str, campo: str, c: Cifrado) -> Cifrado:
        """Re-cifra con la clave activa. Si ya lo está, lo devuelve igual."""
        if not self.necesita_rotar(c):
            return c
        return self.cifrar(sistema_id, campo, self.descifrar(sistema_id, campo, c))


def generar_clave() -> str:
    """Una clave maestra nueva, en base64, lista para `kid:<esto>`."""
    return base64.b64encode(os.urandom(LONGITUD_CLAVE)).decode()
