// E2E del dictado y la respuesta hablada con la voz DEL NAVEGADOR (Web Speech). Sin LLM, sin whisper y
// sin micrófono real: SpeechRecognition y speechSynthesis se simulan con un guion y la respuesta del chat
// se fabrica con page.route. Comprueba el cableado del widget (no la calidad de las voces, que se juzga
// a mano, ver PRUEBA_MANUAL_VOZ.md). Se ejecuta como widget.e2e.js (ver README.md).
async (page) => {
  const BASE = "http://localhost:8203";
  const SHOTS = ".playwright-mcp/e2e";
  const resultados = [];
  const caso = async (nombre, fn) => {
    try { await fn(); resultados.push({ nombre, ok: true }); }
    catch (e) { resultados.push({ nombre, ok: false, detalle: String(e.message).split("\n")[0].slice(0, 300) }); }
  };
  const afirma = (c, m) => { if (!c) throw new Error(m); };

  const RESPUESTA = "Tenés **870,5** hectáreas de soja. Querés compararlas con la zafra anterior?";
  const abrir = async (modoReco) => {
    const p = await page.context().newPage();
    await p.setViewportSize({ width: 1280, height: 800 });
    await p.route("**/v1/chat", (route) => route.fulfill({
      status: 200,
      headers: { "content-type": "text/event-stream", "access-control-allow-origin": "http://localhost:8203" },
      body: `event: delta\ndata: ${JSON.stringify({ texto: "Tenés **870,5** hectáreas de soja. " })}\n\n`
        + `event: delta\ndata: ${JSON.stringify({ texto: "Querés compararlas con la zafra anterior?" })}\n\n`
        + `event: done\ndata: ${JSON.stringify({ conversacion_id: "00000000-0000-0000-0000-000000000000" })}\n\n`,
    }));
    await p.addInitScript((modoReco) => {
      window.__reco = { modo: modoReco, inicios: 0, abortos: 0, paradas: 0 };
      const resultado = (texto, final) => ({ resultIndex: 0, results: [Object.assign([{ transcript: texto, confidence: 0.9 }], { isFinal: final })] });
      window.SpeechRecognition = window.webkitSpeechRecognition = class {
        start() {
          window.__reco.inicios++;
          this.onstart && this.onstart();
          if (window.__reco.modo === "red") { setTimeout(() => { this.onerror && this.onerror({ error: "network" }); this.onend && this.onend(); }, 30); return; }
          if (window.__reco.modo === "silencio") { setTimeout(() => { this.onerror && this.onerror({ error: "no-speech" }); this.onend && this.onend(); }, 30); return; }
          setTimeout(() => this.onresult && this.onresult(resultado("cuántas hectáreas", false)), 30);
          setTimeout(() => { this.onresult && this.onresult(resultado("cuántas hectáreas de soja tengo", true)); this.onend && this.onend(); }, 400);
        }
        stop() { window.__reco.paradas++; }
        abort() { window.__reco.abortos++; }
      };
      window.__voz = { dichas: [], cancelaciones: 0 };
      window.SpeechSynthesisUtterance = class { constructor(t) { this.text = t; } };
      Object.defineProperty(window, "speechSynthesis", { configurable: true, value: {
        getVoices: () => [{ name: "Mexicana", lang: "es-MX" }, { name: "Española", lang: "es-ES" }, { name: "Inglesa", lang: "en-US" }],
        speak(u) { window.__voz.dichas.push({ texto: u.text, voz: u.voice && u.voice.name, lang: u.lang }); setTimeout(() => u.onend && u.onend(), 20); },
        cancel() { window.__voz.cancelaciones++; },
      } });
    }, modoReco);
    await p.goto(`${BASE}/?usuario=ana`);
    await p.locator("asistente-chat textarea").waitFor();
    return p;
  };
  const W = (p, sel) => p.locator(`asistente-chat ${sel}`);
  const esperarFin = (p) => p.waitForFunction(() => document.querySelector("asistente-chat").shadowRoot.querySelector("[aria-busy]")?.getAttribute("aria-busy") === "false", null, { timeout: 15000 });
  const enviar = async (p, texto) => { await W(p, "textarea").fill(texto); await W(p, "textarea").press("Enter"); await esperarFin(p); };

  // ── dictado con el navegador ──
  const p = await abrir("ok");
  await caso("el micrófono aparece aunque el servidor no ofrezca STT: el navegador basta", async () => {
    await W(p, "button.mic").waitFor({ state: "visible", timeout: 10000 });
  });
  await caso("dictar: muestra el texto parcial y deja el final en el campo sin enviar", async () => {
    await W(p, "button.mic").click();
    await W(p, "button.mic.grabando").waitFor();
    await p.waitForFunction(() => document.querySelector("asistente-chat").shadowRoot.querySelector(".aviso-voz").textContent.includes("cuántas hectáreas"), null, { timeout: 3000 });
    await p.screenshot({ path: `${SHOTS}/30-reco-parcial.png` });
    await p.waitForFunction(() => !document.querySelector("asistente-chat").shadowRoot.querySelector("button.mic.grabando"), null, { timeout: 3000 });
    afirma((await W(p, "textarea").inputValue()) === "cuántas hectáreas de soja tengo", "campo: «" + await W(p, "textarea").inputValue() + "»");
    afirma(await W(p, ".msg").count() === 0, "se envió sin confirmar");
    afirma((await W(p, ".aviso-voz").innerText()).trim() === "", "aviso visible: " + await W(p, ".aviso-voz").innerText());
    afirma(await p.evaluate(() => window.__reco.inicios) === 1, "no usó el reconocimiento del navegador");
  });

  // ── respuesta hablada ──
  await caso("sin lectura automática no habla; la respuesta trae su botón de escuchar y no ensucia el texto", async () => {
    await enviar(p, "pregunta");
    afirma((await p.evaluate(() => window.__voz.dichas.length)) === 0, "habló sin pedirlo");
    await W(p, ".msg.assistant button.escuchar").waitFor();
    const t = await W(p, ".msg.assistant").last().innerText();
    afirma(/870,5/.test(t) && !/escuchar/i.test(t), "texto inesperado: " + t);
  });
  await caso("el botón de escuchar lee la respuesta completa, sin símbolos, con la voz es-ES", async () => {
    await W(p, ".msg.assistant button.escuchar").last().click();
    const d = await p.evaluate(() => window.__voz.dichas);
    afirma(d.length === 1, "piezas: " + d.length);
    afirma(d[0].texto === "Tenés 870,5 hectáreas de soja. Querés compararlas con la zafra anterior?", "texto leído: «" + d[0].texto + "»");
    afirma(d[0].voz === "Española" && d[0].lang === "es-ES", `voz: ${d[0].voz}/${d[0].lang} (sin es-UY debía caer en es-ES)`);
  });
  await caso("lectura automática: lee por oraciones, en orden, al llegar la respuesta", async () => {
    await W(p, "button.altavoz").click();
    afirma((await W(p, "button.altavoz").getAttribute("aria-pressed")) === "true", "el altavoz no quedó activado");
    await p.evaluate(() => { window.__voz.dichas.length = 0; });
    await enviar(p, "otra pregunta");
    const d = (await p.evaluate(() => window.__voz.dichas)).map((x) => x.texto.trim());
    afirma(d.length === 2, "piezas: " + JSON.stringify(d));
    afirma(d[0] === "Tenés 870,5 hectáreas de soja." && d[1] === "Querés compararlas con la zafra anterior?", "orden/texto: " + JSON.stringify(d));
  });
  await p.screenshot({ path: `${SHOTS}/31-voz-lectura.png` });
  await caso("dictar mientras habla el asistente lo calla", async () => {
    const antes = await p.evaluate(() => window.__voz.cancelaciones);
    await W(p, "button.mic").click();
    afirma((await p.evaluate(() => window.__voz.cancelaciones)) > antes, "no canceló la síntesis");
    await p.waitForFunction(() => !document.querySelector("asistente-chat").shadowRoot.querySelector("button.mic.grabando"), null, { timeout: 3000 });
  });
  await caso("la lectura automática se recuerda en la pestaña (solo esa preferencia)", async () => {
    await p.reload();
    await W(p, "textarea").waitFor();
    afirma((await W(p, "button.altavoz").getAttribute("aria-pressed")) === "true", "no recordó la preferencia");
    const claves = await p.evaluate(() => Object.keys(sessionStorage));
    afirma(!claves.some((k) => /token/i.test(k)), "sessionStorage con token: " + claves);
  });
  await p.close();

  // ── errores del reconocimiento ──
  const r = await abrir("red");
  await caso("sin red al servicio de voz del navegador: aviso claro y el campo queda vacío", async () => {
    await W(r, "button.mic").click();
    await r.waitForFunction(() => document.querySelector("asistente-chat").shadowRoot.querySelector(".aviso-voz.err"), null, { timeout: 3000 });
    afirma(/navegador/i.test(await W(r, ".aviso-voz").innerText()), "aviso: " + await W(r, ".aviso-voz").innerText());
    afirma((await W(r, "textarea").inputValue()) === "", "campo con texto");
    afirma(!(await W(r, "button.mic.grabando").count()), "el micrófono quedó grabando");
  });
  await r.screenshot({ path: `${SHOTS}/32-reco-error.png` });
  await r.close();

  const s = await abrir("silencio");
  await caso("silencio: avisa que no se entendió nada", async () => {
    await W(s, "button.mic").click();
    await s.waitForFunction(() => document.querySelector("asistente-chat").shadowRoot.querySelector(".aviso-voz.err"), null, { timeout: 3000 });
    afirma((await W(s, "textarea").inputValue()) === "", "campo con texto");
  });
  await s.close();

  // ── el sistema anfitrión puede forzar el STT del servidor (evita enviar audio a Google) ──
  const f = await page.context().newPage();
  await f.addInitScript(() => { window.__reco = { inicios: 0 }; window.webkitSpeechRecognition = window.SpeechRecognition = class { start() { window.__reco.inicios++; } stop() {} abort() {} }; });
  await f.goto(`${BASE}/?usuario=ana`);
  await W(f, "textarea").waitFor();
  await caso("voz-motor=\"servidor\": no usa el reconocimiento del navegador", async () => {
    await f.evaluate(() => { document.querySelector("asistente-chat").setAttribute("voz-motor", "servidor"); });
    await f.waitForTimeout(500);
    const visible = await W(f, "button.mic").isVisible();
    if (visible) { await W(f, "button.mic").click(); await f.waitForTimeout(600); }   // abre el micrófono propio, no Web Speech
    afirma((await f.evaluate(() => window.__reco.inicios)) === 0, "usó Web Speech con voz-motor=servidor");
  });
  await f.close();

  return { resultados, resumen: `${resultados.filter((x) => x.ok).length}/${resultados.length} ok` };
}
