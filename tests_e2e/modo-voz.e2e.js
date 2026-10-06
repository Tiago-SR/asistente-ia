// E2E de la vista del modo voz: «otra ventana» con orbe (sin chat ni campo), alternancia con el chat, resumen hablado
// (evento SSE `voz`), respuesta completa en el chat y tarjeta de confirmación siempre a la vista. Sin LLM ni micrófono:
// el chat y la voz se simulan (como manos-libres.e2e.js). Se ejecuta como los demás (ver README.md).
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
  const COMPLETA = "Tenés **870,5** hectáreas de soja y 88,2 de maíz.\n\n| Cultivo | Superficie (ha) |\n|---|---|\n| Soja | 870,5 |\n| Maíz | 88,2 |\n";
  const RESUMEN = "Tenés unas 870 hectáreas de soja; el desglose está en pantalla.";

  // `guion`: lista de cuerpos SSE, uno por mensaje enviado; `pedidos` registra los cuerpos recibidos.
  const abrir = async (esquema, guion, { lento = false, mic = "ok", atributos = {}, demora = 0 } = {}) => {
    const p = await page.context().newPage();
    await p.emulateMedia({ colorScheme: esquema });
    await p.setViewportSize({ width: 1100, height: 760 });
    const pedidos = []; let n = 0;
    const ev = (e, d) => `event: ${e}\ndata: ${JSON.stringify(d)}\n\n`;
    await p.route("**/v1/chat", async (route) => {
      if (route.request().method() === "OPTIONS") return route.fulfill({ status: 204, headers: CORS });
      if (demora) await new Promise((r) => setTimeout(r, demora));   // un servidor lento (varias tools)
      pedidos.push(JSON.parse(route.request().postData()));
      const partes = guion[Math.min(n++, guion.length - 1)](ev);
      return route.fulfill({ status: 200, headers: { "content-type": "text/event-stream", ...CORS }, body: partes + ev("done", { conversacion_id: "00000000-0000-0000-0000-000000000000", tiempos_ms: { voz: 800, primer_delta: 900, total: 1500 } }) });
    });
    await p.addInitScript(({ lento, mic }) => {
      window.__mh = { actual: null };
      // micrófono y Web Audio simulados: `__nivelMic` (0..1) fija el volumen que «oye» el analizador
      window.__gum = { llamadas: 0, paradas: 0, ctxCerrados: 0 }; window.__nivelMic = 0;
      Object.defineProperty(navigator.mediaDevices, "getUserMedia", { configurable: true, value: async () => {
        window.__gum.llamadas++;
        if (mic === "rechaza") throw new DOMException("denegado", "NotAllowedError");
        return { getTracks: () => [{ stop: () => window.__gum.paradas++ }] };
      } });
      window.AudioContext = window.webkitAudioContext = class {
        createMediaStreamSource() { return { connect() {} }; }
        createAnalyser() { return { fftSize: 512, getByteTimeDomainData(a) { const v = Math.round(window.__nivelMic * 127); for (let i = 0; i < a.length; i++) a[i] = 128 + (i % 2 ? v : -v); } }; }
        close() { window.__gum.ctxCerrados++; }
      };
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
      window.__voz = { dichas: [], actual: null };
      window.SpeechSynthesisUtterance = class { constructor(t) { this.text = t; } };
      Object.defineProperty(window, "speechSynthesis", { configurable: true, value: {
        pendientes: [], getVoices: () => [{ name: "Española", lang: "es-ES" }],
        speak(u) { window.__voz.dichas.push(u.text); window.__voz.actual = u; this.pendientes.push(u); setTimeout(() => u.onstart && u.onstart(), 30); setTimeout(() => { if (!u.__c) { this.pendientes = this.pendientes.filter((x) => x !== u); u.onend && u.onend(); } }, lento ? 60000 : 20); },
        cancel() { for (const u of this.pendientes) { u.__c = true; setTimeout(() => u.onerror && u.onerror({ error: "canceled" }), 0); } this.pendientes = []; },
      } });
    }, { lento, mic });
    await p.goto(`${BASE}/?usuario=ana`);
    await p.locator("asistente-chat textarea").waitFor();
    if (Object.keys(atributos).length) await p.locator("asistente-chat").evaluate((e, a) => { for (const [k, v] of Object.entries(a)) e.setAttribute(k, v); }, atributos);
    return { p, pedidos };
  };
  const W = (p, sel) => p.locator(`asistente-chat ${sel}`);
  const etapa = (p, re) => p.waitForFunction((src) => new RegExp(src, "i").test(document.querySelector("asistente-chat").shadowRoot.querySelector(".mh-estado").textContent), re.source, { timeout: 5000 });
  const fin = (p) => p.waitForFunction(() => document.querySelector("asistente-chat").shadowRoot.querySelector("[aria-busy]")?.getAttribute("aria-busy") === "false", null, { timeout: 15000 });
  const raiz = (p, f) => p.locator("asistente-chat").evaluate((e, src) => (new Function("r", "return (" + src + ")(r)"))(e.shadowRoot.querySelector(".raiz")), f.toString());
  const enVoz = (p) => raiz(p, (r) => r.classList.contains("vista-voz"));
  const visible = (p, sel) => W(p, sel).first().isVisible();
  const preguntar = async (p, frase) => {
    await p.evaluate((f) => window.__decir("asistente " + f, true), frase);
    await etapa(p, /enviar.*cancelar/);
    await p.evaluate(() => window.__decir("enviar", true));
    await fin(p);
  };
  const conResumen = (ev) => ev("voz", { texto: RESUMEN }) + ev("delta", { texto: COMPLETA });

  for (const esquema of ["light", "dark"]) {
    const { p, pedidos } = await abrir(esquema, [conResumen]);
    const t = `[${esquema}] `;
    await caso(t + "al encender, el modo voz abre su propia vista: orbe, sin chat ni campo de texto", async () => {
      await W(p, "button.manos").click();
      await etapa(p, /para hablar/);
      afirma(await enVoz(p), "no está en la vista de voz");
      afirma(await visible(p, ".escena .orbe") && await visible(p, ".escena .mh-estado") && await visible(p, ".escena .mh-priv"), "falta orbe, estado o aviso de privacidad");
      afirma(!(await visible(p, ".scroll")) && !(await visible(p, "textarea")), "se ve el chat o el campo");
      afirma(!(await visible(p, ".barra .manos")), "el botón de la barra no debería verse en la vista de voz");
      afirma(await visible(p, "button.ver-chat") && await visible(p, ".mh-apagar"), "faltan «Ver el chat» o «Salir del modo voz»");
      afirma((await W(p, ".mh").getAttribute("data-estado")) === "armado", "estado del orbe");
      await p.screenshot({ path: `${SHOTS}/50-voz-${esquema}-armado.png` });
    });
    await caso(t + "capturando: lo dictado se ve en la vista de voz (el campo no)", async () => {
      await p.evaluate(() => window.__decir("asistente cuántas hectáreas de soja", false));
      await etapa(p, /escucho/);
      afirma((await W(p, ".mh").getAttribute("data-estado")) === "capturando", "estado del orbe");
      afirma(/hectáreas/.test(await W(p, ".mh-parcial").innerText()), "no muestra el parcial");
      await p.screenshot({ path: `${SHOTS}/51-voz-${esquema}-capturando.png` });
      await p.evaluate(() => window.__decir("asistente cuántas hectáreas de soja tengo", true));
      await etapa(p, /enviar.*cancelar/);
      afirma((await W(p, ".mh-campo").innerText()).trim() === "cuántas hectáreas de soja tengo", "el texto pendiente no se ve: «" + await W(p, ".mh-campo").innerText() + "»");
      afirma((await W(p, ".mh").getAttribute("data-estado")) === "confirmando", "estado del orbe");
      await p.screenshot({ path: `${SHOTS}/52-voz-${esquema}-confirmando.png` });
    });
    await caso(t + "enviar por voz: pide el canal «voz», dice solo el resumen y lo muestra; la respuesta completa queda en el chat", async () => {
      await p.evaluate(() => window.__decir("enviar", true));
      await fin(p);
      afirma(pedidos.length === 1 && pedidos[0].canal === "voz" && pedidos[0].mensaje === "cuántas hectáreas de soja tengo", JSON.stringify(pedidos));
      const dichas = await p.evaluate(() => window.__voz.dichas);
      afirma(dichas.length === 1 && dichas[0] === RESUMEN, "se dijo: " + JSON.stringify(dichas));
      afirma((await W(p, ".dicho").innerText()).includes(RESUMEN), "la vista de voz no muestra lo que se dice");
      afirma(await enVoz(p), "se salió de la vista de voz sin que el usuario lo pidiera");
      await p.screenshot({ path: `${SHOTS}/53-voz-${esquema}-dicho.png` });
      await W(p, "button.ver-chat").click();
      afirma(!(await enVoz(p)) && await visible(p, ".scroll") && await visible(p, "textarea"), "no pasó al chat");
      const respuesta = await W(p, ".msg.assistant").last().innerText();
      afirma(/870,5/.test(respuesta) && /88,2/.test(respuesta) && await W(p, ".msg.assistant table").count() === 1, "el chat no tiene la respuesta completa: " + respuesta);
      afirma(!/<voz>|desglose está en pantalla/.test(respuesta), "el resumen hablado se coló en el texto del chat");
      afirma((await W(p, ".msg.user").last().innerText()).trim() === "cuántas hectáreas de soja tengo", "falta lo que se dijo");
    });
    await caso(t + "en el chat con el modo voz encendido: panel compacto con el micrófono siempre visible, y se vuelve a la voz con «Voz»", async () => {
      afirma(await visible(p, ".mh .mh-priv") && await visible(p, ".mh .mh-apagar") && await visible(p, ".mh .orbe"), "el indicador de micrófono abierto no está visible en el chat");
      const alto = await W(p, ".mh").evaluate((e) => e.getBoundingClientRect().height);
      afirma(alto < 130, "el panel compacto es demasiado alto: " + alto);
      afirma((await W(p, "button.manos").getAttribute("aria-pressed")) === "true" && await visible(p, "button.manos"), "falta el botón «Voz» pulsado");
      await p.screenshot({ path: `${SHOTS}/54-voz-${esquema}-chat-compacto.png` });
      await W(p, "button.manos").click();
      afirma(await enVoz(p) && await visible(p, ".escena .mh"), "no volvió a la vista de voz");
    });
    await caso(t + "Esc y «Salir del modo voz» apagan desde cualquiera de las dos vistas", async () => {
      await W(p, "button.ver-chat").focus();
      await p.keyboard.press("Escape");
      afirma(!(await visible(p, ".mh")) && !(await enVoz(p)) && await visible(p, "textarea"), "Esc no apagó y volvió al chat");
      await W(p, "button.manos").click(); await etapa(p, /para hablar/);
      await W(p, "button.ver-chat").click();
      await W(p, ".mh-apagar").click();
      afirma(!(await visible(p, ".mh")) && !(await enVoz(p)), "«Salir del modo voz» no apagó");
    });
    await p.close();
  }

  // — sin bloque de voz: se dicen las dos primeras oraciones (la respuesta completa nunca se lee entera) —
  {
    const { p } = await abrir("light", [(ev) => ev("delta", { texto: "Tenés **870,5** hectáreas de soja. Y 88,2 de maíz. Hay más detalle abajo. Otra oración más." })]);
    await caso("sin resumen del modelo se dicen solo las dos primeras oraciones", async () => {
      await W(p, "button.manos").click(); await etapa(p, /para hablar/);
      await preguntar(p, "cuántas hectáreas");
      const dichas = await p.evaluate(() => window.__voz.dichas);
      afirma(dichas.length === 1 && dichas[0] === "Tenés 870,5 hectáreas de soja. Y 88,2 de maíz.", "se dijo: " + JSON.stringify(dichas));
    });
    await p.close();
  }

  // — fuera del modo voz: canal «texto», sin lectura —
  {
    const { p, pedidos } = await abrir("light", [(ev) => ev("delta", { texto: "Hola Ana." })]);
    await caso("sin el modo voz el chat pide canal «texto» y no cambia", async () => {
      await W(p, "textarea").fill("hola"); await W(p, "textarea").press("Enter"); await fin(p);
      afirma(pedidos[0].canal === "texto", JSON.stringify(pedidos[0]));
      afirma((await p.evaluate(() => window.__voz.dichas.length)) === 0, "habló sin el modo voz ni lectura automática");
    });
    await p.close();
  }

  // — acción propuesta: la tarjeta tiene que verse; nunca se confirma por voz —
  {
    const propuesta = (ev) => ev("confirmacion", { id: "acc-1", tool: "agregar_nota", huella: "h".repeat(64), expira: new Date(Date.now() + 600000).toISOString(),
      resumen: "Agregar una nota al establecimiento «El Matorral»", lineas: ["Texto: Helada"] }) + ev("voz", { texto: "Pedí agregar una nota; confirmala en pantalla." }) + ev("delta", { texto: "Pedí confirmar la nota." });
    const { p } = await abrir("dark", [propuesta]);
    await caso("una propuesta de acción saca de la vista de voz al chat, con la tarjeta visible, y se dice una sola frase (la del sistema)", async () => {
      await W(p, "button.manos").click(); await etapa(p, /para hablar/);
      await preguntar(p, "anotá helada en El Matorral");
      afirma(!(await enVoz(p)), "sigue en la vista de voz con una tarjeta pendiente");
      afirma(await visible(p, ".msg.confirmacion") && await visible(p, ".msg.confirmacion button.primario"), "la tarjeta no está a la vista");
      afirma(/chat/i.test(await W(p, ".aviso-voz").innerText()), "sin aviso de que la acción se confirma en el chat: " + await W(p, ".aviso-voz").innerText());
      const dichas = await p.evaluate(() => window.__voz.dichas);
      afirma(dichas.length === 1 && /pantalla/.test(dichas[0]) && /El Matorral/.test(dichas[0]), "se dijo: " + JSON.stringify(dichas));
      await p.evaluate(() => window.__decir("confirmar", true));            // ninguna orden de voz confirma
      await p.evaluate(() => window.__decir("asistente confirmar la acción", true));
      await p.waitForTimeout(400);
      afirma(await W(p, ".msg.confirmacion").count() === 1 && !/hecho|ejecutando/i.test(await W(p, ".accion-estado").innerText()), "algo reaccionó a «confirmar» por voz");
      await p.screenshot({ path: `${SHOTS}/55-voz-confirmacion-en-chat.png` });
    });
    await p.close();
  }

  // — movimiento reducido: sin animaciones, el estado se ve por el glifo —
  {
    const { p } = await abrir("light", [conResumen]);
    await p.emulateMedia({ reducedMotion: "reduce" });
    await caso("con prefers-reduced-motion no hay animaciones en el orbe y cada estado conserva su glifo", async () => {
      await W(p, "button.manos").click(); await etapa(p, /para hablar/);
      const medir = () => W(p, ".mh").evaluate((m) => {
        const todas = [...m.querySelectorAll("*")].filter((e) => getComputedStyle(e).animationName !== "none").length;
        const glifo = [...m.querySelectorAll(".o-glifo")].filter((g) => getComputedStyle(g).opacity === "1").map((g) => g.getAttribute("class").split("g-")[1]);
        return { animadas: todas, glifo };
      });
      let r = await medir(); afirma(r.animadas === 0 && r.glifo.join() === "mic", "armado: " + JSON.stringify(r));
      await p.evaluate(() => window.__decir("asistente hola", false)); await etapa(p, /escucho/);
      r = await medir(); afirma(r.animadas === 0 && r.glifo.join() === "esc", "capturando: " + JSON.stringify(r));
      await p.evaluate(() => window.__decir("asistente hola", true)); await etapa(p, /enviar.*cancelar/);
      r = await medir(); afirma(r.animadas === 0 && r.glifo.join() === "pausa", "confirmando: " + JSON.stringify(r));
    });
    await p.close();
  }

  // — volumen del orbe: micrófono real (simulado), pulsos del asistente y degradación —
  const nivel = (p) => W(p, ".mh").evaluate((m) => parseFloat(m.style.getPropertyValue("--nivel") || "0"));
  const hasta = (p, cond, arg) => p.waitForFunction(cond, arg, { timeout: 4000 });
  {
    const { p } = await abrir("dark", [conResumen]);
    await caso("el orbe sigue el volumen del micrófono: sube al hablar y baja en silencio", async () => {
      await W(p, "button.manos").click(); await etapa(p, /para hablar/);
      await hasta(p, () => window.__gum.llamadas === 1);
      afirma((await nivel(p)) < 0.05, "con silencio el orbe ya se mueve: " + await nivel(p));
      await p.evaluate(() => { window.__nivelMic = 0.15; });
      await hasta(p, () => parseFloat(document.querySelector("asistente-chat").shadowRoot.querySelector(".mh").style.getPropertyValue("--nivel") || "0") > 0.3);
      afirma(await W(p, ".escena .o-nivel").evaluate((e) => getComputedStyle(e).display !== "none" && parseFloat(getComputedStyle(e).opacity) > 0.2), "el anillo de volumen no se ve");
      await p.screenshot({ path: `${SHOTS}/56-voz-dark-volumen.png` });
      await p.evaluate(() => { window.__nivelMic = 0; });
      await hasta(p, () => parseFloat(document.querySelector("asistente-chat").shadowRoot.querySelector(".mh").style.getPropertyValue("--nivel") || "0") < 0.08);
    });
    await caso("mientras el asistente habla el micrófono no mueve el orbe (se oiría a él) y cada palabra da un pulso", async () => {
      await p.evaluate(() => window.__decir("asistente cuántas hectáreas", true)); await etapa(p, /enviar.*cancelar/);
      await p.evaluate(() => { window.__nivelMic = 0.2; window.__decir("enviar", true); });
      await hasta(p, () => document.querySelector("asistente-chat").shadowRoot.querySelector(".mh").dataset.estado === "hablando" || window.__voz.dichas.length > 0);
      await p.evaluate(() => { window.__nivelMic = 0; });
      await p.waitForTimeout(700);                       // se apaga el nivel del micrófono y no hay pulsos todavía
      afirma((await nivel(p)) < 0.1, "el orbe se movió sin pulsos: " + await nivel(p));
      await p.evaluate(() => { document.querySelector("asistente-chat").shadowRoot.querySelector(".mh").dataset.estado = "hablando"; window.__voz.actual && window.__voz.actual.onboundary && window.__voz.actual.onboundary(); });
      await hasta(p, () => parseFloat(document.querySelector("asistente-chat").shadowRoot.querySelector(".mh").style.getPropertyValue("--nivel") || "0") > 0.15);
    });
    await caso("al salir del modo voz se paran el micrófono de medición y el contexto de audio, y el orbe vuelve a cero", async () => {
      await W(p, "button.ver-chat").click().catch(() => {});
      await W(p, ".mh-apagar").click();
      const g = await p.evaluate(() => window.__gum);
      afirma(g.llamadas === 1 && g.paradas === 1 && g.ctxCerrados === 1, JSON.stringify(g));
      afirma(!(await W(p, ".mh").evaluate((m) => m.style.getPropertyValue("--nivel"))), "queda un nivel escrito");
    });
    await p.close();
  }
  {
    const { p } = await abrir("light", [conResumen], { mic: "rechaza" });
    await caso("si el navegador no da el segundo flujo de audio, el modo voz funciona igual (sin volumen) y sin avisos de error", async () => {
      await W(p, "button.manos").click(); await etapa(p, /para hablar/);
      await hasta(p, () => window.__gum.llamadas === 1);
      await preguntar(p, "cuántas hectáreas");
      afirma(await enVoz(p) && (await W(p, ".dicho").innerText()).includes(RESUMEN), "el modo voz dejó de funcionar");
      afirma((await W(p, ".aviso-voz.err").count()) === 0, "mostró un error por no poder medir el volumen");
      afirma((await nivel(p)) === 0, "hay nivel sin micrófono");
    });
    await p.close();
  }
  {
    const { p } = await abrir("light", [conResumen], { atributos: { "orbe-volumen": "no" } });
    await caso("orbe-volumen=\"no\" no abre ningún segundo flujo de audio", async () => {
      await W(p, "button.manos").click(); await etapa(p, /para hablar/);
      await p.waitForTimeout(400);
      afirma((await p.evaluate(() => window.__gum.llamadas)) === 0, "pidió el micrófono");
    });
    await p.close();
  }
  {
    const { p } = await abrir("light", [conResumen]);
    await p.emulateMedia({ reducedMotion: "reduce" });
    await caso("con movimiento reducido no se abre el segundo flujo de audio ni se anima el volumen", async () => {
      await W(p, "button.manos").click(); await etapa(p, /para hablar/);
      await p.evaluate(() => { window.__nivelMic = 0.5; });
      await p.waitForTimeout(500);
      afirma((await p.evaluate(() => window.__gum.llamadas)) === 0 && (await nivel(p)) === 0, "midió el volumen con movimiento reducido");
      afirma(await W(p, ".o-nivel").evaluate((e) => getComputedStyle(e).display === "none"), "el anillo de volumen se ve");
    });
    await p.close();
  }

  // — tiempos del turno por voz: evento asistente:metricas (solo números) —
  {
    const { p } = await abrir("light", [conResumen]);
    await p.evaluate(() => { window.__metricas = []; document.addEventListener("asistente:metricas", (e) => window.__metricas.push(e.detail)); });
    await caso("cada turno por voz informa cuánto tardó: llegada del resumen, inicio de la voz y tiempos del servidor", async () => {
      await W(p, "button.manos").click(); await etapa(p, /para hablar/);
      await preguntar(p, "cuántas hectáreas");
      await hasta(p, () => window.__metricas.length === 1);
      const m = await p.evaluate(() => window.__metricas[0]);
      afirma(m.canal === "voz" && m.fuente === "resumen", JSON.stringify(m));
      afirma(Number.isInteger(m.voz_ms) && Number.isInteger(m.habla_ms) && m.voz_ms >= 0 && m.habla_ms >= m.voz_ms, "tiempos incoherentes: " + JSON.stringify(m));
      afirma(Number.isInteger(m.tts_ms) && m.tts_ms >= 0 && m.servidor && m.servidor.voz === 800, "faltan tts o servidor: " + JSON.stringify(m));
      afirma(!JSON.stringify(m).match(/hect|870|soja/i), "el evento lleva texto del usuario o de la respuesta");
      await p.waitForTimeout(3500);
      afirma((await p.evaluate(() => window.__metricas.length)) === 1, "se emitió más de una vez");
    });
    await p.close();
  }
  {
    const { p } = await abrir("light", [(ev) => ev("delta", { texto: "Tenés **870,5** hectáreas de soja. Y 88,2 de maíz." })]);
    await p.evaluate(() => { window.__metricas = []; document.addEventListener("asistente:metricas", (e) => window.__metricas.push(e.detail)); });
    await caso("sin resumen del modelo la fuente es «respaldo» y voz_ms es null", async () => {
      await W(p, "button.manos").click(); await etapa(p, /para hablar/);
      await preguntar(p, "cuántas hectáreas");
      await hasta(p, () => window.__metricas.length === 1);
      const m = await p.evaluate(() => window.__metricas[0]);
      afirma(m.fuente === "respaldo" && m.voz_ms === null && Number.isInteger(m.habla_ms), JSON.stringify(m));
    });
    await p.close();
  }
  {
    const { p } = await abrir("light", [(ev) => ev("delta", { texto: "Hola Ana." })]);
    await p.evaluate(() => { window.__metricas = []; document.addEventListener("asistente:metricas", (e) => window.__metricas.push(e.detail)); });
    await caso("el chat de texto no emite métricas de voz", async () => {
      await W(p, "textarea").fill("hola"); await W(p, "textarea").press("Enter"); await fin(p);
      await p.waitForTimeout(3300);
      afirma((await p.evaluate(() => window.__metricas.length)) === 0, "emitió métricas fuera del modo voz");
    });
    await p.close();
  }

  // — acuse inmediato: una frase corta si el resumen tarda; nada si llega rápido —
  const FRASES = ["Un momento, lo consulto.", "Ya lo busco.", "Dame un segundo."];
  {
    const { p } = await abrir("dark", [conResumen], { demora: 1800 });
    await p.evaluate(() => { window.__metricas = []; document.addEventListener("asistente:metricas", (e) => window.__metricas.push(e.detail)); });
    await caso("si el resumen tarda, se dice un acuse corto antes y después el resumen; las métricas lo registran", async () => {
      await W(p, "button.manos").click(); await etapa(p, /para hablar/);
      await preguntar(p, "cuántas hectáreas");
      const dichas = await p.evaluate(() => window.__voz.dichas);
      afirma(dichas.length === 2 && FRASES.includes(dichas[0]) && dichas[1] === RESUMEN, "se dijo: " + JSON.stringify(dichas));
      await hasta(p, () => window.__metricas.length === 1);
      const m = await p.evaluate(() => window.__metricas[0]);
      afirma(Number.isInteger(m.acuse_ms) && m.acuse_ms >= 850 && m.acuse_ms < m.voz_ms, "acuse_ms incoherente: " + JSON.stringify(m));
      afirma(m.habla_ms >= m.voz_ms, "habla_ms debe ser el del resumen, no el del acuse: " + JSON.stringify(m));
      afirma(!(await W(p, ".dicho").innerText()).match(/momento|busco|segundo/i), "el acuse se mostró como si fuera la respuesta");
    });
    await caso("las frases del acuse rotan entre turnos", async () => {
      await preguntar(p, "y de maíz");
      const acuses = (await p.evaluate(() => window.__voz.dichas)).filter((d) => FRASES.includes(d));
      afirma(acuses.length === 2 && acuses[0] !== acuses[1], "se dijo: " + JSON.stringify(acuses));
    });
    await p.close();
  }
  {
    const { p, pedidos } = await abrir("dark", [conResumen]);   // respuesta inmediata
    await caso("si el resumen llega rápido no se dice ningún acuse", async () => {
      await W(p, "button.manos").click(); await etapa(p, /para hablar/);
      await preguntar(p, "cuántas hectáreas");
      await p.waitForTimeout(1100);                       // pasa el plazo del acuse: el turno ya terminó y no debe sonar nada
      const dichas = await p.evaluate(() => window.__voz.dichas);
      afirma(pedidos.length === 1 && dichas.length === 1 && dichas[0] === RESUMEN, "se dijo: " + JSON.stringify(dichas));
    });
    await p.close();
  }
  {
    const { p } = await abrir("dark", [conResumen], { demora: 1800, atributos: { acuse: "no" } });
    await caso("acuse=\"no\" lo quita: solo se dice el resumen", async () => {
      await W(p, "button.manos").click(); await etapa(p, /para hablar/);
      await preguntar(p, "cuántas hectáreas");
      const dichas = await p.evaluate(() => window.__voz.dichas);
      afirma(dichas.length === 1 && dichas[0] === RESUMEN, "se dijo: " + JSON.stringify(dichas));
    });
    await p.close();
  }
  {
    const { p } = await abrir("dark", [conResumen], { demora: 2600 });
    await caso("si se apaga el modo o se interrumpe antes del plazo, no suena el acuse", async () => {
      await W(p, "button.manos").click(); await etapa(p, /para hablar/);
      await p.evaluate(() => window.__decir("asistente cuántas hectáreas", true)); await etapa(p, /enviar.*cancelar/);
      await p.evaluate(() => window.__decir("enviar", true));
      await W(p, ".mh-apagar").click();                   // sale del modo voz mientras espera la respuesta
      await p.waitForTimeout(1400);
      afirma((await p.evaluate(() => window.__voz.dichas.length)) === 0, "habló un acuse con el modo apagado");
    });
    await p.close();
  }

  return { resultados, resumen: `${resultados.filter((r) => r.ok).length}/${resultados.length} ok` };
}
