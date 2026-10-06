"""Resumen hablado del canal de voz.

En el canal `voz` el modelo abre su respuesta final con un bloque `<voz>…</voz>` (lo que se dice en voz
alta) y sigue con la respuesta completa (lo que se ve en el chat). `FiltroVoz` separa los dos en el flujo
de deltas: el bloque no llega nunca al texto visible ni se guarda en el historial.
"""

import re

ABRE, CIERRA = "<voz>", "</voz>"
MAX_RESUMEN = 600  # un bloque más largo que esto no es un resumen: se deja como texto normal

_BLOQUE = re.compile(r"^\s*<voz>(.*?)</voz>\s*", re.DOTALL)


def limpiar(texto: str) -> str:
    """El texto sin el bloque `<voz>` inicial (el que se guarda y se muestra)."""
    return _BLOQUE.sub("", texto, count=1)


def resumen_de(texto: str) -> str | None:
    m = _BLOQUE.match(texto)
    return m.group(1).strip() if m and m.group(1).strip() else None


class FiltroVoz:
    """Procesa deltas: `alimentar` devuelve (texto visible, resumen o None); `cerrar` libera lo retenido."""

    def __init__(self) -> None:
        self._estado = "inicio"  # inicio (decidiendo) | dentro (en el bloque) | despues (recortando) | fuera (texto normal)
        self._buf = ""

    def alimentar(self, trozo: str) -> tuple[str, str | None]:
        if self._estado == "fuera":
            return trozo, None
        if self._estado == "despues":  # los saltos de línea que separan el bloque del texto no se muestran
            trozo = trozo.lstrip()
            if trozo:
                self._estado = "fuera"
            return trozo, None
        self._buf += trozo
        if self._estado == "inicio":
            s = self._buf.lstrip()
            if len(s) < len(ABRE) and ABRE.startswith(s):
                return "", None  # todavía puede ser el comienzo de «<voz>»
            if not s.startswith(ABRE):
                return self._soltar(), None
            self._buf, self._estado = s[len(ABRE):], "dentro"
        fin = self._buf.find(CIERRA)
        if fin < 0:
            if len(self._buf) > MAX_RESUMEN:
                return self._soltar(ABRE), None
            return "", None
        resumen = self._buf[:fin].strip()
        resto = self._buf[fin + len(CIERRA):].lstrip()
        self._buf, self._estado = "", "fuera" if resto else "despues"
        return resto, resumen or None

    def cerrar(self) -> str:
        """Fin del flujo: si el bloque quedó abierto o la respuesta estaba vacía, se entrega lo retenido."""
        return self._soltar(ABRE if self._estado == "dentro" else "") if self._estado in ("inicio", "dentro") else ""

    def _soltar(self, prefijo: str = "") -> str:
        salida, self._buf, self._estado = prefijo + self._buf, "", "fuera"
        return salida
