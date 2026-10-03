"""Configuración del servicio por variables de entorno (sección 7.6 del plan)."""

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
    log_level: str = _env("ASISTENTE_LOG_LEVEL", "INFO")

    llm_proveedor: str = _env("LLM_PROVEEDOR", "openai_compat")
    llm_base_url: str | None = _env("LLM_BASE_URL", None)
    llm_api_key: str | None = _env("LLM_API_KEY", None)
    modelo_default: str | None = _env("ASISTENTE_MODELO_DEFAULT", None)

    max_iter: int = _env("ASISTENTE_MAX_ITER", 8)
    max_output_tokens: int = _env("ASISTENTE_MAX_OUTPUT_TOKENS", 1500)
    timeout_turno_s: float = _env("ASISTENTE_TIMEOUT_TURNO_S", 120.0)
    max_turnos_historial: int = _env("ASISTENTE_MAX_TURNOS_HISTORIAL", 10)
    max_mensaje_chars: int = _env("ASISTENTE_MAX_MENSAJE_CHARS", 4000)
    heartbeat_s: float = _env("ASISTENTE_HEARTBEAT_S", 15.0)
