"""Registro de proveedores de canal (strategy): `canal_mensajeria.proveedor` elige la clase."""

from collections.abc import Callable

import httpx

from asistente.core.canales.base import Canal
from asistente.core.canales.config import ConfigCanal
from asistente.core.canales.meta import CanalMeta
from asistente.core.canales.openwa import CanalOpenWA

PROVEEDORES = {"meta": CanalMeta, "openwa": CanalOpenWA}


def para(cfg: ConfigCanal | None, secreto: Callable[[str], str | None],
         http: httpx.AsyncClient | None) -> Canal | None:
    """El canal de un sistema (`cfg` = su `canal_mensajeria`), o None si no tiene o le faltan secretos.
    Barato: se arma en cada uso."""
    if cfg is None:
        return None
    return PROVEEDORES[cfg.proveedor].crear(cfg, secreto, http)
