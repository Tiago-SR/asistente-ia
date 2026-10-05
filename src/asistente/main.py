import logging
import os
from contextlib import asynccontextmanager

from fastapi import FastAPI
from fastapi.responses import JSONResponse
from sqlalchemy import text

from asistente.api import admin, chat, conversaciones, estado, voz, widget
from asistente.api.cors import CorsSistemas
from asistente.api.errores import ErrorApi, manejar_error_api
from asistente.config import Settings
from asistente.servicios import Servicios, construir

log = logging.getLogger(__name__)


def create_app(servicios: Servicios | None = None) -> FastAPI:
    """Sin `servicios`, se construyen desde el entorno al arrancar (lifespan)."""

    @asynccontextmanager
    async def lifespan(app: FastAPI):
        propio = servicios is None
        if propio:
            settings = Settings()
            logging.basicConfig(level=settings.log_level)
            app.state.servicios = construir(settings)
        else:
            app.state.servicios = servicios
        try:
            yield
        finally:
            svc = app.state.servicios
            if propio and svc.cierre:
                await svc.cierre()

    # /docs y /openapi.json solo con ASISTENTE_DOCS=1 (dev); en prod no se exponen.
    docs = os.environ.get("ASISTENTE_DOCS") == "1"
    app = FastAPI(
        title="Asistente",
        version="0.1.0",
        lifespan=lifespan,
        docs_url="/docs" if docs else None,
        redoc_url=None,
        openapi_url="/openapi.json" if docs else None,
    )
    app.state.servicios = servicios
    app.add_exception_handler(ErrorApi, manejar_error_api)
    app.add_middleware(CorsSistemas)
    for r in (chat.router, conversaciones.router, estado.router, voz.router, admin.router, widget.router):
        app.include_router(r)

    @app.get("/salud")
    async def salud():
        svc: Servicios | None = app.state.servicios
        if svc is None:
            return {"ok": True}
        bd = True
        if svc.sesiones is not None:
            try:
                async with svc.sesiones() as s:
                    await s.execute(text("SELECT 1"))
            except Exception:
                log.exception("healthcheck: la BD no responde")
                bd = False
        cuerpo = {"ok": bd, "bd": bd, "sistemas": len(svc.registro.todos())}
        return JSONResponse(cuerpo, status_code=200 if bd else 503)

    return app


app = create_app()
