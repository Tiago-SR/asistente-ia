import httpx

from asistente.core.voz import catalogo
from asistente.core.voz.elevenlabs import TtsElevenLabs


def _yaml(tmp_path, texto):
    p = tmp_path / "voces.yaml"
    p.write_text(texto, encoding="utf-8")
    return p


def test_sin_archivo_la_voz_unica_es_tts_voz_id(tmp_path):
    c = catalogo.cargar(tmp_path / "no.yaml", "V1")
    assert [v.voz_id for v in c.voces] == ["V1"] and c.resolver(None).voz_id == "V1"
    assert not catalogo.cargar(tmp_path / "no.yaml", None)


def test_voz_id_literal_o_de_entorno_y_la_pendiente_se_ignora(tmp_path):
    p = _yaml(tmp_path, """
voces:
  - {id: m, etiqueta: Mateo, genero: masculina, voz_id_env: A}
  - {id: f, etiqueta: Lucia, genero: femenina, voz_id_env: FALTA}
  - {id: f2, genero: femenina, voz_id: LIT}
defecto: m
""")
    c = catalogo.cargar(p, env={"A": "EL_A"})
    assert [(v.id, v.voz_id) for v in c.voces] == [("m", "EL_A"), ("f2", "LIT")]
    assert c.publico()[1] == {"id": "f2", "etiqueta": "f2", "genero": "femenina"}


def test_resolver_cae_a_la_predeterminada_y_esta_a_la_primera(tmp_path):
    p = _yaml(tmp_path, "voces:\n  - {id: a, voz_id: X}\n  - {id: b, voz_id: Y}\ndefecto: no_existe\n")
    c = catalogo.cargar(p, env={})
    assert c.defecto == "a" and c.resolver("b").voz_id == "Y" and c.resolver("zzz").voz_id == "X"


def test_genero_invalido_e_ids_repetidos(tmp_path):
    p = _yaml(tmp_path, "voces:\n  - {id: a, genero: robot, voz_id: X}\n  - {id: a, voz_id: Y}\n")
    c = catalogo.cargar(p, env={})
    assert len(c.voces) == 1 and c.voces[0].genero is None


async def test_el_adaptador_usa_la_voz_pedida_o_la_suya():
    vistas = []

    def handler(req):
        vistas.append(req.url.path)
        return httpx.Response(200, content=b"MP3")

    tts = TtsElevenLabs("k", "base", "m", base_url="http://t/v1", cliente=httpx.AsyncClient(transport=httpx.MockTransport(handler)))
    await tts.sintetizar("x")
    await tts.sintetizar("x", voz_id="otra")
    assert vistas == ["/v1/text-to-speech/base", "/v1/text-to-speech/otra"]


def test_el_voces_yaml_del_repo_es_valido():
    from pathlib import Path

    import pytest

    ruta = next((r for r in (Path(__file__).parent.parent / "config" / "voces.yaml", Path("/config/voces.yaml")) if r.is_file()), None)
    if ruta is None:
        pytest.skip("no está config/voces.yaml")
    c = catalogo.cargar(ruta, env={"TTS_VOZ_ID": "X", "TTS_VOZ_ID_FEMENINA": "Y"})
    ids = [v.id for v in c.voces]
    assert c.voces and c.defecto in ids and len(ids) == len(set(ids))
    assert all(v.genero in (None, "femenina", "masculina") and v.voz_id for v in c.voces)
