"""Página pública de privacidad y eliminación de datos (la piden Meta y otros proveedores de canal)."""

from html import escape

from fastapi import APIRouter, Depends
from fastapi.responses import HTMLResponse

from asistente.api.deps import servicios
from asistente.servicios import Servicios

router = APIRouter()

_HTML = """<!doctype html><html lang="es"><head><meta charset="utf-8"><meta name="viewport" content="width=device-width,initial-scale=1">
<title>Privacidad y eliminación de datos</title>
<style>body{{font:16px/1.5 system-ui,sans-serif;max-width:40rem;margin:2rem auto;padding:0 1rem}}</style></head><body>
<h1>Política de privacidad y eliminación de datos</h1>
<h2>Datos que se tratan</h2>
<p>Los mensajes que una persona envía a este asistente (por la web o por WhatsApp) y, en WhatsApp, su número de teléfono.</p>
<h2>Para qué se usan</h2>
<p>Solo para generar y enviar la respuesta del asistente. No se venden. Para responder, el texto de la consulta se envía al
proveedor del modelo de lenguaje configurado por el operador.</p>
<h2>Cuánto se conservan</h2>
<p>Las conversaciones se conservan durante el período de retención configurado por el operador y luego se eliminan. El registro de los mensajes recibidos por WhatsApp (sin contenido, con el número) se borra a los 8 días; el vínculo de tu número, tras el mismo período de retención sin usarlo.</p>
<h2>Cómo pedir la eliminación de tus datos</h2>
<p>{contacto}</p>
</body></html>"""


@router.get("/privacidad", response_class=HTMLResponse)
async def privacidad(svc: Servicios = Depends(servicios)) -> HTMLResponse:
    c = svc.settings.contacto_privacidad
    contacto = (f"Escribe a <a href=\"mailto:{escape(c)}\">{escape(c)}</a> indicando tu número de teléfono."
                if c else "Escribe al operador de este servicio indicando tu número de teléfono.")
    return HTMLResponse(_HTML.format(contacto=contacto))
