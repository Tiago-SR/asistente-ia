"""Tope de tamaño del cuerpo, antes de que FastAPI lo parsee: por `Content-Length` y por bytes realmente leídos
(un cliente puede mentir o usar chunked). El chat lleva imágenes en base64 (3 × 700 KB ≈ 2,9 MB) y el dictado audio:
esas rutas tienen 4 MB, igual que el nginx de ejemplo; el resto, 1 MB."""

from starlette.responses import JSONResponse
from starlette.types import ASGIApp, Message, Receive, Scope, Send

MAX_GENERAL = 1 * 1024 * 1024
MAX_GRANDE = 4 * 1024 * 1024
_RUTAS_GRANDES = ("/v1/chat", "/v1/voz/")


class TopeCuerpo:
    def __init__(self, app: ASGIApp) -> None:
        self.app = app

    async def __call__(self, scope: Scope, receive: Receive, send: Send) -> None:
        if scope["type"] != "http":
            return await self.app(scope, receive, send)
        tope = MAX_GRANDE if scope["path"].startswith(_RUTAS_GRANDES) else MAX_GENERAL
        declarado = dict(scope["headers"]).get(b"content-length", b"")
        if declarado.isdigit() and int(declarado) > tope:
            return await JSONResponse({"error": "cuerpo_demasiado_grande"}, status_code=413)(scope, receive, send)

        leidos = 0
        empezo = False

        async def recibir() -> Message:
            nonlocal leidos
            m = await receive()
            if m["type"] == "http.request":
                leidos += len(m.get("body", b""))
                if leidos > tope:
                    raise _Excedido
            return m

        async def enviar(m: Message) -> None:
            nonlocal empezo
            empezo = empezo or m["type"] == "http.response.start"
            await send(m)

        try:
            await self.app(scope, recibir, enviar)
        except _Excedido:
            if not empezo:
                await JSONResponse({"error": "cuerpo_demasiado_grande"}, status_code=413)(scope, receive, send)


class _Excedido(Exception):
    pass
