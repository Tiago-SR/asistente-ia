"""`consultas_recientes` (Fase 0 de memoria): zona horaria, vista para el modelo y despacho en el agente."""

from datetime import UTC, datetime

import pytest

from asistente.core import recientes, zona
from asistente.core.agent import run_turn
from asistente.core.llm.base import LlamadaTool
from asistente.core.llm.falso import LLMFalso, pide, texto
from asistente.core.ports import ConsultaPrevia
from asistente.sistemas.manifiesto import parsear_manifiesto
from asistente.sistemas.registro import RegistroSistemas
from conftest import entorno, entrada_sistema, escribir_registro
from test_agent import AuditoriaFalsa, ConectorFalso, LimitesFalsos, contexto
from test_manifiesto import manifiesto, tool

MONTEVIDEO, MADRID = "America/Montevideo", "Europe/Madrid"


def consulta(cuando: datetime, zona_horaria=MONTEVIDEO, tool="resumen_por_cultivo", parametros=None, veces=1):
    return ConsultaPrevia(tool, parametros or {"cultivo": "soja"}, cuando, veces, zona_horaria)


class RecientesFalso:
    def __init__(self, consultas=()):
        self.consultas_ = list(consultas)
        self.pedidos = []

    async def consultas(self, ctx, tools, desde, limite):
        self.pedidos.append((ctx, set(tools), desde, limite))
        return self.consultas_[:limite]


# ── zona ────────────────────────────────────────────────────────────────────────────────


@pytest.mark.parametrize("nombre", [MONTEVIDEO, "UTC", "Europe/Madrid"])
def test_zonas_validas(nombre):
    assert zona.valida(nombre) == nombre


@pytest.mark.parametrize("nombre", [None, "", "no/existe", "../../etc/passwd", "x" * 65, 5, "America/"])
def test_zonas_invalidas(nombre):
    assert zona.valida(nombre) is None


def test_resolver_usa_la_primera_valida_y_si_no_utc():
    assert zona.resolver("basura", MONTEVIDEO) == MONTEVIDEO
    assert zona.resolver(MADRID, MONTEVIDEO) == MADRID
    assert zona.resolver(None, None) == "UTC"


# ── vista para el modelo ────────────────────────────────────────────────────────────────


def test_la_fecha_se_da_en_la_zona_actual_del_usuario():
    # 01:30 UTC del 6 = 22:30 del 5 en Montevideo: «ayer» (5) no es el día UTC.
    v = recientes.a_vista(consulta(datetime(2026, 10, 6, 1, 30, tzinfo=UTC)), MONTEVIDEO)
    assert v["fecha"] == "2026-10-05" and v["veces"] == 1
    assert "zona_original" not in v and "resultado" not in v and "datos" not in v


def test_misma_zona_u_otra_con_el_mismo_dia_no_agrega_ruido():
    c = datetime(2026, 10, 5, 15, 0, tzinfo=UTC)
    assert "zona_original" not in recientes.a_vista(consulta(c, MONTEVIDEO), MONTEVIDEO)
    assert "zona_original" not in recientes.a_vista(consulta(c, MADRID), MONTEVIDEO)  # 17:00 y 12:00: mismo día


def test_si_la_zona_cambia_el_dia_se_informa_la_de_entonces():
    # 23:30 UTC del 5: en Montevideo es el 5 (20:30); en Madrid, el 6 (01:30).
    v = recientes.a_vista(consulta(datetime(2026, 10, 5, 23, 30, tzinfo=UTC), MADRID), MONTEVIDEO)
    assert v["fecha"] == "2026-10-05"
    assert v["zona_original"] == MADRID and v["fecha_en_zona_original"] == "2026-10-06"


def test_consultas_viejas_sin_zona_no_fallan():
    v = recientes.a_vista(consulta(datetime(2026, 10, 5, 23, 30, tzinfo=UTC), None), MONTEVIDEO)
    assert v["fecha"] == "2026-10-05" and "zona_original" not in v
    v = recientes.a_vista(consulta(datetime(2026, 10, 5, 23, 30, tzinfo=UTC), "zona/rota"), MONTEVIDEO)
    assert "zona_original" not in v


# ── la tool local ───────────────────────────────────────────────────────────────────────


async def test_ejecutar_acota_la_ventana_a_la_retencion_y_el_limite():
    r = RecientesFalso([consulta(datetime(2026, 10, 5, 12, tzinfo=UTC))])
    ctx = contexto(zona_horaria=MONTEVIDEO, retencion_dias=30)
    ahora = datetime(2026, 10, 6, 15, tzinfo=UTC)
    res = await recientes.ejecutar(ctx, r, {"lista"}, {"dias": 365, "limite": 5}, ahora)
    assert res.ok
    _, tools, desde, limite = r.pedidos[0]
    assert tools == {"lista"} and limite == 5
    assert desde == datetime(2026, 9, 6, 15, tzinfo=UTC)  # 30 días, no 365
    assert res.datos["hoy"] == "2026-10-06" and res.datos["zona_horaria"] == MONTEVIDEO
    assert res.datos["consultas"][0]["tool"] == "resumen_por_cultivo"
    assert "no sus resultados" in res.datos["nota"]


async def test_ejecutar_usa_los_valores_por_defecto():
    r = RecientesFalso()
    await recientes.ejecutar(contexto(), r, {"lista"}, {})
    assert r.pedidos[0][3] == recientes.LIMITE_DEFECTO


@pytest.mark.parametrize("args", [{"dias": 0}, {"limite": 21}, {"limite": "x"}, {"otro": 1}])
async def test_ejecutar_rechaza_parametros_invalidos(args):
    r = RecientesFalso()
    res = await recientes.ejecutar(contexto(), r, {"lista"}, args)
    assert not res.ok and res.error == "parametros_invalidos" and r.pedidos == []


def test_un_sistema_no_puede_declarar_la_tool_reservada():
    m = parsear_manifiesto(manifiesto(tool("consultas_recientes"), tool("lista")))
    assert list(m.tools) == ["lista"]


# ── en el agente ────────────────────────────────────────────────────────────────────────


async def correr(llm, recientes_=None, conector=None, ctx=None):
    aud = AuditoriaFalsa()
    res = await run_turn(ctx or contexto(), llm, conector or ConectorFalso(), aud, LimitesFalsos(), [],
                         "lo mismo que ayer", _descartar, "conv-1", recientes=recientes_)
    return res, aud


async def _descartar(ev, datos):
    pass


async def test_la_tool_local_solo_se_ofrece_si_hay_recientes():
    llm = LLMFalso([texto("ok")])
    await correr(llm, None)
    assert [t.nombre for t in llm.llamadas[0].tools] == ["lista"]
    llm = LLMFalso([texto("ok")])
    await correr(llm, RecientesFalso())
    assert [t.nombre for t in llm.llamadas[0].tools] == ["lista", recientes.NOMBRE]


async def test_la_tool_local_se_atiende_sin_pasar_por_el_conector_y_se_audita():
    r = RecientesFalso([consulta(datetime(2026, 10, 5, 12, tzinfo=UTC), tool="lista")])
    conector = ConectorFalso()
    llm = LLMFalso([pide(LlamadaTool("c1", recientes.NOMBRE, {})), texto("ya lo repito")])
    res, aud = await correr(llm, r, conector)
    assert res.completo and conector.llamadas == []
    visto = llm.llamadas[1].messages[-1].texto
    assert '"consultas"' in visto and "lista" in visto
    assert [x[1] for x in aud.registros] == [recientes.NOMBRE]
    assert r.pedidos[0][1] == {"lista"}  # solo las tools de lectura que el sistema ofrece hoy


async def test_las_escrituras_y_la_propia_tool_no_se_listan():
    from asistente.core.llm.base import ToolDef

    class ConectorConEscritura(ConectorFalso):
        async def tools(self):
            return [*await super().tools(), ToolDef("agregar_nota", "d", {"type": "object"}, escritura=True)]

    r = RecientesFalso()
    llm = LLMFalso([pide(LlamadaTool("c1", recientes.NOMBRE, {})), texto("ok")])
    await correr(llm, r, ConectorConEscritura())
    assert r.pedidos[0][1] == {"lista"}


async def test_argumentos_que_no_son_objeto_se_rechazan():
    r = RecientesFalso()
    llm = LLMFalso([pide(LlamadaTool("c1", recientes.NOMBRE, {}, argumentos_invalidos=True)), texto("ok")])
    res, aud = await correr(llm, r)
    assert res.completo and r.pedidos == [] and aud.registros[0][4] == "parametros_invalidos"


async def test_si_el_historial_falla_el_turno_sigue():
    class Roto:
        async def consultas(self, *a):
            raise RuntimeError("BD caída")

    llm = LLMFalso([pide(LlamadaTool("c1", recientes.NOMBRE, {})), texto("no pude")])
    res, aud = await correr(llm, Roto())
    assert res.completo and aud.registros[0][3] is False and aud.registros[0][4] == "error_sistema"


# ── configuración del sistema ───────────────────────────────────────────────────────────


def test_registro_zona_y_interruptor(tmp_path):
    r = RegistroSistemas(escribir_registro(tmp_path / "s.yaml", [
        entrada_sistema("a", zona_horaria=MONTEVIDEO, consultas_recientes=False),
        entrada_sistema("b"),
        entrada_sistema("c", zona_horaria="Mar/Inexistente"),
    ]), env=entorno("a", "b", "c"))
    assert r.obtener("a").zona_horaria == MONTEVIDEO and r.obtener("a").consultas_recientes is False
    assert r.obtener("b").zona_horaria is None and r.obtener("b").consultas_recientes is True
    assert r.obtener("c") is None and "c" in r.errores
