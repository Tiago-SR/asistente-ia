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
    for prohibido in ("innerHTML", "outerHTML", "insertAdjacentHTML", "document.write", "eval("):
        assert prohibido not in js.replace("sin innerHTML", ""), prohibido
    # localStorage solo para los ajustes del panel (volumen, motor de voz, acuse): nunca el token ni el chat
    usos = [ln for ln in js.splitlines() if "localStorage." in ln]
    assert usos and all("CLAVE_AJUSTES" in ln for ln in usos), usos


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
    assert '_motorDictado() === "navegador" && this._hablaPosible() && window.isSecureContext !== false' in js
    # el indicador de micrófono abierto y la forma de apagar existen
    assert "mh-apagar" in js and 'e.key === "Escape"' in js and "mhPrivacidad" in js
    # atributos documentados
    assert 'getAttribute("palabra-activacion")' in js and "manos-libres-inactividad" in js
    # sigue sin llamar a ningún otro host
    import re

    assert not re.search(r"fetch\(\s*[\"'`]https?://", js)


# ───────────────────────── tema claro / oscuro ─────────────────────────


def _paleta(js: str, selector: str) -> dict[str, str]:
    import re

    bloque = js.split(f"    {selector} {{\n", 1)[1].split("}", 1)[0]
    return dict(re.findall(r"--p-([\w-]+): (#[0-9a-fA-F]{3,6});", bloque))


def _luminancia(h: str) -> float:
    h = h.lstrip("#")
    if len(h) == 3:
        h = "".join(c * 2 for c in h)
    canales = []
    for i in (0, 2, 4):
        v = int(h[i : i + 2], 16) / 255
        canales.append(v / 12.92 if v <= 0.03928 else ((v + 0.055) / 1.055) ** 2.4)
    return 0.2126 * canales[0] + 0.7152 * canales[1] + 0.0722 * canales[2]


def _contraste(a: str, b: str) -> float:
    la, lb = sorted((_luminancia(a), _luminancia(b)), reverse=True)
    return (la + 0.05) / (lb + 0.05)


def _mezcla(a: str, b: str, pct: float) -> str:
    """color-mix(in srgb, a pct%, b) como hex."""
    def canales(h: str) -> list[int]:
        h = h.lstrip("#")
        h = "".join(c * 2 for c in h) if len(h) == 3 else h
        return [int(h[i : i + 2], 16) for i in (0, 2, 4)]

    ca, cb = canales(a), canales(b)
    return "#" + "".join(f"{round(x * pct + y * (1 - pct)):02x}" for x, y in zip(ca, cb, strict=True))


def test_widget_tema_atributo_y_variables_del_anfitrion_mandan():
    """`tema` (claro|oscuro|auto) sigue prefers-color-scheme y reacciona a su cambio; --asistente-* mandan sobre la paleta."""
    js = _js()
    assert '"tema"' in js and "prefers-color-scheme: dark" in js
    assert 'addEventListener("change", this._alCambiarTema)' in js
    assert 'removeEventListener("change", this._alCambiarTema)' in js  # no deja oyentes al desconectarse
    assert 'getAttribute("tema") || "auto"' in js
    # cambiar `tema` solo repinta: no reinicia la sesión (token, conversación)
    assert 'if (nombre === "tema") { this._aplicarTema(); return; }' in js
    for var, paleta in (("color", "c"), ("color-texto", "ct"), ("fondo", "f"), ("texto", "t"), ("borde", "b")):
        assert f"var(--asistente-{var}, var(--p-{paleta}))" in js, var
    assert "color-scheme: dark" in js and "color-scheme: light" in js
    assert "scrollbar-color" in js


def test_widget_colores_fijos_solo_en_las_paletas():
    """Ningún color literal fuera de las paletas: todo lo demás sale de variables y se adapta al tema."""
    import re

    css = _js().split("const CSS = `", 1)[1].split("`;", 1)[0]
    fuera = re.sub(r"\.raiz(\.oscuro)? \{\n\s+--p-.*?\}", "", css, flags=re.DOTALL)
    literales = re.findall(r"#[0-9a-fA-F]{3,6}\b|rgba?\(", fuera)
    # lo único permitido: sombra y velo del menú lateral (oculto), que son negros translúcidos en ambos temas
    assert [x for x in literales if x != "rgba("] == [], literales
    assert len(literales) <= 2, literales


def test_widget_paletas_cumplen_contraste_wcag_aa():
    """Texto normal ≥ 4,5:1 en ambos temas, sobre cada fondo que usa el widget (incluidos los derivados con color-mix)."""
    js = _js()
    claro, oscuro = _paleta(js, ".raiz"), _paleta(js, ".raiz.oscuro")
    assert set(claro) == set(oscuro) and len(claro) >= 10, (claro, oscuro)
    for nombre, p in (("claro", claro), ("oscuro", oscuro)):
        f, t = p["f"], p["t"]
        suave, codigo = _mezcla(t, f, 0.06), _mezcla(t, f, 0.09)
        apagado = _mezcla(t, f, 0.70)  # --apagado
        pares = {
            "texto/fondo": (t, f), "texto/mensaje del usuario": (t, suave), "texto/código": (t, codigo),
            "apagado/fondo": (apagado, f), "apagado/suave": (apagado, suave), "apagado/código": (apagado, codigo),
            "enlace/fondo": (p["c"], f), "enlace/código": (p["c"], codigo),
            "primario (Confirmar, Enviar)": (p["ct"], p["c"]),
            "error/su fondo": (p["err-t"], p["err-f"]), "error/fondo": (p["err-t"], f),
            "ok/fondo": (p["ok"], f), "micrófono grabando": (p["rec-t"], p["rec"]),
        }
        for par, (a, b) in pares.items():
            assert _contraste(a, b) >= 4.5, (nombre, par, round(_contraste(a, b), 2))
    assert "--apagado: color-mix(in srgb, var(--t) 70%, var(--f))" in js  # el porcentaje que se verificó arriba


# ───────────────────────── modo voz: vista propia, resumen hablado, orbe ─────────────────────────


def test_resumen_breve_de_respaldo_son_dos_oraciones_con_tope():
    r = _utiles_voz(
        """
        const b = (t, m) => U.resumenBreve(t, m);
        return {
          dos: b("Tenés **870,5** ha de soja. Y 88,2 de maíz. Más detalle abajo. Otra más."),
          decimal: b("Superficie total: 1.234,5 hectáreas en dos campos. Ver tabla."),
          una: b("Sin punto final"),
          largo: b("Una oración muy " + "larga ".repeat(80) + "termina. Segunda."),
          tabla: b("| A | B |\\n|---|---|\\n| 1 | 2 |"),
          vacio: b("   "),
        };
        """
    )
    assert r["dos"] == "Tenés 870,5 ha de soja. Y 88,2 de maíz."
    assert r["decimal"] == "Superficie total: 1.234,5 hectáreas en dos campos. Ver tabla."
    assert r["una"] == "Sin punto final"
    assert len(r["largo"]) <= 301 and r["largo"].endswith("…")
    assert "|" not in r["tabla"] and r["vacio"] == ""


def test_comando_de_voz_para_salir_del_modo_voz_y_el_alias_viejo():
    r = _utiles_voz(
        """
        const c = (t) => U.comandoDe(t);
        return [c("Salir del modo voz"), c("apagar modo voz por favor"), c("salir de voz"), c("apagar manos libres"),
                c("quiero salir de voz ahora")];
        """
    )
    assert r == ["apagar", "apagar", "apagar", "apagar", None]


def test_widget_modo_voz_tiene_vista_propia_y_se_alterna_con_el_chat():
    js = _js()
    # el nombre visible cambió; los atributos y las clases internas se conservan
    assert 'manosLibres: "Voz"' in js and 'apagarManosLibres: "Salir del modo voz"' in js and 'verChat: "Ver el chat"' in js
    assert "Manos libres" not in js.split("const CSS", 1)[0].split("const TEXTOS", 1)[1].split("const ERRORES", 1)[0]
    assert 'getAttribute("manos-libres-inactividad")' in js
    # dos vistas: la de voz oculta el chat y el campo, y el panel del micrófono es el mismo en ambas
    for esperado in ('_vista = "chat"', "_aplicarVista(", ".vista-voz .scroll", 'class: "escena"', 'class: "ver-chat"'):
        assert esperado in js, esperado
    aplicar = js.split("_aplicarVista(foco = false) {", 1)[1].split("\n    }\n", 1)[0]
    assert "insertBefore(this._mhCaja" in aplicar and 'toggle("vista-voz"' in aplicar
    # el indicador de micrófono abierto no puede ocultarse: en la vista de chat vuelve sobre la entrada
    assert "this._cajaEntrada.insertBefore(this._mhCaja, this._form)" in aplicar


def test_widget_la_tarjeta_de_confirmacion_siempre_queda_a_la_vista_y_no_se_confirma_por_voz():
    js = _js()
    conf = js.split("_confirmacion(d) {", 1)[1].split("\n    }\n", 1)[0]
    assert 'if (this._vista === "voz") { this._vista = "chat"; this._aplicarVista();' in conf
    assert "this._propuestaTurno = true" in conf
    assert "ev.isTrusted" in js  # solo un clic real confirma
    # ninguna orden de voz confirma una acción: los comandos de voz son enviar, cancelar y apagar
    assert 'confirmar:' not in js.split("const COMANDOS = {", 1)[1].split("};", 1)[0]


def test_widget_modo_voz_pide_el_canal_voz_y_dice_el_resumen_una_sola_vez():
    js = _js()
    assert 'canal: canalVoz ? "voz" : "texto"' in js
    assert 'case "voz": this._marca("voz"); if (hablarVoz) this._resumenHablado(datos.texto, "resumen"); break;' in js
    # la lectura automática de la respuesta completa no corre en el modo voz; el resumen sí, con el altavoz apagado
    assert "const leer = this._leerAuto && !canalVoz && this._hablaPosible();" in js
    res = js.split("_resumenHablado(texto, fuente = \"resumen\") {", 1)[1].split("_mostrarDicho", 1)[0]
    assert "this._dichoTurno ||" in res and "this._propuestaTurno ||" in res and "this._leerCortado" in res
    # respaldo si el modelo no manda el bloque
    assert 'this._resumenHablado(resumenBreve(acumulado), "respaldo")' in js
    # la respuesta completa sigue yendo al chat y con su botón de escuchar
    assert "this._botonEscuchar(burbuja, acumulado)" in js


def test_widget_envia_la_zona_horaria_del_navegador():
    js = _js()
    assert 'zona_horaria: zonaHoraria() });' in js
    fn = js.split("function zonaHoraria() {", 1)[1].split("\n  }\n", 1)[0]
    assert "Intl.DateTimeFormat().resolvedOptions().timeZone" in fn and "catch" in fn  # nunca rompe el envío


def test_widget_orbe_sin_dependencias_ni_mascaras_y_respeta_movimiento_reducido():
    js = _js()
    css = js.split("const CSS = `", 1)[1].split("`;", 1)[0]
    assert "mask" not in css and "<canvas" not in js and "createElement(\"canvas\")" not in js and "filter:" not in css
    # todas las animaciones del orbe viven bajo prefers-reduced-motion: no-preference
    import re

    fuera = re.sub(r"@media \(prefers-reduced-motion: no-preference\) \{.*?\n    \}\n", "", css, flags=re.DOTALL)
    uso_animaciones = [l for l in fuera.splitlines() if "animation:" in l and ".mh" in l]
    assert uso_animaciones == [], uso_animaciones
    # cada estado tiene su glifo: se distinguen sin movimiento ni color
    for estado, glifo in (("armado", "g-mic"), ("capturando", "g-esc"), ("confirmando", "g-pausa"),
                          ("procesando", "g-pensar"), ("hablando", "g-habla")):
        assert f'.mh[data-estado="{estado}"] .{glifo}' in css, estado
    # el orbe es decorativo: el texto aria-live existente (.mh-estado) es lo que anuncia el estado
    assert 'class: "orbe", "aria-hidden": "true"' in js and 'class: "mh-estado", role: "status", "aria-live": "polite"' in js


def test_widget_paleta_pausa_es_distinguible_del_fondo():
    """El ámbar de «confirmando» es gráfico (anillo), no texto: pide 3:1 contra el fondo (WCAG 1.4.11)."""
    js = _js()
    for nombre, selector in (("claro", ".raiz"), ("oscuro", ".raiz.oscuro")):
        p = _paleta(js, selector)
        assert _contraste(p["pausa"], p["f"]) >= 3, (nombre, round(_contraste(p["pausa"], p["f"]), 2))
        assert _contraste(p["c"], p["f"]) >= 3, nombre


# ───────────────────────── volumen del orbe y tiempos del turno por voz ─────────────────────────


def test_nivel_de_volumen_a_partir_de_muestras_de_audio():
    r = _utiles_voz(
        """
        const mk = (amp, n = 512) => Uint8Array.from({ length: n }, (_, i) => 128 + (i % 2 ? amp : -amp));
        return { silencio: U.nivelDe(mk(0)), bajo: U.nivelDe(mk(4)), hablando: U.nivelDe(mk(25)), fuerte: U.nivelDe(mk(120)),
                 vacio: U.nivelDe(new Uint8Array(0)), nulo: U.nivelDe(null) };
        """
    )
    assert r["silencio"] == 0 and r["vacio"] == 0 and r["nulo"] == 0
    assert 0 < r["bajo"] < r["hablando"] < r["fuerte"] <= 1
    assert r["bajo"] < 0.15 and r["hablando"] > 0.3  # el ruido de fondo casi no mueve el orbe; la voz sí


def test_suavizado_sube_rapido_y_baja_despacio_sin_pasarse():
    r = _utiles_voz(
        """
        const sube = U.suavizar(0, 1, 1 / 30), baja = U.suavizar(1, 0, 1 / 30);
        let v = 0; for (let i = 0; i < 60; i++) v = U.suavizar(v, 0.5, 1 / 30);
        return { sube, baja, converge: v, tope: U.suavizar(0, 1, 5), igual: U.suavizar(0.4, 0.4, 0.1) };
        """
    )
    assert r["sube"] > 1 - r["baja"]  # el ataque es más rápido que la caída
    assert abs(r["converge"] - 0.5) < 0.01 and r["tope"] == 1 and r["igual"] == 0.4


def test_widget_volumen_del_orbe_es_local_degradable_y_respeta_movimiento_reducido():
    js = _js()
    niv = js.split("async _nivelIniciar() {", 1)[1].split("_nivelPulso(x)", 1)[0]
    # solo se mide: el flujo no se graba ni se envía; ningún fetch ni MediaRecorder en el camino del nivel
    assert "fetch(" not in niv and "MediaRecorder" not in niv and "sendBeacon" not in niv
    # sin movimiento no se abre nada; con orbe-volumen="no" tampoco; un fallo se traga y el orbe sigue sin nivel
    assert 'prefers-reduced-motion: reduce' in niv and 'getAttribute("orbe-volumen")' in niv and "catch { /* sin nivel de micrófono */ }" in niv
    # se apaga con el modo: se paran las pistas, se cierra el contexto y se cancela el bucle
    det = js.split("_nivelDetener() {", 1)[1].split("\n    }\n", 1)[0]
    assert "t.stop()" in det and "ctx.close()" in det and "cancelAnimationFrame" in det
    assert "this._nivelDetener();" in js.split("_mhApagar(motivo, silencioso = false) {", 1)[1].split("\n    }\n", 1)[0]
    # mientras habla el asistente no se lee el micrófono (se oiría a él) y la voz del asistente da pulsos por palabra
    assert 'e === "armado" || e === "capturando" || e === "confirmando"' in niv.split("_nivelBucle() {", 1)[0] + js.split("_nivelBucle() {", 1)[1]
    assert "u.onboundary" in js
    assert "--nivel" in js and ".o-nivel { display: none !important; }" in js


def test_widget_tiempos_del_turno_por_voz_sin_datos_del_usuario():
    js = _js()
    for esperado in ('"asistente:metricas"', "primer_delta_ms", "voz_ms", "habla_ms", "tts_ms", "servidor: t.servidor"):
        assert esperado in js, esperado
    met = js.split("_metricasIntentar(forzar = false) {", 1)[1].split("\n    }\n", 1)[0]
    # el evento lleva solo números y la fuente («resumen» o «respaldo»): ni el mensaje ni la respuesta
    assert "mensaje" not in met and "texto:" not in met and "acumulado" not in met
    assert 'case "voz": this._marca("voz");' in js and "tiempos_ms" in js


# ───────────────────────── acuse inmediato del modo voz ─────────────────────────


def test_widget_acuse_solo_cuando_hace_falta_y_nunca_con_acciones():
    js = _js()
    assert "const MH_ACUSE_MS = 900;" in js
    acuse = js.split("_acuseProgramar() {", 1)[1].split("\n    }\n", 1)[0]
    # solo con el modo voz, voz disponible y sin «acuse=no» ni acuse apagado por el usuario; texto fijo (sin datos ni LLM)
    assert "_acuseActivo()" in acuse and "_hablaPosible()" in acuse
    activo = js.split("_acuseActivo() {", 1)[1].split("\n    }\n", 1)[0]
    assert 'getAttribute("acuse")' in activo
    assert "fetch(" not in acuse and "textoParaVoz" not in acuse
    # no se dice si el resumen ya llegó, si el turno propuso una acción, si se interrumpió, si terminó o si se apagó
    for guarda in ("!this._mhActivo()", "this._t !== t", "!this._ocupado", "this._dichoTurno", "this._propuestaTurno", "this._leerCortado"):
        assert guarda in acuse, guarda
    # se programa solo en el modo voz, se cancela al apagarlo y se informa en las métricas
    assert "this._metricasIniciar(); this._acuseProgramar();" in js
    assert "clearTimeout(this._tAcuse);" in js.split("_mhApagar(motivo, silencioso = false) {", 1)[1].split("\n    }\n", 1)[0]
    assert "acuse_ms: ms(t.acuse)" in js
    # varias frases cortas, sin cifras ni nombres (es texto fijo)
    frases = js.split("mhAcuse: [", 1)[1].split("]", 1)[0]
    assert frases.count('"') >= 6 and not any(c.isdigit() for c in frases)


def test_widget_un_turno_nuevo_empieza_sin_interrumpido():
    """Dictar con la palabra de activación pone _leerCortado en true; si el turno no lo limpia al enviar, el acuse y el resumen no suenan."""
    js = _js()
    envio = js.split("async _enviarMensaje(texto) {", 1)[1].split("this._bloquear(true);", 1)[0]
    assert "this._leerCortado = false;" in envio and envio.index("this._leerCortado = false;") < envio.index("this._acuseProgramar();")


# ───────────────────────── memoria por usuario: tarjeta local y panel «Lo que recuerdo» ─────────────────────────


def test_widget_tarjeta_local_confirma_con_la_sesion_y_no_pide_token_al_anfitrion():
    js = _js()
    cuerpo = js.split("async _confirmarAccion(t) {", 1)[1].split("async _cancelarAccion", 1)[0]
    rama_local, rama_anfitrion = cuerpo.split("} else {", 1)
    assert "t.d.local === true" in rama_local and "/confirmar-local`" in rama_local
    assert "_conToken" in rama_local  # la sesión normal de lectura
    # la rama local no toca el token-url del anfitrión (ni su token de escritura)
    for prohibido in ("_tokenEscritura", "token-url", "searchParams", "Bearer"):
        assert prohibido not in rama_local, prohibido
    # la del anfitrión sigue igual: token de escritura del sistema y /confirmar
    assert "await this._tokenEscritura(t.d)" in rama_anfitrion and "/confirmar`" in rama_anfitrion
    assert "confirmar-local" not in rama_anfitrion
    # solo _confirmarAccion llama a _tokenEscritura (y solo en la rama del anfitrión)
    assert js.count("this._tokenEscritura(") == 1
    # el clic humano sigue siendo la única confirmación, también para las tarjetas locales
    assert 'confirmar.addEventListener("click", (ev) => { if (ev.isTrusted) this._confirmarAccion(t); });' in js


def test_widget_la_tarjeta_local_se_ve_igual_y_se_restaura_con_su_marca():
    js = _js()
    conf = js.split("_confirmacion(d) {", 1)[1].split("\n    }\n", 1)[0]
    assert "local" not in conf.replace("localStorage", "")  # nada distinto al pintarla: mismos botones y modo voz
    assert "if (d.pendiente) this._confirmacion(d.pendiente);" in js  # lo restaurado conserva `local` (viene en d)


def test_widget_panel_de_memoria_solo_con_el_estado_del_servicio_y_sin_innerhtml():
    js = _js()
    assert "this._memoria = e.memoria === true;" in js
    assert "this._memBtn.hidden = !(habilitado && this._memoria);" in js
    assert 'class: "accion memoria", type: "button", hidden: true' in js  # nace oculto
    assert "_memoriaAbrir() {\n      if (!this._memoria) return;" in js
    panel = js.split("// — memoria por usuario: panel", 1)[1].split("// — acciones con confirmación", 1)[0]
    for prohibido in ("innerHTML", "outerHTML", "insertAdjacentHTML", "document.write", "eval(", "localStorage"):
        assert prohibido not in panel, prohibido
    assert "textContent: x.descripcion" in panel and "replaceChildren" in panel
    # lo que dice el servidor (descripcion, tipo, fecha) entra solo como texto
    assert panel.count("textContent") >= 6
    # usa los endpoints del contrato: listar, borrar uno y borrar todo, con la sesión normal
    assert '"/v1/memoria"' in panel and 'method: "DELETE"' in panel and "encodeURIComponent(id)" in panel
    assert "_conToken" in panel
    # Escape lo cierra y no apaga el modo voz que pudiera estar debajo
    assert 'e.key === "Escape") { e.stopPropagation(); this._memoriaCerrar(); }' in panel
    # en la vista de voz el botón no está
    assert ".vista-voz .barra .memoria" in js


def test_widget_panel_de_memoria_borra_sin_confirmacion_pero_nunca_guarda():
    """Olvidar es un clic del propio usuario; guardar solo existe por la tarjeta (nada en el panel crea recuerdos)."""
    panel = _js().split("// — memoria por usuario: panel", 1)[1].split("// — acciones con confirmación", 1)[0]
    assert "window.confirm" not in panel and "confirm(" not in panel
    assert 'method: "POST"' not in panel and 'method: "PUT"' not in panel


def test_widget_panel_de_memoria_usa_solo_colores_de_la_paleta_con_contraste_verificado():
    """El panel usa solo las combinaciones que ya verifica test_widget_paletas_cumplen_contraste_wcag_aa:
    texto/fondo, apagado/fondo, color/fondo (botones), color-texto/color (hover) y error/fondo."""
    import re

    css = _js().split("const CSS = `", 1)[1].split("`;", 1)[0]
    bloque = css.split("/* Panel «Lo que recuerdo»", 1)[1].split(".entrada { padding", 1)[0]
    assert re.findall(r"#[0-9a-fA-F]{3,6}\b|rgba?\(|color-mix", bloque) == []
    colores = set(re.findall(r"(?<![-\w])(?:color|background|border-color|background-color):\s*(var\(--[\w-]+\))", bloque))
    assert colores <= {"var(--c)", "var(--ct)", "var(--f)", "var(--apagado)", "var(--p-err-t)", "var(--b)"}, colores
    # texto con un color de acento o de error solo sobre el fondo del tema (verificado ≥ 4,5:1)
    assert ".mem-error { margin-top: 6px; font-size: 13px; color: var(--p-err-t); }" in bloque
    assert ".mem-lista li { display: flex; align-items: center; gap: 10px; padding: 10px 12px; border: 1px solid var(--b); border-radius: var(--r); background: var(--f); }" in bloque
    # los botones de la barra respetan el foco visible y el tamaño táctil de los demás
    assert "aria-expanded" in _js() and 'role: "dialog"' in _js()


def test_widget_textos_de_memoria_en_espanol_rioplatense():
    js = _js()
    for frase in ("Lo que recuerdo", "Olvidar todo", "Podés pedirme", "Listo, lo olvidé."):
        assert frase in js, frase


def test_widget_ajustes_del_usuario_solo_guardan_preferencias_y_llegan_a_las_dos_voces():
    js = _js()
    # lo único que se persiste es `this._aj`: motor, volumen y acuse (sin token ni texto)
    assert 'const AJUSTES_BASE = { motor: "auto", volumen: 1, acuse: true };' in js
    assert "JSON.stringify(this._aj)" in js
    # el volumen del panel llega a la voz del navegador y al audio del servidor; el motor se resuelve en un método
    assert "u.volume = this._volumen();" in js and "a.volume = this._volumen();" in js
    prefs = js.split("_prefRespuesta() {", 1)[1].split("\n    }\n", 1)[0]
    assert "this._aj.motor" in prefs and 'getAttribute("voz-respuesta")' in prefs
    # ajustes="no" quita el panel y deja mandar a los atributos del anfitrión
    assert 'getAttribute("ajustes")' in js.split("_ajustesActivos() {", 1)[1].split("\n", 1)[0]
