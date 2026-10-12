"""Control anti-SSRF de los destinos salientes (`core/red.py`)."""

import ipaddress

import httpx
import pytest

from asistente.core.red import DestinoNoPermitido, ReglasRed, TransporteSeguro, denegada, ip_publica


def _ip(s: str):
    return ipaddress.ip_address(s)


@pytest.mark.parametrize("ip,publica", [
    ("8.8.8.8", True),
    ("2606:4700:4700::1111", True),
    ("10.0.0.5", False),
    ("172.18.0.3", False),
    ("192.168.1.10", False),
    ("127.0.0.1", False),
    ("::1", False),
    ("100.64.0.1", False),            # CGNAT
    ("::ffff:127.0.0.1", False),      # IPv4 mapeada
    ("::ffff:10.0.0.1", False),
    ("::ffff:8.8.8.8", True),
    ("64:ff9b::a00:1", False),        # NAT64 de 10.0.0.1
    ("64:ff9b::808:808", True),       # NAT64 de 8.8.8.8
    ("2002:7f00:1::", False),         # 6to4 de 127.0.0.1
    ("169.254.169.254", False),
    ("224.0.0.1", False),
])
def test_ip_publica(ip, publica):
    assert ip_publica(_ip(ip)) is publica


@pytest.mark.parametrize("ip", ["169.254.169.254", "100.100.100.200", "0.0.0.0", "fd00:ec2::254", "fe80::1",
                                "::ffff:169.254.169.254", "64:ff9b::a9fe:a9fe", "224.0.0.251"])
def test_denegacion_fija(ip):
    assert denegada(_ip(ip))


def test_reglas_desde_texto_separa_nombres_y_redes():
    r = ReglasRed.desde_texto("Mock-A, host.docker.internal ,10.0.5.0/24,", extra_nombres=["llm.interno"])
    assert r.nombres == {"mock-a", "host.docker.internal", "llm.interno"}
    assert [str(n) for n in r.redes] == ["10.0.5.0/24"]


def test_lista_de_permitidos_habilita_privadas_pero_nunca_lo_denegado():
    r = ReglasRed.desde_texto("mock-a,169.254.0.0/16,10.0.5.0/24,127.0.0.1")
    assert r.permite("mock-a", [_ip("172.18.0.7")])             # nombre de la lista: IP privada cualquiera
    assert r.permite("otro", [_ip("10.0.5.9")])                  # red de la lista
    assert not r.permite("otro", [_ip("10.0.6.9")])              # fuera de la red
    assert not r.permite("mock-a", [_ip("169.254.169.254")])     # el nombre permitido no salva a los metadatos
    assert not r.permite("otro", [_ip("169.254.169.254")])       # ni una red CIDR que los incluya
    assert not r.permite("otro", [_ip("8.8.8.8"), _ip("10.0.6.9")])  # todas las IPs deben valer
    assert r.permite("api.ejemplo.com", [_ip("8.8.8.8")])
    assert not ReglasRed().permite("localhost", [_ip("127.0.0.1")])  # loopback solo si se pide expresamente
    assert not ReglasRed().permite("x", [])


def _transporte(reglas: ReglasRed, tabla: dict[str, list[str]], vistas: list[httpx.Request] | None = None):
    llamadas: list[str] = []

    async def resolver(host: str, puerto: int) -> list[str]:
        llamadas.append(host)
        if host not in tabla:
            raise OSError("no resuelve")
        return tabla[host]

    def interno(request: httpx.Request) -> httpx.Response:
        if vistas is not None:
            vistas.append(request)
        return httpx.Response(200, json={"ok": True})

    t = TransporteSeguro(reglas, resolver=resolver, transporte=httpx.MockTransport(interno))
    return httpx.AsyncClient(transport=t, follow_redirects=False), llamadas


async def test_conecta_a_la_ip_validada_con_host_y_sni_originales():
    vistas: list[httpx.Request] = []
    c, _ = _transporte(ReglasRed(), {"api.ejemplo.com": ["93.184.216.34"]}, vistas)
    async with c:
        r = await c.post("https://api.ejemplo.com/v1/x?a=1", json={"k": 1}, headers={"Authorization": "Bearer t"})
    assert r.status_code == 200
    v = vistas[0]
    assert v.url.host == "93.184.216.34" and v.url.path == "/v1/x" and v.url.query == b"a=1"
    assert v.headers["host"] == "api.ejemplo.com" and v.headers["authorization"] == "Bearer t"
    assert v.extensions["sni_hostname"] == "api.ejemplo.com"


@pytest.mark.parametrize("destino,tabla", [
    ("http://169.254.169.254/latest/meta-data", {}),
    ("http://127.0.0.1:8000/admin/api/sistemas", {}),
    ("http://[::1]:8000/", {}),
    ("http://[::ffff:10.0.0.1]/", {}),
    ("http://interno.ejemplo.com/", {"interno.ejemplo.com": ["10.0.0.5"]}),           # DNS a privada
    ("http://mixto.ejemplo.com/", {"mixto.ejemplo.com": ["93.184.216.34", "10.0.0.5"]}),  # una sola mala basta
    ("http://metadatos.ejemplo.com/", {"metadatos.ejemplo.com": ["169.254.169.254"]}),
    ("http://mock-a:8000/", {"mock-a": ["172.18.0.3"]}),                               # sin lista: bloqueado
])
async def test_destinos_no_publicos_se_rechazan_sin_conectar(destino, tabla):
    vistas: list[httpx.Request] = []
    c, _ = _transporte(ReglasRed(), tabla, vistas)
    async with c:
        with pytest.raises(DestinoNoPermitido):
            await c.get(destino)
    assert vistas == []


async def test_nombre_de_docker_en_la_lista_pasa_pero_los_metadatos_no():
    vistas: list[httpx.Request] = []
    reglas = ReglasRed.desde_texto("mock-a,rebinding")
    c, _ = _transporte(reglas, {"mock-a": ["172.18.0.3"], "rebinding": ["169.254.169.254"]}, vistas)
    async with c:
        assert (await c.get("http://mock-a:8000/manifiesto")).status_code == 200
        with pytest.raises(DestinoNoPermitido):
            await c.get("http://rebinding/")
    assert len(vistas) == 1 and vistas[0].url.host == "172.18.0.3" and vistas[0].url.port == 8000
    assert vistas[0].headers["host"] == "mock-a:8000"
    assert "sni_hostname" not in vistas[0].extensions  # http: sin SNI


async def test_se_resuelve_en_cada_peticion_y_la_conexion_usa_lo_validado():
    """DNS rebinding: el nombre resuelve una vez por petición y esa misma respuesta es a la que se conecta."""
    vistas: list[httpx.Request] = []
    tabla = {"cambia.ejemplo.com": ["93.184.216.34"]}
    c, llamadas = _transporte(ReglasRed(), tabla, vistas)
    async with c:
        await c.get("https://cambia.ejemplo.com/")
        tabla["cambia.ejemplo.com"] = ["10.0.0.5"]  # el atacante cambia la respuesta
        with pytest.raises(DestinoNoPermitido):
            await c.get("https://cambia.ejemplo.com/")
    assert llamadas == ["cambia.ejemplo.com", "cambia.ejemplo.com"]
    assert [v.url.host for v in vistas] == ["93.184.216.34"]


async def test_un_nombre_que_no_resuelve_es_error_de_conexion_normal():
    c, _ = _transporte(ReglasRed(), {})
    async with c:
        with pytest.raises(httpx.ConnectError) as e:
            await c.get("https://no-existe.ejemplo.com/")
    assert not isinstance(e.value, DestinoNoPermitido)


async def test_esquemas_que_no_son_http_se_rechazan():
    c, _ = _transporte(ReglasRed(), {})
    async with c:
        with pytest.raises((DestinoNoPermitido, httpx.UnsupportedProtocol)):
            await c.get("ftp://8.8.8.8/")


async def test_el_mensaje_de_error_no_incluye_ips_resueltas():
    c, _ = _transporte(ReglasRed(), {"x.ejemplo.com": ["10.1.2.3"]})
    async with c:
        with pytest.raises(DestinoNoPermitido) as e:
            await c.get("http://x.ejemplo.com/")
    assert "10.1.2.3" not in str(e.value)
