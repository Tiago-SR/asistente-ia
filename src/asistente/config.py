"""Configuración del servicio por variables de entorno."""

from pydantic import Field, field_validator
from pydantic_settings import BaseSettings, SettingsConfigDict


def _env(nombre: str, default=...):
    return Field(default, validation_alias=nombre)


class Settings(BaseSettings):
    model_config = SettingsConfigDict(extra="ignore", populate_by_name=True)

    database_url: str = _env("ASISTENTE_DATABASE_URL")
    # El registro de sistemas vive siempre en Postgres (secretos cifrados con ASISTENTE_CLAVES_MAESTRAS); el YAML
    # solo se importa con `python -m asistente.sistemas.cli importar-yaml`. La variable ya no elige nada: se
    # acepta ausente o `bd` (deprecada) y cualquier otro valor aborta el arranque, para que un `yaml` olvidado
    # en el .env no deje el servicio sirviendo 0 sistemas en silencio.
    registro: str = _env("ASISTENTE_REGISTRO", "bd")

    @field_validator("registro")
    @classmethod
    def _registro_solo_bd(cls, v: str) -> str:
        if v != "bd":
            raise ValueError(
                f"ASISTENTE_REGISTRO={v!r} ya no existe: el registro se lee de la BD. Importa el YAML con "
                "`python -m asistente.sistemas.cli importar-yaml` y quita la variable (o ponla en `bd`)."
            )
        return v
    prompts_dir: str = _env("ASISTENTE_PROMPTS_DIR", "prompts")
    admin_token: str | None = _env("ASISTENTE_ADMIN_TOKEN", None)
    # Panel: la cookie de sesión es `__Host-admin` (solo HTTPS). En dev sobre http://localhost poner
    # ASISTENTE_ADMIN_COOKIE_SECURE=false (cookie `admin`). `ASISTENTE_ADMIN_ORIGENES` (coma) suma orígenes
    # válidos para el chequeo CSRF además del host propio (p. ej. el dev server de Vite); vacío en prod.
    admin_cookie_secure: bool = _env("ASISTENTE_ADMIN_COOKIE_SECURE", True)
    admin_origenes: str = _env("ASISTENTE_ADMIN_ORIGENES", "")
    # `Host` (coma, con puerto) con que se sirven /admin y /panel; además se rechazan las peticiones con cabeceras
    # de proxy (X-Forwarded-*). En prod lo fija docker-compose.prod.yml (túnel ssh); vacío = sin restricción.
    admin_hosts: str = _env("ASISTENTE_ADMIN_HOSTS", "")
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

    # Excel descargable (tool `generar_excel`, por sistema con `exportar_excel: true`): topes por archivo, por usuario
    # y día, y cuánto vive el archivo: vencido deja de ser descargable al instante, y sus bytes se borran al generarse el
    # siguiente archivo o en la purga de abajo.
    excel_max_filas: int = _env("ASISTENTE_EXCEL_MAX_FILAS", 5000)
    excel_max_columnas: int = _env("ASISTENTE_EXCEL_MAX_COLUMNAS", 50)
    excel_max_kb: int = _env("ASISTENTE_EXCEL_MAX_KB", 2048)
    excel_max_por_dia: int = _env("ASISTENTE_EXCEL_MAX_POR_DIA", 20)
    archivos_ttl_horas: int = _env("ASISTENTE_ARCHIVOS_TTL_HORAS", 24)

    # Purga de retención: cada cuántos segundos (0 = desactivada).
    purga_intervalo_s: float = _env("ASISTENTE_PURGA_INTERVALO_S", 86400.0)
    # Destinos internos a los que el servicio puede conectarse (nombres y/o redes CIDR, separados por coma):
    # `mock-a,sistema-php,host.docker.internal,10.0.5.0/24`. Por defecto solo direcciones públicas. La URL global
    # del LLM (LLM_BASE_URL) se permite sola. 169.254.0.0/16 (metadatos de nube), link-local y multicast nunca.
    hosts_internos_permitidos: str = _env("ASISTENTE_HOSTS_INTERNOS_PERMITIDOS", "")
    # Días que se guarda `admin_auditoria` (quién cambió qué en el panel). 0 = no se purga nunca.
    admin_auditoria_dias: int = _env("ASISTENTE_ADMIN_AUDITORIA_DIAS", 365)

    # Acciones con confirmación (Fase 5): propuestas por usuario y hora.
    acciones_max_por_hora: int = _env("ASISTENTE_ACCIONES_MAX_POR_HORA", 20)

    # Memoria por usuario (Fase 1): un recuerdo vence cuando pasan estos días desde la última vez que se usó.
    memoria_dias_sin_uso: int = _env("ASISTENTE_MEMORIA_DIAS_SIN_USO", 30)

    # Búsqueda web (tools `buscar_web` y `leer_pagina`, por sistema con `busqueda_web: true`). Proveedores en orden:
    # Tavily mientras tenga cupo, luego SearXNG propio. Sin ninguno configurado las tools no se ofrecen.
    web_tavily_api_key: str | None = _env("WEB_TAVILY_API_KEY", None)
    web_searxng_url: str | None = _env("WEB_SEARXNG_URL", None)
    # Lectura directa de páginas desde este servidor (respaldo de Tavily para `leer_pagina`, con defensas de SSRF).
    web_lector_directo: bool = _env("WEB_LECTOR_DIRECTO", True)
    web_pausa_cupo_s: float = _env("ASISTENTE_WEB_PAUSA_CUPO_S", 21600.0)
    web_max_por_min: int = _env("ASISTENTE_WEB_MAX_POR_MIN", 10)
    web_max_por_dia: int = _env("ASISTENTE_WEB_MAX_POR_DIA", 100)
    web_max_por_turno: int = _env("ASISTENTE_WEB_MAX_POR_TURNO", 4)
    web_max_pagina_chars: int = _env("ASISTENTE_WEB_MAX_PAGINA_CHARS", 12000)

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
