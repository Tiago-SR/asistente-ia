"""Endpoints de operación, protegidos por ASISTENTE_ADMIN_TOKEN.

La restricción a red interna se aplica en el proxy; aquí solo se exige el token.
"""

import hmac
import re
from datetime import UTC, datetime

from fastapi import APIRouter, Depends, Query, Request

from asistente import precios
from asistente.api.deps import servicios
from asistente.api.errores import ErrorApi
from asistente.servicios import Servicios
from asistente.sistemas.manifiesto import ManifiestoInvalido
from asistente.store.uso import consumo_del_mes

router = APIRouter(prefix="/admin")


async def admin(request: Request, svc: Servicios = Depends(servicios)) -> Servicios:
    esperado = svc.settings.admin_token
    if not esperado:
        raise ErrorApi(503, "admin_deshabilitado")
    _, _, token = request.headers.get("authorization", "").partition(" ")
    if not hmac.compare_digest(token.encode(), esperado.encode()):
        raise ErrorApi(401, "no_autorizado", {"WWW-Authenticate": "Bearer"})
    return svc


@router.post("/recargar")
async def recargar(svc: Servicios = Depends(admin)) -> dict:
    svc.registro.recargar()
    svc.manifiestos.invalidar()
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
    horario del proveedor; un modelo sin tarifa se informa con `costo_usd: null`."""
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
    for f in filas:
        tarifa = tarifas.get(f.modelo)
        costo = {h: precios.costo(f.tokens_in, f.tokens_in_cache, f.tokens_out, tarifa, h)
                 for h in precios.HORARIOS} if tarifa else None
        s = sistemas.setdefault(f.sistema_id, {"id": f.sistema_id, "nombre": nombres.get(f.sistema_id),
                                               "modelos": [], "costo_usd": {h: 0.0 for h in precios.HORARIOS},
                                               "sin_tarifa": []})
        s["modelos"].append({"modelo": f.modelo, "llamadas": f.llamadas, "tokens_in": f.tokens_in,
                             "tokens_in_cache": f.tokens_in_cache, "tokens_out": f.tokens_out,
                             "costo_usd": costo})
        if costo:
            for h in precios.HORARIOS:
                s["costo_usd"][h] = round(s["costo_usd"][h] + costo[h], 6)
        else:
            s["sin_tarifa"].append(f.modelo)  # el total del sistema no los incluye
    return {"mes": f"{anio:04d}-{num:02d}", "sistemas": list(sistemas.values())}
