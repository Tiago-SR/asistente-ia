// E2E del modo voz (antes «manos libres») del widget: máquina de estados y cableado. La vista de voz, el resumen hablado y el
// paso al chat se prueban en modo-voz.e2e.js. Sin LLM, sin whisper y sin micrófono real: SpeechRecognition y
// speechSynthesis se simulan con un guion que el test controla (window.__decir / __terminar / __error) y la
// respuesta del chat se fabrica con page.route. Comprueba la máquina de estados y el cableado (no la calidad
// del reconocimiento: eso se prueba a mano en Chrome real). Se ejecuta como widget.e2e.js (ver README.md).
async (page) => {
  const BASE = "http://localhost:8203";
  const SHOTS = ".playwright-mcp/e2e";
  const resultados = [];
  const caso = async (nombre, fn) => {
    try { await fn(); resultados.push({ nombre, ok: true }); }
    catch (e) { resultados.push({ nombre, ok: false, detalle: String(e.message).split("\n")[0].slice(0, 300) }); }
  };
  const afirma = (c, m) => { if (!c) throw new Error(m); };

  const abrir = async ({ sinReco = false, lento = false } = {}) => {
    const p = await page.context().newPage();
    await p.setViewportSize({ width: 1280, height: 800 });
    await p.route("**/v1/chat", (route) => route.fulfill({
      status: 200,
      headers: { "content-type": "text/event-stream", "access-control-allow-origin": "http://localhost:8203" },
      body: `event: delta\ndata: ${JSON.stringify({ texto: "Tenés **870,5** hectáreas de soja. " })}\n\n`
        + `event: delta\ndata: ${JSON.stringify({ texto: "Querés compararlas con la zafra anterior?" })}\n\n`
        + `event: done\ndata: ${JSON.stringify({ conversacion_id: "00000000-0000-0000-0000-000000000000" })}\n\n`,
    }));
    await p.addInitScript(({ sinReco, lento }) => {
      window.__mh = { inicios: 0, abortos: 0, actual: null, continuo: null };
      if (sinReco) {
        window.SpeechRecognition = window.webkitSpeechRecognition = undefined;   // Chromium trae uno propio
      } else {
        window.SpeechRecognition = window.webkitSpeechRecognition = class {
          constructor() { this.results = []; window.__mh.actual = this; }
          start() { window.__mh.inicios++; window.__mh.continuo = this.continuous; setTimeout(() => this.onstart && this.onstart(), 0); }
          stop() {}
          abort() { window.__mh.abortos++; }
        };
      }
      // emite un resultado como lo hace Chrome en modo continuo: la lista crece; un parcial se reemplaza por su final
      window.__decir = (texto, final = true) => {
        const r = window.__mh.actual, ultimo = r.results[r.results.length - 1];
        const res = Object.assign([{ transcript: texto, confidence: 0.9 }], { isFinal: final });
        if (ultimo && !ultimo.isFinal) r.results[r.results.length - 1] = res; else r.results.push(res);
        r.onresult({ resultIndex: r.results.length - 1, results: r.results });
      };
      window.__terminar = () => { const r = window.__mh.actual; r.onend && r.onend(); };
      window.__error = (codigo) => { const r = window.__mh.actual; r.onerror && r.onerror({ error: codigo }); r.onend && r.onend(); };
      window.__voz = { dichas: [], cancelaciones: 0 };
      window.SpeechSynthesisUtterance = class { constructor(t) { this.text = t; } };
      Object.defineProperty(window, "speechSynthesis", { configurable: true, value: {
        pendientes: [],
        getVoices: () => [{ name: "Española", lang: "es-ES" }],
        speak(u) {
          window.__voz.dichas.push(u.text);
          this.pendientes.push(u);
          setTimeout(() => { if (!u.__cancelada) { this.pendientes = this.pendientes.filter((x) => x !== u); u.onend && u.onend(); } }, lento ? 4000 : 20);
        },
        cancel() {
          window.__voz.cancelaciones++;
          for (const u of this.pendientes) { u.__cancelada = true; setTimeout(() => u.onerror && u.onerror({ error: "canceled" }), 0); }
          this.pendientes = [];
        },
      } });
    }, { sinReco, lento });
    await p.goto(`${BASE}/?usuario=ana`);
    await p.locator("asistente-chat .barra").waitFor();
    return p;
  };
  const W = (p, sel) => p.locator(`asistente-chat ${sel}`);
  const etiqueta = async (p) => (await W(p, ".mh-estado").innerText()).trim();
  const esperarEtiqueta = (p, re, ms = 4000) => p.waitForFunction(
    (src) => new RegExp(src, "i").test(document.querySelector("asistente-chat").shadowRoot.querySelector(".mh-estado").textContent),
    re.source, { timeout: ms });
  const esperarFin = (p) => p.waitForFunction(() => document.querySelector("asistente-chat").shadowRoot.querySelector("[aria-busy]")?.getAttribute("aria-busy") === "false", null, { timeout: 15000 });
  const decir = (p, t, final = true) => p.evaluate(([t, f]) => window.__decir(t, f), [t, final]);
  const campo = (p) => W(p, "textarea").inputValue();
  const activar = async (p) => { await W(p, "button.manos").click(); await esperarEtiqueta(p, /para hablar/); };
  // «asistente <frase>» y espera a que la frase quede en el campo
  const dictar = async (p, frase) => { await decir(p, "asistente " + frase); await p.waitForFunction((f) => document.querySelector("asistente-chat").shadowRoot.querySelector("textarea").value === f, frase, { timeout: 3000 }); };

  // ── disponibilidad ──
  const sin = await abrir({ sinReco: true });
  await caso("sin reconocimiento de voz del navegador no aparece el botón «Voz»", async () => {
    await sin.waitForTimeout(800);
    afirma(!(await W(sin, "button.manos").isVisible()), "el botón es visible sin SpeechRecognition");
  });
  await sin.close();

  const p = await abrir();
  await caso("el botón «Voz» aparece y no hay indicador de micrófono hasta activarlo", async () => {
    await W(p, "button.manos").waitFor({ state: "visible", timeout: 10000 });
    afirma(!(await W(p, ".mh").isVisible()), "indicador visible con el modo apagado");
  });

  // ── activar: armado ──
  await caso("activar: queda armado con indicador, aviso de privacidad y botón de apagar; reconocimiento continuo", async () => {
    await activar(p);
    afirma(await W(p, ".mh").isVisible() && await W(p, ".mh-apagar").isVisible(), "falta el indicador o el botón de apagar");
    afirma(/Google/.test(await W(p, ".mh-priv").innerText()), "falta el aviso de privacidad");
    afirma((await W(p, "button.manos").getAttribute("aria-pressed")) === "true", "aria-pressed");
    afirma(await W(p, "button.mic").isDisabled(), "el micrófono del dictado manual no se deshabilitó (competirían por el micrófono)");
    const mh = await p.evaluate(() => window.__mh);
    afirma(mh.inicios === 1 && mh.continuo === true, `inicios=${mh.inicios} continuo=${mh.continuo}`);
    await p.screenshot({ path: `${SHOTS}/40-manos-libres-armado.png` });
  });
  await caso("armado: el ruido sin la palabra de activación y los comandos sueltos no hacen nada", async () => {
    await decir(p, "qué lindo día hace hoy");
    await decir(p, "enviar");
    await decir(p, "dime lo que pasa con el asistente de ayer");   // la palabra no está al comienzo
    await p.waitForTimeout(300);
    afirma((await campo(p)) === "" && /para hablar/.test(await etiqueta(p)), "reaccionó al ruido: " + await etiqueta(p));
    afirma(await W(p, ".msg").count() === 0, "se envió algo");
  });

  // ── capturar y confirmar ──
  await caso("la palabra de activación (ya con el parcial) pasa a capturar y la frase queda en el campo sin enviarse", async () => {
    await decir(p, "asistente", false);
    await esperarEtiqueta(p, /Te escucho/);
    await decir(p, "asistente cuántas hectáreas", false);
    await p.waitForFunction(() => document.querySelector("asistente-chat").shadowRoot.querySelector(".mh-parcial").textContent.includes("cuántas hectáreas"), null, { timeout: 2000 });
    afirma(!(await W(p, ".mh-parcial").innerText()).includes("asistente"), "el parcial incluye la palabra de activación");
    await decir(p, "asistente cuántas hectáreas de soja tengo", true);
    afirma((await campo(p)) === "cuántas hectáreas de soja tengo", "campo: «" + await campo(p) + "»");
    afirma(await W(p, ".msg").count() === 0, "se envió sin confirmar");
  });
  await caso("tras un silencio pide confirmación y sigue sin enviar", async () => {
    await esperarEtiqueta(p, /enviar.*cancelar/, 4000);
    afirma(await W(p, ".mh-enviar").isVisible() && await W(p, ".mh-cancelar").isVisible(), "faltan los botones");
    await p.waitForTimeout(1500);
    afirma(await W(p, ".msg").count() === 0, "se envió solo");
    await p.screenshot({ path: `${SHOTS}/41-manos-libres-confirmando.png` });
  });
  await caso("en confirmación, seguir hablando añade al texto (vuelve a capturar)", async () => {
    await decir(p, "y de maíz");
    afirma((await campo(p)) === "cuántas hectáreas de soja tengo y de maíz", "campo: «" + await campo(p) + "»");
    await esperarEtiqueta(p, /enviar.*cancelar/, 4000);
  });
  await caso("«cancelar» descarta el texto y vuelve a armado", async () => {
    await decir(p, "cancelar");
    await esperarEtiqueta(p, /para hablar/);
    afirma((await campo(p)) === "", "el campo no se vació");
    afirma(await W(p, ".msg").count() === 0, "se envió al cancelar");
  });
  await caso("«enviar» dentro de una frase no envía: es texto", async () => {
    await dictar(p, "quiero enviar un informe");
    await decir(p, "quiero enviar un informe más largo");
    afirma((await campo(p)).includes("enviar un informe") && await W(p, ".msg").count() === 0, "envió o perdió el texto");
    await W(p, ".mh-cancelar").click();
    await esperarEtiqueta(p, /para hablar/);
  });

  // ── enviar → respondiendo → leer → armado ──
  await caso("«enviar» envía; la respuesta se lee en voz alta (aunque el altavoz esté apagado) y vuelve a armado", async () => {
    afirma((await W(p, "button.altavoz").getAttribute("aria-pressed")) === "false", "el altavoz ya estaba activado");
    await dictar(p, "cuántas hectáreas de soja tengo");
    await esperarEtiqueta(p, /enviar.*cancelar/);
    await decir(p, "Enviar.");
    await esperarFin(p);
    await W(p, "button.ver-chat").click();                   // la vista de voz no muestra el chat: se alterna para verlo
    await W(p, ".msg.assistant").waitFor();
    afirma(/870,5/.test(await W(p, ".msg.assistant").last().innerText()), "no llegó la respuesta");
    const dichas = await p.evaluate(() => window.__voz.dichas);
    afirma(dichas.length >= 1 && /870,5/.test(dichas.join(" ")), "no leyó la respuesta: " + JSON.stringify(dichas));
    await esperarEtiqueta(p, /para hablar/);
    afirma((await W(p, ".msg.user").last().innerText()).trim() === "cuántas hectáreas de soja tengo", "texto enviado distinto");
    afirma((await campo(p)) === "", "el campo no se vació");
  });
  await caso("el botón «Enviar» del indicador también confirma", async () => {
    await dictar(p, "y de maíz");
    await esperarEtiqueta(p, /enviar.*cancelar/);
    await W(p, ".mh-enviar").click();
    await esperarFin(p);
    afirma(await W(p, ".msg.user").count() === 2, "no se envió");
    await esperarEtiqueta(p, /para hablar/);
  });

  // ── reinicio del reconocimiento ──
  await caso("si el navegador corta el reconocimiento (silencio o ~60 s) se reinicia solo y sigue armado", async () => {
    const antes = await p.evaluate(() => window.__mh.inicios);
    await p.evaluate(() => window.__terminar());
    await p.waitForFunction((n) => window.__mh.inicios === n + 1, antes, { timeout: 3000 });
    afirma(/para hablar/.test(await etiqueta(p)), "ya no está armado: " + await etiqueta(p));
    await dictar(p, "sigue funcionando tras el reinicio");     // los índices de resultados empiezan de cero en la sesión nueva
    await W(p, ".mh-cancelar").click();
    await esperarEtiqueta(p, /para hablar/);
  });
  await caso("«no-speech» (silencio) es el ciclo normal: reinicia sin avisar", async () => {
    const antes = await p.evaluate(() => window.__mh.inicios);
    await p.evaluate(() => window.__error("no-speech"));
    await p.waitForFunction((n) => window.__mh.inicios === n + 1, antes, { timeout: 3000 });
    afirma(!(await W(p, ".aviso-voz.err").count()), "mostró un error por silencio");
  });

  // ── apagar ──
  await caso("el botón «Apagar» apaga: sin indicador, reconocimiento abortado y el micrófono manual vuelve", async () => {
    const abortos = await p.evaluate(() => window.__mh.abortos);
    await W(p, ".mh-apagar").click();
    afirma(!(await W(p, ".mh").isVisible()), "el indicador sigue visible");
    afirma((await p.evaluate(() => window.__mh.abortos)) === abortos + 1, "no abortó el reconocimiento");
    afirma(!(await W(p, "button.mic").isDisabled()), "el micrófono manual sigue deshabilitado");
    afirma((await W(p, "button.manos").getAttribute("aria-pressed")) === "false", "aria-pressed");
  });
  await caso("apagado, el widget ignora la palabra de activación", async () => {
    const mh0 = await p.evaluate(() => window.__mh.inicios);
    await p.waitForTimeout(500);
    afirma((await p.evaluate(() => window.__mh.inicios)) === mh0, "reinició el reconocimiento apagado");
    afirma((await campo(p)) === "", "escribió en el campo");
  });
  await caso("la tecla Esc apaga (con el foco en el widget)", async () => {
    await activar(p);
    await W(p, "button.ver-chat").focus();                   // en la vista de voz no hay campo: el foco está en «Ver el chat»
    await p.keyboard.press("Escape");
    afirma(!(await W(p, ".mh").isVisible()), "Esc no apagó el modo");
  });
  await caso("«apagar manos libres» por voz apaga", async () => {
    await activar(p);
    await decir(p, "apagar manos libres");
    afirma(!(await W(p, ".mh").isVisible()), "la orden de voz no apagó el modo");
  });
  await caso("permiso de micrófono denegado: se apaga con un aviso claro", async () => {
    await activar(p);
    await p.evaluate(() => window.__error("not-allowed"));
    afirma(!(await W(p, ".mh").isVisible()), "sigue activo");
    afirma(/micrófono/i.test(await W(p, ".aviso-voz.err").innerText()), "aviso: " + await W(p, ".aviso-voz").innerText());
  });
  await caso("errores de red repetidos: reintenta con espera y termina apagando con aviso", async () => {
    await activar(p);
    for (let i = 0; i < 5; i++) {
      await p.waitForFunction(() => window.__mh.actual && true);
      await p.evaluate(() => window.__error("network"));
      if (i < 4) await p.waitForFunction((n) => window.__mh.inicios > n, await p.evaluate(() => window.__mh.inicios), { timeout: 6000 });
    }
    await p.waitForFunction(() => !document.querySelector("asistente-chat").shadowRoot.querySelector(".mh") || document.querySelector("asistente-chat").shadowRoot.querySelector(".mh").hidden, null, { timeout: 3000 });
    afirma(/navegador/i.test(await W(p, ".aviso-voz.err").innerText()), "aviso: " + await W(p, ".aviso-voz").innerText());
  });
  await p.close();

  // ── interrumpir la lectura con la palabra de activación ──
  const l = await abrir({ lento: true });
  await caso("decir la palabra de activación mientras lee corta la lectura y empieza a capturar", async () => {
    await activar(l);
    await dictar(l, "cuántas hectáreas de soja tengo");
    await esperarEtiqueta(l, /enviar.*cancelar/);
    await decir(l, "enviar");
    await esperarEtiqueta(l, /Respondiendo/);
    await l.waitForFunction(() => window.__voz.dichas.length >= 1, null, { timeout: 5000 });
    const cortes = await l.evaluate(() => window.__voz.cancelaciones);
    await decir(l, "oye asistente");
    await esperarEtiqueta(l, /Te escucho/);
    afirma((await l.evaluate(() => window.__voz.cancelaciones)) > cortes, "no cortó la lectura");
    await esperarFin(l);
    const dichas = await l.evaluate(() => window.__voz.dichas.length);
    await l.waitForTimeout(300);
    afirma((await l.evaluate(() => window.__voz.dichas.length)) === dichas, "siguió leyendo tras la interrupción");
    await l.screenshot({ path: `${SHOTS}/42-manos-libres-interrumpido.png` });
  });
  await l.close();

  // ── apagado por inactividad (atributo manos-libres-inactividad, en minutos) ──
  const i = await abrir();
  await caso("sin interacción se apaga solo (manos-libres-inactividad) y lo avisa", async () => {
    await i.evaluate(() => document.querySelector("asistente-chat").setAttribute("manos-libres-inactividad", "0.03"));
    await activar(i);
    await i.waitForFunction(() => document.querySelector("asistente-chat").shadowRoot.querySelector(".mh").hidden, null, { timeout: 5000 });
    afirma(/inactividad/i.test(await W(i, ".aviso-voz").innerText()), "aviso: " + await W(i, ".aviso-voz").innerText());
    afirma((await i.evaluate(() => window.__mh.abortos)) === 1, "no abortó el reconocimiento");
  });
  await i.close();

  // ── voz-motor="servidor" ──
  const s = await abrir();
  await caso("voz-motor=\"servidor\" oculta el modo (la palabra de activación no existe en el STT del servidor)", async () => {
    await W(s, "button.manos").waitFor({ state: "visible", timeout: 10000 });
    await s.evaluate(() => { const e = document.querySelector("asistente-chat"); e.setAttribute("voz-motor", "servidor"); e._actualizarVoz(); });
    afirma(!(await W(s, "button.manos").isVisible()), "sigue visible con voz-motor=servidor");
  });
  await s.close();

  return { resultados, resumen: `${resultados.filter((x) => x.ok).length}/${resultados.length} ok` };
}
