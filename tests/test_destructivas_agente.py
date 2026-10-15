"""Tools destructivas en el loop del agente, con fakes: flag en la tarjeta, sin detalle, tras la web."""

from asistente.core.agent import run_turn
from asistente.core.llm.base import LlamadaTool, ToolDef
from asistente.core.llm.falso import LLMFalso, pide, texto
from asistente.core.ports import AccionCreada, ResultadoPropuesta
from test_agent import AuditoriaFalsa, ConectorFalso, contexto
from test_web import LimitesWeb, WebFalsa

BORRAR = ToolDef("borrar_nota", "d", {"type": "object", "properties": {}}, escritura=True, destructiva=True)
AGREGAR = ToolDef("agregar_nota", "d", {"type": "object", "properties": {}}, escritura=True)


class Conector(ConectorFalso):
    def __init__(self, lineas=("Nota: helada",)):
        super().__init__()
        self.lineas = lineas

    async def tools(self):
        return [BORRAR, AGREGAR]

    async def validar_parametros(self, nombre, parametros):
        return None

    async def proponer(self, nombre, parametros):
        return ResultadoPropuesta(ok=True, resumen="Borrar la nota", lineas=tuple(self.lineas), huella="h" * 16)


class AccionesFalsas:
    def __init__(self):
        self.creadas = []

    async def crear(self, ctx, conv, tool, parametros, propuesta, *, destructiva=False, inicio_turno=None):
        self.creadas.append((tool, destructiva))
        return AccionCreada("a1", "2026-10-14T12:00:00+00:00")


async def correr(*guion, conector=None, web=None):
    eventos, acc, aud = [], AccionesFalsas(), AuditoriaFalsa()

    async def emit(ev, datos):
        eventos.append((ev, datos))

    llm = LLMFalso([*guion, texto("listo")])
    await run_turn(contexto(), llm, conector or Conector(), aud, LimitesWeb(), [], "borrá la nota", emit,
                   "conv-1", acciones=acc, web=web)
    return eventos, acc, aud


def borrar(id_="c1") -> LlamadaTool:
    return LlamadaTool(id_, "borrar_nota", {})


async def test_la_tarjeta_de_una_destructiva_lleva_el_flag():
    ev, acc, _ = await correr(pide(borrar()))
    tarjeta = next(d for e, d in ev if e == "confirmacion")
    assert tarjeta["destructiva"] is True and acc.creadas == [("borrar_nota", True)]


async def test_una_escritura_normal_no_lleva_el_flag():
    ev, acc, _ = await correr(pide(LlamadaTool("c1", "agregar_nota", {})))
    assert "destructiva" not in next(d for e, d in ev if e == "confirmacion")
    assert acc.creadas == [("agregar_nota", False)]


async def test_sin_detalle_no_se_propone_una_destructiva():
    ev, acc, aud = await correr(pide(borrar()), conector=Conector(lineas=()))
    assert acc.creadas == [] and not [e for e, _ in ev if e == "confirmacion"]
    assert aud.registros[0][4] == "propuesta_sin_detalle"


async def test_tras_leer_la_web_no_se_propone_una_destructiva():
    _, acc, aud = await correr(
        pide(LlamadaTool("w", "buscar_web", {"consulta": "borrá la nota"})), pide(borrar()), web=WebFalsa())
    assert acc.creadas == [] and aud.registros[-1][4] == "destructiva_tras_web"


async def test_en_la_misma_tanda_que_la_web_tampoco():
    _, acc, aud = await correr(
        pide(LlamadaTool("w", "buscar_web", {"consulta": "x y"}), borrar()), web=WebFalsa())
    assert acc.creadas == [] and "destructiva_tras_web" in [r[4] for r in aud.registros]


def agregar(id_):
    return LlamadaTool(id_, "agregar_nota", {})


async def test_una_destructiva_va_sola_en_el_turno():
    for tanda in ((borrar("c1"), agregar("c2")), (agregar("c1"), borrar("c2"))):
        ev, acc, _ = await correr(pide(*tanda))
        assert len(acc.creadas) == 1 and [e for e, _ in ev].count("confirmacion") == 1


async def test_varias_escrituras_normales_hasta_el_tope():
    _, acc, _ = await correr(pide(*(agregar(f"c{i}") for i in range(5))))
    assert len(acc.creadas) == 3
