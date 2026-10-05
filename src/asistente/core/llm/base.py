"""Formato neutro del core para hablar con un LLM (sección 3.8 del plan).

Nada de vocabulario de proveedor aquí: cada adaptador traduce de y hacia su API.
"""

from collections.abc import Awaitable, Callable
from dataclasses import dataclass, field
from typing import Literal

MotivoFin = Literal["fin", "tool", "limite"]
OnDelta = Callable[[str], Awaitable[None]]


class LLMError(Exception):
    """Falla del proveedor (red, HTTP, stream mal formado). El mensaje no incluye secretos."""


@dataclass(frozen=True)
class ToolDef:
    nombre: str
    descripcion: str
    parametros: dict  # JSON Schema de tipo object


@dataclass(frozen=True)
class LlamadaTool:
    id: str
    nombre: str
    parametros: dict
    # El modelo emitió argumentos que no son un objeto JSON: no se ejecuta, se le avisa.
    argumentos_invalidos: bool = False


@dataclass(frozen=True)
class Mensaje:
    """`user`: texto. `assistant`: texto y/o llamadas. `tool`: resultado de `llamada_id`."""

    rol: Literal["user", "assistant", "tool"]
    texto: str = ""
    llamadas: tuple[LlamadaTool, ...] = ()
    llamada_id: str | None = None


@dataclass(frozen=True)
class Uso:
    tokens_in: int = 0
    tokens_out: int = 0
    tokens_in_cache: int = 0  # parte de `tokens_in` servida desde la caché del proveedor (si la informa)

    def __add__(self, otro: "Uso") -> "Uso":
        return Uso(
            self.tokens_in + otro.tokens_in,
            self.tokens_out + otro.tokens_out,
            self.tokens_in_cache + otro.tokens_in_cache,
        )

    @property
    def total(self) -> int:
        return self.tokens_in + self.tokens_out


@dataclass(frozen=True)
class Respuesta:
    texto: str
    llamadas: tuple[LlamadaTool, ...] = ()
    motivo_fin: MotivoFin = "fin"
    uso: Uso = field(default_factory=Uso)

    def como_mensaje(self) -> Mensaje:
        return Mensaje("assistant", self.texto, self.llamadas)


@dataclass(frozen=True)
class Capacidades:
    soporta_cache: bool = False
    soporta_tools_paralelas: bool = True
    soporta_streaming_tools: bool = True
    contexto_max: int | None = None
