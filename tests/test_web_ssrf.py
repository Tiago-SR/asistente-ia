"""Defensas de SSRF del lector directo de páginas web (`validar_url`, resolución, redirecciones, tamaño)."""

import httpx
import pytest

from asistente.core.web.base import UrlNoPermitida, WebError
from asistente.core.web.directo import LectorDirecto, validar_url


def cliente(manejador) -> httpx.AsyncClient:
    return httpx.AsyncClient(transport=httpx.MockTransport(manejador), follow_redirects=False)


# ───────────────────────── Lector directo y SSRF ─────────────────────────

@pytest.mark.parametrize("url", [
    "http://localhost/", "http://127.0.0.1/", "http://10.0.0.5/", "http://192.168.1.1/", "http://172.17.0.1/",
    "http://169.254.169.254/latest/meta-data/", "http://[::1]/", "http://[::ffff:127.0.0.1]/", "http://0.0.0.0/",
    "https://a.com:8443/", "ftp://a.com/", "file:///etc/passwd", "https://user:pw@a.com/", "http://postgres:5432/",
    "http://searxng/", "http://app.internal/", "http://impresora.local/", "javascript:alert(1)", "http:///x",
])
def test_validar_url_rechaza_destinos_internos(url):
    with pytest.raises(UrlNoPermitida):
        validar_url(url)


def test_validar_url_acepta_un_sitio_publico_y_quita_el_fragmento():
    assert validar_url("https://Ejemplo.com/a?b=1#seccion") == "https://Ejemplo.com/a?b=1"
    assert validar_url("http://8.8.8.8") == "http://8.8.8.8/"


def resolver_fijo(tabla):
    async def resolver(host, puerto):
        return tabla[host]
    return resolver


async def test_lector_rechaza_un_host_que_resuelve_a_una_ip_privada():
    llamado = []
    lector = LectorDirecto(cliente=cliente(lambda r: llamado.append(r) or httpx.Response(200)),
                           resolver=resolver_fijo({"trampa.com": ["93.184.216.34", "10.0.0.1"]}))
    with pytest.raises(UrlNoPermitida):
        await lector.leer("https://trampa.com/", max_chars=100)
    assert llamado == []  # ni siquiera se conecta


async def test_lector_conecta_a_la_ip_comprobada_con_host_y_sni_originales():
    vistos = []

    def h(req: httpx.Request):
        vistos.append(req)
        html = ("<html><head><title>Soja hoy</title><script>robar()</script></head><body><nav>menú</nav>"
                "<h1>Precio</h1><p>La soja cotiza&nbsp;estable.</p><footer>pie</footer></body></html>")
        return httpx.Response(200, headers={"content-type": "text/html; charset=utf-8"}, content=html.encode())

    lector = LectorDirecto(cliente=cliente(h), resolver=resolver_fijo({"ejemplo.com": ["93.184.216.34"]}))
    p = await lector.leer("https://ejemplo.com/soja?x=1", max_chars=1000)
    req = vistos[0]
    assert req.url.host == "93.184.216.34" and req.url.path == "/soja" and req.url.query == b"x=1"
    assert req.headers["host"] == "ejemplo.com" and req.extensions["sni_hostname"] == "ejemplo.com"
    assert p.titulo == "Soja hoy" and "La soja cotiza estable." in p.texto and "Precio" in p.texto
    assert "robar" not in p.texto and "menú" not in p.texto and "pie" not in p.texto


async def test_lector_revisa_cada_redireccion():
    def h(req):
        return httpx.Response(302, headers={"location": "http://169.254.169.254/latest/meta-data/"})

    lector = LectorDirecto(cliente=cliente(h), resolver=resolver_fijo({"a.com": ["93.184.216.34"]}))
    with pytest.raises(UrlNoPermitida):
        await lector.leer("https://a.com/", max_chars=100)


async def test_lector_sigue_una_redireccion_publica_y_corta_las_infinitas():
    def h(req):
        if req.headers["host"] == "a.com":
            return httpx.Response(301, headers={"location": "https://b.com/destino"})
        return httpx.Response(200, headers={"content-type": "text/plain"}, content=b"hola")

    tabla = {"a.com": ["93.184.216.34"], "b.com": ["93.184.216.35"]}
    p = await LectorDirecto(cliente=cliente(h), resolver=resolver_fijo(tabla)).leer("https://a.com/", max_chars=100)
    assert p.url == "https://b.com/destino" and p.texto == "hola"
    bucle = lambda r: httpx.Response(302, headers={"location": "/otra"})
    with pytest.raises(WebError, match="redirecciones"):
        await LectorDirecto(cliente=cliente(bucle), resolver=resolver_fijo(tabla)).leer("https://a.com/", max_chars=9)


async def test_lector_rechaza_lo_que_no_es_html_y_limita_el_tamano():
    tabla = {"a.com": ["93.184.216.34"]}
    pdf = lambda r: httpx.Response(200, headers={"content-type": "application/pdf"}, content=b"%PDF")
    with pytest.raises(WebError, match="HTML"):
        await LectorDirecto(cliente=cliente(pdf), resolver=resolver_fijo(tabla)).leer("https://a.com/", max_chars=9)
    grande = lambda r: httpx.Response(200, headers={"content-type": "text/plain"}, content=b"a" * 5000)
    lector = LectorDirecto(cliente=cliente(grande), resolver=resolver_fijo(tabla), max_bytes=1000)
    p = await lector.leer("https://a.com/", max_chars=10_000)
    assert len(p.texto) == 1000


