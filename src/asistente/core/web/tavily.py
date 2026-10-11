"""Búsqueda y lectura de páginas con Tavily (`POST /search`, `POST /extract`). La clave vive solo en el servidor.

Leer con Tavily tiene una ventaja de seguridad: la página la descarga Tavily, no este servidor, así que una URL
maliciosa no llega a la red interna. La consulta y la URL salen al proveedor; no se guardan aquí más allá de la
auditoría de la tool.
"""

import logging

import httpx

from asistente.core.web.base import CupoAgotado, PaginaIlegible, PaginaWeb, ResultadoWeb, WebError

log = logging.getLogger(__name__)

BASE_URL = "https://api.tavily.com"
MAX_FRAGMENTO = 600


def _motivo(r: httpx.Response) -> str:
    """Mensaje de error de Tavily (`{"detail": {"error": …}}` o `{"detail": "…"}`), para el log."""
    try:
        d = r.json().get("detail")
        if isinstance(d, dict):
            d = d.get("error")
        return f" ({str(d)[:200]})" if d else ""
    except (ValueError, AttributeError):
        return ""


class WebTavily:
    nombre = "tavily"

    def __init__(
        self,
        api_key: str,
        *,
        base_url: str = BASE_URL,
        cliente: httpx.AsyncClient | None = None,
        timeout_s: float = 20.0,
    ) -> None:
        self._api_key = api_key
        self._base = base_url.rstrip("/")
        self._cliente = cliente or httpx.AsyncClient(follow_redirects=False)
        self._timeout = httpx.Timeout(timeout_s, connect=5.0)

    async def _post(self, ruta: str, cuerpo: dict) -> dict:
        try:
            r = await self._cliente.post(
                f"{self._base}{ruta}", json=cuerpo,
                headers={"Authorization": f"Bearer {self._api_key}"}, timeout=self._timeout,
            )
        except httpx.HTTPError as e:
            raise WebError(f"Tavily inaccesible: {type(e).__name__}") from e
        if r.status_code in (432, 433):  # cupo del plan o del pago por uso agotado
            raise CupoAgotado(f"Tavily sin cupo (HTTP {r.status_code}){_motivo(r)}")
        if r.status_code != 200:
            raise WebError(f"Tavily respondió HTTP {r.status_code}{_motivo(r)}")
        try:
            datos = r.json()
        except ValueError as e:
            raise WebError("Tavily devolvió una respuesta inválida") from e
        if not isinstance(datos, dict):
            raise WebError("Tavily devolvió una respuesta inválida")
        return datos

    async def buscar(self, consulta: str, *, max_resultados: int, idioma: str | None = None) -> list[ResultadoWeb]:
        datos = await self._post("/search", {
            "query": consulta, "search_depth": "basic", "max_results": max_resultados,
            "include_answer": False, "include_raw_content": False, "include_images": False,
        })
        resultados = datos.get("results")
        if not isinstance(resultados, list):
            raise WebError("Tavily devolvió una respuesta inválida")
        return [
            ResultadoWeb(str(r.get("title") or r["url"])[:200], r["url"],
                         str(r.get("content") or "")[:MAX_FRAGMENTO], r.get("published_date"))
            for r in resultados[:max_resultados]
            if isinstance(r, dict) and isinstance(r.get("url"), str) and r["url"].startswith(("http://", "https://"))
        ]

    async def leer(self, url: str, *, max_chars: int) -> PaginaWeb:
        datos = await self._post("/extract", {"urls": [url], "extract_depth": "basic", "format": "markdown"})
        resultados = datos.get("results")
        if not isinstance(resultados, list):
            raise WebError("Tavily devolvió una respuesta inválida")
        for r in resultados:
            if isinstance(r, dict) and isinstance(r.get("raw_content"), str):
                texto = r["raw_content"].strip()
                return PaginaWeb(url, None, texto[:max_chars], truncado=len(texto) > max_chars)
        fallos = datos.get("failed_results") or []
        error = fallos[0].get("error") if fallos and isinstance(fallos[0], dict) else None
        raise PaginaIlegible(f"Tavily no pudo leer la página{f' ({str(error)[:200]})' if error else ''}")
