"""CORS dinámico: un origen vale si lo permite algún sistema registrado.

El preflight no lleva token, así que acá solo se acota por la unión de orígenes; la
verificación fina (origen del sistema del token) la hace `sesion_actual`.
"""

from starlette.datastructures import Headers
from starlette.types import ASGIApp, Receive, Scope, Send

_PERMITE = {
    b"access-control-allow-methods": b"GET, POST, DELETE, OPTIONS",
    b"access-control-allow-headers": b"Authorization, Content-Type",
    b"access-control-max-age": b"600",
}


class CorsSistemas:
    def __init__(self, app: ASGIApp) -> None:
        self.app = app

    def _permitidos(self, scope: Scope) -> set[str]:
        svc = getattr(scope["app"].state, "servicios", None)
        if svc is None:
            return set()
        return {o for s in svc.registro.todos() for o in s.origenes_permitidos}

    async def __call__(self, scope: Scope, receive: Receive, send: Send) -> None:
        if scope["type"] != "http":
            return await self.app(scope, receive, send)
        origen = Headers(scope=scope).get("origin")
        if origen is None or origen not in self._permitidos(scope):
            return await self.app(scope, receive, send)

        cabeceras = [(b"access-control-allow-origin", origen.encode()), (b"vary", b"Origin")]
        if scope["method"] == "OPTIONS" and "access-control-request-method" in Headers(scope=scope):
            cabeceras += list(_PERMITE.items())
            await send({"type": "http.response.start", "status": 204, "headers": cabeceras})
            return await send({"type": "http.response.body", "body": b""})

        async def con_cors(msg) -> None:
            if msg["type"] == "http.response.start":
                msg = {**msg, "headers": [*msg.get("headers", []), *cabeceras]}
            await send(msg)

        await self.app(scope, receive, con_cors)
