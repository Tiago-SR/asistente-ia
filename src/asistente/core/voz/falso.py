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
