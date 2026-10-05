// E2E de la tarjeta de confirmación de acciones (Fase 5, contrato sección 8). Sin LLM ni sistema con
// acciones: el chat, el token de escritura y /v1/confirmaciones/* se fabrican con page.route; lo real es
// la página (sistema-php, :8203), el widget y /v1/estado. Se ejecuta como los demás (ver README.md).
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
    "access-control-allow-methods": "GET,POST,OPTIONS",
  };
  const ctx = page.context();

  // Una página nueva con el chat fabricado: cada mensaje enviado propone una acción (`prop(n)`).
  async function nueva({ prop, confirmar, cancelar, token }) {
    const p = await ctx.newPage();
    const visto = { confirmar: [], cancelar: [], token: [] };
    let n = 0;
    await p.route("**/v1/chat", (route) => {
      if (route.request().method() === "OPTIONS") return route.fulfill({ status: 204, headers: CORS });
      const d = prop(++n);
      return route.fulfill({
        status: 200, headers: { "content-type": "text/event-stream", ...CORS },
        body: `event: confirmacion\ndata: ${JSON.stringify(d)}\n\nevent: delta\ndata: ${JSON.stringify({ texto: "Te pedí confirmar la acción." })}\n\nevent: done\ndata: ${JSON.stringify({ conversacion_id: "00000000-0000-0000-0000-000000000000" })}\n\n`,
      });
    });
    await p.route(/\/asistente\/token\?.*confirmacion=/, (route) => {
      visto.token.push({ url: route.request().url(), credenciales: route.request().headers()["cookie"] !== undefined || true });
      return token ? token(route) : route.fulfill({ status: 200, contentType: "application/json", body: JSON.stringify({ token: "tok-escritura", expira: new Date(Date.now() + 60000).toISOString() }) });
    });
    const api = (cola, resp) => (route) => {
      const rq = route.request();
      if (rq.method() === "OPTIONS") return route.fulfill({ status: 204, headers: CORS });
      cola.push({ url: rq.url(), auth: rq.headers()["authorization"] });
      const r = resp ? resp(rq) : { status: 200, json: {} };
      return route.fulfill({ status: r.status, headers: { "content-type": "application/json", ...CORS }, body: JSON.stringify(r.json) });
    };
    await p.route("**/v1/confirmaciones/*/confirmar", api(visto.confirmar, confirmar));
    await p.route("**/v1/confirmaciones/*/cancelar", api(visto.cancelar, cancelar));
    await p.goto(`${BASE}/?usuario=ana`);
    await p.locator("asistente-chat textarea").waitFor();
    await p.evaluate(() => { window.__eventos = []; document.addEventListener("asistente:confirmacion", (e) => window.__eventos.push(e.detail)); });
    const enviar = async (txt = "anotá algo") => {
      await p.locator("asistente-chat textarea").fill(txt);
      await p.locator("asistente-chat textarea").press("Enter");
      await p.waitForFunction(() => document.querySelector("asistente-chat").shadowRoot.querySelector("[aria-busy]")?.getAttribute("aria-busy") === "false");
    };
    return { p, visto, enviar, tarjeta: (i = 0) => p.locator("asistente-chat .msg.confirmacion").nth(i) };
  }
  const prop = (n, extra = {}) => ({
    id: `acc-${n}`, tool: "agregar_nota", huella: "h".repeat(64), expira: new Date(Date.now() + 120000).toISOString(),
    resumen: "Agregar una nota al establecimiento «El Matorral»", lineas: ["Texto: Helada en el potrero"], ...extra,
  });

  // — Aparece con lo que redactó el sistema —
  {
    const { p, enviar, tarjeta } = await nueva({
      prop: (n) => prop(n, { resumen: "Agregar <img src=x onerror=window.__xss=1> nota", lineas: ["Antes: <b>viejo</b>", "Después: nuevo"] }),
    });
    await enviar();
    await caso("la tarjeta muestra el resumen y el detalle del sistema, con los botones y la cuenta regresiva", async () => {
      const t = tarjeta();
      await t.waitFor();
      afirma((await t.locator(".accion-resumen").textContent()).includes("Agregar"), "sin resumen");
      afirma((await t.locator("li").count()) === 2, "líneas de detalle");
      afirma(await t.locator("button.primario").isVisible() && await t.locator("button", { hasText: "Cancelar" }).isVisible(), "botones");
      afirma(/Vence en 1:5|Vence en 2:0/.test(await t.locator(".accion-estado").textContent()), "sin cuenta regresiva: " + await t.locator(".accion-estado").textContent());
    });
    await caso("el texto de la propuesta es texto: no se interpreta HTML", async () => {
      afirma(await tarjeta().locator("img, b").count() === 0, "se creó HTML a partir del resumen");
      afirma(await p.evaluate(() => window.__xss === undefined), "se ejecutó código del resumen");
      afirma((await tarjeta().locator(".accion-resumen").textContent()).includes("<img"), "el resumen no se muestra literal");
    });
    await caso("no se enfoca ningún botón de la tarjeta (Enter no debe confirmar por accidente)", async () => {
      const f = await p.locator("asistente-chat").evaluate((e) => e.shadowRoot.activeElement?.closest?.(".confirmacion") ? "tarjeta" : "otro");
      afirma(f === "otro", "el foco quedó en la tarjeta");
    });
    await p.close();
  }

  // — Confirmar: token del sistema + POST con ese token —
  {
    const { p, visto, enviar, tarjeta } = await nueva({
      prop, confirmar: () => ({ status: 200, json: { estado: "ejecutada", ok: true, mensaje: "Nota agregada.", ui: [{ tipo: "navegar", url: "/establecimientos/1", etiqueta: "Ver establecimiento" }] } }),
    });
    await enviar();
    await caso("un clic NO real (script) no confirma", async () => {
      await p.locator("asistente-chat").evaluate((e) => e.shadowRoot.querySelector(".msg.confirmacion button.primario").click());
      await dormir(400);
      afirma(visto.token.length === 0 && visto.confirmar.length === 0, "un click() de script confirmó");
    });
    await caso("Confirmar pide el token de escritura al sistema (con confirmacion y huella) y lo usa en el POST", async () => {
      await tarjeta().locator("button.primario").click();
      await tarjeta().locator(".accion-estado", { hasText: "Nota agregada." }).waitFor();
      afirma(visto.token.length === 1, "no pidió el token al sistema");
      const u = new URL(visto.token[0].url);
      afirma(u.origin === BASE && u.searchParams.get("confirmacion") === "acc-1" && u.searchParams.get("huella") === "h".repeat(64) && u.searchParams.get("usuario") === "ana", "URL del token: " + u);
      afirma(visto.confirmar.length === 1 && visto.confirmar[0].auth === "Bearer tok-escritura", "POST sin el token de escritura: " + JSON.stringify(visto.confirmar));
      afirma(visto.confirmar[0].url.endsWith("/v1/confirmaciones/acc-1/confirmar"), "ruta");
    });
    await caso("al ejecutarse: botones fuera, estado «Hecho», enlace de la acción y evento al anfitrión", async () => {
      const t = tarjeta();
      afirma(!(await t.locator("button.primario").isVisible()), "los botones siguen visibles");
      afirma(await t.locator("a", { hasText: "Ver establecimiento" }).isVisible(), "sin el enlace de ui");
      const ev = await p.evaluate(() => window.__eventos);
      afirma(ev.length === 1 && ev[0].estado === "ejecutada" && ev[0].id === "acc-1" && ev[0].tool === "agregar_nota", JSON.stringify(ev));
    });
    await p.close();
  }

  // — Cancelar: usa el token de LECTURA, no pide token de escritura —
  {
    const { p, visto, enviar, tarjeta } = await nueva({ prop, cancelar: () => ({ status: 200, json: { estado: "cancelada" } }) });
    await enviar();
    await caso("Cancelar no pide token de escritura y usa el de lectura", async () => {
      await tarjeta().locator("button", { hasText: "Cancelar" }).click();
      await tarjeta().locator(".accion-estado", { hasText: "Cancelada." }).waitFor();
      afirma(visto.token.length === 0 && visto.confirmar.length === 0, "pidió token o confirmó");
      afirma(visto.cancelar.length === 1 && /^Bearer ey/.test(visto.cancelar[0].auth) && visto.cancelar[0].auth !== "Bearer tok-escritura", "token del cancelar: " + visto.cancelar[0]?.auth?.slice(0, 20));
      const ev = await p.evaluate(() => window.__eventos);
      afirma(ev[0].estado === "cancelada", JSON.stringify(ev));
    });
    await p.close();
  }

  // — Resultados que no son «hecho» —
  for (const [titulo, confirmar, esperado, estadoEv] of [
    ["conflicto del sistema (el dato cambió)", () => ({ status: 200, json: { estado: "fallida", ok: false, error: "conflicto" } }), "Los datos cambiaron", "fallida"],
    ["sin permiso en el sistema", () => ({ status: 200, json: { estado: "fallida", ok: false, error: "sin_acceso" } }), "No tenés permiso", "fallida"],
    ["ya cancelada (409)", () => ({ status: 409, json: { error: "accion_no_pendiente", estado: "cancelada" } }), "Cancelada.", "cancelada"],
    ["vencida en el servidor (409)", () => ({ status: 409, json: { error: "accion_no_pendiente", estado: "expirada" } }), "Venció", "expirada"],
    ["confirmación inválida (403)", () => ({ status: 403, json: { error: "confirmacion_invalida" } }), "no es válida", "fallida"],
  ]) {
    const { p, enviar, tarjeta } = await nueva({ prop, confirmar });
    await enviar();
    await caso(`confirmar → ${titulo}`, async () => {
      await tarjeta().locator("button.primario").click();
      await tarjeta().locator(".accion-estado", { hasText: esperado }).waitFor({ timeout: 4000 });
      afirma(!(await tarjeta().locator("button.primario").isVisible()), "los botones siguen");
      const ev = await p.evaluate(() => window.__eventos);
      afirma(ev.at(-1).estado === estadoEv, JSON.stringify(ev));
    });
    await p.close();
  }

  // — Fallos que permiten reintentar —
  {
    let intento = 0;
    const { p, visto, enviar, tarjeta } = await nueva({
      prop,
      token: (route) => (++intento === 1
        ? route.fulfill({ status: 403, body: "" })
        : route.fulfill({ status: 200, contentType: "application/json", body: JSON.stringify({ token: "tok-2", expira: new Date(Date.now() + 60000).toISOString() }) })),
      confirmar: () => ({ status: 200, json: { estado: "ejecutada", ok: true, mensaje: "Hecho ahora." } }),
    });
    await enviar();
    await caso("si el sistema no emite el token se muestra el error y se puede reintentar", async () => {
      await tarjeta().locator("button.primario").click();
      await tarjeta().locator(".accion-error").filter({ hasText: "no autorizó" }).waitFor();
      afirma(visto.confirmar.length === 0, "llamó al asistente sin token");
      afirma(await tarjeta().locator("button.primario").isEnabled(), "el botón quedó deshabilitado");
      await tarjeta().locator("button.primario").click();
      await tarjeta().locator(".accion-estado", { hasText: "Hecho ahora." }).waitFor();
      afirma(visto.confirmar[0].auth === "Bearer tok-2", "no usó el token del reintento");
    });
    await p.close();
  }

  // — Vencimiento en pantalla y reemplazo —
  {
    const { p, enviar, tarjeta } = await nueva({ prop: (n) => prop(n, { expira: new Date(Date.now() + (n === 1 ? 2500 : 120000)).toISOString() }) });
    await enviar();
    await caso("al vencer, la tarjeta se cierra sola y no se puede confirmar", async () => {
      await tarjeta(0).locator(".accion-estado", { hasText: "Venció" }).waitFor({ timeout: 6000 });
      afirma(!(await tarjeta(0).locator("button.primario").isVisible()), "botones visibles");
      afirma((await p.evaluate(() => window.__eventos)).at(-1).estado === "expirada", "evento");
    });
    await enviar("otra");
    await enviar("y otra más");
    await caso("una propuesta nueva reemplaza a la anterior en pantalla", async () => {
      await p.locator("asistente-chat .msg.confirmacion").nth(2).waitFor();
      afirma((await tarjeta(1).locator(".accion-estado").textContent()).includes("Reemplazada"), "la segunda no quedó reemplazada: " + await tarjeta(1).locator(".accion-estado").textContent());
      afirma(await tarjeta(2).locator("button.primario").isVisible(), "la última no es confirmable");
    });
    await p.close();
  }

  // — Un evento mal formado no rompe el chat —
  {
    const { p, enviar } = await nueva({ prop: () => ({ id: 5, resumen: null }) });
    await enviar();
    await caso("una propuesta mal formada se ignora sin romper el chat", async () => {
      afirma(await p.locator("asistente-chat .msg.confirmacion").count() === 0, "dibujó una tarjeta inválida");
      afirma((await p.locator("asistente-chat .msg.assistant").last().textContent()).includes("Te pedí confirmar"), "no mostró el texto");
    });
    await p.close();
  }

  const ok = resultados.filter((r) => r.ok).length;
  return { resultados, resumen: `${ok}/${resultados.length} ok` };
}
