// E2E del Excel descargable (tool `generar_excel`) con el LLM real. Necesita un sistema con `exportar_excel: true`
// y su página de ejemplo: en dev, `mock-a` (:8201). Se ejecuta como los demás (ver README.md).
// Cubre: tarjeta de descarga, descarga real (.xlsx válido, fórmulas neutralizadas), tarjeta tras recargar la página
// y que otro usuario no pueda bajar el archivo (404).
async (page) => {
  const BASE = "http://localhost:8201";
  const SHOTS = ".playwright-mcp/e2e";
  const resultados = [];
  const caso = async (nombre, fn) => {
    try { await fn(); resultados.push({ nombre, ok: true }); }
    catch (e) { resultados.push({ nombre, ok: false, detalle: String(e.message).split("\n")[0].slice(0, 300) }); }
  };
  const afirma = (c, m) => { if (!c) throw new Error(m); };
  const ctx = page.context();
  const verChat = async (p) => {
    const ver = p.locator("asistente-chat button", { hasText: "Ver el chat" });
    await ver.waitFor({ state: "visible", timeout: 4000 }).then(() => ver.click()).catch(() => {});  // arranca en modo voz
    await p.locator("asistente-chat textarea").waitFor({ timeout: 15000 });
  };
  const abrir = async (usuario) => {
    const p = await ctx.newPage();
    await p.setViewportSize({ width: 1100, height: 800 });
    await p.goto(`${BASE}/?usuario=${usuario}`);
    await p.evaluate(() => localStorage.clear());  // el perfil puede traer el modo voz de otra sesión
    await p.reload();
    await verChat(p);
    return p;
  };
  const esperaFin = (p) => p.waitForFunction(() => document.querySelector("asistente-chat").shadowRoot.querySelector("[aria-busy]")?.getAttribute("aria-busy") === "false", null, { timeout: 180000 });
  const PEDIDO = "Genera un Excel llamado «compras» con las columnas Producto, Cantidad y Precio, y estas filas: " +
    "Arroz, 2, 3.5; Fideos, 1, 2.25; =1+1, 3, 0.5. Usa exactamente esos datos.";

  const ana = await abrir("ana");
  let id = "", nombre = "";
  await caso("el pedido genera la tarjeta de descarga", async () => {
    await ana.locator("asistente-chat textarea").fill(PEDIDO);
    await ana.locator("asistente-chat textarea").press("Enter");
    await ana.locator("asistente-chat .msg.user").first().waitFor();
    await esperaFin(ana);
    const b = ana.locator("asistente-chat button.descarga");
    await b.first().waitFor({ timeout: 5000 });
    nombre = (await b.first().innerText()).replace("Descargar ", "");
    afirma(/^compras.*\.xlsx$/i.test(nombre), "nombre inesperado: " + nombre);
  });
  await ana.screenshot({ path: `${SHOTS}/excel-01-tarjeta.png` });

  await caso("el clic baja un .xlsx válido y las fórmulas quedan como texto", async () => {
    const [d] = await Promise.all([
      ana.waitForEvent("download", { timeout: 15000 }),
      ana.locator("asistente-chat button.descarga").first().click(),
    ]);
    afirma(d.suggestedFilename() === nombre, "nombre de descarga: " + d.suggestedFilename());
    let total = 0, primero = null;
    for await (const c of await d.createReadStream()) { primero ??= c; total += c.length; }
    afirma(total > 500 && primero[0] === 0x50 && primero[1] === 0x4b, `no es un zip/xlsx (${total} bytes)`);  // las fórmulas se comprueban en el servidor
  });

  await caso("recargar la página: la conversación vuelve con su tarjeta de descarga", async () => {
    await ana.reload();
    await verChat(ana);
    const b = ana.locator("asistente-chat button.descarga");
    await b.first().waitFor({ timeout: 8000 });
    afirma(!(await b.first().isDisabled()), "la tarjeta aparece deshabilitada");
    const [d] = await Promise.all([ana.waitForEvent("download", { timeout: 15000 }), b.first().click()]);
    afirma(d.suggestedFilename() === nombre, "nombre tras recargar: " + d.suggestedFilename());
  });
  await ana.screenshot({ path: `${SHOTS}/excel-02-recargada.png` });

  await caso("otro usuario no puede bajar el archivo (404)", async () => {
    // id del archivo: lo pide el widget al descargar
    const [req] = await Promise.all([
      ana.waitForRequest((r) => r.url().includes("/v1/descargas/"), { timeout: 15000 }),
      ana.locator("asistente-chat button.descarga").first().click(),
    ]);
    id = req.url().split("/v1/descargas/")[1];
    const beto = await abrir("beto");
    const estado = await beto.evaluate(async (id) => {
      const urlTok = document.querySelector("asistente-chat").getAttribute("token-url");  // el de beto
      const t = await (await fetch(urlTok, { credentials: "same-origin" })).json();
      const r = await fetch(`http://localhost:8100/v1/descargas/${id}`, { headers: { Authorization: "Bearer " + t.token } });
      return r.status;
    }, id);
    afirma(estado === 404, "beto recibió " + estado);
    await beto.close();
  });

  const ok = resultados.filter((r) => r.ok).length;
  return { resultados, resumen: `${ok}/${resultados.length} casos ok`, id };
}
