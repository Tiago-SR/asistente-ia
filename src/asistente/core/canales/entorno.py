"""Marca visible de los mensajes de WhatsApp enviados fuera de producción."""

import os


def marcar_mensaje(texto: str) -> str:
    entorno = os.environ.get("ASISTENTE_ENTORNO", "dev").strip().lower()
    if entorno in {"prod", "production", "produccion"}:
        return texto
    return f"[DEV] {texto}"
