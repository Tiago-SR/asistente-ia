"""Canal de mensajería (strategy): lo que el asistente necesita de WhatsApp o de cualquier otro proveedor.

Cada proveedor traduce su protocolo a estos tipos neutros; el resto del código no sabe de Graph, firmas ni payloads."""

from dataclasses import dataclass
from typing import Literal, Protocol

Tipo = Literal["texto", "imagen", "documento", "boton", "otro"]
EstadoEnvioT = Literal["enviado", "entregado", "leido", "fallido", "otro"]


class ErrorCanal(Exception):
    """Falla del proveedor. `codigo` es el código de error propio del proveedor, si vino."""

    def __init__(self, mensaje: str, *, estado: int | None = None, codigo: int | None = None) -> None:
        super().__init__(mensaje)
        self.estado, self.codigo = estado, codigo


@dataclass(frozen=True)
class Entrante:
    id: str
    contacto: str  # identificador del remitente en el proveedor (wa_id, sin «+»)
    tipo: Tipo
    texto: str | None = None
    medio_ref: str | None = None
    mime: str | None = None
    respuesta_a: str | None = None  # id del mensaje al que contesta (`context.id`)
    boton_id: str | None = None


@dataclass(frozen=True)
class EstadoEnvio:
    id: str
    estado: EstadoEnvioT
    codigo_error: int | None = None


class Canal(Protocol):
    def verificar_suscripcion(self, params: dict[str, str]) -> str | None:
        """Handshake GET del webhook: el desafío a devolver, o None si no corresponde (403)."""

    def autenticar(self, url: str, cuerpo: bytes, headers: dict[str, str]) -> bool:
        """¿El POST viene del proveedor? `url` va porque algunos firman la URL junto con el cuerpo."""

    def parsear(self, cuerpo: bytes) -> tuple[list[Entrante], list[EstadoEnvio]]:
        """Solo lo dirigido a este sistema; lo desconocido se ignora."""

    async def enviar_texto(self, contacto: str, texto: str) -> str:
        """Devuelve el id del mensaje enviado."""

    async def descargar_medio(self, ref: str, max_bytes: int) -> tuple[bytes, str]:
        """`(bytes, mime)`."""

    async def probar(self) -> dict:
        """Comprueba credenciales y número; ErrorCanal si falla."""
