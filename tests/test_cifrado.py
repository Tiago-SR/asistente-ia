import base64
import dataclasses

import pytest

from asistente.sistemas.cifrado import (
    Cifrado,
    Cifrador,
    ClaveAusente,
    DescifradoFallido,
    ErrorCifrado,
    generar_clave,
    huella,
)


def _clave(byte: int = 1) -> str:
    return base64.b64encode(bytes([byte]) * 32).decode()


def test_ida_y_vuelta():
    c = Cifrador.desde_texto(f"k1:{_clave()}")
    cif = c.cifrar("mock-a", "token_manifiesto", "s3creto")
    assert cif.kid == "k1" and b"s3creto" not in cif.cifrado
    assert c.descifrar("mock-a", "token_manifiesto", cif) == "s3creto"


def test_nonce_distinto_en_cada_cifrado():
    c = Cifrador.desde_texto(f"k1:{_clave()}")
    assert c.cifrar("a", "x", "v").nonce != c.cifrar("a", "x", "v").nonce


@pytest.mark.parametrize("sistema,campo", [("otro", "token_manifiesto"), ("mock-a", "auth_hs256")])
def test_aad_cruzada_falla(sistema, campo):
    c = Cifrador.desde_texto(f"k1:{_clave()}")
    cif = c.cifrar("mock-a", "token_manifiesto", "s3creto")
    with pytest.raises(DescifradoFallido):
        c.descifrar(sistema, campo, cif)


def test_texto_manipulado_falla():
    c = Cifrador.desde_texto(f"k1:{_clave()}")
    cif = c.cifrar("a", "x", "v")
    malo = dataclasses.replace(cif, cifrado=bytes([cif.cifrado[0] ^ 1]) + cif.cifrado[1:])
    with pytest.raises(DescifradoFallido):
        c.descifrar("a", "x", malo)


def test_rotacion():
    viejo = Cifrador.desde_texto(f"k1:{_clave(1)}")
    cif = viejo.cifrar("a", "x", "v")
    nuevo = Cifrador.desde_texto(f"k2:{_clave(2)},k1:{_clave(1)}")
    assert nuevo.kid_activo == "k2" and nuevo.necesita_rotar(cif)
    assert nuevo.descifrar("a", "x", cif) == "v"  # la vieja sigue sirviendo para descifrar
    rotado = nuevo.rotar("a", "x", cif)
    assert rotado.kid == "k2" and not nuevo.necesita_rotar(rotado)
    solo_nueva = Cifrador.desde_texto(f"k2:{_clave(2)}")
    assert solo_nueva.descifrar("a", "x", rotado) == "v"
    with pytest.raises(ClaveAusente):
        solo_nueva.descifrar("a", "x", cif)  # cifrado con k1, ya retirada


@pytest.mark.parametrize("texto", [None, "", " , "])
def test_sin_claves(texto):
    with pytest.raises(ClaveAusente):
        Cifrador.desde_texto(texto)


@pytest.mark.parametrize("texto", ["sin-separador", "k1:no es base64!", f"k1:{_clave()},k1:{_clave(2)}",
                                   "k1:" + base64.b64encode(b"corta").decode(), f"mal kid:{_clave()}"])
def test_claves_invalidas_no_reproducen_el_valor(texto):
    with pytest.raises(ErrorCifrado) as e:
        Cifrador.desde_texto(texto)
    assert "no es base64!" not in str(e.value)


def test_huella_y_generar_clave():
    assert len(huella("x")) == 4 and huella("x") == huella("x") and huella("x") != huella("y")
    assert len(base64.b64decode(generar_clave())) == 32
    assert isinstance(Cifrado("k", b"n", b"c"), Cifrado)
