"""Tool local `generar_excel`: arma un .xlsx con una tabla y lo deja para que el usuario lo descargue.

No toca al sistema del cliente. Lo que el usuario recibe es un botón de descarga (evento `ui` de tipo `descarga`);
el modelo solo ve `{id, nombre, filas}`. Las filas son datos de negocio: ni el historial ni la auditoría las guardan
(ver `compactar_parametros`).
"""

import asyncio
import io
import re
from typing import Any

from jsonschema import Draft202012Validator, ValidationError
from openpyxl import Workbook
from openpyxl.styles import Font

from asistente.core.llm.base import ToolDef
from asistente.core.ports import Archivos, Contexto, LimiteExcedido, ResultadoTool

NOMBRE = "generar_excel"
MIME = "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet"
MAX_CELDA = 32_767  # límite de Excel por celda

_CELDA = {"type": ["string", "number", "boolean", "null"]}
PARAMETROS = {
    "type": "object",
    "properties": {
        "nombre": {"type": "string", "minLength": 1, "maxLength": 80,
                   "description": "Nombre del archivo, sin extensión (p. ej. «factura_0123»)."},
        "columnas": {"type": "array", "items": {"type": "string", "maxLength": 200}, "minItems": 1,
                     "description": "Encabezados de la tabla."},
        "filas": {"type": "array", "items": {"type": "array", "items": _CELDA},
                  "description": "Una lista por fila, con un valor por columna. Los importes y cantidades como números."},
    },
    "required": ["nombre", "columnas", "filas"],
    "additionalProperties": False,
}

TOOL = ToolDef(
    NOMBRE,
    "Genera un archivo Excel (.xlsx) descargable con una tabla. Úsala solo cuando el usuario pida un Excel o una "
    "planilla. Los datos salen de lo que consultaste con tus herramientas o de lo que el usuario escribió o mostró "
    "en esta conversación; no inventes ni completes valores. Después de llamarla el usuario ve un botón de descarga: "
    "díselo en una frase, sin enlaces ni repetir la tabla.",
    PARAMETROS,
)

_VALIDADOR = Draft202012Validator(PARAMETROS)
_NUMERO = re.compile(r"^-?(0|[1-9]\d{0,14})(\.\d{1,10})?$")  # sin ceros a la izquierda (códigos) ni más de 15 dígitos
_PELIGROSO = ("=", "+", "-", "@", "\t", "\r")  # Excel lo ejecutaría como fórmula
_NOMBRE_VALIDO = re.compile(r"[^\w .-]")
_INSTRUCCION = "El usuario ve un botón para descargar el archivo. No incluyas enlaces ni repitas toda la tabla."


def compactar_parametros(nombre: str, parametros: dict) -> dict:
    """Lo que se guarda de la llamada (mensaje y auditoría): sin las filas, que son datos de negocio."""
    if nombre != NOMBRE or not isinstance(parametros, dict):
        return parametros
    filas, cols = parametros.get("filas"), parametros.get("columnas")
    return {"nombre": str(parametros.get("nombre", ""))[:80],
            "n_filas": len(filas) if isinstance(filas, list) else 0,
            "n_columnas": len(cols) if isinstance(cols, list) else 0}


def nombre_archivo(nombre: str) -> str:
    base = _NOMBRE_VALIDO.sub("_", nombre.removesuffix(".xlsx")).strip(" .")[:80] or "datos"
    return f"{base}.xlsx"


def _poner(ws, fila: int, col: int, v: Any) -> None:
    if isinstance(v, str):
        v = v[:MAX_CELDA]
        if _NUMERO.match(v.strip()):
            v = float(v) if "." in v else int(v)
    c = ws.cell(row=fila, column=col, value=v)
    if isinstance(v, str) and v.startswith(_PELIGROSO):
        c.data_type = "s"  # texto, no fórmula


def _construir(columnas: list[str], filas: list[list]) -> bytes:
    wb = Workbook()
    ws = wb.active
    ws.title = "Datos"
    for j, titulo in enumerate(columnas, 1):
        _poner(ws, 1, j, titulo)
        ws.cell(row=1, column=j).font = Font(bold=True)
    for i, f in enumerate(filas, 2):
        for j, v in enumerate(f, 1):
            _poner(ws, i, j, v)
    salida = io.BytesIO()
    wb.save(salida)
    return salida.getvalue()


async def ejecutar(
    ctx: Contexto, archivos: Archivos, conversacion_id: Any, parametros: dict,
    *, max_filas: int, max_columnas: int, max_kb: int,
) -> ResultadoTool:
    try:
        _VALIDADOR.validate(parametros)
    except ValidationError as e:
        return ResultadoTool(False, error="parametros_invalidos", detalle=e.message[:200])
    columnas, filas = parametros["columnas"], parametros["filas"]
    if len(columnas) > max_columnas or len(filas) > max_filas:
        return ResultadoTool(False, error="excel_demasiado_grande",
                             detalle=f"máximo {max_filas} filas y {max_columnas} columnas")
    if any(len(f) > len(columnas) for f in filas):
        return ResultadoTool(False, error="parametros_invalidos", detalle="una fila tiene más valores que columnas")
    datos = await asyncio.to_thread(_construir, columnas, filas)
    if len(datos) > max_kb * 1024:
        return ResultadoTool(False, error="excel_demasiado_grande", detalle=f"el archivo supera {max_kb} KB")
    nombre = nombre_archivo(parametros["nombre"])
    try:
        id_ = await archivos.guardar(ctx, conversacion_id, nombre, datos, MIME)
    except LimiteExcedido as e:
        return ResultadoTool(False, error=e.cual, detalle="ya se generaron muchos archivos hoy; intenta mañana")
    return ResultadoTool(True, {"id": id_, "nombre": nombre, "filas": len(filas), "instruccion": _INSTRUCCION},
                         ui=[{"tipo": "descarga", "id": id_, "nombre": nombre}])
