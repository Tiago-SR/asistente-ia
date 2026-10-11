"""Endpoints de operación del panel.

Dos formas de entrar: el token estático `ASISTENTE_ADMIN_TOKEN` (automatización: sin cookie, no sufre CSRF) o la
sesión de un usuario admin (cookie HttpOnly + Origin propio + cabecera `X-CSRF` en lo que no sea GET).
La restricción a red interna se aplica en el proxy; el login se suma a eso, no lo reemplaza.
"""

import hmac
import re
import time
from collections import deque
from dataclasses import dataclass
from datetime import UTC, datetime
from urllib.parse import urlsplit

from fastapi import APIRouter, Depends, Query, Request, Response
from pydantic import BaseModel, Field

from asistente import precios
from asistente.api.deps import servicios
from asistente.api.errores import ErrorApi
from asistente.servicios import Servicios
from asistente.sistemas.manifiesto import ManifiestoInvalido
from asistente.store.admin import DURACION_MAX, AdminSql, SesionAdmin
from asistente.store.uso import consumo_del_mes, consumo_voz_del_mes

router = APIRouter(prefix="/admin")

_LECTURA = {"GET", "HEAD", "OPTIONS"}
_VENTANA_IP_S = 900.0
_FALLOS_IP_MAX = 10


@dataclass(frozen=True)
class Actor:
    nombre: str  # email, o `token`
    rol: str
    csrf: str | None = None


def _store(svc: Servicios) -> AdminSql:
    if svc.sesiones is None:
        raise ErrorApi(503, "sin_base_de_datos")
    return svc.admin or AdminSql(svc.sesiones)


def _nombre_cookie(svc: Servicios) -> str:
    return "__Host-admin" if svc.settings.admin_cookie_secure else "admin"


def _origen_propio(request: Request, svc: Servicios) -> bool:
    origen = request.headers.get("origin")
    if not origen:
        return False
    extra = {o.strip() for o in svc.settings.admin_origenes.split(",") if o.strip()}
    return origen in extra or urlsplit(origen).netloc == request.headers.get("host")


def _ip(request: Request) -> str | None:
    return request.client.host if request.client else None


async def _actor(request: Request, svc: Servicios) -> Actor:
    esquema, _, token = request.headers.get("authorization", "").partition(" ")
    if esquema.lower() == "bearer":
        esperado = svc.settings.admin_token
        if not esperado:
            raise ErrorApi(503, "admin_deshabilitado")
        if not hmac.compare_digest(token.encode(), esperado.encode()):
            raise ErrorApi(401, "no_autorizado", {"WWW-Authenticate": "Bearer"})
        return Actor("token", "admin")
    cookie = request.cookies.get(_nombre_cookie(svc))
    if cookie and svc.sesiones is not None:
        ses = await _store(svc).sesion(cookie)
        if ses is not None:
            if request.method not in _LECTURA:
                enviado = request.headers.get("x-csrf", "")
                if not _origen_propio(request, svc) or not hmac.compare_digest(
                        enviado.encode(), ses.csrf.encode()):
                    raise ErrorApi(403, "csrf")
            return Actor(ses.email, ses.rol, ses.csrf)
    if not cookie and not svc.settings.admin_token:
        raise ErrorApi(503, "admin_deshabilitado")
    raise ErrorApi(401, "no_autorizado")


async def actor(request: Request, svc: Servicios = Depends(servicios)) -> Actor:
    a = await _actor(request, svc)
    request.state.actor = a
    return a


async def admin(request: Request, svc: Servicios = Depends(servicios)) -> Servicios:
    await actor(request, svc)
    return svc


class _Login(BaseModel):
    email: str = Field(max_length=320)
    clave: str = Field(max_length=200)


def _fallos_ip(request: Request) -> deque[float]:
    estado = request.app.state
    if not hasattr(estado, "admin_fallos_ip"):
        estado.admin_fallos_ip = {}
    return estado.admin_fallos_ip.setdefault(_ip(request), deque())


@router.post("/login")
async def login(datos: _Login, request: Request, response: Response,
                svc: Servicios = Depends(servicios)) -> dict:
    if not _origen_propio(request, svc):
        raise ErrorApi(403, "csrf")
    fallos = _fallos_ip(request)
    ahora = time.monotonic()
    while fallos and ahora - fallos[0] > _VENTANA_IP_S:
        fallos.popleft()
    if len(fallos) >= _FALLOS_IP_MAX:
        raise ErrorApi(429, "demasiados_intentos")
    store = _store(svc)
    res = await store.login(datos.email, datos.clave)
    if res is None:
        fallos.append(ahora)
        await store.auditar(datos.email.strip().lower()[:320], "login_fallido", ip=_ip(request))
        raise ErrorApi(401, "credenciales_invalidas")  # mismo mensaje en todos los casos
    token, ses = res
    fallos.clear()
    response.set_cookie(_nombre_cookie(svc), token, max_age=int(DURACION_MAX.total_seconds()), path="/",
                        httponly=True, secure=svc.settings.admin_cookie_secure, samesite="strict")
    await store.auditar(ses.email, "login", ip=_ip(request))
    return _publico(ses)


def _publico(ses: SesionAdmin | Actor) -> dict:
    email = ses.email if isinstance(ses, SesionAdmin) else ses.nombre
    return {"email": email, "rol": ses.rol, "csrf": ses.csrf}


@router.get("/yo")
async def yo(a: Actor = Depends(actor)) -> dict:
    return _publico(a)


@router.post("/logout")
async def logout(request: Request, response: Response, a: Actor = Depends(actor),
                 svc: Servicios = Depends(servicios)) -> dict:
    cookie = request.cookies.get(_nombre_cookie(svc))
    if cookie:
        await _store(svc).cerrar(cookie)
    response.delete_cookie(_nombre_cookie(svc), path="/")
    await _store(svc).auditar(a.nombre, "logout", ip=_ip(request))
    return {"ok": True}


@router.post("/recargar")
async def recargar(request: Request, a: Actor = Depends(actor), svc: Servicios = Depends(servicios)) -> dict:
    await svc.registro.recargar_async()
    svc.manifiestos.invalidar()
    svc.autenticador.invalidar_jwks()
    if svc.sesiones is not None:
        await _store(svc).auditar(a.nombre, "recargar", ip=_ip(request))
    return {"sistemas": len(svc.registro.todos()), "errores": svc.registro.errores}


@router.get("/sistemas")
async def sistemas(svc: Servicios = Depends(admin)) -> dict:
    estado = []
    for s in svc.registro.todos():
        try:
            m = await svc.manifiestos.obtener(s.id)
            manifiesto, error = True, None
            tools = len(m.tools_lectura())
        except ManifiestoInvalido as e:
            manifiesto, error, tools = False, str(e), 0
        estado.append({"id": s.id, "nombre": s.nombre, "habilitado": True,
                       "manifiesto_ok": manifiesto, "tools_lectura": tools, "ultimo_error": error})
    return {"sistemas": estado, "invalidos": svc.registro.errores}


@router.get("/uso")
async def uso(
    mes: str | None = Query(default=None, description="YYYY-MM (por defecto, el mes en curso, UTC)"),
    svc: Servicios = Depends(admin),
) -> dict:
    """Consumo y costo por sistema y modelo en un mes. El costo sale de `config/precios.yaml`:
    `costo_usd` trae la cota inferior (`valle`) y la superior (`pico`) porque la tarifa depende del
    horario del proveedor; un modelo sin tarifa se informa con `costo_usd: null`. La voz del servidor (TTS)
    va aparte en `voz` (caracteres y costo por motor) y su costo se suma al total del sistema."""
    if mes is not None and not re.fullmatch(r"\d{4}-(0[1-9]|1[0-2])", mes):
        raise ErrorApi(422, "mes_invalido")
    if svc.sesiones is None:
        raise ErrorApi(503, "sin_base_de_datos")
    ahora = datetime.now(UTC)
    anio, num = (int(x) for x in mes.split("-")) if mes else (ahora.year, ahora.month)
    filas = await consumo_del_mes(svc.sesiones, datetime(anio, num, 1, tzinfo=UTC))
    tarifas = precios.cargar(svc.settings.precios_path)
    nombres = {s.id: s.nombre for s in svc.registro.todos()}
    sistemas: dict[str, dict] = {}

    def entrada(sistema_id: str) -> dict:
        return sistemas.setdefault(sistema_id, {"id": sistema_id, "nombre": nombres.get(sistema_id),
                                                "modelos": [], "voz": [],
                                                "costo_usd": {h: 0.0 for h in precios.HORARIOS},
                                                "sin_tarifa": []})

    for f in filas:
        tarifa = tarifas.get(f.modelo)
        costo = {h: precios.costo(f.tokens_in, f.tokens_in_cache, f.tokens_out, tarifa, h)
                 for h in precios.HORARIOS} if tarifa else None
        s = entrada(f.sistema_id)
        s["modelos"].append({"modelo": f.modelo, "llamadas": f.llamadas, "tokens_in": f.tokens_in,
                             "tokens_in_cache": f.tokens_in_cache, "tokens_out": f.tokens_out,
                             "costo_usd": costo})
        if costo:
            for h in precios.HORARIOS:
                s["costo_usd"][h] = round(s["costo_usd"][h] + costo[h], 6)
        else:
            s["sin_tarifa"].append(f.modelo)  # el total del sistema no los incluye
    for v in await consumo_voz_del_mes(svc.sesiones, datetime(anio, num, 1, tzinfo=UTC)):
        clave = precios.clave_tts(v.proveedor, v.modelo)
        costo_voz = precios.costo_tts(v.caracteres, tarifas.get(clave))
        s = entrada(v.sistema_id)
        s["voz"].append({"proveedor": v.proveedor, "modelo": v.modelo, "llamadas": v.llamadas,
                         "caracteres": v.caracteres, "costo_usd": costo_voz})
        if costo_voz is not None:
            for h in precios.HORARIOS:   # la voz no tiene valle/pico: suma lo mismo a las dos cotas
                s["costo_usd"][h] = round(s["costo_usd"][h] + costo_voz, 6)
        else:
            s["sin_tarifa"].append(clave)
    return {"mes": f"{anio:04d}-{num:02d}", "sistemas": list(sistemas.values())}
