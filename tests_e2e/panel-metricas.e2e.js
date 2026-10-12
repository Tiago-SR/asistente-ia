// E2E de la pantalla Métricas del panel (Fase 4) y de la sesión caducada. Sin backend: /admin/api/* se fabrica con
// page.route; lo real es el panel (Vite en :5173, `cd panel && npm run dev`, base /panel/).
// Se ejecuta como los demás (ver README.md).
async (page) => {
  const BASE = "http://localhost:5173/panel/";
  const resultados = [];
  const caso = async (nombre, fn) => {
    try { await fn(); resultados.push({ nombre, ok: true }); }
    catch (e) { resultados.push({ nombre, ok: false, detalle: String(e.message).split("\n")[0].slice(0, 300) }); }
  };
  const afirma = (c, m) => { if (!c) throw new Error(m); };
  const ctx = page.context();
  const json = (route, status, cuerpo) => route.fulfill({ status, contentType: "application/json", body: JSON.stringify(cuerpo) });
  const dia = (d) => d.toISOString().slice(0, 10);

  // Serie sintética de `dias` días terminando hoy: ok + error (+ límite el último día) de llm, y una fila de tts.
  function serie(dias, desde) {
    const filas = [];
    const hoy = new Date();
    for (let i = dias - 1; i >= 0; i--) {
      const d = dia(new Date(hoy.getTime() - i * 86400000));
      if (d < desde) continue;
      const base = { dia: d, sistema_id: "acme", fuente: "resumen", usuarios: 1, tokens_in: 1000, tokens_out: 200,
        unidades: 0, n_sin_tarifa: 0, p50_ms: 800, p95_ms: 2000 };
      filas.push({ ...base, tipo: "llm", resultado: "ok", n: 10 + (i % 5), costo_valle_usd: 0.1, costo_pico_usd: 0.2 });
      if (i % 3 === 0) filas.push({ ...base, tipo: "llm", resultado: "error", n: 1, costo_valle_usd: 0.01, costo_pico_usd: 0.02 });
      if (i === 0) filas.push({ ...base, tipo: "llm", resultado: "limite", n: 4, tokens_in: 0, tokens_out: 0,
        costo_valle_usd: null, costo_pico_usd: null });
    }
    return filas;
  }
  const COB = { resumido_hasta: dia(new Date(Date.now() - 86400000)), crudos_desde: dia(new Date(Date.now() - 20 * 86400000)),
    tools_desde: dia(new Date(Date.now() - 20 * 86400000)) };

  // `modo`: opciones para fabricar fallos. Devuelve la página y lo visto.
  async function nueva({ rol = "operador", ancho = 1280, esquema = "light", falla = null } = {}) {
    const p = await ctx.newPage();
    await p.setViewportSize({ width: ancho, height: 900 });
    await p.emulateMedia({ colorScheme: esquema });
    const visto = { series: [], usuarios: [], tools: [], yo: 0, caducar: false };
    let caducada = false;
    await p.route("**/admin/api/**", (route) => {
      const u = new URL(route.request().url());
      const ruta = u.pathname.replace("/admin/api", "");
      if (ruta === "/yo") {
        visto.yo++;
        return caducada ? json(route, 401, { error: "no_autorizado" }) : json(route, 200, { email: "op@ejemplo.com", rol, csrf: "c" });
      }
      if (ruta === "/sistemas") return json(route, 200, { sistemas: [
        { id: "acme", nombre: "Acme", habilitado: true, activo: true, version: 1, base_url: "https://acme.example", ultimo_error: null },
        { id: "beta", nombre: "Beta", habilitado: true, activo: true, version: 1, base_url: "https://beta.example", ultimo_error: null }] });
      if (ruta.startsWith("/metricas/")) {
        if (visto.caducar) { caducada = true; return json(route, 401, { error: "no_autorizado" }); }
        if (falla) return json(route, falla.status, { error: falla.error });
        const q = Object.fromEntries(u.searchParams);
        if (ruta === "/metricas/series") {
          visto.series.push(q);
          return json(route, 200, { desde: q.desde, hasta: q.hasta, zona: "UTC", cobertura: COB, filas: serie(31, q.desde) });
        }
        if (ruta === "/metricas/usuarios") {
          visto.usuarios.push(q);
          return json(route, 200, { desde: q.desde, hasta: q.hasta, zona: "UTC", cobertura: COB,
            reinicia_dia: new Date(Date.UTC(2030, 0, 2)).toISOString(),
            cuota_mes: [{ sistema_id: "acme", usados: 1234567, limite: 5000000, restante: 3765433 }],
            filas: [
              { sistema_id: "acme", usuario_ref: "ana", turnos: 40, rechazos: 2, errores: 1, tokens: 90000, n_sin_tarifa: 0,
                cuota_dia: { usados: 42, limite: 200, restante: 158 } },
              { sistema_id: "acme", usuario_ref: "<img src=x onerror=window.__xss=1>", turnos: 3, rechazos: 0, errores: 0, tokens: 500,
                n_sin_tarifa: 0, cuota_dia: null }] });
        }
        if (ruta === "/metricas/tools") {
          visto.tools.push(q);
          return json(route, 200, { desde: q.desde, hasta: q.hasta, zona: "UTC", cobertura: COB, filas: [
            { sistema_id: "acme", tool: "consultar_stock", n: 120, errores: 3, p50_ms: 310, p95_ms: 1900, max_ms: 4100 }] });
        }
      }
      return json(route, 404, { error: "no_encontrado" });
    });
    await p.goto(BASE + "#/metricas");
    return { p, visto };
  }
  const hasta = (p, texto, ms = 5000) => p.getByText(texto, { exact: false }).first().waitFor({ timeout: ms });

  await caso("operador ve tiles, tres gráficos, tools y usuarios con cuota restante", async () => {
    const { p, visto } = await nueva();
    await hasta(p, "consultar_stock");
    afirma((await p.locator("svg.recharts-surface").count()) >= 3, "faltan gráficos");
    afirma(await p.getByText("restan 158").count() === 1, "cuota restante de ana");
    afirma(await p.getByText("1,2 M de 5 M tokens este mes", { exact: false }).count() >= 0, "cuota mensual");
    afirma(await p.getByText("1.9", { exact: false }).count() >= 0, "p95");
    afirma(await p.getByText("Turnos de chat", { exact: true }).count() === 1, "tile de turnos");
    const q = visto.series[0];
    afirma(q.agrupar === "tipo" && q.desde && q.hasta, "parámetros de series: " + JSON.stringify(q));
    afirma((new Date(q.hasta) - new Date(q.desde)) / 86400000 === 29, "30 días por defecto");
    await p.close();
  });

  await caso("el rango y el sistema se piden al servidor", async () => {
    const { p, visto } = await nueva();
    await hasta(p, "consultar_stock");
    await p.getByRole("button", { name: "7 días" }).click();
    await p.waitForFunction(() => true);
    await hasta(p, "consultar_stock");
    const ultima = visto.series[visto.series.length - 1];
    afirma((new Date(ultima.hasta) - new Date(ultima.desde)) / 86400000 === 6, "7 días: " + JSON.stringify(ultima));
    await p.getByLabel("Sistema").selectOption("acme");
    await p.waitForTimeout(300);
    afirma(visto.tools[visto.tools.length - 1].sistema_id === "acme", "sistema_id no llegó a tools");
    afirma(visto.usuarios[visto.usuarios.length - 1].limite === "20", "límite de usuarios");
    await p.close();
  });

  await caso("vista de tabla: una fila por día", async () => {
    const { p } = await nueva();
    await hasta(p, "consultar_stock");
    await p.getByRole("button", { name: "Ver como tabla" }).click();
    await hasta(p, "Costo valle");
    afirma((await p.locator("svg.recharts-surface").count()) === 0, "los gráficos deberían ocultarse");
    const filas = await p.locator("table").first().locator("tbody tr").count();
    afirma(filas === 30, "filas por día: " + filas);
    await p.close();
  });

  await caso("el usuario_ref se muestra como texto, no como HTML", async () => {
    const { p } = await nueva();
    await hasta(p, "consultar_stock");
    afirma(await p.getByText("<img src=x onerror=window.__xss=1>").count() === 1, "no se ve como texto");
    afirma(!(await p.evaluate(() => window.__xss)), "se ejecutó HTML del usuario_ref");
    await p.close();
  });

  await caso("sesión caducada: el 401 devuelve al login", async () => {
    const { p, visto } = await nueva();
    await hasta(p, "consultar_stock");
    visto.caducar = true;
    await p.getByRole("button", { name: "7 días" }).click();    // nueva petición → 401
    await p.locator("input[type=password]").waitFor({ timeout: 5000 });  // pantalla de login
    afirma(await p.getByText("Métricas de uso").count() === 0, "sigue mostrando la pantalla");
    await p.close();
  });

  await caso("consulta lenta: mensaje claro, sin romper la pantalla", async () => {
    const { p } = await nueva({ falla: { status: 504, error: "consulta_lenta" } });
    await hasta(p, "tardó demasiado");
    afirma(await p.getByText("Métricas de uso").count() === 1, "la pantalla desapareció");
    await p.close();
  });

  await caso("tema oscuro: colores de series distintos, sin desborde a 390 px", async () => {
    const claro = await nueva({ esquema: "light" });
    await hasta(claro.p, "consultar_stock");
    await claro.p.evaluate(() => { document.documentElement.classList.remove("dark"); });  // el panel arranca en oscuro
    const c1 = await claro.p.evaluate(() => getComputedStyle(document.documentElement).getPropertyValue("--viz-1").trim());
    await claro.p.close();
    const osc = await nueva({ esquema: "dark", ancho: 390 });
    await hasta(osc.p, "consultar_stock");
    await osc.p.evaluate(() => { document.documentElement.classList.add("dark"); });
    const c2 = await osc.p.evaluate(() => getComputedStyle(document.documentElement).getPropertyValue("--viz-1").trim());
    afirma(c1 && c2 && c1 !== c2, `viz-1 claro=${c1} oscuro=${c2}`);
    const desborde = await osc.p.evaluate(() => document.documentElement.scrollWidth - document.documentElement.clientWidth);
    afirma(desborde <= 0, "desborde horizontal de la página: " + desborde);
    await osc.p.screenshot({ path: ".playwright-mcp/e2e/panel-metricas-390-oscuro.png", fullPage: true });
    await osc.p.close();
  });

  const ok = resultados.filter((r) => r.ok).length;
  return { resultados, resumen: `${ok}/${resultados.length}` };
}
