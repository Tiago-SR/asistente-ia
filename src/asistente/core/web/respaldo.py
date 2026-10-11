"""Varios proveedores en orden: se usa el primero disponible y, si falla, el siguiente.

Un proveedor sin cupo (Tavily 432/433) se pausa `pausa_cupo_s` (por defecto 6 h): no tiene sentido gastar una
petición por consulta para enterarse de nuevo. Uno que falla por otra causa (red, 5xx, clave inválida) se pausa
`pausa_falla_s`. Una página que no se puede leer (`PaginaIlegible`) no pausa a nadie: es culpa de la página. Los
pausados se prueban igual, después de los demás: una pausa ordena, nunca deja sin búsqueda.
"""

import logging
import time
from collections.abc import Callable, Sequence

from asistente.core.web.base import (
    Busqueda,
    CupoAgotado,
    NoSoportado,
    PaginaIlegible,
    PaginaWeb,
    UrlNoPermitida,
    WebError,
)

log = logging.getLogger(__name__)


class WebConRespaldo:
    def __init__(
        self,
        proveedores: Sequence,
        *,
        pausa_cupo_s: float = 6 * 3600,
        pausa_falla_s: float = 60,
        reloj: Callable[[], float] = time.monotonic,
    ) -> None:
        if not proveedores:
            raise ValueError("hace falta al menos un proveedor")
        self._proveedores = list(proveedores)
        self._pausa_cupo, self._pausa_falla = pausa_cupo_s, pausa_falla_s
        self._reloj = reloj
        self._hasta: dict[str, float] = {}

    @property
    def nombres(self) -> list[str]:
        return [p.nombre for p in self._proveedores]

    def _orden(self) -> list:
        ahora = self._reloj()
        libres = [p for p in self._proveedores if self._hasta.get(p.nombre, 0) <= ahora]
        return libres + [p for p in self._proveedores if p not in libres]

    async def _probar(self, operacion: str, llamar):
        errores = []
        for p in self._orden():
            try:
                resultado = await llamar(p)
            except NoSoportado:
                continue
            except UrlNoPermitida:
                raise
            except PaginaIlegible as e:
                log.info("web: %s no pudo leer la página: %s", p.nombre, e)
                errores.append(p.nombre)
            except CupoAgotado as e:
                if self._hasta.get(p.nombre, 0) <= self._reloj():
                    log.warning("web: %s sin cupo; se pausa %d s y se usa el siguiente: %s",
                                p.nombre, self._pausa_cupo, e)
                self._hasta[p.nombre] = self._reloj() + self._pausa_cupo
                errores.append(p.nombre)
            except WebError as e:
                log.warning("web: %s falló en %s: %s", p.nombre, operacion, e)
                self._hasta[p.nombre] = self._reloj() + self._pausa_falla
                errores.append(p.nombre)
            else:
                self._hasta.pop(p.nombre, None)
                return p.nombre, resultado
        raise WebError(f"ningún proveedor pudo {operacion}" + (f" ({', '.join(errores)})" if errores else ""))

    async def buscar(self, consulta: str, *, max_resultados: int, idioma: str | None = None) -> Busqueda:
        nombre, resultados = await self._probar(
            "buscar", lambda p: p.buscar(consulta, max_resultados=max_resultados, idioma=idioma))
        return Busqueda(nombre, tuple(resultados))

    async def leer(self, url: str, *, max_chars: int) -> PaginaWeb:
        nombre, pagina = await self._probar("leer la página", lambda p: p.leer(url, max_chars=max_chars))
        return PaginaWeb(pagina.url, pagina.titulo, pagina.texto, pagina.truncado, proveedor=nombre)
