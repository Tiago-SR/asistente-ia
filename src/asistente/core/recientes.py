"""Tool local `consultas_recientes`: «lo mismo que ayer» sin guardar resultados.

Devuelve QUÉ consultó el usuario (tool y parámetros), nunca lo que respondió el sistema. Para repetir una
consulta el modelo vuelve a llamar a la tool original, así que las cifras son siempre las de ahora y la
regla «toda cifra sale de una tool consultada en esta conversación» no se toca.
"""

from datetime import UTC, datetime, timedelta
from typing import Any

from jsonschema import Draft202012Validator

from asistente.core import zona as zonas
from asistente.core.llm.base import ToolDef
from asistente.core.ports import ConsultaPrevia, Contexto, Recientes, ResultadoTool

NOMBRE = "consultas_recientes"
LIMITE_DEFECTO = 10
LIMITE_MAX = 20

PARAMETROS = {
    "type": "object",
    "properties": {
        "dias": {"type": "integer", "minimum": 1, "maximum": 365,
                 "description": "Cuántos días hacia atrás mirar (por defecto, todo lo que se conserva)."},
        "limite": {"type": "integer", "minimum": 1, "maximum": LIMITE_MAX,
                   "description": f"Cuántas consultas devolver (por defecto {LIMITE_DEFECTO})."},
    },
    "additionalProperties": False,
}

TOOL = ToolDef(
    NOMBRE,
    "Lista las consultas de lectura que este usuario hizo antes (la tool y sus parámetros, sin resultados), "
    "de la más reciente a la más antigua. Úsala solo cuando pida repetir o retomar una consulta anterior "
    "(«lo mismo que ayer», «la del lunes», «la de siempre»). Después vuelve a ejecutar la tool original: "
    "los resultados de entonces no se guardan y no valen.",
    PARAMETROS,
)

_VALIDADOR = Draft202012Validator(PARAMETROS)
_NOTA = ("Son las consultas, no sus resultados. Para repetir una, llama de nuevo a la tool original con sus "
         "parámetros; si lleva fechas, ajústalas solo si el usuario lo pidió.")


def a_vista(c: ConsultaPrevia, zona_actual: str) -> dict[str, Any]:
    """Una consulta como la ve el modelo, con la fecha en la zona ACTUAL del usuario.

    La zona en que se hizo se guarda con la consulta; solo se menciona cuando la fecha cambiaría de
    día (el usuario viajó, o la zona de entonces era otra): ahí «ayer» podría ser ambiguo."""
    ahora = zonas.zona(zona_actual)
    local = c.ultima_vez.astimezone(ahora)
    vista: dict[str, Any] = {
        "tool": c.tool, "parametros": c.parametros,
        "fecha": local.date().isoformat(), "veces": c.veces,
    }
    original = zonas.valida(c.zona_horaria)
    if original and original != zona_actual:
        entonces = c.ultima_vez.astimezone(zonas.zona(original))
        if entonces.date() != local.date():
            vista["zona_original"] = original
            vista["fecha_en_zona_original"] = entonces.date().isoformat()
    return vista


async def ejecutar(
    ctx: Contexto, recientes: Recientes, lectura: set[str], parametros: dict, ahora: datetime | None = None
) -> ResultadoTool:
    """Solo se listan tools de lectura que el manifiesto ofrece HOY (`lectura`): una retirada, una
    escritura o una propuesta nunca aparecen."""
    errores = [e.message for e in _VALIDADOR.iter_errors(parametros)]
    if errores:
        return ResultadoTool(False, error="parametros_invalidos", detalle="; ".join(errores[:3]))
    ahora = ahora or datetime.now(UTC)
    dias = min(parametros.get("dias", ctx.retencion_dias), ctx.retencion_dias)
    limite = parametros.get("limite", LIMITE_DEFECTO)
    consultas = await recientes.consultas(ctx, lectura, ahora - timedelta(days=dias), limite)
    local = ahora.astimezone(zonas.zona(ctx.zona_horaria))
    return ResultadoTool(True, {
        "zona_horaria": ctx.zona_horaria,
        "hoy": local.date().isoformat(),
        "consultas": [a_vista(c, ctx.zona_horaria) for c in consultas],
        "nota": _NOTA,
    })
