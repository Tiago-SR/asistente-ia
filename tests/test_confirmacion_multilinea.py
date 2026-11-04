import httpx

from asistente.sistemas.conector_http import _interpretar_propuesta


def test_todas_las_lineas_son_visibles():
    detalle = [f"Línea {i}: " + "x" * 200 for i in range(100)]
    r = _interpretar_propuesta(httpx.Response(200, json={"ok": True, "resumen": "Comprobante",
                                "huella": "12345678", "detalle": detalle}), 120)
    assert r.ok
    assert list(r.lineas) == detalle


def test_detalle_excesivo_se_rechaza_sin_truncar():
    r = _interpretar_propuesta(httpx.Response(200, json={"ok": True, "resumen": "Comprobante",
                                "huella": "12345678", "detalle": ["x"] * 501}), 120)
    assert not r.ok
