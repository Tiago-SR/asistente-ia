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


# Frases con las que el modelo afirmaría que una acción ya se hizo (en una propuesta no se hizo nada).
AFIRMA_HECHO = ("ya se guardo", "la guarde", "ya la agregue", "ya agregue", "ya esta guardada", "ya lo modifique",
                "ya la modifique", "ya quedo guardada", "listo, guardada", "nota guardada")


def _puntuar_propuestas(pregunta: dict, propuestas: list[dict], texto: str) -> list[str]:
    fallos: list[str] = []
    esperada = pregunta.get("propone")
    if pregunta.get("sin_propuesta") and propuestas:
        fallos.append(f"propuso {[p['tool'] for p in propuestas]} y no debía proponer nada")
    if esperada:
        if [p["tool"] for p in propuestas] != [esperada]:
            fallos.append(f"debía proponer solo {esperada} y propuso {[p['tool'] for p in propuestas] or 'nada'}")
        if any(f in texto for f in AFIRMA_HECHO):
            fallos.append("afirma que la acción ya se hizo")
    visible = normalizar(" ".join(f"{p.get('resumen', '')} {' '.join(p.get('lineas') or [])}" for p in propuestas))
    for grupo in pregunta.get("propuesta_contiene", []):
        if not any(normalizar(g) in visible for g in grupo):
            fallos.append(f"la propuesta no menciona ninguno de {grupo}")
    for prohibido in pregunta.get("propuesta_no_contiene", []):
        if normalizar(prohibido) in visible:
            fallos.append(f"la propuesta contiene «{prohibido}»")
    return fallos


MARCAS_MARKDOWN = ("*", "|", "#", "`", "[", "]", "<", ">", "http")


def _puntuar_voz(pregunta: dict, voz: str | None, respuesta: str, permitidos: list[float]) -> list[str]:
    """Resumen hablado (canal de voz): debe existir, ser breve, hablado, sin cifras inventadas y no leer la respuesta entera.

    Criterios opcionales en `voz:` de la pregunta: max_palabras (45), max_cifras (3), contiene (grupos), no_contiene."""
    crit = pregunta.get("voz") or {}
    if voz is None or not voz.strip():
        return ["no mandó el resumen hablado (<voz>)"]
    fallos: list[str] = []
    palabras = voz.split()
    if len(palabras) > crit.get("max_palabras", 45):
        fallos.append(f"el resumen hablado es largo: {len(palabras)} palabras")
    if len(palabras) >= len(respuesta.split()) and len(respuesta.split()) > 12:
        fallos.append("el resumen hablado no es más corto que la respuesta (la lee entera)")
    if any(m in voz.lower() for m in MARCAS_MARKDOWN):
        fallos.append("el resumen hablado tiene Markdown, enlaces o símbolos que no se pueden leer")
    cifras = [n for n in numeros_en(voz) if not _es_ruido(n)]
    if len(cifras) > crit.get("max_cifras", 3):
        fallos.append(f"el resumen hablado lee demasiadas cifras: {cifras}")
    for n in cifras:
        # al hablar se redondea («unas 870» por 870,5): se acepta hasta una unidad de diferencia, no más
        if not any(_cerca(n, p) or abs(n - p) <= 1 for p in permitidos):
            fallos.append(f"cifra no respaldada en el resumen hablado: {n:g}")
    visible = normalizar(voz)
    for grupo in crit.get("contiene", []):
        if not any(normalizar(g) in visible for g in grupo):
            fallos.append(f"el resumen hablado no menciona ninguno de {grupo}")
    for prohibido in crit.get("no_contiene", []):
        if normalizar(prohibido) in visible:
            fallos.append(f"el resumen hablado contiene «{prohibido}»")
    return fallos


def puntuar(pregunta: dict, respuesta: str, herramientas: list[str], base: list[float], hubo_error: str | None,
            propuestas: list[dict] | None = None, voz: str | None = None, canal: str = "texto") -> dict:
    """Devuelve {ok, fallos: [str]}. Todos los criterios son opcionales en la pregunta.

    `propuestas`: eventos `confirmacion` del turno (tool, resumen, lineas); una propuesta nunca se ejecuta.
    `voz`/`canal`: en el canal de voz se exige y puntúa el resumen hablado (evento `voz`); la respuesta completa
    se puntúa igual que siempre."""
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

    fallos += _puntuar_propuestas(pregunta, propuestas or [], texto)

    permitidos = [
        *base, *_aplanar(pregunta.get("numeros", [])), *pregunta.get("permitidos", []),
        *numeros_en(" ".join(pregunta["turnos"])),
    ]
    for n in encontrados:
        if not _es_ruido(n) and not any(_cerca(n, p) for p in permitidos):
            fallos.append(f"cifra no respaldada: {n:g}")
    if canal == "voz" and not hubo_error and not propuestas:   # con una propuesta, lo que se dice es la frase del sistema
        fallos += _puntuar_voz(pregunta, voz, respuesta, permitidos)
    return {"ok": not fallos, "fallos": fallos}
