import base64
import json

import pytest

from asistente.sistemas.auth import Autenticador, TokenInvalido
from asistente.sistemas.registro import RegistroSistemas
from conftest import entorno, entrada_sistema, escribir_registro, firmar


@pytest.fixture
def auth(registro_dos):
    return Autenticador(registro_dos)


async def test_token_valido(auth):
    u = await auth.validar(firmar("mock-a", nombre="Ana", tenants=["t1"], locale="es-UY"))
    assert (u.sistema_id, u.usuario_ref, u.nombre, u.tenants, u.locale) == (
        "mock-a", "ana", "Ana", ("t1",), "es-UY",
    )


async def test_locale_del_token_o_el_defecto_del_sistema(tmp_path):
    ruta = escribir_registro(tmp_path / "s.yaml", [
        entrada_sistema("mock-a", locale_defecto="es-AR"), entrada_sistema("mock-b")])
    a = Autenticador(RegistroSistemas(ruta, env=entorno("mock-a", "mock-b")))
    assert (await a.validar(firmar("mock-a"))).locale == "es-AR"                    # el token no lo trae
    assert (await a.validar(firmar("mock-a", locale="pt-BR"))).locale == "pt-BR"    # el token manda
    assert (await a.validar(firmar("mock-b"))).locale is None                       # sin defecto


async def test_token_de_a_no_sirve_firmado_con_clave_de_b(auth):
    # iss = a, pero firmado con el secreto de b
    t = firmar("mock-a", _clave="secreto-mock-b-" + "x" * 32)
    with pytest.raises(TokenInvalido):
        await auth.validar(t)


async def test_iss_desconocido(auth):
    with pytest.raises(TokenInvalido, match="emisor desconocido"):
        await auth.validar(firmar("otro", _clave="k" * 40))


async def test_sistema_deshabilitado_igual_que_desconocido(tmp_path):
    from asistente.sistemas.registro import RegistroSistemas
    from conftest import entorno, entrada_sistema, escribir_registro

    r = RegistroSistemas(
        escribir_registro(tmp_path / "s.yaml", [entrada_sistema("a", habilitado=False)]),
        env=entorno("a"),
    )
    with pytest.raises(TokenInvalido, match="emisor desconocido"):
        await Autenticador(r).validar(firmar("a"))


async def test_vencido_marca_expirado(auth):
    with pytest.raises(TokenInvalido) as e:
        await auth.validar(firmar("mock-a", iat=1, exp=100))
    assert e.value.expirado


async def test_tolerancia_de_reloj(auth):
    import time

    # vencido hace 10 s: dentro de la tolerancia de 30 s
    await auth.validar(firmar("mock-a", exp=int(time.time()) - 10))


async def test_audiencia_incorrecta(auth):
    with pytest.raises(TokenInvalido):
        await auth.validar(firmar("mock-a", aud="otra"))


@pytest.mark.parametrize("faltante", ["sub", "jti", "exp", "iat", "scope", "aud"])
async def test_claims_obligatorios(auth, faltante):
    with pytest.raises(TokenInvalido):
        await auth.validar(firmar("mock-a", **{faltante: None}))


async def test_scope_distinto(auth):
    with pytest.raises(TokenInvalido, match="scope"):
        await auth.validar(firmar("mock-a", scope="asistente:escritura"))


def _b64(d: dict) -> str:
    return base64.urlsafe_b64encode(json.dumps(d).encode()).rstrip(b"=").decode()


async def test_alg_none_rechazado(auth):
    claims = {"iss": "mock-a", "aud": "asistente", "sub": "ana", "iat": 1, "exp": 9999999999,
              "jti": "x", "scope": "asistente:lectura"}
    token = f"{_b64({'alg': 'none', 'typ': 'JWT'})}.{_b64(claims)}."
    with pytest.raises(TokenInvalido):
        await auth.validar(token)


async def test_algoritmo_distinto_al_configurado(auth):
    import jwt

    t = jwt.encode(
        {"iss": "mock-a", "aud": "asistente", "sub": "ana", "iat": 1, "exp": 9999999999,
         "jti": "x", "scope": "asistente:lectura"},
        "secreto-mock-a-" + "x" * 32,
        algorithm="HS512",
    )
    with pytest.raises(TokenInvalido):
        await auth.validar(t)


async def test_basura(auth):
    for t in ["", "abc", "a.b.c"]:
        with pytest.raises(TokenInvalido):
            await auth.validar(t)
