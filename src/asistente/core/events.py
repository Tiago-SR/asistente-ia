"""Eventos que el core emite hacia la capa API (que los serializa como SSE)."""

from collections.abc import Awaitable, Callable
from typing import Any

DELTA = "delta"
VOZ = "voz"  # resumen hablado (solo canal de voz)
TOOL = "tool"
UI = "ui"
CONFIRMACION = "confirmacion"
DONE = "done"
ERROR = "error"
TOKEN_EXPIRADO = "token_expirado"

Emit = Callable[[str, Any], Awaitable[None]]
