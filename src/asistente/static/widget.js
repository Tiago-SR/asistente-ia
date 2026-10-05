/*
 * <asistente-chat> — widget de chat del Asistente.
 *
 * Web Component sin dependencias ni build. Shadow DOM, sin innerHTML: todo el contenido
 * (incluido el Markdown del modelo) se construye con nodos DOM, así que no hay inyección.
 *
 * Es una vista de chat a pantalla completa: ocupa el 100% del alto y ancho de su contenedor
 * (el anfitrión le da tamaño, p. ej. style="display:block;height:100vh"). No es un popup ni se
 * superpone a la página. Muestra solo la conversación actual (botón "Nueva conversación" en la
 * barra superior); el historial de chats está oculto (ver MOSTRAR_HISTORIAL).
 *
 * Atributos:
 *   token-url   (obligatorio) ruta del sistema anfitrión que emite el token; se pide con
 *               las cookies de sesión del anfitrión. Responde {token, expira}.
 *   servidor    URL base del asistente. Por defecto, el origen desde el que se cargó este script.
 *   titulo      título de la barra superior. Por defecto, el nombre del sistema.
 *   placeholder texto del campo de entrada.
 *   idioma      idioma de la voz (BCP 47). Por defecto "es-UY"; sin voces de ese idioma se usa es-ES o la
 *               primera en español que tenga el sistema.
 *   voz         nombre exacto de una voz del navegador (speechSynthesis) para forzarla.
 *   voz-motor   "auto" (por defecto), "navegador" o "servidor". El dictado usa el reconocimiento de voz del
 *               navegador (Web Speech; en Chrome el audio lo procesa el servicio de Google) y, si no existe,
 *               el STT del asistente (POST /v1/voz/transcribir). "servidor" evita enviar el audio a Google.
 *               La respuesta hablada usa siempre las voces del navegador (speechSynthesis).
 *   palabra-activacion        palabra que despierta el modo «manos libres» (por defecto "asistente").
 *   manos-libres-inactividad  minutos sin interacción tras los que el modo manos libres se apaga solo
 *               (por defecto 5; 0 = no se apaga). El botón «Manos libres» solo aparece si el navegador tiene
 *               reconocimiento y síntesis de voz, la página es un contexto seguro y voz-motor no es "servidor".
 *
 * Personalización por variables CSS (se heredan a través del Shadow DOM):
 *   --asistente-color, --asistente-color-texto, --asistente-fondo, --asistente-texto,
 *   --asistente-borde, --asistente-fuente, --asistente-radio,
 *   --asistente-ancho-lateral (260px), --asistente-ancho-columna (760px)
 *
 * Eventos (CustomEvent, burbujean y atraviesan el Shadow DOM):
 *   asistente:accion   {detail: {tipo, url, etiqueta}} por cada sugerencia `ui` del sistema.
 *                      Si el anfitrión llama preventDefault(), el widget no muestra su botón.
 *   asistente:estado   {detail: {habilitado}} al decidir si el asistente está disponible
 *                      (si no lo está, el widget muestra un aviso en lugar del chat).
 *   asistente:confirmacion  {detail: {id, tool, estado}} cuando una acción propuesta por el asistente termina
 *                      (estado: ejecutada | cancelada | expirada | reemplazada | fallida). El anfitrión puede
 *                      refrescar su pantalla tras una acción ejecutada.
 *
 * Acciones con confirmación: si el sistema habilitó escrituras, el asistente solo las PROPONE; el widget muestra
 * una tarjeta con el resumen que redactó el sistema y los botones Confirmar / Cancelar. Confirmar pide al
 * token-url del anfitrión (con su sesión) un token de escritura para esa confirmación. Nunca se confirma por voz.
 */
(() => {
  "use strict";
  if (customElements.get("asistente-chat")) return;

  const ORIGEN_SCRIPT = (() => {
    try { return new URL(document.currentScript.src).origin; } catch { return ""; }
  })();
  const MARGEN_RENOVAR_MS = 60_000;
  // Decisión de producto: por ahora el widget es solo la conversación actual, sin lista de chats.
  // El historial (barra lateral, carga, borrado) sigue implementado; ponerlo en true lo reactiva.
  const MOSTRAR_HISTORIAL = false;
  // Se recuerda solo el id de la conversación actual (nunca el token) en sessionStorage, para
  // retomarla al recargar la página. Se descarta al cerrar la pestaña.
  const CLAVE_CONV = "asistente:conversacion:";

  const TEXTOS = {
    escribir: "Escribí tu pregunta…",
    enviar: "Enviar",
    nueva: "Nueva conversación",
    historial: "Historial",
    borrar: "Borrar conversación",
    confirmarBorrar: "¿Borrar esta conversación? No se puede deshacer.",
    noDisponible: "El asistente no está disponible para tu usuario.",
    sinHistorial: "Todavía no hay conversaciones.",
    bienvenida: "Hola, ¿en qué te puedo ayudar?",
    pensando: "Pensando…",
    consultando: "Consultando",
    dictar: "Dictar",
    detener: "Detener grabación",
    transcribiendo: "Transcribiendo…",
    escuchando: "Escuchando…",
    escuchar: "Escuchar la respuesta",
    callar: "Dejar de escuchar",
    leerAuto: "Leer las respuestas en voz alta",
    noLeerAuto: "Dejar de leer en voz alta",
    manosLibres: "Manos libres",
    apagarManosLibres: "Apagar manos libres",
    mhArmado: "Manos libres activo. Decí «{p}» para hablar.",
    mhCapturando: "Te escucho…",
    mhConfirmando: "¿Lo envío? Decí «enviar» o «cancelar».",
    mhRespondiendo: "Respondiendo… Decí «{p}» para interrumpir.",
    mhEsperar: "Esperá a que termine la respuesta para enviar.",
    mhPrivacidad: "Micrófono abierto: el audio se envía al servicio de voz del navegador (Google, en Chrome).",
    mhInactividad: "Manos libres apagado por inactividad.",
    cancelar: "Cancelar",
    confirmarTitulo: "Confirmá esta acción",
    confirmar: "Confirmar",
    vence: "Vence en {t}",
    ejecutando: "Ejecutando…",
    mhConfirmarPantalla: "Te pido confirmar en pantalla: {r}",
    pie: "Las respuestas pueden contener errores; verificá los datos importantes.",
  };
  const ERRORES = {
    mensajes_min: "Enviaste demasiados mensajes seguidos. Esperá un momento.",
    mensajes_dia: "Alcanzaste el límite diario de mensajes.",
    tokens_mes: "Se alcanzó el límite mensual de uso del asistente.",
    timeout_turno: "La consulta tardó demasiado. Probá de nuevo.",
    demasiadas_iteraciones: "No pude completar la consulta. Probá reformularla.",
    llm_no_disponible: "El asistente no está disponible por ahora.",
    llm_no_configurado: "El asistente no está disponible por ahora.",
    origen_no_permitido: "Esta página no está autorizada para usar el asistente.",
    mensaje_invalido: "El mensaje está vacío o es demasiado largo.",
    no_se_pudo_guardar: "No se pudo guardar la conversación.",
  };
  // Estado final de una acción propuesta (tarjeta de confirmación).
  const ESTADOS_ACCION = {
    ejecutada: "Hecho.",
    cancelada: "Cancelada.",
    expirada: "Venció. Pedilo de nuevo si todavía lo querés.",
    reemplazada: "Reemplazada por una propuesta más reciente.",
    fallida: "No se pudo realizar.",
    confirmada: "Ya se está ejecutando.",
  };
  const ERRORES_ACCION = {
    conflicto: "Los datos cambiaron desde la propuesta. Pedilo de nuevo.",
    sin_acceso: "No tenés permiso para hacer esto.",
    no_encontrado: "Ya no existe el dato sobre el que se iba a actuar.",
    parametros_invalidos: "El sistema no aceptó los datos de la acción.",
    no_disponible: "Esta acción no está disponible.",
    timeout: "El sistema tardó demasiado: verificá en el sistema si se hizo antes de repetirlo.",
    error_sistema: "El sistema no pudo realizar la acción.",
    confirmacion_invalida: "La confirmación no es válida. Pedilo de nuevo.",
    token_invalido: "Tu sesión venció. Volvé a intentarlo.",
    token_expirado: "Tu sesión venció. Volvé a intentarlo.",
    sin_autorizacion: "El sistema no autorizó la acción (puede que haya vencido). Pedilo de nuevo.",
  };
  const ERRORES_VOZ = {
    voz_no_disponible: "El dictado no está disponible por ahora.",
    audio_tipo_no_permitido: "Tu navegador grabó en un formato que el dictado no admite.",
    audio_demasiado_grande: "La grabación es demasiado larga. Probá con una más corta.",
    audio_demasiado_largo: "La grabación es demasiado larga. Probá con una más corta.",
    audio_invalido: "No se pudo procesar el audio. Probá de nuevo.",
    limite_excedido: "Dictaste demasiadas veces seguidas. Esperá un momento.",
    voz_error: "No se pudo transcribir el audio. Probá de nuevo.",
    mic_denegado: "No hay permiso para usar el micrófono.",
    mic_no_disponible: "No se encontró un micrófono.",
    sin_texto: "No se entendió nada. Probá de nuevo.",
    reco_red: "No se pudo contactar el servicio de reconocimiento de voz del navegador.",
    reco_error: "No se pudo reconocer la voz. Probá de nuevo.",
  };
  // Formatos que acepta POST /v1/voz/transcribir, en orden de preferencia.
  const TIPOS_GRABACION = ["audio/webm;codecs=opus", "audio/webm", "audio/ogg;codecs=opus", "audio/mp4"];
  const ERROR_GENERICO = "Ocurrió un error. Probá de nuevo.";

  function puedeGrabar() {
    return !!(window.MediaRecorder && navigator.mediaDevices && navigator.mediaDevices.getUserMedia);
  }
  // Voz del navegador (Web Speech API). Se consulta en cada uso: la disponibilidad puede cambiar (voces que cargan tarde).
  const reconocimiento = () => window.SpeechRecognition || window.webkitSpeechRecognition || null;
  function puedeHablar() {
    return "speechSynthesis" in window && typeof window.SpeechSynthesisUtterance === "function";
  }
  const CLAVE_LEER = "asistente:leer-en-voz-alta";

  // ── Modo «manos libres» (ver contrato 7.4) ──
  // Decisión de producto: nada se envía solo al terminar de hablar; el usuario confirma («enviar» o botón).
  // Ponerlo en false hace que se envíe al cerrar la frase (mismo camino, sin código aparte).
  const MANOS_LIBRES_CONFIRMAR = true;
  const PALABRA_ACTIVACION = "asistente";   // por defecto; atributo palabra-activacion
  const MH_INACTIVIDAD_MIN = 5;             // se apaga solo tras tantos minutos sin interacción; atributo manos-libres-inactividad (0 = nunca)
  const MH_CIERRE_MS = 1800;                // silencio tras el que una frase dictada pasa a confirmación
  const MH_ESPERA_MS = 8000;                // tras la palabra de activación, tiempo para empezar a hablar
  const MH_MAX_FALLOS = 5;                  // reinicios seguidos del reconocedor con error antes de apagar

  const COMANDOS = {
    enviar: ["enviar", "envia", "enviar mensaje", "enviar pregunta"],
    cancelar: ["cancelar", "cancela", "descartar", "descarta"],
    apagar: ["apagar manos libres", "apaga manos libres", "desactivar manos libres"],
  };

  // minúsculas, sin acentos ni puntuación, espacios simples: para comparar lo que reconoce el navegador.
  function normalizarFrase(t) {
    return String(t).normalize("NFD").replace(/[̀-ͯ]/g, "").toLowerCase()
      .replace(/[^a-z0-9\s]/g, " ").replace(/\s+/g, " ").trim();
  }
  // Texto que sigue a la palabra de activación si esta aparece al comienzo de la frase (con hasta `maxAntes`
  // palabras antes, p. ej. «oye asistente»); null si no aparece.
  function buscarActivacion(texto, palabra, maxAntes = 2) {
    const buscadas = normalizarFrase(palabra).split(" ").filter(Boolean);
    if (!buscadas.length) return null;
    const toks = String(texto).trim().split(/\s+/);
    const norm = toks.map(normalizarFrase);
    for (let i = 0; i <= Math.min(maxAntes, toks.length - buscadas.length); i++) {
      if (buscadas.every((b, k) => norm[i + k] === b)) {
        return toks.slice(i + buscadas.length).join(" ").replace(/^[\s,.:;¡!¿?]+/, "");
      }
    }
    return null;
  }
  // "enviar" | "cancelar" | "apagar" si la frase ENTERA es un comando (opcional «por favor»); si no, null.
  function comandoDe(texto) {
    const n = normalizarFrase(texto).replace(/ por favor$/, "");
    for (const [cmd, frases] of Object.entries(COMANDOS)) if (frases.includes(n)) return cmd;
    return null;
  }
  // Qué hacer con una frase reconocida según el estado. Los comandos solo valen en frases finales: un
  // «enviar» parcial podría ser el comienzo de «enviar un informe».
  function interpretar(estado, texto, palabra, final) {
    if (!String(texto).trim()) return { accion: "ignorar" };
    const cmd = final ? comandoDe(texto) : null;
    if (cmd === "apagar" && estado !== "apagado") return { accion: "apagar" };
    if (estado === "capturando" || estado === "confirmando") {
      if (cmd === "enviar" || cmd === "cancelar") return { accion: cmd };
      return { accion: "texto", texto };
    }
    if (estado === "armado" || estado === "respondiendo") {
      const resto = buscarActivacion(texto, palabra);
      return resto === null ? { accion: "ignorar" } : { accion: "activar", resto };
    }
    return { accion: "ignorar" };
  }
  // Espera antes de reiniciar el reconocedor: breve si terminó por silencio, creciente si falló.
  function retrasoReinicio(fallos) { return Math.min(5000, 250 * 2 ** fallos); }

  // Markdown -> texto para leer en voz alta (sin símbolos, enlaces, código ni separadores de tabla).
  function textoParaVoz(md) {
    return String(md)
      .replace(/```[\s\S]*?```/g, " ")
      .replace(/^\s*\|?[\s:|-]{3,}\|?\s*$/gm, "")
      .replace(/\[([^\]]+)\]\([^)]*\)/g, "$1")
      .replace(/(\w)_(\w)/g, "$1 $2")
      .replace(/[`*_#>]+/g, "")
      .replace(/^\s*[-+]\s+/gm, "")
      .replace(/\s*\|\s*/g, ", ")
      .replace(/^, | ?,\s*$/gm, "")
      .replace(/[ \t]+/g, " ")
      .replace(/\n{2,}/g, "\n")
      .trim();
  }
  // Índice (exclusivo) del último final de oración completo de `texto` a partir de `desde`; `desde` si no hay.
  function ultimoCorte(texto, desde) {
    const re = /[.!?…]+["')\]]?(?=\s)|\n/g;
    re.lastIndex = desde;
    let corte = desde, m;
    while ((m = re.exec(texto))) corte = m.index + m[0].length;
    return corte;
  }
  // Voz por nombre; si no, la del idioma pedido; si no, es-ES; si no, cualquiera en español.
  function elegirVoz(voces, idioma, nombre) {
    if (nombre) { const v = voces.find((x) => x.name === nombre); if (v) return v; }
    const norm = (l) => String(l || "").replace("_", "-").toLowerCase();
    const pedido = norm(idioma), base = pedido.slice(0, 2);
    const es = voces.filter((v) => norm(v.lang).startsWith(base));
    return es.find((v) => norm(v.lang) === pedido) || es.find((v) => norm(v.lang) === "es-es") || es[0] || null;
  }

  // ───────────────────────── Markdown → nodos DOM (sin innerHTML) ─────────────────────────

  function urlSegura(href) {
    try {
      const u = new URL(href, location.href);
      return ["http:", "https:", "mailto:"].includes(u.protocol) ? u.href : null;
    } catch { return null; }
  }

  const INLINE = /(`[^`\n]+`)|(\*\*[^*\n]+\*\*)|(__[^_\n]+__)|(\*[^*\s][^*\n]*\*)|(\[[^\]\n]+\]\([^)\s]+\))/;

  function inline(texto, padre) {
    while (texto) {
      const m = INLINE.exec(texto);
      if (!m) { padre.append(texto); return; }
      if (m.index) padre.append(texto.slice(0, m.index));
      const t = m[0];
      if (m[1]) {
        const el = document.createElement("code"); el.textContent = t.slice(1, -1); padre.append(el);
      } else if (m[2] || m[3]) {
        const el = document.createElement("strong"); inline(t.slice(2, -2), el); padre.append(el);
      } else if (m[4]) {
        const el = document.createElement("em"); inline(t.slice(1, -1), el); padre.append(el);
      } else {
        const [, etiqueta, href] = /^\[([^\]]+)\]\(([^)]+)\)$/.exec(t);
        const seguro = urlSegura(href);
        if (seguro) {
          const a = document.createElement("a");
          a.href = seguro; a.target = "_blank"; a.rel = "noopener noreferrer nofollow";
          a.textContent = etiqueta; padre.append(a);
        } else padre.append(etiqueta);
      }
      texto = texto.slice(m.index + t.length);
    }
  }

  function celdas(linea) {
    return linea.trim().replace(/^\||\|$/g, "").split("|").map((c) => c.trim());
  }

  function markdown(fuente, destino) {
    const lineas = fuente.replace(/\r\n?/g, "\n").split("\n");
    let i = 0;
    while (i < lineas.length) {
      const l = lineas[i];
      if (!l.trim()) { i++; continue; }

      if (/^```/.test(l)) {
        const buf = []; i++;
        while (i < lineas.length && !/^```/.test(lineas[i])) buf.push(lineas[i++]);
        i++;
        const pre = document.createElement("pre"), code = document.createElement("code");
        code.textContent = buf.join("\n"); pre.append(code); destino.append(pre);
        continue;
      }
      const h = /^(#{1,4})\s+(.*)$/.exec(l);
      if (h) {
        const el = document.createElement("h" + Math.min(h[1].length + 2, 6));
        inline(h[2], el); destino.append(el); i++; continue;
      }
      if (/^\s*([-*+]|\d+[.)])\s+/.test(l)) {
        const ordenada = /^\s*\d/.test(l);
        const lista = document.createElement(ordenada ? "ol" : "ul");
        while (i < lineas.length && /^\s*([-*+]|\d+[.)])\s+/.test(lineas[i])) {
          const li = document.createElement("li");
          inline(lineas[i].replace(/^\s*([-*+]|\d+[.)])\s+/, ""), li); lista.append(li); i++;
        }
        destino.append(lista); continue;
      }
      if (/^\s*\|.*\|\s*$/.test(l) && i + 1 < lineas.length && /^\s*\|?[\s:|-]+\|[\s:|-]*$/.test(lineas[i + 1])) {
        const tabla = document.createElement("table");
        const cab = document.createElement("tr");
        celdas(l).forEach((c) => { const th = document.createElement("th"); inline(c, th); cab.append(th); });
        const thead = document.createElement("thead"); thead.append(cab); tabla.append(thead);
        const tbody = document.createElement("tbody"); i += 2;
        while (i < lineas.length && /^\s*\|.*\|\s*$/.test(lineas[i])) {
          const tr = document.createElement("tr");
          celdas(lineas[i]).forEach((c) => { const td = document.createElement("td"); inline(c, td); tr.append(td); });
          tbody.append(tr); i++;
        }
        tabla.append(tbody);
        const caja = document.createElement("div"); caja.className = "tabla"; caja.append(tabla);
        destino.append(caja); continue;
      }
      const p = document.createElement("p"), buf = [];
      while (i < lineas.length && lineas[i].trim() && !/^(```|#{1,4}\s|\s*([-*+]|\d+[.)])\s+)/.test(lineas[i])) {
        buf.push(lineas[i++]);
      }
      buf.forEach((t, k) => { if (k) p.append(document.createElement("br")); inline(t, p); });
      destino.append(p);
    }
  }

  // ───────────────────────── Estilos ─────────────────────────

  const CSS = `
    :host { display: block; height: 100%; min-height: 360px; }
    * { box-sizing: border-box; }
    .raiz {
      --c: var(--asistente-color, #2f6f3e);
      --ct: var(--asistente-color-texto, #fff);
      --f: var(--asistente-fondo, #fff);
      --t: var(--asistente-texto, #1d2420);
      --b: var(--asistente-borde, #d9ded9);
      --suave: color-mix(in srgb, var(--t) 6%, var(--f));
      --apagado: color-mix(in srgb, var(--t) 58%, var(--f));
      --r: var(--asistente-radio, 12px);
      display: flex; width: 100%; height: 100%; position: relative; overflow: hidden;
      background: var(--f); color: var(--t);
      font: 15px/1.55 var(--asistente-fuente, system-ui, -apple-system, "Segoe UI", sans-serif);
    }
    [hidden] { display: none !important; }
    button { font: inherit; color: inherit; }
    button:focus-visible, a:focus-visible { outline: 2px solid var(--c); outline-offset: 1px; }

    .lateral {
      width: var(--asistente-ancho-lateral, 260px); flex: none; display: flex; flex-direction: column;
      background: var(--suave); border-right: 1px solid var(--b);
    }
    .lateral-cab { padding: 12px; }
    button.nueva {
      width: 100%; display: flex; align-items: center; gap: 8px; padding: 9px 12px; cursor: pointer;
      border: 1px solid var(--b); background: var(--f); border-radius: var(--r); font-weight: 600;
    }
    button.nueva:hover { border-color: var(--c); }
    button.nueva svg { width: 18px; height: 18px; flex: none; }
    .lista-titulo { padding: 8px 16px 4px; font-size: 11px; letter-spacing: .06em; text-transform: uppercase; color: var(--apagado); }
    .lista { list-style: none; margin: 0; padding: 4px 8px 12px; overflow-y: auto; flex: 1; }
    .lista li { display: flex; align-items: center; border-radius: 8px; }
    .lista li:hover, .lista li.activa { background: color-mix(in srgb, var(--t) 9%, var(--f)); }
    .lista li.activa .abrir { font-weight: 600; }
    .lista .abrir {
      flex: 1; min-width: 0; text-align: left; background: none; border: 0; padding: 9px 10px;
      cursor: pointer; overflow: hidden; text-overflow: ellipsis; white-space: nowrap;
    }
    .lista .borrar {
      background: none; border: 0; cursor: pointer; color: var(--apagado); padding: 6px; margin-right: 4px;
      border-radius: 6px; display: grid; place-items: center; opacity: 0;
    }
    .lista li:hover .borrar, .lista li:focus-within .borrar, .lista li.activa .borrar { opacity: 1; }
    .lista .borrar:hover { color: #8a1f1f; }
    .lista .borrar svg { width: 16px; height: 16px; }
    .lista .vacio-hist { display: block; padding: 10px; color: var(--apagado); font-size: 13px; }

    .principal { flex: 1; min-width: 0; display: flex; flex-direction: column; }
    .barra { display: flex; align-items: center; gap: 8px; padding: 10px 16px; border-bottom: 1px solid var(--b); }
    .barra h1 { flex: 1; margin: 0; font-size: 15px; font-weight: 600; overflow: hidden; text-overflow: ellipsis; white-space: nowrap; }
    .barra .menu, .barra .accion, .barra .altavoz { background: none; border: 0; padding: 6px; border-radius: 6px; cursor: pointer; display: grid; place-items: center; }
    .barra .menu { display: none; }
    .barra .menu:hover, .barra .accion:hover, .barra .altavoz:hover { background: var(--suave); }
    .barra svg { width: 20px; height: 20px; }
    .barra .altavoz.activa { color: var(--c); }
    .barra .altavoz[hidden] { display: none; }
    .barra .manos { display: flex; align-items: center; gap: 6px; background: none; border: 1px solid var(--b); border-radius: 999px; padding: 4px 12px 4px 8px; font: inherit; font-size: 13px; color: inherit; cursor: pointer; }
    .barra .manos:hover { background: var(--suave); }
    .barra .manos[aria-pressed="true"] { background: var(--c); border-color: var(--c); color: var(--ct); }
    .barra .manos[hidden] { display: none; }
    .barra .manos svg { width: 16px; height: 16px; }
    .mh { max-width: var(--asistente-ancho-columna, 760px); margin: 0 auto 8px; padding: 8px 12px; border: 1px solid var(--c); border-radius: var(--r); display: flex; flex-wrap: wrap; align-items: center; gap: 8px; font-size: 13px; }
    .mh[hidden] { display: none; }
    .mh-punto { flex: none; width: 10px; height: 10px; border-radius: 50%; background: #c0392b; }
    .mh-estado { font-weight: 600; }
    .mh-parcial { flex: 1 1 120px; min-width: 0; color: var(--apagado); overflow: hidden; text-overflow: ellipsis; white-space: nowrap; }
    .mh button { border: 1px solid var(--b); background: var(--f); color: inherit; border-radius: 999px; padding: 3px 12px; font: inherit; cursor: pointer; }
    .mh button:hover { border-color: var(--c); color: var(--c); }
    .mh .mh-enviar { background: var(--c); border-color: var(--c); color: var(--ct); }
    .mh .mh-enviar:hover { color: var(--ct); opacity: .9; }
    .mh button[hidden] { display: none; }
    .mh-priv { flex-basis: 100%; font-size: 11px; color: var(--apagado); }
    @media (prefers-reduced-motion: no-preference) { .mh.escuchando .mh-punto { animation: pulso 1.2s infinite; } }
    .voz-acciones { margin-top: 6px; }
    .escuchar { width: 28px; height: 28px; border: 1px solid var(--b); border-radius: 50%; background: transparent; color: var(--apagado); cursor: pointer; display: inline-grid; place-items: center; padding: 0; }
    .escuchar:hover, .escuchar.hablando { color: var(--c); border-color: var(--c); }
    .escuchar svg { width: 14px; height: 14px; }

    .scroll { flex: 1; overflow-y: auto; }
    .columna {
      max-width: var(--asistente-ancho-columna, 760px); margin: 0 auto; padding: 24px 16px;
      display: flex; flex-direction: column; gap: 20px;
    }
    .scroll.vacio { display: flex; }
    .scroll.vacio .columna { flex: 1; width: 100%; justify-content: center; }
    .bienvenida h2 { margin: 0; text-align: center; font-size: 26px; font-weight: 600; }

    .msg { overflow-wrap: anywhere; }
    .msg.user { align-self: flex-end; max-width: 85%; padding: 8px 14px; background: var(--suave); border-radius: calc(var(--r) * 1.5); white-space: pre-wrap; }
    .msg.assistant { align-self: stretch; }
    .msg.error { align-self: stretch; padding: 8px 12px; background: #fdecec; color: #8a1f1f; border-radius: var(--r); }
    .msg > :first-child { margin-top: 0; } .msg > :last-child { margin-bottom: 0; }
    .msg p, .msg ul, .msg ol, .msg pre, .msg h3, .msg h4, .msg h5, .msg h6 { margin: 0 0 10px; }
    .msg h3, .msg h4, .msg h5, .msg h6 { font-size: 16px; }
    .msg ul, .msg ol { padding-left: 22px; }
    .msg code { font-family: ui-monospace, monospace; font-size: 13px; background: rgba(0,0,0,.07); padding: 1px 5px; border-radius: 4px; }
    .msg pre { background: rgba(0,0,0,.07); padding: 10px; border-radius: 8px; overflow-x: auto; }
    .msg pre code { background: none; padding: 0; }
    .msg a { color: var(--c); text-decoration: underline; }
    .tabla { overflow-x: auto; margin-bottom: 10px; }
    .msg table { border-collapse: collapse; font-size: 14px; }
    .msg th, .msg td { border: 1px solid var(--b); padding: 4px 10px; text-align: left; }
    .msg th { background: var(--suave); }
    .estado { font-size: 13px; color: var(--apagado); font-style: italic; }
    .acciones { display: flex; flex-wrap: wrap; gap: 6px; margin-top: 10px; }
    .msg .acciones a {
      display: inline-block; padding: 4px 12px; border: 1px solid var(--c); color: var(--c);
      border-radius: 999px; text-decoration: none; font-size: 13px; background: var(--f);
    }
    .msg .acciones a:hover { background: var(--c); color: var(--ct); }

    .msg.confirmacion { align-self: stretch; padding: 12px 14px; border: 1px solid var(--c); border-radius: calc(var(--r) * 1.5); background: var(--f); }
    .msg.confirmacion.cerrada { border-color: var(--b); opacity: .85; }
    .accion-titulo { font-size: 12px; text-transform: uppercase; letter-spacing: .04em; color: var(--apagado); margin-bottom: 4px; }
    .accion-resumen { font-weight: 600; }
    .msg.confirmacion ul { margin: 6px 0 0; padding-left: 20px; font-size: 14px; }
    .accion-botones { display: flex; gap: 8px; margin-top: 10px; }
    .accion-botones button { padding: 6px 16px; border-radius: 999px; border: 1px solid var(--c); background: var(--f); color: var(--c); font: inherit; cursor: pointer; }
    .accion-botones button.primario { background: var(--c); color: var(--ct); }
    .accion-botones button:disabled { opacity: .45; cursor: default; }
    .accion-botones[hidden] { display: none; }
    .accion-estado { margin-top: 8px; font-size: 13px; color: var(--apagado); }
    .accion-estado.ok { color: #1f6b3a; }
    .accion-error { margin-top: 6px; font-size: 13px; color: #8a1f1f; }
    .accion-error:empty { display: none; }

    .entrada { padding: 0 16px 8px; }
    .entrada form {
      max-width: var(--asistente-ancho-columna, 760px); margin: 0 auto; display: flex; align-items: flex-end; gap: 8px;
      padding: 8px 8px 8px 16px; background: var(--f); border: 1px solid var(--b); border-radius: calc(var(--r) * 1.8);
    }
    .entrada form:focus-within { border-color: var(--c); }
    textarea { flex: 1; resize: none; border: 0; outline: 0; background: transparent; font: inherit; color: inherit; max-height: 200px; padding: 6px 0; }
    form button {
      flex: none; width: 36px; height: 36px; border: 0; border-radius: 50%; display: grid; place-items: center;
      background: var(--c); color: var(--ct); cursor: pointer;
    }
    form button:disabled { opacity: .4; cursor: default; }
    form button.mic { background: transparent; color: var(--apagado); border: 1px solid var(--b); }
    form button.mic:hover:not(:disabled) { color: var(--c); border-color: var(--c); }
    form button.mic.grabando { background: #c0392b; border-color: #c0392b; color: #fff; }
    form button.mic[hidden] { display: none; }
    .aviso-voz { font-size: 12px; color: var(--apagado); text-align: center; padding-top: 4px; min-height: 16px; }
    .aviso-voz:empty { display: none; }
    .aviso-voz.err { color: #8a1f1f; }
    @media (prefers-reduced-motion: no-preference) { form button.mic.grabando { animation: pulso 1.2s infinite; } }
    @keyframes pulso { 50% { opacity: .6; } }
    form button svg { width: 18px; height: 18px; }
    .pie { padding-top: 6px; font-size: 11px; color: var(--apagado); text-align: center; }

    .velo, .aviso { display: none; }
    .sin-acceso .lateral, .sin-acceso .principal { display: none; }
    .sin-acceso .aviso { display: grid; flex: 1; place-items: center; padding: 24px; text-align: center; color: var(--apagado); }

    @media (max-width: 720px) {
      .lateral { position: absolute; inset: 0 auto 0 0; z-index: 3; width: min(300px, 85%); transform: translateX(-100%); }
      .menu-abierto .lateral { transform: none; box-shadow: 0 0 30px rgba(0,0,0,.3); }
      .menu-abierto .velo { display: block; position: absolute; inset: 0; z-index: 2; background: rgba(0,0,0,.4); }
      .barra .menu { display: grid; }
      .bienvenida h2 { font-size: 22px; }
    }
    @media (prefers-reduced-motion: no-preference) { .lateral { transition: transform .2s; } }
  `;

  const ICONO = {
    nuevo: "M12 5v14M5 12h14",
    menu: "M4 6h16M4 12h16M4 18h16",
    x: "M6 6l12 12M18 6L6 18",
    enviar: "M12 19V5M5 12l7-7 7 7",
    mic: "M12 3a3 3 0 0 0-3 3v6a3 3 0 0 0 6 0V6a3 3 0 0 0-3-3zM19 11a7 7 0 0 1-14 0M12 18v3",
    parar: "M7 7h10v10H7z",
    manos: "M12 3a3 3 0 0 0-3 3v6a3 3 0 0 0 6 0V6a3 3 0 0 0-3-3zM5 11a7 7 0 0 0 14 0M12 18v3M2 9v4M22 9v4",
    altavoz: "M11 5L6 9H2v6h4l5 4V5zM15.5 8.5a5 5 0 0 1 0 7M19 5a9 9 0 0 1 0 14",
  };
  function icono(nombre) {
    const ns = "http://www.w3.org/2000/svg";
    const svg = document.createElementNS(ns, "svg");
    svg.setAttribute("viewBox", "0 0 24 24"); svg.setAttribute("fill", "none");
    svg.setAttribute("stroke", "currentColor"); svg.setAttribute("stroke-width", "2");
    svg.setAttribute("stroke-linecap", "round"); svg.setAttribute("stroke-linejoin", "round");
    svg.setAttribute("aria-hidden", "true");
    const p = document.createElementNS(ns, "path"); p.setAttribute("d", ICONO[nombre]); svg.append(p);
    return svg;
  }

  function el(tag, props = {}, ...hijos) {
    const e = document.createElement(tag);
    for (const [k, v] of Object.entries(props)) {
      if (k === "class") e.className = v; else if (k in e) e[k] = v; else e.setAttribute(k, v);
    }
    e.append(...hijos);
    return e;
  }

  // ───────────────────────── Componente ─────────────────────────

  class AsistenteChat extends HTMLElement {
    static get observedAttributes() { return ["token-url", "servidor"]; }
    static get _utiles() { return { textoParaVoz, ultimoCorte, elegirVoz, normalizarFrase, buscarActivacion, comandoDe, interpretar, retrasoReinicio }; }  // para los tests

    constructor() {
      super();
      this._token = null;        // {valor, expiraMs}; solo en memoria, nunca en storage
      this._convId = null;
      this._ocupado = false;
      this._abort = null;
      this._iniciado = false;
      this._nombreSistema = "";
      this._dictadoServidor = false;
      this._reco = null;
      this._leerAuto = false;
      this._leidoHasta = 0;
      this._pendientesVoz = 0;   // frases encoladas en speechSynthesis que aún no terminaron
      this._genVoz = 0;          // cambia al cortar la voz: ignora los eventos de lo cancelado
      this._leerCortado = false; // el usuario interrumpió la lectura de este turno (manos libres)
      // modo manos libres: estado y recursos (ver _mh* más abajo)
      this._mh = { estado: "apagado", reco: null, fallos: 0, ultimoError: "", siguiente: 0, idxActivacion: -1, tCierre: null, tInact: null, tReinicio: null };
      this.attachShadow({ mode: "open" });
    }

    get _servidor() {
      return (this.getAttribute("servidor") || ORIGEN_SCRIPT || location.origin).replace(/\/+$/, "");
    }

    connectedCallback() {
      this._construir();
      this._arrancar();
    }

    disconnectedCallback() {
      if (this._abort) this._abort.abort();
      this._detenerGrabacion(true);
      this._detenerReco(true);
      this._mhApagar("", true);
      this._pararVoz();
    }

    attributeChangedCallback(nombre, viejo, nuevo) {
      if (this.isConnected && this._iniciado && viejo !== nuevo) {
        this._token = null; this._iniciado = false; this._arrancar();
      }
    }

    // — UI —
    _construir() {
      if (this._raiz) return;
      const r = this._raiz = el("div", { class: "raiz", hidden: true });
      this.shadowRoot.append(el("style", { textContent: CSS }), r);

      // barra lateral: nueva conversación + historial
      const nueva = el("button", { class: "nueva", type: "button" }, icono("nuevo"), el("span", { textContent: TEXTOS.nueva }));
      nueva.addEventListener("click", () => this._nueva());
      this._lista = el("ul", { class: "lista" });
      const lateral = el("aside", { class: "lateral", "aria-label": TEXTOS.historial },
        el("div", { class: "lateral-cab" }, nueva),
        el("div", { class: "lista-titulo", textContent: TEXTOS.historial }), this._lista);
      const velo = el("div", { class: "velo" });
      velo.addEventListener("click", () => this._menu(false));

      // columna principal: barra, mensajes, entrada
      this._titulo = el("h1", { textContent: this.getAttribute("titulo") || "Asistente" });
      const menu = el("button", { class: "menu", type: "button", title: TEXTOS.historial, "aria-label": TEXTOS.historial }, icono("menu"));
      menu.addEventListener("click", () => this._menu());
      const otra = el("button", { class: "accion", type: "button", title: TEXTOS.nueva, "aria-label": TEXTOS.nueva }, icono("nuevo"));
      otra.addEventListener("click", () => this._nueva());
      // lectura automática de las respuestas: visible solo si el navegador tiene síntesis de voz
      this._altavoz = el("button", { class: "altavoz", type: "button", hidden: true }, icono("altavoz"));
      this._altavoz.addEventListener("click", () => this._conmutarLeerAuto());
      try { this._leerAuto = sessionStorage.getItem(CLAVE_LEER) === "1"; } catch { /* sin storage */ }
      this._pintarAltavoz();
      // manos libres: oculto hasta saber que el navegador puede (ver _actualizarVoz)
      this._manos = el("button", { class: "manos", type: "button", hidden: true, "aria-pressed": "false" }, icono("manos"), el("span", { textContent: TEXTOS.manosLibres }));
      this._manos.addEventListener("click", () => this._conmutarManosLibres());
      const barra = el("header", { class: "barra" }, ...(MOSTRAR_HISTORIAL ? [menu, this._titulo] : [this._titulo, this._manos, this._altavoz, otra]));

      this._mensajes = el("div", { class: "columna", role: "log", "aria-live": "polite" });
      this._scroll = el("div", { class: "scroll" }, this._mensajes);

      this._entrada = el("textarea", {
        rows: 1, placeholder: this.getAttribute("placeholder") || TEXTOS.escribir,
        "aria-label": TEXTOS.escribir, maxLength: 4000,
      });
      this._entrada.addEventListener("keydown", (e) => {
        if (e.key === "Enter" && !e.shiftKey && !e.isComposing) { e.preventDefault(); this._enviarForm(); }
      });
      this._entrada.addEventListener("input", () => {
        this._entrada.style.height = "auto";
        this._entrada.style.height = Math.min(this._entrada.scrollHeight, 200) + "px";
      });
      this._enviar = el("button", { type: "submit", title: TEXTOS.enviar, "aria-label": TEXTOS.enviar }, icono("enviar"));
      // dictado: oculto hasta que /v1/estado lo habilite (voz.dictado)
      this._mic = el("button", { type: "button", class: "mic", hidden: true, title: TEXTOS.dictar, "aria-label": TEXTOS.dictar }, icono("mic"));
      this._mic.addEventListener("click", () => this._conmutarDictado());
      this._avisoVoz = el("div", { class: "aviso-voz", role: "status" });
      const form = el("form", {}, this._entrada, this._mic, this._enviar);
      form.addEventListener("submit", (e) => { e.preventDefault(); this._enviarForm(); });
      // indicador de manos libres: visible siempre que el micrófono esté abierto, con el botón de apagar
      this._mhPunto = el("span", { class: "mh-punto", "aria-hidden": "true" });
      this._mhEtiqueta = el("span", { class: "mh-estado", role: "status", "aria-live": "polite" });
      this._mhParcial = el("span", { class: "mh-parcial" });
      this._mhEnviar = el("button", { type: "button", class: "mh-enviar", textContent: TEXTOS.enviar });
      this._mhCancelar = el("button", { type: "button", class: "mh-cancelar", textContent: TEXTOS.cancelar });
      this._mhApagarBtn = el("button", { type: "button", class: "mh-apagar", textContent: TEXTOS.apagarManosLibres });
      this._mhEnviar.addEventListener("click", () => this._mhEnviarTexto());
      this._mhCancelar.addEventListener("click", () => this._mhDescartar());
      this._mhApagarBtn.addEventListener("click", () => this._mhApagar(""));
      this._mhCaja = el("div", { class: "mh", hidden: true }, this._mhPunto, this._mhEtiqueta, this._mhParcial,
        this._mhEnviar, this._mhCancelar, this._mhApagarBtn, el("div", { class: "mh-priv", textContent: TEXTOS.mhPrivacidad }));
      this.addEventListener("keydown", (e) => { if (e.key === "Escape" && this._mhActivo()) this._mhApagar(""); });
      const principal = el("main", { class: "principal" }, barra, this._scroll,
        el("div", { class: "entrada" }, this._mhCaja, form, this._avisoVoz, el("div", { class: "pie", textContent: TEXTOS.pie })));

      this._aviso = el("div", { class: "aviso", textContent: TEXTOS.noDisponible });
      r.append(...(MOSTRAR_HISTORIAL ? [lateral, velo] : []), principal, this._aviso);
      this._mostrarBienvenida();
    }

    _menu(abrir) {
      this._raiz.classList.toggle("menu-abierto", abrir === undefined ? !this._raiz.classList.contains("menu-abierto") : abrir);
    }

    _mostrarBienvenida() {
      this._mensajes.replaceChildren(el("div", { class: "bienvenida" }, el("h2", { textContent: TEXTOS.bienvenida })));
      this._scroll.classList.add("vacio");
    }

    _burbuja(rol) {
      const b = el("div", { class: "msg " + rol });
      const bienvenida = this._mensajes.querySelector(".bienvenida");
      if (bienvenida) bienvenida.remove();
      this._scroll.classList.remove("vacio");
      this._mensajes.append(b); this._bajar(); return b;
    }

    _bajar() { this._scroll.scrollTop = this._scroll.scrollHeight; }

    _error(codigo) {
      const b = this._burbuja("error");
      b.textContent = ERRORES[codigo] || ERROR_GENERICO;
    }

    // — arranque: token + estado —
    async _arrancar() {
      this._iniciado = true;
      if (!this.getAttribute("token-url")) {
        console.error("<asistente-chat>: falta el atributo token-url");
        return;
      }
      let habilitado = false;
      try {
        await this._asegurarToken();
        const r = await fetch(this._servidor + "/v1/estado", { headers: this._auth() });
        if (r.ok) {
          const e = await r.json();
          habilitado = e.habilitado !== false;
          this._nombreSistema = e.nombre_sistema || "";
          const voz = e.voz || {};
          this._maxAudioS = Number(voz.max_audio_s) > 0 ? Number(voz.max_audio_s) : 60;
          this._dictadoServidor = voz.dictado === true && puedeGrabar();
          if (!this.getAttribute("titulo") && this._nombreSistema) this._titulo.textContent = "Asistente · " + this._nombreSistema;
        }
      } catch { /* sin acceso: se muestra el aviso */ }
      this._actualizarVoz();
      this._raiz.classList.toggle("sin-acceso", !habilitado);
      this._raiz.hidden = false;
      if (habilitado) { this._cargarHistorial(); this._entrada.focus(); this._restaurar(); }
      this.dispatchEvent(new CustomEvent("asistente:estado", { detail: { habilitado }, bubbles: true, composed: true }));
    }

    _auth() { return { Authorization: "Bearer " + this._token.valor }; }

    async _asegurarToken(forzar = false) {
      const t = this._token;
      if (!forzar && t && t.expiraMs - Date.now() > MARGEN_RENOVAR_MS) return;
      if (this._renovando) return this._renovando;
      this._renovando = (async () => {
        try {
          const r = await fetch(this.getAttribute("token-url"), { credentials: "same-origin", headers: { Accept: "application/json" } });
          if (!r.ok) throw new Error("token-url " + r.status);
          const d = await r.json();
          const expiraMs = Date.parse(d.expira);
          if (!d.token || Number.isNaN(expiraMs)) throw new Error("respuesta de token inválida");
          this._token = { valor: d.token, expiraMs };
        } finally { this._renovando = null; }
      })();
      return this._renovando;
    }

    // Ejecuta `fn` con token vigente; si el asistente responde 401 por token, renueva y reintenta una vez.
    async _conToken(fn) {
      await this._asegurarToken();
      let r = await fn(this._auth());
      if (r.status === 401) {
        await this._asegurarToken(true);
        r = await fn(this._auth());
      }
      return r;
    }

    // — conversaciones (barra lateral) —
    // Recordar/olvidar la conversación actual entre recargas. Nunca guarda el token.
    _recordar() {
      try {
        const clave = CLAVE_CONV + this._servidor;
        if (this._convId) sessionStorage.setItem(clave, this._convId); else sessionStorage.removeItem(clave);
      } catch { /* storage no disponible: se pierde solo la continuidad */ }
    }

    async _restaurar() {
      let id = null;
      try { id = sessionStorage.getItem(CLAVE_CONV + this._servidor); } catch { /* sin storage */ }
      if (id) await this._abrir(id, true);
    }

    // "Nueva conversación" no borra la anterior: solo deja de mostrarla (sigue en el servidor,
    // sujeta a la retención del sistema).
    _nueva() {
      if (this._ocupado) return;
      this._convId = null; this._recordar(); this._mostrarBienvenida(); this._pintarHistorial();
      this._menu(false); this._entrada.focus();
    }

    async _cargarHistorial() {
      if (!MOSTRAR_HISTORIAL) return;
      try {
        const r = await this._conToken((h) => fetch(this._servidor + "/v1/conversaciones", { headers: h }));
        if (!r.ok) throw new Error(r.status);
        this._convs = await r.json();
      } catch { this._convs = null; }
      this._pintarHistorial();
    }

    _pintarHistorial() {
      if (!MOSTRAR_HISTORIAL) return;
      const aviso = (texto) => el("li", {}, el("span", { class: "vacio-hist", textContent: texto }));
      if (this._convs === null) return this._lista.replaceChildren(aviso(ERROR_GENERICO));
      if (!this._convs.length) return this._lista.replaceChildren(aviso(TEXTOS.sinHistorial));
      this._lista.replaceChildren(...this._convs.map((c) => this._itemHistorial(c)));
    }

    _itemHistorial(c) {
      const abrir = el("button", { class: "abrir", type: "button", title: c.titulo || "", textContent: c.titulo || "(sin título)" });
      abrir.addEventListener("click", () => this._abrir(c.id));
      const borrar = el("button", { class: "borrar", type: "button", title: TEXTOS.borrar, "aria-label": TEXTOS.borrar }, icono("x"));
      borrar.addEventListener("click", async () => {
        if (!window.confirm(TEXTOS.confirmarBorrar)) return;
        try {
          const r = await this._conToken((h) => fetch(`${this._servidor}/v1/conversaciones/${c.id}`, { method: "DELETE", headers: h }));
          if (!r.ok && r.status !== 404) return;
        } catch { return; }
        this._convs = this._convs.filter((x) => x.id !== c.id);
        if (this._convId === c.id && !this._ocupado) this._nueva(); else this._pintarHistorial();
      });
      return el("li", { class: c.id === this._convId ? "activa" : "" }, abrir, borrar);
    }

    // `silencioso`: al restaurar al arrancar, si falla (borrada, de otro usuario) se empieza vacío sin error.
    async _abrir(id, silencioso = false) {
      if (this._ocupado) return;
      try {
        const r = await this._conToken((h) => fetch(`${this._servidor}/v1/conversaciones/${id}`, { headers: h }));
        if (!r.ok) throw new Error(r.status);
        const d = await r.json();
        this._convId = id; this._mensajes.replaceChildren(); this._mostrarBienvenida();
        for (const m of d.mensajes) {
          const b = this._burbuja(m.rol);
          if (m.rol === "assistant") { markdown(m.texto, b); this._botonEscuchar(b, m.texto); } else b.textContent = m.texto;
        }
        // Una propuesta que sigue vigente vuelve a mostrarse con su cuenta regresiva (el servidor es la fuente).
        if (d.pendiente) this._confirmacion(d.pendiente);
        this._recordar(); this._pintarHistorial(); this._menu(false); this._bajar();
      } catch {
        if (silencioso) { this._convId = null; this._recordar(); } else this._error();
      }
    }

    // — dictado: graba, transcribe y rellena el campo (sin enviar) —
    _conmutarDictado() {
      this._pararVoz();                                   // al dictar, el asistente se calla
      if (this._reco) { this._detenerReco(false); return; }
      if (this._grabador) { this._detenerGrabacion(false); return; }
      if (this._motorDictado() === "navegador") this._iniciarReco(); else this._iniciarGrabacion();
    }

    // "navegador" | "servidor" | null según el atributo voz-motor y lo disponible.
    _motorDictado() {
      const pref = (this.getAttribute("voz-motor") || "auto").toLowerCase();
      const navegador = !!reconocimiento(), servidor = this._dictadoServidor;
      if (pref === "servidor") return servidor ? "servidor" : null;
      if (pref === "navegador") return navegador ? "navegador" : null;
      return navegador ? "navegador" : (servidor ? "servidor" : null);
    }

    _actualizarVoz() {
      this._mic.hidden = !this._motorDictado();
      this._altavoz.hidden = !puedeHablar();
      // manos libres: solo con el reconocimiento del navegador (la palabra de activación no existe en el STT del servidor)
      this._manos.hidden = !(this._motorDictado() === "navegador" && puedeHablar() && window.isSecureContext !== false);
      if (this._manos.hidden) this._mhApagar("", true);
    }

    _marcarMic(grabando) {
      this._mic.classList.toggle("grabando", grabando);
      const t = grabando ? TEXTOS.detener : TEXTOS.dictar;
      this._mic.title = t; this._mic.setAttribute("aria-label", t);
      this._mic.replaceChildren(icono(grabando ? "parar" : "mic"));
    }

    _anadirAlCampo(texto) {
      const actual = this._entrada.value;
      this._entrada.value = (actual && !/\s$/.test(actual) ? actual + " " : actual) + texto;
      this._entrada.dispatchEvent(new Event("input"));
      this._entrada.focus();
    }

    // Dictado con el reconocimiento de voz del navegador (Web Speech): sin servidor ni grabación propia.
    _iniciarReco() {
      const SR = reconocimiento();
      if (!SR || this._ocupado) return;
      this._avisarVoz("");
      const r = new SR();
      r.lang = this.getAttribute("idioma") || "es-UY";
      r.interimResults = true; r.continuous = false; r.maxAlternatives = 1;
      let final = "", fallo = false;
      r.onstart = () => { this._marcarMic(true); this._avisarVoz(TEXTOS.escuchando); };
      r.onresult = (e) => {
        let parcial = "";
        for (let i = e.resultIndex; i < e.results.length; i++) {
          const res = e.results[i];
          if (res.isFinal) final += res[0].transcript; else parcial += res[0].transcript;
        }
        this._avisarVoz(parcial ? "… " + parcial : TEXTOS.escuchando);
      };
      r.onerror = (e) => {
        fallo = true;
        const codigo = { "not-allowed": "mic_denegado", "service-not-allowed": "mic_denegado", "audio-capture": "mic_no_disponible",
          "network": "reco_red", "no-speech": "sin_texto" }[e.error];
        if (e.error === "aborted") this._avisarVoz("");
        else this._avisarVoz(ERRORES_VOZ[codigo] || ERRORES_VOZ.reco_error, true);
      };
      r.onend = () => {
        if (this._reco === r) this._reco = null;
        this._marcarMic(false);
        if (fallo) return;
        const texto = final.trim();
        if (!texto) { this._avisarVoz(ERRORES_VOZ.sin_texto, true); return; }
        this._anadirAlCampo(texto);
        this._avisarVoz("");
      };
      this._reco = r;
      try { r.start(); }
      catch { this._reco = null; this._marcarMic(false); this._avisarVoz(ERRORES_VOZ.reco_error, true); }
    }

    _detenerReco(cancelar) {
      const r = this._reco;
      if (!r) return;
      try { cancelar ? r.abort() : r.stop(); } catch { /* ya terminó */ }
    }

    // — modo «manos libres» —
    // Un solo SpeechRecognition continuo atiende todos los estados (así no compite por el micrófono):
    //   apagado → armado (solo espera la palabra de activación) → capturando (dicta al campo) →
    //   confirmando («enviar» / «cancelar» o botones) → respondiendo → armado.
    _mhActivo() { return this._mh.estado !== "apagado"; }
    _palabra() { return (this.getAttribute("palabra-activacion") || PALABRA_ACTIVACION).trim() || PALABRA_ACTIVACION; }

    _conmutarManosLibres() {
      if (this._mhActivo()) { this._mhApagar(""); return; }
      if (!reconocimiento() || this._ocupado) return;
      this._detenerReco(true); this._detenerGrabacion(true);   // un solo micrófono a la vez
      this._pararVoz();
      this._avisarVoz("");
      this._mh.fallos = 0; this._mh.ultimoError = "";
      this._mhEstado("armado");
      this._mhIniciarReco();                                   // dentro del gesto del usuario (el navegador lo exige)
    }

    // `motivo`: "" (lo pidió el usuario), "voz", "inactividad" o un código de ERRORES_VOZ.
    _mhApagar(motivo, silencioso = false) {
      const mh = this._mh;
      if (!this._mhActivo()) return;
      clearTimeout(mh.tReinicio); mh.tReinicio = null;
      const r = mh.reco; mh.reco = null;
      if (r) { try { r.abort(); } catch { /* ya terminó */ } }
      this._leerCortado = true; this._pararVoz();
      this._mhEstado("apagado");
      if (silencioso) return;
      if (motivo === "inactividad") this._avisarVoz(TEXTOS.mhInactividad);
      else if (ERRORES_VOZ[motivo]) this._avisarVoz(ERRORES_VOZ[motivo], true);
      else this._avisarVoz("");
    }

    _mhEstado(nuevo) {
      const mh = this._mh;
      mh.estado = nuevo;
      if (nuevo !== "capturando") { clearTimeout(mh.tCierre); mh.tCierre = null; }
      this._mic.disabled = nuevo !== "apagado";
      this._mhPintar();
      this._mhActividad();
    }

    // Reinicia el temporizador de inactividad (se llama en cada cambio de estado o gesto del usuario).
    _mhActividad() {
      const mh = this._mh;
      clearTimeout(mh.tInact); mh.tInact = null;
      if (!this._mhActivo()) return;
      const min = Number(this.getAttribute("manos-libres-inactividad") ?? MH_INACTIVIDAD_MIN);
      if (!(min > 0)) return;
      mh.tInact = setTimeout(() => this._mhApagar("inactividad"), min * 60_000);
    }

    _mhPintar() {
      const mh = this._mh, e = mh.estado, activo = e !== "apagado";
      const p = this._palabra();
      this._mhCaja.hidden = !activo;
      this._mhCaja.classList.toggle("escuchando", activo);
      this._mhEtiqueta.textContent = ({
        armado: TEXTOS.mhArmado, capturando: TEXTOS.mhCapturando, confirmando: TEXTOS.mhConfirmando, respondiendo: TEXTOS.mhRespondiendo,
      }[e] || "").replace("{p}", p);
      this._mhParcial.textContent = "";
      this._mhEnviar.hidden = this._mhCancelar.hidden = !(e === "capturando" || e === "confirmando");
      this._manos.setAttribute("aria-pressed", String(activo));
      const t = activo ? TEXTOS.apagarManosLibres : TEXTOS.manosLibres;
      this._manos.title = t; this._manos.setAttribute("aria-label", t);
    }

    _mhIniciarReco() {
      const SR = reconocimiento(), mh = this._mh;
      if (!SR || !this._mhActivo() || mh.reco) return;
      const r = new SR();
      r.lang = this.getAttribute("idioma") || "es-UY";
      r.continuous = true; r.interimResults = true; r.maxAlternatives = 1;
      mh.siguiente = 0; mh.idxActivacion = -1;                 // los índices de resultados empiezan de cero en cada sesión
      r.onresult = (e) => { mh.fallos = 0; this._mhResultados(e); };
      r.onerror = (e) => {
        // «no-speech» y «aborted» son el ciclo normal (silencio, o lo cortamos nosotros): onend reinicia.
        if (e.error === "no-speech" || e.error === "aborted") return;
        if (e.error === "not-allowed" || e.error === "service-not-allowed") { this._mhApagar("mic_denegado"); return; }
        if (e.error === "audio-capture") { this._mhApagar("mic_no_disponible"); return; }
        mh.fallos++; mh.ultimoError = e.error === "network" ? "reco_red" : "reco_error";
      };
      // Chrome corta el reconocimiento continuo tras un rato de silencio o ~60 s: se reinicia mientras siga activo.
      r.onend = () => {
        if (mh.reco !== r) return;                             // lo reemplazamos o lo apagamos nosotros
        mh.reco = null;
        this._mhReprogramar();
      };
      mh.reco = r;
      try { r.start(); }
      catch { r.onend = null; mh.reco = null; mh.fallos++; mh.ultimoError = "reco_error"; this._mhReprogramar(); }
    }

    // Reinicia el reconocedor tras una pausa; si falló demasiadas veces seguidas, apaga el modo con el aviso del último error.
    _mhReprogramar() {
      const mh = this._mh;
      if (!this._mhActivo()) return;
      if (mh.fallos >= MH_MAX_FALLOS) { this._mhApagar(mh.ultimoError || "reco_error"); return; }
      clearTimeout(mh.tReinicio);
      mh.tReinicio = setTimeout(() => { mh.tReinicio = null; this._mhIniciarReco(); }, retrasoReinicio(mh.fallos));
    }

    _mhResultados(e) {
      const mh = this._mh;
      for (let i = e.resultIndex; i < e.results.length; i++) {
        const res = e.results[i], texto = String(res[0].transcript || "").trim();
        if (!texto) continue;
        if (res.isFinal) {
          if (i < mh.siguiente) continue;                      // ya procesado
          mh.siguiente = i + 1;
        }
        this._mhFrase(texto, res.isFinal, i);
      }
    }

    _mhFrase(texto, final, i) {
      const mh = this._mh;
      if (!this._mhActivo()) return;
      if ((mh.estado === "capturando" || mh.estado === "confirmando") && i < mh.idxActivacion) return;   // eco de lo anterior a la activación
      const a = interpretar(mh.estado, texto, this._palabra(), final);
      switch (a.accion) {
        case "apagar": this._mhApagar("voz"); break;
        case "activar": {
          this._leerCortado = true; this._pararVoz();          // hablarle al asistente corta su lectura
          this._avisarVoz("");
          mh.idxActivacion = i;
          this._mhEstado("capturando");
          this._mhTexto(a.resto, final);
          break;
        }
        case "enviar": this._mhEnviarTexto(); break;
        case "cancelar": this._mhDescartar(); break;
        case "texto": {
          if (mh.estado === "confirmando") this._mhEstado("capturando");   // sigue dictando: vuelve a capturar
          const resto = i === mh.idxActivacion ? buscarActivacion(texto, this._palabra()) : null;
          this._mhTexto(resto === null ? texto : resto, final);
          break;
        }
        default: break;
      }
    }

    // Parcial → indicador; final → campo de texto (sin enviar). Siempre rearma el cierre de la frase.
    _mhTexto(texto, final) {
      if (final && texto) { this._mhParcial.textContent = ""; this._anadirAlCampo(texto); }
      else this._mhParcial.textContent = texto ? "… " + texto : "";
      this._mhArmarCierre();
    }

    // Tras un silencio, lo dictado pasa a confirmación; si no se dijo nada, se vuelve a armado.
    _mhArmarCierre() {
      const mh = this._mh;
      clearTimeout(mh.tCierre);
      if (mh.estado !== "capturando") return;
      const vacio = !this._entrada.value.trim();
      mh.tCierre = setTimeout(() => {
        mh.tCierre = null;
        if (mh.estado !== "capturando") return;
        if (this._entrada.value.trim()) this._mhCerrarFrase();
        else { this._mhEstado("armado"); this._avisarVoz(ERRORES_VOZ.sin_texto, true); }
      }, vacio ? MH_ESPERA_MS : MH_CIERRE_MS);
    }

    _mhCerrarFrase() {
      this._mhEstado("confirmando");
      if (!MANOS_LIBRES_CONFIRMAR) this._mhEnviarTexto();
    }

    // Envía lo que hay en el campo (la confirmación: «enviar», el botón o, si se desactiva MANOS_LIBRES_CONFIRMAR, el cierre de la frase).
    _mhEnviarTexto() {
      if (!this._mhActivo() || !this._entrada.value.trim()) return;
      if (this._ocupado) { this._avisarVoz(TEXTOS.mhEsperar); return; }
      this._avisarVoz("");
      this._enviarForm();                                      // _enviarMensaje pasa el estado a «respondiendo»
    }

    _mhDescartar() {
      if (!this._mhActivo()) return;
      this._entrada.value = ""; this._entrada.dispatchEvent(new Event("input"));
      this._avisarVoz("");
      this._mhEstado("armado");
    }

    // Vuelve a armado cuando la respuesta terminó de llegar y de leerse.
    _mhRevisarFin() {
      if (this._mh.estado === "respondiendo" && !this._ocupado && this._pendientesVoz === 0) this._mhEstado("armado");
    }

    // — respuesta hablada (speechSynthesis) —
    _conmutarLeerAuto() {
      this._leerAuto = !this._leerAuto;
      try { sessionStorage.setItem(CLAVE_LEER, this._leerAuto ? "1" : "0"); } catch { /* sin storage */ }
      if (!this._leerAuto) this._pararVoz();
      this._pintarAltavoz();
    }

    _pintarAltavoz() {
      const t = this._leerAuto ? TEXTOS.noLeerAuto : TEXTOS.leerAuto;
      this._altavoz.title = t; this._altavoz.setAttribute("aria-label", t);
      this._altavoz.setAttribute("aria-pressed", String(this._leerAuto));
      this._altavoz.classList.toggle("activa", this._leerAuto);
    }

    // Encola `texto` (ya sin Markdown); varias llamadas se leen en orden. `alTerminar` al acabar esta pieza.
    _decir(texto, alTerminar) {
      if (!puedeHablar() || !texto.trim()) { if (alTerminar) alTerminar(); return; }
      const u = new window.SpeechSynthesisUtterance(texto);
      const idioma = this.getAttribute("idioma") || "es-UY";
      const v = elegirVoz(window.speechSynthesis.getVoices(), idioma, this.getAttribute("voz"));
      if (v) { u.voice = v; u.lang = v.lang; } else u.lang = idioma;
      const gen = this._genVoz;
      this._pendientesVoz++;
      const fin = () => {
        if (gen === this._genVoz) this._pendientesVoz = Math.max(0, this._pendientesVoz - 1);
        if (alTerminar) alTerminar();
        this._mhRevisarFin();
      };
      u.onend = fin; u.onerror = fin;
      window.speechSynthesis.speak(u);
    }

    _pararVoz() {
      this._genVoz++; this._pendientesVoz = 0;
      if (puedeHablar()) window.speechSynthesis.cancel();
      if (this._raiz) for (const b of this._raiz.querySelectorAll(".escuchar.hablando")) b.classList.remove("hablando");
    }

    // Lee lo que ya forma oraciones completas del texto acumulado (o todo, con `fin`): empieza a hablar antes de que termine la respuesta.
    _leerIncremental(md, fin) {
      const plano = textoParaVoz(md);
      const hasta = fin ? plano.length : ultimoCorte(plano, this._leidoHasta);
      if (hasta > this._leidoHasta) { this._decir(plano.slice(this._leidoHasta, hasta)); this._leidoHasta = hasta; }
    }

    // Botón "escuchar" al pie de una respuesta (solo texto: no altera el texto de la burbuja).
    _botonEscuchar(burbuja, md) {
      if (!puedeHablar() || !md.trim()) return;
      const boton = el("button", { type: "button", class: "escuchar", title: TEXTOS.escuchar, "aria-label": TEXTOS.escuchar }, icono("altavoz"));
      boton.addEventListener("click", () => {
        const hablando = boton.classList.contains("hablando");
        this._pararVoz();
        if (hablando) return;
        boton.classList.add("hablando");
        this._decir(textoParaVoz(md), () => boton.classList.remove("hablando"));
      });
      burbuja.append(el("div", { class: "voz-acciones" }, boton));
      this._bajar();   // el botón suma alto al final: se mantiene el final de la conversación a la vista
    }

    _avisarVoz(texto, esError = false) {
      this._avisoVoz.textContent = texto || "";
      this._avisoVoz.classList.toggle("err", esError);
    }

    async _iniciarGrabacion() {
      if (this._transcribiendo || this._ocupado) return;
      this._avisarVoz("");
      let flujo;
      try {
        flujo = await navigator.mediaDevices.getUserMedia({ audio: true });
      } catch (e) {
        const negado = e && (e.name === "NotAllowedError" || e.name === "SecurityError");
        this._avisarVoz(ERRORES_VOZ[negado ? "mic_denegado" : "mic_no_disponible"], true);
        return;
      }
      const tipo = TIPOS_GRABACION.find((t) => MediaRecorder.isTypeSupported(t));
      let grabador;
      try { grabador = new MediaRecorder(flujo, tipo ? { mimeType: tipo } : undefined); }
      catch { flujo.getTracks().forEach((t) => t.stop()); this._avisarVoz(ERRORES_VOZ.mic_no_disponible, true); return; }
      const trozos = [];
      const inicio = Date.now();
      let cancelada = false;
      grabador.addEventListener("dataavailable", (ev) => { if (ev.data && ev.data.size) trozos.push(ev.data); });
      grabador.addEventListener("stop", () => {
        flujo.getTracks().forEach((t) => t.stop());
        clearTimeout(this._tope);
        this._grabador = null;
        this._marcarMic(false);
        if (cancelada) { this._avisarVoz(""); return; }
        const blob = new Blob(trozos, { type: grabador.mimeType || tipo || "audio/webm" });
        this._transcribir(blob, (Date.now() - inicio) / 1000);
      });
      this._grabador = grabador;
      this._cancelarFn = () => { cancelada = true; };
      grabador.start();
      this._marcarMic(true);
      // Corta al llegar al tope del servidor (con un margen para que el header no lo supere).
      this._tope = setTimeout(() => this._detenerGrabacion(false), Math.max(1, this._maxAudioS - 1) * 1000);
    }

    _detenerGrabacion(cancelar) {
      const g = this._grabador;
      if (!g) return;
      if (cancelar && this._cancelarFn) this._cancelarFn();
      if (g.state !== "inactive") g.stop();
    }

    async _transcribir(blob, segundos) {
      if (!blob.size) { this._avisarVoz(ERRORES_VOZ.audio_invalido, true); return; }
      this._transcribiendo = true; this._mic.disabled = true;
      this._avisarVoz(TEXTOS.transcribiendo);
      try {
        const tipo = blob.type.split(";")[0] || "audio/webm";
        const r = await this._conToken((h) => fetch(`${this._servidor}/v1/voz/transcribir`, {
          method: "POST", body: blob,
          headers: { ...h, "Content-Type": blob.type || tipo, "X-Audio-Duracion-S": segundos.toFixed(1) },
        }));
        if (!r.ok) {
          let codigo = ""; try { codigo = (await r.json()).error; } catch { /* sin cuerpo */ }
          this._avisarVoz(ERRORES_VOZ[codigo] || ERROR_GENERICO, true);
          return;
        }
        const texto = String((await r.json()).texto ?? "").trim();
        if (!texto) { this._avisarVoz(ERRORES_VOZ.sin_texto, true); return; }
        this._anadirAlCampo(texto);
        this._avisarVoz("");
      } catch {
        this._avisarVoz(ERROR_GENERICO, true);
      } finally {
        this._transcribiendo = false; this._mic.disabled = false;
      }
    }

    // — chat —
    _enviarForm() {
      const texto = this._entrada.value.trim();
      if (!texto || this._ocupado) return;
      this._entrada.value = ""; this._entrada.style.height = "auto";
      this._enviarMensaje(texto);
    }

    _bloquear(si) {
      this._ocupado = si; this._enviar.disabled = si;
      this._raiz.setAttribute("aria-busy", String(si));
      if (!si) this._mhRevisarFin();
    }

    async _enviarMensaje(texto) {
      this._pararVoz();
      if (this._mhActivo()) this._mhEstado("respondiendo");   // también si se envió con Enter o el botón
      this._bloquear(true);
      this._burbuja("user").textContent = texto;
      const burbuja = this._burbuja("assistant");
      const estado = el("div", { class: "estado", textContent: TEXTOS.pensando });
      burbuja.append(estado);
      this._abort = new AbortController();
      try {
        let res = await this._turno(texto, burbuja, estado);
        if (res === "token_expirado") {  // el turno no se guardó: se renueva y se reintenta una vez
          await this._asegurarToken(true);
          estado.textContent = TEXTOS.pensando;
          res = await this._turno(texto, burbuja, estado);
        }
        if (res === "token_expirado") this._error("token_invalido");
      } catch (e) {
        if (e.name !== "AbortError") { burbuja.remove(); this._error(); }
      } finally {
        if (!burbuja.textContent.trim() && !burbuja.querySelector(".acciones")) burbuja.remove();
        this._bloquear(false); this._abort = null;
        this._cargarHistorial();  // el turno puede haber creado o retitulado la conversación
      }
    }

    // Devuelve "ok" | "token_expirado" | "error".
    async _turno(texto, burbuja, estado) {
      const cuerpo = JSON.stringify({ conversacion_id: this._convId, mensaje: texto });
      const r = await this._conToken((h) => fetch(this._servidor + "/v1/chat", {
        method: "POST", signal: this._abort.signal, body: cuerpo,
        headers: { ...h, "Content-Type": "application/json", Accept: "text/event-stream" },
      }));
      if (!r.ok) {
        let codigo = ""; try { codigo = (await r.json()).error; } catch { /* sin cuerpo */ }
        if (r.status === 401) return "token_expirado";
        burbuja.remove(); this._error(codigo); return "error";
      }
      let acumulado = "", resultado = "ok";
      this._leidoHasta = 0; this._leerCortado = false;
      const leer = (this._leerAuto || this._mhActivo()) && puedeHablar();   // en manos libres siempre se lee
      const pintar = () => {
        const acciones = burbuja.querySelector(".acciones");
        burbuja.replaceChildren(); markdown(acumulado, burbuja);
        if (acciones) burbuja.append(acciones);
        this._bajar();
      };
      await leerSSE(r.body, (evento, datos) => {
        switch (evento) {
          case "delta":
            acumulado += datos.texto || ""; pintar();
            if (leer && !this._leerCortado) this._leerIncremental(acumulado, false);
            break;
          case "tool":
            estado.textContent = TEXTOS.consultando + "… " + (datos.herramientas || []).join(", ");
            if (!estado.isConnected) burbuja.append(estado);
            break;
          case "ui": this._acciones(datos.acciones || [], burbuja); break;
          case "confirmacion": this._confirmacion(datos); break;
          case "done":
            if (datos.conversacion_id) { this._convId = datos.conversacion_id; this._recordar(); } break;
          case "token_expirado": resultado = "token_expirado"; break;
          case "error":
            if (!acumulado) burbuja.remove(); else estado.remove();
            this._error(datos.codigo); resultado = "error"; break;
        }
      });
      estado.remove();
      if (resultado === "ok" && acumulado.trim()) {
        if (leer && !this._leerCortado) this._leerIncremental(acumulado, true);
        this._botonEscuchar(burbuja, acumulado);
      }
      return resultado;
    }

    // — acciones con confirmación (contrato, sección 8) —
    // El resumen y el detalle los redactó el SISTEMA (no el modelo). Todo el texto va con textContent.
    _confirmacion(d) {
      if (!d || typeof d.id !== "string" || typeof d.huella !== "string" || typeof d.resumen !== "string") return;
      if (this._tarjetaActiva && this._tarjetaActiva.tarjeta.isConnected) this._cerrarTarjeta(this._tarjetaActiva, "reemplazada");
      const lineas = Array.isArray(d.lineas) ? d.lineas.filter((x) => typeof x === "string") : [];
      const tarjeta = this._burbuja("confirmacion");
      tarjeta.setAttribute("role", "group"); tarjeta.setAttribute("aria-label", TEXTOS.confirmarTitulo);
      const confirmar = el("button", { type: "button", class: "primario", textContent: TEXTOS.confirmar });
      const cancelar = el("button", { type: "button", textContent: TEXTOS.cancelar });
      const botones = el("div", { class: "accion-botones" }, confirmar, cancelar);
      const estado = el("div", { class: "accion-estado", role: "status" });
      const err = el("div", { class: "accion-error", role: "alert" });
      tarjeta.append(
        el("div", { class: "accion-titulo", textContent: TEXTOS.confirmarTitulo }),
        el("div", { class: "accion-resumen", textContent: d.resumen }),
        ...(lineas.length ? [el("ul", {}, ...lineas.map((l) => el("li", { textContent: l })))] : []),
        botones, estado, err,
      );
      const t = { d, tarjeta, confirmar, cancelar, botones, estado, err, timer: 0, cerrada: false, ocupada: false };
      // Solo un clic real del usuario confirma: un script que dispare click() no cuenta.
      confirmar.addEventListener("click", (ev) => { if (ev.isTrusted) this._confirmarAccion(t); });
      cancelar.addEventListener("click", (ev) => { if (ev.isTrusted) this._cancelarAccion(t); });
      const expiraMs = Date.parse(d.expira);
      const tick = () => {
        if (t.cerrada || !tarjeta.isConnected) { clearInterval(t.timer); return; }
        if (t.ocupada) return;
        const resta = Math.ceil((expiraMs - Date.now()) / 1000);
        if (resta <= 0) { this._cerrarTarjeta(t, "expirada"); return; }
        estado.textContent = TEXTOS.vence.replace("{t}", Math.floor(resta / 60) + ":" + String(resta % 60).padStart(2, "0"));
      };
      if (!Number.isNaN(expiraMs)) { tick(); t.timer = setInterval(tick, 1000); }
      this._tarjetaActiva = t;
      // En manos libres la propuesta se lee en voz alta, pero se confirma siempre con un clic.
      if (this._mhActivo() && puedeHablar()) this._decir(TEXTOS.mhConfirmarPantalla.replace("{r}", d.resumen));
      this._bajar();
    }

    _cerrarTarjeta(t, estado, texto) {
      if (t.cerrada) return;
      t.cerrada = true; clearInterval(t.timer);
      t.botones.hidden = true; t.err.textContent = "";
      t.tarjeta.classList.add("cerrada", estado);
      t.estado.textContent = texto || ESTADOS_ACCION[estado] || "";
      t.estado.classList.toggle("ok", estado === "ejecutada");
      if (this._tarjetaActiva === t) this._tarjetaActiva = null;
      this.dispatchEvent(new CustomEvent("asistente:confirmacion", {
        detail: { id: t.d.id, tool: t.d.tool || "", estado }, bubbles: true, composed: true,
      }));
      this._bajar();
    }

    // Error que no cierra la tarjeta (red, sesión): se puede reintentar o cancelar.
    _errorTarjeta(t, codigo) {
      t.ocupada = false; t.confirmar.disabled = t.cancelar.disabled = false;
      t.err.textContent = ERRORES_ACCION[codigo] || ERROR_GENERICO;
    }

    // Token de escritura: lo emite el SISTEMA anfitrión, con la sesión del usuario, solo para una propuesta suya vigente.
    async _tokenEscritura(d) {
      let u; try { u = new URL(this.getAttribute("token-url"), location.href); } catch { return null; }
      u.searchParams.set("confirmacion", d.id); u.searchParams.set("huella", d.huella);
      const r = await fetch(u, { credentials: "same-origin", headers: { Accept: "application/json" } });
      if (!r.ok) return null;
      const j = await r.json();
      return typeof j.token === "string" && j.token ? j.token : null;
    }

    async _confirmarAccion(t) {
      if (t.cerrada || t.ocupada) return;
      t.ocupada = true; t.confirmar.disabled = t.cancelar.disabled = true;
      t.err.textContent = ""; t.estado.textContent = TEXTOS.ejecutando;
      try {
        const token = await this._tokenEscritura(t.d);
        if (!token) { this._errorTarjeta(t, "sin_autorizacion"); return; }
        const r = await fetch(`${this._servidor}/v1/confirmaciones/${encodeURIComponent(t.d.id)}/confirmar`, {
          method: "POST", headers: { Authorization: "Bearer " + token },
        });
        let c = {}; try { c = await r.json(); } catch { /* sin cuerpo */ }
        if (r.status === 409) { this._cerrarTarjeta(t, c.estado in ESTADOS_ACCION ? c.estado : "fallida"); return; }
        if (r.ok && c.ok === true) {
          this._cerrarTarjeta(t, "ejecutada", typeof c.mensaje === "string" && c.mensaje ? c.mensaje : ESTADOS_ACCION.ejecutada);
          this._acciones(Array.isArray(c.ui) ? c.ui : [], t.tarjeta);
          return;
        }
        if (r.ok) { this._cerrarTarjeta(t, "fallida", ERRORES_ACCION[c.error] || ESTADOS_ACCION.fallida); return; }
        if (r.status === 403 || r.status === 404) { this._cerrarTarjeta(t, "fallida", ERRORES_ACCION[c.error] || ESTADOS_ACCION.fallida); return; }
        this._errorTarjeta(t, c.error);
      } catch { this._errorTarjeta(t); }
    }

    async _cancelarAccion(t) {
      if (t.cerrada || t.ocupada) return;
      t.ocupada = true; t.confirmar.disabled = t.cancelar.disabled = true; t.err.textContent = "";
      try {
        const r = await this._conToken((h) => fetch(`${this._servidor}/v1/confirmaciones/${encodeURIComponent(t.d.id)}/cancelar`, { method: "POST", headers: h }));
        let c = {}; try { c = await r.json(); } catch { /* sin cuerpo */ }
        if (r.ok) this._cerrarTarjeta(t, "cancelada");
        else if (r.status === 409) this._cerrarTarjeta(t, c.estado in ESTADOS_ACCION ? c.estado : "fallida");
        else this._errorTarjeta(t, c.error);
      } catch { this._errorTarjeta(t); }
    }

    _acciones(lista, burbuja) {
      for (const a of lista) {
        if (!a || a.tipo !== "navegar" || typeof a.url !== "string") continue;
        const ev = new CustomEvent("asistente:accion", {
          detail: { tipo: a.tipo, url: a.url, etiqueta: a.etiqueta || "" },
          bubbles: true, composed: true, cancelable: true,
        });
        if (!this.dispatchEvent(ev)) continue;  // el anfitrión se encarga
        // Por defecto: solo URLs relativas del mismo origen.
        let u; try { u = new URL(a.url, location.href); } catch { continue; }
        if (u.origin !== location.origin || /^[a-z][a-z0-9+.-]*:/i.test(a.url) || a.url.startsWith("//")) continue;
        let caja = burbuja.querySelector(".acciones");
        if (!caja) { caja = el("div", { class: "acciones" }); burbuja.append(caja); }
        caja.append(el("a", { href: u.pathname + u.search + u.hash, textContent: a.etiqueta || a.url }));
      }
    }
  }

  // Lector SSE sobre ReadableStream (EventSource no permite cabecera Authorization).
  async function leerSSE(stream, alEvento) {
    const lector = stream.getReader(), dec = new TextDecoder();
    let buf = "";
    const procesar = (bloque) => {
      let evento = "message", datos = "";
      for (const linea of bloque.split("\n")) {
        if (linea.startsWith(":")) continue;  // heartbeat
        if (linea.startsWith("event:")) evento = linea.slice(6).trim();
        else if (linea.startsWith("data:")) datos += linea.slice(5).trimStart();
      }
      if (!datos) return;
      try { alEvento(evento, JSON.parse(datos)); } catch (e) { console.error("<asistente-chat>: evento inválido", e); }
    };
    for (;;) {
      const { done, value } = await lector.read();
      if (done) break;
      buf += dec.decode(value, { stream: true }).replace(/\r\n/g, "\n");
      let i;
      while ((i = buf.indexOf("\n\n")) >= 0) { procesar(buf.slice(0, i)); buf = buf.slice(i + 2); }
    }
    if (buf.trim()) procesar(buf);
  }

  customElements.define("asistente-chat", AsistenteChat);
})();
