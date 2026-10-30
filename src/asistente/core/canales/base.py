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


# Códigos de error de Meta en un estado `failed` que el operador debe saber leer.
MOTIVOS_FALLO = {131047: "fuera de la ventana de 24 h", 131026: "número no entregable", 131052: "archivo demasiado grande"}


class Canal(Protocol):
    tiene_botones: bool  # False: las confirmaciones se piden por texto con un código (`enviar_botones` no sirve)

    def verificar_suscripcion(self, params: dict[str, str]) -> str | None:
        """Handshake GET del webhook: el desafío a devolver, o None si no corresponde (403)."""

    def autenticar(self, url: str, cuerpo: bytes, headers: dict[str, str]) -> bool:
        """¿El POST viene del proveedor? `url` va porque algunos firman la URL junto con el cuerpo."""

    def parsear(self, cuerpo: bytes) -> tuple[list[Entrante], list[EstadoEnvio]]:
        """Solo lo dirigido a este sistema; lo desconocido se ignora."""

    async def enviar_texto(self, contacto: str, texto: str) -> str:
        """Devuelve el id del mensaje enviado."""

    async def enviar_botones(self, contacto: str, cuerpo: str, botones: list[tuple[str, str]]) -> str:
        """Mensaje con botones de respuesta `(id, título)`. Devuelve el id del mensaje; ErrorCanal si el proveedor no puede."""

    async def descargar_medio(self, ref: str, max_bytes: int) -> tuple[bytes, str]:
        """`(bytes, mime)`."""

    async def probar(self) -> dict:
        """Comprueba credenciales y número; ErrorCanal si falla."""
