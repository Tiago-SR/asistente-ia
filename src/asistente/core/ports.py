"""Puertos del core. Sin dependencias de api/, sistemas/ ni store/."""

from collections.abc import Collection, Sequence
from dataclasses import dataclass, field
from datetime import datetime
from typing import Any, Protocol

from asistente.core.llm.base import Capacidades, Mensaje, OnDelta, Respuesta, ToolDef, Uso

__all__ = [
    "LLM",
    "STT",
    "AccionCreada",
    "Acciones",
    "Auditoria",
    "Capacidades",
    "Conector",
    "ConsultaPrevia",
    "Contexto",
    "LimiteExcedido",
    "Limites",
    "Memoria",
    "Recientes",
    "Recuerdo",
    "Recuerdos",
    "ResultadoPropuesta",
    "TopeMemoria",
    "TurnoMemoria",
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
    # Zona del usuario (IANA): resuelve «hoy» y «ayer»; se guarda con cada tool auditada.
    zona_horaria: str = "UTC"
    # Cuánto se conservan sus consultas (la ventana máxima de `consultas_recientes`).
    retencion_dias: int = 30


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
    # Tools locales: los parámetros ya validados y normalizados por el servidor. Son los que se guardan y se
    # aplican al confirmar (no los que escribió el modelo), así lo confirmado es exactamente lo mostrado.
    parametros_finales: dict | None = None

    @property
    def token_expirado(self) -> bool:
        return self.error == "token_expirado"


@dataclass(frozen=True)
class AccionCreada:
    id: str
    expira: str  # ISO 8601


@dataclass(frozen=True)
class ConsultaPrevia:
    """Una consulta de lectura que el usuario ya hizo (tool y parámetros, nunca el resultado),
    agrupada: `veces` cuenta las repeticiones idénticas y `ultima_vez` es la más reciente (UTC)."""

    tool: str
    parametros: dict
    ultima_vez: datetime
    veces: int
    zona_horaria: str | None  # la del usuario cuando la hizo; None si no se guardó


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


class TTS(Protocol):
    """Texto a voz. Devuelve el audio completo de una pieza corta (el widget pide frase por frase)."""

    tipo_mime: str

    async def sintetizar(self, texto: str, *, idioma: str | None = None) -> bytes: ...

    async def disponible(self) -> bool: ...


class Conector(Protocol):
    """Ligado a un usuario y una petición: ya lleva su credencial. `ejecutar` nunca lanza."""

    async def tools(self) -> list[ToolDef]: ...

    async def ejecutar(self, nombre: str, parametros: dict) -> ResultadoTool: ...

    async def proponer(self, nombre: str, parametros: dict) -> ResultadoPropuesta:
        """Pide al sistema validar y resumir una acción de escritura, sin ejecutarla."""
        ...

    async def validar_parametros(self, nombre: str, parametros: dict) -> ResultadoTool | None:
        """Comprueba, sin llamar al sistema, que `nombre` es una tool de LECTURA del manifiesto actual y que
        los parámetros cumplen su JSON Schema. `None` si es válida; si no, el fallo (`ResultadoTool`)."""
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


class Recientes(Protocol):
    """Historial de consultas del usuario, para repetirlas con datos actuales."""

    async def consultas(
        self, ctx: Contexto, tools: Collection[str], desde: datetime, limite: int
    ) -> list[ConsultaPrevia]:
        """Consultas exitosas de `tools` desde `desde`, de la más reciente a la más antigua.
        Solo las del `(sistema_id, usuario_ref)` de `ctx`."""
        ...


class Limites(Protocol):
    async def reservar_mensaje(self, ctx: Contexto) -> None:
        """Cuenta un mensaje del usuario; lanza `LimiteExcedido` si supera algún tope."""

    async def registrar_uso(self, ctx: Contexto, uso: Uso) -> None: ...

    async def reservar_voz(self, sistema_id: str, usuario_ref: str, tope_por_min: int, clave: str = "voz") -> None:
        """Cuenta un dictado (`clave="voz"`) o una síntesis (`clave="tts"`) del usuario, en un contador
        aparte del de mensajes y del otro; lanza `LimiteExcedido("voz_min")` si supera el tope."""


@dataclass(frozen=True)
class Recuerdo:
    """Algo que el usuario pidió recordar. `valor` ya validado por tipo (ver `core/memoria.py`)."""

    id: str
    tipo: str  # preferencia | alias | consulta_guardada
    clave: str
    valor: Any
    creada: datetime
    actualizada: datetime
    ultimo_uso: datetime


class TopeMemoria(Exception):
    """El usuario ya tiene el máximo de recuerdos en este sistema."""


class Recuerdos(Protocol):
    """Almacén de la memoria por usuario. TODO filtra por `(sistema_id, usuario_ref)`; lo vencido (sin uso en
    `ASISTENTE_MEMORIA_DIAS_SIN_USO` días) no se ve aunque la purga no haya corrido."""

    async def listar(self, sistema_id: str, usuario_ref: str, *, renovar: bool = False) -> list[Recuerdo]:
        """Los recuerdos vigentes. Con `renovar`, su antigüedad se renueva (a lo sumo una vez al día cada uno)."""
        ...

    async def obtener(self, sistema_id: str, usuario_ref: str, tipo: str, clave: str) -> Recuerdo | None: ...

    async def contar(self, sistema_id: str, usuario_ref: str) -> int: ...

    async def guardar(self, sistema_id: str, usuario_ref: str, tipo: str, clave: str, valor: Any) -> Recuerdo:
        """Crea o reemplaza (misma clave) de forma atómica. Lanza `TopeMemoria` si no hay lugar."""
        ...

    async def borrar_clave(self, sistema_id: str, usuario_ref: str, tipo: str, clave: str) -> bool: ...


@dataclass(frozen=True)
class TurnoMemoria:
    """Lo que el servicio de memoria necesita saber del turno en curso para validar una propuesta."""

    mensajes: Sequence[Mensaje]  # los del turno actual (los resultados de tool incluidos), no el historial
    lectura: frozenset[str]  # tools de lectura del manifiesto de hoy
    conector: Conector


class Memoria(Protocol):
    """Propuestas de las tools locales `recordar` y `olvidar`."""

    async def proponer(
        self, ctx: Contexto, nombre: str, parametros: dict, turno: TurnoMemoria
    ) -> ResultadoPropuesta:
        """Valida y redacta el resumen con una plantilla del SERVIDOR. No escribe nada."""
        ...
