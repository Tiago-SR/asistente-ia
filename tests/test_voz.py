"""Canal de voz: resumen hablado (`<voz>…</voz>`) separado del texto visible."""

from datetime import date

from asistente.core.agent import ConfigTurno
from asistente.core.llm.falso import LLMFalso, pide, texto
from asistente.core.prompts import Prompts
from asistente.core.voz_resumen import FiltroVoz, limpiar, resumen_de
from test_agent import correr


def filtrar(*trozos: str) -> tuple[str, str | None]:
    f, visible, resumen = FiltroVoz(), "", None
    for t in trozos:
        v, r = f.alimentar(t)
        visible, resumen = visible + v, r or resumen
    return visible + f.cerrar(), resumen


def test_filtro_separa_resumen_y_texto_aunque_el_bloque_llegue_partido():
    texto_completo = "<voz>Tenés 870,5 hectáreas de soja.</voz>\n\nDetalle: **870,5** ha."
    for corte in range(1, len(texto_completo)):
        visible, resumen = filtrar(texto_completo[:corte], texto_completo[corte:])
        assert resumen == "Tenés 870,5 hectáreas de soja.", corte
        assert visible == "Detalle: **870,5** ha.", corte


def test_filtro_sin_bloque_deja_pasar_todo_el_texto():
    assert filtrar("Hola ", "Ana") == ("Hola Ana", None)
    assert filtrar("<vo", "z") == ("<voz", None)          # parecía el comienzo, pero el flujo terminó
    assert filtrar("  <b>negrita</b>") == ("  <b>negrita</b>", None)
    assert filtrar("") == ("", None)


def test_filtro_bloque_sin_cerrar_o_desmedido_no_se_traga_la_respuesta():
    assert filtrar("<voz>nunca cierra") == ("<voz>nunca cierra", None)
    largo = "x" * 700
    visible, resumen = filtrar("<voz>" + largo, " y sigue")
    assert resumen is None and visible == "<voz>" + largo + " y sigue"


def test_filtro_ignora_bloque_vacio_y_espacios_iniciales():
    assert filtrar("\n <voz></voz>Texto") == ("Texto", None)
    assert filtrar("\n <voz> Resumen </voz> Texto") == ("Texto", "Resumen")


def test_limpiar_y_resumen_de_solo_actuan_al_comienzo():
    assert limpiar("<voz>R</voz>\nCompleta") == "Completa"
    assert limpiar("Completa <voz>R</voz>") == "Completa <voz>R</voz>"
    assert resumen_de("<voz>R</voz>Completa") == "R" and resumen_de("Completa") is None


async def test_agente_en_canal_de_voz_emite_el_resumen_y_no_lo_guarda():
    llm = LLMFalso([texto("<voz>Tenés dos campos.</voz>\n\nEl Matorral y La Aurora.")])
    res, ev, _, _ = await correr(llm, config=ConfigTurno(resumen_voz=True))
    assert ("voz", "Tenés dos campos.") in ev
    visible = "".join(d for e, d in ev if e == "delta")
    assert "<voz>" not in visible and "El Matorral y La Aurora." in visible
    assert res.nuevos[-1].texto.startswith("El Matorral") and "<voz>" not in res.nuevos[-1].texto
    assert res.texto == res.nuevos[-1].texto


async def test_agente_en_canal_de_texto_no_toca_nada():
    res, ev, _, _ = await correr(LLMFalso([texto("<voz>R</voz> Completa")]))
    assert not [e for e, _ in ev if e == "voz"] and "<voz>" in res.texto


async def test_bloque_antes_de_una_tool_tampoco_se_guarda():
    from test_agent import TOOL  # noqa: F401  (el conector falso expone esa tool)

    llm = LLMFalso([pide(__import__("asistente.core.llm.base", fromlist=["LlamadaTool"]).LlamadaTool("c1", "lista", {}),
                         texto_previo="<voz>Voy a mirar.</voz>"),
                    texto("<voz>Listo.</voz> Hay un dato.")])
    res, _, _, _ = await correr(llm, config=ConfigTurno(resumen_voz=True))
    assert all("<voz>" not in m.texto for m in res.nuevos)


def test_prompts_agrega_la_capa_de_voz_solo_en_ese_canal_y_la_versiona(tmp_path):
    (tmp_path / "base.md").write_text("BASE", encoding="utf-8")
    (tmp_path / "voz.md").write_text("RESUMEN HABLADO", encoding="utf-8")
    p = Prompts(tmp_path)
    kw = {"sistema_nombre": "S", "prompt_dominio": None, "usuario_nombre": None, "locale": None, "hoy": date(2026, 1, 1)}
    t_texto, v_texto = p.componer(**kw)
    t_voz, v_voz = p.componer(**kw, canal="voz")
    assert "RESUMEN HABLADO" not in t_texto and "RESUMEN HABLADO" in t_voz
    assert t_voz.index("BASE") < t_voz.index("RESUMEN HABLADO") < t_voz.index("Contexto de la sesión")
    assert v_voz.startswith(v_texto) and v_voz != v_texto and len(v_voz) <= 64


def test_prompts_sin_voz_md_sigue_funcionando(tmp_path):
    (tmp_path / "base.md").write_text("BASE", encoding="utf-8")
    t, v = Prompts(tmp_path).componer(sistema_nombre="S", prompt_dominio=None, usuario_nombre=None, locale=None,
                                      hoy=date(2026, 1, 1), canal="voz")
    assert "Canal de voz" not in t and "+v" not in v


def test_el_prompt_de_voz_del_repo_pide_el_bloque_y_la_brevedad():
    from pathlib import Path

    voz = (Path(__file__).resolve().parent.parent / "prompts" / "voz.md").read_text(encoding="utf-8")
    for clave in ("<voz>", "</voz>", "no la leas entera", "en pantalla", "nunca por voz"):
        assert clave in voz, clave


async def test_agente_mide_cuando_llegan_el_resumen_el_primer_texto_y_el_fin():
    res, _, _, _ = await correr(LLMFalso([texto("<voz>Tenés dos campos.</voz>\n\nEl Matorral y La Aurora.")]),
                                config=ConfigTurno(resumen_voz=True))
    t = res.tiempos
    assert {"voz", "primer_delta", "total"} <= t.keys() and t["voz"] <= t["total"] and t["primer_delta"] <= t["total"]
    sin_voz, _, _, _ = await correr(LLMFalso([texto("Hola")]))
    assert "voz" not in sin_voz.tiempos and "primer_delta" in sin_voz.tiempos
