"""Registro de sistemas: carga y valida `config/sistemas.yaml` (sección 5 del plan).

Un sistema inválido queda deshabilitado (con el error registrado en `errores`) y el
resto sigue funcionando. Los secretos nunca están en el archivo: se referencian por
nombre de variable de entorno y se resuelven con `Sistema.secreto`.
"""

import logging
import os
from collections.abc import Mapping
from pathlib import Path
from typing import Literal, Self

import yaml
from pydantic import BaseModel, ConfigDict, Field, ValidationError, model_validator

log = logging.getLogger(__name__)

ID_RE = r"^[a-z0-9][a-z0-9_-]{0,63}$"


class _Modelo(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)


class AuthConfig(_Modelo):
    algoritmo: Literal["RS256", "EdDSA", "HS256"]
    clave_publica_env: str | None = None
    jwks_url: str | None = None
    secreto_env: str | None = None
    audiencia: str = "asistente"
    tolerancia_reloj_s: int = Field(default=30, ge=0, le=300)

    @model_validator(mode="after")
    def _fuente_de_clave(self) -> Self:
        fuentes = [self.clave_publica_env, self.jwks_url, self.secreto_env]
        if sum(f is not None for f in fuentes) != 1:
            raise ValueError(
                "indicar exactamente una fuente de clave: "
                "clave_publica_env, jwks_url o secreto_env"
            )
        if self.algoritmo == "HS256" and self.secreto_env is None:
            raise ValueError("HS256 requiere secreto_env")
        if self.algoritmo != "HS256" and self.secreto_env is not None:
            raise ValueError("secreto_env solo es válido con HS256")
        return self


class ConectorConfig(_Modelo):
    tipo: Literal["http"] = "http"
    ruta_manifiesto: str = "/asistente/tools"
    ruta_ejecucion: str = "/asistente/tools/{nombre}"
    token_manifiesto_env: str
    timeout_s: float = Field(default=20, gt=0, le=120)
    manifiesto_ttl_s: int = Field(default=3600, ge=0)
    max_respuesta_bytes: int = Field(default=50_000, gt=0)

    @model_validator(mode="after")
    def _rutas(self) -> Self:
        if not self.ruta_manifiesto.startswith("/"):
            raise ValueError("ruta_manifiesto debe empezar con /")
        if not self.ruta_ejecucion.startswith("/") or "{nombre}" not in self.ruta_ejecucion:
            raise ValueError("ruta_ejecucion debe empezar con / y contener {nombre}")
        return self


class LLMConfig(_Modelo):
    proveedor: str
    modelo: str
    base_url_env: str | None = None
    api_key_env: str | None = None


class LimitesConfig(_Modelo):
    mensajes_por_usuario_min: int = Field(default=10, gt=0)
    mensajes_por_usuario_dia: int = Field(default=200, gt=0)
    tokens_por_mes: int = Field(default=5_000_000, gt=0)


class Sistema(_Modelo):
    id: str = Field(pattern=ID_RE)
    nombre: str = Field(min_length=1, max_length=200)
    habilitado: bool = True
    base_url: str
    origenes_permitidos: tuple[str, ...] = ()
    auth: AuthConfig
    conector: ConectorConfig
    prompt_dominio: str | None = None
    llm: LLMConfig | None = None
    limites: LimitesConfig = LimitesConfig()
    retencion_dias: int = Field(default=30, gt=0)

    @model_validator(mode="after")
    def _base_url(self) -> Self:
        if not self.base_url.startswith(("http://", "https://")):
            raise ValueError("base_url debe ser http(s)")
        return self

    def secreto(self, nombre_env: str | None, env: Mapping[str, str] | None = None) -> str | None:
        """Valor de una variable de entorno referenciada por el registro (o None)."""
        if not nombre_env:
            return None
        return (env if env is not None else os.environ).get(nombre_env) or None


class RegistroSistemas:
    """Sistemas habilitados y válidos, indexados por id (= claim `iss`)."""

    def __init__(self, ruta: str | Path, env: Mapping[str, str] | None = None) -> None:
        self._ruta = Path(ruta)
        self._env = env
        self._sistemas: dict[str, Sistema] = {}
        self.errores: dict[str, str] = {}
        self.recargar()

    @property
    def env(self) -> Mapping[str, str]:
        return self._env if self._env is not None else os.environ

    def recargar(self) -> None:
        sistemas, errores = self._leer()
        self._sistemas, self.errores = sistemas, errores

    def obtener(self, sistema_id: str) -> Sistema | None:
        return self._sistemas.get(sistema_id)

    def todos(self) -> list[Sistema]:
        return list(self._sistemas.values())

    def _leer(self) -> tuple[dict[str, Sistema], dict[str, str]]:
        sistemas: dict[str, Sistema] = {}
        errores: dict[str, str] = {}
        try:
            crudo = yaml.safe_load(self._ruta.read_text(encoding="utf-8")) or {}
            entradas = crudo.get("sistemas") or []
            if not isinstance(entradas, list):
                raise TypeError("`sistemas` debe ser una lista")
        except (OSError, ValueError, TypeError, yaml.YAMLError) as e:
            log.error("registro de sistemas ilegible (%s): %s", self._ruta, e)
            return {}, {"<archivo>": str(e)}

        for i, entrada in enumerate(entradas):
            clave = entrada.get("id") if isinstance(entrada, dict) else None
            clave = str(clave) if clave else f"<entrada {i}>"
            try:
                sistema = Sistema.model_validate(entrada)
                self._validar_entorno(sistema)
            except (ValidationError, ValueError) as e:
                errores[clave] = str(e)
                log.error("sistema %s deshabilitado por configuración inválida: %s", clave, e)
                continue
            if sistema.id in sistemas or sistema.id in errores:
                errores[clave] = "id duplicado"
                sistemas.pop(sistema.id, None)
                log.error("id de sistema duplicado: %s; se deshabilitan ambos", sistema.id)
                continue
            if sistema.habilitado:
                sistemas[sistema.id] = sistema
        return sistemas, errores

    def _validar_entorno(self, s: Sistema) -> None:
        """Las variables de entorno obligatorias deben existir si el sistema está habilitado."""
        if not s.habilitado:
            return
        faltan = []
        if s.auth.clave_publica_env and not s.secreto(s.auth.clave_publica_env, self.env):
            faltan.append(s.auth.clave_publica_env)
        if s.auth.secreto_env and not s.secreto(s.auth.secreto_env, self.env):
            faltan.append(s.auth.secreto_env)
        if not s.secreto(s.conector.token_manifiesto_env, self.env):
            faltan.append(s.conector.token_manifiesto_env)
        if faltan:
            raise ValueError(f"faltan variables de entorno: {', '.join(faltan)}")
