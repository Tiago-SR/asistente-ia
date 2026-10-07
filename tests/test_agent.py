import asyncio

import pytest

from asistente.core.agent import ConfigTurno, run_turn
from asistente.core.llm.base import LlamadaTool, LLMError, Respuesta, ToolDef
from asistente.core.llm.falso import LLMFalso, pide, texto
from asistente.core.ports import Contexto, LimiteExcedido, LimitesUso, ResultadoTool

TOOL = ToolDef("lista", "d", {"type": "object", "properties": {}})


def contexto(**kw) -> Contexto:
    base = {
        "sistema_id": "mock-a", "sistema_nombre": "A", "usuario_ref": "ana", "jti": "j",
        "request_id": "r", "modelo": "m", "prompt_system": "sys", "prompt_version": "v1",
        "limites": LimitesUso(10, 100, 1000),
    }
    return Contexto(**{**base, **kw})


class ConectorFalso:
    def __init__(self, resultados=None, demora=0.0):
        self.resultados = resultados or {}
        self.demora = demora
        self.llamadas: list[tuple[str, dict]] = []
        self.activas = self.max_activas = 0

    async def tools(self):
        return [TOOL]

    async def validar_parametros(self, nombre, parametros):
        return None if nombre == TOOL.nombre else ResultadoTool(False, error="no_disponible", detalle="desconocida")

    async def ejecutar(self, nombre, parametros):
        self.llamadas.append((nombre, parametros))
        self.activas += 1
        self.max_activas = max(self.max_activas, self.activas)
        try:
            await asyncio.sleep(self.demora)
        finally:
            self.activas -= 1
        return self.resultados.get(nombre, ResultadoTool(True, {"x": 1}, status_http=200))


class AuditoriaFalsa:
    def __init__(self):
        self.registros = []

    async def registrar_tool(self, ctx, conv, tool, params, res, ms):
        self.registros.append((ctx.usuario_ref, tool, params, res.ok, res.error))


class LimitesFalsos:
    def __init__(self, falla: str | None = None):
        self.falla, self.mensajes, self.uso = falla, 0, 0

    async def reservar_mensaje(self, ctx):
        if self.falla:
            raise LimiteExcedido(self.falla)
        self.mensajes += 1

    async def registrar_uso(self, ctx, uso):
        self.uso += uso.total


async def correr(llm, conector=None, *, limites=None, config=None, historial=None, ctx=None):
    eventos: list[tuple[str, object]] = []

    async def emit(ev, datos):
        eventos.append((ev, datos))

    aud = AuditoriaFalsa()
    lim = limites or LimitesFalsos()
    res = await run_turn(ctx or contexto(), llm, conector or ConectorFalso(), aud, lim,
                         historial or [], "hola", emit, "conv-1", config)
    return res, eventos, aud, lim


async def test_respuesta_directa():
    res, ev, _, lim = await correr(LLMFalso([texto("Hola Ana")]))
    assert res.completo and res.texto == "Hola Ana"
    assert [e for e, _ in ev if e == "delta"] and ev[-1] == ("done", {"conversacion_id": "conv-1"})
    assert [m.rol for m in res.nuevos] == ["user", "assistant"]
    assert lim.mensajes == 1 and lim.uso == 15


async def test_tool_y_respuesta_final_con_auditoria_y_ui():
    conector = ConectorFalso({"lista": ResultadoTool(True, [1], ui=[{"tipo": "navegar", "ruta": "/x"}])})
    llm = LLMFalso([pide(LlamadaTool("c1", "lista", {})), texto("hay 1")])
    res, ev, aud, _ = await correr(llm, conector)
    assert res.completo
    assert [m.rol for m in res.nuevos] == ["user", "assistant", "tool", "assistant"]
    assert ("ui", [{"tipo": "navegar", "ruta": "/x"}]) in ev
    assert aud.registros == [("ana", "lista", {}, True, None)]
    # el modelo ve el resultado pero nunca `ui`
    visto = llm.llamadas[1].messages[-1].texto
    assert '"datos": [1]' in visto and "navegar" not in visto


async def test_tools_en_paralelo_con_limite_de_concurrencia():
    conector = ConectorFalso(demora=0.02)
    llamadas = [LlamadaTool(f"c{i}", "lista", {}) for i in range(4)]
    llm = LLMFalso([pide(*llamadas), texto("ok")])
    res, *_ = await correr(llm, conector, config=ConfigTurno(max_tools_concurrentes=2))
    assert res.completo and conector.max_activas == 2
    assert [m.llamada_id for m in res.nuevos if m.rol == "tool"] == ["c0", "c1", "c2", "c3"]


async def test_argumentos_invalidos_no_llegan_al_conector():
    conector = ConectorFalso()
    llm = LLMFalso([pide(LlamadaTool("c", "lista", {}, argumentos_invalidos=True)), texto("ok")])
    res, _, aud, _ = await correr(llm, conector)
    assert conector.llamadas == [] and aud.registros[0][4] == "parametros_invalidos"
    assert res.completo


async def test_token_expirado_corta_y_no_persiste():
    conector = ConectorFalso({"lista": ResultadoTool(False, error="token_expirado")})
    res, ev, *_ = await correr(LLMFalso([pide(LlamadaTool("c", "lista", {}))]), conector)
    assert res.motivo == "token_expirado" and res.nuevos == []
    assert ev[-1] == ("token_expirado", None)


async def test_demasiadas_iteraciones():
    llm = LLMFalso([pide(LlamadaTool(f"c{i}", "lista", {})) for i in range(3)])
    res, ev, *_ = await correr(llm, config=ConfigTurno(max_iter=3))
    assert res.motivo == "error" and res.nuevos == []
    assert ev[-1] == ("error", "demasiadas_iteraciones")


async def test_limite_excedido_no_llama_al_llm():
    llm = LLMFalso([])
    res, ev, *_ = await correr(llm, limites=LimitesFalsos("mensajes_min"))
    assert res.motivo == "error" and llm.llamadas == []
    assert ev == [("error", "mensajes_min")]


async def test_fallo_del_llm():
    def falla(_):
        raise LLMError("x")

    res, ev, *_ = await correr(LLMFalso([falla]))
    assert res.motivo == "error" and ev[-1] == ("error", "llm_no_disponible")


async def test_respuesta_vacia_se_reintenta_una_vez():
    res, ev, *_ = await correr(LLMFalso([texto(""), texto("ahora sí")]))
    assert res.completo and res.texto == "ahora sí" and ("error", "respuesta_vacia") not in ev


async def test_respuesta_vacia_dos_veces_es_error_visible():
    res, ev, *_ = await correr(LLMFalso([texto(""), texto("  ")]))
    assert res.motivo == "error" and ev[-1] == ("error", "respuesta_vacia")


async def test_limite_sin_texto_es_error_y_no_se_reintenta():
    llm = LLMFalso([Respuesta("", (), "limite")])
    res, ev, *_ = await correr(llm)
    assert res.motivo == "error" and ev[-1] == ("error", "respuesta_cortada") and len(llm.llamadas) == 1


async def test_limite_con_texto_avisa_y_no_guarda_el_aviso():
    res, ev, *_ = await correr(LLMFalso([Respuesta("La respuesta es larga", (), "limite")]))
    assert res.completo and res.texto == "La respuesta es larga"
    assert any(e == "delta" and "se cortó" in d for e, d in ev if isinstance(d, str))


async def test_timeout_de_turno():
    conector = ConectorFalso(demora=1)
    llm = LLMFalso([pide(LlamadaTool("c", "lista", {}))])
    res, ev, *_ = await correr(llm, conector, config=ConfigTurno(timeout_turno_s=0.05, timeout_tool_s=5))
    assert res.nuevos == [] and ev[-1] == ("error", "timeout_turno")


async def test_timeout_de_tool_se_convierte_en_error_para_el_modelo():
    conector = ConectorFalso(demora=1)
    llm = LLMFalso([pide(LlamadaTool("c", "lista", {})), texto("no pude")])
    res, _, aud, _ = await correr(llm, conector, config=ConfigTurno(timeout_tool_s=0.05))
    assert res.completo and aud.registros[0][4] == "timeout"


async def test_conector_que_lanza_no_tumba_el_turno():
    class Roto(ConectorFalso):
        async def ejecutar(self, nombre, parametros):
            raise RuntimeError("bug")

    res, _, aud, _ = await correr(LLMFalso([pide(LlamadaTool("c", "lista", {})), texto("ok")]), Roto())
    assert res.completo and aud.registros[0][4] == "error_sistema"


async def test_cancelacion_se_propaga():
    conector = ConectorFalso(demora=5)
    llm = LLMFalso([pide(LlamadaTool("c", "lista", {}))])
    tarea = asyncio.create_task(correr(llm, conector, config=ConfigTurno(timeout_tool_s=10)))
    await asyncio.sleep(0.05)
    tarea.cancel()
    with pytest.raises(asyncio.CancelledError):
        await tarea
    assert conector.activas == 0
