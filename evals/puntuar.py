"""Puntuación de una respuesta contra lo esperado. Funciones puras, sin red (probadas en tests/test_evals.py)."""

import re
import unicodedata

TOLERANCIA = 0.051  # 75.87 y 75.9 son la misma cifra; 76 no
_NUM = re.compile(r"\d[\d.,]*")


def normalizar(texto: str) -> str:
    sin_tildes = unicodedata.normalize("NFKD", texto.lower())
    return re.sub(r"\s+", " ", "".join(c for c in sin_tildes if not unicodedata.combining(c)))


def _a_numero(token: str) -> float | None:
    t = token.rstrip(".,")
    if not t:
        return None
    if "." in t and "," in t:  # el último separador es el decimal
        dec = "," if t.rfind(",") > t.rfind(".") else "."
        t = t.replace("," if dec == "." else ".", "").replace(dec, ".")
    else:
        for sep in (",", "."):
            if sep in t:
                partes = t.split(sep)
                miles = len(partes) > 2 or len(partes[-1]) == 3
                t = "".join(partes) if miles else ".".join(partes)
    try:
        return float(t)
    except ValueError:
        return None


def numeros_en(texto: str) -> list[float]:
    return [n for tok in _NUM.findall(texto) if (n := _a_numero(tok)) is not None]


def _cerca(a: float, b: float) -> bool:
    return abs(a - b) <= TOLERANCIA


def _aparece(esperado, encontrados: list[float]) -> bool:
    """`esperado` es un número o una lista de alternativas aceptables."""
    alternativas = esperado if isinstance(esperado, list) else [esperado]
    return any(_cerca(a, n) for a in alternativas for n in encontrados)


def _aplanar(valores) -> list[float]:
    return [x for v in valores for x in (v if isinstance(v, list) else [v])]


def _es_ruido(n: float) -> bool:
    """Enteros chicos (conteos, ids, numeración de listas) y años no cuentan como cifras."""
    return (n == int(n) and 0 <= n <= 10) or (1900 <= n <= 2100 and n == int(n))


def puntuar(pregunta: dict, respuesta: str, herramientas: list[str], base: list[float], hubo_error: str | None) -> dict:
    """Devuelve {ok, fallos: [str]}. Todos los criterios son opcionales en la pregunta."""
    fallos: list[str] = []
    if hubo_error:
        fallos.append(f"error del servicio: {hubo_error}")
    if not respuesta.strip():
        fallos.append("respuesta vacía")
    texto = normalizar(respuesta)
    encontrados = numeros_en(respuesta)

    for t in pregunta.get("tools_requeridas", []):
        if t not in herramientas:
            fallos.append(f"no llamó a la tool {t}")
    for t in pregunta.get("tools_prohibidas", []):
        if t in herramientas:
            fallos.append(f"llamó a la tool prohibida {t}")
    for esperado in pregunta.get("numeros", []):
        if not _aparece(esperado, encontrados):
            fallos.append(f"falta la cifra {esperado}")
    for prohibido in pregunta.get("sin_numeros", []):
        if _aparece(prohibido, encontrados):
            fallos.append(f"aparece la cifra prohibida {prohibido}")
    for grupo in pregunta.get("contiene", []):
        if not any(normalizar(g) in texto for g in grupo):
            fallos.append(f"no menciona ninguno de {grupo}")
    for prohibido in pregunta.get("no_contiene", []):
        if normalizar(prohibido) in texto:
            fallos.append(f"contiene «{prohibido}»")

    permitidos = [
        *base, *_aplanar(pregunta.get("numeros", [])), *pregunta.get("permitidos", []),
        *numeros_en(" ".join(pregunta["turnos"])),
    ]
    for n in encontrados:
        if not _es_ruido(n) and not any(_cerca(n, p) for p in permitidos):
            fallos.append(f"cifra no respaldada: {n:g}")
    return {"ok": not fallos, "fallos": fallos}
