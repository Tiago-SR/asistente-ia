"""TTS de ElevenLabs (`POST /v1/text-to-speech/{voice_id}`). La clave vive solo en el servidor.

El texto viaja al proveedor y no se guarda ni se registra aquí.
"""

import logging
from urllib.parse import quote

import httpx

from asistente.core.voz.base import VozError

log = logging.getLogger(__name__)

BASE_URL = "https://api.elevenlabs.io/v1"
FORMATO = "mp3_44100_128"


def _motivo(r: httpx.Response) -> str:
    """Estado y mensaje del error de ElevenLabs (`{"detail": {"status", "message"}}`), para el log. Sin el texto enviado."""
    try:
        d = r.json()["detail"]
        if isinstance(d, dict):
            return f" ({d.get('status')}: {str(d.get('message'))[:200]})"
        return f" ({str(d)[:200]})"
    except (ValueError, KeyError, TypeError):
        return ""


class TtsElevenLabs:
    tipo_mime = "audio/mpeg"
    proveedor = "elevenlabs"

    def __init__(
        self,
        api_key: str,
        voz_id: str,
        modelo: str,
        *,
        base_url: str = BASE_URL,
        cliente: httpx.AsyncClient | None = None,
        timeout_s: float = 30.0,
    ) -> None:
        self._api_key = api_key
        self._voz = quote(voz_id, safe="")
        self._modelo = modelo
        self.modelo = modelo
        self._base = base_url.rstrip("/")
        self._cliente = cliente or httpx.AsyncClient(follow_redirects=False)
        self._timeout = httpx.Timeout(timeout_s, connect=5.0)

    def _headers(self) -> dict:
        return {"xi-api-key": self._api_key}

    async def sintetizar(self, texto: str, *, idioma: str | None = None, voz_id: str | None = None) -> bytes:
        voz = quote(voz_id, safe="") if voz_id else self._voz
        try:
            r = await self._cliente.post(
                f"{self._base}/text-to-speech/{voz}",
                params={"output_format": FORMATO},
                json={"text": texto, "model_id": self._modelo},
                headers={**self._headers(), "accept": self.tipo_mime},
                timeout=self._timeout,
            )
        except httpx.HTTPError as e:
            raise VozError(f"TTS inaccesible: {type(e).__name__}") from e
        if r.status_code != 200:
            raise VozError(f"TTS respondió HTTP {r.status_code}{_motivo(r)}")
        if not r.content:
            raise VozError("TTS devolvió audio vacío")
        return r.content

    async def disponible(self) -> bool:
        """`/v1/estado` no puede comprobarlo: ElevenLabs no ofrece un chequeo gratuito que sirva con una
        clave limitada a texto a voz (listar o leer voces pide otro permiso). Si falla, el widget cae a
        la voz del navegador en esa misma frase."""
        return True
