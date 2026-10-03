/*
 * <asistente-chat> — widget de chat del Asistente (sección 9 del plan).
 *
 * Web Component sin dependencias ni build. Shadow DOM, sin innerHTML: todo el contenido
 * (incluido el Markdown del modelo) se construye con nodos DOM, así que no hay inyección.
 *
 * Atributos:
 *   token-url   (obligatorio) ruta del sistema anfitrión que emite el token; se pide con
 *               las cookies de sesión del anfitrión. Responde {token, expira}.
 *   servidor    URL base del asistente. Por defecto, el origen desde el que se cargó este script.
 *   titulo      título de la cabecera. Por defecto, el nombre del sistema.
 *   modo        "flotante" (botón + panel, por defecto) | "incrustado" (ocupa su contenedor).
 *   abierto     (modo flotante) arranca con el panel abierto.
 *   placeholder texto del campo de entrada.
 *
 * Personalización por variables CSS (se heredan a través del Shadow DOM):
 *   --asistente-color, --asistente-color-texto, --asistente-fondo, --asistente-texto,
 *   --asistente-borde, --asistente-fuente, --asistente-radio, --asistente-ancho, --asistente-alto
 *
 * Eventos (CustomEvent, burbujean y atraviesan el Shadow DOM):
 *   asistente:accion   {detail: {tipo, url, etiqueta}} por cada sugerencia `ui` del sistema.
 *                      Si el anfitrión llama preventDefault(), el widget no muestra su botón.
 *   asistente:estado   {detail: {habilitado}} al decidir si se muestra u oculta.
 */
(() => {
  "use strict";
  if (customElements.get("asistente-chat")) return;

  const ORIGEN_SCRIPT = (() => {
    try { return new URL(document.currentScript.src).origin; } catch { return ""; }
  })();
  const MARGEN_RENOVAR_MS = 60_000;

  const TEXTOS = {
    escribir: "Escribí tu pregunta…",
    enviar: "Enviar",
    nueva: "Nueva conversación",
    historial: "Historial",
    cerrar: "Cerrar",
    abrir: "Abrir asistente",
    borrar: "Borrar",
    sinHistorial: "Todavía no hay conversaciones.",
    bienvenida: "Hola, ¿en qué te puedo ayudar?",
    pensando: "Pensando…",
    consultando: "Consultando",
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
  const ERROR_GENERICO = "Ocurrió un error. Probá de nuevo.";

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
    :host { all: initial; display: contents; }
    * { box-sizing: border-box; }
    .raiz {
      --c: var(--asistente-color, #2f6f3e);
      --ct: var(--asistente-color-texto, #fff);
      --f: var(--asistente-fondo, #fff);
      --t: var(--asistente-texto, #1d2420);
      --b: var(--asistente-borde, #d9ded9);
      --suave: color-mix(in srgb, var(--t) 6%, var(--f));
      --r: var(--asistente-radio, 12px);
      font: 14px/1.45 var(--asistente-fuente, system-ui, -apple-system, "Segoe UI", sans-serif);
      color: var(--t);
    }
    .raiz[hidden], [hidden] { display: none !important; }
    .flotante .lanzador {
      position: fixed; right: 20px; bottom: 20px; z-index: 2147483000;
      width: 56px; height: 56px; border-radius: 50%; border: 0; cursor: pointer;
      background: var(--c); color: var(--ct); box-shadow: 0 4px 14px rgba(0,0,0,.25);
      display: grid; place-items: center;
    }
    .lanzador svg { width: 26px; height: 26px; }
    .panel {
      display: flex; flex-direction: column; background: var(--f); border: 1px solid var(--b);
      border-radius: var(--r); overflow: hidden; position: relative;
    }
    .flotante .panel {
      position: fixed; right: 20px; bottom: 88px; z-index: 2147483000;
      width: min(var(--asistente-ancho, 380px), calc(100vw - 24px));
      height: min(var(--asistente-alto, 560px), calc(100vh - 110px));
      box-shadow: 0 10px 40px rgba(0,0,0,.28);
    }
    .incrustado .panel { width: 100%; height: var(--asistente-alto, 560px); }
    .incrustado .lanzador, .incrustado .cerrar { display: none; }
    header {
      display: flex; align-items: center; gap: 4px; padding: 10px 12px;
      background: var(--c); color: var(--ct);
    }
    header h2 { flex: 1; margin: 0; font-size: 15px; font-weight: 600; overflow: hidden; text-overflow: ellipsis; white-space: nowrap; }
    header button {
      background: transparent; border: 0; color: inherit; cursor: pointer; padding: 6px;
      border-radius: 6px; display: grid; place-items: center;
    }
    header button:hover, header button:focus-visible { background: rgba(255,255,255,.2); }
    header svg { width: 18px; height: 18px; }
    .mensajes { flex: 1; overflow-y: auto; padding: 12px; display: flex; flex-direction: column; gap: 10px; }
    .msg { max-width: 88%; padding: 8px 12px; border-radius: var(--r); overflow-wrap: anywhere; }
    .msg.user { align-self: flex-end; background: var(--c); color: var(--ct); white-space: pre-wrap; }
    .msg.assistant { align-self: flex-start; background: var(--suave); }
    .msg.sistema { align-self: center; color: color-mix(in srgb, var(--t) 60%, var(--f)); font-size: 12px; text-align: center; }
    .msg.error { align-self: stretch; max-width: 100%; background: #fdecec; color: #8a1f1f; }
    .msg > :first-child { margin-top: 0; } .msg > :last-child { margin-bottom: 0; }
    .msg p, .msg ul, .msg ol, .msg pre, .msg h3, .msg h4, .msg h5, .msg h6 { margin: 0 0 8px; }
    .msg h3, .msg h4, .msg h5, .msg h6 { font-size: 14px; }
    .msg ul, .msg ol { padding-left: 20px; }
    .msg code { font-family: ui-monospace, monospace; font-size: 12.5px; background: rgba(0,0,0,.08); padding: 1px 4px; border-radius: 4px; }
    .msg pre { background: rgba(0,0,0,.08); padding: 8px; border-radius: 6px; overflow-x: auto; }
    .msg pre code { background: none; padding: 0; }
    .msg a { color: inherit; text-decoration: underline; }
    .tabla { overflow-x: auto; margin-bottom: 8px; }
    .msg table { border-collapse: collapse; font-size: 13px; }
    .msg th, .msg td { border: 1px solid var(--b); padding: 3px 8px; text-align: left; }
    .estado { font-size: 12px; color: color-mix(in srgb, var(--t) 60%, var(--f)); font-style: italic; }
    .acciones { display: flex; flex-wrap: wrap; gap: 6px; margin-top: 8px; }
    .acciones a {
      display: inline-block; padding: 4px 10px; border: 1px solid var(--c); color: var(--c);
      border-radius: 999px; text-decoration: none; font-size: 13px; background: var(--f);
    }
    .acciones a:hover { background: var(--c); color: var(--ct); }
    form { display: flex; gap: 6px; padding: 10px; border-top: 1px solid var(--b); }
    textarea {
      flex: 1; resize: none; font: inherit; color: inherit; background: var(--f);
      border: 1px solid var(--b); border-radius: 8px; padding: 8px; max-height: 120px;
    }
    textarea:focus-visible, button:focus-visible, a:focus-visible { outline: 2px solid var(--c); outline-offset: 1px; }
    form button {
      border: 0; border-radius: 8px; padding: 0 14px; background: var(--c); color: var(--ct);
      cursor: pointer; font: inherit; font-weight: 600;
    }
    form button:disabled { opacity: .5; cursor: default; }
    .pie { padding: 0 12px 8px; font-size: 11px; color: color-mix(in srgb, var(--t) 55%, var(--f)); text-align: center; }
    .historial { position: absolute; inset: 0; top: 0; background: var(--f); display: flex; flex-direction: column; z-index: 2; }
    .historial ul { list-style: none; margin: 0; padding: 8px; overflow-y: auto; flex: 1; }
    .historial li { display: flex; gap: 4px; align-items: center; border-bottom: 1px solid var(--b); }
    .historial li button.abrir { flex: 1; text-align: left; background: none; border: 0; padding: 10px 6px; cursor: pointer; font: inherit; color: inherit; }
    .historial li button.abrir:hover { background: var(--suave); }
    .historial li small { display: block; color: color-mix(in srgb, var(--t) 55%, var(--f)); }
    .historial li button.borrar { background: none; border: 0; cursor: pointer; color: #8a1f1f; padding: 6px; font: inherit; }
    .vacio { padding: 20px; text-align: center; color: color-mix(in srgb, var(--t) 60%, var(--f)); }
    @media (max-width: 480px) {
      .flotante .panel { right: 8px; left: 8px; bottom: 80px; width: auto; }
    }
    @media (prefers-reduced-motion: no-preference) { .lanzador { transition: transform .15s; } .lanzador:hover { transform: scale(1.06); } }
  `;

  const ICONO = {
    chat: "M4 4h16a2 2 0 0 1 2 2v10a2 2 0 0 1-2 2H9l-5 4v-4H4a2 2 0 0 1-2-2V6a2 2 0 0 1 2-2z",
    nuevo: "M12 5v14M5 12h14",
    reloj: "M12 7v5l3 2M21 12a9 9 0 1 1-18 0 9 9 0 0 1 18 0z",
    x: "M6 6l12 12M18 6L6 18",
  };
  function icono(nombre) {
    const ns = "http://www.w3.org/2000/svg";
    const svg = document.createElementNS(ns, "svg");
    svg.setAttribute("viewBox", "0 0 24 24"); svg.setAttribute("fill", nombre === "chat" ? "currentColor" : "none");
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

    disconnectedCallback() { if (this._abort) this._abort.abort(); }

    attributeChangedCallback(nombre, viejo, nuevo) {
      if (this.isConnected && this._iniciado && viejo !== nuevo) {
        this._token = null; this._iniciado = false; this._arrancar();
      }
    }

    // — UI —
    _construir() {
      if (this._raiz) return;
      const incrustado = this.getAttribute("modo") === "incrustado";
      const r = this._raiz = el("div", { class: "raiz " + (incrustado ? "incrustado" : "flotante"), hidden: true });
      this.shadowRoot.append(el("style", { textContent: CSS }), r);

      this._lanzador = el("button", { class: "lanzador", type: "button", title: TEXTOS.abrir, "aria-label": TEXTOS.abrir }, icono("chat"));
      this._lanzador.addEventListener("click", () => this._alternar());

      this._titulo = el("h2", { textContent: this.getAttribute("titulo") || "Asistente" });
      const btn = (clase, titulo, ic, fn) => {
        const b = el("button", { class: clase, type: "button", title: titulo, "aria-label": titulo }, icono(ic));
        b.addEventListener("click", fn); return b;
      };
      const cab = el("header", {}, this._titulo,
        btn("nueva", TEXTOS.nueva, "nuevo", () => this._nueva()),
        btn("hist", TEXTOS.historial, "reloj", () => this._verHistorial()),
        btn("cerrar", TEXTOS.cerrar, "x", () => this._alternar(false)));

      this._mensajes = el("div", { class: "mensajes", role: "log", "aria-live": "polite" });
      this._entrada = el("textarea", {
        rows: 1, placeholder: this.getAttribute("placeholder") || TEXTOS.escribir,
        "aria-label": TEXTOS.escribir, maxLength: 4000,
      });
      this._entrada.addEventListener("keydown", (e) => {
        if (e.key === "Enter" && !e.shiftKey && !e.isComposing) { e.preventDefault(); this._enviarForm(); }
      });
      this._entrada.addEventListener("input", () => {
        this._entrada.style.height = "auto";
        this._entrada.style.height = Math.min(this._entrada.scrollHeight, 120) + "px";
      });
      this._enviar = el("button", { type: "submit", textContent: TEXTOS.enviar });
      const form = el("form", {}, this._entrada, this._enviar);
      form.addEventListener("submit", (e) => { e.preventDefault(); this._enviarForm(); });

      this._panel = el("div", { class: "panel", role: "dialog", "aria-label": "Asistente" },
        cab, this._mensajes, form, el("div", { class: "pie", textContent: TEXTOS.pie }));
      this._panel.hidden = !incrustado && !this.hasAttribute("abierto");
      r.append(this._lanzador, this._panel);
      this._mostrarBienvenida();
    }

    _alternar(abrir) {
      const mostrar = abrir === undefined ? this._panel.hidden : abrir;
      this._panel.hidden = !mostrar;
      if (mostrar) this._entrada.focus(); else this._lanzador.focus();
    }

    _mostrarBienvenida() {
      this._mensajes.replaceChildren(el("div", { class: "msg sistema", textContent: TEXTOS.bienvenida }));
    }

    _burbuja(rol) {
      const b = el("div", { class: "msg " + rol });
      this._mensajes.append(b); this._bajar(); return b;
    }

    _bajar() { this._mensajes.scrollTop = this._mensajes.scrollHeight; }

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
          if (!this.getAttribute("titulo") && this._nombreSistema) this._titulo.textContent = "Asistente · " + this._nombreSistema;
        }
      } catch { /* sin acceso: el widget queda oculto */ }
      this._raiz.hidden = !habilitado;
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

    // — conversaciones —
    _nueva() {
      if (this._ocupado) return;
      this._convId = null; this._cerrarHistorial(); this._mostrarBienvenida(); this._entrada.focus();
    }

    _cerrarHistorial() { if (this._hist) { this._hist.remove(); this._hist = null; } }

    async _verHistorial() {
      if (this._hist) return this._cerrarHistorial();
      const lista = el("ul");
      const cerrar = el("button", { type: "button", title: TEXTOS.cerrar, "aria-label": TEXTOS.cerrar }, icono("x"));
      cerrar.addEventListener("click", () => this._cerrarHistorial());
      const cab = el("header", {}, el("h2", { textContent: TEXTOS.historial }), cerrar);
      this._hist = el("div", { class: "historial" }, cab, lista);
      this._panel.append(this._hist);
      try {
        const r = await this._conToken((h) => fetch(this._servidor + "/v1/conversaciones", { headers: h }));
        if (!r.ok) throw new Error(r.status);
        const convs = await r.json();
        if (!convs.length) { lista.replaceWith(el("div", { class: "vacio", textContent: TEXTOS.sinHistorial })); return; }
        for (const c of convs) lista.append(this._itemHistorial(c, lista));
      } catch { lista.replaceWith(el("div", { class: "vacio", textContent: ERROR_GENERICO })); }
    }

    _itemHistorial(c, lista) {
      const fecha = new Date(c.actualizada).toLocaleString();
      const abrir = el("button", { class: "abrir", type: "button" }, c.titulo || "(sin título)", el("small", { textContent: fecha }));
      abrir.addEventListener("click", () => this._abrir(c.id));
      const borrar = el("button", { class: "borrar", type: "button", textContent: TEXTOS.borrar });
      borrar.addEventListener("click", async () => {
        const r = await this._conToken((h) => fetch(`${this._servidor}/v1/conversaciones/${c.id}`, { method: "DELETE", headers: h }));
        if (r.ok || r.status === 404) {
          li.remove();
          if (this._convId === c.id) this._nueva();
          if (!lista.children.length) lista.replaceWith(el("div", { class: "vacio", textContent: TEXTOS.sinHistorial }));
        }
      });
      const li = el("li", {}, abrir, borrar);
      return li;
    }

    async _abrir(id) {
      if (this._ocupado) return;
      try {
        const r = await this._conToken((h) => fetch(`${this._servidor}/v1/conversaciones/${id}`, { headers: h }));
        if (!r.ok) throw new Error(r.status);
        const d = await r.json();
        this._convId = id; this._cerrarHistorial(); this._mensajes.replaceChildren();
        for (const m of d.mensajes) {
          const b = this._burbuja(m.rol);
          if (m.rol === "assistant") markdown(m.texto, b); else b.textContent = m.texto;
        }
        this._bajar();
      } catch { this._cerrarHistorial(); this._error(); }
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
      this._panel.setAttribute("aria-busy", String(si));
    }

    async _enviarMensaje(texto) {
      this._bloquear(true);
      if (!this._mensajes.querySelector(".msg:not(.sistema)")) this._mensajes.replaceChildren();
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
            if (datos.conversacion_id) this._convId = datos.conversacion_id; break;
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
