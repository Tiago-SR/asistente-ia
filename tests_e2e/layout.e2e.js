// E2E del layout "vista de chat a pantalla completa" (escritorio 1280 y móvil 390). Sin LLM:
// la respuesta del chat se fabrica con page.route. Se ejecuta como widget.e2e.js (ver README.md).
async (page) => {
  const BASE = "http://localhost:8203";
  const SHOTS = ".playwright-mcp/e2e";
  const resultados = [];
  const caso = async (nombre, fn) => {
    try { await fn(); resultados.push({ nombre, ok: true }); }
    catch (e) { resultados.push({ nombre, ok: false, detalle: String(e.message).split("\n")[0].slice(0, 300) }); }
  };
  const afirma = (c, m) => { if (!c) throw new Error(m); };
  const ctx = page.context();
  const larga = Array.from({ length: 40 }, (_, i) => `Línea ${i + 1} de una respuesta larga para forzar el scroll interno.`).join("\n\n");
  const tabla = "| Cultivo | Superficie (ha) | Cantidad de establecimientos | Observaciones largas |\n|---|---|---|---|\n| Soja | 660,5 | 2 | texto-largo-sin-espacios-para-probar-el-desborde-horizontal-en-movil |\n";

  for (const [etq, W, H] of [["desktop", 1280, 800], ["movil", 390, 780]]) {
    const p = await ctx.newPage();
    await p.setViewportSize({ width: W, height: H });
    await p.route("**/v1/chat", (route) => route.fulfill({
      status: 200,
      headers: { "content-type": "text/event-stream", "access-control-allow-origin": "http://localhost:8203" },
      body: `event: delta\ndata: ${JSON.stringify({ texto: tabla + "\n" + larga })}\n\nevent: done\ndata: ${JSON.stringify({ conversacion_id: "00000000-0000-0000-0000-000000000000" })}\n\n`,
    }));
    await p.goto(`${BASE}/?usuario=ana`);
    await p.locator("asistente-chat textarea").waitFor();
    const q = (f) => p.locator("asistente-chat").evaluate(f);

    await caso(`[${etq}] la página no emite avisos de PHP`, async () => {
      const html = await p.content();
      afirma(!/<b>(Warning|Notice|Deprecated|Fatal error)<\/b>/.test(html), "hay avisos de PHP en la página");
      afirma(html.includes("Sesión simulada como «ana»"), "el nombre de usuario no se interpola");
    });
    await caso(`[${etq}] el widget ocupa todo el ancho y el resto del alto bajo la barra`, async () => {
      const r = await p.locator("asistente-chat").boundingBox();
      const nav = await p.locator("nav").boundingBox();
      afirma(Math.abs(r.width - W) <= 1 && r.x === 0, `ancho ${r.width} x=${r.x}`);
      afirma(Math.abs(r.y - (nav.y + nav.height)) <= 1 && Math.abs(r.y + r.height - H) <= 1, `y=${r.y} h=${r.height}`);
    });
    await caso(`[${etq}] sin modos antiguos: sin lateral/menú/lanzador ni elementos fixed; modo y abierto no hacen nada`, async () => {
      const n = await q((e) => {
        e.setAttribute("modo", "flotante"); e.setAttribute("abierto", "");
        const todos = [...e.shadowRoot.querySelectorAll("*")];
        return {
          lateral: e.shadowRoot.querySelectorAll(".lateral, .velo, button.menu, .lanzador").length,
          fixed: todos.filter((x) => getComputedStyle(x).position === "fixed").length,
          host: getComputedStyle(e).position,
        };
      });
      afirma(n.lateral === 0 && n.fixed === 0 && n.host !== "fixed", JSON.stringify(n));
      const r = await p.locator("asistente-chat").boundingBox();
      afirma(Math.abs(r.width - W) <= 1, "el layout cambió con modo/abierto: ancho " + r.width);
    });
    await caso(`[${etq}] barra superior con título y botón de nueva conversación`, async () => {
      afirma(await p.locator("asistente-chat header.barra h1").isVisible(), "sin título");
      afirma(await p.locator("asistente-chat header.barra button.accion").isVisible(), "sin botón nueva conversación");
    });
    await caso(`[${etq}] foco del campo: un solo contorno (el de la píldora), sin outline propio del textarea`, async () => {
      await p.locator("asistente-chat textarea").focus();
      await p.keyboard.press("Shift+Tab"); await p.keyboard.press("Tab");   // foco por teclado (:focus-visible)
      const f = await q((e) => {
        const t = e.shadowRoot.querySelector("textarea"), form = e.shadowRoot.querySelector(".entrada form");
        return { ta: getComputedStyle(t).outlineStyle, outW: getComputedStyle(t).outlineWidth, formBorde: getComputedStyle(form).borderColor, activo: e.shadowRoot.activeElement === t };
      });
      afirma(f.activo, "el textarea no tiene el foco");
      afirma(f.ta === "none" || f.outW === "0px", `el textarea dibuja outline: ${JSON.stringify(f)}`);
    });
    await p.screenshot({ path: `${SHOTS}/10-${etq}-vacio.png` });

    await p.locator("asistente-chat textarea").fill("pregunta");
    await p.locator("asistente-chat textarea").press("Enter");
    await p.locator("asistente-chat .msg.assistant table").waitFor();
    await p.waitForFunction(() => document.querySelector("asistente-chat").shadowRoot.querySelector("[aria-busy]")?.getAttribute("aria-busy") === "false");

    await caso(`[${etq}] columna central: centrada y con ancho máximo ≤ 760 px`, async () => {
      const c = await p.locator("asistente-chat .columna").boundingBox();
      afirma(c.width <= 760.5 && c.width <= W, `columna ${c.width}`);
      // centrada dentro del área útil del scroll (sin la barra de desplazamiento vertical)
      const util = await q((e) => e.shadowRoot.querySelector(".scroll").clientWidth);
      afirma(Math.abs(c.x - (util - c.x - c.width)) <= 1, `descentrada: izq ${c.x}, der ${util - c.x - c.width}`);
      if (W >= 800) afirma(c.width > 600, `columna estrecha en escritorio: ${c.width}`);
    });
    await caso(`[${etq}] entrada fija abajo: con scroll largo la página no se desplaza y el campo sigue visible`, async () => {
      const m = await p.evaluate(() => ({ sy: window.scrollY, sh: document.documentElement.scrollHeight, ih: innerHeight, sw: document.documentElement.scrollWidth, iw: innerWidth }));
      afirma(m.sy === 0 && m.sh <= m.ih + 1, `la página scrollea: ${JSON.stringify(m)}`);
      const sc = await q((e) => { const s = e.shadowRoot.querySelector(".scroll"); return { sh: s.scrollHeight, ch: s.clientHeight, st: s.scrollTop }; });
      afirma(sc.sh > sc.ch, "el contenido no desborda (el caso no prueba nada)");
      afirma(sc.st + sc.ch >= sc.sh - 2, `no baja al final: ${JSON.stringify(sc)}`);
      const t = await p.locator("asistente-chat textarea").boundingBox();
      const b = await p.locator("asistente-chat button[type=submit]").boundingBox();
      afirma(t.y >= 0 && t.y + t.height <= H && b.y + b.height <= H && b.x + b.width <= W, `entrada fuera de pantalla: ${JSON.stringify({ t, b })}`);
    });
    await caso(`[${etq}] sin desborde horizontal (página, widget y tabla)`, async () => {
      const m = await p.evaluate(() => ({ sw: document.documentElement.scrollWidth, iw: innerWidth }));
      afirma(m.sw <= m.iw, `scroll horizontal de página: ${JSON.stringify(m)}`);
      const d = await q((e) => { const s = e.shadowRoot.querySelector(".scroll"); const k = e.shadowRoot.querySelector(".columna"); return { s: s.scrollWidth - s.clientWidth, k: k.scrollWidth - k.clientWidth }; });
      afirma(d.s <= 1 && d.k <= 1, `desborde interno: ${JSON.stringify(d)}`);
      const tb = await p.locator("asistente-chat .msg.assistant table").boundingBox();
      afirma(tb.x + tb.width <= W + 1, `la tabla sale de la pantalla: x=${tb.x} w=${tb.width}`);
    });
    await caso(`[${etq}] nueva conversación vuelve a la bienvenida`, async () => {
      await p.locator("asistente-chat header.barra button.accion").click();
      afirma(await p.locator("asistente-chat .bienvenida").isVisible(), "sin bienvenida");
      afirma(await p.locator("asistente-chat .msg").count() === 0, "quedan mensajes");
    });
    await p.screenshot({ path: `${SHOTS}/11-${etq}-nueva.png` });
    // captura con la conversación larga (se reenvía para tenerla en pantalla)
    await p.locator("asistente-chat textarea").fill("otra");
    await p.locator("asistente-chat textarea").press("Enter");
    await p.locator("asistente-chat .msg.assistant table").waitFor();
    await p.waitForFunction(() => document.querySelector("asistente-chat").shadowRoot.querySelector("[aria-busy]")?.getAttribute("aria-busy") === "false");
    await p.screenshot({ path: `${SHOTS}/12-${etq}-conversacion.png` });
    await p.close();
  }
  return { resultados, resumen: `${resultados.filter((r) => r.ok).length}/${resultados.length} ok` };
}
