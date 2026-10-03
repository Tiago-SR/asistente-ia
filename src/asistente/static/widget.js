/*
 * <asistente-chat> — widget de chat del Asistente (sección 9 del plan).
 *
 * Web Component sin dependencias ni build. Shadow DOM, sin innerHTML: todo el contenido
 * (incluido el Markdown del modelo) se construye con nodos DOM, así que no hay inyección.
 *
 * Es una vista de chat a pantalla completa: ocupa el 100% del alto y ancho de su contenedor
 * (el anfitrión le da tamaño, p. ej. style="display:block;height:100vh"). No es un popup ni se
 * superpone a la página. Muestra solo la conversación actual (botón "Nueva conversación" en la
 * barra superior); el historial de chats está oculto (ver MOSTRAR_HISTORIAL).
 *
 * Atributos:
 *   token-url   (obligatorio) ruta del sistema anfitrión que emite el token; se pide con
 *               las cookies de sesión del anfitrión. Responde {token, expira}.
 *   servidor    URL base del asistente. Por defecto, el origen desde el que se cargó este script.
 *   titulo      título de la barra superior. Por defecto, el nombre del sistema.
 *   placeholder texto del campo de entrada.
 *
 * Personalización por variables CSS (se heredan a través del Shadow DOM):
 *   --asistente-color, --asistente-color-texto, --asistente-fondo, --asistente-texto,
 *   --asistente-borde, --asistente-fuente, --asistente-radio,
 *   --asistente-ancho-lateral (260px), --asistente-ancho-columna (760px)
 *
 * Eventos (CustomEvent, burbujean y atraviesan el Shadow DOM):
 *   asistente:accion   {detail: {tipo, url, etiqueta}} por cada sugerencia `ui` del sistema.
 *                      Si el anfitrión llama preventDefault(), el widget no muestra su botón.
 *   asistente:estado   {detail: {habilitado}} al decidir si el asistente está disponible
 *                      (si no lo está, el widget muestra un aviso en lugar del chat).
 */
(() => {
  "use strict";
  if (customElements.get("asistente-chat")) return;

  const ORIGEN_SCRIPT = (() => {
    try { return new URL(document.currentScript.src).origin; } catch { return ""; }
  })();
  const MARGEN_RENOVAR_MS = 60_000;
  // Decisión de producto: por ahora el widget es solo la conversación actual, sin lista de chats.
  // El historial (barra lateral, carga, borrado) sigue implementado; ponerlo en true lo reactiva.
  const MOSTRAR_HISTORIAL = false;
  // Se recuerda solo el id de la conversación actual (nunca el token) en sessionStorage, para
  // retomarla al recargar la página. Se descarta al cerrar la pestaña.
  const CLAVE_CONV = "asistente:conversacion:";

  const TEXTOS = {
    escribir: "Escribí tu pregunta…",
    enviar: "Enviar",
    nueva: "Nueva conversación",
    historial: "Historial",
    borrar: "Borrar conversación",
    confirmarBorrar: "¿Borrar esta conversación? No se puede deshacer.",
    noDisponible: "El asistente no está disponible para tu usuario.",
    sinHistorial: "Todavía no hay conversaciones.",
    bienvenida: "Hola, ¿en qué te puedo ayudar?",
    pensando: "Pensando…",
    consultando: "Consultando",
    dictar: "Dictar",
    detener: "Detener grabación",
    transcribiendo: "Transcribiendo…",
    pie: "Las respuestas pueden contener errores; verificá los datos importantes.",
  };
  const ERRORES = {
    mensajes_min: "Enviaste demasiados mensajes seguidos. Esperá un momento.",
    mensajes_dia: "Alcanzaste el límite diario de mensajes.",
    tokens_mes: "Se alcanzó el límite mensual de uso del asistente.",
    timeout_turno: "La consulta tardó demasiado. Probá de nuevo.",
    demasiadas_iteraciones: "No pude completar la consulta. Probá reformularla.",
    llm_no_disponible: "El asistente no está disponible por ahora.",
    llm_no_configurado: "El asistente no está disponible por ahora.",
    origen_no_permitido: "Esta página no está autorizada para usar el asistente.",
    mensaje_invalido: "El mensaje está vacío o es demasiado largo.",
    no_se_pudo_guardar: "No se pudo guardar la conversación.",
  };
  const ERRORES_VOZ = {
    voz_no_disponible: "El dictado no está disponible por ahora.",
    audio_tipo_no_permitido: "Tu navegador grabó en un formato que el dictado no admite.",
    audio_demasiado_grande: "La grabación es demasiado larga. Probá con una más corta.",
    audio_demasiado_largo: "La grabación es demasiado larga. Probá con una más corta.",
    audio_invalido: "No se pudo procesar el audio. Probá de nuevo.",
    limite_excedido: "Dictaste demasiadas veces seguidas. Esperá un momento.",
    voz_error: "No se pudo transcribir el audio. Probá de nuevo.",
    mic_denegado: "No hay permiso para usar el micrófono.",
    mic_no_disponible: "No se encontró un micrófono.",
    sin_texto: "No se entendió nada. Probá de nuevo.",
  };
  // Formatos que acepta POST /v1/voz/transcribir, en orden de preferencia.
  const TIPOS_GRABACION = ["audio/webm;codecs=opus", "audio/webm", "audio/ogg;codecs=opus", "audio/mp4"];
  const ERROR_GENERICO = "Ocurrió un error. Probá de nuevo.";

  function puedeGrabar() {
    return !!(window.MediaRecorder && navigator.mediaDevices && navigator.mediaDevices.getUserMedia);
  }

  // ───────────────────────── Markdown → nodos DOM (sin innerHTML) ─────────────────────────

  function urlSegura(href) {
    try {
      const u = new URL(href, location.href);
      return ["http:", "https:", "mailto:"].includes(u.protocol) ? u.href : null;
    } catch { return null; }
  }

  const INLINE = /(`[^`\n]+`)|(\*\*[^*\n]+\*\*)|(__[^_\n]+__)|(\*[^*\s][^*\n]*\*)|(\[[^\]\n]+\]\([^)\s]+\))/;

  function inline(texto, padre) {
    while (texto) {
      const m = INLINE.exec(texto);
      if (!m) { padre.append(texto); return; }
      if (m.index) padre.append(texto.slice(0, m.index));
      const t = m[0];
      if (m[1]) {
        const el = document.createElement("code"); el.textContent = t.slice(1, -1); padre.append(el);
      } else if (m[2] || m[3]) {
        const el = document.createElement("strong"); inline(t.slice(2, -2), el); padre.append(el);
      } else if (m[4]) {
        const el = document.createElement("em"); inline(t.slice(1, -1), el); padre.append(el);
      } else {
        const [, etiqueta, href] = /^\[([^\]]+)\]\(([^)]+)\)$/.exec(t);
        const seguro = urlSegura(href);
        if (seguro) {
          const a = document.createElement("a");
          a.href = seguro; a.target = "_blank"; a.rel = "noopener noreferrer nofollow";
          a.textContent = etiqueta; padre.append(a);
        } else padre.append(etiqueta);
      }
      texto = texto.slice(m.index + t.length);
    }
  }

  function celdas(linea) {
    return linea.trim().replace(/^\||\|$/g, "").split("|").map((c) => c.trim());
  }

  function markdown(fuente, destino) {
    const lineas = fuente.replace(/\r\n?/g, "\n").split("\n");
    let i = 0;
    while (i < lineas.length) {
      const l = lineas[i];
      if (!l.trim()) { i++; continue; }

      if (/^```/.test(l)) {
        const buf = []; i++;
        while (i < lineas.length && !/^```/.test(lineas[i])) buf.push(lineas[i++]);
        i++;
        const pre = document.createElement("pre"), code = document.createElement("code");
        code.textContent = buf.join("\n"); pre.append(code); destino.append(pre);
        continue;
      }
      const h = /^(#{1,4})\s+(.*)$/.exec(l);
      if (h) {
        const el = document.createElement("h" + Math.min(h[1].length + 2, 6));
        inline(h[2], el); destino.append(el); i++; continue;
      }
      if (/^\s*([-*+]|\d+[.)])\s+/.test(l)) {
        const ordenada = /^\s*\d/.test(l);
        const lista = document.createElement(ordenada ? "ol" : "ul");
        while (i < lineas.length && /^\s*([-*+]|\d+[.)])\s+/.test(lineas[i])) {
          const li = document.createElement("li");
          inline(lineas[i].replace(/^\s*([-*+]|\d+[.)])\s+/, ""), li); lista.append(li); i++;
        }
        destino.append(lista); continue;
      }
      if (/^\s*\|.*\|\s*$/.test(l) && i + 1 < lineas.length && /^\s*\|?[\s:|-]+\|[\s:|-]*$/.test(lineas[i + 1])) {
        const tabla = document.createElement("table");
        const cab = document.createElement("tr");
        celdas(l).forEach((c) => { const th = document.createElement("th"); inline(c, th); cab.append(th); });
        const thead = document.createElement("thead"); thead.append(cab); tabla.append(thead);
        const tbody = document.createElement("tbody"); i += 2;
        while (i < lineas.length && /^\s*\|.*\|\s*$/.test(lineas[i])) {
          const tr = document.createElement("tr");
          celdas(lineas[i]).forEach((c) => { const td = document.createElement("td"); inline(c, td); tr.append(td); });
          tbody.append(tr); i++;
        }
        tabla.append(tbody);
        const caja = document.createElement("div"); caja.className = "tabla"; caja.append(tabla);
        destino.append(caja); continue;
      }
      const p = document.createElement("p"), buf = [];
      while (i < lineas.length && lineas[i].trim() && !/^(```|#{1,4}\s|\s*([-*+]|\d+[.)])\s+)/.test(lineas[i])) {
        buf.push(lineas[i++]);
      }
      buf.forEach((t, k) => { if (k) p.append(document.createElement("br")); inline(t, p); });
      destino.append(p);
    }
  }

  // ───────────────────────── Estilos ─────────────────────────

  const CSS = `
    :host { display: block; height: 100%; min-height: 360px; }
    * { box-sizing: border-box; }
    .raiz {
      --c: var(--asistente-color, #2f6f3e);
      --ct: var(--asistente-color-texto, #fff);
      --f: var(--asistente-fondo, #fff);
      --t: var(--asistente-texto, #1d2420);
      --b: var(--asistente-borde, #d9ded9);
      --suave: color-mix(in srgb, var(--t) 6%, var(--f));
      --apagado: color-mix(in srgb, var(--t) 58%, var(--f));
      --r: var(--asistente-radio, 12px);
      display: flex; width: 100%; height: 100%; position: relative; overflow: hidden;
      background: var(--f); color: var(--t);
      font: 15px/1.55 var(--asistente-fuente, system-ui, -apple-system, "Segoe UI", sans-serif);
    }
    [hidden] { display: none !important; }
    button { font: inherit; color: inherit; }
    textarea:focus-visible, button:focus-visible, a:focus-visible { outline: 2px solid var(--c); outline-offset: 1px; }

    .lateral {
      width: var(--asistente-ancho-lateral, 260px); flex: none; display: flex; flex-direction: column;
      background: var(--suave); border-right: 1px solid var(--b);
    }
    .lateral-cab { padding: 12px; }
    button.nueva {
      width: 100%; display: flex; align-items: center; gap: 8px; padding: 9px 12px; cursor: pointer;
      border: 1px solid var(--b); background: var(--f); border-radius: var(--r); font-weight: 600;
    }
    button.nueva:hover { border-color: var(--c); }
    button.nueva svg { width: 18px; height: 18px; flex: none; }
    .lista-titulo { padding: 8px 16px 4px; font-size: 11px; letter-spacing: .06em; text-transform: uppercase; color: var(--apagado); }
    .lista { list-style: none; margin: 0; padding: 4px 8px 12px; overflow-y: auto; flex: 1; }
    .lista li { display: flex; align-items: center; border-radius: 8px; }
    .lista li:hover, .lista li.activa { background: color-mix(in srgb, var(--t) 9%, var(--f)); }
    .lista li.activa .abrir { font-weight: 600; }
    .lista .abrir {
      flex: 1; min-width: 0; text-align: left; background: none; border: 0; padding: 9px 10px;
      cursor: pointer; overflow: hidden; text-overflow: ellipsis; white-space: nowrap;
    }
    .lista .borrar {
      background: none; border: 0; cursor: pointer; color: var(--apagado); padding: 6px; margin-right: 4px;
      border-radius: 6px; display: grid; place-items: center; opacity: 0;
    }
    .lista li:hover .borrar, .lista li:focus-within .borrar, .lista li.activa .borrar { opacity: 1; }
    .lista .borrar:hover { color: #8a1f1f; }
    .lista .borrar svg { width: 16px; height: 16px; }
    .lista .vacio-hist { display: block; padding: 10px; color: var(--apagado); font-size: 13px; }

    .principal { flex: 1; min-width: 0; display: flex; flex-direction: column; }
    .barra { display: flex; align-items: center; gap: 8px; padding: 10px 16px; border-bottom: 1px solid var(--b); }
    .barra h1 { flex: 1; margin: 0; font-size: 15px; font-weight: 600; overflow: hidden; text-overflow: ellipsis; white-space: nowrap; }
    .barra .menu, .barra .accion { background: none; border: 0; padding: 6px; border-radius: 6px; cursor: pointer; display: grid; place-items: center; }
    .barra .menu { display: none; }
    .barra .menu:hover, .barra .accion:hover { background: var(--suave); }
    .barra svg { width: 20px; height: 20px; }

    .scroll { flex: 1; overflow-y: auto; }
    .columna {
      max-width: var(--asistente-ancho-columna, 760px); margin: 0 auto; padding: 24px 16px;
      display: flex; flex-direction: column; gap: 20px;
    }
    .scroll.vacio { display: flex; }
    .scroll.vacio .columna { flex: 1; width: 100%; justify-content: center; }
    .bienvenida h2 { margin: 0; text-align: center; font-size: 26px; font-weight: 600; }

    .msg { overflow-wrap: anywhere; }
    .msg.user { align-self: flex-end; max-width: 85%; padding: 8px 14px; background: var(--suave); border-radius: calc(var(--r) * 1.5); white-space: pre-wrap; }
    .msg.assistant { align-self: stretch; }
    .msg.error { align-self: stretch; padding: 8px 12px; background: #fdecec; color: #8a1f1f; border-radius: var(--r); }
    .msg > :first-child { margin-top: 0; } .msg > :last-child { margin-bottom: 0; }
    .msg p, .msg ul, .msg ol, .msg pre, .msg h3, .msg h4, .msg h5, .msg h6 { margin: 0 0 10px; }
    .msg h3, .msg h4, .msg h5, .msg h6 { font-size: 16px; }
    .msg ul, .msg ol { padding-left: 22px; }
    .msg code { font-family: ui-monospace, monospace; font-size: 13px; background: rgba(0,0,0,.07); padding: 1px 5px; border-radius: 4px; }
    .msg pre { background: rgba(0,0,0,.07); padding: 10px; border-radius: 8px; overflow-x: auto; }
    .msg pre code { background: none; padding: 0; }
    .msg a { color: var(--c); text-decoration: underline; }
    .tabla { overflow-x: auto; margin-bottom: 10px; }
    .msg table { border-collapse: collapse; font-size: 14px; }
    .msg th, .msg td { border: 1px solid var(--b); padding: 4px 10px; text-align: left; }
    .msg th { background: var(--suave); }
    .estado { font-size: 13px; color: var(--apagado); font-style: italic; }
    .acciones { display: flex; flex-wrap: wrap; gap: 6px; margin-top: 10px; }
    .msg .acciones a {
      display: inline-block; padding: 4px 12px; border: 1px solid var(--c); color: var(--c);
      border-radius: 999px; text-decoration: none; font-size: 13px; background: var(--f);
    }
    .msg .acciones a:hover { background: var(--c); color: var(--ct); }

    .entrada { padding: 0 16px 8px; }
    .entrada form {
      max-width: var(--asistente-ancho-columna, 760px); margin: 0 auto; display: flex; align-items: flex-end; gap: 8px;
      padding: 8px 8px 8px 16px; background: var(--f); border: 1px solid var(--b); border-radius: calc(var(--r) * 1.8);
    }
    .entrada form:focus-within { border-color: var(--c); }
    textarea { flex: 1; resize: none; border: 0; outline: 0; background: transparent; font: inherit; color: inherit; max-height: 200px; padding: 6px 0; }
    form button {
      flex: none; width: 36px; height: 36px; border: 0; border-radius: 50%; display: grid; place-items: center;
      background: var(--c); color: var(--ct); cursor: pointer;
    }
    form button:disabled { opacity: .4; cursor: default; }
    form button.mic { background: transparent; color: var(--apagado); border: 1px solid var(--b); }
    form button.mic:hover:not(:disabled) { color: var(--c); border-color: var(--c); }
    form button.mic.grabando { background: #c0392b; border-color: #c0392b; color: #fff; }
    form button.mic[hidden] { display: none; }
    .aviso-voz { font-size: 12px; color: var(--apagado); text-align: center; padding-top: 4px; min-height: 16px; }
    .aviso-voz:empty { display: none; }
    .aviso-voz.err { color: #8a1f1f; }
    @media (prefers-reduced-motion: no-preference) { form button.mic.grabando { animation: pulso 1.2s infinite; } }
    @keyframes pulso { 50% { opacity: .6; } }
    form button svg { width: 18px; height: 18px; }
    .pie { padding-top: 6px; font-size: 11px; color: var(--apagado); text-align: center; }

    .velo, .aviso { display: none; }
    .sin-acceso .lateral, .sin-acceso .principal { display: none; }
    .sin-acceso .aviso { display: grid; flex: 1; place-items: center; padding: 24px; text-align: center; color: var(--apagado); }

    @media (max-width: 720px) {
      .lateral { position: absolute; inset: 0 auto 0 0; z-index: 3; width: min(300px, 85%); transform: translateX(-100%); }
      .menu-abierto .lateral { transform: none; box-shadow: 0 0 30px rgba(0,0,0,.3); }
      .menu-abierto .velo { display: block; position: absolute; inset: 0; z-index: 2; background: rgba(0,0,0,.4); }
      .barra .menu { display: grid; }
      .bienvenida h2 { font-size: 22px; }
    }
    @media (prefers-reduced-motion: no-preference) { .lateral { transition: transform .2s; } }
  `;

  const ICONO = {
    nuevo: "M12 5v14M5 12h14",
    menu: "M4 6h16M4 12h16M4 18h16",
    x: "M6 6l12 12M18 6L6 18",
    enviar: "M12 19V5M5 12l7-7 7 7",
    mic: "M12 3a3 3 0 0 0-3 3v6a3 3 0 0 0 6 0V6a3 3 0 0 0-3-3zM19 11a7 7 0 0 1-14 0M12 18v3",
    parar: "M7 7h10v10H7z",
  };
  function icono(nombre) {
    const ns = "http://www.w3.org/2000/svg";
    const svg = document.createElementNS(ns, "svg");
    svg.setAttribute("viewBox", "0 0 24 24"); svg.setAttribute("fill", "none");
    svg.setAttribute("stroke", "currentColor"); svg.setAttribute("stroke-width", "2");
    svg.setAttribute("stroke-linecap", "round"); svg.setAttribute("stroke-linejoin", "round");
    svg.setAttribute("aria-hidden", "true");
    const p = document.createElementNS(ns, "path"); p.setAttribute("d", ICONO[nombre]); svg.append(p);
    return svg;
  }

  function el(tag, props = {}, ...hijos) {
    const e = document.createElement(tag);
    for (const [k, v] of Object.entries(props)) {
      if (k === "class") e.className = v; else if (k in e) e[k] = v; else e.setAttribute(k, v);
    }
    e.append(...hijos);
    return e;
  }

  // ───────────────────────── Componente ─────────────────────────

  class AsistenteChat extends HTMLElement {
    static get observedAttributes() { return ["token-url", "servidor"]; }

    constructor() {
      super();
      this._token = null;        // {valor, expiraMs}; solo en memoria, nunca en storage
      this._convId = null;
      this._ocupado = false;
      this._abort = null;
      this._iniciado = false;
      this._nombreSistema = "";
      this.attachShadow({ mode: "open" });
    }

    get _servidor() {
      return (this.getAttribute("servidor") || ORIGEN_SCRIPT || location.origin).replace(/\/+$/, "");
    }

    connectedCallback() {
      this._construir();
      this._arrancar();
    }

    disconnectedCallback() {
      if (this._abort) this._abort.abort();
      this._detenerGrabacion(true);
    }

    attributeChangedCallback(nombre, viejo, nuevo) {
      if (this.isConnected && this._iniciado && viejo !== nuevo) {
        this._token = null; this._iniciado = false; this._arrancar();
      }
    }

    // — UI —
    _construir() {
      if (this._raiz) return;
      const r = this._raiz = el("div", { class: "raiz", hidden: true });
      this.shadowRoot.append(el("style", { textContent: CSS }), r);

      // barra lateral: nueva conversación + historial
      const nueva = el("button", { class: "nueva", type: "button" }, icono("nuevo"), el("span", { textContent: TEXTOS.nueva }));
      nueva.addEventListener("click", () => this._nueva());
      this._lista = el("ul", { class: "lista" });
      const lateral = el("aside", { class: "lateral", "aria-label": TEXTOS.historial },
        el("div", { class: "lateral-cab" }, nueva),
        el("div", { class: "lista-titulo", textContent: TEXTOS.historial }), this._lista);
      const velo = el("div", { class: "velo" });
      velo.addEventListener("click", () => this._menu(false));

      // columna principal: barra, mensajes, entrada
      this._titulo = el("h1", { textContent: this.getAttribute("titulo") || "Asistente" });
      const menu = el("button", { class: "menu", type: "button", title: TEXTOS.historial, "aria-label": TEXTOS.historial }, icono("menu"));
      menu.addEventListener("click", () => this._menu());
      const otra = el("button", { class: "accion", type: "button", title: TEXTOS.nueva, "aria-label": TEXTOS.nueva }, icono("nuevo"));
      otra.addEventListener("click", () => this._nueva());
      const barra = el("header", { class: "barra" }, ...(MOSTRAR_HISTORIAL ? [menu, this._titulo] : [this._titulo, otra]));

      this._mensajes = el("div", { class: "columna", role: "log", "aria-live": "polite" });
      this._scroll = el("div", { class: "scroll" }, this._mensajes);

      this._entrada = el("textarea", {
        rows: 1, placeholder: this.getAttribute("placeholder") || TEXTOS.escribir,
        "aria-label": TEXTOS.escribir, maxLength: 4000,
      });
      this._entrada.addEventListener("keydown", (e) => {
        if (e.key === "Enter" && !e.shiftKey && !e.isComposing) { e.preventDefault(); this._enviarForm(); }
      });
      this._entrada.addEventListener("input", () => {
        this._entrada.style.height = "auto";
        this._entrada.style.height = Math.min(this._entrada.scrollHeight, 200) + "px";
      });
      this._enviar = el("button", { type: "submit", title: TEXTOS.enviar, "aria-label": TEXTOS.enviar }, icono("enviar"));
      // dictado: oculto hasta que /v1/estado lo habilite (voz.dictado)
      this._mic = el("button", { type: "button", class: "mic", hidden: true, title: TEXTOS.dictar, "aria-label": TEXTOS.dictar }, icono("mic"));
      this._mic.addEventListener("click", () => this._conmutarDictado());
      this._avisoVoz = el("div", { class: "aviso-voz", role: "status" });
      const form = el("form", {}, this._entrada, this._mic, this._enviar);
      form.addEventListener("submit", (e) => { e.preventDefault(); this._enviarForm(); });
      const principal = el("main", { class: "principal" }, barra, this._scroll,
        el("div", { class: "entrada" }, form, this._avisoVoz, el("div", { class: "pie", textContent: TEXTOS.pie })));

      this._aviso = el("div", { class: "aviso", textContent: TEXTOS.noDisponible });
      r.append(...(MOSTRAR_HISTORIAL ? [lateral, velo] : []), principal, this._aviso);
      this._mostrarBienvenida();
    }

    _menu(abrir) {
      this._raiz.classList.toggle("menu-abierto", abrir === undefined ? !this._raiz.classList.contains("menu-abierto") : abrir);
    }

    _mostrarBienvenida() {
      this._mensajes.replaceChildren(el("div", { class: "bienvenida" }, el("h2", { textContent: TEXTOS.bienvenida })));
      this._scroll.classList.add("vacio");
    }

    _burbuja(rol) {
      const b = el("div", { class: "msg " + rol });
      const bienvenida = this._mensajes.querySelector(".bienvenida");
      if (bienvenida) bienvenida.remove();
      this._scroll.classList.remove("vacio");
      this._mensajes.append(b); this._bajar(); return b;
    }

    _bajar() { this._scroll.scrollTop = this._scroll.scrollHeight; }

    _error(codigo) {
      const b = this._burbuja("error");
      b.textContent = ERRORES[codigo] || ERROR_GENERICO;
    }

    // — arranque: token + estado —
    async _arrancar() {
      this._iniciado = true;
      if (!this.getAttribute("token-url")) {
        console.error("<asistente-chat>: falta el atributo token-url");
        return;
      }
      let habilitado = false;
      try {
        await this._asegurarToken();
        const r = await fetch(this._servidor + "/v1/estado", { headers: this._auth() });
        if (r.ok) {
          const e = await r.json();
          habilitado = e.habilitado !== false;
          this._nombreSistema = e.nombre_sistema || "";
          const voz = e.voz || {};
          this._maxAudioS = Number(voz.max_audio_s) > 0 ? Number(voz.max_audio_s) : 60;
          this._mic.hidden = !(voz.dictado === true && puedeGrabar());
          if (!this.getAttribute("titulo") && this._nombreSistema) this._titulo.textContent = "Asistente · " + this._nombreSistema;
        }
      } catch { /* sin acceso: se muestra el aviso */ }
      this._raiz.classList.toggle("sin-acceso", !habilitado);
      this._raiz.hidden = false;
      if (habilitado) { this._cargarHistorial(); this._entrada.focus(); this._restaurar(); }
      this.dispatchEvent(new CustomEvent("asistente:estado", { detail: { habilitado }, bubbles: true, composed: true }));
    }

    _auth() { return { Authorization: "Bearer " + this._token.valor }; }

    async _asegurarToken(forzar = false) {
      const t = this._token;
      if (!forzar && t && t.expiraMs - Date.now() > MARGEN_RENOVAR_MS) return;
      if (this._renovando) return this._renovando;
      this._renovando = (async () => {
        try {
          const r = await fetch(this.getAttribute("token-url"), { credentials: "same-origin", headers: { Accept: "application/json" } });
          if (!r.ok) throw new Error("token-url " + r.status);
          const d = await r.json();
          const expiraMs = Date.parse(d.expira);
          if (!d.token || Number.isNaN(expiraMs)) throw new Error("respuesta de token inválida");
          this._token = { valor: d.token, expiraMs };
        } finally { this._renovando = null; }
      })();
      return this._renovando;
    }

    // Ejecuta `fn` con token vigente; si el asistente responde 401 por token, renueva y reintenta una vez.
    async _conToken(fn) {
      await this._asegurarToken();
      let r = await fn(this._auth());
      if (r.status === 401) {
        await this._asegurarToken(true);
        r = await fn(this._auth());
      }
      return r;
    }

    // — conversaciones (barra lateral) —
    // Recordar/olvidar la conversación actual entre recargas. Nunca guarda el token.
    _recordar() {
      try {
        const clave = CLAVE_CONV + this._servidor;
        if (this._convId) sessionStorage.setItem(clave, this._convId); else sessionStorage.removeItem(clave);
      } catch { /* storage no disponible: se pierde solo la continuidad */ }
    }

    async _restaurar() {
      let id = null;
      try { id = sessionStorage.getItem(CLAVE_CONV + this._servidor); } catch { /* sin storage */ }
      if (id) await this._abrir(id, true);
    }

    // "Nueva conversación" no borra la anterior: solo deja de mostrarla (sigue en el servidor,
    // sujeta a la retención del sistema).
    _nueva() {
      if (this._ocupado) return;
      this._convId = null; this._recordar(); this._mostrarBienvenida(); this._pintarHistorial();
      this._menu(false); this._entrada.focus();
    }

    async _cargarHistorial() {
      if (!MOSTRAR_HISTORIAL) return;
      try {
        const r = await this._conToken((h) => fetch(this._servidor + "/v1/conversaciones", { headers: h }));
        if (!r.ok) throw new Error(r.status);
        this._convs = await r.json();
      } catch { this._convs = null; }
      this._pintarHistorial();
    }

    _pintarHistorial() {
      const aviso = (texto) => el("li", {}, el("span", { class: "vacio-hist", textContent: texto }));
      if (this._convs === null) return this._lista.replaceChildren(aviso(ERROR_GENERICO));
      if (!this._convs.length) return this._lista.replaceChildren(aviso(TEXTOS.sinHistorial));
      this._lista.replaceChildren(...this._convs.map((c) => this._itemHistorial(c)));
    }

    _itemHistorial(c) {
      const abrir = el("button", { class: "abrir", type: "button", title: c.titulo || "", textContent: c.titulo || "(sin título)" });
      abrir.addEventListener("click", () => this._abrir(c.id));
      const borrar = el("button", { class: "borrar", type: "button", title: TEXTOS.borrar, "aria-label": TEXTOS.borrar }, icono("x"));
      borrar.addEventListener("click", async () => {
        if (!window.confirm(TEXTOS.confirmarBorrar)) return;
        try {
          const r = await this._conToken((h) => fetch(`${this._servidor}/v1/conversaciones/${c.id}`, { method: "DELETE", headers: h }));
          if (!r.ok && r.status !== 404) return;
        } catch { return; }
        this._convs = this._convs.filter((x) => x.id !== c.id);
        if (this._convId === c.id && !this._ocupado) this._nueva(); else this._pintarHistorial();
      });
      return el("li", { class: c.id === this._convId ? "activa" : "" }, abrir, borrar);
    }

    // `silencioso`: al restaurar al arrancar, si falla (borrada, de otro usuario) se empieza vacío sin error.
    async _abrir(id, silencioso = false) {
      if (this._ocupado) return;
      try {
        const r = await this._conToken((h) => fetch(`${this._servidor}/v1/conversaciones/${id}`, { headers: h }));
        if (!r.ok) throw new Error(r.status);
        const d = await r.json();
        this._convId = id; this._mensajes.replaceChildren(); this._mostrarBienvenida();
        for (const m of d.mensajes) {
          const b = this._burbuja(m.rol);
          if (m.rol === "assistant") markdown(m.texto, b); else b.textContent = m.texto;
        }
        this._recordar(); this._pintarHistorial(); this._menu(false); this._bajar();
      } catch {
        if (silencioso) { this._convId = null; this._recordar(); } else this._error();
      }
    }

    // — dictado: graba, transcribe y rellena el campo (sin enviar) —
    _conmutarDictado() {
      if (this._grabador) this._detenerGrabacion(false); else this._iniciarGrabacion();
    }

    _avisarVoz(texto, esError = false) {
      this._avisoVoz.textContent = texto || "";
      this._avisoVoz.classList.toggle("err", esError);
    }

    async _iniciarGrabacion() {
      if (this._transcribiendo || this._ocupado) return;
      this._avisarVoz("");
      let flujo;
      try {
        flujo = await navigator.mediaDevices.getUserMedia({ audio: true });
      } catch (e) {
        const negado = e && (e.name === "NotAllowedError" || e.name === "SecurityError");
        this._avisarVoz(ERRORES_VOZ[negado ? "mic_denegado" : "mic_no_disponible"], true);
        return;
      }
      const tipo = TIPOS_GRABACION.find((t) => MediaRecorder.isTypeSupported(t));
      let grabador;
      try { grabador = new MediaRecorder(flujo, tipo ? { mimeType: tipo } : undefined); }
      catch { flujo.getTracks().forEach((t) => t.stop()); this._avisarVoz(ERRORES_VOZ.mic_no_disponible, true); return; }
      const trozos = [];
      const inicio = Date.now();
      let cancelada = false;
      grabador.addEventListener("dataavailable", (ev) => { if (ev.data && ev.data.size) trozos.push(ev.data); });
      grabador.addEventListener("stop", () => {
        flujo.getTracks().forEach((t) => t.stop());
        clearTimeout(this._tope);
        this._grabador = null;
        this._mic.classList.remove("grabando");
        this._mic.title = TEXTOS.dictar; this._mic.setAttribute("aria-label", TEXTOS.dictar);
        this._mic.replaceChildren(icono("mic"));
        if (cancelada) { this._avisarVoz(""); return; }
        const blob = new Blob(trozos, { type: grabador.mimeType || tipo || "audio/webm" });
        this._transcribir(blob, (Date.now() - inicio) / 1000);
      });
      this._grabador = grabador;
      this._cancelarFn = () => { cancelada = true; };
      grabador.start();
      this._mic.classList.add("grabando");
      this._mic.title = TEXTOS.detener; this._mic.setAttribute("aria-label", TEXTOS.detener);
      this._mic.replaceChildren(icono("parar"));
      // Corta al llegar al tope del servidor (con un margen para que el header no lo supere).
      this._tope = setTimeout(() => this._detenerGrabacion(false), Math.max(1, this._maxAudioS - 1) * 1000);
    }

    _detenerGrabacion(cancelar) {
      const g = this._grabador;
      if (!g) return;
      if (cancelar && this._cancelarFn) this._cancelarFn();
      if (g.state !== "inactive") g.stop();
    }

    async _transcribir(blob, segundos) {
      if (!blob.size) { this._avisarVoz(ERRORES_VOZ.audio_invalido, true); return; }
      this._transcribiendo = true; this._mic.disabled = true;
      this._avisarVoz(TEXTOS.transcribiendo);
      try {
        const tipo = blob.type.split(";")[0] || "audio/webm";
        const r = await this._conToken((h) => fetch(`${this._servidor}/v1/voz/transcribir`, {
          method: "POST", body: blob,
          headers: { ...h, "Content-Type": blob.type || tipo, "X-Audio-Duracion-S": segundos.toFixed(1) },
        }));
        if (!r.ok) {
          let codigo = ""; try { codigo = (await r.json()).error; } catch { /* sin cuerpo */ }
          this._avisarVoz(ERRORES_VOZ[codigo] || ERROR_GENERICO, true);
          return;
        }
        const texto = String((await r.json()).texto ?? "").trim();
        if (!texto) { this._avisarVoz(ERRORES_VOZ.sin_texto, true); return; }
        const actual = this._entrada.value;
        this._entrada.value = (actual && !/\s$/.test(actual) ? actual + " " : actual) + texto;
        this._entrada.dispatchEvent(new Event("input"));
        this._entrada.focus();
        this._avisarVoz("");
      } catch {
        this._avisarVoz(ERROR_GENERICO, true);
      } finally {
        this._transcribiendo = false; this._mic.disabled = false;
      }
    }

    // — chat —
    _enviarForm() {
      const texto = this._entrada.value.trim();
      if (!texto || this._ocupado) return;
      this._entrada.value = ""; this._entrada.style.height = "auto";
      this._enviarMensaje(texto);
    }

    _bloquear(si) {
      this._ocupado = si; this._enviar.disabled = si;
      this._raiz.setAttribute("aria-busy", String(si));
    }

    async _enviarMensaje(texto) {
      this._bloquear(true);
      this._burbuja("user").textContent = texto;
      const burbuja = this._burbuja("assistant");
      const estado = el("div", { class: "estado", textContent: TEXTOS.pensando });
      burbuja.append(estado);
      this._abort = new AbortController();
      try {
        let res = await this._turno(texto, burbuja, estado);
        if (res === "token_expirado") {  // el turno no se guardó: se renueva y se reintenta una vez
          await this._asegurarToken(true);
          estado.textContent = TEXTOS.pensando;
          res = await this._turno(texto, burbuja, estado);
        }
        if (res === "token_expirado") this._error("token_invalido");
      } catch (e) {
        if (e.name !== "AbortError") { burbuja.remove(); this._error(); }
      } finally {
        if (!burbuja.textContent.trim() && !burbuja.querySelector(".acciones")) burbuja.remove();
        this._bloquear(false); this._abort = null;
        this._cargarHistorial();  // el turno puede haber creado o retitulado la conversación
      }
    }

    // Devuelve "ok" | "token_expirado" | "error".
    async _turno(texto, burbuja, estado) {
      const cuerpo = JSON.stringify({ conversacion_id: this._convId, mensaje: texto });
      const r = await this._conToken((h) => fetch(this._servidor + "/v1/chat", {
        method: "POST", signal: this._abort.signal, body: cuerpo,
        headers: { ...h, "Content-Type": "application/json", Accept: "text/event-stream" },
      }));
      if (!r.ok) {
        let codigo = ""; try { codigo = (await r.json()).error; } catch { /* sin cuerpo */ }
        if (r.status === 401) return "token_expirado";
        burbuja.remove(); this._error(codigo); return "error";
      }
      let acumulado = "", resultado = "ok";
      const pintar = () => {
        const acciones = burbuja.querySelector(".acciones");
        burbuja.replaceChildren(); markdown(acumulado, burbuja);
        if (acciones) burbuja.append(acciones);
        this._bajar();
      };
      await leerSSE(r.body, (evento, datos) => {
        switch (evento) {
          case "delta":
            acumulado += datos.texto || ""; pintar(); break;
          case "tool":
            estado.textContent = TEXTOS.consultando + "… " + (datos.herramientas || []).join(", ");
            if (!estado.isConnected) burbuja.append(estado);
            break;
          case "ui": this._acciones(datos.acciones || [], burbuja); break;
          case "done":
            if (datos.conversacion_id) { this._convId = datos.conversacion_id; this._recordar(); } break;
          case "token_expirado": resultado = "token_expirado"; break;
          case "error":
            if (!acumulado) burbuja.remove(); else estado.remove();
            this._error(datos.codigo); resultado = "error"; break;
        }
      });
      estado.remove();
      return resultado;
    }

    _acciones(lista, burbuja) {
      for (const a of lista) {
        if (!a || a.tipo !== "navegar" || typeof a.url !== "string") continue;
        const ev = new CustomEvent("asistente:accion", {
          detail: { tipo: a.tipo, url: a.url, etiqueta: a.etiqueta || "" },
          bubbles: true, composed: true, cancelable: true,
        });
        if (!this.dispatchEvent(ev)) continue;  // el anfitrión se encarga
        // Por defecto: solo URLs relativas del mismo origen.
        let u; try { u = new URL(a.url, location.href); } catch { continue; }
        if (u.origin !== location.origin || /^[a-z][a-z0-9+.-]*:/i.test(a.url) || a.url.startsWith("//")) continue;
        let caja = burbuja.querySelector(".acciones");
        if (!caja) { caja = el("div", { class: "acciones" }); burbuja.append(caja); }
        caja.append(el("a", { href: u.pathname + u.search + u.hash, textContent: a.etiqueta || a.url }));
      }
    }
  }

  // Lector SSE sobre ReadableStream (EventSource no permite cabecera Authorization).
  async function leerSSE(stream, alEvento) {
    const lector = stream.getReader(), dec = new TextDecoder();
    let buf = "";
    const procesar = (bloque) => {
      let evento = "message", datos = "";
      for (const linea of bloque.split("\n")) {
        if (linea.startsWith(":")) continue;  // heartbeat
        if (linea.startsWith("event:")) evento = linea.slice(6).trim();
        else if (linea.startsWith("data:")) datos += linea.slice(5).trimStart();
      }
      if (!datos) return;
      try { alEvento(evento, JSON.parse(datos)); } catch (e) { console.error("<asistente-chat>: evento inválido", e); }
    };
    for (;;) {
      const { done, value } = await lector.read();
      if (done) break;
      buf += dec.decode(value, { stream: true }).replace(/\r\n/g, "\n");
      let i;
      while ((i = buf.indexOf("\n\n")) >= 0) { procesar(buf.slice(0, i)); buf = buf.slice(i + 2); }
    }
    if (buf.trim()) procesar(buf);
  }

  customElements.define("asistente-chat", AsistenteChat);
})();
