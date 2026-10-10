"""Imágenes de referencia que el usuario adjunta a un mensaje.

Hoy viajan solo durante el turno: se validan, se mandan al modelo y no se guardan (`NoGuarda`). Lo que queda
en la conversación es una marca de texto y la metadata. Para conservarlas más adelante basta otra implementación
de `AlmacenAdjuntos`: el agente, el contrato del chat y el widget no cambian.
"""

import base64
import binascii
from collections.abc import Sequence
from dataclasses import replace
from typing import Protocol

from asistente.core.llm.base import Adjunto, Mensaje

# Solo formatos que el modelo acepta con certeza; el widget re-codifica todo a JPEG antes de enviar.
TIPOS = {"image/jpeg": (b"\xff\xd8\xff",), "image/png": (b"\x89PNG\r\n\x1a\n",)}


class AdjuntoInvalido(ValueError):
    """`codigo` es el que ve el cliente (`imagenes_invalidas`, `imagen_demasiado_grande`, `demasiadas_imagenes`)."""

    def __init__(self, codigo: str) -> None:
        super().__init__(codigo)
        self.codigo = codigo


def decodificar(imagenes: Sequence[tuple[str, str]], *, max_imagenes: int, max_bytes: int) -> tuple[Adjunto, ...]:
    """(tipo_mime, base64) → adjuntos validados: tipo permitido, base64 estricto, firma coherente con el tipo."""
    if len(imagenes) > max_imagenes:
        raise AdjuntoInvalido("demasiadas_imagenes")
    salida: list[Adjunto] = []
    for tipo, b64 in imagenes:
        firmas = TIPOS.get(tipo)
        if firmas is None:
            raise AdjuntoInvalido("imagenes_invalidas")
        if len(b64) > max_bytes * 4 // 3 + 8:  # corta antes de decodificar algo enorme
            raise AdjuntoInvalido("imagen_demasiado_grande")
        try:
            datos = base64.b64decode(b64, validate=True)
        except (binascii.Error, ValueError) as e:
            raise AdjuntoInvalido("imagenes_invalidas") from e
        if not datos or not datos.startswith(firmas):
            raise AdjuntoInvalido("imagenes_invalidas")
        if len(datos) > max_bytes:
            raise AdjuntoInvalido("imagen_demasiado_grande")
        salida.append(Adjunto(tipo, datos, len(datos)))
    return tuple(salida)


def marca(adjuntos: Sequence[Adjunto]) -> str:
    """Línea que queda en el historial en lugar de la imagen (también la lee el modelo en turnos siguientes)."""
    n = len(adjuntos)
    if not n:
        return ""
    return f"[El usuario adjuntó {n} imagen{'es' if n > 1 else ''}; no se conserva{'n' if n > 1 else ''}.]"


class AlmacenAdjuntos(Protocol):
    """Dónde se conservan las imágenes. `guardar` devuelve una referencia por adjunto (o None si no se guarda)."""

    async def guardar(self, sistema_id: str, usuario_ref: str, adjuntos: Sequence[Adjunto]) -> tuple[str | None, ...]: ...


class NoGuarda:
    """Política actual: las imágenes no se guardan; viajan solo en el turno."""

    async def guardar(self, sistema_id: str, usuario_ref: str, adjuntos: Sequence[Adjunto]) -> tuple[str | None, ...]:
        return tuple(None for _ in adjuntos)


async def para_guardar(m: Mensaje, almacen: AlmacenAdjuntos, sistema_id: str, usuario_ref: str) -> Mensaje:
    """El mensaje tal como se persiste: sin bytes, con la marca en el texto y la metadata (y `ref` si hay almacén)."""
    if m.rol != "user" or not m.adjuntos:
        return m
    refs = await almacen.guardar(sistema_id, usuario_ref, m.adjuntos)
    meta = tuple(replace(a, datos=b"", ref=r) for a, r in zip(m.adjuntos, refs, strict=True))
    texto = f"{m.texto}\n\n{marca(meta)}" if m.texto else marca(meta)
    return replace(m, texto=texto, adjuntos=meta)
