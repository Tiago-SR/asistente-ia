"""Qué hace el asistente con un mensaje entrante de un canal de mensajería: vincular el número o correr un turno.

La identidad la decide el sistema anfitrión (`contrato/CANAL_WHATSAPP.md`): el asistente le pide un token por mensaje
con el token de canal y valida ese JWT como cualquier otro. Sin vínculo, o ante cualquier rechazo del sistema, el
número recibe silencio."""

import asyncio
import hashlib
import logging
import random
import re
import uuid
import weakref

import httpx

from asistente.api.chat import armar_turno
from asistente.core import adjuntos as adj
from asistente.core import events, medios
from asistente.core.agent import reservar_cuota, run_turn
from asistente.core.canales.base import Canal, Entrante, ErrorCanal
from asistente.core.llm.base import Uso
from asistente.core.ports import LimiteExcedido
from asistente.servicios import LLMNoConfigurado, Servicios
from asistente.sistemas.auth import TokenInvalido, Usuario

log = logging.getLogger(__name__)

BIENVENIDA = "Recibí tu solicitud, la estoy procesando."
SOLO_TEXTO = "Por ahora solo puedo leer mensajes de texto, fotos y PDF."
SIN_IMAGENES = "Por ahora no puedo leer imágenes ni PDF. Escribime lo que necesites."
MEDIO_FALLO = "No pude leer ese archivo. Probá con una foto JPEG o PNG, o un PDF sin clave."
FALLO = "No pude responder ahora. Probá de nuevo en un momento."
MAX_RESPUESTA = 4096  # tope de un mensaje de texto de WhatsApp
_VINCULAR = re.compile(r"^\s*vincular\s+([A-Za-z0-9-]{4,40})\s*$", re.IGNORECASE)
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
    if svc.canal_vinculos is None:
        return
    try:
        cod = _VINCULAR.match(m.texto or "") if m.tipo == "texto" else None
        if cod:
            if not await _cupo_vincular(svc, sistema_id, m.contacto):
                return  # silencio, igual que con un código inválido
            await _vincular(svc, sistema_id, canal, m, cod.group(1))
        elif await svc.canal_vinculos.activo(sistema_id, m.contacto):
            lock = _locks.get((sistema_id, m.contacto)) or _locks.setdefault((sistema_id, m.contacto), asyncio.Lock())
            async with lock:
                await _turno(svc, sistema_id, canal, m)
        # else: sin vínculo y sin código, silencio
    except ErrorCanal as e:
        log.warning("canal %s: no se pudo enviar (%s)", sistema_id, e.codigo)
    except Exception:
        log.exception("canal %s: error procesando %s", sistema_id, m.id)


async def _cupo_vincular(svc: Servicios, sistema_id: str, contacto: str) -> bool:
    """Tope local de intentos, contados antes del POST: por número y global del sistema (rotar números no lo evade).
    El contador guarda un hash, no el teléfono."""
    ref = hashlib.sha256(f"{sistema_id}:{contacto}".encode()).hexdigest()[:32]
    try:
        await svc.limites.reservar_web(sistema_id, ref, 3, 10, clave="vincular")
        await svc.limites.reservar_web(sistema_id, "*", 30, 200, clave="vincular")
    except LimiteExcedido:
        log.warning("canal %s: demasiados intentos de vincular", sistema_id)
        return False
    return True


async def _vincular(svc: Servicios, sistema_id: str, canal: Canal, m: Entrante, codigo: str) -> None:
    try:
        r = await _pedir(svc, sistema_id, "/asistente/canal/vincular", {"wa_id": m.contacto, "codigo": codigo})
    except _SistemaRechaza:
        return  # código inválido (404) o sistema sin canal: silencio, sin distinguir
    await svc.canal_vinculos.guardar(sistema_id, m.contacto)
    nombre = r.get("nombre")
    await canal.enviar_texto(m.contacto, f"Listo{', ' + nombre if isinstance(nombre, str) and nombre else ''}: "
                                         "tu número quedó vinculado. Escribime lo que necesites.")


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
    try:
        t = await _pedir(svc, sistema_id, "/asistente/canal/token", {"wa_id": m.contacto})
        u: Usuario = await svc.autenticador.validar(t["token"], canal="whatsapp")
    except _SistemaRechaza as e:
        if e.definitivo:
            await svc.canal_vinculos.desactivar(sistema_id, m.contacto)
        return
    except (TokenInvalido, KeyError, TypeError) as e:
        log.warning("canal %s: token de canal inválido (%s)", sistema_id, type(e).__name__)
        return
    if u.sistema_id != sistema_id:  # el sistema emisor debe ser el de la ruta
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
    ctx, config, memoria, web, excel, version = await armar_turno(svc, sistema, u, modelo, request_id)
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

    async def emit(evento: str, datos) -> None:
        if evento == events.ERROR:
            error.append(str(datos))

    lectura = (asyncio.create_task(adj.leer(llm, modelo, adjuntos, svc.settings.max_output_tokens))
               if adjuntos and sistema.leer_imagenes else None)
    res = await run_turn(ctx, llm, svc.conector.para(u, request_id), svc.auditoria, svc.limites, historial,
                         texto, emit, conv_id, config, acciones=None, adjuntos=adjuntos,
                         recientes=svc.recientes if sistema.consultas_recientes else None,
                         memoria=memoria, web=web, metricas=svc.metricas,
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
