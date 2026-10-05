import uuid

from fastapi import APIRouter, Depends, Response

from asistente.api.confirmaciones import vista_accion
from asistente.api.deps import Sesion, servicios, sesion_actual
from asistente.api.errores import ErrorApi
from asistente.servicios import Servicios

router = APIRouter()


@router.get("/v1/conversaciones")
async def listar(sesion: Sesion = Depends(sesion_actual), svc: Servicios = Depends(servicios)):
    u = sesion.usuario
    convs = await svc.repo.listar(u.sistema_id, u.usuario_ref)
    return [
        {"id": str(c.id), "titulo": c.titulo, "creada": c.creada.isoformat(),
         "actualizada": c.actualizada.isoformat()}
        for c in convs
    ]


@router.get("/v1/conversaciones/{conv_id}")
async def mensajes(
    conv_id: uuid.UUID, sesion: Sesion = Depends(sesion_actual), svc: Servicios = Depends(servicios)
):
    u = sesion.usuario
    visibles = await svc.repo.visibles(u.sistema_id, u.usuario_ref, conv_id)
    if visibles is None:
        raise ErrorApi(404, "conversacion_no_encontrada")
    # La propuesta pendiente (si hay), para que el widget restaure la tarjeta tras recargar la página.
    pendiente = None
    if svc.acciones is not None:
        accion = await svc.acciones.pendiente_de(u.sistema_id, u.usuario_ref, conv_id)
        pendiente = vista_accion(accion) if accion else None
    return {"id": str(conv_id), "mensajes": visibles, "pendiente": pendiente}


@router.delete("/v1/conversaciones/{conv_id}", status_code=204)
async def borrar(
    conv_id: uuid.UUID, sesion: Sesion = Depends(sesion_actual), svc: Servicios = Depends(servicios)
):
    u = sesion.usuario
    if not await svc.repo.borrar(u.sistema_id, u.usuario_ref, conv_id):
        raise ErrorApi(404, "conversacion_no_encontrada")
    return Response(status_code=204)
