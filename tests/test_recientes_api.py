"""«Lo mismo que ayer» de punta a punta: mocks en memoria, LLM falso y Postgres real."""
# ruff: noqa: F811  (reutiliza fixtures de test_api.py por importación, como test_aislamiento.py)

import json
import os
from datetime import datetime
from zoneinfo import ZoneInfo

import pytest
from sqlalchemy import select

from asistente.core.llm.base import LlamadaTool
from asistente.core.llm.falso import pide, texto
from asistente.store.models import LlamadaTool as FilaLlamada
from conftest import firmar
from test_api import (  # noqa: F401  (fixtures y helpers de la API de punta a punta)
    ORIGEN_A,
    api,
    construir_app,
    llm,
    sesiones,
    sse,
    sub,
)

pytestmark = pytest.mark.skipif(
    not os.environ.get("ASISTENTE_DATABASE_URL"), reason="sin ASISTENTE_DATABASE_URL"
)

LISTAR = LlamadaTool("c1", "listar_establecimientos", {})
RECIENTES = LlamadaTool("c2", "consultas_recientes", {})
KIRITIMATI, PAGO_PAGO = "Pacific/Kiritimati", "Pacific/Pago_Pago"  # UTC+14 y UTC-11: «hoy» siempre distinto


def cabecera(usuario: str, sistema: str = "mock-a") -> dict:
    return {"Authorization": f"Bearer {firmar(sistema, usuario)}", "Origin": ORIGEN_A}


async def chatear(api, usuario, mensaje="hola", **cuerpo):
    r = await api.post("/v1/chat", json={"mensaje": mensaje, **cuerpo}, headers=cabecera(usuario))
    assert r.status_code == 200
    return sse(r)


def vista(guion, indice=1) -> dict:
    msg = guion.llamadas[indice].messages[-1]
    assert msg.rol == "tool"
    return json.loads(msg.texto)


def hoy(zona: str) -> str:
    return datetime.now(ZoneInfo(zona)).date().isoformat()


async def test_repetir_una_consulta_de_otra_conversacion_la_vuelve_a_ejecutar(api, llm):
    ana = sub()
    llm.usar(pide(LISTAR), texto("Tenés El Matorral"))
    await chatear(api, ana, "¿qué campos tengo?", zona_horaria="America/Montevideo")

    # otra conversación, otro día: pide «lo mismo»
    guion = llm.usar(pide(RECIENTES), pide(LISTAR), texto("Tenés El Matorral"))
    ev = await chatear(api, ana, "lo mismo que ayer", zona_horaria="America/Montevideo")
    assert "consultas_recientes" in [t.nombre for t in guion.llamadas[0].tools]

    datos = vista(guion)["datos"]
    assert [(c["tool"], c["parametros"], c["veces"]) for c in datos["consultas"]] == [
        ("listar_establecimientos", {}, 1)]
    assert datos["zona_horaria"] == "America/Montevideo"
    assert set(datos["consultas"][0]) == {"tool", "parametros", "fecha", "veces"}  # nunca un resultado
    # el modelo repite la tool original: el resultado es el de ahora, no uno guardado
    nuevo = vista(guion, 2)
    assert nuevo["ok"] is True and "establecimientos" in nuevo["datos"]
    assert [e for e, _ in ev][-1] == "done"


async def test_no_ve_las_consultas_de_otro_usuario_ni_de_otro_sistema(api, llm):
    ana, beto = sub(), sub()
    llm.usar(pide(LISTAR), texto("ok"))
    await chatear(api, ana)

    guion = llm.usar(pide(RECIENTES), texto("nada"))
    await chatear(api, beto)
    assert vista(guion)["datos"]["consultas"] == []

    guion = llm.usar(pide(RECIENTES), texto("nada"))
    r = await api.post("/v1/chat", json={"mensaje": "hola"},
                       headers={"Authorization": f"Bearer {firmar('mock-b', ana)}", "Origin": "https://b.example"})
    assert r.status_code == 200 and vista(guion)["datos"]["consultas"] == []


async def test_la_zona_del_navegador_fija_el_hoy_y_se_guarda_con_la_consulta(api, llm, sesiones):
    ana = sub()
    guion = llm.usar(pide(LISTAR), texto("ok"))
    await chatear(api, ana, zona_horaria=KIRITIMATI)
    assert f"Fecha de hoy: {hoy(KIRITIMATI)}." in guion.llamadas[0].system

    guion = llm.usar(texto("ok"))
    await chatear(api, ana, zona_horaria=PAGO_PAGO)
    assert f"Fecha de hoy: {hoy(PAGO_PAGO)}." in guion.llamadas[0].system
    assert hoy(KIRITIMATI) != hoy(PAGO_PAGO)

    async with sesiones() as s:
        fila = (await s.execute(select(FilaLlamada).where(FilaLlamada.usuario_ref == ana))).scalar_one()
    assert fila.zona_horaria == KIRITIMATI and fila.tool == "listar_establecimientos"


@pytest.mark.parametrize("zona", ["Mar/Inexistente", "", "x" * 100, None])
async def test_una_zona_invalida_no_bloquea_el_chat_y_cae_a_utc(api, llm, sesiones, zona):
    ana = sub()
    guion = llm.usar(pide(LISTAR), texto("ok"))
    cuerpo = {} if zona is None else {"zona_horaria": zona}
    ev = await chatear(api, ana, **cuerpo)
    assert [e for e, _ in ev][-1] == "done"
    assert f"Fecha de hoy: {hoy('UTC')}." in guion.llamadas[0].system
    async with sesiones() as s:
        fila = (await s.execute(select(FilaLlamada).where(FilaLlamada.usuario_ref == ana))).scalar_one()
    assert fila.zona_horaria == "UTC"


async def test_el_sistema_puede_apagar_la_tool(construir_app, llm):
    async with construir_app(consultas_recientes=False) as api:
        guion = llm.usar(texto("ok"))
        await chatear(api, sub())
        assert "consultas_recientes" not in [t.nombre for t in guion.llamadas[0].tools]
