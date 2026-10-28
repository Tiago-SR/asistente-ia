"""Qué hace el asistente con un mensaje entrante de un canal de mensajería: vincular el número o correr un turno.

La identidad la decide el sistema anfitrión (`contrato/CANAL_WHATSAPP.md`): el asistente le pide un token por mensaje
con el token de canal y valida ese JWT como cualquier otro. Sin vínculo, o ante cualquier rechazo del sistema, el
número recibe silencio."""

import asyncio
import hashlib
import hmac
import logging
import random
import re
import uuid
import weakref

import httpx

from asistente.api.chat import armar_turno
from asistente.api.confirmaciones import cancelar_pendiente, ejecutar_confirmada
from asistente.api.deps import Sesion
from asistente.core import adjuntos as adj
from asistente.core import events, medios
from asistente.core import memoria as memorias
from asistente.core.agent import reservar_cuota, run_turn
from asistente.core.canales.base import Canal, Entrante, ErrorCanal
from asistente.core.llm.base import ToolDef, Uso
from asistente.core.ports import LimiteExcedido
from asistente.servicios import LLMNoConfigurado, Servicios
from asistente.sistemas.auth import SCOPE_ESCRITURA, SCOPE_LECTURA, TokenInvalido, Usuario

log = logging.getLogger(__name__)

BIENVENIDA = "Recibí tu solicitud, la estoy procesando."
SOLO_TEXTO = "Por ahora solo puedo leer mensajes de texto, fotos y PDF."
SIN_IMAGENES = "Por ahora no puedo leer imágenes ni PDF. Escribime lo que necesites."
MEDIO_FALLO = "No pude leer ese archivo. Probá con una foto JPEG o PNG, o un PDF sin clave."
FALLO = "No pude responder ahora. Probá de nuevo en un momento."
MAX_RESPUESTA = 4096  # tope de un mensaje de texto de WhatsApp
_VINCULAR = re.compile(r"^\s*vincular\s+([A-Za-z0-9-]{4,40})\s*$", re.IGNORECASE)
_BOTON = re.compile(r"^(ok|no):([0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}):([0-9a-f]{16})$")
VENCIDA = "Esa propuesta ya no está vigente. Pedímela de nuevo si todavía la querés."
NO_CONFIRMADA = "No pude confirmar la acción. No se guardó nada."
_NS = uuid.UUID("6f1f5f0e-7d52-4d0e-9c4f-2a1f0a7c9b11")
# shortcut: locks en memoria de un solo proceso; con varias réplicas dos turnos del mismo número podrían cruzarse.
_locks: weakref.WeakValueDictionary[tuple[str, str], asyncio.Lock] = weakref.WeakValueDictionary()


class _SistemaRechaza(Exception):
    """El sistema no emite token para este número (sin vínculo, caducado, revocado) o no se pudo hablar con él."""

    def __init__(self, definitivo: bool) -> None:
        self.definitivo = definitivo


async def _pedir(svc: Servicios, sistema_id: str, ruta: str, cuerpo: dict) -> dict:
    s = svc.registro.obtener(sistema_id)
    token = svc.registro.secreto(sistema_id, "token_canal")
    if s is None or not token or svc.http is None:
        if s is not None and not token:
            log.warning("canal %s: falta el secreto token_canal", sistema_id)
        raise _SistemaRechaza(False)
    try:
        r = await svc.http.post(
            s.base_url.rstrip("/") + ruta, json={"canal": "whatsapp", **cuerpo}, timeout=10.0,
            headers={"Authorization": f"Bearer {token}", "X-Asistente-Contrato": "1"}, follow_redirects=False)
    except httpx.HTTPError as e:
        log.warning("canal %s: no se pudo contactar al sistema (%s)", sistema_id, type(e).__name__)
        raise _SistemaRechaza(False) from e
    if r.status_code == 200:
        try:
            return r.json()
        except ValueError:
            pass
    log.info("canal %s: %s respondió HTTP %s", sistema_id, ruta, r.status_code)
    raise _SistemaRechaza(r.status_code == 404)


async def procesar(svc: Servicios, sistema_id: str, canal: Canal, m: Entrante) -> None:
    if svc.canal_vinculos is None or not await _cupo(svc, sistema_id, m.contacto, "entrada", 20, 300, 600, 10000):
        return
    canal = _Registrando(canal, svc, sistema_id)
    try:
        cod = _VINCULAR.match(m.texto or "") if m.tipo == "texto" else None
        if cod:
            if not await _cupo(svc, sistema_id, m.contacto, "vincular", 3, 10, 30, 200):
                return  # silencio, igual que con un código inválido
            await _vincular(svc, sistema_id, canal, m, cod.group(1))
        elif await svc.canal_vinculos.activo(sistema_id, m.contacto):
            lock = _locks.get((sistema_id, m.contacto)) or _locks.setdefault((sistema_id, m.contacto), asyncio.Lock())
            async with lock:
                await (_boton if m.tipo == "boton" else _turno)(svc, sistema_id, canal, m)
        # else: sin vínculo y sin código, silencio
    except ErrorCanal as e:
        log.warning("canal %s: no se pudo enviar (%s)", sistema_id, e.codigo)
    except Exception:
        log.exception("canal %s: error procesando %s", sistema_id, m.id)


async def _cupo(svc: Servicios, sistema_id: str, contacto: str, clave: str, por_min: int, por_dia: int,
                global_min: int, global_dia: int) -> bool:
    """Tope local, contado antes de hacer nada más: por número y global del sistema (rotar números no lo evade).
    El contador guarda un hash, no el teléfono. Pasado el tope, silencio."""
    ref = hashlib.sha256(f"{sistema_id}:{contacto}".encode()).hexdigest()[:32]
    try:
        await svc.limites.reservar_web(sistema_id, ref, por_min, por_dia, clave=clave)
        await svc.limites.reservar_web(sistema_id, "*", global_min, global_dia, clave=clave)
    except LimiteExcedido:
        log.warning("canal %s: demasiados mensajes (%s)", sistema_id, clave)
        return False
    return True


class _Registrando:
    """El canal, anotando cada mensaje que sale para poder seguir su estado (sin contenido)."""

    def __init__(self, canal: Canal, svc: Servicios, sistema_id: str) -> None:
        self._canal, self._svc, self._sistema_id = canal, svc, sistema_id

    async def _anotar(self, mid: str, contacto: str, tipo: str) -> str:
        try:
            await self._svc.canal_mensajes.registrar_salida(self._sistema_id, mid, contacto, tipo)
        except Exception:
            log.exception("canal %s: no se pudo registrar el mensaje saliente", self._sistema_id)
        return mid

    async def enviar_texto(self, contacto: str, texto: str) -> str:
        return await self._anotar(await self._canal.enviar_texto(contacto, texto), contacto, "texto")

    async def enviar_botones(self, contacto: str, cuerpo: str, botones: list[tuple[str, str]]) -> str:
        return await self._anotar(await self._canal.enviar_botones(contacto, cuerpo, botones), contacto, "botones")

    def __getattr__(self, nombre: str):
        return getattr(self._canal, nombre)


async def _vincular(svc: Servicios, sistema_id: str, canal: Canal, m: Entrante, codigo: str) -> None:
    try:
        r = await _pedir(svc, sistema_id, "/asistente/canal/vincular", {"wa_id": m.contacto, "codigo": codigo})
    except _SistemaRechaza:
        return  # código inválido (404) o sistema sin canal: silencio, sin distinguir
    await svc.canal_vinculos.guardar(sistema_id, m.contacto)
    nombre = r.get("nombre")
    await canal.enviar_texto(m.contacto, f"Listo{', ' + nombre if isinstance(nombre, str) and nombre else ''}: "
                                         "tu número quedó vinculado. Escribime lo que necesites.")


async def _identificar(svc: Servicios, sistema_id: str, contacto: str, extra: dict | None = None,
                       scope: str = SCOPE_LECTURA) -> Usuario | None:
    """El usuario del vínculo según el sistema anfitrión (token por mensaje), o None si no hay que seguir."""
    try:
        t = await _pedir(svc, sistema_id, "/asistente/canal/token", {"wa_id": contacto, **(extra or {})})
        u = await svc.autenticador.validar(t["token"], scope, canal="whatsapp")
    except _SistemaRechaza as e:
        if e.definitivo:
            await svc.canal_vinculos.desactivar(sistema_id, contacto)
        return None
    except (TokenInvalido, KeyError, TypeError) as e:
        log.warning("canal %s: token de canal inválido (%s)", sistema_id, type(e).__name__)
        return None
    return u if u.sistema_id == sistema_id else None  # el sistema emisor debe ser el de la ruta


def _mac(clave: str, decision: str, accion_id: str, contacto: str) -> str:
    return hmac.new(clave.encode(), f"{decision}|{accion_id}|{contacto}".encode(), hashlib.sha256).hexdigest()[:16]


def _boton_id(clave: str, decision: str, accion_id: str, contacto: str) -> str:
    """El id del botón ata la decisión a la acción y al número: solo Meta, con la firma del webhook, lo entrega."""
    return f"{decision}:{accion_id}:{_mac(clave, decision, accion_id, contacto)}"


class _ConectorCanal:
    """Por WhatsApp solo se ofrecen las escrituras que el operador encendió para el canal, y nunca una destructiva."""

    def __init__(self, base, permitidas: frozenset[str]) -> None:
        self._base, self._permitidas = base, permitidas

    async def tools(self) -> list[ToolDef]:
        return [t for t in await self._base.tools()
                if not t.escritura or (t.nombre in self._permitidas and not t.destructiva)]

    def __getattr__(self, nombre: str):
        return getattr(self._base, nombre)


async def _ofrecer(svc: Servicios, sistema_id: str, canal: Canal, u: Usuario, contacto: str, clave: str,
                   tarjetas: list[dict]) -> None:
    """Una propuesta por vez: la primera sale con botones, las demás se cancelan."""
    elegida = None
    for t in tarjetas:
        if elegida is None and not t.get("destructiva") and not t.get("local"):
            elegida = t
        else:
            await svc.acciones.cancelar(sistema_id, u.usuario_ref, uuid.UUID(t["id"]))
    if elegida is None:
        return
    cuerpo = "\n".join(["¿Confirmás esta acción?", str(elegida["resumen"]), *map(str, elegida["lineas"])])
    try:
        await canal.enviar_botones(contacto, cuerpo, [
            (_boton_id(clave, "ok", elegida["id"], contacto), "Confirmar"),
            (_boton_id(clave, "no", elegida["id"], contacto), "Cancelar")])
    except ErrorCanal:
        await svc.acciones.cancelar(sistema_id, u.usuario_ref, uuid.UUID(elegida["id"]))  # sin botones nadie la confirma
        raise


async def _boton(svc: Servicios, sistema_id: str, canal: Canal, m: Entrante) -> None:
    """Respuesta a la tarjeta de una propuesta. El id del botón lleva una firma: sin ella o con otra, silencio."""
    clave = svc.registro.secreto(sistema_id, "wa_app_secret")
    f = _BOTON.match(m.boton_id or "")
    if not (clave and f and svc.acciones is not None
            and hmac.compare_digest(_mac(clave, f[1], f[2], m.contacto), f[3])):
        return
    decision, accion_id = f[1], uuid.UUID(f[2])
    sistema = svc.registro.obtener(sistema_id)
    u = await _identificar(svc, sistema_id, m.contacto)
    if sistema is None or u is None:
        return
    accion = await svc.acciones.obtener(sistema_id, u.usuario_ref, accion_id)
    if accion is None or accion.estado != "pendiente":
        await canal.enviar_texto(m.contacto, VENCIDA)
        return
    if decision == "no":
        await canal.enviar_texto(m.contacto, "Listo, cancelado. No se guardó nada."
                                 if await cancelar_pendiente(svc, Sesion(u, sistema), accion) else VENCIDA)
        return
    if accion.destructiva or accion.tool in memorias.NOMBRES:  # no se ofrecen por este canal; por si acaso
        return
    # Token de escritura justo ahora, atado a esta acción: el sistema comprueba que la propuesta fue de este canal.
    t = await _identificar(svc, sistema_id, m.contacto,
                           {"confirmacion": str(accion.id), "huella": accion.huella}, SCOPE_ESCRITURA)
    c = t.accion if t else None
    if (t is None or t.usuario_ref != u.usuario_ref or c is None
            or (c.cid, c.act, c.ph) != (str(accion.id), accion.tool, accion.huella)):
        await canal.enviar_texto(m.contacto, NO_CONFIRMADA)
        return
    r = await ejecutar_confirmada(svc, Sesion(t, sistema), accion_id)
    if r.get("ok"):
        texto = r["mensaje"]
    elif r.get("error") == "accion_no_pendiente":
        texto = VENCIDA
    else:
        texto = f"No se pudo realizar la acción: {r.get('detalle') or r.get('error')}. No se guardó nada."
    await canal.enviar_texto(m.contacto, texto[:MAX_RESPUESTA])


async def _turno(svc: Servicios, sistema_id: str, canal: Canal, m: Entrante) -> None:
    sistema = svc.registro.obtener(sistema_id)
    if sistema is None:
        return
    es_medio = m.tipo in ("imagen", "documento") and bool(m.medio_ref)
    if not es_medio and (m.tipo != "texto" or not m.texto):
        await canal.enviar_texto(m.contacto, SOLO_TEXTO)
        return
    texto = (m.texto or "").strip() or ("Te envío este archivo." if es_medio else "")
    if len(texto) > svc.settings.max_mensaje_chars:
        await canal.enviar_texto(m.contacto, "El mensaje es demasiado largo.")
        return
    u = await _identificar(svc, sistema_id, m.contacto)
    if u is None:
        return
    await svc.canal_vinculos.tocar(sistema_id, m.contacto)

    request_id = uuid.uuid4().hex
    try:
        llm, modelo = svc.llm_para(sistema)
    except LLMNoConfigurado:
        await canal.enviar_texto(m.contacto, FALLO)
        return
    if es_medio and not (llm.capacidades.soporta_imagenes and sistema.adjuntos.habilitado):
        await canal.enviar_texto(m.contacto, SIN_IMAGENES)
        return
    ctx, config, _, web, excel, version = await armar_turno(svc, sistema, u, modelo, request_id)
    # La cuota se reserva antes de descargar y leer el medio: es lo caro, y un medio inválido también cuenta.
    if await reservar_cuota(ctx, svc.limites, svc.metricas):
        await canal.enviar_texto(m.contacto, FALLO)
        return

    await asyncio.sleep(random.uniform(1, 5))
    await canal.enviar_texto(m.contacto, BIENVENIDA)

    adjuntos: tuple = ()
    if es_medio:
        cfg = svc.settings
        tope = min(sistema.adjuntos.max_kb or cfg.max_imagen_kb, cfg.max_imagen_kb) * 1024
        n = min(sistema.adjuntos.max_archivos or cfg.max_imagenes, cfg.max_imagenes)
        try:
            datos, _ = await canal.descargar_medio(m.medio_ref, medios.MAX_MEDIO_BYTES)
            adjuntos = adj.decodificar(await medios.a_imagenes(datos, max_bytes=tope, max_imagenes=n),
                                       max_imagenes=n, max_bytes=tope)
        except (ErrorCanal, medios.MedioInvalido, adj.AdjuntoInvalido) as e:
            log.info("[%s] medio rechazado (%s)", request_id, type(e).__name__)
            await canal.enviar_texto(m.contacto, MEDIO_FALLO)
            return
    # Una conversación por número y usuario: el id es determinista y guardar_turno la crea la primera vez.
    conv_id = uuid.uuid5(_NS, f"{sistema_id}:{u.usuario_ref}")
    historial = await svc.repo.historial(sistema_id, u.usuario_ref, conv_id, svc.settings.max_turnos_historial)
    error: list[str] = []

    tarjetas: list[dict] = []

    async def emit(evento: str, datos) -> None:
        if evento == events.ERROR:
            error.append(str(datos))
        elif evento == events.CONFIRMACION:
            tarjetas.append(datos)

    lectura = (asyncio.create_task(adj.leer(llm, modelo, adjuntos, svc.settings.max_output_tokens))
               if adjuntos and sistema.leer_imagenes else None)
    # Escritura por el canal: opt-in del operador (`canal_mensajeria.acciones`) y solo si hay con qué firmar los botones.
    permitidas = frozenset(sistema.canal_mensajeria.acciones) if sistema.canal_mensajeria else frozenset()
    clave = svc.registro.secreto(sistema_id, "wa_app_secret")
    escribe = bool(permitidas and clave and svc.acciones is not None)
    conector = _ConectorCanal(svc.conector.para(u, request_id), permitidas if escribe else frozenset())
    # `memoria=None`: recordar/olvidar se confirman en el widget, no hay cómo por aquí.
    res = await run_turn(ctx, llm, conector, svc.auditoria, svc.limites, historial,
                         texto, emit, conv_id, config, acciones=svc.acciones if escribe else None, adjuntos=adjuntos,
                         recientes=svc.recientes if sistema.consultas_recientes else None,
                         memoria=None, web=web, metricas=svc.metricas,
                         excel=svc.archivos if excel else None, reservar=False)
    if not res.completo:
        if lectura:
            lectura.cancel()
        log.info("[%s] turno de canal sin completar (%s %s)", request_id, res.motivo, error)
        await canal.enviar_texto(m.contacto, FALLO)
        return
    leidos, uso_lectura = await lectura if lectura else ([], Uso())
    nuevos = [await adj.para_guardar(x, svc.adjuntos, sistema_id, u.usuario_ref, leidos) for x in res.nuevos]
    await asyncio.shield(svc.repo.guardar_turno(sistema_id, u.usuario_ref, conv_id, "WhatsApp", nuevos,
                                                res.uso + uso_lectura, modelo, version))
    await canal.enviar_texto(m.contacto, (res.texto or FALLO)[:MAX_RESPUESTA])
    if escribe:
        await _ofrecer(svc, sistema_id, canal, u, m.contacto, clave, tarjetas)
