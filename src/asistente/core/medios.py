"""Medios de un canal de mensajería (foto o PDF) → imágenes JPEG que `adjuntos.decodificar` acepta.

Todo en memoria y sin guardar nada. Entrada no confiable: tope de bytes, de píxeles, de páginas y de tiempo."""

import asyncio
import base64
import io
import threading
import warnings

import pypdfium2
from PIL import Image, ImageOps

MAX_MEDIO_BYTES = 10 * 1024 * 1024  # el tope de WhatsApp para imágenes y documentos es mayor; esto es lo que aceptamos
MAX_LADO = 1600
MAX_PAGINAS = 3
TIMEOUT_S = 15.0
_CALIDADES = (85, 75, 60, 45)

Image.MAX_IMAGE_PIXELS = 40_000_000
warnings.simplefilter("error", Image.DecompressionBombWarning)
_pdfium = threading.Lock()  # pdfium no es thread-safe


class MedioInvalido(ValueError):
    pass


def _jpeg(img: Image.Image, max_bytes: int) -> bytes:
    img = ImageOps.exif_transpose(img).convert("RGB")  # sin EXIF, sin canal alfa
    img.thumbnail((MAX_LADO, MAX_LADO))
    for q in _CALIDADES:
        buf = io.BytesIO()
        img.save(buf, "JPEG", quality=q)
        if buf.tell() <= max_bytes:
            return buf.getvalue()
    raise MedioInvalido("imagen_demasiado_grande")


def _convertir(datos: bytes, max_bytes: int, max_imagenes: int) -> list[bytes]:
    if len(datos) > MAX_MEDIO_BYTES:
        raise MedioInvalido("medio_demasiado_grande")
    try:
        if datos.startswith(b"%PDF-"):
            with _pdfium:
                pdf = pypdfium2.PdfDocument(datos)  # cifrado: lanza PdfiumError
                try:
                    salida = []
                    for i in range(min(len(pdf), MAX_PAGINAS, max_imagenes)):
                        pag = pdf[i]
                        ancho, alto = pag.get_size()  # puntos
                        if not 0 < ancho * alto <= 20_000_000:
                            raise MedioInvalido("medio_invalido")
                        escala = min(2.0, MAX_LADO / max(ancho, alto))
                        salida.append(_jpeg(pag.render(scale=escala).to_pil(), max_bytes))
                    return salida
                finally:
                    pdf.close()
        if datos.startswith((b"\xff\xd8\xff", b"\x89PNG\r\n\x1a\n")):
            with Image.open(io.BytesIO(datos)) as img:
                return [_jpeg(img, max_bytes)]
    except MedioInvalido:
        raise
    except Exception as e:  # PdfiumError, OSError, DecompressionBombError/Warning, etc.
        raise MedioInvalido("medio_invalido") from e
    raise MedioInvalido("medio_invalido")


async def a_imagenes(datos: bytes, *, max_bytes: int, max_imagenes: int) -> list[tuple[str, str]]:
    """Pares `(mime, base64)` listos para `adjuntos.decodificar`. `MedioInvalido` si no se puede convertir."""
    try:
        jpegs = await asyncio.wait_for(asyncio.to_thread(_convertir, datos, max_bytes, max_imagenes), TIMEOUT_S)
    except TimeoutError as e:
        raise MedioInvalido("medio_invalido") from e
    return [("image/jpeg", base64.b64encode(j).decode()) for j in jpegs]
