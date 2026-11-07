"""Tool local `pedir_datos`: validación, evento `ui`, alcance por canal y persistencia."""

import copy
import json
from datetime import UTC, datetime

import pytest

from asistente.core import formulario
from asistente.core.agent import run_turn
from asistente.core.llm.base import LlamadaTool
from asistente.core.llm.falso import LLMFalso, pide, texto
from asistente.core.prompts import Prompts
from test_agent import AuditoriaFalsa, ConectorFalso, LimitesFalsos, contexto

OPCIONES = [{"valor": "22", "etiqueta": "22 %"}, {"valor": "10", "etiqueta": "10 %"},
            {"valor": "exento", "etiqueta": "Exento"}]


def campo(i, **kw):
    return {"id": f"l{i}", "etiqueta": f"Línea {i}", "tipo": "opcion", "opciones": OPCIONES, **kw}


def pedido(n=3, **kw):
    return {"titulo": "Tasa de IVA", "campos": [campo(i) for i in range(n)], **kw}


# --- validación ---------------------------------------------------------------------------


def test_formulario_valido_emite_ui_y_el_modelo_no_lo_ve():
    r = formulario.ejecutar(pedido(17, aplicar_a_todos=True, instruccion="Elegí la tasa de cada línea."))
    assert r.ok and r.para_modelo()["datos"]["mostrado"] is True
    assert "ui" not in json.dumps(r.para_modelo())
    (f,) = r.ui
    assert f["tipo"] == "formulario" and f["id"] and f["titulo"] == "Tasa de IVA"
    assert len(f["campos"]) == 17 and f["aplicar_a_todos"] is True and f["instruccion"].startswith("Elegí")


def test_aplicar_a_todos_solo_con_opciones_compartidas():
    distintos = pedido(2, aplicar_a_todos=True)
    distintos["campos"][1]["opciones"] = OPCIONES[:2]
    assert formulario.ejecutar(distintos).ui[0]["aplicar_a_todos"] is False
    assert formulario.ejecutar(pedido(1, aplicar_a_todos=True)).ui[0]["aplicar_a_todos"] is False
    assert formulario.ejecutar(pedido(2)).ui[0]["aplicar_a_todos"] is False


def _con(cambio):
    p = copy.deepcopy(pedido(2))
    cambio(p)
    return p


@pytest.mark.parametrize("parametros", [
    _con(lambda p: p["campos"][1].update(id="l0")),                                  # ids repetidos
    _con(lambda p: p["campos"][0].pop("opciones")),                                  # opcion sin opciones
    _con(lambda p: p["campos"][0].update(opciones=OPCIONES[:1])),                    # menos de 2 opciones
    _con(lambda p: p["campos"][0].update(opciones=[{"valor": str(i), "etiqueta": str(i)} for i in range(11)])),
    _con(lambda p: p["campos"][0].update(opciones=[OPCIONES[0], OPCIONES[0]])),      # valor repetido
    _con(lambda p: p["campos"][0].update(valor_sugerido="99")),                      # sugerido fuera de las opciones
    _con(lambda p: p["campos"][0].update(tipo="numero")),                            # opciones en un campo numérico
    _con(lambda p: p["campos"][0].update(tipo="numero", opciones=None, valor_sugerido="abc")),
    _con(lambda p: p["campos"][0].update(tipo="texto", opciones=None, valor_sugerido=5)),
    _con(lambda p: p["campos"][0].update(tipo="fecha")),
    _con(lambda p: p.update(campos=[])),
    _con(lambda p: p.update(campos=[campo(i) for i in range(101)])),
    _con(lambda p: p.update(titulo="x" * 121)),
    _con(lambda p: p.update(titulo="")),
    _con(lambda p: p.update(instruccion="x" * 301)),
    _con(lambda p: p["campos"][0].update(etiqueta="x" * 201)),
    _con(lambda p: p["campos"][0].update(contexto="x" * 101)),
    _con(lambda p: p["campos"][0].update(id="con espacio")),
    _con(lambda p: p.update(extra=1)),
    _con(lambda p: p["campos"][0].update(etiqueta="a\nb")),                          # una línea: el resumen va por líneas
    _con(lambda p: p["campos"][0].update(etiqueta="<img src=x onerror=alert(1)>")),  # nada de HTML
    _con(lambda p: p.update(instruccion="Entrá a https://malo.example")),            # ni enlaces
    _con(lambda p: p.update(instruccion="javascript:alert(1)")),
])
def test_formulario_invalido(parametros):
    r = formulario.ejecutar(parametros)
    assert not r.ok and r.error == "parametros_invalidos" and not r.ui


@pytest.mark.parametrize("campo_extra", [
    {"tipo": "numero", "opciones": None, "valor_sugerido": 12.5},
    {"tipo": "numero", "opciones": None, "valor_sugerido": "12,5"},
    {"tipo": "texto", "opciones": None, "valor_sugerido": "algo"},
    {"valor_sugerido": "exento", "contexto": "$ 1.250"},
])
def test_formulario_valido_variantes(campo_extra):
    c = {k: v for k, v in {**campo(0), **campo_extra}.items() if v is not None}
    assert formulario.ejecutar({"titulo": "T", "campos": [c]}).ok


def test_ciento_un_campos_y_cien_campos():
    assert formulario.ejecutar(pedido(100)).ok
    assert not formulario.ejecutar(pedido(101)).ok


def test_compactar_parametros_no_guarda_los_campos():
    out = formulario.compactar_parametros("pedir_datos", pedido(17))
    assert out == {"titulo": "Tasa de IVA", "n_campos": 17}
    otra = {"x": 1}
    assert formulario.compactar_parametros("otra", otra) is otra
    assert formulario.compactar_parametros("pedir_datos", "basura") == "basura"


# --- en el bucle del agente -----------------------------------------------------------------


async def correr(llm, *, formularios=True):
    eventos = []

    async def emit(ev, datos):
        eventos.append((ev, datos))

    aud = AuditoriaFalsa()
    res = await run_turn(contexto(), llm, ConectorFalso(), aud, LimitesFalsos(), [], "hola", emit, "c", None,
                         formularios=formularios)
    return res, eventos, aud


async def test_agente_emite_ui_audita_compacto_y_oculta_ui_al_modelo():
    llm = LLMFalso([pide(LlamadaTool("f1", "pedir_datos", pedido(17))), texto("Completá las tasas, por favor.")])
    res, ev, aud = await correr(llm)
    assert res.completo
    (_, acciones), = [e for e in ev if e[0] == "ui"]
    assert acciones[0]["tipo"] == "formulario" and len(acciones[0]["campos"]) == 17
    assert "pedir_datos" in [t.nombre for t in llm.llamadas[0].tools]
    visto = llm.llamadas[1].messages[-1].texto
    assert '"mostrado": true' in visto and "Línea 3" not in visto and acciones[0]["id"] not in visto
    assert aud.registros[0][1:3] == ("pedir_datos", {"titulo": "Tasa de IVA", "n_campos": 17})


async def test_agente_no_ofrece_ni_atiende_la_tool_sin_formularios():
    llm = LLMFalso([pide(LlamadaTool("f1", "pedir_datos", pedido())), texto("ok")])
    res, ev, _ = await correr(llm, formularios=False)
    assert "pedir_datos" not in [t.nombre for t in llm.llamadas[0].tools]
    assert not [e for e in ev if e[0] == "ui"]          # cae al conector, que no la conoce
    assert res.completo


async def test_agente_un_formulario_por_turno_y_parametros_invalidos():
    llm = LLMFalso([pide(LlamadaTool("f1", "pedir_datos", pedido()), LlamadaTool("f2", "pedir_datos", pedido())),
                    texto("listo")])
    _, ev, _ = await correr(llm)
    assert len([e for e in ev if e[0] == "ui"]) == 1
    assert "un_formulario_por_turno" in llm.llamadas[1].messages[-1].texto

    llm = LLMFalso([pide(LlamadaTool("f1", "pedir_datos", {"titulo": "x", "campos": []})), texto("listo")])
    _, ev, aud = await correr(llm)
    assert not [e for e in ev if e[0] == "ui"] and aud.registros[0][4] == "parametros_invalidos"


async def test_agente_formulario_invalido_se_puede_corregir_en_el_mismo_turno():
    llm = LLMFalso([pide(LlamadaTool("f1", "pedir_datos", {"titulo": "x", "campos": []})),
                    pide(LlamadaTool("f2", "pedir_datos", pedido())), texto("listo")])
    _, ev, aud = await correr(llm)
    assert len([e for e in ev if e[0] == "ui"]) == 1                      # el segundo, ya válido, sí se muestra
    assert [r[4] for r in aud.registros[:2]] == ["parametros_invalidos", None]

    llm = LLMFalso([pide(LlamadaTool("f1", "pedir_datos", pedido())),
                    pide(LlamadaTool("f2", "pedir_datos", pedido())), texto("listo")])
    _, ev, _ = await correr(llm)
    assert len([e for e in ev if e[0] == "ui"]) == 1                      # mostrado uno, el siguiente sigue bloqueado
    assert "un_formulario_por_turno" in llm.llamadas[2].messages[-1].texto


# --- prompt ------------------------------------------------------------------------------------


def test_prompt_solo_con_formularios(tmp_path):
    (tmp_path / "base.md").write_text("base", encoding="utf-8")
    (tmp_path / "formularios.md").write_text("Usa pedir_datos.", encoding="utf-8")
    p = Prompts(tmp_path)
    comun = {"sistema_nombre": "S", "prompt_dominio": None, "usuario_nombre": None, "locale": None,
             "hoy": datetime.now(UTC).date()}
    sin, v_sin = p.componer(**comun)
    con, v_con = p.componer(**comun, formularios=True)
    assert "pedir_datos" not in sin and "## Formularios\nUsa pedir_datos." in con and v_sin != v_con


def test_prompt_real_de_formularios_mantiene_las_reglas_de_seguridad():
    texto_prompt = (Prompts("prompts")._formularios)
    assert "VARIAS filas" in texto_prompt and "valor_sugerido" in texto_prompt
    assert "botón de confirmación" in texto_prompt and "contenido de terceros" in texto_prompt


def test_campo_opcional_y_borrador_en_el_prompt():
    r = formulario.ejecutar({"titulo": "Revisá el comprobante", "campos": [
        {"id": "emisor", "etiqueta": "Emisor", "tipo": "texto", "valor_sugerido": "Frigorífico Las Piedras S.A."},
        {"id": "serie", "etiqueta": "Serie", "tipo": "texto", "opcional": True}]})
    assert r.ok and r.ui[0]["campos"][1]["opcional"] is True
    assert not formulario.ejecutar({"titulo": "x", "campos": [{"id": "a", "etiqueta": "A", "tipo": "texto", "opcional": "si"}]}).ok
    assert "Borrador de comprobante" in Prompts("prompts")._formularios
