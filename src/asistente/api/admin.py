"""Endpoints de operación, protegidos por ASISTENTE_ADMIN_TOKEN.

La restricción a red interna se aplica en el proxy; aquí solo se exige el token.
"""

import hmac

from fastapi import APIRouter, Depends, Request

from asistente.api.deps import servicios
from asistente.api.errores import ErrorApi
from asistente.servicios import Servicios
from asistente.sistemas.manifiesto import ManifiestoInvalido

router = APIRouter(prefix="/admin")


async def admin(request: Request, svc: Servicios = Depends(servicios)) -> Servicios:
    esperado = svc.settings.admin_token
    if not esperado:
        raise ErrorApi(503, "admin_deshabilitado")
    _, _, token = request.headers.get("authorization", "").partition(" ")
    if not hmac.compare_digest(token.encode(), esperado.encode()):
        raise ErrorApi(401, "no_autorizado", {"WWW-Authenticate": "Bearer"})
    return svc


@router.post("/recargar")
async def recargar(svc: Servicios = Depends(admin)) -> dict:
    svc.registro.recargar()
    svc.manifiestos.invalidar()
    return {"sistemas": len(svc.registro.todos()), "errores": svc.registro.errores}


@router.get("/sistemas")
async def sistemas(svc: Servicios = Depends(admin)) -> dict:
    estado = []
    for s in svc.registro.todos():
        try:
            m = await svc.manifiestos.obtener(s.id)
            manifiesto, error = True, None
            tools = len(m.tools_lectura())
        except ManifiestoInvalido as e:
            manifiesto, error, tools = False, str(e), 0
        estado.append({"id": s.id, "nombre": s.nombre, "habilitado": True,
                       "manifiesto_ok": manifiesto, "tools_lectura": tools, "ultimo_error": error})
    return {"sistemas": estado, "invalidos": svc.registro.errores}
