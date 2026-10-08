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
  async function nueva({ nombreAsistente = null, servidor = false, navegador = true, reco = false, antes, voces = null } = {}) {
    const p = await ctx.newPage();
    const visto = { sintetizar: 0, cuerpos: [] };
    await p.addInitScript(({ navegador, reco }) => {
      window.__hablado = []; window.__audios = [];
      // el dictado del navegador decide si hay modo voz (y por tanto acuse): se controla para que el caso no dependa del Chromium
      window.SpeechRecognition = window.webkitSpeechRecognition = reco ? class { start() {} stop() {} abort() {} } : undefined;
      if (navegador) {
        window.SpeechSynthesisUtterance = class { constructor(t) { this.text = t; } };
        Object.defineProperty(window, "speechSynthesis", { configurable: true, value: {
          getVoices: () => [], cancel() {}, onvoiceschanged: null,
          speak(u) { window.__hablado.push({ texto: u.text, volumen: u.volume, velocidad: u.rate }); setTimeout(() => u.onstart && u.onstart(), 0); setTimeout(() => u.onend && u.onend(), 20); },
        } });
      } else { try { delete window.speechSynthesis; } catch (e) { /* nada */ } Object.defineProperty(window, "speechSynthesis", { configurable: true, value: undefined }); }
      HTMLMediaElement.prototype.play = function () {
        window.__audios.push({ volumen: this.volume, velocidad: this.playbackRate });
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
        habilitado: true, nombre_sistema: "Sistema PHP", nombre_asistente: nombreAsistente, memoria: false, voz: { dictado: false, respuesta: servidor, max_audio_s: 60, ...(voces ? { voces: voces.lista, voz_defecto: voces.defecto } : {}) } }) });
    });
    await p.route("**/v1/voz/sintetizar", (route) => {
      if (route.request().method() === "OPTIONS") return route.fulfill({ status: 204, headers: CORS });
      visto.sintetizar++;
      try { visto.cuerpos.push(JSON.parse(route.request().postData() || "{}")); } catch { visto.cuerpos.push(null); }
      return route.fulfill({ status: 200, headers: { "content-type": "audio/mpeg", ...CORS }, body: Buffer.from("ID3audio") });
    });
    if (antes) await p.addInitScript(antes);
    await p.goto(`${BASE}/?usuario=ana`);
    await p.locator("asistente-chat .barra").waitFor();
    await dormir(300);
    const sel = (css, o) => p.locator("asistente-chat " + css, o);
    const guardado = () => p.evaluate(() => { const k = Object.keys(localStorage).find((x) => x.startsWith("asistente:ajustes:")); return k ? JSON.parse(localStorage.getItem(k)) : null; });
    return { p, visto, sel, guardado };
  }

  // Los bloques comparten origen, y por tanto localStorage: se parte de cero (y se recarga para que el widget lo lea).
  async function limpiarGuardado(p) {
    await p.evaluate(() => { for (const k of Object.keys(localStorage)) if (k.startsWith("asistente:ajustes:")) localStorage.removeItem(k); });
    await p.reload(); await p.locator("asistente-chat .barra").waitFor(); await dormir(300);
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
      afirma(await sel("fieldset.aj-fila:has(input[value=navegador])").isHidden(), "el selector de motor está visible");
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
    await caso("la velocidad se aplica a la voz del navegador (rate) y se guarda", async () => {
      await sel("#aj-vel").fill("150");
      afirma((await guardado())?.velocidad === 1.5, "no se guardó: " + JSON.stringify(await guardado()));
      await sel(".aj-acciones button", { hasText: "Probar voz" }).click();
      await p.waitForFunction(() => window.__hablado.length === 2);
      afirma((await p.evaluate(() => window.__hablado[1].velocidad)) === 1.5, "rate " + await p.evaluate(() => window.__hablado[1].velocidad));
      await sel("#aj-vel").fill("100");
    });
    await caso("el ajuste sobrevive a recargar la página", async () => {
      await p.reload();
      await p.locator("asistente-chat .barra").waitFor(); await dormir(300);
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
      afirma((await sel("#aj-vel").inputValue()) === "100", "velocidad " + (await sel("#aj-vel").inputValue()));
      afirma((await guardado()) === null, "quedó guardado: " + JSON.stringify(await guardado()));
    });
    await p.close();
  }

  // — Voz del navegador y del servidor: el selector manda y el volumen llega al <audio> —
  {
    const { p, visto, sel, guardado } = await nueva({ servidor: true });
    await sel(".ajustes").click();
    await caso("con las dos voces: hay selector y por defecto está la del servidor", async () => {
      afirma(await sel("fieldset.aj-fila:has(input[value=navegador])").isVisible(), "no se ve el selector");
      afirma(await sel("input[value=servidor]").isChecked(), "el servidor no es el actual");
    });
    await caso("probar voz con el servidor: pide el audio, lo reproduce al volumen elegido y no usa la voz del navegador", async () => {
      await sel("#aj-vol").fill("30");
      await sel("#aj-vel").fill("125");
      await sel(".aj-acciones button", { hasText: "Probar voz" }).click();
      await p.waitForFunction(() => window.__audios.length === 1);
      afirma((await p.evaluate(() => window.__audios[0].velocidad)) === 1.25, "velocidad del audio");
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
      await p.locator("asistente-chat .barra").waitFor(); await dormir(300);
      await sel(".ajustes").click();
      afirma(await sel("input[value=navegador]").isChecked(), "no recordó el navegador");
    });
    await p.close();
  }

  // — Varias voces del servidor: tipo (femenina/masculina) y voz dentro del tipo —
  {
    const lista = [
      { id: "m1", etiqueta: "Mateo", genero: "masculina" }, { id: "m2", etiqueta: "Bruno", genero: "masculina" },
      { id: "f1", etiqueta: "Lucía", genero: "femenina" }, { id: "f2", etiqueta: "Carla", genero: "femenina" },
    ];
    const { p, visto, sel, guardado } = await nueva({ servidor: true, voces: { lista, defecto: "m1" } });
    await limpiarGuardado(p);
    await sel(".ajustes").click();
    const opciones = () => sel("#aj-voz option").allTextContents();
    await caso("con varias voces: aparece el tipo (el de la predeterminada) y solo las voces de ese tipo", async () => {
      afirma(await sel("#aj-voz").isVisible(), "no se ve la lista de voces");
      afirma(await sel("input[value=masculina]").isChecked(), "no marca masculina");
      afirma(JSON.stringify(await opciones()) === JSON.stringify(["Mateo", "Bruno"]), JSON.stringify(await opciones()));
    });
    await caso("la voz elegida viaja en la petición y se guarda; sin elegir no se envía", async () => {
      await sel(".aj-acciones button", { hasText: "Probar voz" }).click();
      await p.waitForFunction(() => window.__audios.length === 1);
      afirma(visto.cuerpos[0].voz === undefined, "envió voz sin que la eligieran: " + JSON.stringify(visto.cuerpos[0]));
      await sel("#aj-voz").selectOption("m2");
      afirma((await guardado())?.voz === "m2", JSON.stringify(await guardado()));
      await sel(".aj-acciones button", { hasText: "Probar voz" }).click();
      await p.waitForFunction(() => window.__audios.length === 2);
      afirma(visto.cuerpos[1].voz === "m2", JSON.stringify(visto.cuerpos[1]));
    });
    await caso("la frase de prueba no se reutiliza de otra voz (el caché es por voz)", async () => {
      await sel("#aj-voz").selectOption("m1");
      await sel(".aj-acciones button", { hasText: "Probar voz" }).click();
      await p.waitForFunction(() => window.__audios.length === 3);
      afirma(visto.cuerpos.length === 3 && visto.cuerpos[2].voz === "m1", "no volvió a pedir con la otra voz: " + JSON.stringify(visto.cuerpos));
    });
    await caso("cambiar el tipo elige una voz de ese tipo y la lista pasa a mostrar solo esas", async () => {
      await sel("input[value=femenina]").check();
      afirma(JSON.stringify(await opciones()) === JSON.stringify(["Lucía", "Carla"]), JSON.stringify(await opciones()));
      afirma((await guardado())?.voz === "f1", JSON.stringify(await guardado()));
      await sel("#aj-voz").selectOption("f2");
      afirma((await guardado())?.voz === "f2", "no guardó f2");
    });
    await caso("la elección sobrevive a recargar", async () => {
      await p.reload();
      await p.locator("asistente-chat .barra").waitFor(); await dormir(300);
      await sel(".ajustes").click();
      afirma(await sel("input[value=femenina]").isChecked() && (await sel("#aj-voz").inputValue()) === "f2", "no recordó la voz");
    });
    await caso("una voz guardada que el servidor ya no ofrece cae a la predeterminada", async () => {
      await p.evaluate(() => { const k = Object.keys(localStorage).find((x) => x.startsWith("asistente:ajustes:")); localStorage.setItem(k, JSON.stringify({ voz: "retirada" })); });
      await p.reload();
      await p.locator("asistente-chat .barra").waitFor(); await dormir(300);
      await sel(".ajustes").click();
      afirma((await sel("#aj-voz").inputValue()) === "m1", "valor " + (await sel("#aj-voz").inputValue()));
    });
    await caso("«Restablecer» vuelve a la voz predeterminada", async () => {
      await sel("#aj-voz").selectOption("m2");
      await sel(".aj-acciones button", { hasText: "Restablecer" }).click();
      afirma((await sel("#aj-voz").inputValue()) === "m1" && (await guardado()) === null, "no restableció");
    });
    await caso("con la voz del navegador no se ofrecen las del servidor", async () => {
      await sel("input[value=navegador]").check();
      afirma(await sel("#aj-voz").isHidden(), "se ve la lista de voces del servidor");
    });
    await p.close();
  }
  {
    const una = await nueva({ servidor: true, voces: { lista: [{ id: "m1", etiqueta: "Mateo", genero: "masculina" }], defecto: "m1" } });
    await limpiarGuardado(una.p);
    await una.sel(".ajustes").click();
    await caso("con una sola voz no hay selector", async () => {
      afirma(await una.sel("#aj-voz").isHidden() && await una.sel("input[value=masculina]").count() === 0, "se ofrece elegir con una sola voz");
    });
    await una.p.close();
    const mismo = await nueva({ servidor: true, voces: { lista: [{ id: "a", etiqueta: "Ana", genero: "femenina" }, { id: "b", etiqueta: "Bea", genero: "femenina" }], defecto: "a" } });
    await limpiarGuardado(mismo.p);
    await mismo.sel(".ajustes").click();
    await caso("con voces de un solo tipo: lista sin selector de tipo", async () => {
      afirma(await mismo.sel("#aj-voz").isVisible() && await mismo.sel("input[value=femenina]").isHidden(), "tipo visible");
      afirma((await mismo.sel("#aj-voz option").count()) === 2, "opciones");
    });
    await mismo.p.close();
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

  // — Nombre del asistente: el del sistema (yaml) es el valor por defecto y el usuario lo cambia en sus ajustes —
  {
    const { p, sel, guardado } = await nueva({ servidor: true, nombreAsistente: "Sofía" });
    const titulo = () => sel("h1").textContent();
    await caso("el nombre del sistema (nombre_asistente) es el título por defecto", async () => {
      afirma((await titulo()) === "Sofía · Sistema PHP", await titulo());
    });
    await caso("el usuario lo cambia en ajustes: se ve ya en el título y la voz, y se guarda", async () => {
      await sel(".ajustes").click();
      afirma((await sel("#aj-nombre").getAttribute("placeholder")) === "Sofía", "placeholder");
      await sel("#aj-nombre").fill("  Don Pepe ");
      afirma((await titulo()) === "Don Pepe · Sistema PHP", await titulo());
      afirma((await sel("fieldset.aj-fila:has(input[value=navegador]) legend").textContent()) === "Voz de Don Pepe", "leyenda");
      afirma((await guardado())?.nombre === "Don Pepe", JSON.stringify(await guardado()));
    });
    await caso("el nombre es la palabra que despierta el modo voz (y vaciarlo vuelve a la del sistema)", async () => {
      const palabra = () => p.locator("asistente-chat").evaluate((e) => e._palabra());
      afirma((await palabra()) === "Don Pepe", await palabra());
      await sel("#aj-nombre").fill("");
      afirma((await palabra()) === "Sofía", await palabra());
      await sel("#aj-nombre").fill("Don Pepe");
    });
    await caso("sobrevive a recargar y «restablecer» vuelve al del sistema", async () => {
      await p.reload();
      await p.locator("asistente-chat .barra").waitFor(); await dormir(300);
      afirma((await titulo()) === "Don Pepe · Sistema PHP", await titulo());
      await sel(".ajustes").click();
      afirma((await sel("#aj-nombre").inputValue()) === "Don Pepe", "el campo no recuerda el nombre");
      await sel(".aj-acciones button", { hasText: "Restablecer" }).click();
      afirma((await titulo()) === "Sofía · Sistema PHP", await titulo());
      afirma((await guardado()) === null, "quedó algo guardado");
    });
    await caso("vaciar el campo vuelve al nombre por defecto", async () => {
      await sel("#aj-nombre").fill("Ana");
      await sel("#aj-nombre").fill("");
      afirma((await titulo()) === "Sofía · Sistema PHP", await titulo());
    });
    await p.close();
  }

  // — Sin nombre en el yaml: «Asistente» —
  {
    const { p, sel } = await nueva({ servidor: false });
    await caso("sin nombre_asistente el título sigue siendo «Asistente · sistema»", async () => {
      afirma((await sel("h1").textContent()) === "Asistente · Sistema PHP", await sel("h1").textContent());
    });
    await p.close();
  }

  const ok = resultados.filter((r) => r.ok).length;
  return { resultados, resumen: `${ok}/${resultados.length} ok` };
}
