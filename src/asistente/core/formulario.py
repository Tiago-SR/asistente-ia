"""Tool local `pedir_datos`: muestra un formulario en el widget para completar un dato por fila (p. ej. la tasa de IVA
de cada línea de una factura). No ejecuta nada ni toca al sistema del cliente.

Emite un evento `ui` de tipo `formulario`; las respuestas vuelven como un turno normal del usuario, así que valen igual
que cualquier cosa que escriba. El modelo solo ve `{mostrado}`. Los campos son datos de negocio: la auditoría y el
historial guardan solo el título y la cantidad (ver `compactar_parametros`).
"""

import re
import uuid
from typing import Any

from jsonschema import Draft202012Validator, ValidationError

from asistente.core.llm.base import ToolDef
from asistente.core.ports import ResultadoTool

NOMBRE = "pedir_datos"
MAX_CAMPOS = 100
MAX_OPCIONES = 10

# Una línea, sin etiquetas HTML ni enlaces: el widget los pinta con textContent, pero el texto también vuelve al modelo.
_SEGURO = r"^(?!.*[\r\n])(?!.*<[A-Za-z/!?])(?!.*(?:https?:|javascript:|data:|www\.)).*$"


def _texto(maximo: int, minimo: int = 1) -> dict:
    return {"type": "string", "minLength": minimo, "maxLength": maximo, "pattern": _SEGURO}


_OPCION = {
    "type": "object",
    "properties": {"valor": _texto(60), "etiqueta": _texto(60)},
    "required": ["valor", "etiqueta"],
    "additionalProperties": False,
}
_CAMPO = {
    "type": "object",
    "properties": {
        "id": {"type": "string", "pattern": r"^[A-Za-z0-9_.-]{1,40}$"},
        "etiqueta": _texto(200),
        "tipo": {"enum": ["opcion", "numero", "texto"]},
        "opciones": {"type": "array", "items": _OPCION, "minItems": 2, "maxItems": MAX_OPCIONES},
        "valor_sugerido": {"type": ["string", "number"]},
        "contexto": _texto(100),
        "opcional": {"type": "boolean", "description": "El usuario puede dejarlo vacío (p. ej. serie, número o RUT que el documento no muestra)."},
    },
    "required": ["id", "etiqueta", "tipo"],
    "additionalProperties": False,
}
PARAMETROS = {
    "type": "object",
    "properties": {
        "titulo": _texto(120),
        "instruccion": _texto(300),
        "campos": {"type": "array", "items": _CAMPO, "minItems": 1, "maxItems": MAX_CAMPOS,
                   "description": "Un campo por fila o línea que falta completar."},
        "aplicar_a_todos": {"type": "boolean",
                            "description": "Con campos «opcion» de las mismas opciones: ofrece un selector para rellenar todos."},
    },
    "required": ["titulo", "campos"],
    "additionalProperties": False,
}

TOOL = ToolDef(
    NOMBRE,
    "Muestra al usuario un formulario con un campo por fila para completar datos que faltan en VARIAS filas o líneas "
    "(no para una pregunta simple). Cada campo es de tipo «opcion» (con 2 a 10 opciones {valor, etiqueta}), «numero» o "
    "«texto»; en «valor_sugerido» pon la respuesta probable si tienes una pista razonable, y en «contexto» un dato "
    "informativo de la fila (p. ej. su importe). Los datos que el documento no tiene y no son imprescindibles van con "
    "«opcional»: true. El usuario responde con un mensaje normal. Después de llamarla termina "
    "tu turno con una frase breve, sin repetir los campos ni llamar otras herramientas ni asumir valores.",
    PARAMETROS,
)

_VALIDADOR = Draft202012Validator(PARAMETROS)
_NUMERO = re.compile(r"^-?\d{1,15}([.,]\d{1,10})?$")
_INSTRUCCION = ("Formulario mostrado al usuario. Termina tu turno con una frase breve y espera su respuesta; "
                "no llames otras herramientas ni asumas valores.")


def compactar_parametros(nombre: str, parametros: dict) -> dict:
    """Lo que se guarda de la llamada (mensaje y auditoría): sin los campos, que son datos de negocio."""
    if nombre != NOMBRE or not isinstance(parametros, dict):
        return parametros
    campos = parametros.get("campos")
    return {"titulo": str(parametros.get("titulo", ""))[:120], "n_campos": len(campos) if isinstance(campos, list) else 0}


def _incoherencia(campos: list[dict]) -> str | None:
    """Lo que el esquema no puede expresar: ids únicos y la coherencia de opciones y valor sugerido."""
    ids = [c["id"] for c in campos]
    if len(set(ids)) != len(ids):
        return "hay ids de campo repetidos"
    for c in campos:
        sug, ops = c.get("valor_sugerido"), c.get("opciones")
        if c["tipo"] == "opcion":
            if not ops:
                return f"el campo «{c['id']}» es de tipo opcion y no trae opciones"
            valores = [o["valor"] for o in ops]
            if len(set(valores)) != len(valores):
                return f"el campo «{c['id']}» repite el valor de una opción"
            if sug is not None and sug not in valores:
                return f"el valor_sugerido de «{c['id']}» no es una de sus opciones"
            continue
        if ops:
            return f"el campo «{c['id']}» no es de tipo opcion y trae opciones"
        if sug is None:
            continue
        if c["tipo"] == "numero" and not (isinstance(sug, (int, float)) and not isinstance(sug, bool)
                                          or isinstance(sug, str) and _NUMERO.match(sug.strip())):
            return f"el valor_sugerido de «{c['id']}» no es un número"
        if c["tipo"] == "texto" and not isinstance(sug, str):
            return f"el valor_sugerido de «{c['id']}» no es texto"
    return None


def _mismas_opciones(campos: list[dict]) -> bool:
    """Hay al menos dos campos «opcion» y todos comparten las mismas opciones: «aplicar a todas» tiene sentido."""
    conjuntos = [tuple(o["valor"] for o in c["opciones"]) for c in campos if c["tipo"] == "opcion"]
    return len(conjuntos) >= 2 and len(set(conjuntos)) == 1


def ejecutar(parametros: dict) -> ResultadoTool:
    try:
        _VALIDADOR.validate(parametros)
    except ValidationError as e:
        return ResultadoTool(False, error="parametros_invalidos", detalle=e.message[:200])
    campos = parametros["campos"]
    if (problema := _incoherencia(campos)) is not None:
        return ResultadoTool(False, error="parametros_invalidos", detalle=problema)
    formulario: dict[str, Any] = {
        "tipo": "formulario", "id": str(uuid.uuid4()), "titulo": parametros["titulo"], "campos": campos,
        "aplicar_a_todos": bool(parametros.get("aplicar_a_todos")) and _mismas_opciones(campos),
    }
    if parametros.get("instruccion"):
        formulario["instruccion"] = parametros["instruccion"]
    return ResultadoTool(True, {"mostrado": True, "instruccion": _INSTRUCCION}, ui=[formulario])
