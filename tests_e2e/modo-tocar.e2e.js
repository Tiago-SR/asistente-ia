// E2E del modo voz «tocar para hablar» (un turno por toque, sin palabra de activación ni reconocimiento continuo), con el
// reconocimiento del navegador y con el STT del servidor (getUserMedia + MediaRecorder + /v1/voz/transcribir). Sin LLM ni
// micrófono: SpeechRecognition, speechSynthesis, getUserMedia, MediaRecorder y Web Audio se simulan; el chat, /v1/estado y
// la transcripción se fabrican con page.route. No juzga el reconocimiento real (para eso, el celular: PRUEBA_MANUAL_VOZ.md).
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
  const CORS = { "access-control-allow-origin": BASE, "access-control-allow-headers": "authorization,content-type,accept,x-audio-duracion-s", "access-control-allow-methods": "GET,POST,OPTIONS" };
  const RESUMEN = "Tenés unas 870 hectáreas de soja; el desglose está en pantalla.";
  const COMPLETA = "Tenés **870,5** hectáreas de soja.";

  // `atributos`: atributos del widget antes de cargar el estado; `ua`: user agent simulado; `lento`: la voz del asistente no termina sola.
  const abrir = async ({ atributos = {}, ua = null, lento = false, dictado = true, textoStt = "cuántas hectáreas de soja tengo", reco = true } = {}) => {
    const p = await page.context().newPage();
    await p.setViewportSize({ width: 420, height: 800 });
    const visto = { chat: [], stt: [], sttTipos: [] };
    const ev = (e, d) => `event: ${e}\ndata: ${JSON.stringify(d)}\n\n`;
    await p.route("**/v1/estado", (route) => {
      if (route.request().method() === "OPTIONS") return route.fulfill({ status: 204, headers: CORS });
      return route.fulfill({ status: 200, headers: { "content-type": "application/json", ...CORS }, body: JSON.stringify({
        habilitado: true, nombre_sistema: "Sistema PHP", nombre_asistente: "Asistente", memoria: false, voz: { dictado, respuesta: false, max_audio_s: 60 } }) });
    });
    await p.route("**/v1/chat", (route) => {
      if (route.request().method() === "OPTIONS") return route.fulfill({ status: 204, headers: CORS });
      visto.chat.push(JSON.parse(route.request().postData()));
      return route.fulfill({ status: 200, headers: { "content-type": "text/event-stream", ...CORS },
        body: ev("voz", { texto: RESUMEN }) + ev("delta", { texto: COMPLETA }) + ev("done", { conversacion_id: "00000000-0000-0000-0000-000000000000" }) });
    });
    await p.route("**/v1/voz/transcribir", (route) => {
      if (route.request().method() === "OPTIONS") return route.fulfill({ status: 204, headers: CORS });
      visto.stt.push(route.request().postDataBuffer()?.length || 0);
      visto.sttTipos.push(route.request().headers()["content-type"]);
      return route.fulfill({ status: 200, headers: { "content-type": "application/json", ...CORS }, body: JSON.stringify({ texto: textoStt }) });
    });
    await p.addInitScript(({ ua, lento, reco }) => {
      // los ajustes del usuario quedan en localStorage del navegador compartido: cada página parte limpia
      try { for (const k of Object.keys(localStorage)) if (k.startsWith("asistente:ajustes:")) localStorage.removeItem(k); } catch (e) { /* sin storage */ }
      if (ua) Object.defineProperty(navigator, "userAgent", { configurable: true, get: () => ua });
      window.__nivelMic = 0;
      window.__gum = { llamadas: 0, paradas: 0, ctxCerrados: 0 };
      Object.defineProperty(navigator.mediaDevices, "getUserMedia", { configurable: true, value: async () => {
        window.__gum.llamadas++;
        return { getTracks: () => [{ stop: () => window.__gum.paradas++ }] };
      } });
      window.AudioContext = window.webkitAudioContext = class {
        createMediaStreamSource() { return { connect() {} }; }
        createAnalyser() { return { fftSize: 512, getByteTimeDomainData(a) { const v = Math.round(window.__nivelMic * 127); for (let i = 0; i < a.length; i++) a[i] = 128 + (i % 2 ? v : -v); } }; }
        close() { window.__gum.ctxCerrados++; }
      };
      window.__rec = { inicios: 0, paradas: 0, abortos: 0, inicia: 0, continuous: null, actual: null };
      window.MediaRecorder = class {
        static isTypeSupported() { return true; }
        constructor() { this.state = "inactive"; this.mimeType = "audio/webm"; this.oyentes = {}; }
        addEventListener(t, f) { (this.oyentes[t] = this.oyentes[t] || []).push(f); }
        start() { this.state = "recording"; window.__rec.inicia++; }
        stop() {
          if (this.state === "inactive") return;
          this.state = "inactive";
          setTimeout(() => {
            for (const f of this.oyentes.dataavailable || []) f({ data: new Blob([new Uint8Array(3000)], { type: "audio/webm" }) });
            for (const f of this.oyentes.stop || []) f({});
          }, 0);
        }
      };
      if (reco) {
        window.SpeechRecognition = window.webkitSpeechRecognition = class {
          constructor() { this.results = []; window.__rec.actual = this; }
          start() { window.__rec.inicios++; window.__rec.continuous = this.continuous; setTimeout(() => this.onstart && this.onstart(), 0); }
          stop() { window.__rec.paradas++; setTimeout(() => this.onend && this.onend(), 0); }
          abort() { window.__rec.abortos++; }
        };
      } else { window.SpeechRecognition = window.webkitSpeechRecognition = undefined; }
      window.__decir = (texto, final = true) => {
        const r = window.__rec.actual;
        r.results.push(Object.assign([{ transcript: texto, confidence: 0.9 }], { isFinal: final }));
        r.onresult({ resultIndex: r.results.length - 1, results: r.results });
      };
      window.__terminar = () => window.__rec.actual.onend();
      window.__error = (e) => { window.__rec.actual.onerror({ error: e }); window.__rec.actual.onend(); };
      window.__voz = { dichas: [], cancelaciones: 0, pendientes: [] };
      window.SpeechSynthesisUtterance = class { constructor(t) { this.text = t; } };
      Object.defineProperty(window, "speechSynthesis", { configurable: true, value: {
        getVoices: () => [{ name: "Española", lang: "es-ES" }],
        speak(u) { window.__voz.dichas.push(u.text); window.__voz.pendientes.push(u); setTimeout(() => u.onstart && u.onstart(), 10); if (!lento) setTimeout(() => u.onend && u.onend(), 30); },
        cancel() { window.__voz.cancelaciones++; for (const u of window.__voz.pendientes) setTimeout(() => u.onerror && u.onerror({ error: "canceled" }), 0); window.__voz.pendientes = []; },
        get speaking() { return window.__voz.pendientes.length > 0; },
      } });
    }, { ua, lento, reco });
    await p.goto(`${BASE}/?usuario=ana`);
    await p.locator("asistente-chat .barra").waitFor();
    await dormir(500);
    // por defecto el widget abre en modo voz (con los atributos de la página): se apaga y se parte de cero con los de la prueba
    await p.locator("asistente-chat").evaluate((e) => { if (e._mhActivo()) e._mhApagar("", true); });
    if (Object.keys(atributos).length) {
      await p.locator("asistente-chat").evaluate((e, a) => { for (const [k, v] of Object.entries(a)) e.setAttribute(k, v); }, atributos);
    }
    await dormir(300);
    await p.evaluate(() => { Object.assign(window.__rec, { inicios: 0, paradas: 0, abortos: 0, inicia: 0 }); Object.assign(window.__gum, { llamadas: 0, paradas: 0, ctxCerrados: 0 }); });
    return { p, visto };
  };
  const W = (p, sel) => p.locator(`asistente-chat ${sel}`);
  const etiqueta = (p) => W(p, ".mh-estado").innerText();
  const estado = (p) => W(p, ".mh").getAttribute("data-estado");
  const etapa = (p, re) => p.waitForFunction((src) => new RegExp(src, "i").test(document.querySelector("asistente-chat").shadowRoot.querySelector(".mh-estado").textContent), re.source, { timeout: 8000 });
  const fin = (p) => p.waitForFunction(() => document.querySelector("asistente-chat").shadowRoot.querySelector("[aria-busy]")?.getAttribute("aria-busy") === "false", null, { timeout: 15000 });
  const rec = (p) => p.evaluate(() => ({ ...window.__rec, actual: undefined }));
  const gum = (p) => p.evaluate(() => ({ ...window.__gum }));
  const orbe = (p) => W(p, ".escena .orbe").click();

  // ───────────────────────── navegador, un turno por toque ─────────────────────────
  {
    const { p, visto } = await abrir({ atributos: { "modo-entrada": "tocar" } });
    await caso("«tocar»: al encender no abre el micrófono ni arranca el reconocimiento; queda «listo» con el botón Hablar", async () => {
      await W(p, "button.manos").click();
      await etapa(p, /Tocá el orbe para hablar/);
      afirma((await rec(p)).inicios === 0, "arrancó el reconocimiento al encender");
      afirma((await gum(p)).llamadas === 0, "abrió un flujo de micrófono al encender");
      afirma((await estado(p)) === "armado", "estado del orbe");
      afirma(await W(p, ".mh-hablar").isVisible() && (await W(p, ".mh-hablar").innerText()) === "Hablar", "falta el botón Hablar");
      afirma(/voz del navegador|Google/.test(await W(p, ".mh-priv").innerText()) && /solo mientras hablás/.test(await W(p, ".mh-priv").innerText()), "aviso de privacidad");
    });
    await caso("un toque abre UN turno no continuo; el final y el cierre llevan a confirmar, sin reiniciar", async () => {
      await orbe(p);
      await etapa(p, /Te escucho/);
      const r = await rec(p);
      afirma(r.inicios === 1 && r.continuous === false, "debería ser un arranque no continuo: " + JSON.stringify(r));
      afirma((await estado(p)) === "capturando" && (await W(p, ".mh-hablar").innerText()) === "Terminar", "estado del turno");
      await p.evaluate(() => window.__decir("cuántas hectáreas", false));
      afirma(/hectáreas/.test(await W(p, ".mh-parcial").innerText()), "no muestra el parcial");
      await p.evaluate(() => { window.__decir("cuántas hectáreas de soja tengo", true); window.__terminar(); });
      await etapa(p, /Tocá «Enviar»/);
      afirma((await W(p, "textarea").inputValue()) === "cuántas hectáreas de soja tengo", "el campo no tiene lo dictado");
      afirma((await estado(p)) === "confirmando" && visto.chat.length === 0, "no debería enviar sin confirmar");
      await dormir(1500);
      afirma((await rec(p)).inicios === 1, "reinició el reconocimiento solo");
    });
    await caso("confirmar (botón Enviar): pide el canal «voz», se dice el resumen y queda quieto hasta el próximo toque", async () => {
      await W(p, ".mh-enviar").click();
      await fin(p);
      afirma(visto.chat.length === 1 && visto.chat[0].canal === "voz", "pedido: " + JSON.stringify(visto.chat));
      await p.waitForFunction(() => window.__voz.dichas.some((t) => /870 hectáreas/.test(t)), null, { timeout: 5000 });
      await etapa(p, /Tocá el orbe para hablar/);
      await dormir(2000);
      const r = await rec(p);
      afirma(r.inicios === 1, "reabrió el micrófono solo: " + r.inicios);
      afirma((await estado(p)) === "armado", "no volvió a listo: " + (await estado(p)));
    });
    await caso("un segundo toque termina el turno (stop) y entrega lo dictado", async () => {
      await orbe(p);
      await etapa(p, /Te escucho/);
      await p.evaluate(() => window.__decir("y de maíz", true));
      await W(p, ".escena .orbe").click();                     // segundo toque
      await etapa(p, /Tocá «Enviar»/);
      afirma((await rec(p)).paradas === 1, "no llamó a stop()");
      afirma((await W(p, "textarea").inputValue()) === "y de maíz", "texto: " + (await W(p, "textarea").inputValue()));
      await W(p, ".mh-cancelar").click();
      await etapa(p, /Tocá el orbe para hablar/);
      afirma((await W(p, "textarea").inputValue()) === "", "cancelar no vació el campo");
    });
    await caso("sin voz (no-speech): vuelve a listo con el aviso y no reabre el micrófono", async () => {
      await orbe(p);
      await etapa(p, /Te escucho/);
      const antes = (await rec(p)).inicios;
      await p.evaluate(() => window.__error("no-speech"));
      await etapa(p, /Tocá el orbe para hablar/);
      afirma(/No se entendió/.test(await W(p, ".aviso-voz").innerText()), "sin aviso: " + await W(p, ".aviso-voz").innerText());
      await dormir(1200);
      afirma((await rec(p)).inicios === antes, "reabrió solo");
    });
    await caso("permiso de micrófono denegado: apaga el modo voz con el aviso", async () => {
      await orbe(p);
      await etapa(p, /Te escucho/);
      await p.evaluate(() => window.__error("not-allowed"));
      await p.waitForFunction(() => !document.querySelector("asistente-chat").shadowRoot.querySelector(".raiz").classList.contains("vista-voz"), null, { timeout: 5000 });
    });
    await p.close();
  }

  // ───────────────────────── tocar corta la lectura ─────────────────────────
  {
    const { p, visto } = await abrir({ atributos: { "modo-entrada": "tocar" }, lento: true });
    await caso("tocar el orbe mientras el asistente habla corta la lectura y abre el micrófono (sin interrupción por voz)", async () => {
      await W(p, "button.manos").click();
      await orbe(p);
      await etapa(p, /Te escucho/);
      await p.evaluate(() => { window.__decir("cuántas hectáreas de soja tengo", true); window.__terminar(); });
      await etapa(p, /Tocá «Enviar»/);
      await W(p, ".mh-enviar").click();
      await p.waitForFunction(() => window.__voz.dichas.some((t) => /870 hectáreas/.test(t)), null, { timeout: 8000 });
      await etapa(p, /interrumpir y hablar/);
      afirma((await estado(p)) === "hablando", "estado: " + (await estado(p)));
      const cortes = await p.evaluate(() => window.__voz.cancelaciones);
      await orbe(p);
      await etapa(p, /Te escucho/);
      afirma((await p.evaluate(() => window.__voz.cancelaciones)) > cortes, "no cortó la lectura");
      afirma((await rec(p)).inicios === 2, "no abrió el micrófono: " + (await rec(p)).inicios);
      afirma(visto.chat.length === 1, "pedidos: " + visto.chat.length);
    });
    await p.close();
  }

  // ───────────────────────── confirmar-local desactivado ─────────────────────────
  {
    const { p, visto } = await abrir({ atributos: { "modo-entrada": "tocar" } });
    await caso("sin confirmación (ajuste del usuario): el fin del turno envía directamente", async () => {
      await W(p, ".ajustes").click();
      await p.locator("asistente-chat #aj-confirmar").uncheck();
      await p.locator("asistente-chat .ajustes-panel button", { hasText: "Cerrar" }).click();
      await W(p, "button.manos").click();
      await orbe(p);
      await etapa(p, /Te escucho/);
      await p.evaluate(() => { window.__decir("cuántas hectáreas de soja tengo", true); window.__terminar(); });
      await fin(p);
      afirma(visto.chat.length === 1 && visto.chat[0].mensaje === "cuántas hectáreas de soja tengo", "pedido: " + JSON.stringify(visto.chat));
    });
    await caso("ajustes: «Cómo hablar en el modo voz» aparece y cambiarlo a manos libres reinicia el modo", async () => {
      await W(p, ".ajustes").click();
      afirma(await p.locator("asistente-chat input[name=aj-entrada]").first().isVisible(), "falta el selector de entrada");
      await p.locator("asistente-chat input[name=aj-entrada][value=entrada-libres]").check();
      afirma(!(await W(p, ".mh").isVisible()), "el modo voz debería apagarse al cambiar de modo");
      await p.locator("asistente-chat .ajustes-panel button", { hasText: "Cerrar" }).click();
      await W(p, "button.manos").click();
      await etapa(p, /Decí «asistente»/);
      afirma((await rec(p)).inicios >= 2, "manos libres debería arrancar el reconocimiento continuo");
    });
    await p.close();
  }

  // ───────────────────────── Android: «auto» es tocar ─────────────────────────
  {
    const ANDROID = "Mozilla/5.0 (Linux; Android 14; Pixel 8) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/130.0.0.0 Mobile Safari/537.36";
    const { p } = await abrir({ ua: ANDROID });
    await caso("en Android, modo-entrada=auto es «tocar»", async () => {
      await W(p, "button.manos").click();
      await etapa(p, /Tocá el orbe para hablar/);
      afirma((await rec(p)).inicios === 0, "arrancó el reconocimiento continuo en Android");
    });
    await p.close();
  }

  // ───────────────────────── STT del servidor ─────────────────────────
  {
    const { p, visto } = await abrir({ atributos: { "voz-motor": "servidor" } });
    await caso("voz-motor=\"servidor\": hay modo voz y es «tocar» (sin palabra de activación ni Web Speech)", async () => {
      afirma(await W(p, "button.manos").isVisible(), "el botón Voz no aparece con voz-motor=servidor");
      await W(p, "button.manos").click();
      await etapa(p, /Tocá el orbe para hablar/);
      afirma((await rec(p)).inicios === 0 && (await gum(p)).llamadas === 0, "abrió micrófono o reconocimiento al encender");
      afirma(/servicio de voz del asistente/.test(await W(p, ".mh-priv").innerText()), "aviso de privacidad: " + await W(p, ".mh-priv").innerText());
    });
    await caso("un toque abre el micrófono (getUserMedia), corta por silencio, transcribe en el servidor y lo cierra", async () => {
      await p.evaluate(() => { window.__nivelMic = 0.25; });
      await orbe(p);
      await etapa(p, /Te escucho/);
      afirma((await gum(p)).llamadas === 1 && (await p.evaluate(() => window.__rec.inicia)) === 1, "no grabó");
      await dormir(400);
      await p.evaluate(() => { window.__nivelMic = 0; });      // se calla: el fin llega ~1,2 s después
      await etapa(p, /Tocá «Enviar»/);
      afirma(visto.stt.length === 1 && visto.stt[0] > 0 && /audio\/webm/.test(visto.sttTipos[0]), "transcripción: " + JSON.stringify(visto));
      afirma((await W(p, "textarea").inputValue()) === "cuántas hectáreas de soja tengo", "el campo no tiene lo transcrito");
      const g = await gum(p);
      afirma(g.paradas >= 1 && g.ctxCerrados >= 1, "no cerró el micrófono: " + JSON.stringify(g));
      afirma((await rec(p)).inicios === 0, "usó Web Speech");
    });
    await caso("enviar: canal «voz» y queda quieto (no reabre el micrófono)", async () => {
      await W(p, ".mh-enviar").click();
      await fin(p);
      await etapa(p, /Tocá el orbe para hablar/);
      await dormir(1500);
      afirma(visto.chat.length === 1 && visto.chat[0].canal === "voz", "pedido: " + JSON.stringify(visto.chat));
      afirma((await gum(p)).llamadas === 1, "reabrió el micrófono solo");
    });
    await caso("segundo toque durante la grabación: termina y transcribe", async () => {
      await p.evaluate(() => { window.__nivelMic = 0.25; });
      await orbe(p);
      await etapa(p, /Te escucho/);
      await dormir(300);
      await orbe(p);
      await etapa(p, /Tocá «Enviar»/);
      afirma(visto.stt.length === 2, "no transcribió: " + visto.stt.length);
    });
    await caso("sin hablar, el turno se descarta solo y vuelve a «listo» con el aviso", async () => {
      await W(p, ".mh-cancelar").click();
      await p.evaluate(() => { window.__nivelMic = 0; });
      await orbe(p);
      await etapa(p, /Te escucho/);
      const antes = visto.stt.length;
      await etapa(p, /Tocá el orbe para hablar/);              // tras TOCAR_ESPERA_MS (7 s)
      afirma(visto.stt.length === antes, "transcribió un silencio");
      afirma((await gum(p)).paradas >= 3, "no cerró el micrófono");
    });
    await p.close();
  }

  // ───────────────────────── sin ningún reconocimiento no hay modo voz ─────────────────────────
  {
    const { p } = await abrir({ dictado: false, reco: false });
    await caso("sin Web Speech ni STT del servidor no aparece el botón Voz", async () => {
      afirma(await W(p, "button.manos").isHidden(), "el botón Voz aparece sin motor de dictado");
    });
    await p.close();
  }

  const falla = resultados.filter((r) => !r.ok).length;
  return { resultados, resumen: `${resultados.length - falla}/${resultados.length} ok` };
}
