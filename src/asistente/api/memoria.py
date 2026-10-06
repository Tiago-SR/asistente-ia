"""Lo que el asistente recuerda del usuario (Fase 1): verlo y borrarlo. Todo filtra por
`(sistema_id, usuario_ref)` de la sesión: un recuerdo ajeno es indistinguible de uno inexistente. Borrar no pide
confirmación: es un clic del propio usuario sobre sus datos. Con la memoria apagada para el sistema, 404."""

import uuid
from datetime import timedelta

from fastapi import APIRouter, Depends, Response

from asistente.api.deps import Sesion, servicios, sesion_actual
from asistente.api.errores import ErrorApi
from asistente.core.memoria import describir
from asistente.core.ports import Recuerdo
from asistente.servicios import Servicios
from asistente.store.memoria import MemoriaSql

router = APIRouter()


def _almacen(sesion: Sesion, svc: Servicios) -> MemoriaSql:
    if not sesion.sistema.memoria_habilitada or svc.memoria is None:
        raise ErrorApi(404, "memoria_no_habilitada")
    return svc.memoria


def _vista(r: Recuerdo, dias: int) -> dict:
    return {
        "id": r.id, "tipo": r.tipo, "clave": r.clave, "descripcion": describir(r),
        "creada": r.creada.isoformat(), "ultimo_uso": r.ultimo_uso.isoformat(),
        "vence": (r.ultimo_uso + timedelta(days=dias)).isoformat(),
    }


@router.get("/v1/memoria")
async def listar(sesion: Sesion = Depends(sesion_actual), svc: Servicios = Depends(servicios)):
    almacen = _almacen(sesion, svc)
    u = sesion.usuario
    # Mirar la lista no renueva nada: solo cuenta como uso lo que el asistente aplica en una conversación.
    recuerdos = await almacen.listar(u.sistema_id, u.usuario_ref)
    return [_vista(r, svc.settings.memoria_dias_sin_uso) for r in recuerdos]


@router.delete("/v1/memoria/{recuerdo_id}", status_code=204)
async def borrar(
    recuerdo_id: uuid.UUID, sesion: Sesion = Depends(sesion_actual), svc: Servicios = Depends(servicios)
):
    almacen = _almacen(sesion, svc)
    u = sesion.usuario
    if not await almacen.borrar(u.sistema_id, u.usuario_ref, recuerdo_id):
        raise ErrorApi(404, "recuerdo_no_encontrado")
    return Response(status_code=204)


@router.delete("/v1/memoria")
async def borrar_todo(sesion: Sesion = Depends(sesion_actual), svc: Servicios = Depends(servicios)):
    almacen = _almacen(sesion, svc)
    u = sesion.usuario
    return {"borrados": await almacen.borrar_todo(u.sistema_id, u.usuario_ref)}
