"""Sirve el panel de administración (SPA compilada con Vite) en `/panel`.

Son archivos estáticos que van en la imagen (el contenedor es `read_only`): no se leen en memoria ni se
escriben en runtime. Las cabeceras de seguridad se aplican solo a esta ruta. El enrutado del panel usa el hash
de la URL, así que no hace falta un fallback a `index.html`.
En dev el panel lo sirve Vite con HMR (ver docker-compose.dev.yml) y esta carpeta no existe.
"""

from pathlib import Path

from fastapi import FastAPI
from starlette.staticfiles import StaticFiles
from starlette.types import Scope

DIRECTORIO = Path(__file__).resolve().parent.parent / "static" / "panel"

CABECERAS = {
    # Sin scripts ni estilos de terceros; la tipografía va empaquetada. `style-src 'unsafe-inline'` por los
    # atributos `style` de los componentes (Radix/base-ui); los scripts siguen siendo solo 'self'.
    "Content-Security-Policy": (
        "default-src 'self'; script-src 'self'; style-src 'self' 'unsafe-inline'; img-src 'self' data:; "
        "font-src 'self'; connect-src 'self'; object-src 'none'; base-uri 'none'; form-action 'self'; "
        "frame-ancestors 'none'"
    ),
    "X-Frame-Options": "DENY",
    "X-Content-Type-Options": "nosniff",
    "Referrer-Policy": "no-referrer",
    "Cache-Control": "no-cache",
}


class _Panel(StaticFiles):
    async def get_response(self, path: str, scope: Scope):
        r = await super().get_response(path, scope)
        r.headers.update(CABECERAS)
        # Los archivos con hash en el nombre (assets/) no cambian nunca: se pueden cachear.
        if path.startswith("assets/"):
            r.headers["Cache-Control"] = "public, max-age=31536000, immutable"
        return r


def montar(app: FastAPI, directorio: Path = DIRECTORIO) -> bool:
    if not (directorio / "index.html").is_file():
        return False
    app.mount("/panel", _Panel(directory=directorio, html=True), name="panel")
    return True
