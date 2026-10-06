"""Descarga, validación y cache del manifiesto de tools (sección 2 del contrato)."""

import logging
import re
import time
from collections.abc import Iterable
from dataclasses import dataclass, field

import httpx
from jsonschema import Draft202012Validator
from jsonschema.exceptions import SchemaError

from asistente.core.recientes import NOMBRE as TOOL_LOCAL_RECIENTES
from asistente.sistemas.registro import RegistroSistemas, Sistema

log = logging.getLogger(__name__)

CONTRATO_SOPORTADO = "1"
MAX_TOOLS = 40
MAX_BYTES_MANIFIESTO = 256 * 1024
MAX_DESCRIPCION = 1000
MAX_TTL_CONFIRMACION_S = 300
NOMBRE_RE = re.compile(r"^[a-z][a-z0-9_]{0,63}$")


class ManifiestoInvalido(Exception):
    pass


@dataclass(frozen=True)
class Tool:
    nombre: str
    descripcion: str
    parametros: dict
    efecto: str
    timeout_s: float | None = None
    # Solo escritura: declara que el sistema soporta el flujo de propuesta y confirmación.
    confirmacion_ttl_s: int | None = None
    destructiva: bool = False

    @property
    def accionable(self) -> bool:
        """Escritura que se puede ofrecer al modelo: soporta confirmación y no es destructiva
        (el borrado no se admite en esta fase)."""
        return self.efecto == "escritura" and self.confirmacion_ttl_s is not None and not self.destructiva


@dataclass(frozen=True)
class Manifiesto:
    sistema_nombre: str
    version_sistema: str | None
    tools: dict[str, Tool] = field(default_factory=dict)  # todas las válidas

    def tools_lectura(self) -> list[Tool]:
        """Lo único que se expone al modelo en el MVP."""
        return [t for t in self.tools.values() if t.efecto == "lectura"]

    def tools_accion(self, habilitadas: Iterable[str]) -> list[Tool]:
        """Escrituras que el operador habilitó para este sistema (`acciones_habilitadas`)."""
        permitidas = set(habilitadas)
        return [t for t in self.tools.values() if t.accionable and t.nombre in permitidas]


def parsear_manifiesto(crudo: object) -> Manifiesto:
    """Valida un manifiesto ya decodificado. Las tools inválidas se descartan con log;
    un manifiesto inválido en su conjunto lanza `ManifiestoInvalido`."""
    if not isinstance(crudo, dict):
        raise ManifiestoInvalido("el manifiesto debe ser un objeto JSON")
    if crudo.get("contrato") != CONTRATO_SOPORTADO:
        raise ManifiestoInvalido(
            f"versión de contrato no soportada: {crudo.get('contrato')!r} "
            f"(se soporta {CONTRATO_SOPORTADO!r})"
        )
    info = crudo.get("sistema")
    if not isinstance(info, dict) or not isinstance(info.get("nombre"), str) or not info["nombre"]:
        raise ManifiestoInvalido("falta sistema.nombre")
    tools_crudas = crudo.get("tools")
    if not isinstance(tools_crudas, list):
        raise ManifiestoInvalido("`tools` debe ser una lista")
    if len(tools_crudas) > MAX_TOOLS:
        raise ManifiestoInvalido(f"demasiadas tools ({len(tools_crudas)} > {MAX_TOOLS})")

    tools: dict[str, Tool] = {}
    repetidas: set[str] = set()
    for i, t in enumerate(tools_crudas):
        try:
            tool = _parsear_tool(t)
        except ManifiestoInvalido as e:
            log.error("tool #%d rechazada: %s", i, e)
            continue
        if tool.nombre in repetidas:
            continue
        if tool.nombre in tools:
            # Nombre ambiguo: no se sabe cuál es la correcta, se descartan ambas.
            log.error("tool duplicada, se descartan todas: %s", tool.nombre)
            del tools[tool.nombre]
            repetidas.add(tool.nombre)
            continue
        tools[tool.nombre] = tool

    version = info.get("version")
    return Manifiesto(
        sistema_nombre=info["nombre"],
        version_sistema=version if isinstance(version, str) else None,
        tools=tools,
    )


def _parsear_tool(t: object) -> Tool:
    if not isinstance(t, dict):
        raise ManifiestoInvalido("la tool debe ser un objeto")
    nombre = t.get("nombre")
    if not isinstance(nombre, str) or not NOMBRE_RE.match(nombre):
        raise ManifiestoInvalido(f"nombre inválido: {nombre!r}")
    if nombre == TOOL_LOCAL_RECIENTES:
        raise ManifiestoInvalido(f"{nombre}: nombre reservado para una tool local del asistente")
    desc = t.get("descripcion")
    if not isinstance(desc, str) or not desc.strip() or len(desc) > MAX_DESCRIPCION:
        raise ManifiestoInvalido(f"{nombre}: descripcion ausente o > {MAX_DESCRIPCION} caracteres")
    efecto = t.get("efecto")
    if efecto not in ("lectura", "escritura"):
        raise ManifiestoInvalido(f"{nombre}: efecto inválido: {efecto!r}")
    params = t.get("parametros")
    if not isinstance(params, dict) or params.get("type") != "object":
        raise ManifiestoInvalido(f"{nombre}: parametros debe ser un JSON Schema de tipo object")
    try:
        Draft202012Validator.check_schema(params)
    except SchemaError as e:
        raise ManifiestoInvalido(f"{nombre}: JSON Schema inválido: {e.message}") from e
    timeout = t.get("timeout_s")
    if timeout is not None and (
        isinstance(timeout, bool) or not isinstance(timeout, int | float) or not 0 < timeout <= 120
    ):
        raise ManifiestoInvalido(f"{nombre}: timeout_s inválido: {timeout!r}")
    ttl = None
    confirmacion = t.get("confirmacion")
    if confirmacion is not None:
        if efecto != "escritura" or not isinstance(confirmacion, dict):
            raise ManifiestoInvalido(f"{nombre}: `confirmacion` solo aplica a escrituras y debe ser un objeto")
        ttl = confirmacion.get("ttl_s", 120)
        if isinstance(ttl, bool) or not isinstance(ttl, int) or not 10 <= ttl <= MAX_TTL_CONFIRMACION_S:
            raise ManifiestoInvalido(f"{nombre}: confirmacion.ttl_s inválido: {ttl!r}")
    destructiva = t.get("destructiva", False)
    if not isinstance(destructiva, bool):
        raise ManifiestoInvalido(f"{nombre}: `destructiva` debe ser booleano")
    return Tool(nombre, desc, params, efecto, float(timeout) if timeout is not None else None,
                ttl, destructiva)


class CacheManifiestos:
    """Manifiesto por sistema, con TTL y recarga manual."""

    def __init__(
        self,
        registro: RegistroSistemas,
        cliente: httpx.AsyncClient | None = None,
        reloj=time.monotonic,
    ) -> None:
        self._registro = registro
        # Sin redirecciones: el conector solo puede hablar con la base_url registrada.
        self._cliente = cliente or httpx.AsyncClient(follow_redirects=False)
        self._reloj = reloj
        self._cache: dict[str, tuple[float, Manifiesto]] = {}

    async def obtener(self, sistema_id: str) -> Manifiesto:
        sistema = self._registro.obtener(sistema_id)
        if sistema is None:
            raise ManifiestoInvalido(f"sistema desconocido o deshabilitado: {sistema_id}")
        hit = self._cache.get(sistema_id)
        if hit and self._reloj() - hit[0] < sistema.conector.manifiesto_ttl_s:
            return hit[1]
        return await self.recargar(sistema_id)

    async def recargar(self, sistema_id: str) -> Manifiesto:
        sistema = self._registro.obtener(sistema_id)
        if sistema is None:
            self._cache.pop(sistema_id, None)
            raise ManifiestoInvalido(f"sistema desconocido o deshabilitado: {sistema_id}")
        try:
            manifiesto = await self._descargar(sistema)
        except ManifiestoInvalido:
            # Un manifiesto nuevo inválido no pisa al último bueno; si no hay, se propaga.
            if sistema_id in self._cache:
                log.error("manifiesto de %s inválido; se conserva el anterior", sistema_id)
                return self._cache[sistema_id][1]
            raise
        self._cache[sistema_id] = (self._reloj(), manifiesto)
        return manifiesto

    def invalidar(self, sistema_id: str | None = None) -> None:
        if sistema_id is None:
            self._cache.clear()
        else:
            self._cache.pop(sistema_id, None)

    async def _descargar(self, s: Sistema) -> Manifiesto:
        token = s.secreto(s.conector.token_manifiesto_env, self._registro.env)
        url = s.base_url.rstrip("/") + s.conector.ruta_manifiesto
        try:
            async with self._cliente.stream(
                "GET",
                url,
                headers={"Authorization": f"Bearer {token}", "X-Asistente-Contrato": "1"},
                timeout=s.conector.timeout_s,
            ) as r:
                if r.status_code != 200:
                    raise ManifiestoInvalido(f"el manifiesto respondió HTTP {r.status_code}")
                cuerpo = bytearray()
                async for trozo in r.aiter_bytes():
                    cuerpo += trozo
                    if len(cuerpo) > MAX_BYTES_MANIFIESTO:
                        raise ManifiestoInvalido("manifiesto demasiado grande")
        except httpx.HTTPError as e:
            raise ManifiestoInvalido(f"no se pudo descargar el manifiesto: {type(e).__name__}") from e
        try:
            crudo = httpx.Response(200, content=bytes(cuerpo)).json()
        except ValueError as e:
            raise ManifiestoInvalido("el manifiesto no es JSON válido") from e
        return parsear_manifiesto(crudo)
