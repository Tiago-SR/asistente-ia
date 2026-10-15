"""Registro de sistemas en Postgres: lectura coherente, sondeo entre réplicas y operaciones de escritura.

Auth, conector y CORS nunca consultan la BD: leen la copia en memoria de `RegistroSistemas`, que esta fuente
reemplaza de golpe. Cada cambio incrementa `registro_version` en la misma transacción; cada réplica la sondea
cada pocos segundos y recarga si cambió. Si la BD cae en marcha se conserva la última copia buena.
"""

import asyncio
import logging
from collections.abc import Mapping
from pathlib import Path

from sqlalchemy import delete, func, select
from sqlalchemy.dialects.postgresql import insert as pg_insert
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from asistente.sistemas.cifrado import Cifrado, Cifrador, ErrorCifrado, huella
from asistente.sistemas.registro import (
    CAMPOS_SECRETOS,
    EntradaRegistro,
    RegistroSistemas,
    Sistema,
    entradas_desde_yaml,
    validar_sistema,
)
from asistente.store.models import RegistroVersion, SistemaRegistro, SistemaSecreto, ToolEstado

log = logging.getLogger(__name__)

# Columnas propias: no se repiten dentro de `config` (JSONB), así hay una sola fuente para cada dato.
_FUERA_DE_CONFIG = {"id", "nombre", "habilitado", "acciones_habilitadas", "tool_estado",
                   "destructivas_aprobadas"}
INTERVALO_SONDEO_S = 5.0


def config_json(sistema: Sistema) -> dict:
    """Lo que va al JSONB `config` de un sistema: todo menos lo que tiene columna o tabla propia."""
    return sistema.model_dump(mode="json", exclude=_FUERA_DE_CONFIG, exclude_none=True)


class ErrorRegistro(Exception):
    """Operación de registro rechazada (datos inválidos, BD no vacía, conflicto de versión...)."""


async def incrementar_version(s: AsyncSession) -> None:
    """Debe llamarse en la misma transacción que cualquier cambio al registro."""
    await s.execute(
        pg_insert(RegistroVersion)
        .values(id=1, version=1)
        .on_conflict_do_update(index_elements=["id"], set_={"version": RegistroVersion.version + 1})
    )


async def version_actual(sesiones: async_sessionmaker[AsyncSession]) -> int:
    async with sesiones() as s:
        return (await s.execute(select(RegistroVersion.version).where(RegistroVersion.id == 1))).scalar() or 0


async def leer_registro(
    sesiones: async_sessionmaker[AsyncSession], cifrador: Cifrador | None
) -> tuple[int, list[EntradaRegistro]]:
    """Versión y sistemas, leídos en UNA transacción REPEATABLE READ: si no, una réplica podría quedarse con
    una mezcla de dos versiones y no volver a recargar. Un secreto que no descifra deja a ese sistema en
    `errores`; no tumba al resto."""
    async with sesiones() as s:
        await s.connection(execution_options={"isolation_level": "REPEATABLE READ"})
        version = (await s.execute(select(RegistroVersion.version).where(RegistroVersion.id == 1))).scalar() or 0
        filas = (await s.execute(select(SistemaRegistro).order_by(SistemaRegistro.id))).scalars().all()
        secretos = (await s.execute(select(SistemaSecreto))).scalars().all()
        tools = (await s.execute(select(ToolEstado))).scalars().all()

    por_secreto: dict[str, list[SistemaSecreto]] = {}
    for x in secretos:
        por_secreto.setdefault(x.sistema_id, []).append(x)
    por_tool: dict[str, dict[str, bool]] = {}
    aprobadas: dict[str, dict[str, str]] = {}
    for t in tools:
        por_tool.setdefault(t.sistema_id, {})[t.tool] = t.habilitada
        if t.aprobada_huella:
            aprobadas.setdefault(t.sistema_id, {})[t.tool] = t.aprobada_huella

    entradas = []
    for f in filas:
        config = {**f.config, "id": f.id, "nombre": f.nombre, "habilitado": f.habilitado,
                  "tool_estado": por_tool.get(f.id, {}),
                  "destructivas_aprobadas": aprobadas.get(f.id, {})}
        claves: dict[str, str] = {}
        error = None
        for x in por_secreto.get(f.id, []):
            try:
                if cifrador is None:
                    raise ErrorCifrado("no hay claves maestras (ASISTENTE_CLAVES_MAESTRAS)")
                claves[x.campo] = cifrador.descifrar(f.id, x.campo, Cifrado(x.kid, x.nonce, x.cifrado))
            except ErrorCifrado as e:
                error = f"secreto {x.campo!r}: {e}"
                break
        entradas.append(EntradaRegistro(f.id, config, claves, error))
    return version, entradas


class FuenteBD:
    """Alimenta a un `RegistroSistemas` desde la BD y lo mantiene al día."""

    def __init__(
        self, registro: RegistroSistemas, sesiones: async_sessionmaker[AsyncSession],
        cifrador: Cifrador | None, intervalo_s: float = INTERVALO_SONDEO_S,
    ) -> None:
        self._registro = registro
        self._sesiones = sesiones
        self._cifrador = cifrador
        self._intervalo_s = intervalo_s
        self.version: int | None = None
        self.listo = False  # readiness: nunca se sirve un registro vacío «por defecto»
        registro.fuente_bd = self

    async def cargar(self) -> None:
        version, entradas = await leer_registro(self._sesiones, self._cifrador)
        self._registro.aplicar(entradas)
        self.version, self.listo = version, True

    async def sondear(self) -> None:
        if self.version is None or await version_actual(self._sesiones) != self.version:
            await self.cargar()

    async def bucle(self) -> None:
        while True:
            try:
                await self.sondear()
            except asyncio.CancelledError:
                raise
            except Exception as e:  # noqa: BLE001 BD caída: se conserva la última copia buena
                log.error("no se pudo sondear el registro de sistemas: %s", type(e).__name__)
            await asyncio.sleep(self._intervalo_s)


async def importar_yaml(
    sesiones: async_sessionmaker[AsyncSession], cifrador: Cifrador | None, ruta: str | Path,
    env: Mapping[str, str] | None = None, *, reemplazar: bool = False, por: str = "cli",
) -> int:
    """Carga el YAML en la BD resolviendo los `*_env` en este momento. Todo o nada: si una entrada es
    inválida no se escribe nada. Con la BD ya poblada exige `reemplazar`. `acciones_habilitadas` pasa a filas
    de `tool_estado` (mismo comportamiento)."""
    problemas, listos = [], []
    for e in entradas_desde_yaml(ruta, env):
        try:
            if e.error is not None:
                raise ValueError(e.error)
            listos.append((validar_sistema(e.config or {}, e.secretos), e.secretos))
        except ValueError as ex:  # incluye ValidationError
            problemas.append(f"{e.clave}: {ex}")
    ids = [s.id for s, _ in listos]
    if len(set(ids)) != len(ids):
        problemas.append("ids duplicados en el YAML")
    if problemas:
        raise ErrorRegistro("YAML inválido, no se importó nada:\n" + "\n".join(problemas))
    if any(sec for _, sec in listos) and cifrador is None:
        raise ErrorRegistro("hay secretos que cifrar y falta ASISTENTE_CLAVES_MAESTRAS")

    async with sesiones() as s, s.begin():
        existentes = (await s.execute(select(func.count()).select_from(SistemaRegistro))).scalar_one()
        if existentes and not reemplazar:
            raise ErrorRegistro(f"la BD ya tiene {existentes} sistema(s); usar --reemplazar para sobrescribir")
        if existentes:
            await s.execute(delete(SistemaRegistro))  # secretos y tool_estado caen en cascada
        for sistema, secretos in listos:
            config = config_json(sistema)
            s.add(SistemaRegistro(id=sistema.id, nombre=sistema.nombre, habilitado=sistema.habilitado,
                                  config=config, actualizado_por=por))
            estados = {n: True for n in sistema.acciones_habilitadas} | sistema.tool_estado
            await s.flush()
            for tool, habilitada in estados.items():
                s.add(ToolEstado(sistema_id=sistema.id, tool=tool, habilitada=habilitada, actualizado_por=por))
            for campo, valor in secretos.items():
                assert cifrador is not None and campo in CAMPOS_SECRETOS
                c = cifrador.cifrar(sistema.id, campo, valor)
                s.add(SistemaSecreto(sistema_id=sistema.id, campo=campo, kid=c.kid, nonce=c.nonce,
                                     cifrado=c.cifrado, huella=huella(valor), actualizado_por=por))
        await incrementar_version(s)
    return len(listos)


def _env_de(sistema_id: str, campo: str) -> str:
    return f"{sistema_id.upper().replace('-', '_')}_{campo.upper()}"


async def exportar_yaml(sesiones: async_sessionmaker[AsyncSession]) -> dict:
    """El registro como YAML (`{"sistemas": [...]}`), SIN secretos: cada secreto presente sale como una
    referencia `*_env` con un nombre derivado, para poder reimportarlo exportando esas variables."""
    async with sesiones() as s:
        await s.connection(execution_options={"isolation_level": "REPEATABLE READ"})
        filas = (await s.execute(select(SistemaRegistro).order_by(SistemaRegistro.id))).scalars().all()
        campos = (await s.execute(select(SistemaSecreto.sistema_id, SistemaSecreto.campo))).all()
        tools = (await s.execute(select(ToolEstado))).scalars().all()
    presentes: dict[str, set[str]] = {}
    for sid, campo in campos:
        presentes.setdefault(sid, set()).add(campo)
    estado: dict[str, dict[str, bool]] = {}
    for t in tools:
        estado.setdefault(t.sistema_id, {})[t.tool] = t.habilitada

    salida = []
    for f in filas:
        d = {"id": f.id, "nombre": f.nombre, **f.config}
        if not f.habilitado:
            d["habilitado"] = False
        if estado.get(f.id):
            d["tool_estado"] = dict(sorted(estado[f.id].items()))
        tiene = presentes.get(f.id, set())
        if "auth_hs256" in tiene:
            d["auth"] = {**d["auth"], "secreto_env": _env_de(f.id, "auth_hs256")}
        if "token_manifiesto" in tiene:
            d["conector"] = {**d["conector"], "token_manifiesto_env": _env_de(f.id, "token_manifiesto")}
        if "llm_api_key" in tiene:
            d["llm"] = {**(d.get("llm") or {}), "api_key_env": _env_de(f.id, "llm_api_key")}
        salida.append(d)
    return {"sistemas": salida}


async def rotar_clave(sesiones: async_sessionmaker[AsyncSession], cifrador: Cifrador) -> int:
    """Re-cifra con la clave activa los secretos cifrados con otra. Devuelve cuántos rotó. Si alguno no
    descifra no se escribe nada: la clave vieja todavía hace falta."""
    async with sesiones() as s, s.begin():
        filas = (await s.execute(select(SistemaSecreto))).scalars().all()
        rotados = 0
        for x in filas:
            c = Cifrado(x.kid, x.nonce, x.cifrado)
            if not cifrador.necesita_rotar(c):
                continue
            n = cifrador.rotar(x.sistema_id, x.campo, c)  # puede lanzar: aborta toda la transacción
            x.kid, x.nonce, x.cifrado = n.kid, n.nonce, n.cifrado
            rotados += 1
        if rotados:
            await incrementar_version(s)
    return rotados
