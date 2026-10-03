from fastapi import APIRouter, Depends

from asistente.api.deps import Sesion, sesion_actual

router = APIRouter()


@router.get("/v1/estado")
async def estado(sesion: Sesion = Depends(sesion_actual)) -> dict:
    """El widget lo consulta para mostrarse u ocultarse. Un sistema deshabilitado ni
    siquiera valida token (401), y el widget lo trata igual que `habilitado: false`."""
    return {"habilitado": True, "nombre_sistema": sesion.sistema.nombre}
