"""Composición del prompt de sistema en tres capas: base, dominio del sistema y contexto de sesión.

Devuelve también una versión (`hash base + hash dominio`) que se guarda en cada mensaje.
"""

import hashlib
import logging
from datetime import date
from pathlib import Path

log = logging.getLogger(__name__)

MAX_DOMINIO_BYTES = 20_000


def _hash(texto: str) -> str:
    return hashlib.sha256(texto.encode()).hexdigest()[:8]


class Prompts:
    def __init__(self, directorio: str | Path) -> None:
        self._dir = Path(directorio).resolve()
        self._base = (self._dir / "base.md").read_text(encoding="utf-8").strip()

    def _dominio(self, ruta: str | None) -> str:
        if not ruta:
            return ""
        # El archivo vive bajo prompts/: una ruta que se salga se ignora.
        archivo = (self._dir.parent / ruta).resolve()
        if not archivo.is_relative_to(self._dir):
            log.error("prompt_dominio fuera de %s: %s", self._dir, ruta)
            return ""
        try:
            if archivo.stat().st_size > MAX_DOMINIO_BYTES:
                log.error("prompt_dominio demasiado grande: %s", ruta)
                return ""
            return archivo.read_text(encoding="utf-8").strip()
        except OSError as e:
            log.error("prompt_dominio ilegible (%s): %s", ruta, e)
            return ""

    def componer(
        self,
        *,
        sistema_nombre: str,
        prompt_dominio: str | None,
        usuario_nombre: str | None,
        locale: str | None,
        hoy: date,
    ) -> tuple[str, str]:
        dominio = self._dominio(prompt_dominio)
        sesion = [f"Sistema: {sistema_nombre}.", f"Fecha de hoy: {hoy.isoformat()}."]
        if usuario_nombre:
            sesion.append(f"Usuario: {usuario_nombre}.")
        if locale:
            sesion.append(f"Idioma preferido del usuario: {locale}.")
        partes = [self._base]
        if dominio:
            partes.append("## Dominio del sistema\n" + dominio)
        partes.append("## Contexto de la sesión\n" + "\n".join(sesion))
        return "\n\n".join(partes), f"{_hash(self._base)}+{_hash(dominio)}"
