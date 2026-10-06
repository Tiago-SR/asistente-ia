"""Tarifa de la voz del servidor (por carácter) en `precios.py`."""

import pytest

from asistente import precios


def test_costo_tts_es_proporcional_a_los_caracteres():
    tarifa = {"usd_por_1k_caracteres": 0.04}
    assert precios.costo_tts(1000, tarifa) == pytest.approx(0.04)
    assert precios.costo_tts(0, tarifa) == 0
    assert precios.costo_tts(273_000, tarifa) == pytest.approx(10.92)


def test_costo_tts_sin_tarifa_no_se_inventa():
    assert precios.costo_tts(1000, None) is None
    assert precios.costo_tts(1000, {}) is None


def test_la_clave_de_tarifa_no_choca_con_un_modelo_de_llm():
    assert precios.clave_tts("elevenlabs", "eleven_flash_v2_5") == "elevenlabs:eleven_flash_v2_5"


def test_precios_yaml_trae_la_tarifa_del_modelo_configurado_en_el_entorno_de_desarrollo():
    from pathlib import Path

    raiz = Path(__file__).resolve().parent.parent / "config" / "precios.yaml"
    if not raiz.is_file():   # el contenedor lo monta en /config
        raiz = Path("/config/precios.yaml")
    tarifas = precios.cargar(raiz)
    assert tarifas[precios.clave_tts("elevenlabs", "eleven_flash_v2_5")]["usd_por_1k_caracteres"] == 0.04
