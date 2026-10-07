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


def test_widget_solo_un_clic_real_confirma_y_ninguna_orden_de_voz():
    js = _js()
    assert "ev.isTrusted" in js  # solo un clic real confirma
    # ninguna orden de voz confirma una acción: los comandos de voz son enviar, cancelar y apagar
    assert 'confirmar:' not in js.split("const COMANDOS = {", 1)[1].split("};", 1)[0]


def test_widget_envia_la_zona_horaria_del_navegador():
    js = _js()
    assert 'zona_horaria: zonaHoraria() });' in js
    fn = js.split("function zonaHoraria() {", 1)[1].split("\n  }\n", 1)[0]
    assert "Intl.DateTimeFormat().resolvedOptions().timeZone" in fn and "catch" in fn  # nunca rompe el envío


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


# ───────────────────────── acuse inmediato del modo voz ─────────────────────────


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


def test_widget_panel_de_memoria_borra_sin_confirmacion_pero_nunca_guarda():
    """Olvidar es un clic del propio usuario; guardar solo existe por la tarjeta (nada en el panel crea recuerdos)."""
    panel = _js().split("// — memoria por usuario: panel", 1)[1].split("// — acciones con confirmación", 1)[0]
    assert "window.confirm" not in panel and "confirm(" not in panel
    assert 'method: "POST"' not in panel and 'method: "PUT"' not in panel


def test_widget_el_nombre_del_asistente_es_la_palabra_de_activacion():
    js = _js()
    # palabra-activacion del anfitrión > nombre del asistente > «asistente»
    assert 'this.getAttribute("palabra-activacion")?.trim() || (this._nombre() !== NOMBRE_BASE ? this._nombre() : PALABRA_ACTIVACION)' in js
