"""Conector HTTP: ejecuta una tool en el sistema con el token del usuario (sección 4.3)."""

import json
import logging
from typing import Any

import httpx
from jsonschema import Draft202012Validator

from asistente.core.llm.base import ToolDef
from asistente.core.ports import ResultadoTool
from asistente.sistemas.auth import Usuario
from asistente.sistemas.manifiesto import CacheManifiestos, ManifiestoInvalido, Tool
from asistente.sistemas.registro import RegistroSistemas

log = logging.getLogger(__name__)

ERRORES_NEGOCIO = {"no_encontrado", "sin_acceso", "parametros_invalidos", "no_disponible"}
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
        self, usuario: Usuario, nombre_tool: str, parametros: dict, request_id: str
    ) -> ResultadoTool:
        sistema = self._registro.obtener(usuario.sistema_id)
        if sistema is None:
            return _fallo("no_disponible", "sistema deshabilitado")

        tool = await self._tool_de_lectura(usuario.sistema_id, nombre_tool)
        if tool is None:
            return _fallo("no_disponible", f"tool desconocida: {nombre_tool}")

        # Los ids que propone el LLM no son confiables: se validan antes de llamar.
        errores = sorted(
            Draft202012Validator(tool.parametros).iter_errors(parametros),
            key=lambda e: list(e.path),
        )
        if errores:
            return _fallo("parametros_invalidos", "; ".join(e.message for e in errores[:5]))

        url = sistema.base_url.rstrip("/") + sistema.conector.ruta_ejecucion.format(nombre=nombre_tool)
        try:
            r = await self._cliente.post(
                url,
                json={"parametros": parametros},
                headers={
                    "Authorization": f"Bearer {usuario.token}",
                    "X-Asistente-Contrato": "1",
                    "X-Asistente-Request-Id": request_id,
                },
                timeout=tool.timeout_s or min(DEFAULT_TIMEOUT_S, sistema.conector.timeout_s),
            )
        except httpx.TimeoutException:
            return _fallo("timeout", "el sistema no respondió a tiempo")
        except httpx.HTTPError as e:
            log.warning("[%s] fallo de red en %s: %s", request_id, nombre_tool, type(e).__name__)
            return _fallo("error_sistema", "no se pudo contactar al sistema")

        if r.status_code == 401:
            return _fallo("token_expirado", "token inválido o vencido", 401)
        if r.status_code == 403:
            return _fallo("sin_acceso", "el sistema rechazó el acceso", 403)
        if r.status_code != 200:  # incluye 3xx: no se siguen redirecciones
            return _fallo("error_sistema", f"el sistema respondió HTTP {r.status_code}", r.status_code)

        return self._interpretar(r, sistema.conector.max_respuesta_bytes)

    def para(self, usuario: Usuario, request_id: str) -> "ConectorDeUsuario":
        return ConectorDeUsuario(self, usuario, request_id)

    async def tools_de(self, sistema_id: str) -> list[ToolDef]:
        try:
            manifiesto = await self._manifiestos.obtener(sistema_id)
        except ManifiestoInvalido as e:
            log.error("sin manifiesto utilizable para %s: %s", sistema_id, e)
            return []
        return [ToolDef(t.nombre, t.descripcion, t.parametros) for t in manifiesto.tools_lectura()]

    async def _tool_de_lectura(self, sistema_id: str, nombre: str) -> Tool | None:
        try:
            manifiesto = await self._manifiestos.obtener(sistema_id)
        except ManifiestoInvalido as e:
            log.error("sin manifiesto utilizable para %s: %s", sistema_id, e)
            return None
        tool = manifiesto.tools.get(nombre)
        # Solo lectura: una tool de escritura nunca se ejecuta desde el asistente.
        return tool if tool and tool.efecto == "lectura" else None

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
