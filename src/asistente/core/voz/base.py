"""Tipos neutros de voz (Fase 4). Como el LLM, cada proveedor va detrás de un puerto."""


class VozError(Exception):
    """Falla del proveedor de voz (red, HTTP, respuesta inválida). Sin secretos en el mensaje."""


class AudioInvalido(VozError):
    """El proveedor rechazó el audio (formato no soportado, vacío, ilegible)."""
