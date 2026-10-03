import httpx
import pytest

from asistente.sistemas.manifiesto import (
    CacheManifiestos,
    ManifiestoInvalido,
    parsear_manifiesto,
)
from conftest import RAIZ


def tool(nombre="t", **cambios):
    t = {
        "nombre": nombre,
        "descripcion": "hace algo",
        "parametros": {"type": "object", "properties": {}},
        "efecto": "lectura",
    }
    t.update(cambios)
    return t


def manifiesto(*tools, **cambios):
    m = {"contrato": "1", "sistema": {"nombre": "S"}, "tools": list(tools)}
    m.update(cambios)
    return m


def test_valido():
    m = parsear_manifiesto(manifiesto(tool("a"), tool("b", efecto="escritura")))
    assert set(m.tools) == {"a", "b"}
    assert [t.nombre for t in m.tools_lectura()] == ["a"]


@pytest.mark.parametrize("version", ["2", None, 1])
def test_contrato_no_soportado(version):
    with pytest.raises(ManifiestoInvalido, match="contrato"):
        parsear_manifiesto(manifiesto(contrato=version))


def test_demasiadas_tools():
    with pytest.raises(ManifiestoInvalido, match="demasiadas"):
        parsear_manifiesto(manifiesto(*[tool(f"t{i}") for i in range(41)]))


@pytest.mark.parametrize(
    "malo",
    [
        tool("Mayuscula"),
        tool("1abc"),
        tool("a" * 65),
        tool(descripcion=""),
        tool(descripcion="x" * 1001),
        tool(efecto="otro"),
        tool(parametros={"type": "array"}),
        tool(parametros={"type": "object", "properties": {"x": {"type": "nada"}}}),
        tool(timeout_s=0),
        tool(timeout_s=500),
        tool(timeout_s=True),
        "no-es-objeto",
    ],
)
def test_tool_invalida_se_descarta_sin_tumbar_el_manifiesto(malo):
    m = parsear_manifiesto(manifiesto(tool("buena"), malo))
    assert list(m.tools) == ["buena"]


def test_nombres_duplicados_se_descartan_todos():
    m = parsear_manifiesto(manifiesto(tool("a"), tool("a"), tool("a"), tool("b")))
    assert list(m.tools) == ["b"]


def test_el_manifiesto_del_mock_cumple_el_schema_del_contrato(mock_a):
    import json

    import jsonschema

    schema = json.loads((RAIZ / "contrato/schemas/manifiesto.schema.json").read_text())
    jsonschema.validate(mock_a.MANIFIESTO, schema)
    assert len(parsear_manifiesto(mock_a.MANIFIESTO).tools) == 3


# --- cache y descarga contra el mock -------------------------------------------------


async def test_descarga_del_mock(registro_dos, cliente_mocks):
    cache = CacheManifiestos(registro_dos, cliente_mocks)
    m = await cache.obtener("mock-a")
    assert m.sistema_nombre == "MOCK-A"
    # el mock publica una tool de escritura: existe, pero no se expone
    assert "eliminar_establecimiento" in m.tools
    assert "eliminar_establecimiento" not in [t.nombre for t in m.tools_lectura()]


async def test_ttl_y_recarga(registro_dos, cliente_mocks):
    ahora = [0.0]
    llamadas = []

    class Contador(httpx.AsyncBaseTransport):
        async def handle_async_request(self, request):
            llamadas.append(request.url.path)
            return await cliente_mocks._transport.handle_async_request(request)

    async with httpx.AsyncClient(transport=Contador()) as c:
        cache = CacheManifiestos(registro_dos, c, reloj=lambda: ahora[0])
        await cache.obtener("mock-a")
        await cache.obtener("mock-a")
        assert len(llamadas) == 1
        ahora[0] = 3601  # TTL por defecto: 3600
        await cache.obtener("mock-a")
        assert len(llamadas) == 2
        await cache.recargar("mock-a")
        assert len(llamadas) == 3


async def test_credencial_de_manifiesto_incorrecta(registro_dos, cliente_mocks, monkeypatch):
    monkeypatch.setitem(registro_dos._env, "mock-a_MANIFEST", "otra-cosa")
    with pytest.raises(ManifiestoInvalido, match="401"):
        await CacheManifiestos(registro_dos, cliente_mocks).obtener("mock-a")


async def test_manifiesto_invalido_conserva_el_anterior(registro_dos):
    respuestas = [manifiesto(tool("a")), {"contrato": "9"}]

    def handler(request):
        return httpx.Response(200, json=respuestas.pop(0))

    async with httpx.AsyncClient(transport=httpx.MockTransport(handler)) as c:
        cache = CacheManifiestos(registro_dos, c)
        await cache.obtener("mock-a")
        m = await cache.recargar("mock-a")
        assert list(m.tools) == ["a"]


async def test_manifiesto_demasiado_grande(registro_dos):
    grande = manifiesto(tool("a", descripcion="x" * 900))
    grande["relleno"] = "y" * (300 * 1024)

    async with httpx.AsyncClient(
        transport=httpx.MockTransport(lambda r: httpx.Response(200, json=grande))
    ) as c:
        with pytest.raises(ManifiestoInvalido, match="grande"):
            await CacheManifiestos(registro_dos, c).obtener("mock-a")


async def test_no_sigue_redirecciones(registro_dos):
    visitas = []

    def handler(request):
        visitas.append(str(request.url))
        return httpx.Response(302, headers={"Location": "http://atacante/tools"})

    async with httpx.AsyncClient(transport=httpx.MockTransport(handler)) as c:
        with pytest.raises(ManifiestoInvalido):
            await CacheManifiestos(registro_dos, c).obtener("mock-a")
    assert len(visitas) == 1


async def test_sistema_desconocido(registro_dos, cliente_mocks):
    with pytest.raises(ManifiestoInvalido):
        await CacheManifiestos(registro_dos, cliente_mocks).obtener("nope")
