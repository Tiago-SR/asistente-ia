"""Tarifas de los modelos (USD por millón de tokens) y costo de un consumo.

`config/precios.yaml` es la única fuente: la usan el informe de costo del admin y los evals.
La tarifa depende del horario del proveedor (valle/pico) y el servicio no sabe en cuál cayó cada
llamada, así que se informan las dos cifras como cota inferior y superior.
"""

from pathlib import Path

import yaml

HORARIOS = ("valle", "pico")


def cargar(ruta: str | Path) -> dict[str, dict]:
    """Tarifas por modelo. Sin archivo (o sin tarifa para un modelo) el costo queda sin calcular."""
    p = Path(ruta)
    if not p.is_file():
        return {}
    return yaml.safe_load(p.read_text(encoding="utf-8")) or {}


def costo(tokens_in: int, tokens_in_cache: int, tokens_out: int, tarifa: dict | None, horario: str) -> float | None:
    """USD de un consumo. `tokens_in_cache` es la parte de `tokens_in` servida desde la caché."""
    if not tarifa:
        return None
    return (
        (tokens_in - tokens_in_cache) * tarifa["entrada_cache_miss"][horario]
        + tokens_in_cache * tarifa["entrada_cache_hit"][horario]
        + tokens_out * tarifa["salida"][horario]
    ) / 1e6
