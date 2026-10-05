"""Puertos del core. Sin dependencias de api/, sistemas/ ni store/."""

from dataclasses import dataclass, field
from typing import Any, Protocol

from asistente.core.llm.base import Capacidades, Mensaje, OnDelta, Respuesta, ToolDef, Uso

__all__ = [
    "LLM", "STT", "AccionCreada", "Acciones", "Auditoria", "Capacidades", "Conector", "Contexto",
    "LimiteExcedido", "Limites", "ResultadoPropuesta",
]


@dataclass(frozen=True)
class LimitesUso:
    mensajes_por_usuario_min: int
    mensajes_por_usuario_dia: int
    tokens_por_mes: int


@dataclass(frozen=True)
class Contexto:
    """Todo lo que el core necesita saber de quién pregunta. No lleva el token del usuario:
    ese lo tiene el conector, ligado a la petición."""

    sistema_id: str
    sistema_nombre: str
    usuario_ref: str
    jti: str
    request_id: str
    modelo: str
    prompt_system: str
    prompt_version: str
    limites: LimitesUso


@dataclass(frozen=True)
class ResultadoTool:
    ok: bool
    datos: Any = None
    fuente: str | None = None
    ui: list[dict] = field(default_factory=list)  # va al widget, no al modelo
    error: str | None = None
    detalle: str | None = None
    truncado: bool = False
    status_http: int | None = None
    bytes_respuesta: int | None = None

    @property
    def token_expirado(self) -> bool:
        return self.error == "token_expirado"

    def para_modelo(self) -> dict:
        """Lo que ve el LLM: datos o error, sin `ui`."""
        if not self.ok:
            return {"ok": False, "error": self.error, "detalle": self.detalle}
        return {"ok": True, "datos": self.datos, "fuente": self.fuente, "truncado": self.truncado}


@dataclass(frozen=True)
class ResultadoPropuesta:
    """Respuesta del sistema a la propuesta de una acción (sin efectos). El resumen lo redacta
    el sistema, no el modelo: es lo que el usuario confirma."""

    ok: bool
    resumen: str = ""
    lineas: tuple[str, ...] = ()
    huella: str = ""
    expira_s: int = 120
    error: str | None = None
    detalle_error: str | None = None
    status_http: int | None = None

    @property
    def token_expirado(self) -> bool:
        return self.error == "token_expirado"


@dataclass(frozen=True)
class AccionCreada:
    id: str
    expira: str  # ISO 8601


class LLM(Protocol):
    capacidades: Capacidades

    async def stream(
        self,
        *,
        modelo: str,
        system: str,
        tools: list[ToolDef],
        messages: list[Mensaje],
        max_tokens: int,
        on_delta: OnDelta | None = None,
    ) -> Respuesta: ...


class STT(Protocol):
    """Voz a texto (Fase 4). Independiente del LLM: el agente solo ve el texto resultante."""

    async def transcribir(self, audio: bytes, *, tipo_mime: str, idioma: str | None = None) -> str: ...

    async def disponible(self) -> bool: ...


class Conector(Protocol):
    """Ligado a un usuario y una petición: ya lleva su credencial. `ejecutar` nunca lanza."""

    async def tools(self) -> list[ToolDef]: ...

    async def ejecutar(self, nombre: str, parametros: dict) -> ResultadoTool: ...

    async def proponer(self, nombre: str, parametros: dict) -> ResultadoPropuesta:
        """Pide al sistema validar y resumir una acción de escritura, sin ejecutarla."""
        ...


class Acciones(Protocol):
    """Propuestas pendientes de confirmación del usuario."""

    async def crear(
        self, ctx: Contexto, conversacion_id: Any, tool: str, parametros: dict,
        propuesta: ResultadoPropuesta,
    ) -> AccionCreada:
        """Guarda la propuesta; reemplaza la pendiente anterior de la conversación.
        Lanza `LimiteExcedido("acciones_hora")` si el usuario propone demasiado."""


class Auditoria(Protocol):
    async def registrar_tool(
        self,
        ctx: Contexto,
        conversacion_id: Any,
        tool: str,
        parametros: dict,
        resultado: ResultadoTool,
        duracion_ms: int,
    ) -> None: ...


class LimiteExcedido(Exception):
    def __init__(self, cual: str) -> None:
        super().__init__(cual)
        self.cual = cual  # mensajes_min | mensajes_dia | tokens_mes


class Limites(Protocol):
    async def reservar_mensaje(self, ctx: Contexto) -> None:
        """Cuenta un mensaje del usuario; lanza `LimiteExcedido` si supera algún tope."""

    async def registrar_uso(self, ctx: Contexto, uso: Uso) -> None: ...

    async def reservar_voz(self, sistema_id: str, usuario_ref: str, tope_por_min: int) -> None:
        """Cuenta un dictado del usuario (contador aparte del de mensajes); lanza
        `LimiteExcedido("voz_min")` si supera el tope."""
