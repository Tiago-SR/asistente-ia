"""Cableado de dependencias. La API solo ve esta estructura, así los tests inyectan fakes."""

from collections.abc import Callable
from dataclasses import dataclass

import httpx
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine

from asistente.config import Settings
from asistente.core.llm.openai_compat import OpenAICompat
from asistente.core.ports import LLM, Auditoria, Limites
from asistente.core.prompts import Prompts
from asistente.limits import LimitesPostgres
from asistente.sistemas.auth import Autenticador
from asistente.sistemas.conector_http import ConectorHttp
from asistente.sistemas.manifiesto import CacheManifiestos
from asistente.sistemas.registro import RegistroSistemas, Sistema
from asistente.store.auditoria import AuditoriaSql
from asistente.store.repo import Repo


class LLMNoConfigurado(Exception):
    pass


@dataclass
class Servicios:
    settings: Settings
    registro: RegistroSistemas
    autenticador: Autenticador
    manifiestos: CacheManifiestos
    conector: ConectorHttp
    repo: Repo
    limites: Limites
    auditoria: Auditoria
    prompts: Prompts
    # (sistema) -> (adaptador, modelo); lanza LLMNoConfigurado
    llm_para: Callable[[Sistema], tuple[LLM, str]]
    sesiones: async_sessionmaker[AsyncSession] | None = None
    cierre: Callable[[], object] | None = None


def _fabrica_llm(settings: Settings, registro: RegistroSistemas) -> Callable[[Sistema], tuple[LLM, str]]:
    cliente = httpx.AsyncClient(follow_redirects=False)
    cache: dict[tuple[str, str | None], LLM] = {}

    def llm_para(sistema: Sistema) -> tuple[LLM, str]:
        cfg = sistema.llm
        proveedor = cfg.proveedor if cfg else settings.llm_proveedor
        modelo = (cfg.modelo if cfg else None) or settings.modelo_default
        base_url = (sistema.secreto(cfg.base_url_env, registro.env) if cfg else None) or settings.llm_base_url
        api_key = (sistema.secreto(cfg.api_key_env, registro.env) if cfg else None) or settings.llm_api_key
        if proveedor != "openai_compat":
            raise LLMNoConfigurado(f"proveedor no soportado: {proveedor}")
        if not base_url or not modelo:
            raise LLMNoConfigurado("falta base_url o modelo del LLM")
        clave = (base_url, api_key)
        if clave not in cache:
            cache[clave] = OpenAICompat(base_url, api_key, cliente=cliente)
        return cache[clave], modelo

    return llm_para


def construir(settings: Settings) -> Servicios:
    motor = create_async_engine(settings.database_url, pool_pre_ping=True)
    sesiones = async_sessionmaker(motor, expire_on_commit=False)
    registro = RegistroSistemas(settings.sistemas_path)
    manifiestos = CacheManifiestos(registro)
    return Servicios(
        settings=settings,
        registro=registro,
        autenticador=Autenticador(registro),
        manifiestos=manifiestos,
        conector=ConectorHttp(registro, manifiestos),
        repo=Repo(sesiones),
        limites=LimitesPostgres(sesiones),
        auditoria=AuditoriaSql(sesiones),
        prompts=Prompts(settings.prompts_dir),
        llm_para=_fabrica_llm(settings, registro),
        sesiones=sesiones,
        cierre=motor.dispose,
    )
