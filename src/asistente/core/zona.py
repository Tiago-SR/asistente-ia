"""Zona horaria del usuario: de dónde sale y cómo se valida."""

from zoneinfo import ZoneInfo, ZoneInfoNotFoundError

POR_DEFECTO = "UTC"


def valida(nombre: object) -> str | None:
    """El nombre IANA si existe (`America/Montevideo`), si no `None`. El nombre viene del navegador
    o de la configuración: nunca se confía en él sin comprobarlo."""
    if not isinstance(nombre, str) or not nombre or len(nombre) > 64:
        return None
    try:
        ZoneInfo(nombre)
    except (ZoneInfoNotFoundError, ValueError, OSError):
        return None
    return nombre


def resolver(*candidatas: object) -> str:
    """La primera zona válida de la lista (usuario, luego sistema); UTC si ninguna lo es."""
    return next((z for c in candidatas if (z := valida(c))), POR_DEFECTO)


def zona(nombre: str | None) -> ZoneInfo:
    return ZoneInfo(valida(nombre) or POR_DEFECTO)
