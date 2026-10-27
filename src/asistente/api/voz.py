"""Voz (sección 7.4 del contrato).

`POST /v1/voz/transcribir`: dictado. Cuerpo = audio crudo; devuelve el texto para que el widget lo ponga en
el campo (sin envío automático). El audio no se guarda.
`POST /v1/voz/sintetizar`: respuesta hablada con la voz del servidor (texto -> audio)."""

import logging
import time

from fastapi import APIRouter, Depends, Request, Response
from fastapi.responses import StreamingResponse
from pydantic import BaseModel, ValidationError

from asistente.api.deps import Sesion, servicios, sesion_actual
from asistente.api.errores import ErrorApi
from asistente.core.ports import EventoMetrica, LimiteExcedido
from asistente.core.voz.base import AudioInvalido, VozError
from asistente.precios import clave_tts
from asistente.servicios import Servicios
from asistente.store.uso import sumar_uso_voz

log = logging.getLogger(__name__)
router = APIRouter()


def _medir(svc: Servicios, u, tipo: str, resultado: str, *, motivo: str = "", modelo: str = "", unidades: int = 0,
           inicio: float | None = None) -> None:
    """Una métrica por dictado o síntesis. Nunca lanza ni espera; sin texto ni audio, solo tamaños y tiempos."""
    if svc.metricas is None:
        return
    try:
        ms = int((time.monotonic() - inicio) * 1000) if inicio is not None else None
        svc.metricas.registrar(EventoMetrica(
            sistema_id=u.sistema_id, usuario_ref=u.usuario_ref, tipo=tipo, resultado=resultado, motivo=motivo,
            modelo=modelo, canal="voz", unidades=unidades, duracion_ms=ms,
        ))
    except Exception:
        log.warning("no se pudo registrar la métrica de voz", exc_info=True)

TIPOS_PERMITIDOS = {"audio/webm", "audio/ogg", "audio/mp4", "audio/mpeg", "audio/wav", "audio/x-wav"}


async def _leer_acotado(request: Request, max_bytes: int) -> bytes:
    """Lee el cuerpo cortando al pasarse del tope, sin cargarlo entero en memoria."""
    partes, total = [], 0
    async for trozo in request.stream():
        total += len(trozo)
        if total > max_bytes:
            raise ErrorApi(413, "audio_demasiado_grande")
        partes.append(trozo)
    return b"".join(partes)


@router.post("/v1/voz/transcribir")
async def transcribir(
    request: Request,
    idioma: str | None = None,
    sesion: Sesion = Depends(sesion_actual),
    svc: Servicios = Depends(servicios),
) -> dict:
    cfg, u = svc.settings, sesion.usuario
    if svc.stt is None:
        raise ErrorApi(503, "voz_no_disponible")

    tipo = request.headers.get("content-type", "").split(";")[0].strip().lower()
    if tipo not in TIPOS_PERMITIDOS:
        raise ErrorApi(415, "audio_tipo_no_permitido")

    max_bytes = cfg.voz_max_audio_kb * 1024
    declarado = request.headers.get("content-length")
    if declarado and declarado.isdigit() and int(declarado) > max_bytes:
        raise ErrorApi(413, "audio_demasiado_grande")

    duracion = request.headers.get("x-audio-duracion-s")
    if duracion is not None:
        try:
            segundos = float(duracion)
        except ValueError:
            raise ErrorApi(422, "audio_invalido") from None
        if not 0 <= segundos < float("inf"):
            raise ErrorApi(422, "audio_invalido")
        if segundos > cfg.voz_max_audio_s:
            raise ErrorApi(413, "audio_demasiado_largo")
    else:
        segundos = None

    try:
        await svc.limites.reservar_voz(u.sistema_id, u.usuario_ref, cfg.voz_max_por_min, cfg.voz_max_por_dia)
    except LimiteExcedido as e:
        _medir(svc, u, "stt", "limite", motivo=e.cual)
        raise ErrorApi(429, "limite_excedido") from e

    audio = await _leer_acotado(request, max_bytes)
    if not audio:
        raise ErrorApi(422, "audio_invalido")

    inicio = time.monotonic()
    try:
        texto = await svc.stt.transcribir(audio, tipo_mime=tipo, idioma=idioma or u.locale)
    except AudioInvalido as e:
        _medir(svc, u, "stt", "error", motivo="audio_invalido", unidades=len(audio), inicio=inicio)
        raise ErrorApi(422, "audio_invalido") from e
    except VozError as e:
        log.warning("STT falló para %s: %s", u.sistema_id, e)
        _medir(svc, u, "stt", "error", motivo="voz_error", unidades=len(audio), inicio=inicio)
        raise ErrorApi(502, "voz_error") from e
    _medir(svc, u, "stt", "ok", unidades=len(audio), inicio=inicio)

    # Solo metadatos: ni el audio ni el texto transcrito.
    log.info("dictado sistema=%s usuario=%s bytes=%d duracion_s=%s",
             u.sistema_id, u.usuario_ref, len(audio), segundos)
    return {"texto": texto}


class _Sintesis(BaseModel):
    texto: str
    idioma: str | None = None
    voz: str | None = None   # id del catálogo (`voz.voces` de /v1/estado); si falta o no existe, la predeterminada
    stream: bool = False     # true: el audio llega a medida que se genera (el primer trozo en ~0,35 s)


@router.post("/v1/voz/sintetizar")
async def sintetizar(
    request: Request,
    sesion: Sesion = Depends(sesion_actual),
    svc: Servicios = Depends(servicios),
) -> Response:
    """Respuesta hablada con la voz del servidor: `{ "texto", "idioma"?, "voz"?, "stream"? }` -> `audio/mpeg` de una
    pieza corta (el widget pide frase por frase). Con `stream: true` el audio se envía a medida que el proveedor lo
    genera; si falla antes del primer trozo se responde el mismo error JSON. El texto no se guarda ni se registra."""
    cfg, u = svc.settings, sesion.usuario
    if svc.tts is None:
        raise ErrorApi(503, "voz_no_disponible")

    try:
        cuerpo = _Sintesis.model_validate_json(await _leer_acotado(request, cfg.voz_max_tts_chars * 8 + 1024))
    except (ValidationError, ValueError):
        raise ErrorApi(422, "texto_invalido") from None
    texto = cuerpo.texto.strip()
    if not texto:
        raise ErrorApi(422, "texto_invalido")
    if len(texto) > cfg.voz_max_tts_chars:
        raise ErrorApi(413, "texto_demasiado_largo")

    try:
        await svc.limites.reservar_voz(u.sistema_id, u.usuario_ref, cfg.voz_tts_max_por_min, cfg.voz_tts_max_por_dia, clave="tts")
    except LimiteExcedido as e:
        _medir(svc, u, "tts", "limite", motivo=e.cual)
        raise ErrorApi(429, "limite_excedido") from e

    voz = svc.voces.resolver(cuerpo.voz)
    voz_id = voz.voz_id if voz else None
    idioma = cuerpo.idioma or u.locale
    cabeceras = {"Cache-Control": "no-store", "X-Accel-Buffering": "no"}

    inicio = time.monotonic()
    clave = clave_tts(svc.tts.proveedor, svc.tts.modelo)  # es también la clave de tarifa en precios.yaml

    async def contar() -> None:
        _medir(svc, u, "tts", "ok", modelo=clave, unidades=len(texto), inicio=inicio)
        if svc.sesiones is None:
            return
        try:   # el costo es contabilidad: si falla no se pierde el audio que el usuario ya pagó
            await sumar_uso_voz(svc.sesiones, u.sistema_id, svc.tts.proveedor, svc.tts.modelo, len(texto))
        except Exception:
            log.warning("no se pudo registrar el uso de voz de %s", u.sistema_id, exc_info=True)

    transmitir = getattr(svc.tts, "sintetizar_stream", None)
    if cuerpo.stream and transmitir:
        flujo = transmitir(texto, idioma=idioma, voz_id=voz_id)
        try:   # el primer trozo decide: si el proveedor falla antes, se responde el error de siempre
            primero = await anext(flujo)
        except (VozError, StopAsyncIteration) as e:
            await flujo.aclose()
            log.warning("TTS falló para %s: %s", u.sistema_id, e or "audio vacío")
            _medir(svc, u, "tts", "error", motivo="voz_error", modelo=clave, inicio=inicio)
            raise ErrorApi(502, "voz_error") from e
        await contar()
        log.info("síntesis (stream) sistema=%s usuario=%s caracteres=%d", u.sistema_id, u.usuario_ref, len(texto))

        async def trozos():
            try:
                yield primero
                async for t in flujo:
                    yield t
            except VozError as e:   # ya se envió parte del audio: solo se corta (el widget lo trata como fin del audio)
                log.warning("TTS se cortó a mitad para %s: %s", u.sistema_id, e)
            finally:
                await flujo.aclose()

        return StreamingResponse(trozos(), media_type=svc.tts.tipo_mime, headers=cabeceras)

    try:
        audio = await svc.tts.sintetizar(texto, idioma=idioma, voz_id=voz_id)
    except VozError as e:
        log.warning("TTS falló para %s: %s", u.sistema_id, e)
        _medir(svc, u, "tts", "error", motivo="voz_error", modelo=clave, inicio=inicio)
        raise ErrorApi(502, "voz_error") from e

    await contar()
    # Solo metadatos: ni el texto ni el audio.
    log.info("síntesis sistema=%s usuario=%s caracteres=%d bytes=%d", u.sistema_id, u.usuario_ref, len(texto), len(audio))
    return Response(audio, media_type=svc.tts.tipo_mime, headers=cabeceras)
