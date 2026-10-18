"""GET /v1/descargas/{id}: baja un archivo generado. El widget lo pide con `fetch` y Bearer (un `<a href>` no lo manda)."""

import uuid
from urllib.parse import quote

from fastapi import APIRouter, Depends, Response

from asistente.api.deps import Sesion, servicios, sesion_actual
from asistente.api.errores import ErrorApi
from asistente.servicios import Servicios

router = APIRouter()


@router.get("/v1/descargas/{archivo_id}")
async def descargar(
    archivo_id: uuid.UUID, sesion: Sesion = Depends(sesion_actual), svc: Servicios = Depends(servicios)
) -> Response:
    u = sesion.usuario
    # Ajeno, inexistente o vencido: la misma respuesta.
    a = await svc.archivos.obtener(u.sistema_id, u.usuario_ref, archivo_id) if svc.archivos else None
    if a is None:
        raise ErrorApi(404, "archivo_no_disponible")
    return Response(a.datos, media_type=a.tipo_mime, headers={
        "Content-Disposition": f"attachment; filename*=UTF-8''{quote(a.nombre)}",  # el nombre se sanea al generarlo
        "X-Content-Type-Options": "nosniff",
        "Cache-Control": "no-store",
    })
