// E2E del widget <asistente-chat> en navegador real. Se ejecuta con el MCP de Playwright
// (browser_run_code_unsafe, parámetro `filename`); ver README.md. Fuera de la suite pytest.
// Devuelve {resultados: [{nombre, ok, detalle}], ...} y no lanza: todos los casos corren siempre.
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
  const abrir = async (usuario, ancho = 1280, alto = 800) => {
    const p = await ctx.newPage();
    await p.setViewportSize({ width: ancho, height: alto });
    await p.goto(`${BASE}/?usuario=${usuario}`);
    await p.locator("asistente-chat textarea").waitFor({ timeout: 15000 });
    return p;
  };
  const enviar = async (p, texto) => {
    await p.locator("asistente-chat textarea").fill(texto);
    await p.locator("asistente-chat textarea").press("Enter");
  };
  const esperaFin = (p) => p.waitForFunction(() => document.querySelector("asistente-chat").shadowRoot.querySelector("[aria-busy]")?.getAttribute("aria-busy") === "false", null, { timeout: 180000 });
  const ultima = (p) => p.locator("asistente-chat .msg.assistant").last();
  const PREGUNTA = "¿Cuántas hectáreas tengo en total y por cultivo? Usa la herramienta de resumen por cultivo.";

  // ── ana, modelo real ──
  const ana = await abrir("ana");
  let textoAna = "";
  await caso("carga: el widget monta con barra, entrada y bienvenida", async () => {
    afirma(await ana.locator("asistente-chat header.barra").isVisible(), "sin barra");
    afirma(await ana.locator("asistente-chat .bienvenida").isVisible(), "sin bienvenida");
    afirma(await ana.locator("asistente-chat .aviso").isHidden(), "aviso de no disponible visible");
  });
  await ana.screenshot({ path: `${SHOTS}/01-ana-inicio.png` });

  await caso("streaming: la burbuja crece en varios pasos antes de terminar (SSE real)", async () => {
    await ana.evaluate(() => {
      const col = document.querySelector("asistente-chat").shadowRoot.querySelector(".columna");
      window.__largos = [];
      new MutationObserver(() => {
        const u = [...col.querySelectorAll(".msg.assistant")].pop();
        const n = u ? u.textContent.length : 0;
        if (n && window.__largos[window.__largos.length - 1] !== n) window.__largos.push(n);
      }).observe(col, { subtree: true, childList: true, characterData: true });
    });
    await enviar(ana, PREGUNTA);
    await ana.locator("asistente-chat .msg.user").first().waitFor();
    await esperaFin(ana);
    const largos = await ana.evaluate(() => window.__largos);
    afirma(largos.length >= 3, `solo ${largos.length} estados intermedios: ${largos}`);
    afirma(largos.some((n, i) => i > 0 && n > largos[i - 1]), "el texto no crece");
    textoAna = await ultima(ana).innerText();
  });
  await ana.screenshot({ path: `${SHOTS}/02-ana-respuesta.png` });

  await caso("cifras de la tool: 870,5 en la respuesta de ana", async () => {
    afirma(/870[.,]5/.test(textoAna), "no aparece 870,5/870.5 en: " + textoAna.slice(0, 300));
    afirma(!/88[.,]2/.test(textoAna), "aparece 88,2 (dato de beto) en la respuesta de ana");
  });

  await caso("historial de la conversación actual: tras recargar, vuelven pregunta y respuesta", async () => {
    await ana.reload();
    await ana.locator("asistente-chat .msg.assistant").last().waitFor({ timeout: 15000 });
    afirma((await ana.locator("asistente-chat .msg.user").first().innerText()).includes("hectáreas"), "falta la pregunta");
    afirma(/870[.,]5/.test(await ultima(ana).innerText()), "falta la respuesta con 870,5");
    afirma(await ana.locator("asistente-chat .lateral").count() === 0, "se renderiza la barra lateral de historial");
  });
  await ana.screenshot({ path: `${SHOTS}/03-ana-recargada.png` });

  // ── beto: aislamiento ──
  const beto = await abrir("beto");
  await caso("aislamiento: beto empieza vacío (no ve la conversación de ana)", async () => {
    afirma(await beto.locator("asistente-chat .msg").count() === 0, "beto ve mensajes al abrir");
    afirma(await beto.locator("asistente-chat .bienvenida").isVisible(), "sin bienvenida");
  });
  await caso("aislamiento: beto pregunta y solo ve 88,2 (nunca 870,5 ni 540,5)", async () => {
    await enviar(beto, PREGUNTA);
    await beto.locator("asistente-chat .msg.user").first().waitFor();
    await esperaFin(beto);
    const t = await ultima(beto).innerText();
    afirma(/88[.,]2/.test(t), "falta 88,2 en: " + t.slice(0, 300));
    afirma(!/870[.,]5|540[.,]5|660[.,]5/.test(t), "datos de ana en la respuesta de beto");
    const todo = await beto.locator("asistente-chat").evaluate((e) => e.shadowRoot.textContent);
    afirma(!/El Matorral|870[.,]5/.test(todo), "rastro de ana en el DOM de beto");
  });
  await beto.screenshot({ path: `${SHOTS}/04-beto-respuesta.png` });
  await caso("aislamiento: el id de conversación de ana no sirve con el token de beto (404)", async () => {
    const idAna = await ana.evaluate(() => sessionStorage.length ? Object.values(sessionStorage).join(",") : "");
    afirma(idAna, "ana no guardó id en sessionStorage");
    const id = idAna.split(",").find((v) => /^[0-9a-f-]{20,}$/i.test(v)) || idAna.replace(/"/g, "");
    const st = await beto.evaluate(async ({ id }) => {
      const t = (await (await fetch("/asistente/token?usuario=beto")).json()).token;
      return (await fetch(`http://localhost:8100/v1/conversaciones/${id}`, { headers: { Authorization: "Bearer " + t } })).status;
    }, { id });
    afirma(st === 404, "estado " + st);
  });
  await beto.close();

  // ── Markdown sanitizado: SSE fabricado con tabla + script + onerror ──
  const san = await ctx.newPage();
  await san.setViewportSize({ width: 1280, height: 800 });
  await san.addInitScript(() => { window.__pwned = 0; });
  const md = [
    "Resumen:", "", "| Cultivo | Ha |", "|---|---|", "| soja | **660,5** |", "| maíz | 210,0 |", "",
    "<script>window.__pwned=1</script>", "",
    '<img src=x onerror="window.__pwned=2">', "",
    "[malo](javascript:window.__pwned=3) y [bueno](https://example.com)", "",
  ].join("\n");
  await san.route("**/v1/chat", (route) => route.fulfill({
    status: 200,
    headers: { "content-type": "text/event-stream", "access-control-allow-origin": "http://localhost:8203" },
    body: `event: delta\ndata: ${JSON.stringify({ texto: md })}\n\nevent: done\ndata: ${JSON.stringify({ conversacion_id: "00000000-0000-0000-0000-000000000000" })}\n\n`,
  }));
  await san.goto(`${BASE}/?usuario=ana`);
  await san.locator("asistente-chat textarea").waitFor();
  await enviar(san, "prueba");
  await san.locator("asistente-chat .msg.assistant table").waitFor({ timeout: 15000 }).catch(() => {});
  await caso("markdown: la tabla se renderiza como <table> con sus celdas", async () => {
    afirma(await san.locator("asistente-chat .msg.assistant table").count() === 1, "no hay tabla");
    afirma(await san.locator("asistente-chat .msg.assistant th").count() === 2, "cabeceras != 2");
    afirma((await san.locator("asistente-chat .msg.assistant td").allInnerTexts()).join("|").includes("660,5"), "falta celda");
  });
  await caso("sanitizado: <script> y onerror no se ejecutan ni se crean como nodos", async () => {
    await san.waitForTimeout(500);
    afirma(await san.evaluate(() => window.__pwned) === 0, "se ejecutó código: __pwned=" + await san.evaluate(() => window.__pwned));
    const n = await san.locator("asistente-chat").evaluate((e) => ({
      s: e.shadowRoot.querySelectorAll("script").length,
      i: e.shadowRoot.querySelectorAll("img").length,
      on: [...e.shadowRoot.querySelectorAll("*")].filter((x) => [...x.attributes].some((a) => a.name.startsWith("on"))).length,
      js: [...e.shadowRoot.querySelectorAll("a")].filter((a) => /^javascript:/i.test(a.getAttribute("href") || "")).length,
    }));
    afirma(n.s === 0 && n.i === 0 && n.on === 0 && n.js === 0, JSON.stringify(n));
  });
  await san.screenshot({ path: `${SHOTS}/05-markdown-sanitizado.png` });
  await san.close();

  return { resultados, resumen: `${resultados.filter((r) => r.ok).length}/${resultados.length} ok` };
}
