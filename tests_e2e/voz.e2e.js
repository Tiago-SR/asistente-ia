// E2E del dictado (voz). Requiere el servicio whisper (`--profile voz`) y el modelo Kokoro de speaches
// para generar tests_e2e/voz.wav (ver README.md). El micrófono se simula: getUserMedia devuelve el
// audio del wav (o silencio) a través de un MediaStreamDestination, y MediaRecorder graba de verdad.
async (page) => {
  const BASE = "http://localhost:8203";
  const SHOTS = ".playwright-mcp/e2e";
  // El sandbox del MCP no tiene fs: el wav se sirve con `python3 -m http.server 8299 -d tests_e2e` (ver README.md).
  const WAV_URL = "http://localhost:8299/voz.wav";
  const resultados = [];
  const caso = async (nombre, fn) => {
    try { await fn(); resultados.push({ nombre, ok: true }); }
    catch (e) { resultados.push({ nombre, ok: false, detalle: String(e.message).split("\n")[0].slice(0, 300) }); }
  };
  const afirma = (c, m) => { if (!c) throw new Error(m); };

  const abrir = async (modo) => {
    const p = await page.context().newPage();
    await p.setViewportSize({ width: 1280, height: 800 });
    await p.route("**/__voz.wav", async (r) => r.fulfill({ response: await r.fetch({ url: WAV_URL }) }));
    await p.addInitScript((modo) => {
      navigator.mediaDevices.getUserMedia = async () => {
        const ac = new AudioContext();
        const dest = ac.createMediaStreamDestination();
        if (modo === "voz") {
          const buf = await ac.decodeAudioData(await (await fetch("/__voz.wav")).arrayBuffer());
          const src = ac.createBufferSource(); src.buffer = buf; src.connect(dest); src.start();
          window.__duracion = buf.duration;
        } else {
          const o = ac.createOscillator(); const g = ac.createGain(); g.gain.value = 0;
          o.connect(g); g.connect(dest); o.start();
        }
        return dest.stream;
      };
    }, modo);
    await p.goto(`${BASE}/?usuario=ana`);
    await p.locator("asistente-chat textarea").waitFor();
    return p;
  };
  const mic = (p) => p.locator("asistente-chat button.mic");
  const aviso = (p) => p.locator("asistente-chat .aviso-voz");
  const ocupado = (p) => p.waitForFunction(() => { const r = document.querySelector("asistente-chat").shadowRoot; return !r.querySelector("button.mic").disabled && !r.querySelector("button.mic.grabando"); }, null, { timeout: 60000 });

  // ── voz real (sintetizada) ──
  const p = await abrir("voz");
  await caso("el botón de micrófono aparece (estado: voz.dictado habilitado)", async () => {
    await mic(p).waitFor({ state: "visible", timeout: 10000 });
  });
  await caso("dictar: graba, transcribe y rellena el campo sin enviar", async () => {
    await mic(p).click();
    await p.locator("asistente-chat button.mic.grabando").waitFor();
    await p.screenshot({ path: `${SHOTS}/20-voz-grabando.png` });
    await p.waitForFunction(() => window.__duracion, null, { timeout: 5000 });
    await p.waitForTimeout(Math.ceil((await p.evaluate(() => window.__duracion)) * 1000) + 500);
    await mic(p).click();                       // detener
    await ocupado(p);
    const v = await p.locator("asistente-chat textarea").inputValue();
    afirma(/hect[aá]reas|soja/i.test(v), "transcripción inesperada: «" + v + "»");
    afirma(await p.locator("asistente-chat .msg").count() === 0, "se envió sin confirmar");
    afirma((await aviso(p).innerText()).trim() === "", "aviso de voz visible: " + await aviso(p).innerText());
  });
  await p.screenshot({ path: `${SHOTS}/21-voz-transcrito.png` });
  await caso("el texto dictado se envía y la respuesta trae la cifra de la tool (660,5 de soja)", async () => {
    await p.locator("asistente-chat textarea").press("Enter");
    await p.locator("asistente-chat .msg.assistant").first().waitFor();
    await p.waitForFunction(() => document.querySelector("asistente-chat").shadowRoot.querySelector("[aria-busy]")?.getAttribute("aria-busy") === "false", null, { timeout: 180000 });
    const t = await p.locator("asistente-chat .msg.assistant").last().innerText();
    afirma(/660[.,]5/.test(t), "falta 660,5 en: " + t.slice(0, 300));
  });
  await p.screenshot({ path: `${SHOTS}/22-voz-respuesta.png` });
  await p.close();

  // ── silencio: el servidor responde sin texto y el widget avisa ──
  const s = await abrir("silencio");
  await caso("silencio: no rellena el campo y muestra el aviso de 'sin texto'", async () => {
    await mic(s).waitFor({ state: "visible", timeout: 10000 });
    await mic(s).click();
    await s.locator("asistente-chat button.mic.grabando").waitFor();
    await s.waitForTimeout(2500);
    await mic(s).click();
    await ocupado(s);
    afirma((await s.locator("asistente-chat textarea").inputValue()) === "", "se rellenó con texto");
    afirma((await aviso(s).innerText()).trim().length > 0, "sin aviso");
  });
  await s.screenshot({ path: `${SHOTS}/23-voz-silencio.png` });
  await s.close();

  return { resultados, resumen: `${resultados.filter((r) => r.ok).length}/${resultados.length} ok` };
}
