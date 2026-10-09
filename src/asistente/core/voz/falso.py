"""STT de guion para tests."""

from dataclasses import dataclass

from asistente.core.voz.base import VozError


@dataclass
class AudioRecibido:
    audio: bytes
    tipo_mime: str
    idioma: str | None


class SttFalso:
    def __init__(self, texto: str = "hola", *, disponible: bool = True, falla: bool = False) -> None:
        self.texto = texto
        self.esta_disponible = disponible
        self.falla = falla
        self.llamadas: list[AudioRecibido] = []

    async def transcribir(self, audio: bytes, *, tipo_mime: str, idioma: str | None = None) -> str:
        self.llamadas.append(AudioRecibido(audio, tipo_mime, idioma))
        if self.falla:
            raise VozError("falla simulada")
        return self.texto

    async def disponible(self) -> bool:
        return self.esta_disponible


class TtsFalso:
    tipo_mime = "audio/mpeg"
    proveedor = "falso"
    modelo = "falso"

    def __init__(self, audio: bytes = b"AUDIO", *, disponible: bool = True, falla: bool = False) -> None:
        self.audio = audio
        self.esta_disponible = disponible
        self.falla = falla
        self.llamadas: list[tuple[str, str | None]] = []
        self.voces: list[str | None] = []   # voz_id pedido en cada llamada

    async def sintetizar(self, texto: str, *, idioma: str | None = None, voz_id: str | None = None) -> bytes:
        self.llamadas.append((texto, idioma))
        self.voces.append(voz_id)
        if self.falla:
            raise VozError("falla simulada")
        return self.audio

    async def sintetizar_stream(self, texto: str, *, idioma: str | None = None, voz_id: str | None = None):
        """El mismo audio, en tres trozos."""
        audio = await self.sintetizar(texto, idioma=idioma, voz_id=voz_id)
        paso = max(1, len(audio) // 3)
        for i in range(0, len(audio), paso):
            yield audio[i:i + paso]

    async def disponible(self) -> bool:
        return self.esta_disponible
