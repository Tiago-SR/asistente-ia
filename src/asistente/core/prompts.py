"""Composición del prompt de sistema en tres capas: base, dominio del sistema y contexto de sesión.

Devuelve también una versión (`hash base + hash dominio`) que se guarda en cada mensaje.
"""

import hashlib
import logging
from collections.abc import Sequence
from datetime import date
from pathlib import Path

from asistente.core import memoria as memorias
from asistente.core.ports import Recuerdo

log = logging.getLogger(__name__)

MAX_DOMINIO_BYTES = 20_000


def _hash(texto: str) -> str:
    return hashlib.sha256(texto.encode()).hexdigest()[:8]


class Prompts:
    def __init__(self, directorio: str | Path) -> None:
        self._dir = Path(directorio).resolve()
        self._base = (self._dir / "base.md").read_text(encoding="utf-8").strip()
        # Capa del canal de voz (opcional): cómo pedir el resumen hablado. Ver core/voz_resumen.py.
        archivo_voz = self._dir / "voz.md"
        self._voz = archivo_voz.read_text(encoding="utf-8").strip() if archivo_voz.is_file() else ""
        # Capa de la búsqueda web (solo en los sistemas que la tienen): cómo separar internet de los datos del sistema.
        archivo_web = self._dir / "web.md"
        self._web = archivo_web.read_text(encoding="utf-8").strip() if archivo_web.is_file() else ""
        # Capa de lectura de imágenes (solo en los sistemas con `leer_imagenes`): relaja la regla (2) de `base.md`.
        archivo_img = self._dir / "imagenes.md"
        self._imagenes = archivo_img.read_text(encoding="utf-8").strip() if archivo_img.is_file() else ""
        # Capa del Excel descargable (solo en los sistemas con `exportar_excel`).
        archivo_excel = self._dir / "excel.md"
        self._excel = archivo_excel.read_text(encoding="utf-8").strip() if archivo_excel.is_file() else ""

    def validar_dominio(self, ruta: str | None) -> str:
        """Texto del dominio. Lanza `ValueError` si la ruta se sale de prompts/, pesa de más o no se lee."""
        if not ruta:
            return ""
        # El archivo vive bajo prompts/: una ruta que se salga no vale.
        archivo = (self._dir.parent / ruta).resolve()
        if not archivo.is_relative_to(self._dir):
            raise ValueError(f"prompt_dominio fuera de {self._dir}: {ruta}")
        try:
            if archivo.stat().st_size > MAX_DOMINIO_BYTES:
                raise ValueError(f"prompt_dominio demasiado grande: {ruta}")
            return archivo.read_text(encoding="utf-8").strip()
        except OSError as e:
            raise ValueError(f"prompt_dominio ilegible ({ruta}): {e}") from e

    def _dominio(self, ruta: str | None) -> str:
        # En ejecución no se tumba el chat por un dominio que cambió en el panel; al arrancar sí (`validar_dominio`).
        try:
            return self.validar_dominio(ruta)
        except ValueError as e:
            log.error("%s", e)
            return ""

    def componer(
        self,
        *,
        sistema_nombre: str,
        prompt_dominio: str | None,
        usuario_nombre: str | None,
        locale: str | None,
        hoy: date,
        canal: str = "texto",
        memoria: Sequence[Recuerdo] | None = None,
        web: bool = False,
        leer_imagenes: bool = False,
        excel: bool = False,
    ) -> tuple[str, str]:
        dominio = self._dominio(prompt_dominio)
        sesion = [f"Sistema: {sistema_nombre}.", f"Fecha de hoy: {hoy.isoformat()}."]
        if usuario_nombre:
            sesion.append(f"Usuario: {memorias._limpio(usuario_nombre, 80)}.")
        if locale:
            sesion.append(f"Idioma preferido del usuario: {memorias._limpio(locale, 20)}.")
        partes = [self._base]
        if dominio:
            partes.append("## Dominio del sistema\n" + dominio)
        version = f"{_hash(self._base)}+{_hash(dominio)}"
        if web and self._web:
            partes.append("## Búsqueda web\n" + self._web)
            version += f"+w{_hash(self._web)}"
        if leer_imagenes and self._imagenes:
            partes.append("## Lectura de imágenes\n" + self._imagenes)
            version += f"+i{_hash(self._imagenes)}"
        if excel and self._excel:
            partes.append("## Excel descargable\n" + self._excel)
            version += f"+x{_hash(self._excel)}"
        if canal == "voz" and self._voz:
            partes.append("## Canal de voz\n" + self._voz)
            version += f"+v{_hash(self._voz)}"
        partes.append("## Contexto de la sesión\n" + "\n".join(sesion))
        # Lo que el usuario pidió recordar es por usuario: va al final para no romper el prefijo cacheable (base y
        # dominio) y no entra en la versión, solo una marca.
        recordado = memorias.seccion_prompt(memoria or ())
        if recordado:
            partes.append(recordado)
            version += "+m"
        return "\n\n".join(partes), version
