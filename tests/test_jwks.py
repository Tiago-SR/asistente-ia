"""JWKS por httpx: caché, refresco por `kid` desconocido y el control de destinos del servicio."""

import json
import time

import httpx
import jwt
import pytest
from cryptography.hazmat.primitives.asymmetric import rsa
from jwt.algorithms import RSAAlgorithm

from asistente.core.red import ReglasRed, TransporteSeguro
from asistente.sistemas.auth import Autenticador, ClienteJwks, TokenInvalido
from conftest import entorno, entrada_sistema, escribir_registro, registro_desde_yaml


def _par(kid: str):
    privada = rsa.generate_private_key(public_exponent=65537, key_size=2048)
    jwk = json.loads(RSAAlgorithm.to_jwk(privada.public_key()))
    return privada, {**jwk, "kid": kid, "use": "sig", "alg": "RS256"}


def _token(privada, kid: str | None, iss: str = "acme") -> str:
    ahora = int(time.time())
    claims = {"iss": iss, "aud": "asistente", "sub": "ana", "iat": ahora, "exp": ahora + 300, "jti": "j1",
              "scope": "asistente:lectura"}
    return jwt.encode(claims, privada, algorithm="RS256", headers={"kid": kid} if kid else {})


class _Emisor:
    def __init__(self, claves: list[dict], estado: int = 200) -> None:
        self.claves, self.estado, self.pedidas = claves, estado, 0

    def __call__(self, request: httpx.Request) -> httpx.Response:
        self.pedidas += 1
        return httpx.Response(self.estado, json={"keys": self.claves})


def _cliente(emisor: _Emisor) -> httpx.AsyncClient:
    return httpx.AsyncClient(transport=httpx.MockTransport(emisor), follow_redirects=False)


async def test_clave_por_kid_y_cache():
    priv, jwk = _par("k1")
    emisor = _Emisor([jwk])
    c = ClienteJwks("https://acme.example/jwks", _cliente(emisor))
    assert await c.clave(_token(priv, "k1"))
    assert await c.clave(_token(priv, "k1"))
    assert emisor.pedidas == 1


async def test_kid_desconocido_refresca_una_vez_y_no_en_rafaga():
    priv, jwk = _par("k1")
    emisor = _Emisor([jwk])
    t = [0.0]
    c = ClienteJwks("https://acme.example/jwks", _cliente(emisor), reloj=lambda: t[0])
    await c.clave(_token(priv, "k1"))
    t[0] = 10.0
    with pytest.raises(jwt.PyJWKClientError):  # kid al azar dentro de los 30 s: no vuelve a descargar
        await c.clave(_token(priv, "otro"))
    assert emisor.pedidas == 1
    priv2, jwk2 = _par("k2")  # el emisor rotó la clave
    emisor.claves = [jwk, jwk2]
    t[0] = 40.0
    assert await c.clave(_token(priv2, "k2"))
    assert emisor.pedidas == 2


async def test_sin_kid_vale_si_hay_una_sola_clave():
    priv, jwk = _par("k1")
    c = ClienteJwks("https://acme.example/jwks", _cliente(_Emisor([jwk])))
    assert await c.clave(_token(priv, None))


@pytest.mark.parametrize("estado", [404, 500])
async def test_respuesta_de_error_es_clave_no_disponible(estado):
    priv, jwk = _par("k1")
    c = ClienteJwks("https://acme.example/jwks", _cliente(_Emisor([jwk], estado)))
    with pytest.raises(jwt.PyJWKClientError):
        await c.clave(_token(priv, "k1"))


async def test_jwks_demasiado_grande_se_rechaza():
    priv, jwk = _par("k1")
    relleno = [{**jwk, "kid": f"k{i}"} for i in range(1500)]
    c = ClienteJwks("https://acme.example/jwks", _cliente(_Emisor(relleno)))
    with pytest.raises(jwt.PyJWKClientError):
        await c.clave(_token(priv, "k1"))


def _autenticador(tmp_path, url: str, cliente: httpx.AsyncClient) -> Autenticador:
    ruta = escribir_registro(tmp_path / "s.yaml", [
        entrada_sistema("acme", auth={"algoritmo": "RS256", "jwks_url": url})])
    return Autenticador(registro_desde_yaml(ruta, env=entorno("acme")), cliente)


async def test_autenticador_valida_con_jwks(tmp_path):
    priv, jwk = _par("k1")
    a = _autenticador(tmp_path, "https://acme.example/jwks", _cliente(_Emisor([jwk])))
    u = await a.validar(_token(priv, "k1"))
    assert (u.sistema_id, u.usuario_ref) == ("acme", "ana")


async def test_jwks_en_red_privada_se_bloquea_con_el_transporte_seguro(tmp_path):
    priv, jwk = _par("k1")
    emisor = _Emisor([jwk])

    async def resolver(host: str, puerto: int) -> list[str]:
        return ["10.0.0.5"]

    seguro = TransporteSeguro(ReglasRed(), resolver=resolver, transporte=httpx.MockTransport(emisor))
    cliente = httpx.AsyncClient(transport=seguro, follow_redirects=False)
    a = _autenticador(tmp_path, "http://interno.ejemplo.com/jwks", cliente)
    with pytest.raises(TokenInvalido, match="clave de firma no disponible"):
        await a.validar(_token(priv, "k1"))
    assert emisor.pedidas == 0
