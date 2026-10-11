"""Tipos neutros de la búsqueda web. Como el LLM y la voz, cada proveedor va detrás de un puerto (`Buscador`)."""

from dataclasses import dataclass


class WebError(Exception):
    """Falla del proveedor (red, HTTP, respuesta inválida). Sin secretos en el mensaje."""


class CupoAgotado(WebError):
    """El proveedor rechazó por cupo del plan agotado (Tavily 432/433): conviene no volver a pedirle por un rato."""


class NoSoportado(WebError):
    """El proveedor no ofrece esta operación (SearXNG no lee páginas): se pasa al siguiente sin penalizarlo."""


class PaginaIlegible(WebError):
    """Esa página no se pudo leer (no es HTML, respondió 404, no carga). Es culpa de la página, no del proveedor:
    se prueba el siguiente, pero no se pausa a este."""


class UrlNoPermitida(WebError):
    """La URL apunta a un destino prohibido (red privada, puerto raro, esquema no http(s)). No se reintenta."""


@dataclass(frozen=True)
class ResultadoWeb:
    titulo: str
    url: str
    fragmento: str
    fecha: str | None = None


@dataclass(frozen=True)
class PaginaWeb:
    url: str
    titulo: str | None
    texto: str
    truncado: bool = False
    proveedor: str = ""


@dataclass(frozen=True)
class Busqueda:
    proveedor: str
    resultados: tuple[ResultadoWeb, ...]
