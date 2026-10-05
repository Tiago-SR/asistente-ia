"""Confirmación de acciones (Fase 5): el usuario confirma o cancela en el widget la escritura que el
asistente propuso. Nada se ejecuta sin este paso.

`confirmar` exige el token de escritura que el SISTEMA emitió para esta confirmación (scope
`asistente:escritura`, un solo uso, atado a la tool y a la huella de los parámetros): el asistente
no puede fabricarlo. El resumen que vio el usuario salió del sistema, no del modelo.
"""

import logging
import time
import uuid

from fastapi import APIRouter, Depends
from fastapi.responses import JSONResponse

from asistente.api.deps import Sesion, servicios, sesion_actual, sesion_escritura
from asistente.api.errores import ErrorApi
from asistente.core.ports import Contexto, LimitesUso
from asistente.servicios import Servicios
from asistente.store.models import Accion

log = logging.getLogger(__name__)
router = APIRouter()

MAX_MENSAJE = 300


def _acciones(svc: Servicios):
    if svc.acciones is None:
        raise ErrorApi(503, "acciones_no_disponibles")
    return svc.acciones


def _vista(a: Accion) -> dict:
    return {"id": str(a.id), "tool": a.tool, "estado": a.estado, "resumen": a.resumen,
            "lineas": list(a.lineas or []), "huella": a.huella, "expira": a.expira.isoformat()}


async def _propia(svc: Servicios, sesion: Sesion, accion_id: uuid.UUID) -> Accion:
    u = sesion.usuario
    # Ajena o inexistente: misma respuesta, para no revelar ids de otros.
    accion = await _acciones(svc).obtener(u.sistema_id, u.usuario_ref, accion_id)
    if accion is None:
        raise ErrorApi(404, "accion_no_encontrada")
    return accion


def _no_pendiente(a: Accion) -> JSONResponse:
    return JSONResponse({"error": "accion_no_pendiente", "estado": a.estado}, status_code=409)


async def _anotar(svc: Servicios, sesion: Sesion, a: Accion, texto: str) -> None:
    """El resultado entra al historial para que el modelo sepa qué pasó con su propuesta."""
    if a.conversacion_id is None:
        return
    try:
        await svc.repo.agregar_nota(sesion.usuario.sistema_id, sesion.usuario.usuario_ref,
                                    a.conversacion_id, texto)
    except Exception:
        log.exception("no se pudo anotar el resultado de la acción %s", a.id)


@router.get("/v1/confirmaciones/{accion_id}")
async def ver(
    accion_id: uuid.UUID, sesion: Sesion = Depends(sesion_actual), svc: Servicios = Depends(servicios)
):
    return _vista(await _propia(svc, sesion, accion_id))


@router.post("/v1/confirmaciones/{accion_id}/cancelar")
async def cancelar(
    accion_id: uuid.UUID, sesion: Sesion = Depends(sesion_actual), svc: Servicios = Depends(servicios)
):
    accion = await _propia(svc, sesion, accion_id)
    u = sesion.usuario
    if not await _acciones(svc).cancelar(u.sistema_id, u.usuario_ref, accion_id):
        return _no_pendiente(await _propia(svc, sesion, accion_id))
    await _anotar(svc, sesion, accion, f"Acción cancelada por el usuario: {accion.resumen}")
    return {"estado": "cancelada"}


@router.post("/v1/confirmaciones/{accion_id}/confirmar")
async def confirmar(
    accion_id: uuid.UUID, sesion: Sesion = Depends(sesion_escritura), svc: Servicios = Depends(servicios)
):
    u = sesion.usuario
    accion = await _propia(svc, sesion, accion_id)
    c = u.accion
    # El token debe ser para ESTA acción, tool y parámetros. Se comprueba antes de reclamar: un token
    # equivocado no gasta la confirmación.
    if c is None or c.cid != str(accion.id) or c.act != accion.tool or c.ph != accion.huella:
        raise ErrorApi(403, "confirmacion_invalida")
    if sesion.sistema.id != accion.sistema_id:
        raise ErrorApi(403, "confirmacion_invalida")

    reclamada = await _acciones(svc).reclamar(u.sistema_id, u.usuario_ref, accion_id, u.jti)
    if reclamada is None:
        return _no_pendiente(await _propia(svc, sesion, accion_id))

    request_id = uuid.uuid4().hex
    inicio = time.monotonic()
    r = await svc.conector.ejecutar(
        u, reclamada.tool, reclamada.parametros, request_id,
        escritura=True, idempotencia=str(reclamada.id),
    )
    ms = int((time.monotonic() - inicio) * 1000)
    try:
        ctx = Contexto(
            sistema_id=u.sistema_id, sistema_nombre=sesion.sistema.nombre, usuario_ref=u.usuario_ref,
            jti=u.jti, request_id=request_id, modelo="", prompt_system="", prompt_version="",
            limites=LimitesUso(0, 0, 0),
        )
        await svc.auditoria.registrar_tool(ctx, reclamada.conversacion_id, reclamada.tool,
                                           reclamada.parametros, r, ms)
    except Exception:
        log.exception("[%s] no se pudo auditar la acción %s", request_id, accion_id)
    await _acciones(svc).finalizar(accion_id, ok=r.ok, error=r.error, status_http=r.status_http)

    if r.ok:
        mensaje = r.datos.get("mensaje") if isinstance(r.datos, dict) else None
        mensaje = mensaje[:MAX_MENSAJE] if isinstance(mensaje, str) and mensaje else "Hecho."
        await _anotar(svc, sesion, reclamada, f"Acción realizada: {reclamada.resumen}")
        return {"estado": "ejecutada", "ok": True, "mensaje": mensaje, "ui": r.ui}
    await _anotar(svc, sesion, reclamada,
                  f"La acción no se pudo realizar ({r.error}): {reclamada.resumen}")
    return {"estado": "fallida", "ok": False, "error": r.error, "detalle": (r.detalle or "")[:MAX_MENSAJE]}
