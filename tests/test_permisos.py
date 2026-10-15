import pytest

from asistente.sistemas.auth import Autenticador
from asistente.sistemas.manifiesto import Tool
from asistente.sistemas.permisos import tool_permitida
from asistente.sistemas.registro import Sistema, desde_yaml
from conftest import entorno, entrada_sistema


def _sistema(destructivas_aprobadas=None, **cambios) -> Sistema:
    config, _ = desde_yaml(entrada_sistema("a", **cambios), entorno("a"))
    # No viene del YAML (`desde_yaml` lo rechaza): lo pone el registro desde la BD.
    return Sistema.model_validate({**config, "destructivas_aprobadas": destructivas_aprobadas or {}})


LECTURA = Tool("ver", "d", {}, "lectura")
ESCRITURA = Tool("agregar", "d", {}, "escritura", confirmacion_ttl_s=120)
SIN_CONFIRMACION = Tool("agregar", "d", {}, "escritura")
DESTRUCTIVA = Tool("agregar", "d", {}, "escritura", confirmacion_ttl_s=120, destructiva=True)


@pytest.mark.parametrize("cambios,tool,esperado", [
    ({}, LECTURA, True),  # lectura: habilitada por defecto
    ({"tool_estado": {"ver": False}}, LECTURA, False),
    ({"tool_estado": {"otra": False}}, LECTURA, True),
    ({}, ESCRITURA, False),  # escritura: apagada por defecto
    ({"acciones_habilitadas": ["agregar"]}, ESCRITURA, True),
    ({"tool_estado": {"agregar": True}}, ESCRITURA, True),
    ({"tool_estado": {"agregar": False}, "acciones_habilitadas": ["agregar"]}, ESCRITURA, False),
    ({"tool_estado": {"agregar": True}}, SIN_CONFIRMACION, False),  # encenderla no salta las reglas del contrato
    ({"tool_estado": {"agregar": True}}, DESTRUCTIVA, False),  # sin huella aprobada
    ({"acciones_habilitadas": ["agregar"]}, DESTRUCTIVA, False),
    ({"acciones_habilitadas": ["agregar"], "destructivas_aprobadas": {"agregar": DESTRUCTIVA.huella}}, DESTRUCTIVA, False),
    ({"tool_estado": {"agregar": True}, "destructivas_aprobadas": {"agregar": DESTRUCTIVA.huella}}, DESTRUCTIVA, True),
    ({"tool_estado": {"agregar": True}, "destructivas_aprobadas": {"agregar": "otra"}}, DESTRUCTIVA, False),
    ({"tool_estado": {"agregar": False}, "destructivas_aprobadas": {"agregar": DESTRUCTIVA.huella}}, DESTRUCTIVA, False),
])
def test_tool_permitida(cambios, tool, esperado):
    assert tool_permitida(_sistema(**cambios), tool) is esperado


def test_jwks_se_recrea_si_cambia_la_url_y_se_puede_invalidar():
    a = Autenticador(registro=None)  # type: ignore[arg-type]
    c1 = a._cliente_jwks("s", "http://uno/jwks")
    assert a._cliente_jwks("s", "http://uno/jwks") is c1
    c2 = a._cliente_jwks("s", "http://dos/jwks")
    assert c2 is not c1
    a.invalidar_jwks("s")
    assert a._cliente_jwks("s", "http://dos/jwks") is not c2
