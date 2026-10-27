"""Escrituras del panel sobre el registro de sistemas (modo BD).

Cada operación es UNA transacción: bloquea la fila del sistema (`FOR UPDATE`, siempre antes que
`registro_version`, para no entrelazar bloqueos), valida con el mismo `validar_sistema` que usa la carga,
escribe, incrementa `registro_version` y deja la auditoría. Quien llama recarga el registro local tras el commit;
las demás réplicas lo ven con el sondeo.

Reglas que protegen el acceso a terceros:
- cambiar `base_url` borra `token_manifiesto` (el conector lo reenvía a esa URL); cambiar `llm.base_url` borra
  `llm_api_key`. Un secreto nuevo en el mismo cambio los reemplaza; sin él, y con el sistema habilitado, se
  rechaza (`base_url_requiere_token`) en vez de apagarlo en silencio.
- los secretos se escriben, nunca se devuelven: solo `configurado`, huella y fecha.
- la auditoría guarda la config sin secretos y, de los secretos, solo qué campos cambiaron.
"""

import re
from collections.abc import Mapping
from datetime import UTC, datetime, timedelta

from pydantic import ValidationError
from sqlalchemy import delete, func, select
from sqlalchemy.dialects.postgresql import insert as pg_insert
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from asistente.sistemas.cifrado import Cifrador, huella
from asistente.sistemas.registro import (
    CAMPOS_SECRETOS,
    SECRETOS_BASE,
    Sistema,
    secretos_canal,
    validar_sistema,
)
from asistente.sistemas.registro_bd import config_json, incrementar_version
from asistente.store.models import (
    Accion,
    AdminAuditoria,
    SistemaRegistro,
    SistemaSecreto,
    ToolEstado,
)

# No se editan con el PUT de configuración.
RESERVADOS = {"id", "tool_estado", "acciones_habilitadas", "destructivas_aprobadas"}
TOOL_RE = re.compile(r"^[A-Za-z0-9_.-]{1,128}$")
SECRETO_MAX = 4096
HS256_MIN = 32  # bytes


class ErrorEscritura(Exception):
    """Operación rechazada. `estado` y `codigo` van tal cual a la respuesta HTTP; `datos` se suma al cuerpo."""

    def __init__(self, estado: int, codigo: str, datos: dict | None = None) -> None:
        super().__init__(codigo)
        self.estado, self.codigo, self.datos = estado, codigo, datos or {}


def _errores(e: ValidationError) -> dict:
    # Sin el valor de entrada: la config no lleva secretos, pero el panel no necesita el eco.
    return {"detalle": [{"campo": ".".join(str(x) for x in d["loc"]), "mensaje": d["msg"]}
                        for d in e.errors(include_input=False, include_url=False, include_context=False)]}


def _validar(config: Mapping) -> Sistema:
    try:
        return Sistema.model_validate(config)
    except ValidationError as e:
        raise ErrorEscritura(422, "config_invalida", _errores(e)) from None


def _auditar(s: AsyncSession, actor: str, accion: str, objetivo: str, *,
             antes: dict | None = None, despues: dict | None = None, ip: str | None = None) -> None:
    s.add(AdminAuditoria(actor=actor, accion=accion, objetivo=objetivo, antes=antes, despues=despues, ip=ip))


async def _bloquear(s: AsyncSession, sistema_id: str) -> SistemaRegistro:
    fila = (await s.execute(
        select(SistemaRegistro).where(SistemaRegistro.id == sistema_id).with_for_update()
    )).scalar_one_or_none()
    if fila is None:
        raise ErrorEscritura(404, "sistema_inexistente")
    return fila


def _exigir_version(fila: SistemaRegistro, version: int) -> None:
    if fila.version != version:
        raise ErrorEscritura(409, "version_obsoleta", {"version": fila.version})


async def _secretos(s: AsyncSession, sistema_id: str) -> dict[str, SistemaSecreto]:
    # populate_existing: los upserts van por Core y la identity map no se entera; sin esto se devolvería la fila vieja.
    filas = (await s.execute(select(SistemaSecreto).where(SistemaSecreto.sistema_id == sistema_id)
                             .execution_options(populate_existing=True))).scalars()
    return {f.campo: f for f in filas}


async def _tools(s: AsyncSession, sistema_id: str) -> dict[str, bool]:
    filas = (await s.execute(select(ToolEstado).where(ToolEstado.sistema_id == sistema_id)
                             .execution_options(populate_existing=True))).scalars()
    return {f.tool: f.habilitada for f in filas}


async def aprobaciones(sesiones: async_sessionmaker[AsyncSession], sistema_id: str) -> dict[str, str]:
    """Huella aprobada por tool destructiva, leída de la BD (no del registro en memoria, que puede ir 5 s atrás)."""
    async with sesiones() as s:
        filas = (await s.execute(select(ToolEstado.tool, ToolEstado.aprobada_huella).where(
            ToolEstado.sistema_id == sistema_id, ToolEstado.aprobada_huella.is_not(None)))).all()
    return dict(filas)


async def destructivas_hora(sesiones: async_sessionmaker[AsyncSession], sistema_id: str) -> dict[str, int]:
    """Propuestas destructivas de la última hora (cualquier estado, igual que lo que cuenta el tope):
    el total del sistema y lo que lleva el usuario más activo, que es el que choca con el límite."""
    desde = datetime.now(UTC) - timedelta(hours=1)
    async with sesiones() as s:
        filas = (await s.execute(
            select(func.count()).where(Accion.sistema_id == sistema_id, Accion.destructiva.is_(True),
                                       Accion.creada > desde).group_by(Accion.usuario_ref))).scalars().all()
    return {"total": sum(filas), "maximo_usuario": max(filas, default=0), "usuarios": len(filas)}


def _config_visible(f: SistemaRegistro) -> dict:
    """La configuración editable: lo mismo que acepta el PUT (sin `id`, `tool_estado` ni secretos)."""
    return {**f.config, "nombre": f.nombre, "habilitado": f.habilitado}


def _vista(f: SistemaRegistro, secretos: Mapping[str, SistemaSecreto], tools: Mapping[str, bool]) -> dict:
    return {
        "id": f.id,
        "version": f.version,
        "config": _config_visible(f),
        "secretos": {c: ({"configurado": True, "huella": secretos[c].huella,
                          "actualizado_en": secretos[c].actualizado_en.isoformat()}
                         if c in secretos else {"configurado": False})
                     for c in SECRETOS_BASE + secretos_canal(f.config)},
        "tool_estado": dict(sorted(tools.items())),
        "actualizado_en": f.actualizado_en.isoformat() if f.actualizado_en else None,
        "actualizado_por": f.actualizado_por,
    }


def _faltan(sistema: Sistema, presentes: set[str]) -> list[str]:
    try:
        validar_sistema(sistema.model_dump(mode="json"), dict.fromkeys(presentes, "x"))
    except ValueError as e:
        texto = str(e)
        if texto.startswith("faltan secretos: "):
            return [c.strip() for c in texto.removeprefix("faltan secretos: ").split(",")]
        raise
    return []


# --- lectura ---

async def listar(sesiones: async_sessionmaker[AsyncSession]) -> list[dict]:
    async with sesiones() as s:
        filas = (await s.execute(select(SistemaRegistro).order_by(SistemaRegistro.id))).scalars().all()
        campos = (await s.execute(select(SistemaSecreto.sistema_id, SistemaSecreto.campo))).all()
    por: dict[str, set[str]] = {}
    for sid, campo in campos:
        por.setdefault(sid, set()).add(campo)
    return [{"id": f.id, "nombre": f.nombre, "habilitado": f.habilitado, "version": f.version,
             "base_url": f.config.get("base_url"), "secretos": sorted(por.get(f.id, set())),
             "actualizado_en": f.actualizado_en.isoformat() if f.actualizado_en else None} for f in filas]


async def leer(sesiones: async_sessionmaker[AsyncSession], sistema_id: str) -> dict:
    async with sesiones() as s:
        fila = (await s.execute(select(SistemaRegistro).where(SistemaRegistro.id == sistema_id))).scalar_one_or_none()
        if fila is None:
            raise ErrorEscritura(404, "sistema_inexistente")
        return _vista(fila, await _secretos(s, sistema_id), await _tools(s, sistema_id))


# --- escritura ---

async def crear_sistema(sesiones: async_sessionmaker[AsyncSession], config: Mapping, *, por: str,
                        ip: str | None = None) -> dict:
    """Siempre deshabilitado: un sistema habilitado exige `token_manifiesto`, que se carga cuando la fila ya existe."""
    if RESERVADOS - {"id"} & set(config):
        raise ErrorEscritura(422, "campo_reservado")
    sistema = _validar({**config, "habilitado": False})
    try:
        async with sesiones() as s, s.begin():
            if await s.get(SistemaRegistro, sistema.id) is not None:
                raise ErrorEscritura(409, "sistema_existente")
            fila = SistemaRegistro(id=sistema.id, nombre=sistema.nombre, habilitado=False,
                                   config=config_json(sistema), version=1, actualizado_por=por)
            s.add(fila)
            await incrementar_version(s)
            _auditar(s, por, "sistema_crear", sistema.id, despues=_config_visible(fila), ip=ip)
            await s.flush()
            await s.refresh(fila)
            return _vista(fila, {}, {})
    except IntegrityError:
        raise ErrorEscritura(409, "sistema_existente") from None


async def actualizar_sistema(
    sesiones: async_sessionmaker[AsyncSession], cifrador: Cifrador | None, sistema_id: str, cuerpo: Mapping,
    version: int, *, token_manifiesto: str | None = None, llm_api_key: str | None = None,
    auth_hs256: str | None = None, por: str, ip: str | None = None,
) -> dict:
    """PUT de la configuración completa (no un parche) con control de `version`. Los secretos que lleguen se
    cifran en la misma transacción; ver las reglas de `base_url` y `llm.base_url` en la cabecera del módulo."""
    if RESERVADOS & set(cuerpo):
        raise ErrorEscritura(422, "campo_reservado")
    nuevos = {c: v for c, v in (("token_manifiesto", token_manifiesto), ("llm_api_key", llm_api_key),
                                ("auth_hs256", auth_hs256)) if v is not None}
    for campo, valor in nuevos.items():
        _validar_secreto(campo, valor)
    if nuevos and cifrador is None:
        raise ErrorEscritura(503, "sin_claves_maestras")

    async with sesiones() as s, s.begin():
        fila = await _bloquear(s, sistema_id)
        _exigir_version(fila, version)
        presentes = await _secretos(s, sistema_id)
        tools = await _tools(s, sistema_id)
        antes = _config_visible(fila)
        sistema = _validar({**cuerpo, "id": sistema_id, "tool_estado": tools})

        url_antes = antes.get("base_url")
        llm_antes = (antes.get("llm") or {}).get("base_url")
        llm_ahora = sistema.llm.base_url if sistema.llm else None
        borrar: set[str] = set()
        if sistema.base_url != url_antes and "token_manifiesto" not in nuevos:
            borrar.add("token_manifiesto")
        if llm_ahora != llm_antes and "llm_api_key" not in nuevos:
            borrar.add("llm_api_key")
        if sistema.auth.algoritmo != "HS256":
            if "auth_hs256" in nuevos:
                raise ErrorEscritura(422, "secreto_no_aplica", {"campo": "auth_hs256"})
            borrar.add("auth_hs256")
        # Cambiar o quitar el proveedor del canal deja sin sentido los secretos del anterior.
        aplican = secretos_canal(config_json(sistema))
        borrar |= {c for c in presentes if c in CAMPOS_SECRETOS and c not in SECRETOS_BASE and c not in aplican}
        final = (set(presentes) - borrar) | set(nuevos)

        faltan = _faltan(sistema, final) if sistema.habilitado else []
        if faltan:
            if "token_manifiesto" in faltan and "token_manifiesto" in borrar:
                raise ErrorEscritura(409, "base_url_requiere_token")
            raise ErrorEscritura(409, "faltan_secretos", {"faltan": faltan})

        fila.nombre, fila.habilitado, fila.config = sistema.nombre, sistema.habilitado, config_json(sistema)
        fila.version += 1
        fila.actualizado_por, fila.actualizado_en = por, func.now()
        borrados = sorted(c for c in borrar if c in presentes)
        if borrados:
            await s.execute(delete(SistemaSecreto).where(
                SistemaSecreto.sistema_id == sistema_id, SistemaSecreto.campo.in_(borrados)))
        for campo, valor in nuevos.items():
            await _guardar(s, cifrador, sistema_id, campo, valor, por)  # type: ignore[arg-type]
        await incrementar_version(s)
        _auditar(s, por, "sistema_actualizar", sistema_id, antes=antes, despues=_config_visible(fila),
                 ip=ip)
        if nuevos or borrados:
            _auditar(s, por, "secretos_cambiados", sistema_id,
                     despues={"cargados": sorted(nuevos), "borrados": borrados}, ip=ip)
        await s.flush()
        await s.refresh(fila)
        return _vista(fila, await _secretos(s, sistema_id), tools)


def _validar_secreto(campo: str, valor: str) -> None:
    if campo not in CAMPOS_SECRETOS:
        raise ErrorEscritura(422, "campo_desconocido")
    if not valor or valor != valor.strip() or len(valor) > SECRETO_MAX or not valor.isprintable():
        raise ErrorEscritura(422, "secreto_invalido")
    if campo == "auth_hs256" and len(valor.encode()) < HS256_MIN:
        raise ErrorEscritura(422, "secreto_corto", {"minimo": HS256_MIN})


async def _guardar(s: AsyncSession, cifrador: Cifrador, sistema_id: str, campo: str, valor: str,
                   por: str) -> None:
    c = cifrador.cifrar(sistema_id, campo, valor)
    vals = {"sistema_id": sistema_id, "campo": campo, "kid": c.kid, "nonce": c.nonce, "cifrado": c.cifrado,
            "huella": huella(valor), "actualizado_por": por}
    await s.execute(pg_insert(SistemaSecreto).values(**vals).on_conflict_do_update(
        index_elements=["sistema_id", "campo"],
        set_={k: v for k, v in vals.items() if k not in ("sistema_id", "campo")} | {"actualizado_en": func.now()}))


async def guardar_secreto(
    sesiones: async_sessionmaker[AsyncSession], cifrador: Cifrador | None, sistema_id: str, campo: str,
    valor: str, version: int, *, por: str, ip: str | None = None,
) -> dict:
    _validar_secreto(campo, valor)
    if cifrador is None:
        raise ErrorEscritura(503, "sin_claves_maestras")
    async with sesiones() as s, s.begin():
        fila = await _bloquear(s, sistema_id)
        _exigir_version(fila, version)
        if campo == "auth_hs256" and fila.config.get("auth", {}).get("algoritmo") != "HS256":
            raise ErrorEscritura(409, "secreto_no_aplica", {"campo": campo})
        if campo not in SECRETOS_BASE and campo not in secretos_canal(fila.config):
            raise ErrorEscritura(409, "secreto_no_aplica", {"campo": campo})
        await _guardar(s, cifrador, sistema_id, campo, valor, por)
        fila.version += 1
        fila.actualizado_por, fila.actualizado_en = por, func.now()
        await incrementar_version(s)
        _auditar(s, por, "secreto_guardar", sistema_id,
                 despues={"campo": campo, "huella": huella(valor)}, ip=ip)
        await s.flush()
        await s.refresh(fila)
        return _vista(fila, await _secretos(s, sistema_id), await _tools(s, sistema_id))


async def borrar_secreto(
    sesiones: async_sessionmaker[AsyncSession], sistema_id: str, campo: str, version: int, *, por: str,
    ip: str | None = None,
) -> dict:
    """Un sistema habilitado no puede quedarse sin un secreto que exige: se rechaza en vez de apagarlo."""
    if campo not in CAMPOS_SECRETOS:
        raise ErrorEscritura(422, "campo_desconocido")
    async with sesiones() as s, s.begin():
        fila = await _bloquear(s, sistema_id)
        _exigir_version(fila, version)
        presentes = await _secretos(s, sistema_id)
        if campo not in presentes:
            raise ErrorEscritura(404, "secreto_inexistente")
        if fila.habilitado:
            sistema = _validar({**_config_visible(fila), "id": sistema_id})
            if (f := _faltan(sistema, set(presentes) - {campo})):
                raise ErrorEscritura(409, "secreto_requerido", {"faltan": f})
        await s.execute(delete(SistemaSecreto).where(
            SistemaSecreto.sistema_id == sistema_id, SistemaSecreto.campo == campo))
        fila.version += 1
        fila.actualizado_por, fila.actualizado_en = por, func.now()
        await incrementar_version(s)
        _auditar(s, por, "secreto_borrar", sistema_id, despues={"campo": campo}, ip=ip)
        await s.flush()
        await s.refresh(fila)
        return _vista(fila, await _secretos(s, sistema_id), await _tools(s, sistema_id))


async def fijar_tool(
    sesiones: async_sessionmaker[AsyncSession], sistema_id: str, tool: str, habilitada: bool, defecto: bool,
    *, huella: str | None = None, por: str, ip: str | None = None,
) -> dict[str, bool]:
    """Guarda solo excepciones: si `habilitada` coincide con el valor por defecto de la tool, borra la fila
    (y con ella la aprobación). `huella` es la definición que aprueba un admin al encender una destructiva.
    No exige `version` (no toca la config) para que un interruptor no choque con una edición en curso."""
    if not TOOL_RE.match(tool):
        raise ErrorEscritura(422, "tool_invalida")
    async with sesiones() as s, s.begin():
        await _bloquear(s, sistema_id)
        if habilitada == defecto:
            await s.execute(delete(ToolEstado).where(
                ToolEstado.sistema_id == sistema_id, ToolEstado.tool == tool))
        else:
            await s.execute(pg_insert(ToolEstado).values(
                sistema_id=sistema_id, tool=tool, habilitada=habilitada, aprobada_huella=huella,
                actualizado_por=por
            ).on_conflict_do_update(index_elements=["sistema_id", "tool"], set_={
                "habilitada": habilitada, "aprobada_huella": huella, "actualizado_por": por,
                "actualizado_en": func.now()}))
        await incrementar_version(s)
        _auditar(s, por, "tool_fijar", sistema_id, despues={"tool": tool, "habilitada": habilitada, "destructiva": huella is not None, "huella": huella},
                  ip=ip)
        return await _tools(s, sistema_id)
