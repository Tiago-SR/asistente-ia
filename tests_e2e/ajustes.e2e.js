// E2E del panel de ajustes del widget (engranaje): motor de voz, volumen, lectura automática, acuse, «probar voz» y
// «restablecer». Sin LLM: /v1/estado, el chat y /v1/voz/sintetizar se fabrican con page.route; speechSynthesis y la
// reproducción de <audio> se simulan y registran (texto y volumen). Lo real es la página (sistema-php, :8203) y el widget.
// Se ejecuta como los demás (ver README.md).
//
// WIDGET_LOCAL: para probar un widget.js que aún no está en el contenedor, serví con
// `python3 -m http.server 8299 -d src/asistente/static` y poné aquí "http://localhost:8299/widget.js" (null = el del servidor).
async (page) => {
  const WIDGET_LOCAL = null;
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

  // `servidor`: lo que dice /v1/estado en voz.respuesta. `navegador`: si existe speechSynthesis.
  async function nueva({ servidor = false, navegador = true, reco = false, antes } = {}) {
    const p = await ctx.newPage();
    const visto = { sintetizar: 0 };
    await p.addInitScript(({ navegador, reco }) => {
      window.__hablado = []; window.__audios = [];
      // el dictado del navegador decide si hay modo voz (y por tanto acuse): se controla para que el caso no dependa del Chromium
      window.SpeechRecognition = window.webkitSpeechRecognition = reco ? class { start() {} stop() {} abort() {} } : undefined;
      if (navegador) {
        window.SpeechSynthesisUtterance = class { constructor(t) { this.text = t; } };
        Object.defineProperty(window, "speechSynthesis", { configurable: true, value: {
          getVoices: () => [], cancel() {}, onvoiceschanged: null,
          speak(u) { window.__hablado.push({ texto: u.text, volumen: u.volume }); setTimeout(() => u.onstart && u.onstart(), 0); setTimeout(() => u.onend && u.onend(), 20); },
        } });
      } else { try { delete window.speechSynthesis; } catch (e) { /* nada */ } Object.defineProperty(window, "speechSynthesis", { configurable: true, value: undefined }); }
      HTMLMediaElement.prototype.play = function () {
        window.__audios.push({ volumen: this.volume });
        setTimeout(() => { this.dispatchEvent(new Event("playing")); setTimeout(() => this.dispatchEvent(new Event("ended")), 20); }, 0);
        return Promise.resolve();
      };
    }, { navegador, reco });
    if (WIDGET_LOCAL) {
      await p.route("**/widget.js", async (route) => { const r = await route.fetch({ url: WIDGET_LOCAL }); await route.fulfill({ response: r }); });
    }
    await p.route("**/v1/estado", (route) => {
      if (route.request().method() === "OPTIONS") return route.fulfill({ status: 204, headers: CORS });
      return route.fulfill({ status: 200, headers: { "content-type": "application/json", ...CORS }, body: JSON.stringify({
        habilitado: true, nombre_sistema: "Sistema PHP", memoria: false, voz: { dictado: false, respuesta: servidor, max_audio_s: 60 } }) });
    });
    await p.route("**/v1/voz/sintetizar", (route) => {
      if (route.request().method() === "OPTIONS") return route.fulfill({ status: 204, headers: CORS });
      visto.sintetizar++;
      return route.fulfill({ status: 200, headers: { "content-type": "audio/mpeg", ...CORS }, body: Buffer.from("ID3audio") });
    });
    if (antes) await p.addInitScript(antes);
    await p.goto(`${BASE}/?usuario=ana`);
    await p.locator("asistente-chat textarea").waitFor();
    await dormir(300);
    const sel = (css, o) => p.locator("asistente-chat " + css, o);
    const guardado = () => p.evaluate(() => { const k = Object.keys(localStorage).find((x) => x.startsWith("asistente:ajustes:")); return k ? JSON.parse(localStorage.getItem(k)) : null; });
    return { p, visto, sel, guardado };
  }

  // — Engranaje y panel: accesibilidad básica —
  {
    const { p, sel } = await nueva({ servidor: true });
    await caso("el engranaje está en la barra, etiquetado y con el panel cerrado", async () => {
      await sel(".ajustes").waitFor({ state: "visible" });
      afirma((await sel(".ajustes").getAttribute("aria-label")) === "Ajustes" && (await sel(".ajustes").getAttribute("aria-expanded")) === "false", "etiquetas");
      afirma(await sel(".ajustes-panel").isHidden(), "el panel empieza abierto");
    });
    await caso("abrir: el foco va al panel y aria-expanded=true; Escape lo cierra y devuelve el foco al engranaje", async () => {
      await sel(".ajustes").click();
      afirma(await sel(".ajustes-panel").isVisible(), "no se abrió");
      afirma((await sel(".ajustes").getAttribute("aria-expanded")) === "true", "aria-expanded");
      afirma(await p.locator("asistente-chat").evaluate((e) => e.shadowRoot.activeElement?.textContent === "Cerrar"), "el foco no fue al panel");
      await p.keyboard.press("Escape");
      afirma(await sel(".ajustes-panel").isHidden(), "Escape no cerró");
      afirma(await p.locator("asistente-chat").evaluate((e) => e.shadowRoot.activeElement?.classList.contains("ajustes")), "el foco no volvió al engranaje");
    });
    await caso("operable con teclado: el control de volumen se ajusta con las flechas", async () => {
      await sel(".ajustes").click();
      await sel("#aj-vol").focus();
      await p.keyboard.press("ArrowLeft");
      afirma((await sel("#aj-vol").inputValue()) === "95", "valor " + (await sel("#aj-vol").inputValue()));
    });
    await p.close();
  }

  // — ajustes="no": no hay engranaje (mandan los atributos) —
  {
    const { p } = await nueva({ servidor: true });
    await caso('atributo ajustes="no": el widget no muestra el engranaje', async () => {
      const oculto = await p.evaluate(() => {
        const w = document.querySelector("asistente-chat"), n = document.createElement("asistente-chat");
        for (const a of w.attributes) n.setAttribute(a.name, a.value);
        n.setAttribute("ajustes", "no");
        document.body.append(n);
        return n.shadowRoot.querySelector(".ajustes").hidden;
      });
      afirma(oculto === true, "el engranaje sigue visible");
    });
    await p.close();
  }

  // — Solo la voz del navegador: sin selector de motor —
  {
    const { p, sel, guardado } = await nueva({ servidor: false });
    await sel(".ajustes").click();
    await caso("sin voz de servidor: no hay selector de motor, pero sí volumen, lectura automática y probar voz", async () => {
      afirma(await sel("fieldset.aj-fila").isHidden(), "el selector de motor está visible");
      afirma(await sel("#aj-vol").isVisible() && await sel("#aj-leer").isVisible(), "faltan controles");
      afirma(await sel(".aj-acciones button").first().isVisible(), "falta «Probar voz»");
    });
    await caso("el volumen se aplica a la voz del navegador (probar voz) y se guarda en localStorage", async () => {
      await sel("#aj-vol").fill("40");
      afirma((await guardado())?.volumen === 0.4, "no se guardó: " + JSON.stringify(await guardado()));
      await sel(".aj-acciones button", { hasText: "Probar voz" }).click();
      await p.waitForFunction(() => window.__hablado.length === 1);
      const h = await p.evaluate(() => window.__hablado[0]);
      afirma(h.volumen === 0.4 && /Hola/.test(h.texto), JSON.stringify(h));
    });
    await caso("el ajuste sobrevive a recargar la página", async () => {
      await p.reload();
      await p.locator("asistente-chat textarea").waitFor(); await dormir(300);
      await sel(".ajustes").click();
      afirma((await sel("#aj-vol").inputValue()) === "40", "volumen " + (await sel("#aj-vol").inputValue()));
    });
    await caso("«leer en voz alta» del panel y el botón del altavoz de la barra van juntos", async () => {
      afirma(!(await sel("#aj-leer").isChecked()), "empieza marcado");
      await sel("#aj-leer").check();
      afirma((await sel(".altavoz").getAttribute("aria-pressed")) === "true", "el altavoz no se marcó");
      await sel("#aj-leer").uncheck();
      afirma((await sel(".altavoz").getAttribute("aria-pressed")) === "false", "el altavoz no se desmarcó");
    });
    await caso("sin modo voz no se ofrece el acuse", async () => {
      afirma(await sel("#aj-acuse").isHidden(), "el acuse está visible sin modo voz");
    });
    await caso("«Restablecer» vuelve al volumen por defecto y borra lo guardado", async () => {
      await sel(".aj-acciones button", { hasText: "Restablecer" }).click();
      afirma((await sel("#aj-vol").inputValue()) === "100", "volumen " + (await sel("#aj-vol").inputValue()));
      afirma((await guardado()) === null, "quedó guardado: " + JSON.stringify(await guardado()));
    });
    await p.close();
  }

  // — Voz del navegador y del servidor: el selector manda y el volumen llega al <audio> —
  {
    const { p, visto, sel, guardado } = await nueva({ servidor: true });
    await sel(".ajustes").click();
    await caso("con las dos voces: hay selector y por defecto está la del servidor", async () => {
      afirma(await sel("fieldset.aj-fila").isVisible(), "no se ve el selector");
      afirma(await sel("input[value=servidor]").isChecked(), "el servidor no es el actual");
    });
    await caso("probar voz con el servidor: pide el audio, lo reproduce al volumen elegido y no usa la voz del navegador", async () => {
      await sel("#aj-vol").fill("30");
      await sel(".aj-acciones button", { hasText: "Probar voz" }).click();
      await p.waitForFunction(() => window.__audios.length === 1);
      afirma(visto.sintetizar === 1, "pidió audio " + visto.sintetizar + " veces");
      afirma(Math.abs((await p.evaluate(() => window.__audios[0].volumen)) - 0.3) < 1e-6, "volumen del audio");
      afirma((await p.evaluate(() => window.__hablado.length)) === 0, "habló el navegador");
    });
    await caso("elegir la voz del navegador: se guarda, no se pide más audio al servidor y habla con el volumen", async () => {
      await sel("input[value=navegador]").check();
      afirma((await guardado())?.motor === "navegador", JSON.stringify(await guardado()));
      await sel(".aj-acciones button", { hasText: "Probar voz" }).click();
      await p.waitForFunction(() => window.__hablado.length === 1);
      afirma(visto.sintetizar === 1, "volvió a pedir audio al servidor");
      afirma((await p.evaluate(() => window.__hablado[0].volumen)) === 0.3, "volumen del navegador");
    });
    await caso("volver a la voz del servidor y recargar conserva la elección del usuario", async () => {
      await p.reload();
      await p.locator("asistente-chat textarea").waitFor(); await dormir(300);
      await sel(".ajustes").click();
      afirma(await sel("input[value=navegador]").isChecked(), "no recordó el navegador");
    });
    await p.close();
  }

  // — Con modo voz disponible: el acuse se puede apagar —
  {
    const { p, sel, guardado } = await nueva({ servidor: false, reco: true });
    await sel(".ajustes").click();
    await caso("con modo voz: se ofrece el acuse, activo por defecto, y apagarlo se guarda", async () => {
      afirma(await sel("#aj-acuse").isVisible() && await sel("#aj-acuse").isChecked(), "no se ofrece o no está activo");
      await sel("#aj-acuse").uncheck();
      afirma((await guardado())?.acuse === false, JSON.stringify(await guardado()));
    });
    await p.close();
  }

  // — Guardado corrupto o inválido: valores por defecto, sin romper —
  {
    const { p, sel } = await nueva({ servidor: true, antes: () => {
      try { localStorage.setItem("asistente:ajustes:" + location.origin.replace("8203", "8100"), "{no es json"); localStorage.setItem("asistente:ajustes:http://localhost:8100", JSON.stringify({ motor: "otro", volumen: 7, acuse: "sí" })); } catch (e) { /* nada */ }
    } });
    await caso("un guardado inválido se ignora: volumen 100 % y el widget funciona", async () => {
      await sel(".ajustes").click();
      afirma((await sel("#aj-vol").inputValue()) === "100", "volumen " + (await sel("#aj-vol").inputValue()));
    });
    await p.close();
  }

  const ok = resultados.filter((r) => r.ok).length;
  return { resultados, resumen: `${ok}/${resultados.length} ok` };
}
