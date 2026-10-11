"""Endpoints de operación del panel.

Dos formas de entrar: el token estático `ASISTENTE_ADMIN_TOKEN` (automatización: sin cookie, no sufre CSRF) o la
sesión de un usuario admin (cookie HttpOnly + Origin propio + cabecera `X-CSRF` en lo que no sea GET).
La restricción a red interna se aplica en el proxy; el login se suma a eso, no lo reemplaza.
"""

import asyncio
import hmac
import re
import time
import uuid
from collections import deque
from dataclasses import dataclass
from datetime import UTC, datetime
from urllib.parse import urlsplit

from fastapi import APIRouter, Depends, Query, Request, Response
from pydantic import BaseModel, ConfigDict, Field

from asistente import precios
from asistente.api.deps import servicios
from asistente.api.errores import ErrorApi
from asistente.servicios import Servicios
from asistente.sistemas import escritura
from asistente.sistemas.escritura import ErrorEscritura
from asistente.sistemas.manifiesto import ManifiestoInvalido
from asistente.sistemas.permisos import tool_permitida
from asistente.store.admin import DURACION_MAX, AdminSql, ErrorAdmin, SesionAdmin
from asistente.store.uso import consumo_del_mes, consumo_voz_del_mes

router = APIRouter(prefix="/admin/api")

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


# Permisos por rol. Las escrituras exigen una sesión de usuario (el token estático es solo automatización:
# recargar y leer). Abrir algo al operador es cambiar esta tabla, no cada endpoint.
PERMISOS: dict[str, frozenset[str]] = {
    "admin": frozenset({"sistemas.escribir", "usuarios.gestionar"}),
    "operador": frozenset(),
}


def requiere(permiso: str, *, registro_bd: bool = True):
    async def dependencia(request: Request, svc: Servicios = Depends(servicios)) -> Servicios:
        a = await actor(request, svc)
        if a.nombre == "token" or permiso not in PERMISOS.get(a.rol, frozenset()):
            raise ErrorApi(403, "permiso_insuficiente")
        if registro_bd and svc.settings.registro != "bd":
            raise ErrorApi(409, "registro_en_yaml")
        if svc.sesiones is None:
            raise ErrorApi(503, "sin_base_de_datos")
        return svc
    return dependencia


async def _tras_escribir(svc: Servicios, respuesta: dict) -> dict:
    """La réplica que escribe recarga al momento; las otras lo ven con el sondeo (hasta 5 s)."""
    try:
        await svc.registro.recargar_async()
    except Exception:  # noqa: BLE001 el commit ya ocurrió: se informa y el sondeo lo corrige
        respuesta = {**respuesta, "aviso": "recarga_pendiente"}
    return respuesta


def _fallo(e: ErrorEscritura) -> ErrorApi:
    return ErrorApi(e.estado, e.codigo, datos=e.datos)


_ESCRIBIR = Depends(requiere("sistemas.escribir"))
_ESPERA_MANIFIESTO_S = 3.0  # tope por sistema al listar
_USUARIOS = Depends(requiere("usuarios.gestionar", registro_bd=False))


class _Secretos(BaseModel):
    model_config = ConfigDict(extra="forbid", str_strip_whitespace=False)
    token_manifiesto: str | None = Field(default=None, max_length=4096, repr=False)
    llm_api_key: str | None = Field(default=None, max_length=4096, repr=False)
    auth_hs256: str | None = Field(default=None, max_length=4096, repr=False)


class _Crear(BaseModel):
    model_config = ConfigDict(extra="forbid")
    config: dict


class _Actualizar(BaseModel):
    model_config = ConfigDict(extra="forbid")
    version: int = Field(ge=1)
    config: dict
    secretos: _Secretos = Field(default_factory=_Secretos, repr=False)


class _Secreto(BaseModel):
    model_config = ConfigDict(extra="forbid")
    version: int = Field(ge=1)
    valor: str = Field(max_length=4096, repr=False)


class _EstadoTool(BaseModel):
    model_config = ConfigDict(extra="forbid")
    habilitada: bool


class _UsuarioNuevo(BaseModel):
    model_config = ConfigDict(extra="forbid")
    email: str = Field(max_length=320)
    clave: str = Field(max_length=200, repr=False)
    rol: str = Field(max_length=16)


class _UsuarioCambio(BaseModel):
    model_config = ConfigDict(extra="forbid")
    rol: str | None = Field(default=None, max_length=16)
    activo: bool | None = None


class _Clave(BaseModel):
    model_config = ConfigDict(extra="forbid")
    clave: str = Field(max_length=200, repr=False)


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
    if svc.settings.registro == "bd" and svc.sesiones is not None:
        return await _sistemas_bd(svc)
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


async def _estado_manifiesto(svc: Servicios, sistema_id: str) -> tuple[bool, str | None, int]:
    """(ok, error, tools). Acotado: un sistema caído no debe dejar la lista colgada hasta su timeout."""
    try:
        m = await asyncio.wait_for(svc.manifiestos.obtener(sistema_id), _ESPERA_MANIFIESTO_S)
    except ManifiestoInvalido as e:
        return False, str(e), 0
    except TimeoutError:
        return False, "el sistema no respondió a tiempo", 0
    return True, None, len(m.tools_lectura())


async def _sistemas_bd(svc: Servicios) -> dict:
    """Lista del registro en BD: incluye los deshabilitados y los inválidos, con su versión y secretos."""
    assert svc.sesiones is not None
    filas = await escritura.listar(svc.sesiones)
    activos = [svc.registro.obtener(f["id"]) is not None for f in filas]
    # En paralelo: la lista tarda lo que el más lento (con tope), no la suma.
    manifiestos = await asyncio.gather(
        *(_estado_manifiesto(svc, f["id"]) if a else asyncio.sleep(0, (False, None, 0))
          for f, a in zip(filas, activos, strict=True)))
    estado = []
    for f, activo, (ok, error, tools) in zip(filas, activos, manifiestos, strict=True):
        estado.append({**f, "activo": activo, "manifiesto_ok": ok, "tools_lectura": tools,
                       "ultimo_error": error if activo else svc.registro.errores.get(f["id"])})
    return {"sistemas": estado, "invalidos": svc.registro.errores}


@router.post("/sistemas", status_code=201)
async def crear_sistema(request: Request, datos: _Crear,
                        svc: Servicios = _ESCRIBIR) -> dict:
    """Crea el sistema DESHABILITADO: los secretos se cargan después y entonces se habilita (PUT)."""
    a = request.state.actor
    assert svc.sesiones is not None
    try:
        r = await escritura.crear_sistema(svc.sesiones, datos.config, por=a.nombre, ip=_ip(request))
    except ErrorEscritura as e:
        raise _fallo(e) from None
    return await _tras_escribir(svc, r)


@router.get("/sistemas/{sistema_id}")
async def sistema(sistema_id: str, svc: Servicios = Depends(admin)) -> dict:
    if svc.settings.registro != "bd" or svc.sesiones is None:
        raise ErrorApi(409, "registro_en_yaml")
    try:
        vista = await escritura.leer(svc.sesiones, sistema_id)
    except ErrorEscritura as e:
        raise _fallo(e) from None
    return {**vista, "activo": svc.registro.obtener(sistema_id) is not None,
            "error": svc.registro.errores.get(sistema_id)}


@router.put("/sistemas/{sistema_id}")
async def actualizar_sistema(sistema_id: str, datos: _Actualizar, request: Request,
                             svc: Servicios = _ESCRIBIR) -> dict:
    a = request.state.actor
    assert svc.sesiones is not None
    try:
        r = await escritura.actualizar_sistema(
            svc.sesiones, svc.cifrador, sistema_id, datos.config, datos.version,
            token_manifiesto=datos.secretos.token_manifiesto, llm_api_key=datos.secretos.llm_api_key,
            auth_hs256=datos.secretos.auth_hs256, por=a.nombre, ip=_ip(request))
    except ErrorEscritura as e:
        raise _fallo(e) from None
    return await _tras_escribir(svc, r)


@router.put("/sistemas/{sistema_id}/secretos/{campo}")
async def guardar_secreto(sistema_id: str, campo: str, datos: _Secreto, request: Request,
                          svc: Servicios = _ESCRIBIR) -> dict:
    a = request.state.actor
    assert svc.sesiones is not None
    try:
        r = await escritura.guardar_secreto(svc.sesiones, svc.cifrador, sistema_id, campo, datos.valor,
                                            datos.version, por=a.nombre, ip=_ip(request))
    except ErrorEscritura as e:
        raise _fallo(e) from None
    return await _tras_escribir(svc, r)


@router.delete("/sistemas/{sistema_id}/secretos/{campo}")
async def borrar_secreto(sistema_id: str, campo: str, request: Request, version: int = Query(ge=1),
                         svc: Servicios = _ESCRIBIR) -> dict:
    a = request.state.actor
    assert svc.sesiones is not None
    try:
        r = await escritura.borrar_secreto(svc.sesiones, sistema_id, campo, version, por=a.nombre,
                                           ip=_ip(request))
    except ErrorEscritura as e:
        raise _fallo(e) from None
    return await _tras_escribir(svc, r)


def _falla_admin(e: ErrorAdmin) -> ErrorApi:
    estado = {"usuario_inexistente": 404, "ultimo_admin": 409, "auto_cambio": 409}.get(e.codigo, 422)
    return ErrorApi(estado, e.codigo if e.codigo != "invalido" else "usuario_invalido",
                    datos={"mensaje": str(e)})


@router.get("/usuarios")
async def usuarios(svc: Servicios = _USUARIOS) -> dict:
    return {"usuarios": await _store(svc).listar_usuarios()}


@router.post("/usuarios", status_code=201)
async def crear_usuario(datos: _UsuarioNuevo, request: Request, svc: Servicios = _USUARIOS) -> dict:
    a = request.state.actor
    try:
        await _store(svc).crear_usuario(datos.email, datos.clave, datos.rol)
    except ErrorAdmin as e:
        raise _falla_admin(e) from None
    email = datos.email.strip().lower()
    await _store(svc).auditar(a.nombre, "usuario_crear", email, despues={"rol": datos.rol}, ip=_ip(request))
    return {"email": email, "rol": datos.rol}


@router.patch("/usuarios/{usuario_id}")
async def modificar_usuario(usuario_id: uuid.UUID, datos: _UsuarioCambio, request: Request,
                            svc: Servicios = _USUARIOS) -> dict:
    a = request.state.actor
    try:
        r = await _store(svc).modificar_usuario(usuario_id, rol=datos.rol, activo=datos.activo, actor=a.nombre)
    except ErrorAdmin as e:
        raise _falla_admin(e) from None
    await _store(svc).auditar(a.nombre, "usuario_modificar", r["email"],
                              despues={"rol": r["rol"], "activo": r["activo"]}, ip=_ip(request))
    return r


@router.post("/usuarios/{usuario_id}/clave")
async def cambiar_clave(usuario_id: uuid.UUID, datos: _Clave, request: Request,
                        svc: Servicios = _USUARIOS) -> dict:
    a = request.state.actor
    store = _store(svc)
    email = next((u["email"] for u in await store.listar_usuarios() if u["id"] == str(usuario_id)), None)
    if email is None:
        raise ErrorApi(404, "usuario_inexistente")
    try:
        await store.cambiar_clave(email, datos.clave)  # revoca sus sesiones
    except ErrorAdmin as e:
        raise _falla_admin(e) from None
    await store.auditar(a.nombre, "usuario_clave", email, ip=_ip(request))
    return {"ok": True}


def _defecto(efecto: str) -> bool:
    return efecto == "lectura"  # lectura encendida salvo excepción; escritura apagada salvo excepción


@router.get("/sistemas/{sistema_id}/tools")
async def tools(sistema_id: str, refrescar: bool = False, svc: Servicios = Depends(admin)) -> dict:
    """Tools del manifiesto en vivo y su estado. Los nombres y descripciones los escribe un tercero: el panel
    los muestra como texto, nunca como HTML."""
    if svc.settings.registro != "bd" or svc.sesiones is None:
        raise ErrorApi(409, "registro_en_yaml")
    try:
        vista = await escritura.leer(svc.sesiones, sistema_id)
    except ErrorEscritura as e:
        raise _fallo(e) from None
    excepciones: dict[str, bool] = vista["tool_estado"]
    activo = svc.registro.obtener(sistema_id)
    salida: dict = {"manifiesto_ok": False, "error": None, "tools": [], "huerfanas": []}
    conocidas: set[str] = set()
    if activo is None:
        salida["error"] = svc.registro.errores.get(sistema_id) or "sistema_deshabilitado"
    else:
        activo = activo.model_copy(update={"tool_estado": excepciones})
        try:
            m = await (svc.manifiestos.recargar(sistema_id) if refrescar else svc.manifiestos.obtener(sistema_id))
            salida["manifiesto_ok"] = True
            for t in m.tools.values():
                conocidas.add(t.nombre)
                salida["tools"].append({
                    "nombre": t.nombre, "descripcion": t.descripcion, "efecto": t.efecto,
                    "accionable": t.efecto == "lectura" or t.accionable, "destructiva": t.destructiva,
                    "habilitada": tool_permitida(activo, t), "excepcion": excepciones.get(t.nombre)})
        except ManifiestoInvalido as e:
            salida["error"] = str(e)
    salida["huerfanas"] = [{"nombre": n, "habilitada": v} for n, v in excepciones.items() if n not in conocidas]
    return salida


@router.put("/sistemas/{sistema_id}/tools/{tool}")
async def fijar_tool(sistema_id: str, tool: str, datos: _EstadoTool, request: Request,
                     svc: Servicios = _ESCRIBIR) -> dict:
    a = request.state.actor
    assert svc.sesiones is not None
    defecto = False  # tool desconocida (aún no está en el manifiesto): se trata como escritura
    if svc.registro.obtener(sistema_id) is not None:
        try:
            t = (await svc.manifiestos.obtener(sistema_id)).tools.get(tool)
        except ManifiestoInvalido:
            t = None
        if t is not None:
            if datos.habilitada and t.efecto == "escritura" and not t.accionable:
                raise ErrorApi(409, "tool_no_accionable")
            defecto = _defecto(t.efecto)
    try:
        estado = await escritura.fijar_tool(svc.sesiones, sistema_id, tool, datos.habilitada, defecto,
                                            por=a.nombre, ip=_ip(request))
    except ErrorEscritura as e:
        raise _fallo(e) from None
    return await _tras_escribir(svc, {"tool_estado": estado})


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
