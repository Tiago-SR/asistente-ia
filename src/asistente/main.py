import asyncio
import logging
import os
from contextlib import asynccontextmanager

from fastapi import FastAPI, Request
from fastapi.exception_handlers import request_validation_exception_handler
from fastapi.exceptions import RequestValidationError
from fastapi.responses import JSONResponse
from sqlalchemy import text

from asistente.api import (
    admin,
    canal,
    chat,
    confirmaciones,
    conversaciones,
    descargas,
    estado,
    memoria,
    panel,
    privacidad,
    voz,
    widget,
)
from asistente.api.acceso_admin import AccesoAdmin
from asistente.api.cors import CorsSistemas
from asistente.api.errores import ErrorApi, manejar_error_api
from asistente.api.tope_cuerpo import TopeCuerpo
from asistente.config import Settings
from asistente.retencion import bucle_purga
from asistente.servicios import Servicios, construir
from asistente.store.admin import AdminSql
from asistente.store.resumen import ResumenSql

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
        purga = None
        if propio and app.state.servicios.settings.purga_intervalo_s > 0:
            svc = app.state.servicios
            purga = asyncio.create_task(
                bucle_purga(svc.registro, svc.repo, svc.settings.purga_intervalo_s, svc.acciones,
                            svc.auditoria, svc.memoria,
                            svc.admin or (AdminSql(svc.sesiones) if svc.sesiones is not None else None),
                            svc.settings.admin_auditoria_dias,
                            ResumenSql(svc.sesiones) if svc.sesiones is not None else None,
                            svc.archivos))
        escritor = None
        if propio and app.state.servicios.metricas is not None:
            escritor = asyncio.create_task(app.state.servicios.metricas.bucle())
        sondeo = None
        fuente = app.state.servicios.registro.fuente_bd
        if propio and fuente is not None:
            try:
                await fuente.cargar()
            except Exception as e:  # noqa: BLE001 readiness en falso (no un registro vacío); el sondeo reintenta
                log.error("registro de sistemas no disponible al arrancar: %s", type(e).__name__)
            for sis in app.state.servicios.registro.todos():  # un dominio roto = asistente sin sus reglas: no arrancar
                app.state.servicios.prompts.validar_dominio(sis.prompt_dominio)
            sondeo = asyncio.create_task(fuente.bucle())
        try:
            yield
        finally:
            for tarea in (purga, sondeo, escritor):
                if tarea:
                    tarea.cancel()
            svc = app.state.servicios
            if propio and escritor is not None:  # lo encolado se escribe antes de cerrar el motor
                try:
                    await asyncio.wait_for(svc.metricas.vaciar(), timeout=5)
                except Exception:  # noqa: BLE001 apagar no debe fallar por las métricas
                    log.warning("métricas: no se pudo vaciar la cola al apagar")
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

    async def validacion(request: Request, e: RequestValidationError):
        if not request.url.path.startswith("/admin/api"):
            return await request_validation_exception_handler(request, e)
        # El cuerpo del panel puede llevar secretos: el error por defecto de FastAPI repite el valor recibido.
        detalle = [{"campo": ".".join(str(x) for x in d["loc"] if x != "body"), "mensaje": d["msg"]}
                   for d in e.errors()]
        return JSONResponse({"error": "solicitud_invalida", "detalle": detalle}, status_code=422)

    app.add_exception_handler(RequestValidationError, validacion)
    app.add_middleware(CorsSistemas)
    app.add_middleware(AccesoAdmin)  # el último añadido es el más externo: corta antes que CORS
    app.add_middleware(TopeCuerpo)  # el más externo: corta antes que nadie parsee el cuerpo
    routers = (chat.router, confirmaciones.router, conversaciones.router, estado.router, memoria.router,
               voz.router, admin.router, widget.router, descargas.router, canal.router, privacidad.router)
    for r in routers:
        app.include_router(r)
    panel.montar(app)  # solo si la imagen trae el panel compilado (prod); en dev lo sirve Vite

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
        fuente = svc.registro.fuente_bd
        registro_listo = fuente is None or fuente.listo
        ok = bd and registro_listo
        cuerpo = {"ok": ok, "bd": bd, "sistemas": len(svc.registro.todos())}
        if not registro_listo:
            cuerpo["registro"] = "sin_cargar"
        return JSONResponse(cuerpo, status_code=200 if ok else 503)

    return app


app = create_app()
