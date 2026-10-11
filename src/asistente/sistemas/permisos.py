"""Qué tools de un sistema puede usar el asistente.

Es el único sitio donde se decide: tanto la lista que se ofrece al modelo (`tools_de`) como la ejecución
(`_tool`) pasan por `tool_permitida`. Si un filtro viviera solo en uno de los dos, una tool oculta seguiría
siendo ejecutable por el otro. Para acotar por empresa o tenant más adelante, es la única función que se toca.
"""

from asistente.sistemas.manifiesto import Tool
from asistente.sistemas.registro import Sistema


def tool_permitida(sistema: Sistema, tool: Tool) -> bool:
    """Lectura: habilitada salvo excepción en `tool_estado`. Escritura: solo si es accionable (declara la
    confirmación y no es destructiva) y el operador la encendió, en `tool_estado` o en `acciones_habilitadas`."""
    estado = sistema.tool_estado.get(tool.nombre)
    if tool.efecto == "lectura":
        return estado is not False
    if not tool.accionable or estado is False:
        return False
    return estado is True or tool.nombre in sistema.acciones_habilitadas
