// E2E del tema claro/oscuro del widget. Sin LLM ni micrófono: el chat se fabrica con page.route y la voz
// se simula (como en manos-libres.e2e.js). Emula prefers-color-scheme y comprueba el atributo `tema`, la
// reacción al cambio del sistema, que las variables --asistente-* del anfitrión sigan mandando y, sobre todo,
// que ningún texto quede ilegible (contraste computado ≥ 4,5:1) en ambos temas y en cada estado de la UI.
// Se ejecuta como los demás (ver README.md).
async (page) => {
  const BASE = "http://localhost:8203";
  const SHOTS = ".playwright-mcp/e2e";
  const resultados = [];
  const caso = async (nombre, fn) => {
    try { await fn(); resultados.push({ nombre, ok: true }); }
    catch (e) { resultados.push({ nombre, ok: false, detalle: String(e.message).split("\n")[0].slice(0, 300) }); }
  };
  const afirma = (c, m) => { if (!c) throw new Error(m); };
  const CORS = { "access-control-allow-origin": BASE, "access-control-allow-headers": "authorization,content-type,accept", "access-control-allow-methods": "GET,POST,OPTIONS" };
  const MD = "### Resumen\n\nTenés **870,5** hectáreas de `soja` ([detalle](https://ejemplo.test/a)).\n\n- Soja: 870,5\n- Maíz: 88,2\n\n"
    + "| Cultivo | Superficie (ha) |\n|---|---|\n| Soja | 870,5 |\n| Maíz | 88,2 |\n\n```\nresumen_por_cultivo({ zafra: 2025 })\n```\n";

  const abrir = async (esquema, { atributos = "", lento = false } = {}) => {
    const p = await page.context().newPage();
    await p.emulateMedia({ colorScheme: esquema });
    await p.setViewportSize({ width: 1280, height: 800 });
    let n = 0;
    await p.route("**/v1/chat", (route) => {
      if (route.request().method() === "OPTIONS") return route.fulfill({ status: 204, headers: CORS });
      n++;
      const ev = (e, d) => `event: ${e}\ndata: ${JSON.stringify(d)}\n\n`;
      const body = n === 2
        ? ev("error", { codigo: "tokens_mes" })
        : ev("confirmacion", { id: "acc-1", tool: "agregar_nota", huella: "h".repeat(64), expira: new Date(Date.now() + 600000).toISOString(),
            resumen: "Agregar una nota al establecimiento «El Matorral»", lineas: ["Texto: Helada en el potrero"] })
          + ev("delta", { texto: MD }) + ev("done", { conversacion_id: "00000000-0000-0000-0000-000000000000" });
      return route.fulfill({ status: 200, headers: { "content-type": "text/event-stream", ...CORS }, body });
    });
    await p.addInitScript(({ lento }) => {
      window.__mh = { actual: null };
      window.SpeechRecognition = window.webkitSpeechRecognition = class {
        constructor() { this.results = []; window.__mh.actual = this; }
        start() { setTimeout(() => this.onstart && this.onstart(), 0); }
        stop() {} abort() {}
      };
      window.__decir = (texto, final = true) => {
        const r = window.__mh.actual, ultimo = r.results[r.results.length - 1];
        const res = Object.assign([{ transcript: texto, confidence: 0.9 }], { isFinal: final });
        if (ultimo && !ultimo.isFinal) r.results[r.results.length - 1] = res; else r.results.push(res);
        r.onresult({ resultIndex: r.results.length - 1, results: r.results });
      };
      window.SpeechSynthesisUtterance = class { constructor(t) { this.text = t; } };
      Object.defineProperty(window, "speechSynthesis", { configurable: true, value: {
        pendientes: [], getVoices: () => [{ name: "Española", lang: "es-ES" }],
        speak(u) { this.pendientes.push(u); setTimeout(() => { if (!u.__c) u.onend && u.onend(); }, lento ? 60000 : 20); },
        cancel() { for (const u of this.pendientes) { u.__c = true; setTimeout(() => u.onerror && u.onerror({ error: "canceled" }), 0); } this.pendientes = []; },
      } });
    }, { lento });
    await p.goto(`${BASE}/?usuario=ana`);
    await p.locator("asistente-chat textarea").waitFor();
    if (atributos) await p.locator("asistente-chat").evaluate((e, a) => { for (const [k, v] of Object.entries(a)) e.setAttribute(k, v); }, atributos);
    return p;
  };
  const raiz = (p, fn, arg) => p.locator("asistente-chat").evaluate((e, [f, a]) => (new Function("raiz", "arg", "return (" + f + ")(raiz, arg)"))(e.shadowRoot.querySelector(".raiz"), a), [fn.toString(), arg]);
  const info = (p) => raiz(p, (r) => {
    const cs = getComputedStyle(r), ta = getComputedStyle(r.querySelector("textarea"));
    return { oscuro: r.classList.contains("oscuro"), fondo: cs.backgroundColor, texto: cs.color, esquema: cs.colorScheme, esquemaTextarea: ta.colorScheme };
  });
  const enviar = async (p, txt) => {
    await p.locator("asistente-chat textarea").fill(txt);
    await p.locator("asistente-chat textarea").press("Enter");
    await p.waitForFunction(() => document.querySelector("asistente-chat").shadowRoot.querySelector("[aria-busy]")?.getAttribute("aria-busy") === "false");
  };

  // Recorre todo el texto visible del widget y calcula su contraste real contra el fondo compuesto detrás.
  const auditar = (p) => raiz(p, (r) => {
    const num = (s) => s.match(/-?[\d.]+(?:e-?\d+)?/g).map(Number);
    const parse = (s) => {                                    // rgb(), rgba() o color(srgb r g b / a)
      if (s.startsWith("color(")) { const [a, b, c, al = 1] = num(s.replace("srgb", "")); return [a * 255, b * 255, c * 255, al]; }
      const [a, b, c, al = 1] = num(s); return [a, b, c, al];
    };
    const sobre = (f, b) => { const a = f[3]; return [0, 1, 2].map((i) => f[i] * a + b[i] * (1 - a)).concat(1); };
    const lum = ([R, G, B]) => { const f = (v) => { v /= 255; return v <= 0.03928 ? v / 12.92 : ((v + 0.055) / 1.055) ** 2.4; }; return 0.2126 * f(R) + 0.7152 * f(G) + 0.0722 * f(B); };
    const cr = (a, b) => { const [x, y] = [lum(a), lum(b)].sort((m, n) => n - m); return (x + 0.05) / (y + 0.05); };
    const padre = (e) => e.parentElement || (e.getRootNode() instanceof ShadowRoot ? e.getRootNode().host : null);
    const fondoDe = (e) => {
      const capas = [];
      for (let x = e; x; x = padre(x)) { const c = parse(getComputedStyle(x).backgroundColor); if (c[3] > 0) capas.push(c); if (c[3] >= 1) break; }
      return capas.reduceRight((abajo, c) => sobre(c, abajo), [255, 255, 255, 1]);
    };
    const malos = [], revisados = [];
    const visible = (e) => { for (let x = e; x && x !== r.getRootNode(); x = padre(x)) { if (x.hidden) return false; } return e.getClientRects().length > 0 && getComputedStyle(e).visibility !== "hidden"; };
    for (const e of r.querySelectorAll("*")) {
      if (e instanceof SVGElement || e.disabled || e.closest("[disabled]")) continue;
      const tieneTexto = [...e.childNodes].some((n) => n.nodeType === 3 && n.textContent.trim());
      const placeholder = e.tagName === "TEXTAREA" && e.placeholder;
      if (!tieneTexto && !placeholder) continue;
      if (!visible(e)) continue;
      const cs = getComputedStyle(e);
      const fondo = fondoDe(e);
      const colores = tieneTexto ? [["texto", cs.color]] : [];
      if (placeholder) colores.push(["placeholder", getComputedStyle(e, "::placeholder").color]);
      for (const [que, col] of colores) {
        const f = sobre(parse(col), fondo), c = cr(f, fondo);
        const grande = parseFloat(cs.fontSize) >= 24 || (parseFloat(cs.fontSize) >= 18.66 && Number(cs.fontWeight) >= 700);
        const min = grande ? 3 : 4.5, etq = `${e.tagName.toLowerCase()}.${e.className || "-"} «${(e.textContent || e.placeholder).trim().slice(0, 24)}» (${que})`;
        revisados.push(etq);
        if (c < min) malos.push(`${etq}: ${c.toFixed(2)} < ${min}`);
      }
    }
    return { malos, n: revisados.length };
  });

  for (const esquema of ["light", "dark"]) {
    const oscuro = esquema === "dark";
    const p = await abrir(esquema);
    await caso(`[${esquema}] auto: sigue prefers-color-scheme (clase, fondo, texto y color-scheme nativo)`, async () => {
      const i = await info(p);
      afirma(i.oscuro === oscuro, JSON.stringify(i));
      afirma(i.fondo === (oscuro ? "rgb(21, 26, 23)" : "rgb(255, 255, 255)"), "fondo " + i.fondo);
      afirma(i.esquema === (oscuro ? "dark" : "light") && i.esquemaTextarea === i.esquema, "color-scheme " + JSON.stringify(i));
    });
    await caso(`[${esquema}] bienvenida legible`, async () => {
      const a = await auditar(p); afirma(a.n >= 3 && !a.malos.length, JSON.stringify(a));
    });
    await caso(`[${esquema}] respuesta con tabla, código, enlace y tarjeta de confirmación legibles`, async () => {
      await enviar(p, "anotá algo");
      await p.locator("asistente-chat .msg.confirmacion").waitFor();
      afirma(await p.locator("asistente-chat table").count() === 1 && await p.locator("asistente-chat pre").count() === 1, "falta tabla o código");
      const a = await auditar(p); afirma(a.n >= 12 && !a.malos.length, JSON.stringify(a));
    });
    await caso(`[${esquema}] tarjeta: botones Confirmar/Cancelar y bloque de código distinguibles del fondo`, async () => {
      const d = await raiz(p, (r) => {
        const cs = (s, pr) => getComputedStyle(r.querySelector(s))[pr];
        return { fondo: getComputedStyle(r).backgroundColor, primario: cs("button.primario", "backgroundColor"), cancelar: cs(".accion-botones button:not(.primario)", "backgroundColor"),
                 pre: cs(".msg pre", "backgroundColor"), th: cs(".msg th", "backgroundColor"), borde: cs(".msg.confirmacion", "borderColor") };
      });
      afirma(d.primario !== d.fondo && d.pre !== d.fondo && d.th !== d.fondo && d.borde !== d.fondo, JSON.stringify(d));
    });
    await caso(`[${esquema}] mensaje de error legible`, async () => {
      await enviar(p, "otra");
      await p.locator("asistente-chat .msg.error").waitFor();
      const a = await auditar(p); afirma(!a.malos.length, JSON.stringify(a));
    });
    await p.screenshot({ path: `${SHOTS}/20-tema-${esquema}-conversacion.png` });
    await p.close();

    // manos libres: armado → capturando → confirmando → respondiendo
    const m = await abrir(esquema, { lento: true });
    await caso(`[${esquema}] manos libres: indicador, botones y parcial legibles en cada estado`, async () => {
      await m.locator("asistente-chat button.manos").click();
      await m.locator("asistente-chat .mh").waitFor();
      const estados = {};
      const medir = async (nombre) => { const a = await auditar(m); estados[nombre] = a.n; afirma(!a.malos.length, nombre + ": " + JSON.stringify(a)); };
      await medir("armado");
      await m.screenshot({ path: `${SHOTS}/21-tema-${esquema}-mh-armado.png` });
      await m.evaluate(() => window.__decir("asistente cuántas hectáreas de soja", false));
      await m.waitForFunction(() => /escucho/i.test(document.querySelector("asistente-chat").shadowRoot.querySelector(".mh-estado").textContent));
      await medir("capturando");
      await m.screenshot({ path: `${SHOTS}/22-tema-${esquema}-mh-capturando.png` });
      await m.evaluate(() => window.__decir("asistente cuántas hectáreas de soja", true));
      await m.waitForFunction(() => /enviar/i.test(document.querySelector("asistente-chat").shadowRoot.querySelector(".mh-estado").textContent), null, { timeout: 6000 });
      await medir("confirmando");
      await m.screenshot({ path: `${SHOTS}/23-tema-${esquema}-mh-confirmando.png` });
      await m.locator("asistente-chat .mh-enviar").click();
      await m.waitForFunction(() => /Respondiendo/i.test(document.querySelector("asistente-chat").shadowRoot.querySelector(".mh-estado").textContent), null, { timeout: 6000 });
      await medir("respondiendo");
      await m.screenshot({ path: `${SHOTS}/24-tema-${esquema}-mh-respondiendo.png` });
    });
    await m.close();
  }

  // — atributo `tema`, cambio del sistema en caliente y variables del anfitrión —
  const q = await abrir("light");
  await caso("el cambio del tema del sistema se refleja sin recargar (auto)", async () => {
    afirma(!(await info(q)).oscuro, "arranca claro");
    await q.emulateMedia({ colorScheme: "dark" });
    await q.waitForFunction(() => document.querySelector("asistente-chat").shadowRoot.querySelector(".raiz").classList.contains("oscuro"));
    await q.emulateMedia({ colorScheme: "light" });
    await q.waitForFunction(() => !document.querySelector("asistente-chat").shadowRoot.querySelector(".raiz").classList.contains("oscuro"));
  });
  await caso("tema=oscuro y tema=claro ignoran al sistema; quitar el atributo vuelve a auto; un valor inválido es auto", async () => {
    const poner = (v) => q.locator("asistente-chat").evaluate((e, v) => (v === null ? e.removeAttribute("tema") : e.setAttribute("tema", v)), v);
    await poner("oscuro"); afirma((await info(q)).oscuro, "oscuro forzado");
    await q.emulateMedia({ colorScheme: "dark" });
    await poner("claro"); afirma(!(await info(q)).oscuro, "claro forzado bajo sistema oscuro");
    await poner("OSCURO"); afirma((await info(q)).oscuro, "mayúsculas");
    await poner(null); afirma((await info(q)).oscuro, "auto bajo sistema oscuro");
    await poner("quizás"); afirma((await info(q)).oscuro, "inválido = auto");
    await q.emulateMedia({ colorScheme: "light" });
    await q.waitForFunction(() => !document.querySelector("asistente-chat").shadowRoot.querySelector(".raiz").classList.contains("oscuro"));
  });
  await caso("cambiar `tema` no reinicia la sesión (los mensajes siguen y no se vuelve a pedir token)", async () => {
    await enviar(q, "anotá algo");
    await q.locator("asistente-chat .msg.assistant").waitFor();
    const antes = await q.locator("asistente-chat .msg").count();
    let pidio = 0; q.on("request", (r) => { if (/\/asistente\/token/.test(r.url())) pidio++; });
    await q.locator("asistente-chat").evaluate((e) => e.setAttribute("tema", "oscuro"));
    await q.waitForTimeout(300);
    afirma(await q.locator("asistente-chat .msg").count() === antes && pidio === 0, `mensajes ${antes}→${await q.locator("asistente-chat .msg").count()}, tokens pedidos ${pidio}`);
  });
  await caso("las variables --asistente-* del anfitrión mandan sobre la paleta oscura", async () => {
    await q.locator("asistente-chat").evaluate((e) => {
      e.setAttribute("tema", "oscuro");
      e.style.setProperty("--asistente-fondo", "#fffbe6"); e.style.setProperty("--asistente-texto", "#222");
      e.style.setProperty("--asistente-color", "#8a2be2"); e.style.setProperty("--asistente-color-texto", "#fff"); e.style.setProperty("--asistente-borde", "#ccb");
    });
    const i = await info(q);
    afirma(i.oscuro && i.fondo === "rgb(255, 251, 230)" && i.texto === "rgb(34, 34, 34)", JSON.stringify(i));
    const c = await raiz(q, (r) => getComputedStyle(r.querySelector("form button[type=submit]")).backgroundColor);
    afirma(c === "rgb(138, 43, 226)", "color de acento " + c);
    const a = await auditar(q); afirma(!a.malos.length, JSON.stringify(a));
  });
  await q.screenshot({ path: `${SHOTS}/25-tema-anfitrion.png` });
  await q.close();

  return { resultados, resumen: `${resultados.filter((r) => r.ok).length}/${resultados.length} ok` };
}
