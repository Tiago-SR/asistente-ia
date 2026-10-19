"""Lectura directa de una página, desde este servidor. Es el respaldo de `leer_pagina` cuando Tavily no está
disponible, y el único camino con riesgo de SSRF: la URL la eligió el modelo, que pudo leerla en una página hostil.

Defensas, en este orden:
1. Solo `http`/`https`, puertos 80/443, sin credenciales en la URL y con un nombre de host con punto
   (los servicios de Docker, `postgres` o `searxng`, no lo tienen). Ver `validar_url`.
2. El nombre se resuelve aquí y se rechaza si alguna dirección no es pública (privada, loopback, link-local,
   reservada, multicast). La conexión va a esa misma IP, con `Host` y SNI del nombre original: un DNS que cambie
   de respuesta entre la comprobación y la conexión (DNS rebinding) no lleva a otro lado.
3. Las redirecciones se siguen a mano, como máximo `max_redirecciones`, y cada salto pasa por 1 y 2.
4. Solo HTML o texto, como máximo `max_bytes`, con un tiempo máximo por petición.

Si la infraestructura lo permite, restringir además el egress del contenedor (regla 11 del README).
"""

import ipaddress
import re
from collections.abc import Awaitable, Callable
from html.parser import HTMLParser
from urllib.parse import urljoin, urlsplit, urlunsplit

import httpx

from asistente.core.red import ip_publica as _ip_publica
from asistente.core.red import resolver_dns as _resolver_dns
from asistente.core.web.base import NoSoportado, PaginaIlegible, PaginaWeb, UrlNoPermitida

PUERTOS = {"http": 80, "https": 443}
_SUFIJOS_INTERNOS = (".localhost", ".local", ".internal", ".lan", ".home", ".arpa")
_TIPOS = ("text/html", "application/xhtml+xml", "text/plain")
_REDIRECCIONES = {301, 302, 303, 307, 308}
UA = "Mozilla/5.0 (compatible; AsistenteLector/1.0)"

Resolver = Callable[[str, int], Awaitable[list[str]]]


def validar_url(url: str) -> str:
    """Comprobación estática (sin DNS) de que la URL apunta a un sitio público. Devuelve la URL sin fragmento.
    Lanza `UrlNoPermitida`."""
    try:
        p = urlsplit(url.strip())
        puerto = p.port
    except ValueError as e:
        raise UrlNoPermitida("URL inválida") from e
    if p.scheme not in PUERTOS:
        raise UrlNoPermitida("solo se leen páginas http o https")
    host = (p.hostname or "").rstrip(".").lower()
    if not host:
        raise UrlNoPermitida("URL sin host")
    if p.username is not None or p.password is not None:
        raise UrlNoPermitida("la URL no puede llevar usuario ni contraseña")
    if puerto is not None and puerto != PUERTOS[p.scheme]:
        raise UrlNoPermitida("solo se leen páginas en los puertos 80 y 443")
    try:
        ip = ipaddress.ip_address(host)
    except ValueError:
        if "." not in host or host == "localhost" or host.endswith(_SUFIJOS_INTERNOS):
            raise UrlNoPermitida("el host no es un sitio público") from None
    else:
        if not _ip_publica(ip):
            raise UrlNoPermitida("la dirección no es pública")
    return urlunsplit((p.scheme, p.netloc, p.path or "/", p.query, ""))


class _Texto(HTMLParser):
    """Texto legible de un HTML, sin scripts, estilos ni navegación. Suficiente para que el modelo lea."""

    _OMITIR = frozenset({"script", "style", "noscript", "svg", "template", "nav", "footer", "aside", "form", "iframe",
               "head", "button", "select"})
    _BLOQUE = frozenset({"p", "div", "br", "li", "ul", "ol", "tr", "table", "section", "article", "main", "header",
               "h1", "h2", "h3", "h4", "h5", "h6", "blockquote", "pre", "dd", "dt"})

    def __init__(self) -> None:
        super().__init__(convert_charrefs=True)
        self.partes: list[str] = []
        self.principal: list[str] = []  # lo que está dentro de <main> o <article>: sin menús ni listas de idiomas
        self.titulo: list[str] = []
        self._dentro = 0
        self._omitir = 0
        self._en_titulo = False

    def handle_starttag(self, tag, attrs):
        if tag == "title":
            self._en_titulo = True
        elif tag in self._OMITIR:
            self._omitir += 1
        elif tag in self._BLOQUE:
            self._agregar("\n")
        if tag in ("main", "article"):
            self._dentro += 1

    def _agregar(self, texto: str) -> None:
        self.partes.append(texto)
        if self._dentro:
            self.principal.append(texto)

    def handle_startendtag(self, tag, attrs):
        if tag == "br":
            self._agregar("\n")

    def handle_endtag(self, tag):
        if tag == "title":
            self._en_titulo = False
        elif tag in self._OMITIR and self._omitir:
            self._omitir -= 1
        elif tag in self._BLOQUE:
            self._agregar("\n")
        if tag in ("main", "article") and self._dentro:
            self._dentro -= 1

    def handle_data(self, data):
        if self._en_titulo:
            self.titulo.append(data)
        elif not self._omitir:
            self._agregar(data)


def texto_de_html(html: str) -> tuple[str | None, str]:
    p = _Texto()  # HTMLParser tolera el HTML roto: no lanza, lee lo que puede
    p.feed(html)
    p.close()
    principal = "".join(p.principal)
    cuerpo = principal if len(principal.strip()) >= 200 else "".join(p.partes)  # un <main> casi vacío no sirve
    lineas = (re.sub(r"[ \t\r\f\v\xa0]+", " ", linea).strip() for linea in cuerpo.split("\n"))
    texto = re.sub(r"\n{3,}", "\n\n", "\n".join(lineas)).strip()
    titulo = re.sub(r"\s+", " ", "".join(p.titulo)).strip() or None
    return titulo, texto


class LectorDirecto:
    nombre = "directo"

    def __init__(
        self,
        *,
        cliente: httpx.AsyncClient | None = None,
        resolver: Resolver = _resolver_dns,
        timeout_s: float = 10.0,
        max_bytes: int = 2_000_000,
        max_redirecciones: int = 3,
    ) -> None:
        self._cliente = cliente or httpx.AsyncClient(follow_redirects=False)
        self._resolver = resolver
        self._timeout = httpx.Timeout(timeout_s, connect=5.0)
        self._max_bytes = max_bytes
        self._max_red = max_redirecciones

    async def buscar(self, consulta: str, *, max_resultados: int, idioma: str | None = None):
        raise NoSoportado("el lector directo no busca")

    async def _destino(self, url: str) -> tuple[str, dict, dict]:
        """URL hacia la IP ya comprobada, cabeceras y extensiones (SNI) para pedir `url` sin volver a resolver."""
        p = urlsplit(url)
        host = p.hostname.rstrip(".").lower()
        puerto = p.port or PUERTOS[p.scheme]
        try:
            ips = [host] if ipaddress.ip_address(host) else []
        except ValueError:
            try:
                ips = await self._resolver(host, puerto)
            except OSError as e:
                raise PaginaIlegible(f"no se pudo resolver el host: {type(e).__name__}") from e
        if not ips:
            raise PaginaIlegible("el host no tiene direcciones")
        if not all(_ip_publica(ipaddress.ip_address(ip)) for ip in ips):
            raise UrlNoPermitida("el host resuelve a una dirección no pública")
        ip = ips[0]
        red = f"[{ip}]" if ":" in ip else ip
        destino = urlunsplit((p.scheme, red if p.port is None else f"{red}:{p.port}", p.path or "/", p.query, ""))
        return destino, {"Host": p.netloc.rsplit("@", 1)[-1], "User-Agent": UA,
                         "Accept": "text/html,application/xhtml+xml,text/plain;q=0.9",
                         "Accept-Encoding": "identity"}, (  # sin compresión: `max_bytes` acota lo que baja de la red
            {"sni_hostname": host} if p.scheme == "https" else {})

    async def leer(self, url: str, *, max_chars: int) -> PaginaWeb:
        actual = validar_url(url)
        for _ in range(self._max_red + 1):
            destino, cabeceras, ext = await self._destino(actual)
            try:
                async with self._cliente.stream("GET", destino, headers=cabeceras, extensions=ext,
                                                timeout=self._timeout) as r:
                    if r.status_code in _REDIRECCIONES:
                        siguiente = r.headers.get("location")
                        if not siguiente:
                            raise PaginaIlegible(f"redirección sin destino (HTTP {r.status_code})")
                        actual = validar_url(urljoin(actual, siguiente))
                        continue
                    if r.status_code != 200:
                        raise PaginaIlegible(f"la página respondió HTTP {r.status_code}")
                    tipo = r.headers.get("content-type", "").split(";")[0].strip().lower()
                    if tipo not in _TIPOS:
                        raise PaginaIlegible(f"la página no es HTML ni texto ({tipo or 'sin tipo'})")
                    cuerpo = bytearray()
                    async for trozo in r.aiter_bytes():
                        cuerpo += trozo
                        if len(cuerpo) >= self._max_bytes:
                            del cuerpo[self._max_bytes:]
                            break
                    crudo = bytes(cuerpo).decode(r.charset_encoding or "utf-8", errors="replace")
            except httpx.HTTPError as e:
                raise PaginaIlegible(f"no se pudo descargar la página: {type(e).__name__}") from e
            except LookupError:  # charset desconocido
                crudo = bytes(cuerpo).decode("utf-8", errors="replace")
            titulo, texto = texto_de_html(crudo) if tipo != "text/plain" else (None, crudo.strip())
            return PaginaWeb(actual, titulo, texto[:max_chars], truncado=len(texto) > max_chars)
        raise PaginaIlegible("demasiadas redirecciones")
