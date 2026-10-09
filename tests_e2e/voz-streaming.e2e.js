// E2E del audio en vivo de la voz del servidor (MediaSource): el <audio> arranca con el primer trozo, sin esperar la
// frase entera. Sin LLM ni ElevenLabs: /v1/estado y /v1/voz/sintetizar se fabrican con page.route, pero el audio es un MP3
// REAL (un tono de 1,2 s) y se reproduce de verdad en el Chromium del navegador de pruebas.
// Se ejecuta como los demás (ver README.md). Necesita sistema-php (:8203).
//
// El MP3 se generó con: ffmpeg -f lavfi -i "sine=frequency=440:duration=1.2" -ac 1 -ar 16000 -b:a 16k tono.mp3
async (page) => {
  const BASE = "http://localhost:8203";
  const MP3_B64 = "SUQzBAAAAAAAIlRTU0UAAAAOAAADTGF2ZjYzLjEuMTAyAAAAAAAAAAAAAAD/81jAAAAAAAAAAAAASW5mbwAAAA8AAAAkAAAK1AAXFx0dHSQkJCsrKzExODg4Pz8/RUVFTExTU1NZWVlgYGBnZ2dtbXR0dHt7e4GBgYiIjo6OlZWVnJycoqKiqamwsLC2tra9vb3ExMrKytHR0djY2N7e3uXl7Ozs8vLy+fn5//8AAAAATGF2YzYzLjEuAAAAAAAAAAAAAAAAJAPAAAAAAAAACtTpVxsNAAAAAAAAAAAAAAD/8yjEAAnAWrBfRhgCAuW2gYC7u7u7uIiHPBwGTIEEIBD08EOD7+co8/yjuH+U9/R////obwgwwwhpyv//Uybj8f+WggicJgL/8yjEFBGw8phRmpgAIkcZKIQB6wIFQhtooEBwxb0AEWFiRGOFlCtiZ/yKkVMi8Xv/MS6XUkjL8FQkDTfyoSBp///7kacKbkD/8yjECA8IcjQB3hAABQADALAwMEEAIwQAbzDOItNZIcA5GyUjGTGqMQwMswqhTwqEWYHABJfFsTrU0yKMf///96qld5dpf0L/8yjEBg1gajAAB7YsoAgIATMAMC4wFgbzBZFuMmryg1QR5jBGBdMdBDhrMys1BSMiK06Kzwxv//////6q///84w/b2sJEAEP/8yjECw7AciwA5/iAAIbMKDoxyhzSmeMNBQlDG9AjIwM8C1Mzms1NADHJEAxPQMae/EvpMA9////3f/tq///9yR8XSV0iyPD/8yjECwzIbjAA37iA+HJAGpz0g40pQhjnoAyMPUE8xycTBVwEJ0JAao89Mkr1DP//////9lX///3TP6zpIYtyCQUYEEJhsrH/8yjEEgywajQA57aAmCVmULkyauwxpgrgfGECZtN4Y8bAoxTWcWLWR7P///+9///9U8UgZmSHMKA4wKKzDhmMs0kyENbTR1H/8yjEGguwbjQA57aBvzCECENGQDgZ0yYjDjRSbyReWWwx///9R96HRZKi2HDgCSzUhI9FXNJw6M52QjTD2BgMgHIxLbwAcxT/8yjEJgx4bjAA37iABS23oj8xXD3////Q///9UrtM5SFLhAADmCQ0YkJpnOJGXBd0bHItRg4AWgUgNc2zGUEBFSdLjRW1yDX/8yjELwuYbjQA57aBsSOBWQpOCMAsEARGAaCyYGwlBix4aGYIMgYLoN5t1p8MRoRgsrW5C5y3YCP//////9qoAABUAfRAJ8z/8yjEOwx4bjgAB7QsjLtiLuIpebhGv4AewBwGF5e8QCpJaJ1Ba7nWf//+n//tuYarVl5Vn//26v///cqfVnSQxd0wEEMOFTL/8yjERA0AXmZWDjhG1COE9zMzqzNuAUUwhwGCAvNP9DEkoxABTqd2NUvS3////RW3JnWWkVAARgBAKgWmAMDUYE4rpiGcfmT/8yjESwyYbjQA37aAmjrmCoD8Z8VHCpJlACRHihb2SOcthb////oV///9TbwSVsyA8BDBkYmaccHk4JoxPznK2IqYeQPRk47/8yjEUwyQbjQAB7Yshk+umEDWYABCt76ROkpw9////0r///1KXCXag6WaMIAzGRQz5DOr9jP0rWOHsUQwtABwoRjJk1MJmEz/8yjEWwzobjAA37iAJgZIlyozTHQ3////3////t6BmWpUkIGIQyIhsCT+YMyhgOKDQYH8EPGAhgRpopKc4MDzMUJyMLZ4On7/8yjEYgz4ajAA37iAwEf//////7GCG///3KH3iD9oADCwUyAaNLRzvuw0L5njjuFMMO0IcymczMFMMMmQwSB1MHbjFPSBn///8yjEaQ1wbjAA5/aAo//o//7F///7sBLRROARjYM+qMDgCEwdQVjEeE9NkPcE9WBlxomsw2hzMf2MOKgw8HSyywrtSkgDP///8yjEbg4gbjCo37iC//3//oqd/////3L///5POquovcKAshDxVIZIkgtzzAnUq8wXoJpMAgAmjSBo7MYM+ABphIgZisKkFsL/8yjEcA/oaiQAx7hk3////TX///1XiFPGFAwAAGIiZlx0cHmmYBEibOYkJhUAzGdJxp/SYgggYIYm/lPSVxz///1Mukw1Ikv/8yjEaw0YbiwA5/aApA4ZMhAjSiE8OcNGZ4A5aQyDDWAMMLFwxFWzAJvMCgpOVwojW2a////6Kv///s64yxS6ohBQiD4hIAH/8yjEcQs4bjgA37aBEiYl4xguyTcYaGEuDgEeZ+BnXMJnoyGMQ8Cr+hNHYCP//////9v///3SRuciacgFAzDBYytDN45jLFn/8yjEfwzQbjAA37iAljXwFAMJ8G0z1LNY1jFTgFC66IfllPYDP////T//2v///ceeFlSYQkAiQ0EIpp4UeUzmkSr6c2AP5hz/8yjEhg14biwA5/aAoE5iUymCbMFjkBAWpU6MSqhh///////66v///lM7rEkEwWAoXCgIGZgk7GPL+Y8f4ZoRD/mBCDYPKJz/8yjEiwz4bjgA37aAfCGXEgQkoRNrA07bFv///+j/9VX///1K38k7YC85gAIGFRaY2NRpOomaFsybfY5phiBMGWDEaHgJigj/8yjEkg0QajAA37iA4CGia7iQ/LKfMSr5SV6mkp0oREQ6TJQlQnokRpPGMHO6BAYdwHhgXA1Eot5KDqIQDFgXijtzM1////3/8yjEmA1IbjAA57aAP//TpXeXaX9CoAgIATMAMC4wFgbzBZFuMmryg1QR5jBGBdMdBDhrMys1BSMiK06Kzwxv//////6l////8yjEnQxYcjAA57iB/dJD8JZ6IgABQmYOGBi85mfrQZbPRhsMD1GFmE2ausnHbhlpwCj9Lh14pL6TAPf///93/7al///9yR//8yjEpgy4bjAADvwoF0ldIsjw+HJAGpz0g40pQhjnoAyMPUE8xycTBVwEJ0JAao89Mkr1DP//////9ir///3TOSu4v8DAGAT/8yjErg1gajAAB7YsIGCBSYjMxnKsmXHy6bHg45gzglGHDJve0ZMhAJBQqabFp0ez////vv///VPAjzL6GQGDAoYJGpiQ8Gb/8yjEsw3gcjAA57aAm9mS96aai5AJhNBNGqJxy9uZgVhCIkG2kXllODn//////9HD//CYfx/Eyw4AxHswAwIwgGcwQgbDCyH/8yjEtgzIbjAA37iA+DVuJ3ORkmMxUQpzAdCXMLUVMlCTMD0AlK9eDaWD4If///9yiAUwCYiRClKEn/bRE8ABIVCN7MPHT6X/8yjEvQzwajAA57aAkJg4xo9/wArwN4xS4hEFwwXDccwihoZikRBUQVIF5fdSEgxAjEnSK//Mi8XkS6Xf232Mi8XkUTFXl5z/8yjExA14bjAA57aALg0JQkDX5wvOFwVER4FaTEFNRTQuMKqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqr/8yjEyQ7oajQBXgAAqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqr/8yjEyBghWoArm6AAqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqr/8yjEogAAA0gBwAAAqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqo=";
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

  async function nueva({ atributos = {}, sintetizar } = {}) {
    const p = await ctx.newPage();
    const visto = { cuerpos: [] };
    await p.addInitScript(() => {
      window.__hablado = [];
      window.SpeechRecognition = window.webkitSpeechRecognition = undefined;
      window.SpeechSynthesisUtterance = class { constructor(t) { this.text = t; } };
      Object.defineProperty(window, "speechSynthesis", { configurable: true, value: {
        getVoices: () => [], cancel() {}, onvoiceschanged: null,
        speak(u) { window.__hablado.push(u.text); setTimeout(() => u.onstart && u.onstart(), 0); setTimeout(() => u.onend && u.onend(), 20); },
      } });
    });
    await p.route("**/v1/estado", (route) => {
      if (route.request().method() === "OPTIONS") return route.fulfill({ status: 204, headers: CORS });
      return route.fulfill({ status: 200, headers: { "content-type": "application/json", ...CORS }, body: JSON.stringify({
        habilitado: true, nombre_sistema: "Sistema PHP", memoria: false, voz: { dictado: false, respuesta: true, max_audio_s: 60 } }) });
    });
    await p.route("**/v1/voz/sintetizar", (route) => {
      if (route.request().method() === "OPTIONS") return route.fulfill({ status: 204, headers: CORS });
      try { visto.cuerpos.push(JSON.parse(route.request().postData() || "{}")); } catch { visto.cuerpos.push(null); }
      if (sintetizar) return sintetizar(route, CORS);
      return route.fulfill({ status: 200, headers: { "content-type": "audio/mpeg", ...CORS }, body: Buffer.from(MP3_B64, "base64") });
    });
    await p.goto(`${BASE}/?usuario=ana`);
    await p.locator("asistente-chat .barra").waitFor();
    if (Object.keys(atributos).length) {
      await p.evaluate((a) => { const w = document.querySelector("asistente-chat"); for (const [k, v] of Object.entries(a)) w.setAttribute(k, v); }, atributos);
    }
    await dormir(300);
    await p.locator("body").click();   // gesto del usuario: el navegador permite reproducir
    const sel = (css, o) => p.locator("asistente-chat " + css, o);
    return { p, visto, sel };
  }

  // — El audio real, por trozos, en la página —
  {
    const { p } = await nueva();
    await caso("el navegador de pruebas puede reproducir MP3 por trozos (MediaSource)", async () => {
      afirma(await p.evaluate(() => typeof MediaSource === "function" && MediaSource.isTypeSupported("audio/mpeg")), "sin MediaSource para audio/mpeg");
    });
    await caso("_audioEnVivo devuelve la URL con el primer trozo y suena antes de que llegue el resto", async () => {
      const r = await p.evaluate(async (b64) => {
        const w = document.querySelector("asistente-chat");
        const bytes = Uint8Array.from(atob(b64), (c) => c.charCodeAt(0));
        const corte = Math.floor(bytes.length / 3), RETRASO = 700;
        const t0 = performance.now();
        let tResto = 0;
        const flujo = new ReadableStream({
          async start(c) {
            c.enqueue(bytes.slice(0, corte));
            await new Promise((res) => setTimeout(res, RETRASO));
            tResto = performance.now() - t0; c.enqueue(bytes.slice(corte)); c.close();
          },
        });
        const url = await w._audioEnVivo(new Response(flujo), w._genVoz, 3);
        const tUrl = performance.now() - t0;
        const a = new Audio();
        const sono = new Promise((res) => { a.onplaying = () => res(performance.now() - t0); });
        const termino = new Promise((res) => { a.onended = () => res(performance.now() - t0); a.onerror = () => res(-1); });
        a.src = url; a.play().catch(() => {});
        const tSono = await Promise.race([sono, new Promise((res) => setTimeout(() => res(-1), 3000))]);
        const tFin = await Promise.race([termino, new Promise((res) => setTimeout(() => res(-1), 6000))]);
        return { tUrl, tSono, tFin, tResto, dur: a.duration, vivas: w._urlsVivas.has(url) };
      }, MP3_B64);
      afirma(r.tUrl < 300, "la URL tardó " + Math.round(r.tUrl) + " ms (esperó al resto)");
      afirma(r.tSono > 0 && r.tSono < 650, "no sonó con el primer trozo: " + JSON.stringify(r));
      afirma(r.tResto > r.tSono, "sonó después de que llegara el resto: " + JSON.stringify(r));
      afirma(r.tFin > 0 && isFinite(r.dur) && Math.abs(r.dur - 1.2) < 0.3, "no terminó bien: " + JSON.stringify(r));
      afirma(r.vivas === true, "la URL no quedó registrada como pendiente");
    });
    await caso("un flujo vacío no da URL (cae a la voz del navegador)", async () => {
      const r = await p.evaluate(async () => { const w = document.querySelector("asistente-chat"); return await w._audioEnVivo(new Response(new Blob([])), w._genVoz, 1); });
      afirma(r === null, "devolvió " + r);
    });
    await caso("si la voz se detuvo mientras llegaba el primer trozo, no se crea nada", async () => {
      const r = await p.evaluate(async (b64) => {
        const w = document.querySelector("asistente-chat");
        const bytes = Uint8Array.from(atob(b64), (c) => c.charCodeAt(0));
        const gen = w._genVoz; w._genVoz++;
        return await w._audioEnVivo(new Response(bytes), gen, 1);
      }, MP3_B64);
      afirma(r === null, "devolvió una URL");
    });
    await p.close();
  }

  // — Por el widget: «Probar voz» pide stream y suena con el audio real, sin caer a la voz del navegador —
  {
    const { p, visto, sel } = await nueva();
    await sel(".ajustes").click();
    await caso("«Probar voz»: pide stream, reproduce el MP3 real y no usa la voz del navegador", async () => {
      await sel(".aj-acciones button", { hasText: "Probar voz" }).click();
      await p.waitForFunction(() => { const w = document.querySelector("asistente-chat"); return w._audio && w._audio.currentTime > 0.3; }, null, { timeout: 5000 });
      afirma(visto.cuerpos.length === 1 && visto.cuerpos[0].stream === true, "cuerpo: " + JSON.stringify(visto.cuerpos));
      await p.waitForFunction(() => { const w = document.querySelector("asistente-chat"); return !w._sonando; }, null, { timeout: 5000 });
      afirma((await p.evaluate(() => window.__hablado.length)) === 0, "cayó a la voz del navegador");
    });
    await p.close();
  }

  // — voz-streaming="no": se pide el audio completo, como antes —
  {
    const { p, visto, sel } = await nueva({ atributos: { "voz-streaming": "no" } });
    await sel(".ajustes").click();
    await caso('con voz-streaming="no" no se pide stream y suena igual', async () => {
      await sel(".aj-acciones button", { hasText: "Probar voz" }).click();
      await p.waitForFunction(() => { const w = document.querySelector("asistente-chat"); return w._audio && w._audio.currentTime > 0.3; }, null, { timeout: 5000 });
      afirma(visto.cuerpos[0] && visto.cuerpos[0].stream === undefined, "cuerpo: " + JSON.stringify(visto.cuerpos));
      afirma((await p.evaluate(() => window.__hablado.length)) === 0, "cayó a la voz del navegador");
    });
    await p.close();
  }

  // — Si el servidor falla, sigue el respaldo de siempre (voz del navegador) —
  {
    const { p, sel } = await nueva({ sintetizar: (route, CORS) => route.fulfill({ status: 502, headers: { "content-type": "application/json", ...CORS }, body: '{"error":"voz_error"}' }) });
    await sel(".ajustes").click();
    await caso("con el servidor caído (502) habla la voz del navegador", async () => {
      await sel(".aj-acciones button", { hasText: "Probar voz" }).click();
      await p.waitForFunction(() => window.__hablado.length === 1, null, { timeout: 8000 });
    });
    await p.close();
  }

  const ok = resultados.filter((r) => r.ok).length;
  return { resultados, resumen: `${ok}/${resultados.length} ok` };
}
