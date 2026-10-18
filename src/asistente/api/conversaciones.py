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
    # Las propuestas pendientes, para que el widget restaure las tarjetas tras recargar la página.
    # `pendiente` (la más reciente) se conserva por compatibilidad con widgets anteriores.
    pendientes = []
    if svc.acciones is not None:
        acciones = await svc.acciones.pendientes_de(u.sistema_id, u.usuario_ref, conv_id)
        pendientes = [vista_accion(a) for a in acciones]
    # Las tarjetas de descarga guardadas en los mensajes: `vigente` dice si el archivo sigue disponible.
    pedidos = {a["id"] for m in visibles for a in m.get("archivos", [])}
    vigentes = await svc.archivos.vigentes(u.sistema_id, u.usuario_ref, [uuid.UUID(i) for i in pedidos]) \
        if svc.archivos else set()
    for m in visibles:
        for a in m.get("archivos", []):
            a["vigente"] = a["id"] in vigentes
    return {"id": str(conv_id), "mensajes": visibles, "pendientes": pendientes,
            "pendiente": pendientes[-1] if pendientes else None}


@router.delete("/v1/conversaciones/{conv_id}", status_code=204)
async def borrar(
    conv_id: uuid.UUID, sesion: Sesion = Depends(sesion_actual), svc: Servicios = Depends(servicios)
):
    u = sesion.usuario
    if not await svc.repo.borrar(u.sistema_id, u.usuario_ref, conv_id):
        raise ErrorApi(404, "conversacion_no_encontrada")
    return Response(status_code=204)
