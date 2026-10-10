from fastapi import APIRouter, Depends

from asistente.api.deps import Sesion, servicios, sesion_actual
from asistente.core import adjuntos
from asistente.servicios import LLMNoConfigurado, Servicios

router = APIRouter()


@router.get("/v1/estado")
async def estado(
    sesion: Sesion = Depends(sesion_actual), svc: Servicios = Depends(servicios)
) -> dict:
    """El widget lo consulta para mostrarse u ocultarse. Un sistema deshabilitado ni
    siquiera valida token (401), y el widget lo trata igual que `habilitado: false`.

    `voz` informa qué puede hacer el servicio, no el LLM: el dictado depende del adaptador
    STT configurado y de que responda; `respuesta` es la voz del servidor (TTS) y solo es true si el adaptador responde;
    `max_audio_s` es el tope de duración que el widget usa para cortar la grabación."""
    dictado = svc.stt is not None and await svc.stt.disponible()
    respuesta = svc.tts is not None and await svc.tts.disponible()
    voz = {"dictado": dictado, "respuesta": respuesta, "max_audio_s": svc.settings.voz_max_audio_s}
    if respuesta and svc.voces:
        # Voces del servidor que el usuario puede elegir (sin el voice_id del proveedor).
        voz["voces"] = svc.voces.publico()
        voz["voz_defecto"] = svc.voces.defecto
    resp = {
        "habilitado": True,
        "nombre_sistema": sesion.sistema.nombre,
        # Nombre por defecto del asistente (sistemas.yaml); el usuario puede cambiarlo en el widget.
        "nombre_asistente": sesion.sistema.nombre_asistente,
        # El widget muestra el panel «Lo que recuerdo» solo si el sistema tiene la memoria encendida.
        "memoria": sesion.sistema.memoria_habilitada and svc.memoria is not None,
        "voz": voz,
    }
    # Imágenes de referencia: solo si el modelo de este sistema las admite.
    try:
        llm, _ = svc.llm_para(sesion.sistema)
        admite = llm.capacidades.soporta_imagenes
    except LLMNoConfigurado:
        admite = False
    if admite:
        cfg = svc.settings
        resp["imagenes"] = {"max": cfg.max_imagenes, "max_kb": cfg.max_imagen_kb, "tipos": list(adjuntos.TIPOS)}
    return resp
