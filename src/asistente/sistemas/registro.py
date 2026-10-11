"""Registro de sistemas (sección 6 del contrato).

El modelo `Sistema` es el canónico: lo que se guarda en la BD (JSONB) y lo que valida el panel. Los secretos
no forman parte de él: viajan aparte (`EntradaRegistro.secretos`), con los campos de `CAMPOS_SECRETOS`, y se
leen con `RegistroSistemas.secreto`.

Hay dos fuentes y nunca conviven en un mismo registro:
- YAML (`config/sistemas.yaml`): un adaptador traduce las referencias `*_env` y resuelve el entorno AL CARGAR.
- BD (`registro_bd.py`): lee las filas cifradas y nunca consulta `os.environ` para secretos de sistema.
Ambas pasan por `validar_sistema`: una sola regla de validación.

Un sistema inválido queda deshabilitado (con el error registrado en `errores`) y el resto sigue funcionando.
"""

import copy
import logging
import os
from collections.abc import Callable, Iterable, Mapping
from dataclasses import dataclass, field
from pathlib import Path
from typing import Literal, Self

import yaml
from pydantic import (
    BaseModel,
    ConfigDict,
    Field,
    SecretStr,
    ValidationError,
    field_validator,
    model_validator,
)

from asistente.core import zona

log = logging.getLogger(__name__)

ID_RE = r"^[a-z0-9][a-z0-9_-]{0,63}$"


class _Modelo(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)


class AuthConfig(_Modelo):
    """Cómo se verifican los tokens del sistema. La clave HS256 es un secreto (campo `auth_hs256`); la clave
    pública y la URL JWKS no lo son."""

    algoritmo: Literal["RS256", "EdDSA", "HS256"]
    clave_publica: str | None = None  # PEM
    jwks_url: str | None = None
    audiencia: str = "asistente"
    tolerancia_reloj_s: int = Field(default=30, ge=0, le=300)

    @model_validator(mode="after")
    def _fuente_de_clave(self) -> Self:
        if self.algoritmo == "HS256":
            if self.clave_publica is not None or self.jwks_url is not None:
                raise ValueError("HS256 usa un secreto compartido: sin clave_publica ni jwks_url")
        elif (self.clave_publica is None) == (self.jwks_url is None):
            raise ValueError("indicar exactamente una fuente de clave: clave_publica o jwks_url")
        return self


class ConectorConfig(_Modelo):
    tipo: Literal["http"] = "http"
    ruta_manifiesto: str = "/asistente/tools"
    ruta_ejecucion: str = "/asistente/tools/{nombre}"
    ruta_propuesta: str = "/asistente/tools/{nombre}/propuesta"
    timeout_s: float = Field(default=20, gt=0, le=120)
    manifiesto_ttl_s: int = Field(default=3600, ge=0)
    max_respuesta_bytes: int = Field(default=50_000, gt=0)

    @model_validator(mode="after")
    def _rutas(self) -> Self:
        if not self.ruta_manifiesto.startswith("/"):
            raise ValueError("ruta_manifiesto debe empezar con /")
        if not self.ruta_ejecucion.startswith("/") or "{nombre}" not in self.ruta_ejecucion:
            raise ValueError("ruta_ejecucion debe empezar con / y contener {nombre}")
        if not self.ruta_propuesta.startswith("/") or "{nombre}" not in self.ruta_propuesta:
            raise ValueError("ruta_propuesta debe empezar con / y contener {nombre}")
        return self


class LLMConfig(_Modelo):
    # Todo es opcional: lo que se omite se hereda de la configuración global (`LLM_*`, `ASISTENTE_MODELO_DEFAULT`),
    # así que `llm: {imagenes: true}` basta para encender solo las imágenes de ese sistema.
    proveedor: str | None = None
    modelo: str | None = None
    base_url: str | None = None  # la clave va aparte, como secreto `llm_api_key`
    # ¿el modelo admite imágenes? None = lo que diga `LLM_IMAGENES`
    imagenes: bool | None = None


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
    # Idioma de los usuarios cuyo token no trae el claim `locale` (p. ej. `es-UY`).
    locale_defecto: str | None = Field(default=None, pattern=r"^[a-z]{2}(-[A-Z]{2})?$")
    # Fase 5: escrituras que el modelo puede proponer (con confirmación del usuario). Vacío = solo lectura.
    acciones_habilitadas: tuple[str, ...] = ()
    # Excepciones por tool (nombre → habilitada). Solo se guarda lo que se aparta del valor por defecto: la lectura
    # está habilitada salvo que aquí diga `false`; la escritura, deshabilitada salvo `true` (o `acciones_habilitadas`).
    # Ver `sistemas/permisos.py`; es el hueco donde la tabla `tool_estado` entrega sus filas.
    tool_estado: dict[str, bool] = Field(default_factory=dict)
    # Zona (IANA, p. ej. `America/Montevideo`) de los usuarios cuyo navegador no la informa: fija qué día es «hoy».
    zona_horaria: str | None = None
    # Tool local `consultas_recientes` («lo mismo que ayer»): lee las consultas que ya se auditan, sin guardar nada nuevo.
    consultas_recientes: bool = True
    # Memoria por usuario (Fase 1): tools locales `recordar` y `olvidar`, sección «lo que pidió recordar» en el prompt
    # y panel en el widget. Apagada por defecto; sin esto no se expone ni se inyecta nada.
    memoria_habilitada: bool = False
    # Búsqueda web: tools locales `buscar_web` y `leer_pagina` y la capa `prompts/web.md`. Apagada por defecto: la
    # consulta sale a un proveedor externo (ver `core/web/herramientas.py`). Requiere `WEB_*` configurado.
    busqueda_web: bool = False
    # Cómo se llama el asistente en el widget (título, avisos, ajustes). Es el valor por defecto: cada usuario puede
    # ponerle otro desde el panel de ajustes. Sin él el widget dice «Asistente».
    nombre_asistente: str | None = Field(default=None, min_length=1, max_length=40)

    @field_validator("nombre_asistente")
    @classmethod
    def _nombre_asistente(cls, valor: str | None) -> str | None:
        if valor is not None and (valor != valor.strip() or not valor.isprintable()):
            raise ValueError("nombre_asistente: sin espacios en los extremos ni caracteres de control")
        return valor

    @field_validator("zona_horaria")
    @classmethod
    def _zona(cls, valor: str | None) -> str | None:
        if valor is not None and zona.valida(valor) is None:
            raise ValueError(f"zona horaria desconocida: {valor!r}")
        return valor

    @model_validator(mode="after")
    def _base_url(self) -> Self:
        if not self.base_url.startswith(("http://", "https://")):
            raise ValueError("base_url debe ser http(s)")
        return self


# Secretos canónicos de un sistema. Se escriben, nunca se devuelven en claro.
CAMPOS_SECRETOS = ("auth_hs256", "token_manifiesto", "llm_api_key")


@dataclass(frozen=True)
class EntradaRegistro:
    """Un sistema tal como lo entrega una fuente, antes de validar. `error` = la fuente ya no pudo leerlo
    (p. ej. un secreto que no descifra): queda en `errores` sin intentar validarlo."""

    clave: str  # id (o una etiqueta si ni siquiera lo tiene), para los mensajes de error
    config: Mapping | None = None
    secretos: Mapping[str, str] = field(default_factory=dict, repr=False)
    error: str | None = None


def validar_sistema(config: Mapping, secretos: Mapping[str, str]) -> Sistema:
    """La única validación: el modelo, más los secretos que exige un sistema habilitado."""
    sistema = Sistema.model_validate(config)
    if sistema.habilitado:
        faltan = []
        if sistema.auth.algoritmo == "HS256" and not secretos.get("auth_hs256"):
            faltan.append("auth_hs256")
        if not secretos.get("token_manifiesto"):
            faltan.append("token_manifiesto")
        if faltan:
            raise ValueError(f"faltan secretos: {', '.join(faltan)}")
    return sistema


def desde_yaml(entrada: Mapping, env: Mapping[str, str]) -> tuple[dict, dict[str, str]]:
    """Adaptador del YAML: traduce `*_env` a (config canónica, secretos). Las variables que faltan se
    reportan por nombre (nunca su valor)."""
    cfg = copy.deepcopy(dict(entrada))
    secretos: dict[str, str] = {}
    faltan: list[str] = []

    def valor(nombre: object) -> str | None:
        return env.get(nombre) or None if isinstance(nombre, str) else None

    auth = cfg.get("auth")
    if isinstance(auth, dict):
        if "secreto_env" in auth:
            if auth.get("algoritmo") != "HS256":
                raise ValueError("secreto_env solo es válido con HS256")
            nombre = auth.pop("secreto_env")
            if v := valor(nombre):
                secretos["auth_hs256"] = v
            else:
                faltan.append(str(nombre))
        if "clave_publica_env" in auth:
            nombre = auth.pop("clave_publica_env")
            if v := valor(nombre):
                auth["clave_publica"] = v
            else:
                faltan.append(str(nombre))
    conector = cfg.get("conector")
    if isinstance(conector, dict) and "token_manifiesto_env" in conector:
        nombre = conector.pop("token_manifiesto_env")
        if v := valor(nombre):
            secretos["token_manifiesto"] = v
        else:
            faltan.append(str(nombre))
    llm = cfg.get("llm")
    if isinstance(llm, dict):
        # Opcionales: sin variable se hereda de la configuración global.
        if "base_url_env" in llm and (v := valor(llm.pop("base_url_env"))):
            llm["base_url"] = v
        else:
            llm.pop("base_url_env", None)
        if "api_key_env" in llm and (v := valor(llm.pop("api_key_env"))):
            secretos["llm_api_key"] = v
        else:
            llm.pop("api_key_env", None)
    if faltan and cfg.get("habilitado", True):
        raise ValueError(f"faltan variables de entorno: {', '.join(faltan)}")
    return cfg, secretos


class RegistroSistemas:
    """Sistemas habilitados y válidos, indexados por id (= claim `iss`), y sus secretos."""

    def __init__(self, ruta: str | Path | None = None, env: Mapping[str, str] | None = None) -> None:
        """Con `ruta`, fuente YAML. Sin ella el registro empieza vacío y lo llena `aplicar` (fuente BD)."""
        self._ruta = Path(ruta) if ruta is not None else None
        self._env = env
        self._sistemas: dict[str, Sistema] = {}
        self._secretos: dict[str, dict[str, SecretStr]] = {}
        self._suscriptores: list[Callable[[set[str]], None]] = []
        self.errores: dict[str, str] = {}
        self.fuente_bd = None  # `registro_bd.FuenteBD`, si el registro se alimenta de la BD
        if self._ruta is not None:
            self.recargar()

    def recargar(self) -> None:
        """Relee la fuente YAML (la de BD se recarga con `recargar_async`)."""
        if self._ruta is not None:
            self.aplicar(entradas_desde_yaml(self._ruta, self._env))

    async def recargar_async(self) -> None:
        if self.fuente_bd is not None:
            await self.fuente_bd.cargar()
        else:
            self.recargar()

    def suscribir(self, callback: Callable[[set[str]], None]) -> None:
        """`callback(ids)` se llama tras una recarga con los sistemas que cambiaron (o se quitaron):
        las cachés derivadas (manifiestos, JWKS) los descartan."""
        self._suscriptores.append(callback)

    def obtener(self, sistema_id: str) -> Sistema | None:
        return self._sistemas.get(sistema_id)

    def todos(self) -> list[Sistema]:
        return list(self._sistemas.values())

    def secreto(self, sistema_id: str, campo: str) -> str | None:
        """Valor en claro de un secreto del sistema. Solo se llama en el punto de uso."""
        valor = self._secretos.get(sistema_id, {}).get(campo)
        return valor.get_secret_value() if valor is not None else None

    def aplicar(self, entradas: Iterable[EntradaRegistro]) -> set[str]:
        """Valida las entradas y reemplaza el registro de golpe. Devuelve los ids que cambiaron."""
        sistemas: dict[str, Sistema] = {}
        secretos: dict[str, dict[str, SecretStr]] = {}
        errores: dict[str, str] = {}
        for e in entradas:
            if e.error is not None:
                errores[e.clave] = e.error
                log.error("sistema %s deshabilitado: %s", e.clave, e.error)
                continue
            try:
                sistema = validar_sistema(e.config or {}, e.secretos)
            except (ValidationError, ValueError) as ex:
                errores[e.clave] = str(ex)
                log.error("sistema %s deshabilitado por configuración inválida: %s", e.clave, ex)
                continue
            if sistema.id in sistemas or sistema.id in errores:
                errores[e.clave] = "id duplicado"
                sistemas.pop(sistema.id, None)
                secretos.pop(sistema.id, None)
                log.error("id de sistema duplicado: %s; se deshabilitan ambos", sistema.id)
                continue
            if sistema.habilitado:
                sistemas[sistema.id] = sistema
                secretos[sistema.id] = {k: SecretStr(v) for k, v in e.secretos.items() if v}

        def plano(d: dict[str, dict[str, SecretStr]]) -> dict[str, dict[str, str]]:
            return {i: {k: v.get_secret_value() for k, v in m.items()} for i, m in d.items()}

        antes, despues = (self._sistemas, plano(self._secretos)), (sistemas, plano(secretos))
        cambiados = {
            i for i in set(antes[0]) | set(despues[0])
            if antes[0].get(i) != despues[0].get(i) or antes[1].get(i) != despues[1].get(i)
        }
        self._sistemas, self._secretos, self.errores = sistemas, secretos, errores
        if cambiados:
            for cb in self._suscriptores:
                cb(cambiados)
        return cambiados


def entradas_desde_yaml(ruta: str | Path, env: Mapping[str, str] | None = None) -> list[EntradaRegistro]:
    """Lee el YAML y lo traduce con `desde_yaml`. Un archivo ilegible es una entrada con error."""
    ruta = Path(ruta)
    env = env if env is not None else os.environ
    try:
        crudo = yaml.safe_load(ruta.read_text(encoding="utf-8")) or {}
        entradas = crudo.get("sistemas") or []
        if not isinstance(entradas, list):
            raise TypeError("`sistemas` debe ser una lista")
    except (OSError, ValueError, TypeError, yaml.YAMLError) as e:
        log.error("registro de sistemas ilegible (%s): %s", ruta, e)
        return [EntradaRegistro("<archivo>", error=str(e))]

    salida = []
    for i, entrada in enumerate(entradas):
        clave = entrada.get("id") if isinstance(entrada, dict) else None
        clave = str(clave) if clave else f"<entrada {i}>"
        if not isinstance(entrada, dict):
            salida.append(EntradaRegistro(clave, error="la entrada debe ser un mapa"))
            continue
        try:
            config, secretos = desde_yaml(entrada, env)
        except ValueError as e:
            salida.append(EntradaRegistro(clave, error=str(e)))
            continue
        salida.append(EntradaRegistro(clave, config, secretos))
    return salida
