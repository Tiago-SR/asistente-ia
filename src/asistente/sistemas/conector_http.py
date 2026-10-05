"""Conector HTTP: ejecuta una tool en el sistema con el token del usuario (sección 3 del contrato)."""

import json
import logging
from typing import Any

import httpx
from jsonschema import Draft202012Validator

from asistente.core.llm.base import ToolDef
from asistente.core.ports import ResultadoPropuesta, ResultadoTool
from asistente.sistemas.auth import Usuario
from asistente.sistemas.manifiesto import CacheManifiestos, ManifiestoInvalido, Tool
from asistente.sistemas.registro import RegistroSistemas

log = logging.getLogger(__name__)

# `conflicto` (v1.1): el dato cambió entre la propuesta y la confirmación de una acción.
ERRORES_NEGOCIO = {"no_encontrado", "sin_acceso", "parametros_invalidos", "no_disponible", "conflicto"}
MAX_RESUMEN = 300
MAX_LINEAS = 10
MAX_LINEA = 200
DEFAULT_TIMEOUT_S = 15.0


def _fallo(error: str, detalle: str, status: int | None = None) -> ResultadoTool:
    return ResultadoTool(ok=False, error=error, detalle=detalle, status_http=status)


class ConectorHttp:
    def __init__(
        self,
        registro: RegistroSistemas,
        manifiestos: CacheManifiestos,
        cliente: httpx.AsyncClient | None = None,
    ) -> None:
        self._registro = registro
        self._manifiestos = manifiestos
        self._cliente = cliente or httpx.AsyncClient(follow_redirects=False)

    async def ejecutar(
        self, usuario: Usuario, nombre_tool: str, parametros: dict, request_id: str,
        *, escritura: bool = False, idempotencia: str | None = None,
    ) -> ResultadoTool:
        """`escritura=True` solo lo usa el endpoint de confirmación, con un token de escritura."""
        sistema, tool, fallo = await self._preparar(usuario, nombre_tool, parametros, escritura)
        if fallo is not None:
            return fallo
        url = sistema.base_url.rstrip("/") + sistema.conector.ruta_ejecucion.format(nombre=nombre_tool)
        cabeceras = {}
        if idempotencia:
            cabeceras["Idempotency-Key"] = idempotencia
        r = await self._post(sistema, tool, url, usuario, {"parametros": parametros}, request_id, cabeceras)
        if isinstance(r, ResultadoTool):
            return r
        return self._interpretar(r, sistema.conector.max_respuesta_bytes)

    async def proponer(
        self, usuario: Usuario, nombre_tool: str, parametros: dict, request_id: str
    ) -> ResultadoPropuesta:
        """Pide al sistema validar y resumir una escritura (token de lectura, sin efectos)."""
        sistema, tool, fallo = await self._preparar(usuario, nombre_tool, parametros, True)
        if fallo is not None:
            return _fallo_propuesta(fallo.error or "error_sistema", fallo.detalle or "", fallo.status_http)
        url = sistema.base_url.rstrip("/") + sistema.conector.ruta_propuesta.format(nombre=nombre_tool)
        r = await self._post(sistema, tool, url, usuario, {"parametros": parametros}, request_id, {})
        if isinstance(r, ResultadoTool):
            return _fallo_propuesta(r.error or "error_sistema", r.detalle or "", r.status_http)
        return _interpretar_propuesta(r, tool.confirmacion_ttl_s or 120)

    async def _preparar(self, usuario, nombre_tool, parametros, escritura):
        """Resuelve sistema y tool y valida los parámetros. Devuelve (sistema, tool, fallo)."""
        sistema = self._registro.obtener(usuario.sistema_id)
        if sistema is None:
            return None, None, _fallo("no_disponible", "sistema deshabilitado")
        tool = await self._tool(sistema, nombre_tool, escritura)
        if tool is None:
            return None, None, _fallo("no_disponible", f"tool desconocida: {nombre_tool}")
        # Los ids que propone el LLM no son confiables: se validan antes de llamar.
        errores = sorted(
            Draft202012Validator(tool.parametros).iter_errors(parametros),
            key=lambda e: list(e.path),
        )
        if errores:
            return None, None, _fallo("parametros_invalidos", "; ".join(e.message for e in errores[:5]))
        return sistema, tool, None

    async def _post(self, sistema, tool, url, usuario, cuerpo, request_id, extra):
        """POST al sistema con el token del usuario. Devuelve la respuesta 200 o un `ResultadoTool` de fallo."""
        try:
            r = await self._cliente.post(
                url,
                json=cuerpo,
                headers={
                    "Authorization": f"Bearer {usuario.token}",
                    "X-Asistente-Contrato": "1",
                    "X-Asistente-Request-Id": request_id,
                    **extra,
                },
                timeout=tool.timeout_s or min(DEFAULT_TIMEOUT_S, sistema.conector.timeout_s),
                # Nunca se reenvía el token del usuario a otro host, sea cual sea el cliente inyectado.
                follow_redirects=False,
            )
        except httpx.TimeoutException:
            return _fallo("timeout", "el sistema no respondió a tiempo")
        except httpx.HTTPError as e:
            log.warning("[%s] fallo de red en %s: %s", request_id, tool.nombre, type(e).__name__)
            return _fallo("error_sistema", "no se pudo contactar al sistema")

        if r.status_code == 401:
            return _fallo("token_expirado", "token inválido o vencido", 401)
        if r.status_code == 403:
            return _fallo("sin_acceso", "el sistema rechazó el acceso", 403)
        if r.status_code != 200:  # incluye 3xx: no se siguen redirecciones
            return _fallo("error_sistema", f"el sistema respondió HTTP {r.status_code}", r.status_code)
        return r

    def para(self, usuario: Usuario, request_id: str) -> "ConectorDeUsuario":
        return ConectorDeUsuario(self, usuario, request_id)

    async def tools_de(self, sistema_id: str) -> list[ToolDef]:
        try:
            manifiesto = await self._manifiestos.obtener(sistema_id)
        except ManifiestoInvalido as e:
            log.error("sin manifiesto utilizable para %s: %s", sistema_id, e)
            return []
        sistema = self._registro.obtener(sistema_id)
        habilitadas = sistema.acciones_habilitadas if sistema else ()
        return [
            *(ToolDef(t.nombre, t.descripcion, t.parametros) for t in manifiesto.tools_lectura()),
            *(ToolDef(t.nombre, t.descripcion, t.parametros, escritura=True)
              for t in manifiesto.tools_accion(habilitadas)),
        ]

    async def _tool(self, sistema, nombre: str, escritura: bool) -> Tool | None:
        try:
            manifiesto = await self._manifiestos.obtener(sistema.id)
        except ManifiestoInvalido as e:
            log.error("sin manifiesto utilizable para %s: %s", sistema.id, e)
            return None
        tool = manifiesto.tools.get(nombre)
        if tool is None:
            return None
        if not escritura:
            # Por esta vía solo se ejecuta lectura: el agente nunca ejecuta una escritura.
            return tool if tool.efecto == "lectura" else None
        # Una escritura solo existe si el operador la habilitó y el sistema declara la confirmación.
        habilitada = nombre in sistema.acciones_habilitadas
        return tool if tool.accionable and habilitada else None

    def _interpretar(self, r: httpx.Response, max_bytes: int) -> ResultadoTool:
        try:
            cuerpo = r.json()
        except ValueError:
            return _fallo("respuesta_invalida", "la respuesta no es JSON", r.status_code)
        if not isinstance(cuerpo, dict) or not isinstance(cuerpo.get("ok"), bool):
            return _fallo("respuesta_invalida", "falta el campo booleano `ok`", r.status_code)

        if cuerpo["ok"] is False:
            error = cuerpo.get("error")
            if error not in ERRORES_NEGOCIO:
                return _fallo("respuesta_invalida", f"código de error desconocido: {error!r}", r.status_code)
            detalle = cuerpo.get("detalle")
            return _fallo(error, detalle[:1000] if isinstance(detalle, str) else "", r.status_code)

        if "datos" not in cuerpo:
            return _fallo("respuesta_invalida", "falta `datos`", r.status_code)
        datos, truncado = _limitar(cuerpo["datos"], max_bytes)
        fuente = cuerpo.get("fuente")
        return ResultadoTool(
            ok=True,
            datos=datos,
            fuente=fuente[:200] if isinstance(fuente, str) else None,
            ui=_ui_valida(cuerpo.get("ui")),
            truncado=truncado,
            status_http=r.status_code,
            bytes_respuesta=len(r.content),
        )


def _fallo_propuesta(error: str, detalle: str, status: int | None = None) -> ResultadoPropuesta:
    return ResultadoPropuesta(ok=False, error=error, detalle_error=detalle, status_http=status)


def _interpretar_propuesta(r: httpx.Response, ttl_s: int) -> ResultadoPropuesta:
    try:
        cuerpo = r.json()
    except ValueError:
        return _fallo_propuesta("respuesta_invalida", "la respuesta no es JSON", r.status_code)
    if not isinstance(cuerpo, dict) or not isinstance(cuerpo.get("ok"), bool):
        return _fallo_propuesta("respuesta_invalida", "falta el campo booleano `ok`", r.status_code)
    if cuerpo["ok"] is False:
        error = cuerpo.get("error")
        if error not in ERRORES_NEGOCIO:
            return _fallo_propuesta("respuesta_invalida", f"código de error desconocido: {error!r}", r.status_code)
        detalle = cuerpo.get("detalle")
        return _fallo_propuesta(error, detalle[:1000] if isinstance(detalle, str) else "", r.status_code)

    resumen, huella, lineas = cuerpo.get("resumen"), cuerpo.get("huella"), cuerpo.get("detalle", [])
    if not isinstance(resumen, str) or not resumen.strip():
        return _fallo_propuesta("respuesta_invalida", "falta `resumen`", r.status_code)
    if not isinstance(huella, str) or not 8 <= len(huella) <= 128:
        return _fallo_propuesta("respuesta_invalida", "falta `huella`", r.status_code)
    if not isinstance(lineas, list) or not all(isinstance(x, str) for x in lineas):
        return _fallo_propuesta("respuesta_invalida", "`detalle` debe ser una lista de textos", r.status_code)
    expira_s = cuerpo.get("expira_s", ttl_s)
    if isinstance(expira_s, bool) or not isinstance(expira_s, int) or expira_s <= 0:
        expira_s = ttl_s
    return ResultadoPropuesta(
        ok=True,
        resumen=resumen.strip()[:MAX_RESUMEN],
        lineas=tuple(x[:MAX_LINEA] for x in lineas[:MAX_LINEAS]),
        huella=huella,
        expira_s=min(expira_s, ttl_s),  # el operador de la tool fija el tope, no la respuesta
        status_http=r.status_code,
    )


def _limitar(datos: Any, max_bytes: int) -> tuple[Any, bool]:
    """Si `datos` serializado excede el límite, se reemplaza por un recorte de texto
    marcado como truncado (el modelo debe saberlo)."""
    texto = json.dumps(datos, ensure_ascii=False)
    crudo = texto.encode()
    if len(crudo) <= max_bytes:
        return datos, False
    recorte = crudo[:max_bytes].decode(errors="ignore")
    return {"recorte_parcial": recorte}, True


def _ui_valida(ui: Any) -> list[dict]:
    if not isinstance(ui, list):
        return []
    return [u for u in ui if isinstance(u, dict) and u.get("tipo") == "navegar"]


class ConectorDeUsuario:
    """`ConectorHttp` ligado a un usuario y una petición: implementa el puerto `Conector`."""

    def __init__(self, conector: ConectorHttp, usuario: Usuario, request_id: str) -> None:
        self._conector, self._usuario, self._request_id = conector, usuario, request_id

    async def tools(self) -> list[ToolDef]:
        return await self._conector.tools_de(self._usuario.sistema_id)

    async def ejecutar(self, nombre: str, parametros: dict) -> ResultadoTool:
        return await self._conector.ejecutar(self._usuario, nombre, parametros, self._request_id)

    async def proponer(self, nombre: str, parametros: dict) -> ResultadoPropuesta:
        return await self._conector.proponer(self._usuario, nombre, parametros, self._request_id)
