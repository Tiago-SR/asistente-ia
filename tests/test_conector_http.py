import httpx
import pytest

from asistente.sistemas.auth import Autenticador
from asistente.sistemas.conector_http import ConectorHttp
from asistente.sistemas.manifiesto import CacheManifiestos
from conftest import firmar


@pytest.fixture
def conector(registro_dos, cliente_mocks):
    return ConectorHttp(registro_dos, CacheManifiestos(registro_dos, cliente_mocks), cliente_mocks)


@pytest.fixture
def usuario(registro_dos):
    async def _u(sistema="mock-a", sub="ana", **claims):
        return await Autenticador(registro_dos).validar(firmar(sistema, sub, **claims))

    return _u


async def test_listar_devuelve_solo_datos_del_usuario(conector, usuario):
    r = await conector.ejecutar(await usuario(), "listar_establecimientos", {}, "r1")
    assert r.ok
    assert [e["nombre"] for e in r.datos["establecimientos"]] == ["El Matorral", "La Esperanza"]
    assert r.fuente == "establecimientos"
    assert r.ui and r.ui[0]["tipo"] == "navegar"


async def test_ui_no_llega_al_modelo(conector, usuario):
    r = await conector.ejecutar(await usuario(), "listar_establecimientos", {}, "r1")
    assert "ui" not in r.para_modelo()


async def test_aislamiento_entre_usuarios(conector, usuario):
    r = await conector.ejecutar(await usuario(sub="beto"), "resumen_establecimiento", {"id": "1"}, "r")
    assert not r.ok and r.error == "no_encontrado"  # el 1 es de ana


async def test_error_de_negocio(conector, usuario):
    r = await conector.ejecutar(await usuario(), "resumen_establecimiento", {"id": "999"}, "r")
    assert (r.ok, r.error) == (False, "no_encontrado")


async def test_parametros_invalidos_no_llegan_al_sistema(conector, usuario, cliente_mocks):
    llamadas = []
    original = cliente_mocks.post

    async def espia(*a, **k):
        llamadas.append(a)
        return await original(*a, **k)

    cliente_mocks.post = espia
    r = await conector.ejecutar(await usuario(), "resumen_establecimiento", {"id": 1}, "r")
    assert r.error == "parametros_invalidos"
    r = await conector.ejecutar(await usuario(), "resumen_establecimiento", {}, "r")
    assert r.error == "parametros_invalidos"
    r = await conector.ejecutar(await usuario(), "listar_establecimientos", {"extra": 1}, "r")
    assert r.error == "parametros_invalidos"
    assert llamadas == []


async def test_tool_de_escritura_nunca_se_ejecuta(conector, usuario, cliente_mocks):
    llamadas = []
    original = cliente_mocks.post

    async def espia(*a, **k):
        llamadas.append(a)
        return await original(*a, **k)

    cliente_mocks.post = espia
    r = await conector.ejecutar(await usuario(), "eliminar_establecimiento", {"id": "1"}, "r")
    assert r.error == "no_disponible"
    assert llamadas == []


async def test_tool_inexistente(conector, usuario):
    r = await conector.ejecutar(await usuario(), "no_existe", {}, "r")
    assert r.error == "no_disponible"


async def test_cada_sistema_solo_ve_su_base_url(registro_dos, cliente_mocks, usuario):
    pedidos = []

    class Espia(httpx.AsyncBaseTransport):
        async def handle_async_request(self, request):
            pedidos.append(request.url.host)
            return await cliente_mocks._transport.handle_async_request(request)

    async with httpx.AsyncClient(transport=Espia()) as c:
        con = ConectorHttp(registro_dos, CacheManifiestos(registro_dos, c), c)
        await con.ejecutar(await usuario("mock-b", "ana"), "listar_establecimientos", {}, "r")
    assert set(pedidos) == {"mock-b"}


async def test_envia_cabeceras_del_contrato(registro_dos, usuario):
    vistos = {}

    def handler(request):
        if request.method == "GET":
            return httpx.Response(200, json={
                "contrato": "1", "sistema": {"nombre": "S"},
                "tools": [{"nombre": "t", "descripcion": "d", "efecto": "lectura",
                           "parametros": {"type": "object"}}],
            })
        vistos.update(request.headers)
        vistos["body"] = request.content
        return httpx.Response(200, json={"ok": True, "datos": {}})

    async with httpx.AsyncClient(transport=httpx.MockTransport(handler)) as c:
        u = await usuario()
        await ConectorHttp(registro_dos, CacheManifiestos(registro_dos, c), c).ejecutar(
            u, "t", {}, "req-42"
        )
    assert vistos["authorization"] == f"Bearer {u.token}"
    assert vistos["x-asistente-contrato"] == "1"
    assert vistos["x-asistente-request-id"] == "req-42"
    assert vistos["body"] == b'{"parametros":{}}'


def _con_respuesta(registro, respuesta):
    """Conector cuyo sistema devuelve `respuesta(request)` al ejecutar la tool `t`."""

    def handler(request):
        if request.method == "GET":
            return httpx.Response(200, json={
                "contrato": "1", "sistema": {"nombre": "S"},
                "tools": [{"nombre": "t", "descripcion": "d", "efecto": "lectura",
                           "parametros": {"type": "object"}}],
            })
        return respuesta(request)

    c = httpx.AsyncClient(transport=httpx.MockTransport(handler))
    return ConectorHttp(registro, CacheManifiestos(registro, c), c)


@pytest.mark.parametrize(
    ("respuesta", "esperado"),
    [
        (lambda r: httpx.Response(401), "token_expirado"),
        (lambda r: httpx.Response(403), "sin_acceso"),
        (lambda r: httpx.Response(500), "error_sistema"),
        (lambda r: httpx.Response(302, headers={"Location": "http://otro/"}), "error_sistema"),
        (lambda r: httpx.Response(200, content=b"<html>"), "respuesta_invalida"),
        (lambda r: httpx.Response(200, json=[1]), "respuesta_invalida"),
        (lambda r: httpx.Response(200, json={"ok": "si"}), "respuesta_invalida"),
        (lambda r: httpx.Response(200, json={"ok": True}), "respuesta_invalida"),
        (lambda r: httpx.Response(200, json={"ok": False, "error": "raro"}), "respuesta_invalida"),
    ],
)
async def test_mapeo_de_errores(registro_dos, usuario, respuesta, esperado):
    r = await _con_respuesta(registro_dos, respuesta).ejecutar(await usuario(), "t", {}, "r")
    assert (r.ok, r.error) == (False, esperado)


async def test_timeout(registro_dos, usuario):
    def lento(request):
        raise httpx.ReadTimeout("lento", request=request)

    r = await _con_respuesta(registro_dos, lento).ejecutar(await usuario(), "t", {}, "r")
    assert r.error == "timeout"


async def test_error_de_red(registro_dos, usuario):
    def caido(request):
        raise httpx.ConnectError("no", request=request)

    r = await _con_respuesta(registro_dos, caido).ejecutar(await usuario(), "t", {}, "r")
    assert r.error == "error_sistema"


async def test_token_expirado_se_senala(registro_dos, usuario):
    r = await _con_respuesta(registro_dos, lambda r: httpx.Response(401)).ejecutar(
        await usuario(), "t", {}, "r"
    )
    assert r.token_expirado


async def test_respuesta_grande_se_trunca_y_se_avisa(registro_dos, usuario):
    grande = {"ok": True, "datos": {"filas": ["x" * 100] * 2000}}
    r = await _con_respuesta(registro_dos, lambda q: httpx.Response(200, json=grande)).ejecutar(
        await usuario(), "t", {}, "r"
    )
    assert r.ok and r.truncado
    assert len(str(r.datos)) < 51_000
    assert r.para_modelo()["truncado"] is True


async def test_ui_invalida_se_filtra(registro_dos, usuario):
    cuerpo = {"ok": True, "datos": {}, "ui": [{"tipo": "navegar", "url": "/x"}, {"tipo": "js"}, 5]}
    r = await _con_respuesta(registro_dos, lambda q: httpx.Response(200, json=cuerpo)).ejecutar(
        await usuario(), "t", {}, "r"
    )
    assert r.ui == [{"tipo": "navegar", "url": "/x"}]
