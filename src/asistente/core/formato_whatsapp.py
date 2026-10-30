"""Markdown → texto que WhatsApp dibuja bien. Red de seguridad: el prompt (`prompts/whatsapp.md`) ya pide este formato."""

import re

_ENCABEZADO = re.compile(r"^\s{0,3}#{1,6}\s+(.+?)\s*#*\s*$")
_VINETA = re.compile(r"^(\s*)[*+-]\s+")
_NEGRITA = re.compile(r"\*\*(.+?)\*\*|__(.+?)__")
_ENLACE = re.compile(r"\[([^\]]+)\]\((https?://[^)\s]+)\)")
_SEPARADOR = re.compile(r"^\s*\|?\s*:?-{2,}:?\s*(\|\s*:?-{2,}:?\s*)*\|?\s*$")


def _celdas(linea: str) -> list[str]:
    return [c.strip() for c in linea.strip().strip("|").split("|")]


def _tabla(filas: list[str]) -> list[str]:
    """Una tabla se vuelve una lista: `- <primera celda>: <col> <valor>, ...` (con 2 columnas, `- a: b`)."""
    datos = [_celdas(f) for f in filas if not _SEPARADOR.match(f)]
    if len(datos) < 2:
        return [" ".join(c for d in datos for c in d)]
    cab, *cuerpo = datos
    salida = []
    for fila in cuerpo:
        resto = [f"{h} {v}".strip() if len(cab) > 2 else v for h, v in zip(cab[1:], fila[1:]) if v]
        salida.append(f"- {fila[0]}" + (f": {', '.join(resto)}" if resto else ""))
    return salida


def a_whatsapp(texto: str) -> str:
    salida, tabla, codigo = [], [], False
    for linea in texto.splitlines() + [""]:
        if linea.lstrip().startswith("```"):
            codigo = not codigo
        if not codigo and linea.lstrip().startswith("|") and linea.count("|") >= 2:
            tabla.append(linea)
            continue
        if tabla:
            salida += _tabla(tabla)
            tabla = []
        if codigo or linea.lstrip().startswith("```"):
            salida.append(linea)
            continue
        linea = _ENCABEZADO.sub(r"*\1*", linea)
        linea = _VINETA.sub(r"\1- ", linea)
        linea = _ENLACE.sub(r"\1 (\2)", linea)
        salida.append(_NEGRITA.sub(lambda m: f"*{m.group(1) or m.group(2)}*", linea))
    return "\n".join(salida[:-1]).strip()
