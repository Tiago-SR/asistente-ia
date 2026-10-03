"""LLM de guion para tests: devuelve respuestas predefinidas y registra las llamadas."""

from collections.abc import Callable
from dataclasses import dataclass

from asistente.core.llm.base import (
    Capacidades,
    LlamadaTool,
    Mensaje,
    OnDelta,
    Respuesta,
    ToolDef,
    Uso,
)


@dataclass
class LlamadaRecibida:
    modelo: str
    system: str
    tools: list[ToolDef]
    messages: list[Mensaje]
    max_tokens: int


USO = Uso(10, 5)


def texto(t: str, uso: Uso = USO) -> Respuesta:
    return Respuesta(t, (), "fin", uso)


def pide(*llamadas: LlamadaTool, texto_previo: str = "", uso: Uso = USO) -> Respuesta:
    return Respuesta(texto_previo, tuple(llamadas), "tool", uso)


class LLMFalso:
    """`guion`: lista de Respuesta o funciones `(LlamadaRecibida) -> Respuesta`, una por llamada."""

    def __init__(self, guion: list[Respuesta | Callable[[LlamadaRecibida], Respuesta]]) -> None:
        self._guion = list(guion)
        self.llamadas: list[LlamadaRecibida] = []
        self.capacidades = Capacidades()

    async def stream(
        self,
        *,
        modelo: str,
        system: str,
        tools: list[ToolDef],
        messages: list[Mensaje],
        max_tokens: int,
        on_delta: OnDelta | None = None,
    ) -> Respuesta:
        rec = LlamadaRecibida(modelo, system, list(tools), list(messages), max_tokens)
        self.llamadas.append(rec)
        if not self._guion:
            raise AssertionError("el guion del LLM falso se agotó")
        paso = self._guion.pop(0)
        resp = paso(rec) if callable(paso) else paso
        if on_delta and resp.texto:
            for palabra in resp.texto.split(" "):
                await on_delta(palabra + " ")
        return resp
