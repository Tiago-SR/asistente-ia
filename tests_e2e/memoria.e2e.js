// E2E de la memoria por usuario (Fase 1): tarjeta LOCAL de «recordar»/«olvidar» y panel «Lo que recuerdo». Sin LLM ni
// memoria real: /v1/estado, el chat, /v1/memoria y /v1/confirmaciones/* se fabrican con page.route; lo real es la página
// (sistema-php, :8203), el widget y —en el primer caso— el /v1/estado verdadero (memoria apagada para sistema-php).
// Se ejecuta como los demás (ver README.md).
async (page) => {
  const BASE = "http://localhost:8203";
  const resultados = [];
  const caso = async (nombre, fn) => {
    try { await fn(); resultados.push({ nombre, ok: true }); }
    catch (e) { resultados.push({ nombre, ok: false, detalle: String(e.message).split("\n")[0].slice(0, 300) }); }
  };
  const afirma = (c, m) => { if (!c) throw new Error(m); };
  const dormir = (ms) => new Promise((r) => setTimeout(r, ms));
  const CORS = {
    "access-control-allow-origin": BASE, "access-control-allow-headers": "authorization,content-type,accept",
    "access-control-allow-methods": "GET,POST,DELETE,OPTIONS",
  };
  const ctx = page.context();
  const json = (route, status, cuerpo) => route.fulfill({ status, headers: { "content-type": "application/json", ...CORS }, body: JSON.stringify(cuerpo) });

  // Una página nueva. `memoria`: lo que dice /v1/estado (undefined = el verdadero, sin fabricar).
  async function nueva({ memoria, lista = [], propuesta, confirmarLocal, confirmar, listaError = false, esquema = "light" } = {}) {
    const p = await ctx.newPage();
    await p.emulateMedia({ colorScheme: esquema });
    const visto = { token: [], confirmar: [], local: [], cancelar: [], borrar: [], listar: [], dialogos: 0 };
    const estado = { lista: lista.map((x) => ({ ...x })) };
    p.on("dialog", (d) => { visto.dialogos++; d.dismiss(); });
    if (memoria !== undefined) {
      await p.route("**/v1/estado", (route) => {
        if (route.request().method() === "OPTIONS") return route.fulfill({ status: 204, headers: CORS });
        return json(route, 200, { habilitado: true, nombre_sistema: "Sistema PHP", memoria, voz: { dictado: false, respuesta: false, max_audio_s: 60 } });
      });
    }
    await p.route(/\/v1\/memoria(\/[^/?]+)?$/, (route) => {
      const rq = route.request(), m = new URL(rq.url()).pathname.match(/\/v1\/memoria(?:\/([^/]+))?$/);
      if (rq.method() === "OPTIONS") return route.fulfill({ status: 204, headers: CORS });
      const auth = rq.headers()["authorization"];
      if (rq.method() === "GET") {
        visto.listar.push({ auth });
        return listaError ? json(route, 500, { error: "error_interno" }) : json(route, 200, estado.lista);
      }
      visto.borrar.push({ id: m[1] || null, auth });
      if (m[1]) estado.lista = estado.lista.filter((x) => x.id !== m[1]); else estado.lista = [];
      return route.fulfill({ status: m[1] ? 204 : 200, headers: CORS, ...(m[1] ? {} : { contentType: "application/json", body: JSON.stringify({ borrados: 1 }) }) });
    });
    let n = 0;
    await p.route("**/v1/chat", (route) => {
      if (route.request().method() === "OPTIONS") return route.fulfill({ status: 204, headers: CORS });
      const d = propuesta ? propuesta(++n) : null;
      return route.fulfill({
        status: 200, headers: { "content-type": "text/event-stream", ...CORS },
        body: (d ? `event: confirmacion\ndata: ${JSON.stringify(d)}\n\n` : "") +
          `event: delta\ndata: ${JSON.stringify({ texto: "Te pedí confirmar." })}\n\nevent: done\ndata: ${JSON.stringify({ conversacion_id: "00000000-0000-0000-0000-000000000000" })}\n\n`,
      });
    });
    await p.route(/\/asistente\/token\?.*confirmacion=/, (route) => {
      visto.token.push({ url: route.request().url() });
      return route.fulfill({ status: 200, contentType: "application/json", body: JSON.stringify({ token: "tok-escritura", expira: new Date(Date.now() + 60000).toISOString() }) });
    });
    const api = (cola, resp) => (route) => {
      const rq = route.request();
      if (rq.method() === "OPTIONS") return route.fulfill({ status: 204, headers: CORS });
      cola.push({ url: rq.url(), auth: rq.headers()["authorization"] });
      const r = resp ? resp(rq) : { status: 200, json: {} };
      return json(route, r.status, r.json);
    };
    await p.route("**/v1/confirmaciones/*/confirmar-local", api(visto.local, confirmarLocal));
    await p.route(/\/v1\/confirmaciones\/[^/]+\/confirmar$/, api(visto.confirmar, confirmar));
    await p.route("**/v1/confirmaciones/*/cancelar", api(visto.cancelar, () => ({ status: 200, json: { estado: "cancelada" } })));
    await p.goto(`${BASE}/?usuario=ana`);
    await p.locator("asistente-chat textarea").waitFor();
    await p.evaluate(() => { window.__eventos = []; document.addEventListener("asistente:confirmacion", (e) => window.__eventos.push(e.detail)); });
    const enviar = async (txt = "recordá algo") => {
      await p.locator("asistente-chat textarea").fill(txt);
      await p.locator("asistente-chat textarea").press("Enter");
      await p.waitForFunction(() => document.querySelector("asistente-chat").shadowRoot.querySelector("[aria-busy]")?.getAttribute("aria-busy") === "false");
    };
    const sel = (css, opciones) => p.locator("asistente-chat " + css, opciones);
    return { p, visto, estado, enviar, sel, tarjeta: (i = 0) => p.locator("asistente-chat .msg.confirmacion").nth(i) };
  }

  const ahora = Date.now();
  const R = (i, tipo, clave, descripcion) => ({
    id: `00000000-0000-0000-0000-00000000000${i}`, tipo, clave, descripcion,
    creada: new Date(ahora - 86400000).toISOString(), ultimo_uso: new Date(ahora).toISOString(), vence: new Date(ahora + 30 * 86400000).toISOString(),
  });
  const LISTA = [
    R(1, "preferencia", "decimales", "Cifras con 0 decimales"),
    R(2, "alias", "la sojera", "“la sojera” → San Pedro (establecimiento 4)"),
    R(3, "consulta_guardada", "la de siempre", "“la de siempre”: resumen_por_cultivo {}"),
  ];
  const local = (n, extra = {}) => ({
    id: `acc-${n}`, tool: "recordar", local: true, huella: "h".repeat(32), expira: new Date(Date.now() + 120000).toISOString(),
    resumen: "Recordar: “la sojera” = San Pedro (establecimiento 4)", lineas: [], ...extra,
  });

  // — Con la memoria apagada para el sistema (el /v1/estado verdadero de sistema-php) no hay botón ni panel —
  {
    const { p, sel } = await nueva();
    await caso("sin memoria en /v1/estado: el botón y el panel no aparecen", async () => {
      await dormir(300);
      afirma(await sel(".memoria").isHidden(), "el botón está visible");
      afirma(await sel(".memoria-panel").isHidden(), "el panel está visible");
    });
    await p.close();
  }

  // — Panel: lista, olvidar uno, olvidar todo, Escape —
  {
    const { p, visto, estado, sel } = await nueva({ memoria: true, lista: LISTA });
    await caso("con memoria: el botón de la barra aparece, accesible y con el panel cerrado", async () => {
      await sel(".memoria").waitFor({ state: "visible" });
      afirma(await sel(".memoria-panel").isHidden(), "el panel empieza abierto");
      afirma((await sel(".memoria").getAttribute("aria-label")) === "Lo que recuerdo" && (await sel(".memoria").getAttribute("aria-expanded")) === "false", "etiquetas del botón");
    });
    await caso("abrir: lista cada recuerdo con su tipo, su descripción, cuándo se olvida solo y un botón Olvidar; el foco va al panel", async () => {
      await sel(".memoria").click();
      await sel(".mem-lista li").first().waitFor();
      afirma(await sel(".mem-lista li").count() === 3, "cantidad");
      const textos = await sel(".mem-lista li").allTextContents();
      afirma(textos[1].includes("Alias") && textos[1].includes("la sojera") && textos[1].includes("San Pedro") && /Se olvida solo el/.test(textos[1]), textos[1]);
      afirma((await sel(".mem-lista li button").first().getAttribute("aria-label")) === "Olvidar: Cifras con 0 decimales", "aria-label del botón");
      afirma((await sel(".memoria").getAttribute("aria-expanded")) === "true", "aria-expanded");
      afirma(await p.locator("asistente-chat").evaluate((e) => e.shadowRoot.activeElement?.textContent === "Cerrar"), "el foco no fue al panel");
      afirma(visto.listar.length === 1 && /^Bearer ey/.test(visto.listar[0].auth), "listó con la sesión: " + JSON.stringify(visto.listar));
    });
    await caso("olvidar uno: DELETE de ese id con la sesión, sin diálogo de confirmación, y se recarga la lista", async () => {
      await sel(".mem-lista li").nth(1).locator("button").click();
      await sel(".mem-estado", { hasText: "Listo, lo olvidé." }).waitFor();
      afirma(visto.borrar.length === 1 && visto.borrar[0].id === LISTA[1].id && /^Bearer ey/.test(visto.borrar[0].auth), JSON.stringify(visto.borrar));
      afirma(visto.dialogos === 0, "pidió confirmación con un diálogo");
      afirma(await sel(".mem-lista li").count() === 2 && !(await sel(".mem-lista").textContent()).includes("la sojera"), "la lista no se actualizó");
    });
    await caso("Escape cierra el panel, devuelve el foco al botón y no apaga nada más", async () => {
      await p.keyboard.press("Escape");
      afirma(await sel(".memoria-panel").isHidden(), "el panel sigue abierto");
      afirma((await sel(".memoria").getAttribute("aria-expanded")) === "false", "aria-expanded");
      afirma(await p.locator("asistente-chat").evaluate((e) => e.shadowRoot.activeElement?.classList.contains("memoria")), "el foco no volvió al botón");
    });
    await caso("olvidar todo: DELETE /v1/memoria, lista vacía con la ayuda y el botón deshabilitado", async () => {
      await sel(".memoria").click();
      await sel(".mem-lista li").first().waitFor();
      await sel(".mem-pie button").click();
      await sel(".mem-estado", { hasText: "Listo, olvidé todo." }).waitFor();
      afirma(visto.borrar.at(-1).id === null && estado.lista.length === 0, JSON.stringify(visto.borrar.at(-1)));
      afirma(await sel(".mem-lista li").count() === 0 && await sel(".mem-vacio").isVisible(), "sin estado vacío");
      afirma((await sel(".mem-vacio").textContent()).includes("Podés pedirme"), "texto en rioplatense");
      afirma(await sel(".mem-pie button").isDisabled(), "Olvidar todo sigue habilitado");
    });
    await caso("el botón de la barra no está en la vista de voz", async () => {
      await p.locator("asistente-chat").evaluate((e) => e.shadowRoot.querySelector(".raiz").classList.add("vista-voz"));
      afirma(await sel(".memoria").isHidden(), "visible en la vista de voz");
      await p.locator("asistente-chat").evaluate((e) => e.shadowRoot.querySelector(".raiz").classList.remove("vista-voz"));
    });
    await p.close();
  }

  // — Lo que dice el servidor es texto —
  {
    const hostil = [R(1, "alias", "x", "<img src=x onerror=window.__xss=1> <b>negrita</b>"), { ...R(2, "alias", "y", "ok"), tipo: "<script>window.__xss=1</script>" }];
    const { p, sel } = await nueva({ memoria: true, lista: hostil });
    await caso("la descripción y el tipo del servidor se muestran como texto: no se crea HTML ni se ejecuta código", async () => {
      await sel(".memoria").click();
      await sel(".mem-lista li").first().waitFor();
      afirma(await sel(".mem-lista img, .mem-lista b, .mem-lista script").count() === 0, "se creó HTML");
      afirma(await p.evaluate(() => window.__xss === undefined), "se ejecutó código");
      afirma((await sel(".mem-lista li").first().textContent()).includes("<img"), "no se muestra literal");
    });
    await p.close();
  }

  // — Fallas —
  {
    const { p, sel } = await nueva({ memoria: true, listaError: true });
    await caso("si no se puede cargar la lista, lo dice en el panel (sin romper el chat)", async () => {
      await sel(".memoria").click();
      await sel(".mem-error", { hasText: "No pude cargar" }).waitFor();
      afirma(await sel("textarea").isVisible(), "el chat dejó de estar");
    });
    await p.close();
  }

  // — Contraste computado del panel abierto, con datos y vacío, en ambos temas —
  for (const esquema of ["light", "dark"]) {
    const { p, sel } = await nueva({ memoria: true, lista: LISTA, esquema });
    await sel(".memoria").click();
    await sel(".mem-lista li").first().waitFor();
    await caso(`[${esquema}] el texto del panel (con lista y con error) cumple 4,5:1 sobre su fondo`, async () => {
      const a = await p.locator("asistente-chat").evaluate((e) => {
        const r = e.shadowRoot.querySelector(".raiz");
        r.querySelector(".mem-error").textContent = "No pude olvidarlo. Probá de nuevo.";   // para auditar también el color de error
        const num = (s) => s.match(/-?[\d.]+(?:e-?\d+)?/g).map(Number);
        const parse = (s) => { if (s.startsWith("color(")) { const [a, b, c, al = 1] = num(s.replace("srgb", "")); return [a * 255, b * 255, c * 255, al]; } const [a, b, c, al = 1] = num(s); return [a, b, c, al]; };
        const sobre = (f, b) => { const a = f[3]; return [0, 1, 2].map((i) => f[i] * a + b[i] * (1 - a)).concat(1); };
        const lum = ([R, G, B]) => { const f = (v) => { v /= 255; return v <= 0.03928 ? v / 12.92 : ((v + 0.055) / 1.055) ** 2.4; }; return 0.2126 * f(R) + 0.7152 * f(G) + 0.0722 * f(B); };
        const cr = (a, b) => { const [x, y] = [lum(a), lum(b)].sort((m, n) => n - m); return (x + 0.05) / (y + 0.05); };
        const padre = (x) => x.parentElement || (x.getRootNode() instanceof ShadowRoot ? x.getRootNode().host : null);
        const fondoDe = (x0) => { const capas = []; for (let x = x0; x; x = padre(x)) { const c = parse(getComputedStyle(x).backgroundColor); if (c[3] > 0) capas.push(c); if (c[3] >= 1) break; } return capas.reduceRight((abajo, c) => sobre(c, abajo), [255, 255, 255, 1]); };
        const malos = [], vistos = [];
        for (const x of r.querySelectorAll(".memoria-panel *")) {
          if (x instanceof SVGElement || x.disabled || !x.getClientRects().length) continue;
          if (![...x.childNodes].some((n) => n.nodeType === 3 && n.textContent.trim())) continue;
          const f = fondoDe(x), c = cr(sobre(parse(getComputedStyle(x).color), f), f);
          vistos.push(x.className || x.tagName);
          if (c < 4.5) malos.push(`${x.tagName}.${x.className} «${x.textContent.trim().slice(0, 20)}»: ${c.toFixed(2)}`);
        }
        return { malos, n: vistos.length, oscuro: r.classList.contains("oscuro") };
      });
      afirma(a.oscuro === (esquema === "dark"), "tema " + JSON.stringify(a));
      afirma(a.n >= 8 && a.malos.length === 0, JSON.stringify(a));
    });
    await p.close();
  }

  // — Tarjeta local: se confirma con la sesión, sin pedir token de escritura al sistema —
  {
    const { p, visto, enviar, tarjeta } = await nueva({
      memoria: true, propuesta: (n) => local(n),
      confirmarLocal: () => ({ status: 200, json: { estado: "ejecutada", ok: true, mensaje: "Listo, lo voy a recordar.", ui: [] } }),
    });
    await enviar();
    await caso("la tarjeta local se ve como cualquier otra: resumen del servidor, Confirmar y Cancelar, cuenta regresiva", async () => {
      const t = tarjeta();
      await t.waitFor();
      afirma((await t.locator(".accion-resumen").textContent()) === "Recordar: “la sojera” = San Pedro (establecimiento 4)", "resumen");
      afirma(await t.locator("button.primario").isVisible() && await t.locator("button", { hasText: "Cancelar" }).isVisible(), "botones");
      afirma(/Vence en 1:5|Vence en 2:0/.test(await t.locator(".accion-estado").textContent()), "cuenta regresiva");
    });
    await caso("un clic NO real (script) no confirma una tarjeta local", async () => {
      await p.locator("asistente-chat").evaluate((e) => e.shadowRoot.querySelector(".msg.confirmacion button.primario").click());
      await dormir(400);
      afirma(visto.local.length === 0 && visto.token.length === 0, "un click() de script confirmó");
    });
    await caso("Confirmar usa POST …/confirmar-local con la sesión normal y NO pide token de escritura al sistema anfitrión", async () => {
      await tarjeta().locator("button.primario").click();
      await tarjeta().locator(".accion-estado", { hasText: "Listo, lo voy a recordar." }).waitFor();
      afirma(visto.token.length === 0, "pidió token de escritura al anfitrión: " + JSON.stringify(visto.token));
      afirma(visto.confirmar.length === 0, "usó la ruta del anfitrión");
      afirma(visto.local.length === 1 && visto.local[0].url.endsWith("/v1/confirmaciones/acc-1/confirmar-local"), "ruta: " + JSON.stringify(visto.local));
      afirma(/^Bearer ey/.test(visto.local[0].auth) && visto.local[0].auth !== "Bearer tok-escritura", "la sesión: " + visto.local[0].auth?.slice(0, 20));
    });
    await caso("al terminar: botones fuera, estado «Listo» y evento al anfitrión con la tool local", async () => {
      afirma(!(await tarjeta().locator("button.primario").isVisible()), "los botones siguen visibles");
      const ev = await p.evaluate(() => window.__eventos);
      afirma(ev.length === 1 && ev[0].estado === "ejecutada" && ev[0].tool === "recordar" && ev[0].id === "acc-1", JSON.stringify(ev));
    });
    await p.close();
  }

  // — Tarjeta local: cancelar, tope y errores —
  {
    const { p, visto, enviar, tarjeta } = await nueva({ memoria: true, propuesta: (n) => local(n) });
    await enviar();
    await caso("Cancelar una tarjeta local usa la ruta de siempre, con la sesión", async () => {
      await tarjeta().locator("button", { hasText: "Cancelar" }).click();
      await tarjeta().locator(".accion-estado", { hasText: "Cancelada." }).waitFor();
      afirma(visto.cancelar.length === 1 && visto.local.length === 0 && visto.token.length === 0, JSON.stringify(visto));
    });
    await p.close();
  }
  for (const [titulo, respuesta, esperado] of [
    ["tope de recuerdos alcanzado", { status: 200, json: { estado: "fallida", ok: false, error: "tope_alcanzado" } }, "Ya hay 20 cosas guardadas"],
    ["memoria apagada entre la propuesta y el clic (403)", { status: 403, json: { error: "memoria_no_habilitada" } }, "no está habilitada"],
    ["acción que no es local (403)", { status: 403, json: { error: "accion_no_local" } }, "no es válida"],
    ["ya confirmada (409, doble clic en otra pestaña)", { status: 409, json: { error: "accion_no_pendiente", estado: "ejecutada" } }, "Hecho."],
  ]) {
    const { p, enviar, tarjeta } = await nueva({ memoria: true, propuesta: (n) => local(n), confirmarLocal: () => respuesta });
    await enviar();
    await caso(`confirmar local: ${titulo}`, async () => {
      await tarjeta().locator("button.primario").click();
      await tarjeta().locator(".accion-estado", { hasText: esperado }).waitFor();
      afirma(!(await tarjeta().locator("button.primario").isVisible()), "los botones siguen visibles");
    });
    await p.close();
  }

  // — Control: una acción del anfitrión (sin `local`) sigue pidiendo su token de escritura —
  {
    const { p, visto, enviar, tarjeta } = await nueva({
      memoria: true, propuesta: (n) => local(n, { tool: "agregar_nota", local: undefined, resumen: "Agregar una nota" }),
      confirmar: () => ({ status: 200, json: { estado: "ejecutada", ok: true, mensaje: "Nota agregada.", ui: [] } }),
    });
    await enviar();
    await caso("una tarjeta del anfitrión sigue pidiendo el token de escritura y usa /confirmar (no /confirmar-local)", async () => {
      await tarjeta().locator("button.primario").click();
      await tarjeta().locator(".accion-estado", { hasText: "Nota agregada." }).waitFor();
      afirma(visto.token.length === 1 && visto.local.length === 0, JSON.stringify(visto));
      afirma(visto.confirmar.length === 1 && visto.confirmar[0].auth === "Bearer tok-escritura" && visto.confirmar[0].url.endsWith("/v1/confirmaciones/acc-1/confirmar"), JSON.stringify(visto.confirmar));
    });
    await p.close();
  }

  const ok = resultados.filter((r) => r.ok).length;
  return { resultados, resumen: `${ok}/${resultados.length} ok` };
}
