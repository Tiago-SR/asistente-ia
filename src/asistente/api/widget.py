"""GET /widget.js: bundle público del Web Component, con ETag para validar la caché."""

import hashlib
from pathlib import Path

from fastapi import APIRouter, Request, Response

router = APIRouter()

_JS = (Path(__file__).resolve().parent.parent / "static" / "widget.js").read_bytes()
_ETAG = '"' + hashlib.sha256(_JS).hexdigest()[:16] + '"'
_CABECERAS = {
    "ETag": _ETAG,
    # Se revalida siempre (barato con ETag): un cambio del widget llega a todos los sistemas
    # sin esperar a que venza una caché.
    "Cache-Control": "public, no-cache",
    "X-Content-Type-Options": "nosniff",
}


@router.get("/widget.js", include_in_schema=False)
async def widget(request: Request) -> Response:
    if request.headers.get("if-none-match") == _ETAG:
        return Response(status_code=304, headers=_CABECERAS)
    return Response(_JS, media_type="text/javascript; charset=utf-8", headers=_CABECERAS)
