"""Imágenes de referencia: validación, traducción al modelo y API (solo en el turno, nunca guardadas)."""
# ruff: noqa: F811  (reutiliza fixtures de test_api.py por importación, como test_recientes_api.py)

import base64
import json
import os

import pytest
from sqlalchemy import select

from asistente.core import adjuntos as adj
from asistente.core.llm.base import Adjunto, Mensaje
from asistente.core.llm.falso import texto
from asistente.core.llm.openai_compat import NOTA_IMAGEN, _traducir
from asistente.store.models import Mensaje as FilaMensaje
from test_api import (  # noqa: F401  (fixtures y helpers)
    api,
    auth,
    construir_app,
    llm,
    sesiones,
    sse,
)

PNG = b"\x89PNG\r\n\x1a\n" + b"\x00" * 32
JPG = b"\xff\xd8\xff\xe0" + b"\x00" * 32


def b64(b: bytes) -> str:
    return base64.b64encode(b).decode()


def imagen(tipo="image/png", datos=PNG) -> dict:
    return {"tipo": tipo, "datos": b64(datos)}


# --- validación ----------------------------------------------------------------------------


def test_decodifica_png_y_jpeg_validos():
    r = adj.decodificar([("image/png", b64(PNG)), ("image/jpeg", b64(JPG))], max_imagenes=3, max_bytes=1000)
    assert [(a.tipo_mime, a.datos, a.bytes) for a in r] == [("image/png", PNG, len(PNG)), ("image/jpeg", JPG, len(JPG))]


@pytest.mark.parametrize("tipo,datos,codigo", [
    ("image/gif", b64(PNG), "imagenes_invalidas"),            # tipo no permitido
    ("image/png", b64(JPG), "imagenes_invalidas"),            # la firma no es la del tipo declarado
    ("image/png", "###no-es-base64###", "imagenes_invalidas"),
    ("image/png", "", "imagenes_invalidas"),
    ("image/png", b64(PNG + b"\x00" * 2000), "imagen_demasiado_grande"),
])
def test_rechaza_lo_invalido(tipo, datos, codigo):
    with pytest.raises(adj.AdjuntoInvalido) as e:
        adj.decodificar([(tipo, datos)], max_imagenes=3, max_bytes=1000)
    assert e.value.codigo == codigo


def test_rechaza_demasiadas_imagenes():
    with pytest.raises(adj.AdjuntoInvalido) as e:
        adj.decodificar([("image/png", b64(PNG))] * 4, max_imagenes=3, max_bytes=1000)
    assert e.value.codigo == "demasiadas_imagenes"


async def test_para_guardar_quita_los_bytes_y_deja_la_marca():
    m = Mensaje("user", "mirá esto", adjuntos=(Adjunto("image/png", PNG, len(PNG)),))
    g = await adj.para_guardar(m, adj.NoGuarda(), "s", "u")
    assert g.adjuntos == (Adjunto("image/png", b"", len(PNG), None),)
    assert g.texto.startswith("mirá esto") and "adjuntó 1 imagen" in g.texto
    sin = Mensaje("user", "hola")
    assert await adj.para_guardar(sin, adj.NoGuarda(), "s", "u") is sin


# --- traducción al modelo ----------------------------------------------------------------------


def test_traducir_manda_texto_e_imagen_como_partes():
    out = _traducir([Mensaje("user", "¿qué es?", adjuntos=(Adjunto("image/png", PNG, len(PNG)),))])
    partes = out[0]["content"]
    assert partes[0] == {"type": "text", "text": "¿qué es?"}
    assert partes[1] == {"type": "text", "text": NOTA_IMAGEN}   # la imagen es dato, no instrucción
    assert partes[2]["image_url"]["url"] == f"data:image/png;base64,{b64(PNG)}"


def test_traducir_ignora_adjuntos_sin_bytes_y_sin_texto():
    meta = Adjunto("image/png", b"", 10)   # lo que queda tras guardar: ya no se manda
    assert _traducir([Mensaje("user", "hola", adjuntos=(meta,))]) == [{"role": "user", "content": "hola"}]
    solo = _traducir([Mensaje("user", "", adjuntos=(Adjunto("image/png", PNG, 1),))])
    assert [p["type"] for p in solo[0]["content"]] == ["text", "image_url"]


# --- API -----------------------------------------------------------------------------------


necesita_bd = pytest.mark.skipif(not os.environ.get("ASISTENTE_DATABASE_URL"), reason="sin ASISTENTE_DATABASE_URL")


async def post(api, **cuerpo):
    return await api.post("/v1/chat", json=cuerpo, headers=auth())


@necesita_bd
async def test_imagenes_no_soportadas_422_y_el_estado_no_las_ofrece(api, llm):
    r = await post(api, mensaje="mirá", imagenes=[imagen()])
    assert r.status_code == 422 and r.json()["error"] == "imagenes_no_soportadas"
    assert "imagenes" not in (await api.get("/v1/estado", headers=auth())).json()


@necesita_bd
async def test_con_soporte_llega_al_modelo_y_no_se_guarda(api, llm, sesiones):
    llm.capacidades = type(llm.capacidades)(soporta_imagenes=True)
    llm.actual.capacidades = llm.capacidades
    guion = llm.usar(texto("Es un cuadrado"))
    llm.actual.capacidades = llm.capacidades
    r = await post(api, mensaje="¿qué ves?", imagenes=[imagen()])
    ev = sse(r)
    assert ev[-1][0] == "done"
    recibido = guion.llamadas[0].messages[0]
    assert recibido.texto == "¿qué ves?" and recibido.adjuntos[0].datos == PNG

    conv = ev[-1][1]["conversacion_id"]
    visibles = (await api.get(f"/v1/conversaciones/{conv}", headers=auth())).json()["mensajes"]
    assert "adjuntó 1 imagen" in visibles[0]["texto"]
    async with sesiones() as s:   # ni los bytes ni su base64 llegan a la base
        filas = (await s.execute(select(FilaMensaje))).scalars().all()
    volcado = json.dumps([f.contenido for f in filas])
    assert b64(PNG) not in volcado and "adjuntos" in volcado


@necesita_bd
async def test_estado_informa_las_imagenes_si_el_modelo_las_admite(api, llm):
    llm.capacidades = type(llm.capacidades)(soporta_imagenes=True)
    r = (await api.get("/v1/estado", headers=auth())).json()
    assert r["imagenes"] == {"max": 3, "max_kb": 700, "tipos": ["image/jpeg", "image/png"]}


@necesita_bd
@pytest.mark.parametrize("cuerpo,status,codigo", [
    ({"mensaje": "x", "imagenes": [{"tipo": "image/gif", "datos": b64(PNG)}]}, 422, "imagenes_invalidas"),
    ({"mensaje": "x", "imagenes": [{"tipo": "image/png", "datos": b64(PNG + b"\0" * 800_000)}]}, 413,
     "imagen_demasiado_grande"),
    ({"mensaje": "x", "imagenes": [imagen()] * 4}, 422, "demasiadas_imagenes"),
])
async def test_imagenes_invalidas(api, llm, cuerpo, status, codigo):
    llm.capacidades = type(llm.capacidades)(soporta_imagenes=True)
    r = await post(api, **cuerpo)
    assert r.status_code == status and r.json()["error"] == codigo


@necesita_bd
async def test_sin_texto_ni_imagen_es_invalido(api, llm):
    assert (await post(api, mensaje="  ")).json()["error"] == "mensaje_invalido"


# --- configuración por sistema ---------------------------------------------------------------------------


def _fabrica(tmp_path, monkeypatch, global_imagenes: bool, **llm):
    from asistente.config import Settings
    from asistente.servicios import _fabrica_llm
    from asistente.sistemas.registro import RegistroSistemas
    from conftest import entorno, entrada_sistema, escribir_registro

    cambios = {"llm": llm} if llm else {}
    reg = RegistroSistemas(escribir_registro(tmp_path / "s.yaml", [entrada_sistema("a", **cambios)]), env=entorno("a"))
    assert reg.errores == {}
    monkeypatch.setenv("ASISTENTE_DATABASE_URL", "postgresql+asyncpg://x/y")
    ajustes = Settings(LLM_BASE_URL="http://llm/v1", ASISTENTE_MODELO_DEFAULT="modelo-global", LLM_IMAGENES=global_imagenes)
    return _fabrica_llm(ajustes, reg)(reg.obtener("a"))


@pytest.mark.parametrize("global_,llm,esperado", [
    (False, {}, False),                                   # sin bloque llm: manda LLM_IMAGENES
    (True, {}, True),
    (False, {"imagenes": True}, True),                    # basta con `llm: {imagenes: true}` y hereda el modelo global
    (True, {"imagenes": False}, False),                   # el sistema lo apaga aunque el global lo encienda
    (True, {"modelo": "otro", "proveedor": "openai_compat"}, True),   # bloque llm sin `imagenes`: manda el global
])
def test_las_imagenes_se_configuran_por_sistema(tmp_path, monkeypatch, global_, llm, esperado):
    adaptador, modelo = _fabrica(tmp_path, monkeypatch, global_, **llm)
    assert adaptador.capacidades.soporta_imagenes is esperado
    assert modelo == llm.get("modelo", "modelo-global")
