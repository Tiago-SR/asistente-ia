"""Búsqueda con una instancia propia de SearXNG (`GET /search?format=json`). Gratis y sin clave, pero depende de
que los buscadores que consulta por dentro no bloqueen la IP del servidor: puede fallar sin aviso. No lee páginas.

El formato JSON viene apagado en una instalación nueva: hay que agregarlo a `search.formats` en `settings.yml`
(ver `config/searxng/settings.yml`). Sin él la instancia responde 403.
"""

import httpx

from asistente.core.web.base import NoSoportado, PaginaWeb, ResultadoWeb, WebError
from asistente.core.web.tavily import MAX_FRAGMENTO


class WebSearxng:
    nombre = "searxng"

    def __init__(self, base_url: str, *, cliente: httpx.AsyncClient | None = None, timeout_s: float = 15.0) -> None:
        self._base = base_url.rstrip("/")
        self._cliente = cliente or httpx.AsyncClient(follow_redirects=False)
        self._timeout = httpx.Timeout(timeout_s, connect=5.0)

    async def buscar(self, consulta: str, *, max_resultados: int, idioma: str | None = None) -> list[ResultadoWeb]:
        params = {"q": consulta, "format": "json", "safesearch": "1"}
        if idioma:
            params["language"] = idioma
        try:
            r = await self._cliente.get(f"{self._base}/search", params=params, timeout=self._timeout)
        except httpx.HTTPError as e:
            raise WebError(f"SearXNG inaccesible: {type(e).__name__}") from e
        if r.status_code == 403:
            raise WebError("SearXNG rechazó el formato JSON (falta `json` en search.formats de settings.yml)")
        if r.status_code != 200:
            raise WebError(f"SearXNG respondió HTTP {r.status_code}")
        try:
            resultados = r.json()["results"]
        except (ValueError, KeyError, TypeError) as e:
            raise WebError("SearXNG devolvió una respuesta inválida") from e
        if not isinstance(resultados, list):
            raise WebError("SearXNG devolvió una respuesta inválida")
        vistos, salida = set(), []
        for x in resultados:
            url = x.get("url") if isinstance(x, dict) else None
            if not isinstance(url, str) or not url.startswith(("http://", "https://")) or url in vistos:
                continue
            vistos.add(url)
            salida.append(ResultadoWeb(str(x.get("title") or url)[:200], url,
                                       str(x.get("content") or "")[:MAX_FRAGMENTO], x.get("publishedDate")))
            if len(salida) >= max_resultados:
                break
        if not salida and resultados == []:
            # Sin resultados puede ser real o que todos los buscadores internos fallaron (bloqueo, captcha).
            caidos = r.json().get("unresponsive_engines") or []
            if caidos:
                raise WebError(f"SearXNG sin respuesta de sus buscadores ({len(caidos)} caídos)")
        return salida

    async def leer(self, url: str, *, max_chars: int) -> PaginaWeb:
        raise NoSoportado("SearXNG no lee páginas")
