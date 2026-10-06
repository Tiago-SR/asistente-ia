import sys
from pathlib import Path

import pytest
import yaml

from asistente.core.llm.base import Uso
from asistente.core.llm.openai_compat import _cache

EVALS = Path(__file__).resolve().parent.parent / "evals"
sys.path.insert(0, str(EVALS))
import correr
import puntuar as p

BASE = [540.5, 210, 120, 88.2, 870.5, 660.5]


def pregunta(**criterios) -> dict:
    return {"turnos": ["¿algo?"], **criterios}


@pytest.mark.parametrize("texto,esperado", [
    ("Tiene 540,5 ha", [540.5]),
    ("Tiene 540.5 hectáreas", [540.5]),
    ("Son 1.234,5 ha", [1234.5]),
    ("Son 1,234.5 ha", [1234.5]),
    ("Son 1.234 ha", [1234.0]),
    ("El 75,9% de 870,5.", [75.9, 870.5]),
])
def test_numeros_en_acepta_formato_es_y_en(texto, esperado):
    assert p.numeros_en(texto) == esperado


def test_la_cifra_esperada_debe_aparecer_con_tolerancia():
    q = pregunta(numeros=[[75.9, 75.87]])
    assert p.puntuar(q, "Es el 75,9 %", [], BASE, None)["ok"]
    assert p.puntuar(q, "Es el 75,87 %", [], BASE, None)["ok"]
    r = p.puntuar(q, "Es el 76 %", [], BASE, None)
    assert not r["ok"] and any("falta la cifra" in f for f in r["fallos"])


def test_una_cifra_de_otro_usuario_es_fallo():
    r = p.puntuar(pregunta(sin_numeros=[88.2]), "Los Ceibos tiene 88,2 ha", [], BASE, None)
    assert any("prohibida" in f for f in r["fallos"])


def test_cifra_inventada_se_detecta_pero_enteros_chicos_y_anios_no():
    r = p.puntuar(pregunta(), "Tiene 3 lotes, 999,9 ha, en 2026", [], BASE, None)
    assert r["fallos"] == ["cifra no respaldada: 999.9"]


def test_cifras_derivadas_declaradas_no_cuentan_como_inventadas():
    q = pregunta(permitidos=[420.5])
    assert p.puntuar(q, "Hay 420,5 ha de diferencia", [], BASE, None)["ok"]
    assert not p.puntuar(pregunta(), "Hay 420,5 ha de diferencia", [], BASE, None)["ok"]


def test_las_cifras_de_la_pregunta_estan_permitidas():
    q = {"turnos": ["Crea un campo de 100 hectáreas"], "contiene": [["no puedo"]]}
    assert p.puntuar(q, "No puedo crear los 100 ha", [], BASE, None)["ok"]


def test_contiene_ignora_tildes_y_mayusculas_y_pide_un_grupo_completo():
    q = pregunta(contiene=[["maíz"], ["soja"]])
    assert p.puntuar(q, "MAIZ y Soja", [], BASE, None)["ok"]
    assert not p.puntuar(q, "solo soja", [], BASE, None)["ok"]


def test_tools_y_errores_del_servicio():
    q = pregunta(tools_requeridas=["a"], tools_prohibidas=["b"])
    assert p.puntuar(q, "ok", ["a"], BASE, None)["ok"]
    assert len(p.puntuar(q, "ok", ["b"], BASE, None)["fallos"]) == 2
    assert not p.puntuar(pregunta(), "", [], BASE, "llm_no_disponible")["ok"]


def prop(tool="agregar_nota", resumen="Agregar una nota", lineas=("Texto: Hubo helada",)):
    return {"tool": tool, "resumen": resumen, "lineas": list(lineas)}


def test_propone_exige_exactamente_esa_propuesta_y_que_no_diga_que_ya_se_hizo():
    q = pregunta(propone="agregar_nota")
    assert p.puntuar(q, "Confirmala en pantalla", [], BASE, None, [prop()])["ok"]
    assert not p.puntuar(q, "Confirmala en pantalla", [], BASE, None, [])["ok"]
    assert not p.puntuar(q, "ok", [], BASE, None, [prop("modificar_nota")])["ok"]
    assert not p.puntuar(q, "ok", [], BASE, None, [prop(), prop()])["ok"]
    assert "afirma que la acción ya se hizo" in p.puntuar(q, "Ya se guardó la nota", [], BASE, None, [prop()])["fallos"]
    # «todavía no está guardada» no cuenta como afirmar que se hizo
    assert p.puntuar(q, "Todavía no está guardada: confirmala", [], BASE, None, [prop()])["ok"]


def test_sin_propuesta_falla_si_propone():
    q = pregunta(sin_propuesta=True)
    assert p.puntuar(q, "¿En cuál establecimiento?", [], BASE, None, [])["ok"]
    assert not p.puntuar(q, "Listo", [], BASE, None, [prop()])["ok"]


def test_la_propuesta_se_revisa_en_lo_que_ve_el_usuario():
    q = pregunta(propone="agregar_nota", propuesta_contiene=[["helada"]], propuesta_no_contiene=["2026"])
    assert p.puntuar(q, "ok", [], BASE, None, [prop()])["ok"]
    assert not p.puntuar(q, "ok", [], BASE, None, [prop(lineas=["Texto: Hubo helada el 1 de octubre de 2026"])])["ok"]
    assert not p.puntuar(q, "ok", [], BASE, None, [prop(lineas=["Texto: Revisar el molino"])])["ok"]


def test_cache_de_distintos_proveedores():
    assert _cache({"prompt_cache_hit_tokens": 120, "prompt_tokens_details": {"cached_tokens": 5}}) == 120
    assert _cache({"prompt_tokens_details": {"cached_tokens": 64}}) == 64
    assert _cache({"prompt_tokens": 10}) == 0
    assert (Uso(10, 2, 8) + Uso(5, 1, 0)) == Uso(15, 3, 8)


def test_costo_separa_cache_hit_y_miss():
    tarifa = {"entrada_cache_hit": {"valle": 1.0}, "entrada_cache_miss": {"valle": 10.0}, "salida": {"valle": 100.0}}
    uso = {"tokens_in": 1_000_000, "tokens_in_cache": 400_000, "tokens_out": 10_000}
    assert correr.costo(uso, tarifa, "valle") == pytest.approx(0.4 + 6.0 + 1.0)
    assert correr.costo(uso, None, "valle") is None


def test_el_set_de_preguntas_es_valido():
    conjunto = yaml.safe_load((EVALS / "preguntas.yaml").read_text(encoding="utf-8"))
    ids = [q["id"] for q in conjunto["preguntas"]]
    assert len(ids) == len(set(ids)) >= 30
    permitidos = {"turnos", "id", "categoria", "usuario", "tools_requeridas", "tools_prohibidas", "numeros",
                  "sin_numeros", "contiene", "no_contiene", "permitidos"}
    for q in conjunto["preguntas"]:
        assert set(q) <= permitidos, q["id"]
        assert q["turnos"] and q["usuario"] in ("ana", "beto"), q["id"]


def test_el_set_de_acciones_es_valido():
    conjunto = yaml.safe_load((EVALS / "preguntas_acciones.yaml").read_text(encoding="utf-8"))
    ids = [q["id"] for q in conjunto["preguntas"]]
    assert len(ids) == len(set(ids)) >= 20
    permitidos = {"turnos", "id", "categoria", "usuario", "tools_requeridas", "tools_prohibidas", "numeros",
                  "sin_numeros", "contiene", "no_contiene", "permitidos", "propone", "sin_propuesta",
                  "propuesta_contiene", "propuesta_no_contiene"}
    categorias = set()
    for q in conjunto["preguntas"]:
        assert set(q) <= permitidos, q["id"]
        assert q["turnos"] and q["usuario"] in ("ana", "beto", "eva"), q["id"]
        assert not (q.get("propone") and q.get("sin_propuesta")), q["id"]
        categorias.add(q["categoria"])
    assert {"propuesta", "ambigua", "inyeccion", "fuera_de_alcance"} <= categorias


# ───────────────────────── canal de voz ─────────────────────────


def test_voz_sin_resumen_es_un_fallo_solo_en_el_canal_de_voz():
    q = pregunta(numeros=[870.5])
    assert p.puntuar(q, "Son 870,5 ha.", [], BASE, None)["ok"]  # canal de texto: no se exige
    r = p.puntuar(q, "Son 870,5 ha.", [], BASE, None, None, None, "voz")
    assert not r["ok"] and any("resumen hablado" in f for f in r["fallos"])


def test_voz_resumen_breve_hablado_y_respaldado_pasa():
    larga = "Tenés 870,5 hectáreas en total. " + "Detalle por cultivo y por establecimiento. " * 6
    r = p.puntuar(pregunta(numeros=[870.5]), larga, [], BASE, None, None,
                  "Tenés unas 870 hectáreas en total; el desglose está en pantalla.", "voz")
    assert r["ok"], r["fallos"]


@pytest.mark.parametrize("voz,esperado", [
    ("palabra " * 60, "es largo"),
    ("Mirá **870,5** hectáreas", "Markdown"),
    ("Entrá a https://x.test para verlo", "Markdown"),
    ("Tenés 540,5 de soja, 210 de maíz y 120 de otro, y 870,5 en total", "demasiadas cifras"),
    ("Tenés 999 hectáreas", "no respaldada"),
    ("Tenés 872 hectáreas", "no respaldada"),
])
def test_voz_fallos_de_forma_y_de_cifras(voz, esperado):
    larga = "Respuesta completa. " * 30
    r = p.puntuar(pregunta(), larga, [], BASE, None, None, voz, "voz")
    assert not r["ok"] and any(esperado in f for f in r["fallos"]), r["fallos"]


def test_voz_que_lee_la_respuesta_entera_falla_y_la_frase_del_sistema_en_propuestas_no_se_exige():
    corta = "Tenés tres establecimientos: El Matorral, La Esperanza y San Pedro, con soja y maíz como cultivos."
    r = p.puntuar(pregunta(), corta, [], BASE, None, None, corta, "voz")
    assert not r["ok"] and any("más corto" in f for f in r["fallos"])
    prop = [{"tool": "agregar_nota", "resumen": "Agregar una nota", "lineas": []}]
    assert p.puntuar(pregunta(), "Pedí confirmar.", [], BASE, None, prop, None, "voz")["ok"]


def test_voz_criterios_propios_de_la_pregunta():
    q = pregunta(voz={"max_cifras": 1, "contiene": [["pantalla"]], "no_contiene": ["trigo"]})
    larga = "Respuesta completa. " * 30
    assert p.puntuar(q, larga, [], BASE, None, None, "Son 870 hectáreas; mirá la pantalla.", "voz")["ok"]
    r = p.puntuar(q, larga, [], BASE, None, None, "Son 540,5 y 210 de trigo.", "voz")
    assert not r["ok"] and len(r["fallos"]) >= 3


def test_el_set_de_evals_de_voz_es_valido_y_fija_el_canal():
    conjunto = yaml.safe_load((EVALS / "preguntas_voz.yaml").read_text(encoding="utf-8"))
    assert conjunto["canal"] == "voz" and len(conjunto["preguntas"]) >= 10
    ids = [q["id"] for q in conjunto["preguntas"]]
    assert len(ids) == len(set(ids)) and all({"id", "categoria", "usuario", "turnos"} <= q.keys() for q in conjunto["preguntas"])
