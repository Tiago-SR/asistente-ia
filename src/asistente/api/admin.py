"""Endpoints de operación del panel.

Dos formas de entrar: el token estático `ASISTENTE_ADMIN_TOKEN` (automatización: sin cookie, no sufre CSRF) o la
sesión de un usuario admin (cookie HttpOnly + Origin propio + cabecera `X-CSRF` en lo que no sea GET).
/admin y /panel no se exponen en el proxy (túnel ssh, deploy/VPS.md) y `api/acceso_admin.py` lo refuerza; el
login se suma a eso, no lo reemplaza.
"""

import asyncio
import hmac
import ipaddress
import re
import time
import uuid
from collections import deque
from dataclasses import dataclass
from datetime import UTC, date, datetime, timedelta
from urllib.parse import urlsplit

from fastapi import APIRouter, Depends, Query, Request, Response
from pydantic import BaseModel, ConfigDict, Field
from sqlalchemy.exc import DBAPIError

from asistente import precios
from asistente.api.deps import servicios
from asistente.api.errores import ErrorApi
from asistente.core.red import resolver_dns
from asistente.servicios import Servicios, reglas_red
from asistente.sistemas import escritura
from asistente.sistemas.escritura import ErrorEscritura
from asistente.sistemas.manifiesto import NOMBRE_DESTRUCTIVO_RE, ManifiestoInvalido
from asistente.sistemas.permisos import tool_permitida
from asistente.store.admin import DURACION_MAX, AdminSql, ErrorAdmin, SesionAdmin
from asistente.store.lectura_metricas import (
    ORDENES,
    RANGO_CRUDOS_MAX_DIAS,
    MetricasLectura,
)
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
    "admin": frozenset({"sistemas.escribir", "usuarios.gestionar", "auditoria.leer", "metricas.leer"}),
    "operador": frozenset({"metricas.leer"}),
}


def requiere(permiso: str):
    async def dependencia(request: Request, svc: Servicios = Depends(servicios)) -> Servicios:
        a = await actor(request, svc)
        if a.nombre == "token" or permiso not in PERMISOS.get(a.rol, frozenset()):
            raise ErrorApi(403, "permiso_insuficiente")
        if svc.sesiones is None:
            raise ErrorApi(503, "sin_base_de_datos")
        return svc
    return dependencia


def _solo_admin_o_token(a: Actor) -> None:
    """Recargar manifiestos: admin o el token de automatización; el operador no."""
    if a.nombre != "token" and a.rol != "admin":
        raise ErrorApi(403, "permiso_insuficiente")


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
_USUARIOS = Depends(requiere("usuarios.gestionar"))
_AUDITORIA = Depends(requiere("auditoria.leer"))
_METRICAS = Depends(requiere("metricas.leer"))


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
    confirmo_nombre: str | None = Field(default=None, max_length=128)  # obligatorio para encender una destructiva


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


class _ClavePropia(BaseModel):
    model_config = ConfigDict(extra="forbid")
    actual: str = Field(max_length=200, repr=False)
    nueva: str = Field(max_length=200, repr=False)


class _Login(BaseModel):
    email: str = Field(max_length=320)
    clave: str = Field(max_length=200)


def _ip_distinguible(ip: str | None) -> bool:
    """Una IP privada o de loopback (túnel ssh, proxy, red docker) es la de todos los operadores a la vez: contarla
    haría que los fallos de uno bloqueen a los demás. El bloqueo por cuenta sigue vigente."""
    try:
        return ip is not None and ipaddress.ip_address(ip).is_global
    except ValueError:
        return False


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
    contar_ip = _ip_distinguible(_ip(request))
    fallos = _fallos_ip(request)
    ahora = time.monotonic()
    while fallos and ahora - fallos[0] > _VENTANA_IP_S:
        fallos.popleft()
    if contar_ip and len(fallos) >= _FALLOS_IP_MAX:
        raise ErrorApi(429, "demasiados_intentos")
    store = _store(svc)
    res = await store.login(datos.email, datos.clave)
    if res is None:
        if contar_ip:
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
    _solo_admin_o_token(a)
    await svc.registro.recargar_async()
    svc.manifiestos.invalidar()
    svc.autenticador.invalidar_jwks()
    if svc.sesiones is not None:
        await _store(svc).auditar(a.nombre, "recargar", ip=_ip(request))
    return {"sistemas": len(svc.registro.todos()), "errores": svc.registro.errores}


@router.get("/sistemas")
async def sistemas(svc: Servicios = Depends(admin)) -> dict:
    """Lista del registro sin tocar la red: el estado de los manifiestos va aparte (`/manifiestos`)."""
    if svc.sesiones is None:
        return {"sistemas": [{"id": s.id, "nombre": s.nombre, "habilitado": True, "activo": True}
                             for s in svc.registro.todos()],
                "invalidos": svc.registro.errores}
    return await _sistemas_bd(svc)


async def _estado_manifiesto(svc: Servicios, sistema_id: str) -> dict:
    """Acotado: un sistema caído no debe dejar la respuesta colgada hasta su timeout."""
    try:
        m = await asyncio.wait_for(svc.manifiestos.obtener(sistema_id), _ESPERA_MANIFIESTO_S)
    except ManifiestoInvalido as e:
        return {"ok": False, "error": str(e), "tools_lectura": 0}
    except TimeoutError:
        return {"ok": False, "error": "el sistema no respondió a tiempo", "tools_lectura": 0}
    return {"ok": True, "error": None, "tools_lectura": len(m.tools_lectura())}


@router.get("/manifiestos")
async def manifiestos(svc: Servicios = Depends(admin)) -> dict:
    """Estado del manifiesto de cada sistema activo, en paralelo: tarda lo que el más lento (con tope)."""
    ids = [s.id for s in svc.registro.todos()]
    estados = await asyncio.gather(*(_estado_manifiesto(svc, i) for i in ids))
    return {"manifiestos": dict(zip(ids, estados, strict=True))}


async def _sistemas_bd(svc: Servicios) -> dict:
    """Lista del registro en BD: incluye los deshabilitados y los inválidos, con su versión y secretos."""
    assert svc.sesiones is not None
    filas = await escritura.listar(svc.sesiones)
    estado = []
    for f in filas:
        activo = svc.registro.obtener(f["id"]) is not None
        estado.append({**f, "activo": activo,
                       "ultimo_error": None if activo else svc.registro.errores.get(f["id"])})
    return {"sistemas": estado, "invalidos": svc.registro.errores}


_DNS_TOPE_S = 3.0


def _verificar_adjuntos(config: dict, svc: Servicios) -> None:
    """Los límites de imágenes del sistema no pueden superar el techo global (env); el modelo no lo exige para que
    bajar el env no impida cargar sistemas ya guardados."""
    adj, cfg = config.get("adjuntos"), svc.settings
    if not isinstance(adj, dict):
        return
    for campo, techo in (("max_archivos", cfg.max_imagenes), ("max_kb", cfg.max_imagen_kb)):
        v = adj.get(campo)
        if isinstance(v, int) and not isinstance(v, bool) and v > techo:
            raise ErrorApi(422, f"adjuntos_{campo}_sobre_el_techo")


async def _verificar_destinos(config: dict, svc: Servicios) -> None:
    """Rechaza al guardar una URL que el servicio no podría usar (loopback, red privada o metadatos que no figuren
    en ASISTENTE_HOSTS_INTERNOS_PERMITIDOS) para dar un error claro. No es el control: ese ocurre al conectar
    (`core/red.py`), con la IP resuelta en ese momento. Un nombre que aún no resuelve se acepta."""
    reglas = reglas_red(svc.settings)
    auth, llm = config.get("auth"), config.get("llm")
    for campo, url in (("base_url", config.get("base_url")),
                       ("auth.jwks_url", auth.get("jwks_url") if isinstance(auth, dict) else None),
                       ("llm.base_url", llm.get("base_url") if isinstance(llm, dict) else None)):
        if not isinstance(url, str) or not url:
            continue
        try:
            host = (urlsplit(url).hostname or "").rstrip(".").lower()
            puerto = urlsplit(url).port or 80
        except ValueError:
            continue  # la forma la rechaza la validación del modelo
        if not host:
            continue
        try:
            ips = [ipaddress.ip_address(host)]
        except ValueError:
            try:
                ips = [ipaddress.ip_address(i.split("%", 1)[0]) for i in await asyncio.wait_for(
                    resolver_dns(host, puerto), _DNS_TOPE_S)]
            except (OSError, ValueError, TimeoutError):
                continue
        if not reglas.permite(host, ips):
            raise ErrorApi(422, "destino_no_permitido", datos={"mensaje": f"{campo}: {host}"})


@router.post("/sistemas", status_code=201)
async def crear_sistema(request: Request, datos: _Crear,
                        svc: Servicios = _ESCRIBIR) -> dict:
    """Crea el sistema DESHABILITADO: los secretos se cargan después y entonces se habilita (PUT)."""
    a = request.state.actor
    assert svc.sesiones is not None
    _verificar_adjuntos(datos.config, svc)
    await _verificar_destinos(datos.config, svc)
    try:
        r = await escritura.crear_sistema(svc.sesiones, datos.config, por=a.nombre, ip=_ip(request))
    except ErrorEscritura as e:
        raise _fallo(e) from None
    return await _tras_escribir(svc, r)


@router.get("/sistemas/{sistema_id}")
async def sistema(sistema_id: str, svc: Servicios = Depends(admin)) -> dict:
    if svc.sesiones is None:
        raise ErrorApi(503, "sin_base_de_datos")
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
    _verificar_adjuntos(datos.config, svc)
    await _verificar_destinos(datos.config, svc)
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
    estado = {"usuario_inexistente": 404, "ultimo_admin": 409, "auto_cambio": 409,
              "clave_actual_incorrecta": 403}.get(e.codigo, 422)
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


@router.post("/yo/clave")
async def cambiar_clave_propia(datos: _ClavePropia, request: Request, svc: Servicios = Depends(servicios)) -> dict:
    """Cualquier rol, solo con sesión (el token estático no es una persona). Pide la contraseña actual y deja
    abierta únicamente la sesión desde la que se cambia."""
    a = await actor(request, svc)
    token = request.cookies.get(_nombre_cookie(svc))
    if a.nombre == "token" or not token:
        raise ErrorApi(403, "permiso_insuficiente")
    store = _store(svc)
    try:
        await store.cambiar_clave_propia(a.nombre, datos.actual, datos.nueva, token)
    except ErrorAdmin as e:
        if e.codigo == "clave_actual_incorrecta":
            await store.auditar(a.nombre, "clave_propia_fallida", a.nombre, ip=_ip(request))
        raise _falla_admin(e) from None
    await store.auditar(a.nombre, "clave_propia", a.nombre, ip=_ip(request))
    return {"ok": True}


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


@router.get("/auditoria")
async def auditoria(limite: int = Query(50, ge=1, le=200), antes_id: int | None = Query(None, ge=1),
                    actor: str | None = Query(None, max_length=320), accion: str | None = Query(None, max_length=64),
                    svc: Servicios = _AUDITORIA) -> dict:
    """Bitácora del panel, más reciente primero. `antes_id` es el cursor (`siguiente` de la página previa).
    Solo `admin` y solo con sesión; `antes`/`despues` nunca llevan secretos (se guardan ya filtrados)."""
    return await _store(svc).listar_auditoria(limite=limite, antes_id=antes_id, actor=actor, accion=accion)


def _defecto(efecto: str) -> bool:
    return efecto == "lectura"  # lectura encendida salvo excepción; escritura apagada salvo excepción


@router.get("/sistemas/{sistema_id}/tools")
async def tools(sistema_id: str, request: Request, refrescar: bool = False,
                svc: Servicios = Depends(admin)) -> dict:
    if refrescar:
        _solo_admin_o_token(await actor(request, svc))
    """Tools del manifiesto en vivo y su estado. Los nombres y descripciones los escribe un tercero: el panel
    los muestra como texto, nunca como HTML."""
    if svc.sesiones is None:
        raise ErrorApi(503, "sin_base_de_datos")
    try:
        vista = await escritura.leer(svc.sesiones, sistema_id)
    except ErrorEscritura as e:
        raise _fallo(e) from None
    excepciones: dict[str, bool] = vista["tool_estado"]
    aprobadas = await escritura.aprobaciones(svc.sesiones, sistema_id)
    activo = svc.registro.obtener(sistema_id)
    limite = (vista["config"].get("limites") or {}).get("destructivas_por_usuario_hora", 5)
    salida: dict = {"manifiesto_ok": False, "error": None, "tools": [], "huerfanas": [],
                    "destructivas_hora": {**await escritura.destructivas_hora(svc.sesiones, sistema_id),
                                          "limite": limite}}
    conocidas: set[str] = set()
    if activo is None:
        salida["error"] = svc.registro.errores.get(sistema_id) or "sistema_deshabilitado"
    else:
        activo = activo.model_copy(update={"tool_estado": excepciones, "destructivas_aprobadas": aprobadas})
        try:
            m = await (svc.manifiestos.recargar(sistema_id) if refrescar else svc.manifiestos.obtener(sistema_id))
            salida["manifiesto_ok"] = True
            for t in m.tools.values():
                conocidas.add(t.nombre)
                salida["tools"].append({
                    "nombre": t.nombre, "descripcion": t.descripcion, "efecto": t.efecto,
                    "accionable": t.efecto == "lectura" or t.accionable, "destructiva": t.destructiva,
                    "habilitada": tool_permitida(activo, t), "excepcion": excepciones.get(t.nombre),
                    # vigente: coincide con la definición actual; obsoleta: el sistema la cambió y requiere reaprobación
                    "aprobacion": None if t.nombre not in aprobadas
                    else ("vigente" if aprobadas[t.nombre] == t.huella else "obsoleta")})
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
    t = None
    if svc.registro.obtener(sistema_id) is not None:
        try:
            t = (await svc.manifiestos.obtener(sistema_id)).tools.get(tool)
        except ManifiestoInvalido:
            t = None
        if t is not None:
            if datos.habilitada and t.efecto == "escritura" and not t.accionable:
                raise ErrorApi(409, "tool_no_accionable")
            defecto = _defecto(t.efecto)
    destructiva = t.destructiva if t is not None else bool(NOMBRE_DESTRUCTIVO_RE.search(tool))
    huella = None
    if datos.habilitada and destructiva:
        # Encender una destructiva es una decisión explícita de un admin sobre la definición que ve ahora.
        if t is None:
            raise ErrorApi(409, "manifiesto_requerido")
        if a.rol != "admin":
            raise ErrorApi(403, "permiso_insuficiente")
        if datos.confirmo_nombre != tool:
            raise ErrorApi(422, "confirmacion_nombre")
        huella = t.huella
    try:
        estado = await escritura.fijar_tool(svc.sesiones, sistema_id, tool, datos.habilitada, defecto,
                                            huella=huella, por=a.nombre, ip=_ip(request))
    except ErrorEscritura as e:
        raise _fallo(e) from None
    return await _tras_escribir(svc, {"tool_estado": estado})


SERIES_MAX_DIAS = 731


def _rango(desde: date | None, hasta: date | None, max_dias: int) -> tuple[date, date]:
    """Fechas UTC, `hasta` inclusivo. Por defecto, los últimos 30 días (hoy incluido)."""
    hoy = datetime.now(UTC).date()
    h = hasta or hoy
    d = desde or h - timedelta(days=29)
    if d > h:
        raise ErrorApi(422, "rango_invalido")
    if (h - d).days + 1 > max_dias:
        raise ErrorApi(422, "rango_excedido", datos={"max_dias": max_dias})
    return d, h


def _ids_registro(svc: Servicios, sistema_id: str | None) -> list[str]:
    return [sistema_id] if sistema_id else [s.id for s in svc.registro.todos()]


async def _leer(coro):
    try:
        return await coro
    except DBAPIError as e:
        if "statement timeout" in str(e.orig).lower():
            raise ErrorApi(504, "consulta_lenta") from None
        raise


def _sobre(d: date, h: date, cuerpo: dict) -> dict:
    return {"desde": d.isoformat(), "hasta": h.isoformat(), "zona": "UTC",
            "generado": datetime.now(UTC).isoformat(), **cuerpo}


@router.get("/metricas/series")
async def metricas_series(
    sistema_id: str | None = Query(None, max_length=64), desde: date | None = None, hasta: date | None = None,
    tipo: str | None = Query(None, pattern="^(llm|tts|stt|tool)$"),
    resultado: str | None = Query(None, pattern="^(ok|error|limite)$"),
    agrupar: str = Query("detalle", pattern="^(detalle|tipo)$"), svc: Servicios = _METRICAS,
) -> dict:
    """Serie diaria (UTC) de uso: turnos de chat (`llm`), voz (`tts`/`stt`) y tools (`tool`, con el nombre en
    `modelo`). Hasta 731 días. Sale de `uso_diario` y, al vuelo, de los días aún sin resumir (`fuente: crudos`).

    `agrupar=detalle` devuelve las filas tal como se guardan (día, sistema, tipo, modelo, resultado, motivo,
    canal); `agrupar=tipo` suma por (día, sistema, tipo, resultado). `usuarios`, `p50_ms` y `p95_ms` no se
    pueden sumar: al agrupar vienen `null` salvo que el grupo sea una sola fila. Costo: `costo_valle_usd` y
    `costo_pico_usd` son las cotas inferior y superior; `null` = sin tarifa (nunca 0) y `n_sin_tarifa` cuenta los
    eventos que no entran en la suma. `cobertura` dice hasta dónde hay resumen y desde cuándo hay crudos."""
    d, h = _rango(desde, hasta, SERIES_MAX_DIAS)
    r = await _leer(MetricasLectura(svc.sesiones).series(
        _ids_registro(svc, sistema_id), d, h, filtrar=sistema_id is not None, tipo=tipo, resultado=resultado,
        agrupar=agrupar))
    return _sobre(d, h, r)


@router.get("/metricas/usuarios")
async def metricas_usuarios(
    sistema_id: str | None = Query(None, max_length=64), desde: date | None = None, hasta: date | None = None,
    orden: str = Query("turnos", pattern="^(" + "|".join(ORDENES) + ")$"),
    limite: int = Query(20, ge=1, le=100), svc: Servicios = _METRICAS,
) -> dict:
    """Top de usuarios finales (con su `usuario_ref`) sobre los eventos crudos: máximo 90 días. Cada fila trae
    `cuota_dia` (`usados`, `limite`, `restante`): mensajes de hoy (UTC; se reinicia en `reinicia_dia`, no a
    medianoche local) contra el límite actual del sistema; los rechazos también cuentan. `cuota_mes` es la cuota
    de tokens del sistema, la única que puede detener a todos."""
    d, h = _rango(desde, hasta, RANGO_CRUDOS_MAX_DIAS)
    lec = MetricasLectura(svc.sesiones)
    r = await _leer(lec.usuarios([sistema_id] if sistema_id else None, d, h, orden, limite))
    registro = {s.id: s for s in svc.registro.todos()}
    ids = sorted({f["sistema_id"] for f in r["filas"]} | ({sistema_id} if sistema_id else set(registro)))
    cont = await _leer(lec.contadores([(f["sistema_id"], f["usuario_ref"]) for f in r["filas"]],
                                      [i for i in ids if i in registro]))
    for f in r["filas"]:
        s = registro.get(f["sistema_id"])
        if s is None:
            f["cuota_dia"] = None
            continue
        usados = cont["dia"].get((f["sistema_id"], f["usuario_ref"]), 0)
        lim = s.limites.mensajes_por_usuario_dia
        f["cuota_dia"] = {"usados": usados, "limite": lim, "restante": max(0, lim - usados)}
    cuota_mes = []
    for i in ids:
        if i in registro:
            usados = cont["mes"].get(i, 0)
            lim = registro[i].limites.tokens_por_mes
            cuota_mes.append({"sistema_id": i, "usados": usados, "limite": lim, "restante": max(0, lim - usados)})
    return _sobre(d, h, {**r, "cuota_mes": cuota_mes, "reinicia_dia": cont["reinicia_dia"],
                         "reinicia_mes": cont["reinicia_mes"]})


@router.get("/metricas/tools")
async def metricas_tools(
    sistema_id: str | None = Query(None, max_length=64), desde: date | None = None, hasta: date | None = None,
    svc: Servicios = _METRICAS,
) -> dict:
    """Por tool: llamadas, errores y p50/p95 exactos sobre `llamadas_tool` (máximo 90 días; los datos llegan
    solo hasta `retencion_dias` del sistema: ver `cobertura.tools_desde`). La duración incluye la espera del
    semáforo del conector, así que un p95 alto puede ser cola y no lentitud del sistema externo. Para más
    de 90 días, `/metricas/series?tipo=tool` (por día, sin percentiles del rango)."""
    d, h = _rango(desde, hasta, RANGO_CRUDOS_MAX_DIAS)
    r = await _leer(MetricasLectura(svc.sesiones).tools([sistema_id] if sistema_id else None, d, h))
    return _sobre(d, h, r)


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
