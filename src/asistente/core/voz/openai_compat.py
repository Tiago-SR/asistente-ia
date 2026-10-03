"""STT para cualquier endpoint `/v1/audio/transcriptions` (OpenAI, faster-whisper-server, etc.).

Sirve igual para un servidor local de Whisper que para un proveedor remoto: solo cambia `base_url`.
El audio no se guarda ni se registra; solo viaja en la petición.
"""

import logging

import httpx

from asistente.core.voz.base import AudioInvalido, VozError

log = logging.getLogger(__name__)

_EXTENSIONES = {
    "audio/webm": "webm",
    "audio/ogg": "ogg",
    "audio/mp4": "mp4",
    "audio/mpeg": "mp3",
    "audio/wav": "wav",
    "audio/x-wav": "wav",
}


class SttOpenAICompat:
    def __init__(
        self,
        base_url: str,
        modelo: str,
        api_key: str | None = None,
        cliente: httpx.AsyncClient | None = None,
        timeout_s: float = 60.0,
    ) -> None:
        self._base = base_url.rstrip("/")
        self._modelo = modelo
        self._api_key = api_key
        self._cliente = cliente or httpx.AsyncClient(follow_redirects=False)
        self._timeout = httpx.Timeout(timeout_s, connect=5.0)

    def _headers(self) -> dict:
        return {"Authorization": f"Bearer {self._api_key}"} if self._api_key else {}

    async def transcribir(self, audio: bytes, *, tipo_mime: str, idioma: str | None = None) -> str:
        base_mime = tipo_mime.split(";")[0].strip().lower()
        archivo = f"audio.{_EXTENSIONES.get(base_mime, 'bin')}"
        datos = {"model": self._modelo, "response_format": "json"}
        if idioma:
            datos["language"] = idioma
        try:
            r = await self._cliente.post(
                f"{self._base}/audio/transcriptions",
                data=datos,
                files={"file": (archivo, audio, base_mime)},
                headers=self._headers(),
                timeout=self._timeout,
            )
        except httpx.HTTPError as e:
            raise VozError(f"STT inaccesible: {type(e).__name__}") from e
        if r.status_code in (400, 415, 422):
            raise AudioInvalido(f"STT rechazó el audio (HTTP {r.status_code})")
        if r.status_code != 200:
            raise VozError(f"STT respondió HTTP {r.status_code}")
        try:
            texto = r.json()["text"]
        except (ValueError, KeyError, TypeError) as e:
            raise VozError("STT devolvió una respuesta inválida") from e
        if not isinstance(texto, str):
            raise VozError("STT devolvió una respuesta inválida")
        return texto.strip()

    async def disponible(self) -> bool:
        """Chequeo barato para `/v1/estado`: el servidor responde en `/models`."""
        try:
            r = await self._cliente.get(
                f"{self._base}/models", headers=self._headers(), timeout=httpx.Timeout(2.0)
            )
        except httpx.HTTPError:
            return False
        return r.status_code == 200
