from fastapi.testclient import TestClient

from asistente.main import app


def test_widget_se_sirve_publico_con_etag():
    c = TestClient(app)
    r = c.get("/widget.js")
    assert r.status_code == 200
    assert r.headers["content-type"].startswith("text/javascript")
    assert "customElements.define(\"asistente-chat\"" in r.text
    etag = r.headers["etag"]
    assert c.get("/widget.js", headers={"If-None-Match": etag}).status_code == 304


def test_widget_no_usa_innerhtml_ni_storage():
    """El contenido del modelo solo entra al DOM como nodos de texto (sección 9)."""
    from pathlib import Path

    js = (Path(__file__).resolve().parent.parent / "src/asistente/static/widget.js").read_text()
    for prohibido in ("innerHTML", "outerHTML", "insertAdjacentHTML", "document.write",
                      "localStorage", "eval("):
        assert prohibido not in js.replace("sin innerHTML", ""), prohibido


def _js():
    from pathlib import Path

    return (Path(__file__).resolve().parent.parent / "src/asistente/static/widget.js").read_text()


def test_widget_es_solo_vista_completa():
    """Sin burbuja flotante, lanzador ni modos: el componente ocupa su contenedor."""
    js = _js()
    for descartado in ("flotante", "incrustado", "lanzador", "position: fixed", "_alternar", '"modo"'):
        assert descartado not in js, descartado
    for esperado in ('class: "lateral"', 'class: "principal"', "height: 100%", "max-width: 720px"):
        assert esperado in js, esperado


def test_widget_sintaxis_valida():
    import shutil
    import subprocess
    from pathlib import Path

    import pytest

    node = shutil.which("node")
    if not node:
        pytest.skip("node no disponible")
    ruta = Path(__file__).resolve().parent.parent / "src/asistente/static/widget.js"
    r = subprocess.run([node, "--check", str(ruta)], capture_output=True, text=True, check=False)
    assert r.returncode == 0, r.stderr


def test_widget_solo_recuerda_el_id_de_conversacion():
    """sessionStorage solo guarda el id de la conversación; el token vive en memoria (sección 9)."""
    import re

    js = _js()
    usos = re.findall(r"sessionStorage\.\w+Item\(([^)]*)\)", js)
    assert usos, "debería recordar la conversación"
    assert "token" not in "".join(usos).lower(), usos
    assert 'setItem(clave, this._convId)' in js  # lo único que se escribe es el id


def test_widget_dictado_solo_con_capacidad_y_sin_envio_automatico():
    """El micrófono nace oculto, se muestra con voz.dictado y solo rellena el campo (sección 7.7)."""
    js = _js()
    assert 'class: "mic", hidden: true' in js
    assert "voz.dictado === true" in js
    assert "/v1/voz/transcribir" in js and "X-Audio-Duracion-S" in js
    assert "MediaRecorder" in js and "max_audio_s" in js
    # el texto transcrito va al campo; _transcribir no debe enviar el mensaje
    cuerpo = js.split("async _transcribir(", 1)[1].split("// — chat —", 1)[0]
    assert "_entrada.value" in cuerpo
    assert "_enviarForm" not in cuerpo and "_enviarMensaje" not in cuerpo
