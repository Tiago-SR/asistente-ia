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
    """El contenido del modelo solo entra al DOM como nodos de texto."""
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
    """sessionStorage solo guarda el id de la conversación; el token vive en memoria."""
    import re

    js = _js()
    usos = re.findall(r"sessionStorage\.\w+Item\(([^)]*)\)", js)
    assert usos, "debería recordar la conversación"
    assert "token" not in "".join(usos).lower(), usos
    assert 'setItem(clave, this._convId)' in js  # lo único que se escribe es el id


def test_widget_dictado_solo_con_capacidad_y_sin_envio_automatico():
    """El micrófono nace oculto, se muestra con voz.dictado y solo rellena el campo (contrato, sección 7.4)."""
    js = _js()
    assert 'class: "mic", hidden: true' in js
    assert "voz.dictado === true" in js
    assert "/v1/voz/transcribir" in js and "X-Audio-Duracion-S" in js
    assert "MediaRecorder" in js and "max_audio_s" in js
    # el texto transcrito va al campo; ni _transcribir ni el dictado del navegador envían el mensaje
    cuerpo = js.split("async _transcribir(", 1)[1].split("// — chat —", 1)[0]
    assert "_anadirAlCampo" in cuerpo
    assert "_enviarForm" not in cuerpo and "_enviarMensaje" not in cuerpo
    reco = js.split("_iniciarReco() {", 1)[1].split("_detenerReco(cancelar)", 1)[0]
    assert "_anadirAlCampo" in reco
    assert "_enviarForm" not in reco and "_enviarMensaje" not in reco
    campo = js.split("_anadirAlCampo(texto) {", 1)[1].split("// Dictado con el reconocimiento", 1)[0]
    assert "_entrada.value" in campo and "_enviar" not in campo.replace("_entrada", "")


def test_widget_voz_del_navegador_no_manda_audio_a_terceros_por_su_cuenta():
    """El widget solo usa Web Speech (lo procesa el navegador) o el STT del propio asistente; nunca llama a otro host."""
    import re

    js = _js()
    assert "SpeechRecognition" in js and "speechSynthesis" in js
    assert "voz-motor" in js  # el sistema anfitrión puede forzar el STT del servidor y evitar a Google
    assert not re.search(r"fetch\(\s*[\"'`]https?://", js)


def _utiles_voz(casos: str):
    """Ejecuta `casos` (JS que usa U = utilidades de voz) con el widget cargado en node y devuelve el JSON impreso."""
    import json
    import shutil
    import subprocess
    from pathlib import Path

    import pytest

    node = shutil.which("node")
    if not node:
        pytest.skip("node no disponible")
    ruta = Path(__file__).resolve().parent.parent / "src/asistente/static/widget.js"
    prog = (
        "globalThis.window = globalThis; globalThis.document = { currentScript: null };"
        "let C; globalThis.customElements = { get() {}, define(n, c) { C = c; } };"
        "globalThis.HTMLElement = class {};"
        f"require({json.dumps(str(ruta))}); const U = C._utiles;"
        f"console.log(JSON.stringify((() => {{ {casos} }})()));"
    )
    r = subprocess.run([node, "-e", prog], capture_output=True, text=True, check=False)
    assert r.returncode == 0, r.stderr
    return json.loads(r.stdout)


def test_texto_para_voz_quita_markdown_y_conserva_cifras():
    md = (
        "**Resumen** de `soja`:\n\n| Cultivo | Hectáreas |\n|---|---|\n| Soja | 870,5 |\n| Maíz | 88,2 |\n\n"
        "- Ver [el detalle](https://x.test/a)\n- tool resumen_por_cultivo\n\n```js\ncodigo()\n```\nFin."
    )
    plano = _utiles_voz(f"return U.textoParaVoz({__import__('json').dumps(md)});")
    assert "870,5" in plano and "88,2" in plano
    for prohibido in ("**", "`", "|", "---", "https://", "codigo()", "[", "]"):
        assert prohibido not in plano, (prohibido, plano)
    assert "Ver el detalle" in plano
    assert "resumen por cultivo" in plano  # los guiones bajos de los nombres no se leen pegados


def test_ultimo_corte_solo_corta_en_oraciones_completas():
    r = _utiles_voz(
        """
        const t = "Tenés 1.234,5 hectáreas. Querés compararlas? Sí y despu";
        const a = U.ultimoCorte(t, 0);
        const b = U.ultimoCorte("Tenés 870,5 hectáreas", 0);
        return { primero: t.slice(0, a), sin_oracion: b, desde: U.ultimoCorte(t, a) };
        """
    )
    assert r["primero"] == "Tenés 1.234,5 hectáreas. Querés compararlas?"  # el decimal no corta; lo incompleto espera
    assert r["sin_oracion"] == 0
    assert r["desde"] == len(r["primero"])


def test_elegir_voz_prefiere_idioma_pedido_luego_es_es_luego_cualquier_es():
    r = _utiles_voz(
        """
        const v = (name, lang) => ({ name, lang });
        const voces = [v("Inglesa", "en-US"), v("Mexicana", "es-MX"), v("Española", "es-ES"), v("Uruguaya", "es-UY")];
        return {
          exacta: U.elegirVoz(voces, "es-UY").name,
          sin_uy: U.elegirVoz(voces.slice(0, 3), "es-UY").name,
          sin_es_es: U.elegirVoz([voces[0], voces[1]], "es-UY").name,
          por_nombre: U.elegirVoz(voces, "es-UY", "Mexicana").name,
          guion_bajo: U.elegirVoz([v("X", "es_AR")], "es-AR").name,
          ninguna: U.elegirVoz([voces[0]], "es-UY"),
        };
        """
    )
    assert r == {"exacta": "Uruguaya", "sin_uy": "Española", "sin_es_es": "Mexicana", "por_nombre": "Mexicana",
                 "guion_bajo": "X", "ninguna": None}


def test_widget_historial_oculto_no_toca_la_lista():
    """Con MOSTRAR_HISTORIAL=false _pintarHistorial no hace nada: si lanzara, _abrir lo capturaría y olvidaría el id."""
    js = _js()
    assert "MOSTRAR_HISTORIAL = false" in js
    assert "_pintarHistorial() {\n      if (!MOSTRAR_HISTORIAL) return;" in js


# ───────────────────────── modo «manos libres» ─────────────────────────


def test_buscar_activacion_solo_al_comienzo_de_la_frase():
    r = _utiles_voz(
        """
        const b = (t, p = "asistente") => U.buscarActivacion(t, p);
        return {
          sola: b("asistente"),
          con_pregunta: b("Asistente, ¿cuántas hectáreas de soja tengo?"),
          sin_acento_y_mayusculas: b("ASISTENTE cuántas hectáreas"),
          con_muletilla: b("oye asistente dame el resumen"),
          muy_adentro: b("dime lo que pasa con el asistente de ayer"),
          ausente: b("buenos días a todos"),
          vacia: b(""),
          compuesta: U.buscarActivacion("hola jarvis, abrí el mapa", "hola jarvis"),
          sin_palabra: U.buscarActivacion("asistente hola", ""),
        };
        """
    )
    assert r == {
        "sola": "",
        "con_pregunta": "cuántas hectáreas de soja tengo?",
        "sin_acento_y_mayusculas": "cuántas hectáreas",
        "con_muletilla": "dame el resumen",
        "muy_adentro": None,
        "ausente": None,
        "vacia": None,
        "compuesta": "abrí el mapa",
        "sin_palabra": None,
    }


def test_comandos_solo_valen_como_frase_entera():
    r = _utiles_voz(
        """
        const c = (t) => U.comandoDe(t);
        return {
          enviar: c("Enviar"), enviar_punto: c("enviar."), enviar_voseo: c("¡Enviá!"), por_favor: c("enviar por favor"),
          cancelar: c("cancelar"), descartar: c("descartá"),
          apagar: c("Apagar manos libres"),
          dentro_de_frase: c("quiero enviar un informe"), cancelar_cuota: c("cancelar la cuota de ayer"), nada: c(""),
        };
        """
    )
    assert r == {
        "enviar": "enviar", "enviar_punto": "enviar", "enviar_voseo": "enviar", "por_favor": "enviar",
        "cancelar": "cancelar", "descartar": "cancelar", "apagar": "apagar",
        "dentro_de_frase": None, "cancelar_cuota": None, "nada": None,
    }


def test_interpretar_segun_el_estado():
    r = _utiles_voz(
        """
        const i = (e, t, final = true) => U.interpretar(e, t, "asistente", final);
        return {
          armado_ruido: i("armado", "qué lindo día hace hoy"),
          armado_enviar: i("armado", "enviar"),
          armado_activa: i("armado", "asistente cuántas hectáreas"),
          armado_activa_parcial: i("armado", "asistente", false),
          respondiendo_activa: i("respondiendo", "oye asistente"),
          capturando_texto: i("capturando", "de soja tengo"),
          capturando_enviar: i("capturando", "enviar"),
          capturando_enviar_parcial: i("capturando", "enviar", false),
          confirmando_cancelar: i("confirmando", "cancelar"),
          confirmando_texto: i("confirmando", "y de maíz"),
          apagar_armado: i("armado", "apagar manos libres"),
          apagar_capturando: i("capturando", "apagar manos libres"),
          apagado: i("apagado", "asistente hola"),
          vacio: i("capturando", "  "),
        };
        """
    )
    assert r["armado_ruido"] == {"accion": "ignorar"}
    assert r["armado_enviar"] == {"accion": "ignorar"}  # sin activación no hay comandos: nada se envía solo
    assert r["armado_activa"] == {"accion": "activar", "resto": "cuántas hectáreas"}
    assert r["armado_activa_parcial"] == {"accion": "activar", "resto": ""}  # la activación reacciona ya con el parcial
    assert r["respondiendo_activa"] == {"accion": "activar", "resto": ""}      # interrumpe la lectura
    assert r["capturando_texto"] == {"accion": "texto", "texto": "de soja tengo"}
    assert r["capturando_enviar"] == {"accion": "enviar"}
    assert r["capturando_enviar_parcial"] == {"accion": "texto", "texto": "enviar"}  # un comando parcial no dispara
    assert r["confirmando_cancelar"] == {"accion": "cancelar"}
    assert r["confirmando_texto"] == {"accion": "texto", "texto": "y de maíz"}
    assert r["apagar_armado"] == {"accion": "apagar"} and r["apagar_capturando"] == {"accion": "apagar"}
    assert r["apagado"] == {"accion": "ignorar"} and r["vacio"] == {"accion": "ignorar"}


def test_reinicio_del_reconocedor_crece_y_tiene_tope():
    r = _utiles_voz("return [0, 1, 2, 3, 4, 5, 10].map((n) => U.retrasoReinicio(n));")
    assert r == [250, 500, 1000, 2000, 4000, 5000, 5000]


def test_widget_manos_libres_pide_confirmacion_y_es_opcional():
    """Nada se envía solo salvo que se cambie la constante; el modo no existe sin Web Speech ni en voz-motor=servidor."""
    js = _js()
    assert "const MANOS_LIBRES_CONFIRMAR = true;" in js
    # un único camino de envío: el cierre de frase solo envía si la constante lo pide
    cierre = js.split("_mhCerrarFrase() {", 1)[1].split("// Envía lo que hay", 1)[0]
    assert "if (!MANOS_LIBRES_CONFIRMAR) this._mhEnviarTexto();" in cierre
    # los comandos de voz solo se interpretan con frases finales
    assert 'const cmd = final ? comandoDe(texto) : null;' in js
    # oculto por defecto; se muestra solo con el reconocimiento del navegador, síntesis y contexto seguro
    assert 'class: "manos", type: "button", hidden: true' in js
    assert '_motorDictado() === "navegador" && puedeHablar() && window.isSecureContext !== false' in js
    # el indicador de micrófono abierto y la forma de apagar existen
    assert "mh-apagar" in js and 'e.key === "Escape"' in js and "mhPrivacidad" in js
    # atributos documentados
    assert 'getAttribute("palabra-activacion")' in js and "manos-libres-inactividad" in js
    # sigue sin llamar a ningún otro host
    import re

    assert not re.search(r"fetch\(\s*[\"'`]https?://", js)
