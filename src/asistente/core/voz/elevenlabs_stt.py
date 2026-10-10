"""STT de ElevenLabs Scribe (`POST /v1/speech-to-text`). La clave vive solo en el servidor.

No es compatible con OpenAI: la clave va en `xi-api-key`, el modelo en `model_id` y el idioma en `language_code`.
El audio no se guarda ni se registra; solo viaja en la petición.
"""

import logging

import httpx

from asistente.core.voz.base import AudioInvalido, VozError
from asistente.core.voz.elevenlabs import BASE_URL, _motivo
from asistente.core.voz.openai_compat import _EXTENSIONES, _codigo_idioma

log = logging.getLogger(__name__)


class SttElevenLabs:
    def __init__(
        self,
        api_key: str,
        modelo: str,
        *,
        base_url: str = BASE_URL,
        cliente: httpx.AsyncClient | None = None,
        timeout_s: float = 60.0,
    ) -> None:
        self._api_key = api_key
        self._modelo = modelo
        self._base = base_url.rstrip("/")
        self._cliente = cliente or httpx.AsyncClient(follow_redirects=False)
        self._timeout = httpx.Timeout(timeout_s, connect=5.0)

    async def transcribir(self, audio: bytes, *, tipo_mime: str, idioma: str | None = None) -> str:
        base_mime = tipo_mime.split(";")[0].strip().lower()
        archivo = f"audio.{_EXTENSIONES.get(base_mime, 'bin')}"
        datos = {"model_id": self._modelo}
        codigo = _codigo_idioma(idioma)
        if codigo:
            datos["language_code"] = codigo
        try:
            r = await self._cliente.post(
                f"{self._base}/speech-to-text",
                data=datos,
                files={"file": (archivo, audio, base_mime)},
                headers={"xi-api-key": self._api_key},
                timeout=self._timeout,
            )
        except httpx.HTTPError as e:
            raise VozError(f"STT inaccesible: {type(e).__name__}") from e
        if r.status_code in (400, 415, 422):
            log.warning("STT rechazó el audio: HTTP %s%s", r.status_code, _motivo(r))
            raise AudioInvalido(f"STT rechazó el audio (HTTP {r.status_code})")
        if r.status_code != 200:
            raise VozError(f"STT respondió HTTP {r.status_code}{_motivo(r)}")
        try:
            texto = r.json()["text"]
        except (ValueError, KeyError, TypeError) as e:
            raise VozError("STT devolvió una respuesta inválida") from e
        if not isinstance(texto, str):
            raise VozError("STT devolvió una respuesta inválida")
        return texto.strip()

    async def disponible(self) -> bool:
        """ElevenLabs no ofrece un chequeo gratuito que sirva con una clave limitada a voz a texto
        (listar modelos pide otro permiso): si falla, el dictado devuelve el error al transcribir."""
        return True
