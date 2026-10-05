"""Dependencias de la API: servicios, usuario autenticado y verificación de Origin."""

from dataclasses import dataclass

from fastapi import Request

from asistente.api.errores import ErrorApi
from asistente.servicios import Servicios
from asistente.sistemas.auth import TokenInvalido, Usuario
from asistente.sistemas.registro import Sistema


@dataclass(frozen=True)
class Sesion:
    usuario: Usuario
    sistema: Sistema


def servicios(request: Request) -> Servicios:
    s = getattr(request.app.state, "servicios", None)
    if s is None:
        raise ErrorApi(503, "servicio_no_disponible")
    return s


async def sesion_actual(request: Request) -> Sesion:
    """El sistema sale del token (`iss`), nunca del request."""
    svc = servicios(request)
    cabecera = request.headers.get("authorization", "")
    esquema, _, token = cabecera.partition(" ")
    if esquema.lower() != "bearer" or not token.strip():
        raise ErrorApi(401, "token_invalido", {"WWW-Authenticate": "Bearer"})
    try:
        usuario = await svc.autenticador.validar(token.strip())
    except TokenInvalido as e:
        codigo = "token_expirado" if e.expirado else "token_invalido"
        raise ErrorApi(401, codigo, {"WWW-Authenticate": "Bearer"}) from e
    sistema = svc.registro.obtener(usuario.sistema_id)
    if sistema is None:  # deshabilitado entre la validación y aquí (recarga)
        raise ErrorApi(401, "token_invalido", {"WWW-Authenticate": "Bearer"})
    origen = request.headers.get("origin")
    # Los navegadores siempre envían Origin; las llamadas servidor a servidor no lo traen.
    if origen is not None and origen not in sistema.origenes_permitidos:
        raise ErrorApi(403, "origen_no_permitido")
    return Sesion(usuario, sistema)
