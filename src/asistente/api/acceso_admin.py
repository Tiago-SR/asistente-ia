"""Defensa en profundidad: `/admin` y `/panel` solo se sirven a peticiones directas (túnel ssh o el host).

Si `ASISTENTE_ADMIN_HOSTS` (coma) no está vacío, una petición a `/admin` o `/panel` responde 404 cuando trae
cabeceras de proxy (`X-Forwarded-*`, `Forwarded`) o su `Host` no está en la lista. Así, un proxy mal copiado
(sin el bloqueo de `deploy/`) no deja el panel expuesto. Vacío = sin restricción (dev).
"""

from starlette.datastructures import Headers
from starlette.responses import PlainTextResponse
from starlette.types import ASGIApp, Receive, Scope, Send

_PREFIJOS = ("/admin", "/panel")
_PROXY = ("x-forwarded-for", "x-forwarded-host", "x-forwarded-proto", "x-real-ip", "forwarded")


def _es_admin(path: str) -> bool:
    return any(path == p or path.startswith(p + "/") for p in _PREFIJOS)


class AccesoAdmin:
    def __init__(self, app: ASGIApp) -> None:
        self.app = app

    def _hosts(self, scope: Scope) -> set[str]:
        svc = getattr(scope["app"].state, "servicios", None)
        if svc is None:
            return set()
        return {h.strip().lower() for h in svc.settings.admin_hosts.split(",") if h.strip()}

    async def __call__(self, scope: Scope, receive: Receive, send: Send) -> None:
        if scope["type"] != "http" or not _es_admin(scope["path"]):
            return await self.app(scope, receive, send)
        permitidos = self._hosts(scope)
        if permitidos:
            cabeceras = Headers(scope=scope)
            if any(c in cabeceras for c in _PROXY) or cabeceras.get("host", "").lower() not in permitidos:
                return await PlainTextResponse("Not Found", status_code=404)(scope, receive, send)
        await self.app(scope, receive, send)
