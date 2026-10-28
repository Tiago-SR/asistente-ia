"""Webhook de los canales de mensajería (hoy WhatsApp/Meta). Sin sesión ni CSRF: la autenticidad la decide el
proveedor del sistema (firma). Una ruta por sistema; todo fallo es la misma 403, para no enumerar sistemas.

El POST responde 200 enseguida (el proveedor reintenta si tarda) y el trabajo sigue en segundo plano."""

import logging
from datetime import UTC, datetime, timedelta

from fastapi import APIRouter, BackgroundTasks, Depends, Request
from fastapi.responses import PlainTextResponse

from asistente.api.canal_flujo import procesar
from asistente.api.deps import servicios
from asistente.api.errores import ErrorApi
from asistente.core import canales
from asistente.core.canales.base import MOTIVOS_FALLO as MOTIVOS
from asistente.core.canales.base import Canal
from asistente.servicios import Servicios

log = logging.getLogger(__name__)
router = APIRouter()
UMBRAL_FALLIDOS = 5  # envíos fallidos en una hora que se registran como error


def canal_de(svc: Servicios, sistema_id: str, *, habilitado: bool = True) -> Canal | None:
    s = svc.registro.obtener(sistema_id)
    if s is None or (habilitado and not s.habilitado):
        return None
    return canales.para(s.canal_mensajeria, lambda c: svc.registro.secreto(sistema_id, c), svc.http)


def _canal(svc: Servicios, sistema_id: str) -> Canal:
    canal = canal_de(svc, sistema_id)
    if canal is None:
        raise ErrorApi(403, "no_autorizado")
    return canal


@router.get("/canal/{sistema_id}/webhook")
async def verificar(sistema_id: str, request: Request, svc: Servicios = Depends(servicios)) -> PlainTextResponse:
    desafio = _canal(svc, sistema_id).verificar_suscripcion(dict(request.query_params))
    if desafio is None:
        raise ErrorApi(403, "no_autorizado")
    return PlainTextResponse(desafio)


@router.post("/canal/{sistema_id}/webhook")
async def recibir(sistema_id: str, request: Request, tareas: BackgroundTasks,
                  svc: Servicios = Depends(servicios)) -> dict:
    canal = _canal(svc, sistema_id)
    cuerpo = await request.body()  # TopeCuerpo ya cortó lo desmesurado
    if not canal.autenticar(str(request.url), cuerpo, dict(request.headers)):
        raise ErrorApi(403, "no_autorizado")
    entrantes, estados = canal.parsear(cuerpo)
    log.info("canal %s: webhook firmado con %d mensajes y %d estados", sistema_id, len(entrantes), len(estados))
    for e in estados:
        if e.estado == "fallido":
            log.warning("canal %s: envío fallido id=%s codigo=%s (%s)", sistema_id, e.id, e.codigo_error,
                        MOTIVOS.get(e.codigo_error, "otro"))
        await svc.canal_mensajes.actualizar_estado(
            sistema_id, e.id, e.estado, str(e.codigo_error) if e.codigo_error is not None else None)
        if e.estado == "fallido":
            n = len(await svc.canal_mensajes.fallidos(sistema_id, datetime.now(UTC) - timedelta(hours=1), UMBRAL_FALLIDOS))
            if n >= UMBRAL_FALLIDOS:
                log.error("canal %s: %d envíos fallidos en la última hora", sistema_id, n)
    for m in entrantes:
        # Solo metadatos, nunca contenido. Un reenvío (mismo id) no se procesa de nuevo.
        if await svc.canal_mensajes.registrar_entrada(sistema_id, m.id, m.contacto, m.tipo):
            tareas.add_task(procesar, svc, sistema_id, canal, m)
    return {"ok": True}
