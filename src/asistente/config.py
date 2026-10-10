"""Configuración del servicio por variables de entorno."""

from pydantic import Field
from pydantic_settings import BaseSettings, SettingsConfigDict


def _env(nombre: str, default=...):
    return Field(default, validation_alias=nombre)


class Settings(BaseSettings):
    model_config = SettingsConfigDict(extra="ignore", populate_by_name=True)

    database_url: str = _env("ASISTENTE_DATABASE_URL")
    sistemas_path: str = _env("ASISTENTE_SISTEMAS_PATH", "/config/sistemas.yaml")
    prompts_dir: str = _env("ASISTENTE_PROMPTS_DIR", "prompts")
    admin_token: str | None = _env("ASISTENTE_ADMIN_TOKEN", None)
    precios_path: str = _env("ASISTENTE_PRECIOS_PATH", "/config/precios.yaml")
    log_level: str = _env("ASISTENTE_LOG_LEVEL", "INFO")

    llm_proveedor: str = _env("LLM_PROVEEDOR", "openai_compat")
    llm_base_url: str | None = _env("LLM_BASE_URL", None)
    llm_api_key: str | None = _env("LLM_API_KEY", None)
    modelo_default: str | None = _env("ASISTENTE_MODELO_DEFAULT", None)

    max_iter: int = _env("ASISTENTE_MAX_ITER", 8)
    max_output_tokens: int = _env("ASISTENTE_MAX_OUTPUT_TOKENS", 4096)
    timeout_turno_s: float = _env("ASISTENTE_TIMEOUT_TURNO_S", 120.0)
    max_turnos_historial: int = _env("ASISTENTE_MAX_TURNOS_HISTORIAL", 10)
    max_mensaje_chars: int = _env("ASISTENTE_MAX_MENSAJE_CHARS", 4000)
    # Imágenes de referencia: solo si el modelo las admite (`LLM_IMAGENES=true`, o `imagenes: true` en el `llm` del
    # sistema). Viajan en el turno y no se guardan. 700 KB × 3 cabe en el `client_max_body_size 4m` del proxy.
    llm_imagenes: bool = _env("LLM_IMAGENES", False)
    max_imagenes: int = _env("ASISTENTE_MAX_IMAGENES", 3)
    max_imagen_kb: int = _env("ASISTENTE_MAX_IMAGEN_KB", 700)
    heartbeat_s: float = _env("ASISTENTE_HEARTBEAT_S", 15.0)

    # Purga de retención: cada cuántos segundos (0 = desactivada).
    purga_intervalo_s: float = _env("ASISTENTE_PURGA_INTERVALO_S", 86400.0)

    # Acciones con confirmación (Fase 5): propuestas por usuario y hora.
    acciones_max_por_hora: int = _env("ASISTENTE_ACCIONES_MAX_POR_HORA", 20)

    # Memoria por usuario (Fase 1): un recuerdo vence cuando pasan estos días desde la última vez que se usó.
    memoria_dias_sin_uso: int = _env("ASISTENTE_MEMORIA_DIAS_SIN_USO", 30)

    # Voz (Fase 4). Sin STT_PROVEEDOR el dictado queda deshabilitado.
    stt_proveedor: str | None = _env("STT_PROVEEDOR", None)
    stt_base_url: str | None = _env("STT_BASE_URL", None)
    stt_api_key: str | None = _env("STT_API_KEY", None)
    stt_modelo: str | None = _env("STT_MODELO", None)
    # Respuesta hablada (TTS). Sin TTS_PROVEEDOR el widget usa solo la voz del navegador.
    tts_proveedor: str | None = _env("TTS_PROVEEDOR", None)
    tts_api_key: str | None = _env("TTS_API_KEY", None)
    tts_voz_id: str | None = _env("TTS_VOZ_ID", None)
    voces_path: str = _env("ASISTENTE_VOCES_PATH", "/config/voces.yaml")
    tts_modelo: str | None = _env("TTS_MODELO", None)
    voz_max_tts_chars: int = _env("ASISTENTE_VOZ_MAX_TTS_CHARS", 1000)
    voz_tts_max_por_min: int = _env("ASISTENTE_VOZ_TTS_MAX_POR_MIN", 60)
    voz_max_audio_kb: int = _env("ASISTENTE_VOZ_MAX_AUDIO_KB", 2048)
    voz_max_audio_s: int = _env("ASISTENTE_VOZ_MAX_AUDIO_S", 60)
    voz_max_por_min: int = _env("ASISTENTE_VOZ_MAX_POR_MIN", 10)
