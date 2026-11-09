"""Avisos salientes iniciados por el sistema anfitrión (`contrato/AVISOS.md`). El anfitrión es la fuente de verdad del
negocio; aquí solo hay transporte: se valida, se guarda (idempotente) y un worker (`avisos_flujo.py`) lo entrega.

Sin sesión ni CSRF: la credencial es `token_avisos` por sistema. Cualquier fallo de autenticación o de sistema (inexistente,
deshabilitado, sin avisos) es la misma 403, para no enumerar sistemas. El texto es una plantilla del anfitrión: no se
interpreta, no se resuelven sus URLs y nunca llega al modelo. Los logs llevan solo los últimos 4 dígitos del número."""

import hashlib
import hmac
import json
import logging
import re
from datetime import UTC, datetime, timedelta

from fastapi import APIRouter, Depends, Request
from fastapi.responses import JSONResponse
from pydantic import BaseModel, ConfigDict, Field, StrictStr, ValidationError

from asistente.api.deps import servicios
from asistente.api.errores import ErrorApi
from asistente.servicios import Servicios
from asistente.sistemas.registro import TIPO_AVISO_RE
from asistente.store.admin import AdminSql
from asistente.store.models import Aviso

log = logging.getLogger(__name__)
router = APIRouter()

MAX_CUERPO = 16 * 1024  # el texto máximo es 4000 caracteres; el adjunto (A4) tendrá su propia ruta o nivel
MAX_TEXTO_DURO = 4000  # techo de `avisos.max_texto`
ID_EVENTO_RE = r"^[A-Za-z0-9._:-]{1,128}$"
REF_RE = r"^[A-Za-z0-9._:-]{1,40}$"  # va al historial de la conversación: caracteres inertes
_NO_AUTORIZADO = ErrorApi(403, "no_autorizado")


class _Destinatario(BaseModel):
    model_config = ConfigDict(extra="forbid")
    usuario_ref: StrictStr = Field(min_length=1, max_length=256)
    wa_id: StrictStr = Field(pattern=r"^[0-9]{8,15}$")  # texto exacto (CAN-05, CAN-15): ni «+», ni espacios, ni número


class _Contexto(BaseModel):
    model_config = ConfigDict(extra="forbid")
    ref: StrictStr = Field(pattern=REF_RE)
    comprobante_id: int | StrictStr | None = None  # opaco para el asistente: no se guarda ni se usa


class _EntradaAviso(BaseModel):
    model_config = ConfigDict(extra="forbid")
    id_evento: StrictStr = Field(pattern=ID_EVENTO_RE)
    tipo: StrictStr = Field(pattern=TIPO_AVISO_RE)
    destinatario: _Destinatario
    texto: StrictStr = Field(min_length=1, max_length=MAX_TEXTO_DURO)
    contexto: _Contexto
    adjunto: object | None = None  # debe ser null (A4 lo habilitará)


def _ult4(wa_id: str) -> str:
    return "…" + wa_id[-4:]


def _autenticar(svc: Servicios, sistema_id: str, request: Request):
    """Devuelve el sistema o lanza la 403 única. Compara siempre con ambos secretos (actual y anterior), en tiempo
    constante y sin cortocircuitar, también cuando el sistema no existe."""
    esquema, _, token = request.headers.get("authorization", "").partition(" ")
    presentado = token.strip().encode() if esquema.lower() == "bearer" else b""
    sistema = svc.registro.obtener(sistema_id)
    actual = (svc.registro.secreto(sistema_id, "token_avisos") or "").encode()
    anterior = (svc.registro.secreto(sistema_id, "token_avisos_anterior") or "").encode()
    coincide = (hmac.compare_digest(presentado, actual) & bool(actual)) | \
               (hmac.compare_digest(presentado, anterior) & bool(anterior))
    if not (coincide and bool(presentado) and sistema is not None and sistema.avisos and sistema.avisos.habilitado):
        raise _NO_AUTORIZADO
    return sistema


def _vista(a: Aviso) -> dict:
    return {"id_evento": a.id_evento, "tipo": a.tipo, "estado": a.estado, "intentos": a.intentos,
            "error": a.error, "creado_en": a.creado_en.isoformat(), "actualizado_en": a.actualizado_en.isoformat(),
            "enviado_en": a.enviado_en.isoformat() if a.enviado_en else None}


def _hash(e: _EntradaAviso) -> str:
    canonico = json.dumps(e.model_dump(mode="json"), sort_keys=True, separators=(",", ":"), ensure_ascii=False)
    return hashlib.sha256(canonico.encode()).hexdigest()


async def _repetido(e: _EntradaAviso, previo: Aviso, svc: Servicios, sistema_id: str, request: Request,
                    h: str) -> JSONResponse:
    """Mismo `id_evento`: mismo contenido = el estado guardado (200); distinto = conflicto (409) y auditoría."""
    if previo.hash == h:
        return JSONResponse(_vista(previo), status_code=200)
    log.warning("avisos %s: id_evento %s repetido con contenido distinto (destino %s)", sistema_id, e.id_evento,
                _ult4(e.destinatario.wa_id))
    if svc.sesiones is not None:
        try:
            await AdminSql(svc.sesiones).auditar(
                f"sistema:{sistema_id}", "aviso_conflicto", sistema_id,
                despues={"id_evento": e.id_evento, "tipo": e.tipo, "numero": _ult4(e.destinatario.wa_id)},
                ip=request.client.host if request.client else None)
        except Exception:  # la auditoría no cambia la respuesta
            log.exception("avisos %s: no se pudo auditar el conflicto", sistema_id)
    raise ErrorApi(409, "id_evento_conflicto")


def _almacen(svc: Servicios):
    if svc.avisos is None or svc.canal_vinculos is None:
        raise ErrorApi(503, "sin_base_de_datos")
    return svc.avisos


@router.post("/sistemas/{sistema_id}/avisos")
async def recibir(sistema_id: str, request: Request, svc: Servicios = Depends(servicios)) -> JSONResponse:
    sistema = _autenticar(svc, sistema_id, request)  # antes que nada: sin credencial no se revela nada más
    cfg = sistema.avisos
    cuerpo = await request.body()  # TopeCuerpo ya cortó lo desmesurado (1 MB); aquí el tope propio
    if len(cuerpo) > MAX_CUERPO:
        raise ErrorApi(413, "cuerpo_demasiado_grande")
    try:
        e = _EntradaAviso.model_validate_json(cuerpo)
    except ValidationError as ex:  # sin los valores recibidos: el texto no debe volver en el error ni al log
        campos = sorted({".".join(str(x) for x in d["loc"]) for d in ex.errors()})
        raise ErrorApi(422, "solicitud_invalida", datos={"campos": campos}) from None
    if e.adjunto is not None:
        raise ErrorApi(422, "adjunto_no_soportado")
    if e.tipo not in cfg.tipos:
        raise ErrorApi(422, "tipo_no_permitido")
    if len(e.texto) > cfg.max_texto:
        raise ErrorApi(422, "texto_demasiado_largo")

    almacen = _almacen(svc)
    h = _hash(e)
    previo = await almacen.obtener(sistema_id, e.id_evento)
    if previo is not None:  # un reintento del anfitrión no depende de que el vínculo siga vigente
        return await _repetido(e, previo, svc, sistema_id, request, h)
    d = e.destinatario
    if not await svc.canal_vinculos.vigente(sistema_id, d.wa_id, d.usuario_ref):
        log.info("avisos %s: destinatario %s sin vínculo vigente de ese usuario", sistema_id, _ult4(d.wa_id))
        raise ErrorApi(422, "destinatario_invalido")
    if await almacen.pendientes_de(sistema_id, d.wa_id) >= cfg.max_pendientes_numero:
        raise ErrorApi(429, "demasiados_pendientes", {"Retry-After": "300"})
    aviso, nuevo = await almacen.crear({
        "sistema_id": sistema_id, "id_evento": e.id_evento, "hash": h, "wa_id": d.wa_id,
        "usuario_ref": d.usuario_ref, "tipo": e.tipo, "ref": e.contexto.ref, "texto": e.texto,
        "caduca_en": datetime.now(UTC) + timedelta(hours=cfg.caducidad_h)})
    if not nuevo:  # carrera con otra petición idéntica
        return await _repetido(e, aviso, svc, sistema_id, request, h)
    log.info("avisos %s: aceptado %s tipo=%s destino %s", sistema_id, e.id_evento, e.tipo, _ult4(d.wa_id))
    return JSONResponse(_vista(aviso), status_code=202)  # `crear` ya hizo commit


@router.get("/sistemas/{sistema_id}/avisos/{id_evento}")
async def estado(sistema_id: str, id_evento: str, request: Request, svc: Servicios = Depends(servicios)) -> dict:
    _autenticar(svc, sistema_id, request)
    aviso = await _almacen(svc).obtener(sistema_id, id_evento) if re.match(ID_EVENTO_RE, id_evento) else None
    if aviso is None:
        raise ErrorApi(404, "aviso_inexistente")
    return _vista(aviso)
