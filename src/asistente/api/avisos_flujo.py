"""Entrega de los avisos salientes (`contrato/AVISOS.md`): un worker que toma de a uno los avisos pendientes y los envía
por el canal del sistema. No usa el modelo ni ejecuta tools: solo transporte.

Reglas de resultado (la misma que `_entregar_archivos`: un timeout puede ocultar un envío ya hecho):
- éxito → `enviado`;
- el canal rechazó antes de enviar (`ErrorCanal.no_enviado`) → reintento con backoff acotado y luego `fallido`;
- cualquier otra falla o resultado ambiguo → `incierto`, sin reintento. El anfitrión lo ve en el GET del aviso.
El espaciado entre envíos y los topes de 24 h salen de la propia tabla, así valen también con varias réplicas."""

import asyncio
import logging
import random
from collections.abc import Callable
from datetime import UTC, datetime, timedelta

from asistente.api.canal import canal_de
from asistente.api.canal_flujo import _Registrando, candado, conv_id_de
from asistente.core.canales.base import ErrorCanal
from asistente.servicios import Servicios
from asistente.store.models import Aviso

log = logging.getLogger(__name__)

LEASE_S = 120.0  # mucho mayor que el timeout HTTP del canal (20 s + conexión)
MAX_INTENTOS = 5  # envíos rechazados «de forma segura» antes de dar el aviso por fallido
BACKOFF_BASE_S = 60.0
ESPERA_TOPE_S = 15 * 60  # cuánto se pospone un aviso que chocó con el tope diario
SONDEO_S = 5.0
ETIQUETAS = {"refacturacion_pendiente": "refacturación pendiente", "refacturacion_resultado": "resultado de refacturación"}


def _ult4(wa_id: str) -> str:
    return "…" + wa_id[-4:]


def _backoff(intentos: int) -> timedelta:
    return timedelta(seconds=min(BACKOFF_BASE_S * 2 ** max(intentos - 1, 0), 3600))


def texto_de_contexto(tipo: str, ref: str | None) -> str:
    """Lo que queda en el historial: lo genera el servidor con el tipo (de la whitelist del operador) y el `ref`
    (validado con una regex estricta). NUNCA el texto del aviso ni datos de terceros: el modelo lo lee como propio."""
    return f"Aviso enviado: {ETIQUETAS.get(tipo, tipo.replace('_', ' '))}" + (f", ref {ref}" if ref else "")


async def _persistir(operacion: Callable, *args) -> bool:
    """El resultado ya ocurrió fuera: se reintenta guardarlo (es idempotente) y no se cancela a medias."""
    for i in range(3):
        try:
            return await asyncio.shield(operacion(*args))
        except Exception:
            log.exception("avisos: no se pudo guardar el resultado (intento %d)", i + 1)
            await asyncio.sleep(0.2 * (i + 1))
    return False


async def _contexto(svc: Servicios, a: Aviso) -> None:
    """Mejor esfuerzo: el aviso ya salió. Un turno mínimo del asistente en la conversación del usuario."""
    try:
        await svc.repo.agregar_aviso(a.sistema_id, a.usuario_ref, conv_id_de(a.sistema_id, a.usuario_ref), "WhatsApp",
                                     texto_de_contexto(a.tipo, a.ref))
    except Exception:
        log.exception("avisos %s: no se pudo dejar el contexto de %s", a.sistema_id, a.id_evento)


async def _enviar(svc: Servicios, a: Aviso, canal) -> None:
    """Un aviso ya reclamado (`enviando`): lo envía y registra el resultado."""
    sistema_id = a.sistema_id
    if not await svc.canal_vinculos.vigente(sistema_id, a.wa_id, a.usuario_ref):
        # El vínculo caducó, se revocó o pasó a otro usuario entre aceptar y enviar: no se escribe a quien no corresponde.
        log.warning("avisos %s: %s sin vínculo vigente de ese usuario (destino %s)", sistema_id, a.id_evento, _ult4(a.wa_id))
        await _persistir(svc.avisos.fallido, a.id, "vinculo_no_vigente")
        return
    try:
        async with candado(sistema_id, a.wa_id):
            mid = await _Registrando(canal, svc, sistema_id).enviar_texto(a.wa_id, a.texto or "")
    except ErrorCanal as e:
        if e.no_enviado and a.intentos < MAX_INTENTOS:
            proximo = min(datetime.now(UTC) + _backoff(a.intentos), a.caduca_en)
            log.warning("avisos %s: %s no enviado (%s), reintento %d", sistema_id, a.id_evento, e.estado or "sin respuesta", a.intentos)
            await _persistir(svc.avisos.reintentar, a.id, f"no_enviado:{e.estado or 'conexion'}", proximo)
        elif e.no_enviado:
            await _persistir(svc.avisos.fallido, a.id, f"no_enviado:{e.estado or 'conexion'}")
        else:
            # Un timeout o una respuesta ambigua pueden ocultar un envío ya hecho: no se reintenta.
            log.warning("avisos %s: %s sin confirmar (%s); queda incierto", sistema_id, a.id_evento, e.estado or "sin respuesta")
            await _persistir(svc.avisos.incierto, a.id, f"sin_confirmar:{e.estado or 'timeout'}")
        return
    except Exception:
        log.exception("avisos %s: error inesperado enviando %s", sistema_id, a.id_evento)
        await _persistir(svc.avisos.incierto, a.id, "error_inesperado")
        return
    log.info("avisos %s: enviado %s id=%s destino %s", sistema_id, a.id_evento, mid, _ult4(a.wa_id))
    await _persistir(svc.avisos.enviado, a.id, mid)
    await _contexto(svc, a)


async def procesar_uno(svc: Servicios, canal_para: Callable = canal_de) -> bool:
    """Envía como mucho un aviso. `True` si hizo algo (hay que volver enseguida); `False` si no había nada que pueda
    salir ahora (cola vacía, espaciado o topes)."""
    almacen = svc.avisos
    await almacen.recuperar()
    ahora = datetime.now(UTC)
    for a in await almacen.candidatos():
        sistema = svc.registro.obtener(a.sistema_id)
        cfg = sistema.avisos if sistema else None
        canal = canal_para(svc, a.sistema_id) if cfg and cfg.habilitado else None
        if canal is None or getattr(sistema.canal_mensajeria, "proveedor", None) != "openwa":
            motivo = "avisos_deshabilitados" if not (cfg and cfg.habilitado) else "canal_no_disponible"
            if (await almacen.reclamar(a.id, LEASE_S)) is not None:
                await _persistir(almacen.fallido, a.id, motivo)
                return True
            continue
        ultimo = await almacen.ultimo_envio(a.sistema_id)
        if ultimo is not None and (ahora - ultimo).total_seconds() < random.uniform(cfg.pausa_min_s, cfg.pausa_max_s):
            continue  # espaciado entre envíos del sistema, con jitter
        if (await almacen.enviados_24h(a.sistema_id, a.wa_id) >= cfg.tope_diario_numero
                or await almacen.enviados_24h(a.sistema_id) >= cfg.tope_diario_sistema):
            await almacen.diferir(a.id, ahora + timedelta(seconds=ESPERA_TOPE_S))
            log.info("avisos %s: tope diario alcanzado, %s queda en espera (destino %s)", a.sistema_id, a.id_evento, _ult4(a.wa_id))
            continue
        reclamado = await almacen.reclamar(a.id, LEASE_S)  # otro worker pudo ganarlo
        if reclamado is None:
            continue
        await _enviar(svc, reclamado, canal)
        return True
    return False


async def bucle_avisos(svc: Servicios, sondeo_s: float = SONDEO_S) -> None:
    """Tarea del lifespan. Se cancela al apagar; si cae a mitad de un envío, `recuperar` lo deja `incierto`."""
    while True:
        try:
            hizo = await procesar_uno(svc)
        except asyncio.CancelledError:
            raise
        except Exception:  # la BD o el registro pueden fallar un rato
            log.exception("avisos: error en el worker")
            hizo = False
        if not hizo:
            await asyncio.sleep(sondeo_s)
