"""PDF adjunto desde el chat web: el servidor lo expande a una imagen JPEG por página."""

import base64
import io
from dataclasses import replace

import pytest
from PIL import Image

from asistente.api.chat import ImagenIn, _expandir_pdfs
from asistente.core import adjuntos as adj
from asistente.core.llm.base import Adjunto, describir_orden


def _pdf(paginas: int) -> str:
    img = Image.new("RGB", (300, 400), "white")
    buf = io.BytesIO()
    img.save(buf, "PDF", save_all=True, append_images=[img] * (paginas - 1))
    return base64.b64encode(buf.getvalue()).decode()


async def _expandir(*entradas: ImagenIn, n: int = 3):
    return await _expandir_pdfs(list(entradas), max_imagenes=n, max_bytes=700 * 1024)


async def test_pdf_se_convierte_en_una_imagen_por_pagina():
    pares, origenes = await _expandir(ImagenIn(tipo="application/pdf", datos=_pdf(2)))
    assert [t for t, _ in pares] == ["image/jpeg"] * 2
    assert origenes == ["pdf1", "pdf1"]
    assert len(adj.decodificar(pares, max_imagenes=3, max_bytes=700 * 1024)) == 2


async def test_pdf_con_mas_paginas_de_las_que_caben_se_rechaza():
    with pytest.raises(adj.AdjuntoInvalido) as e:
        await _expandir(ImagenIn(tipo="application/pdf", datos=_pdf(4)))
    assert e.value.codigo == "pdf_demasiadas_paginas"


async def test_las_paginas_cuentan_como_imagenes():
    jpeg = io.BytesIO()
    Image.new("RGB", (10, 10)).save(jpeg, "JPEG")
    foto = ImagenIn(tipo="image/jpeg", datos=base64.b64encode(jpeg.getvalue()).decode())
    with pytest.raises(adj.AdjuntoInvalido) as e:
        await _expandir(foto, foto, ImagenIn(tipo="application/pdf", datos=_pdf(2)))
    assert e.value.codigo == "pdf_demasiadas_paginas"


@pytest.mark.parametrize("datos", ["no-es-base64!", base64.b64encode(b"no soy un pdf").decode()])
async def test_pdf_invalido(datos):
    with pytest.raises(adj.AdjuntoInvalido) as e:
        await _expandir(ImagenIn(tipo="application/pdf", datos=datos))
    assert e.value.codigo == "imagenes_invalidas"


async def test_foto_y_pdf_se_distinguen_en_el_origen_y_en_la_nota():
    jpeg = io.BytesIO()
    Image.new("RGB", (10, 10)).save(jpeg, "JPEG")
    foto = ImagenIn(tipo="image/jpeg", datos=base64.b64encode(jpeg.getvalue()).decode())
    pares, origenes = await _expandir(foto, ImagenIn(tipo="application/pdf", datos=_pdf(2)))
    assert origenes == ["", "pdf1", "pdf1"]
    ads = tuple(replace(a, origen=o) for a, o in zip(adj.decodificar(pares, max_imagenes=3, max_bytes=700 * 1024), origenes))
    orden = describir_orden(ads)
    assert "imagen 1: foto" in orden and "imagen 3: página 2 del documento PDF 1" in orden
    assert adj.marca(ads) == "[El usuario adjuntó un PDF (2 páginas) y 1 imagen; no se conservan.]"
    assert describir_orden(ads[:1]) == ""


def test_marca_de_solo_fotos_no_cambia():
    assert adj.marca((Adjunto("image/jpeg", b"x", 1),)) == "[El usuario adjuntó 1 imagen; no se conserva.]"
