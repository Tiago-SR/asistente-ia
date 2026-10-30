"""Configuración declarativa de los proveedores de canal (sin E/S): el registro de sistemas la importa."""

from typing import Annotated, Literal
from urllib.parse import urlsplit

from pydantic import BaseModel, ConfigDict, Field, field_validator


class CanalMetaConfig(BaseModel):
    """WhatsApp Cloud API (Meta). Los secretos van aparte (`SECRETOS_CANAL["meta"]`). Una App de Meta por sistema:
    el webhook es por App y el número se filtra por `phone_number_id`."""
    model_config = ConfigDict(extra="forbid", frozen=True)

    proveedor: Literal["meta"]
    phone_number_id: str = Field(pattern=r"^\d{5,32}$")
    graph_version: str = Field(default="v23.0", pattern=r"^v\d{1,3}\.\d{1,3}$")
    # Escrituras que el modelo puede proponer por este canal (aparte de `acciones_habilitadas`). Vacío = solo lectura.
    acciones: tuple[str, ...] = ()
    # Lecturas del sistema que NO se ofrecen por este canal (por defecto todas las habilitadas se ofrecen).
    lecturas_bloqueadas: tuple[str, ...] = ()


class CanalOpenWAConfig(BaseModel):
    """OpenWA (github.com/rmyndharis/OpenWA, MIT, autoalojado): automatiza WhatsApp Web, NO es la API oficial
    (riesgo de baneo del número). Sin botones: las escrituras de `acciones` se confirman escribiendo un código
    (`CONFIRMAR <código>`). El alta de la sesión (QR) y del webhook en OpenWA es manual (ver README). El host de `base_url` interno debe figurar en ASISTENTE_HOSTS_INTERNOS_PERMITIDOS."""
    model_config = ConfigDict(extra="forbid", frozen=True)

    proveedor: Literal["openwa"]
    base_url: str
    session_id: str = Field(pattern=r"^[A-Za-z0-9_-]{1,64}$")
    acciones: tuple[str, ...] = ()
    # Lecturas del sistema que NO se ofrecen por este canal (por defecto todas las habilitadas se ofrecen).
    lecturas_bloqueadas: tuple[str, ...] = ()

    @field_validator("base_url")
    @classmethod
    def _base_url(cls, v: str) -> str:
        u = urlsplit(v)
        if u.scheme not in ("http", "https") or not u.hostname or u.username or u.password or u.query or u.fragment:
            raise ValueError("base_url debe ser http(s) sin usuario, contraseña, query ni fragmento")
        return v


ConfigCanal = Annotated[CanalMetaConfig | CanalOpenWAConfig, Field(discriminator="proveedor")]

# Secretos de cada proveedor: solo aplican al sistema que lo elige.
SECRETOS_CANAL: dict[str, tuple[str, ...]] = {
    "meta": ("wa_token", "wa_app_secret", "wa_verify_token"),
    "openwa": ("owa_api_key", "owa_webhook_secret"),
}
