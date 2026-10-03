from fastapi import APIRouter, Depends

from asistente.api.deps import Sesion, servicios, sesion_actual
from asistente.servicios import Servicios

router = APIRouter()


@router.get("/v1/estado")
async def estado(
    sesion: Sesion = Depends(sesion_actual), svc: Servicios = Depends(servicios)
) -> dict:
    """El widget lo consulta para mostrarse u ocultarse. Un sistema deshabilitado ni
    siquiera valida token (401), y el widget lo trata igual que `habilitado: false`.

    `voz` informa qué puede hacer el servicio, no el LLM: el dictado depende del adaptador
    STT configurado y de que responda; `respuesta` (TTS) llega en un paso posterior."""
    dictado = svc.stt is not None and await svc.stt.disponible()
    return {
        "habilitado": True,
        "nombre_sistema": sesion.sistema.nombre,
        "voz": {"dictado": dictado, "respuesta": False},
    }
