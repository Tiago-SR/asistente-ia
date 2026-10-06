"""Las tools locales `recordar` y `olvidar` en el loop del agente, con fakes (sin API ni base de datos)."""

import json

from asistente.core import memoria as m
from asistente.core.agent import run_turn
from asistente.core.llm.base import LlamadaTool
from asistente.core.llm.falso import LLMFalso, pide, texto
from asistente.core.ports import AccionCreada, ResultadoTool
from test_agent import AuditoriaFalsa, ConectorFalso, LimitesFalsos, contexto
from test_memoria import RecuerdosFalsos

LISTA = LlamadaTool("c1", "lista", {})


class ConectorSinPropuestas(ConectorFalso):
    """Si el agente intentara proponer una acción local al sistema anfitrión, esto lo delata."""

    def __init__(self):
        super().__init__({"lista": ResultadoTool(True, {"items": [{"id": "4", "nombre": "San Pedro"}]})})
        self.propuestas = []

    async def proponer(self, nombre, parametros):
        self.propuestas.append(nombre)
        raise AssertionError("una acción local no debe pasar por el conector")


class AccionesFalsas:
    def __init__(self):
        self.creadas = []

    async def crear(self, ctx, conv, tool, parametros, propuesta):
        self.creadas.append((ctx.usuario_ref, tool, parametros, propuesta))
        return AccionCreada("accion-1", "2026-10-06T12:00:00+00:00")


async def correr(*guion, memoria=True, acciones=True):
    eventos = []

    async def emit(ev, datos):
        eventos.append((ev, datos))

    llm = LLMFalso([*guion, texto("listo")])
    conector, acc = ConectorSinPropuestas(), AccionesFalsas()
    res = await run_turn(
        contexto(), llm, conector, AuditoriaFalsa(), LimitesFalsos(), [], "recordá", emit, "conv-1",
        acciones=acc if acciones else None,
        memoria=m.ServicioMemoria(RecuerdosFalsos()) if memoria else None)
    return res, eventos, llm, conector, acc


def recordar(tipo, clave, valor) -> LlamadaTool:
    return LlamadaTool("c2", "recordar", {"tipo": tipo, "clave": clave, "valor": valor})


def alias(id_="4", **extra) -> LlamadaTool:
    return recordar("alias", "la sojera", {"entidad": "establecimiento", "id": id_, **extra})


def resultado(llm, indice):
    return json.loads(llm.llamadas[indice].messages[-1].texto)


async def test_las_tools_locales_se_ofrecen_solo_con_el_servicio_de_memoria():
    _, _, llm, *_ = await correr(memoria=True)
    assert {"recordar", "olvidar"} <= {t.nombre for t in llm.llamadas[0].tools}
    _, _, llm, *_ = await correr(memoria=False)
    assert not {"recordar", "olvidar"} & {t.nombre for t in llm.llamadas[0].tools}


async def test_propuesta_local_no_pasa_por_el_conector_y_lleva_el_resumen_del_servidor():
    res, ev, llm, conector, acc = await correr(pide(LISTA), pide(alias()))
    assert res.completo and conector.propuestas == []
    [(usuario, tool, parametros, propuesta)] = acc.creadas
    assert (usuario, tool) == ("ana", "recordar")
    # se guardan los parámetros ya normalizados por el servidor, no los del modelo
    assert parametros == {"tipo": "alias", "clave": "la sojera",
                          "valor": {"entidad": "establecimiento", "id": "4", "nombre": "San Pedro"}}
    assert propuesta.resumen == "Recordar: “la sojera” = San Pedro (establecimiento 4)"
    [tarjeta] = [d for e, d in ev if e == "confirmacion"]
    assert tarjeta["local"] is True and tarjeta["id"] == "accion-1" and tarjeta["resumen"] == propuesta.resumen
    assert resultado(llm, 2)["datos"]["estado"] == "pendiente_de_confirmacion"


async def test_alias_con_un_id_que_no_aparecio_en_el_turno_se_rechaza():
    res, ev, llm, _, acc = await correr(pide(LISTA), pide(alias(id_="999")))
    assert res.completo and acc.creadas == [] and "confirmacion" not in [e for e, _ in ev]
    assert resultado(llm, 2)["ok"] is False and resultado(llm, 2)["error"] == "id_no_visto"


async def test_alias_sin_haber_consultado_nada_se_rechaza():
    _, _, llm, _, acc = await correr(pide(alias()))
    assert acc.creadas == [] and resultado(llm, 1)["error"] == "id_no_visto"


async def test_consulta_guardada_con_tool_de_escritura_o_inexistente_se_rechaza():
    for tool in ("agregar_nota", "no_existe"):
        _, _, llm, _, acc = await correr(pide(recordar(
            "consulta_guardada", "x", {"tool": tool, "parametros": {}})))
        assert acc.creadas == [] and resultado(llm, 1)["error"] == "no_disponible", tool


async def test_consulta_guardada_con_tool_de_lectura_se_propone():
    _, ev, _, _, acc = await correr(pide(recordar(
        "consulta_guardada", "la de siempre", {"tool": "lista", "parametros": {}})))
    assert [p[3].resumen for p in acc.creadas] == ["Recordar la consulta “la de siempre”: lista"]
    assert [d["local"] for e, d in ev if e == "confirmacion"] == [True]


async def test_sin_el_servicio_de_acciones_no_hay_propuesta():
    _, _, llm, _, acc = await correr(pide(recordar("preferencia", "decimales", 0)), acciones=False)
    assert acc.creadas == [] and resultado(llm, 1)["error"] == "no_disponible"


async def test_sin_memoria_las_tools_locales_son_tools_desconocidas():
    res, ev, _, conector, acc = await correr(pide(recordar("preferencia", "decimales", 0)), memoria=False)
    assert res.completo and acc.creadas == [] and "confirmacion" not in [e for e, _ in ev]
    # va al conector como cualquier tool (el real la rechaza por desconocida: ver test_memoria_api)
    assert ("recordar", {"tipo": "preferencia", "clave": "decimales", "valor": 0}) in conector.llamadas


async def test_una_sola_propuesta_por_turno_aunque_se_mezclen_locales():
    _, _, llm, _, acc = await correr(pide(
        recordar("preferencia", "decimales", 0), LlamadaTool("c3", "olvidar", {"tipo": "alias", "clave": "x"})))
    assert len(acc.creadas) == 1
    assert json.loads(llm.llamadas[1].messages[-1].texto)["error"] == "una_accion_a_la_vez"
