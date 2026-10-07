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
 *   nombre      cómo se llama el asistente en el widget (título, avisos, ajustes). Orden: el que el usuario puso en su panel
 *               de ajustes > este atributo > `nombre_asistente` del sistema (sistemas.yaml, vía /v1/estado) > "Asistente".
 *               Es también la palabra que despierta el modo voz («Lucas, ¿cuánto…?»), salvo que se fije palabra-activacion.
 *   placeholder texto del campo de entrada.
 *   idioma      idioma de la voz (BCP 47). Por defecto "es-UY"; sin voces de ese idioma se usa es-ES o la
 *               primera en español que tenga el sistema.
 *   voz         nombre exacto de una voz del navegador (speechSynthesis) para forzarla.
 *   voz-motor   "auto" (por defecto), "navegador" o "servidor". El dictado usa el reconocimiento de voz del
 *               navegador (Web Speech; en Chrome el audio lo procesa el servicio de Google) y, si no existe,
 *               el STT del asistente (POST /v1/voz/transcribir). "servidor" evita enviar el audio a Google.
 *               No afecta a la respuesta hablada (ver voz-respuesta).
 *   voz-respuesta  "auto" (por defecto), "servidor" o "navegador": con qué voz habla el asistente. "auto" usa la
 *               voz del servidor (POST /v1/voz/sintetizar, p. ej. ElevenLabs) si el sistema la tiene configurada
 *               (/v1/estado: voz.respuesta) y, si falla o no existe, la del navegador (speechSynthesis).
 *               "navegador" no envía el texto de las respuestas a ningún tercero; "servidor" no cae al navegador.
 *   palabra-activacion        palabra que despierta el «modo voz» (por defecto, el nombre del asistente; si es "Asistente", "asistente").
 *   manos-libres-inactividad  minutos sin interacción tras los que el modo voz se apaga solo
 *               (por defecto 5; 0 = no se apaga; el nombre del atributo se conserva por compatibilidad).
 *               El botón «Voz» solo aparece si el navegador tiene reconocimiento y síntesis de voz, la página
 *               es un contexto seguro y voz-motor no es "servidor". El modo voz tiene su propia vista (un
 *               orbe, lo que dices y lo que te dicen) y se alterna con el chat; el chat guarda todo lo dicho
 *               y la respuesta completa, y por voz el asistente cuenta un resumen (canal «voz» del chat).
 *
 *   tema        "claro" | "oscuro" | "auto" (por defecto). "auto" sigue prefers-color-scheme y reacciona si el
 *               usuario cambia el tema del sistema con la página abierta. Se puede cambiar en caliente.
 *
 *   acuse        "auto" (por defecto) | "no": en el modo voz, si el resumen tarda más de ~0,9 s se dice una frase corta («Un
 *               momento, lo consulto») para que no haya silencio; "no" la quita.
 *   modo-inicial "auto" (por defecto) | "chat": con "auto" el widget abre en modo voz cuando está disponible (el usuario pasa
 *               al chat con el botón «Chat»); "chat" abre en el chat. El ajuste «Abrir en modo voz» del usuario también lo apaga.
 *   ajustes      "auto" (por defecto) | "no": engranaje con el panel de ajustes del usuario (motor de voz, volumen, lectura
 *               automática, acuse, confirmar con «enviar»). Se guardan en el navegador (localStorage, por servidor). Lo que el usuario elige manda
 *               sobre `voz-respuesta` y `acuse`; con "no" no hay panel y mandan los atributos.
 *   orbe-volumen "auto" (por defecto) | "no": el orbe del modo voz sigue el volumen del micrófono con un segundo flujo
 *               de audio local (solo se analiza; no se graba ni se envía). "no" no lo abre.
 *
 * Personalización por variables CSS (se heredan a través del Shadow DOM):
 *   --asistente-color, --asistente-color-texto, --asistente-fondo, --asistente-texto,
 *   --asistente-borde, --asistente-fuente, --asistente-radio,
 *   --asistente-ancho-lateral (260px), --asistente-ancho-columna (760px)
 *   Las que el anfitrión defina mandan sobre la paleta del tema (clara u oscura). Quien fije colores de
 *   fondo/texto propios debe fijar el par completo (fondo y texto, color y color-texto) y, si solo los
 *   diseñó para un tema, fijar también `tema` en consecuencia.
 *
 * Eventos (CustomEvent, burbujean y atraviesan el Shadow DOM):
 *   asistente:accion   {detail: {tipo, url, etiqueta}} por cada sugerencia `ui` del sistema.
 *                      Si el anfitrión llama preventDefault(), el widget no muestra su botón.
 *   asistente:estado   {detail: {habilitado}} al decidir si el asistente está disponible
 *                      (si no lo está, el widget muestra un aviso en lugar del chat).
 *   asistente:metricas {detail: {canal, fuente, acuse_ms, primer_delta_ms, voz_ms, habla_ms, tts_ms, servidor}} al terminar cada turno por
 *                      voz: cuánto tardó en llegar el resumen hablado y en empezar a sonar (solo números).
 *   asistente:confirmacion  {detail: {id, tool, estado}} cuando una acción propuesta por el asistente termina
 *                      (estado: ejecutada | cancelada | expirada | reemplazada | fallida). El anfitrión puede
 *                      refrescar su pantalla tras una acción ejecutada.
 *
 * Memoria por usuario: si el sistema la habilitó (`memoria: true` en /v1/estado), el asistente puede guardar, solo a pedido
 * del usuario y con el mismo botón Confirmar, preferencias, alias y consultas guardadas. Esas tarjetas llevan `local: true`:
 * se confirman con la sesión normal (POST /v1/confirmaciones/{id}/confirmar-local), sin pedir token al sistema anfitrión.
 * Un botón de la barra abre el panel «Lo que recuerdo», donde el usuario ve y olvida cada cosa (o todo). Nunca por voz.
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
    noDisponible: "{n} no está disponible para tu usuario.",
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
    manosLibres: "Voz",
    chatBoton: "Chat",
    volverVoz: "Volver al modo voz",
    apagarManosLibres: "Salir del modo voz",
    verChat: "Ver el chat",
    mhArmado: "Modo voz activo. Decí «{p}» para hablar.",
    mhCapturando: "Te escucho…",
    mhConfirmando: "¿Lo envío? Decí «enviar» o «cancelar».",
    mhRespondiendo: "Respondiendo… Decí «{p}» para interrumpir.",
    mhEsperar: "Esperá a que termine la respuesta para enviar.",
    mhPrivacidad: "Micrófono abierto: el audio se envía al servicio de voz del navegador (Google, en Chrome).",
    mhInactividad: "Modo voz apagado por inactividad.",
    // Acuse inmediato del modo voz: se dice solo si el resumen tarda; varias frases para que no cansen.
    mhAcuse: ["Un momento, lo consulto.", "Ya lo busco.", "Dame un segundo."],
    mhDicho: "Te digo",
    mhChatCompleto: "La respuesta completa está en el chat.",
    mhConfirmaEnChat: "Hay una acción para confirmar: está en el chat, con sus botones.",
    escenaVoz: "Modo voz",
    cancelar: "Cancelar",
    confirmarTitulo: "Confirmá esta acción",
    confirmar: "Confirmar",
    vence: "Vence en {t}",
    ejecutando: "Ejecutando…",
    mhConfirmarPantalla: "Te pido confirmar en pantalla: {r}",
    pie: "Las respuestas pueden contener errores; verificá los datos importantes.",
    memoria: "Lo que recuerdo",
    memoriaTitulo: "Lo que recuerdo de vos",
    memoriaIntro: "Esto es lo que me pediste que recuerde. Lo uso solo en tus conversaciones y, si pasa un tiempo sin usarlo, se olvida solo.",
    memoriaVacio: "Todavía no guardé nada. Podés pedirme, por ejemplo: «recordá que quiero las hectáreas sin decimales».",
    memoriaCerrar: "Cerrar",
    ajustes: "Ajustes",
    ajustesTitulo: "Ajustes",
    ajNombre: "Nombre del asistente",
    ajMotor: "Voz de {n}",
    ajMotorNavegador: "Del navegador",
    ajMotorServidor: "Del servidor (más natural)",
    ajVolumen: "Volumen",
    ajLeerAuto: "Leer las respuestas en voz alta",
    ajConfirmar: "Pedir «enviar» o «cancelar» antes de enviar (modo voz)",
    ajInicioVoz: "Abrir en modo voz",
    ajAcuse: "Decir «un momento» mientras consulta (modo voz)",
    ajProbar: "Probar voz",
    ajPrueba: "Hola, así suena mi voz.",
    ajRestablecer: "Restablecer",
    ajCerrar: "Cerrar",
    memoriaOlvidar: "Olvidar",
    memoriaOlvidarTodo: "Olvidar todo",
    memoriaOlvidarEsto: "Olvidar: {d}",
    memoriaVence: "Se olvida solo el {f} si no lo uso",
    memoriaOlvidado: "Listo, lo olvidé.",
    memoriaOlvidadoTodo: "Listo, olvidé todo.",
    memoriaCargando: "Cargando…",
    memoriaErrorCargar: "No pude cargar lo que recuerdo. Probá de nuevo.",
    memoriaErrorBorrar: "No pude olvidarlo. Probá de nuevo.",
    memoriaTipos: { preferencia: "Preferencia", alias: "Alias", consulta_guardada: "Consulta guardada" },
  };
  const ERRORES = {
    mensajes_min: "Enviaste demasiados mensajes seguidos. Esperá un momento.",
    mensajes_dia: "Alcanzaste el límite diario de mensajes.",
    tokens_mes: "Se alcanzó el límite mensual de uso del asistente.",
    timeout_turno: "La consulta tardó demasiado. Probá de nuevo.",
    demasiadas_iteraciones: "No pude completar la consulta. Probá reformularla.",
    llm_no_disponible: "El asistente no está disponible por ahora.",
    llm_no_configurado: "El asistente no está disponible por ahora.",
    respuesta_vacia: "No llegó respuesta del asistente. Probá de nuevo.",
    respuesta_cortada: "La respuesta era demasiado larga y se cortó. Probá pedirla más corta.",
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
    accion_no_local: "La confirmación no es válida. Pedilo de nuevo.",
    memoria_no_habilitada: "La memoria no está habilitada en este sistema.",
    tope_alcanzado: "Ya hay 20 cosas guardadas. Olvidá alguna desde «Lo que recuerdo» y pedilo de nuevo.",
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
  // Trozos de hasta `max` caracteres para pedirle al servidor: cortan en fin de oración (o de línea, o en un espacio).
  function partirParaVoz(texto, max = 900) {
    const trozos = [];
    let resto = String(texto || "").trim();
    while (resto.length > max) {
      const ventana = resto.slice(0, max);
      let corte = Math.max(ventana.lastIndexOf("\n"), ...[". ", "! ", "? ", "… ", "; "].map((x) => ventana.lastIndexOf(x) + 1));
      if (corte < max / 3) corte = ventana.lastIndexOf(" ");
      if (corte < max / 3) corte = max;
      trozos.push(resto.slice(0, corte).trim());
      resto = resto.slice(corte).trim();
    }
    if (resto) trozos.push(resto);
    return trozos.filter(Boolean);
  }
  const TTS_PAUSA_MS = 30000;        // tras un fallo de la voz del servidor, ese tiempo habla el navegador
  const TTS_CACHE_MAX = 12;          // frases fijas (acuses) cuyo audio se guarda en memoria; el texto de las respuestas nunca
  const TTS_CACHE_CHARS = 60;
  const CLAVE_LEER = "asistente:leer-en-voz-alta";
  const CLAVE_AJUSTES = "asistente:ajustes:";   // + servidor; JSON en localStorage (nunca el token ni texto del usuario)
  const NOMBRE_BASE = "Asistente", NOMBRE_MAX = 40;
  // Nombre limpio (sin espacios en los extremos ni caracteres de control, tope NOMBRE_MAX) o "" si no sirve.
  function nombreLimpio(v) {
    return typeof v === "string" ? v.replace(/[\u0000-\u001f\u007f]/g, "").trim().slice(0, NOMBRE_MAX).trim() : "";
  }
  const AJUSTES_BASE = { nombre: "", motor: "auto", volumen: 1, acuse: true, confirmar: true, iniciarVoz: true };
  const MOTORES = ["auto", "navegador", "servidor"];
  // Zona del usuario (IANA, p. ej. America/Montevideo) para que «hoy» y «ayer» sean los suyos. Si el navegador no la da, se omite.
  function zonaHoraria() {
    try { return Intl.DateTimeFormat().resolvedOptions().timeZone || undefined; } catch (_) { return undefined; }
  }

  // ── Modo voz (antes «manos libres»; ver contrato 7.4) ──
  // Decisión de producto: nada se envía solo al terminar de hablar; el usuario confirma («enviar» o botón).
  // Ponerlo en false hace que se envíe al cerrar la frase (mismo camino, sin código aparte).
  const MANOS_LIBRES_CONFIRMAR = true;
  const PALABRA_ACTIVACION = "asistente";   // por defecto; atributo palabra-activacion
  const MH_INACTIVIDAD_MIN = 5;             // se apaga solo tras tantos minutos sin interacción; atributo manos-libres-inactividad (0 = nunca)
  const MH_CIERRE_MS = 1800;                // silencio tras el que una frase dictada pasa a confirmación
  const MH_ESPERA_MS = 8000;                // tras la palabra de activación, tiempo para empezar a hablar
  const MH_ACUSE_PAUSA_MS = 500;            // silencio entre el acuse y lo que se diga después, para que no se pisen
  const MH_ACUSE_MS = 900;                  // si pasado este tiempo tras «enviar» no hay nada que decir, se dice un acuse corto
  const MH_MAX_FALLOS = 5;                  // reinicios seguidos del reconocedor con error antes de apagar

  const COMANDOS = {
    enviar: ["enviar", "envia", "enviar mensaje", "enviar pregunta"],
    cancelar: ["cancelar", "cancela", "descartar", "descarta"],
    apagar: ["apagar modo voz", "apaga modo voz", "salir del modo voz", "salir de voz", "apagar manos libres", "apaga manos libres", "desactivar manos libres"],
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
  // Volumen (0..1) de un bloque de muestras de audio en el dominio del tiempo (bytes centrados en 128).
  function nivelDe(muestras) {
    if (!muestras || !muestras.length) return 0;
    let suma = 0;
    for (let i = 0; i < muestras.length; i++) { const v = (muestras[i] - 128) / 128; suma += v * v; }
    return Math.min(1, Math.sqrt(suma / muestras.length) * 3.2);   // la voz normal ronda 0,05–0,3 de RMS
  }
  // Suavizado del nivel: sube rápido (ataque) y baja despacio (caída); `dt` en segundos.
  function suavizar(actual, objetivo, dt) {
    return actual + (objetivo - actual) * Math.min(1, dt * (objetivo > actual ? 18 : 5));
  }
  // Respaldo del resumen hablado: si el modelo no mandó su bloque, se leen las dos primeras oraciones (con tope).
  function resumenBreve(md, max = 300) {
    const plano = textoParaVoz(md).replace(/\s+/g, " ").trim();
    const re = /[.!?…]+["')\]]?(?=\s|$)/g;
    let corte = 0, n = 0, m;
    while (n < 2 && (m = re.exec(plano))) {
      const fin = m.index + m[0].length;
      if (n > 0 && fin > max) break;
      corte = fin; n++;
    }
    let t = plano.slice(0, corte || plano.length);
    if (t.length > max) t = t.slice(0, max).replace(/\s+\S*$/, "") + "…";
    return t;
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
    /* Paletas por tema (--p-*). Las variables --asistente-* del anfitrión tienen siempre prioridad. */
    .raiz {
      --p-c: #2f6f3e; --p-ct: #fff; --p-f: #fff; --p-t: #1d2420; --p-b: #d9ded9;
      --p-err-f: #fdecec; --p-err-t: #8a1f1f; --p-ok: #1f6b3a; --p-rec: #c0392b; --p-rec-t: #fff; --p-pausa: #a8530a;
      color-scheme: light;
    }
    .raiz.oscuro {
      --p-c: #6fcf88; --p-ct: #0d1a11; --p-f: #151a17; --p-t: #e6ebe7; --p-b: #3a443e;
      --p-err-f: #3b1d1d; --p-err-t: #ffb8b2; --p-ok: #7fdc9c; --p-rec: #ff6b5e; --p-rec-t: #1a0b09; --p-pausa: #f2b45a;
      color-scheme: dark;
    }
    .raiz {
      --c: var(--asistente-color, var(--p-c));
      --ct: var(--asistente-color-texto, var(--p-ct));
      --f: var(--asistente-fondo, var(--p-f));
      --t: var(--asistente-texto, var(--p-t));
      --b: var(--asistente-borde, var(--p-b));
      --suave: color-mix(in srgb, var(--t) 6%, var(--f));
      --apagado: color-mix(in srgb, var(--t) 70%, var(--f));
      --codigo: color-mix(in srgb, var(--t) 9%, var(--f));
      --r: var(--asistente-radio, 12px);
      display: flex; width: 100%; height: 100%; position: relative; overflow: hidden;
      background: var(--f); color: var(--t);
      scrollbar-color: color-mix(in srgb, var(--t) 35%, var(--f)) transparent;
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
    .lista .borrar:hover { color: var(--p-err-t); }
    .lista .borrar svg { width: 16px; height: 16px; }
    .lista .vacio-hist { display: block; padding: 10px; color: var(--apagado); font-size: 13px; }

    .principal { flex: 1; min-width: 0; display: flex; flex-direction: column; position: relative; }
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
    /* ── Modo voz: panel con orbe. En el chat va compacto sobre la entrada; en la vista de voz ocupa la escena. ── */
    .entrada { container-type: inline-size; }
    .mh {
      --s: 34px; --acento: var(--c);
      --fondo-mh: color-mix(in srgb, var(--acento) 5%, var(--f));
      max-width: var(--asistente-ancho-columna, 760px); margin: 0 auto 8px; padding: 6px 12px;
      border: 1px solid color-mix(in srgb, var(--acento) 70%, var(--b)); border-radius: var(--r); background: var(--fondo-mh);
      display: grid; grid-template-columns: auto 1fr auto; align-items: center; gap: 0 10px; font-size: 13px;
    }
    .mh[hidden] { display: none; }
    .mh[data-estado="confirmando"] { --acento: var(--p-pausa); }
    .mh-texto { min-width: 0; }
    .mh-estado { font-weight: 600; font-size: 12.5px; }
    .mh-campo { display: none; }
    .mh-parcial { color: var(--apagado); overflow: hidden; text-overflow: ellipsis; white-space: nowrap; }
    .mh-parcial:empty { display: none; }
    .mh-botones { display: flex; flex-wrap: wrap; gap: 6px; justify-content: flex-end; }
    .mh button { border: 1px solid var(--b); background: var(--f); color: inherit; border-radius: 999px; padding: 3px 12px; font: inherit; cursor: pointer; }
    .mh button:hover { border-color: var(--c); color: var(--c); }
    .mh .mh-enviar { background: var(--c); border-color: var(--c); color: var(--ct); }
    .mh .mh-enviar:hover { color: var(--ct); opacity: .9; }
    .mh button[hidden] { display: none; }
    .mh-priv { grid-column: 1 / -1; font-size: 10.5px; color: var(--apagado); }
    @container (max-width: 560px) { .mh-botones { grid-column: 1 / -1; justify-content: flex-start; } }

    /* Orbe: capas con transform/opacity, sin máscaras ni canvas. El estado se ve por su forma (glifo y trazo), no solo por el color. */
    .orbe { position: relative; width: var(--s); height: var(--s); margin: calc(var(--s) * .16); flex: none; }
    .orbe i, .orbe svg { position: absolute; inset: 0; border-radius: 50%; display: block; }
    .o-halo { inset: -40% !important; background: radial-gradient(circle, color-mix(in srgb, var(--acento) 34%, transparent) 0, transparent 62%); opacity: calc(var(--halo, 0) * var(--halo-n, .5)); }
    .o-aro { border: var(--g, 3px) solid transparent; opacity: var(--aro-n, 1);
      background: linear-gradient(var(--fondo-mh), var(--fondo-mh)) padding-box,
        conic-gradient(from 20deg, var(--acento), color-mix(in srgb, var(--acento) 35%, transparent) 18%, var(--acento) 34%, color-mix(in srgb, var(--acento) 55%, transparent) 58%, var(--acento) 74%, color-mix(in srgb, var(--acento) 40%, transparent) 90%, var(--acento)) border-box; }
    .o-fino { inset: 17% !important; border: 1px solid color-mix(in srgb, var(--acento) 45%, transparent); }
    /* anillo que sigue el volumen: --nivel (0..1) lo escribe el widget (micrófono del usuario; pulsos por palabra del asistente) */
    .o-nivel { display: none; border: 2px solid var(--acento); opacity: calc(var(--nivel, 0) * .85); transform: scale(calc(1 + var(--nivel, 0) * .42)); }
    .mh[data-estado="armado"] .o-nivel, .mh[data-estado="capturando"] .o-nivel, .mh[data-estado="confirmando"] .o-nivel, .mh[data-estado="hablando"] .o-nivel { display: block; }
    @media (prefers-reduced-motion: reduce) { .o-nivel { display: none !important; } }
    .o-barrido { inset: 7% !important; background: conic-gradient(from 0deg, transparent 0 240deg, color-mix(in srgb, var(--acento) 70%, transparent) 340deg, var(--acento) 360deg); opacity: 0; }
    .o-disco { inset: calc(7% + 7px) !important; background: var(--fondo-mh); opacity: 0; }
    .o-marcas { display: none; inset: -16% !important; width: 132%; height: 132%; fill: none; stroke: var(--acento); stroke-width: 3.4; stroke-dasharray: .9 4.9; border-radius: 0; }
    .o-seg { inset: -3% !important; width: 106%; height: 106%; fill: none; stroke: var(--acento); stroke-width: 2.6; stroke-dasharray: 15 4; opacity: 0; border-radius: 0; }
    .o-nucleo { inset: 30% !important; opacity: calc(var(--nuc-n, .6) + var(--nivel, 0) * .25); background: radial-gradient(circle, color-mix(in srgb, var(--acento) 85%, transparent) 0, color-mix(in srgb, var(--acento) 18%, transparent) 70%, transparent 72%); }
    .o-onda { border: 1.5px solid var(--acento); opacity: 0; }
    .o-glifo { inset: 28% !important; width: 44%; height: 44%; stroke: var(--acento); fill: none; stroke-width: 2; stroke-linecap: round; stroke-linejoin: round; opacity: 0; border-radius: 0; }
    .mh[data-estado="armado"] .g-mic, .mh[data-estado="capturando"] .g-esc, .mh[data-estado="confirmando"] .g-pausa,
    .mh[data-estado="procesando"] .g-pensar, .mh[data-estado="hablando"] .g-habla { opacity: 1; }
    .mh[data-estado="armado"] { --aro-n: .6; --nuc-n: .25; --halo-n: .25; }
    .mh[data-estado="capturando"] { --aro-n: 1; --nuc-n: .75; --halo-n: .9; }
    .mh[data-estado="confirmando"] { --aro-n: 0; --nuc-n: .35; --halo-n: .5; }
    .mh[data-estado="confirmando"] .o-seg { opacity: 1; }
    .mh[data-estado="procesando"] { --aro-n: .55; --nuc-n: .5; --halo-n: .6; }
    .mh[data-estado="procesando"] .o-barrido, .mh[data-estado="procesando"] .o-disco { opacity: 1; }
    .mh[data-estado="hablando"] { --aro-n: 1; --nuc-n: .8; --halo-n: .9; }
    .mh[data-estado="capturando"] .o-fino, .mh[data-estado="hablando"] .o-fino { border-width: 2px; }
    .mh[data-estado="capturando"] .o-onda:first-of-type, .mh[data-estado="hablando"] .o-onda:first-of-type { opacity: .35; transform: scale(1.35); }
    .raiz.oscuro .mh { --halo: 1; }
    @media (prefers-reduced-motion: no-preference) {
      .mh[data-estado="armado"] .o-nucleo { animation: respira 4.2s ease-in-out infinite; }
      .mh[data-estado="capturando"] .o-onda { animation: onda 1.5s ease-out infinite; }
      .mh[data-estado="capturando"] .o-onda.o2 { animation-delay: .75s; }
      .mh[data-estado="capturando"] .o-nucleo, .mh.pulso .o-nucleo { animation: golpe .35s ease-out; }
      .mh[data-estado="procesando"] .o-barrido { animation: gira 1.5s linear infinite; }
      .mh[data-estado="procesando"] .o-nucleo { animation: respira 1.6s ease-in-out infinite; }
      .mh[data-estado="hablando"] .o-onda { animation: onda 2.4s ease-out infinite; }
      .mh[data-estado="hablando"] .o-onda.o2 { animation-delay: 1.2s; }
      .mh[data-estado="hablando"] .o-nucleo { animation: habla 1.1s ease-in-out infinite; }
      .mh[data-estado="confirmando"] .o-halo { animation: respira 2.8s ease-in-out infinite; }
      .vista-voz .o-marcas { animation: gira 48s linear infinite; }
      .vista-voz .mh[data-estado="procesando"] .o-marcas { animation-duration: 14s; animation-direction: reverse; }
    }
    @keyframes respira { 50% { transform: scale(1.06); } }
    @keyframes onda { from { transform: scale(.92); opacity: .55; } to { transform: scale(1.6); opacity: 0; } }
    @keyframes golpe { 40% { transform: scale(1.35); } }
    @keyframes gira { to { transform: rotate(360deg); } }
    @keyframes habla { 0%, 100% { transform: scale(.9); } 20% { transform: scale(1.22); } 45% { transform: scale(1); } 70% { transform: scale(1.14); } }

    /* ── Vista de voz: otra «ventana» (sin chat ni campo); el chat sigue ahí y se alterna con «Ver el chat» ── */
    .escena { display: none; flex: 1; min-height: 0; position: relative; flex-direction: column; align-items: center; justify-content: center; gap: 14px; padding: 20px 16px; overflow-y: auto; }
    .escena::before, .escena::after { content: ""; position: absolute; width: 18px; height: 18px; border: 1.5px solid color-mix(in srgb, var(--c) 70%, var(--b)); }
    .escena::before { top: 14px; left: 14px; border-right: 0; border-bottom: 0; }
    .escena::after { bottom: 14px; right: 14px; border-left: 0; border-top: 0; }
    .vista-voz .escena { display: flex; }
    .raiz.vista-voz .scroll, .vista-voz .entrada form, .vista-voz .entrada .pie, .vista-voz .barra .altavoz { display: none; }
    .escena .mh { --s: clamp(112px, 26vh, 176px); grid-template-columns: 1fr; justify-items: center; text-align: center; gap: 4px; border: 0; background: none; margin: 0; padding: 0; width: 100%; max-width: var(--asistente-ancho-columna, 760px); }
    .escena .mh-estado { font-size: 15px; letter-spacing: .02em; }
    .escena .mh-campo { display: block; font-size: 17px; max-width: 100%; overflow-wrap: anywhere; min-height: 1.5em; }
    .escena .mh-parcial { font-size: 15px; white-space: normal; max-width: 100%; }
    .escena .mh-botones { grid-column: auto; justify-content: center; margin-top: 8px; }
    .escena .mh-apagar { display: none; }   /* en la vista de voz se vuelve al chat con «Chat» o «Ver el chat»; apagar queda en el panel compacto y con Esc */
    .escena .mh-priv { position: absolute; left: 40px; right: 40px; bottom: 12px; margin: 0; font-size: 11px; text-align: center; }   /* aviso fijo al fondo de la escena */
    .escena .o-marcas { display: block; opacity: .55; }
    .escena .o-aro { --g: 4px; }
    .escena .msg.confirmacion { align-self: center; box-sizing: border-box; width: 100%; max-width: var(--asistente-ancho-columna, 760px); }
    .dicho { max-width: var(--asistente-ancho-columna, 760px); text-align: center; font-size: 15px; min-height: 1.5em; }
    .dicho:empty { display: none; }
    .dicho small { display: block; font-size: 11px; letter-spacing: .06em; text-transform: uppercase; color: var(--apagado); margin-bottom: 2px; }
    button.ver-chat { border: 1px solid var(--b); background: var(--f); border-radius: 999px; padding: 6px 16px; font: inherit; cursor: pointer; }
    button.ver-chat:hover { border-color: var(--c); color: var(--c); }
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
    .msg.error { align-self: stretch; padding: 8px 12px; background: var(--p-err-f); color: var(--p-err-t); border-radius: var(--r); }
    .msg > :first-child { margin-top: 0; } .msg > :last-child { margin-bottom: 0; }
    .msg p, .msg ul, .msg ol, .msg pre, .msg h3, .msg h4, .msg h5, .msg h6 { margin: 0 0 10px; }
    .msg h3, .msg h4, .msg h5, .msg h6 { font-size: 16px; }
    .msg ul, .msg ol { padding-left: 22px; }
    .msg code { font-family: ui-monospace, monospace; font-size: 13px; background: var(--codigo); padding: 1px 5px; border-radius: 4px; }
    .msg pre { background: var(--codigo); padding: 10px; border-radius: 8px; overflow-x: auto; }
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
    .accion-estado.ok { color: var(--p-ok); }
    .accion-error { margin-top: 6px; font-size: 13px; color: var(--p-err-t); }
    .accion-error:empty { display: none; }

    /* Panel «Lo que recuerdo»: cubre la columna principal; todo con las variables del tema. */
    .barra .memoria[aria-expanded="true"], .barra .ajustes[aria-expanded="true"] { color: var(--c); }
    .barra .ajustes[hidden] { display: none; }
    /* Menú desplegable bajo el engranaje (no cubre el chat). */
    .ajustes-panel {
      position: absolute; top: 52px; right: 12px; z-index: 6; display: flex; flex-direction: column;
      width: min(320px, calc(100% - 24px)); max-height: calc(100% - 64px);
      background: var(--f); border: 1px solid var(--b); border-radius: calc(var(--r) * 1.5);
      overflow: hidden;
    }
    .ajustes-panel[hidden] { display: none; }
    .aj-fila { margin: 0 0 18px; padding: 0; border: 0; min-width: 0; }
    .aj-fila[hidden] { display: none; }
    .aj-fila legend, .aj-fila > label.aj-tit { display: block; padding: 0; margin: 0 0 6px; font-size: 13px; font-weight: 600; }
    .aj-op { display: flex; align-items: center; gap: 8px; padding: 4px 0; cursor: pointer; }
    .aj-fila input[type="text"] { box-sizing: border-box; width: 100%; padding: 6px 10px; font: inherit; color: var(--t); background: var(--f); border: 1px solid var(--b); border-radius: var(--r); }
    .aj-fila input[type="range"] { width: 100%; accent-color: var(--c); }
    .aj-fila input:focus-visible, .aj-fila button:focus-visible { outline: 2px solid var(--c); outline-offset: 2px; }
    .aj-acciones { display: flex; gap: 8px; flex-wrap: wrap; }
    .aj-acciones button { padding: 5px 14px; border-radius: 999px; border: 1px solid var(--c); background: var(--f); color: var(--c); cursor: pointer; }
    .aj-acciones button:hover:not(:disabled) { background: var(--c); color: var(--ct); }
    .memoria-panel { position: absolute; inset: 0; z-index: 5; display: flex; flex-direction: column; background: var(--f); }
    .memoria-panel[hidden] { display: none; }
    .mem-cab { display: flex; align-items: center; gap: 8px; padding: 10px 16px; border-bottom: 1px solid var(--b); }
    .mem-cab h2 { flex: 1; margin: 0; font-size: 15px; font-weight: 600; }
    .mem-cab button { background: none; border: 1px solid var(--b); border-radius: 999px; padding: 4px 14px; cursor: pointer; }
    .mem-cab button:hover { border-color: var(--c); }
    .mem-cuerpo { flex: 1; min-height: 0; overflow-y: auto; padding: 14px 16px; }
    .mem-col { max-width: var(--asistente-ancho-columna, 760px); margin: 0 auto; }
    .mem-intro { margin: 0 0 12px; font-size: 14px; color: var(--apagado); }
    .mem-lista { list-style: none; margin: 0; padding: 0; display: flex; flex-direction: column; gap: 8px; }
    .mem-lista li { display: flex; align-items: center; gap: 10px; padding: 10px 12px; border: 1px solid var(--b); border-radius: var(--r); background: var(--f); }
    .mem-dato { flex: 1; min-width: 0; }
    .mem-tipo { font-size: 11px; text-transform: uppercase; letter-spacing: .05em; color: var(--apagado); }
    .mem-desc { overflow-wrap: anywhere; }
    .mem-vence { font-size: 12px; color: var(--apagado); }
    .mem-lista button, .mem-pie button { flex: none; padding: 5px 14px; border-radius: 999px; border: 1px solid var(--c); background: var(--f); color: var(--c); cursor: pointer; }
    .mem-lista button:hover:not(:disabled), .mem-pie button:hover:not(:disabled) { background: var(--c); color: var(--ct); }
    .mem-lista button:disabled, .mem-pie button:disabled { opacity: .45; cursor: default; }
    .mem-vacio { color: var(--apagado); font-size: 14px; }
    .mem-estado { margin-top: 10px; font-size: 13px; color: var(--apagado); min-height: 1.4em; }
    .mem-error { margin-top: 6px; font-size: 13px; color: var(--p-err-t); }
    .mem-error:empty { display: none; }
    .mem-pie { padding: 10px 16px; border-top: 1px solid var(--b); }
    .mem-pie .mem-col { display: flex; justify-content: flex-end; }

    .entrada { padding: 0 16px 8px; }
    .entrada form {
      max-width: var(--asistente-ancho-columna, 760px); margin: 0 auto; display: flex; align-items: flex-end; gap: 8px;
      padding: 8px 8px 8px 16px; background: var(--f); border: 1px solid var(--b); border-radius: calc(var(--r) * 1.8);
    }
    .entrada form:focus-within { border-color: var(--c); }
    textarea::placeholder { color: var(--apagado); opacity: 1; }
    textarea { flex: 1; resize: none; border: 0; outline: 0; background: transparent; font: inherit; color: inherit; max-height: 200px; padding: 6px 0; }
    form button {
      flex: none; width: 36px; height: 36px; border: 0; border-radius: 50%; display: grid; place-items: center;
      background: var(--c); color: var(--ct); cursor: pointer;
    }
    form button:disabled { opacity: .4; cursor: default; }
    form button.mic { background: transparent; color: var(--apagado); border: 1px solid var(--b); }
    form button.mic:hover:not(:disabled) { color: var(--c); border-color: var(--c); }
    form button.mic.grabando { background: var(--p-rec); border-color: var(--p-rec); color: var(--p-rec-t); }
    form button.mic[hidden] { display: none; }
    .aviso-voz { font-size: 12px; color: var(--apagado); text-align: center; padding-top: 4px; min-height: 16px; }
    .aviso-voz:empty { display: none; }
    .aviso-voz.err { color: var(--p-err-t); }
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
    chat: "M21 15a2 2 0 0 1-2 2H7l-4 4V5a2 2 0 0 1 2-2h14a2 2 0 0 1 2 2z",
    manos: "M12 3a3 3 0 0 0-3 3v6a3 3 0 0 0 6 0V6a3 3 0 0 0-3-3zM5 11a7 7 0 0 0 14 0M12 18v3M2 9v4M22 9v4",
    altavoz: "M11 5L6 9H2v6h4l5 4V5zM15.5 8.5a5 5 0 0 1 0 7M19 5a9 9 0 0 1 0 14",
    memoria: "M6 3h12a1 1 0 0 1 1 1v17l-7-4-7 4V4a1 1 0 0 1 1-1z",
    ajustes: "M12 15a3 3 0 1 0 0-6 3 3 0 0 0 0 6zM19.4 15a1.65 1.65 0 0 0 .33 1.82l.06.06a2 2 0 0 1 0 2.83 2 2 0 0 1-2.83 0l-.06-.06a1.65 1.65 0 0 0-1.82-.33 1.65 1.65 0 0 0-1 1.51V21a2 2 0 0 1-4 0v-.09A1.65 1.65 0 0 0 9 19.4a1.65 1.65 0 0 0-1.82.33l-.06.06a2 2 0 0 1-2.83-2.83l.06-.06a1.65 1.65 0 0 0 .33-1.82 1.65 1.65 0 0 0-1.51-1H3a2 2 0 0 1 0-4h.09A1.65 1.65 0 0 0 4.6 9a1.65 1.65 0 0 0-.33-1.82l-.06-.06a2 2 0 0 1 2.83-2.83l.06.06a1.65 1.65 0 0 0 1.82.33H9a1.65 1.65 0 0 0 1-1.51V3a2 2 0 0 1 4 0v.09a1.65 1.65 0 0 0 1 1.51 1.65 1.65 0 0 0 1.82-.33l.06-.06a2 2 0 0 1 2.83 2.83l-.06.06a1.65 1.65 0 0 0-.33 1.82V9a1.65 1.65 0 0 0 1.51 1H21a2 2 0 0 1 0 4h-.09a1.65 1.65 0 0 0-1.51 1z",
  };
  // Glifos del centro del orbe: cada estado tiene el suyo (se distinguen sin depender del color ni del movimiento).
  const GLIFO = {
    mic: "M12 4a2.5 2.5 0 0 0-2.5 2.5v5a2.5 2.5 0 0 0 5 0v-5A2.5 2.5 0 0 0 12 4zM6.5 11a5.5 5.5 0 0 0 11 0M12 16.5V20",
    esc: "M5 10v4M9 7v10M13 4v16M17 8v8M21 11v2",
    pausa: "M9 6v12M15 6v12",
    pensar: "M6 12h.01M12 12h.01M18 12h.01",
    habla: "M4 9v6h3l5 4V5L7 9H4zM16 9a4 4 0 0 1 0 6M18.5 6.5a8 8 0 0 1 0 11",
  };
  function orbe() {
    const ns = "http://www.w3.org/2000/svg";
    const capa = (cls) => el("i", { class: cls });
    const svg = (cls, hijo) => { const e = document.createElementNS(ns, "svg"); e.setAttribute("class", cls); e.setAttribute("aria-hidden", "true"); e.append(hijo); return e; };
    const circulo = (cls, r) => {
      const c = document.createElementNS(ns, "circle");
      c.setAttribute("cx", "50"); c.setAttribute("cy", "50"); c.setAttribute("r", String(r));
      const e = svg(cls, c); e.setAttribute("viewBox", "0 0 100 100"); return e;
    };
    const glifo = (k) => {
      const t = document.createElementNS(ns, "path"); t.setAttribute("d", GLIFO[k]);
      if (k === "pensar") t.setAttribute("stroke-width", "3.2");
      const e = svg("o-glifo g-" + k, t); e.setAttribute("viewBox", "0 0 24 24"); return e;
    };
    return el("div", { class: "orbe", "aria-hidden": "true" }, capa("o-halo"), capa("o-onda"), capa("o-onda o2"), circulo("o-marcas", 48),
      capa("o-fino"), capa("o-nivel"), capa("o-barrido"), capa("o-disco"), capa("o-aro"), circulo("o-seg", 47), capa("o-nucleo"),
      glifo("mic"), glifo("esc"), glifo("pausa"), glifo("pensar"), glifo("habla"));
  }

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
    static get observedAttributes() { return ["token-url", "servidor", "tema"]; }
    static get _utiles() { return { partirParaVoz, textoParaVoz, resumenBreve, nivelDe, suavizar, ultimoCorte, elegirVoz, normalizarFrase, buscarActivacion, comandoDe, interpretar, retrasoReinicio }; }  // para los tests

    constructor() {
      super();
      this._token = null;        // {valor, expiraMs}; solo en memoria, nunca en storage
      this._convId = null;
      this._ocupado = false;
      this._abort = null;
      this._iniciado = false;
      this._nombreSistema = "";
      this._nombreServidor = "";
      this._dictadoServidor = false;
      this._ttsServidor = false;  // el sistema tiene voz de servidor (/v1/estado: voz.respuesta)
      this._ttsPausaHasta = 0;    // tras un fallo, hasta cuándo se usa solo la voz del navegador
      this._cola = [];            // piezas por decir con voz de servidor: { texto, audio, alIniciar, alTerminar, gen }
      this._sonando = false;      // hay una pieza de la cola sonando
      this._audio = null;         // <audio> reutilizado
      this._abortTts = new AbortController();
      this._cacheTts = new Map(); // texto corto -> URL del audio
      this._vozAn = null; this._vozBuf = null; this._anIntentado = false; this._motivoRespaldo = "";
      this._finAudio = null; this._tPulso = 0;
      this._reco = null;
      this._leerAuto = false;
      this._leidoHasta = 0;
      this._pendientesVoz = 0;   // frases encoladas en speechSynthesis que aún no terminaron
      this._genVoz = 0;          // cambia al cortar la voz: ignora los eventos de lo cancelado
      this._leerCortado = false; // el usuario interrumpió la lectura de este turno (manos libres)
      // modo manos libres: estado y recursos (ver _mh* más abajo)
      this._niv = { activo: false, valor: 0, pulso: 0, escrito: -1, ult: 0, raf: 0, ctx: null, flujo: null, analizador: null, buf: null };
      this._t = null;            // tiempos del turno por voz (ver _metricas*)
      this._tAcuse = 0;          // temporizador del acuse inmediato
      this._nAcuse = 0;          // rota las frases
      this._mh = { estado: "apagado", reco: null, fallos: 0, ultimoError: "", siguiente: 0, idxActivacion: -1, tCierre: null, tInact: null, tReinicio: null };
      this.attachShadow({ mode: "open" });
    }

    get _servidor() {
      return (this.getAttribute("servidor") || ORIGEN_SCRIPT || location.origin).replace(/\/+$/, "");
    }

    connectedCallback() {
      console.info("[asistente] widget con voz del servidor: cola, pausa tras el acuse y diagnóstico");   // temporal: confirma qué versión tiene el navegador
      this._construir();
      this._vigilarTema();
      this._arrancar();
    }

    disconnectedCallback() {
      this._vigilarTema(false);
      if (this._ajFuera) document.removeEventListener("pointerdown", this._ajFuera, true);
      if (this._abort) this._abort.abort();
      this._detenerGrabacion(true);
      this._detenerReco(true);
      this._mhApagar("", true);
      this._nivelDetener();
      this._pararVoz();
    }

    attributeChangedCallback(nombre, viejo, nuevo) {
      if (nombre === "tema") { this._aplicarTema(); return; }   // solo repinta: no reinicia la sesión
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
      this._titulo = el("h1", { textContent: this.getAttribute("titulo") || NOMBRE_BASE });
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
      this._vista = "chat";   // «chat» | «voz» (la vista de voz solo existe con el modo voz encendido)
      // memoria por usuario: oculto hasta que /v1/estado diga `memoria: true`
      this._memBtn = el("button", { class: "accion memoria", type: "button", hidden: true, title: TEXTOS.memoria, "aria-label": TEXTOS.memoria, "aria-expanded": "false" }, icono("memoria"));
      this._memBtn.addEventListener("click", () => (this._memPanel.hidden ? this._memoriaAbrir() : this._memoriaCerrar()));
      // ajustes del usuario: engranaje (se oculta con ajustes="no")
      this._ajBtn = el("button", { class: "accion ajustes", type: "button", title: TEXTOS.ajustes, "aria-label": TEXTOS.ajustes, "aria-expanded": "false" }, icono("ajustes"));
      this._ajBtn.addEventListener("click", () => (this._ajPanel.hidden ? this._ajustesAbrir() : this._ajustesCerrar()));
      this._ajBtn.hidden = !this._ajustesActivos();
      this._aj = this._ajustesLeer();
      const barra = el("header", { class: "barra" }, ...(MOSTRAR_HISTORIAL ? [menu, this._titulo] : [this._titulo, this._manos, this._memBtn, this._altavoz, this._ajBtn, otra]));

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
      this._mhEtiqueta = el("span", { class: "mh-estado", role: "status", "aria-live": "polite" });
      this._mhCampo = el("div", { class: "mh-campo" });     // lo dictado hasta ahora (en la vista de voz el campo de texto no se ve)
      this._mhParcial = el("span", { class: "mh-parcial" });
      this._mhEnviar = el("button", { type: "button", class: "mh-enviar", textContent: TEXTOS.enviar });
      this._mhCancelar = el("button", { type: "button", class: "mh-cancelar", textContent: TEXTOS.cancelar });
      this._mhApagarBtn = el("button", { type: "button", class: "mh-apagar", textContent: TEXTOS.apagarManosLibres });
      this._mhEnviar.addEventListener("click", () => this._mhEnviarTexto());
      this._mhCancelar.addEventListener("click", () => this._mhDescartar());
      this._mhApagarBtn.addEventListener("click", () => this._mhApagar(""));
      this._mhCaja = el("div", { class: "mh", hidden: true, "data-estado": "armado" }, orbe(),
        el("div", { class: "mh-texto" }, this._mhEtiqueta, this._mhCampo, this._mhParcial),
        el("div", { class: "mh-botones" }, this._mhEnviar, this._mhCancelar, this._mhApagarBtn),
        el("div", { class: "mh-priv", textContent: TEXTOS.mhPrivacidad }));
      this._entrada.addEventListener("input", () => this._mhPintarCampo());
      // vista de voz: lo que te dice el asistente (resumen) y el paso al chat
      this._mhDicho = el("div", { class: "dicho" });
      this._verChat = el("button", { type: "button", class: "ver-chat", textContent: TEXTOS.verChat });
      this._verChat.title = TEXTOS.mhChatCompleto;
      this._verChat.addEventListener("click", () => { this._vista = "chat"; this._mhActividad(); this._aplicarVista(true); });
      this._escena = el("section", { class: "escena", "aria-label": TEXTOS.escenaVoz }, this._mhDicho, this._verChat);
      this.addEventListener("keydown", (e) => { if (e.key === "Escape" && this._mhActivo()) this._mhApagar(""); });
      this._form = form;
      this._cajaEntrada = el("div", { class: "entrada" }, this._mhCaja, form, this._avisoVoz, el("div", { class: "pie", textContent: TEXTOS.pie }));
      this._construirMemoria();
      this._construirAjustes();
      const principal = el("main", { class: "principal" }, barra, this._scroll, this._escena, this._cajaEntrada, this._memPanel, this._ajPanel);

      this._aviso = el("div", { class: "aviso", textContent: TEXTOS.noDisponible });
      r.append(...(MOSTRAR_HISTORIAL ? [lateral, velo] : []), principal, this._aviso);
      this._mostrarBienvenida();
      this._aplicarNombre();
    }

    // — tema (atributo `tema`: claro | oscuro | auto, por defecto auto = el del sistema) —
    _vigilarTema(activar = true) {
      const mq = window.matchMedia ? window.matchMedia("(prefers-color-scheme: dark)") : null;
      if (this._mqTema) this._mqTema.removeEventListener("change", this._alCambiarTema);
      this._mqTema = null;
      if (!activar || !mq) { this._aplicarTema(); return; }
      this._alCambiarTema = () => this._aplicarTema();       // el usuario cambió el tema del sistema con la página abierta
      mq.addEventListener("change", this._alCambiarTema);
      this._mqTema = mq;
      this._aplicarTema();
    }

    _aplicarTema() {
      if (!this._raiz) return;
      const tema = (this.getAttribute("tema") || "auto").trim().toLowerCase();
      const delSistema = !!(this._mqTema && this._mqTema.matches);
      this._raiz.classList.toggle("oscuro", tema === "oscuro" || (tema !== "claro" && delSistema));
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
          this._memoria = e.memoria === true;
          const voz = e.voz || {};
          this._maxAudioS = Number(voz.max_audio_s) > 0 ? Number(voz.max_audio_s) : 60;
          this._dictadoServidor = voz.dictado === true && puedeGrabar();
          this._ttsServidor = voz.respuesta === true;
          this._nombreServidor = nombreLimpio(e.nombre_asistente);
          this._aplicarNombre();
        }
      } catch { /* sin acceso: se muestra el aviso */ }
      this._actualizarVoz();
      this._arrancarEnVoz();
      this._memBtn.hidden = !(habilitado && this._memoria);
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
      this._altavoz.hidden = !this._hablaPosible();
      // manos libres: solo con el reconocimiento del navegador (la palabra de activación no existe en el STT del servidor)
      this._manos.hidden = !(this._motorDictado() === "navegador" && this._hablaPosible() && window.isSecureContext !== false);
      if (this._manos.hidden) this._mhApagar("", true);
    }

    // Por defecto el widget abre en modo voz (si hay) y el usuario pasa al chat cuando quiera. Una sola vez, al cargar.
    // Atributo modo-inicial="chat" o el ajuste «Abrir en modo voz» lo desactivan. El micrófono lo gobierna el navegador (permiso).
    _arrancarEnVoz() {
      if (this._inicioVozHecho) return;
      this._inicioVozHecho = true;
      if ((this.getAttribute("modo-inicial") || "auto").toLowerCase() === "chat") return;
      if (this._ajustesActivos() && this._aj && !this._aj.iniciarVoz) return;
      if (!this._manos.hidden && !this._mhActivo()) this._conmutarManosLibres();
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
    // Cómo se llama el asistente: lo que el usuario eligió (si hay panel de ajustes) > atributo > sistema > «Asistente».
    _nombrePorDefecto() { return nombreLimpio(this.getAttribute("nombre")) || this._nombreServidor || NOMBRE_BASE; }
    _nombre() { return (this._ajustesActivos() && this._aj && this._aj.nombre) || this._nombrePorDefecto(); }

    _aplicarNombre() {
      const n = this._nombre();
      if (!this.getAttribute("titulo")) this._titulo.textContent = this._nombreSistema ? n + " · " + this._nombreSistema : n;
      this._aviso.textContent = TEXTOS.noDisponible.replace("{n}", n);
      if (this._ajMotorLeyenda) this._ajMotorLeyenda.textContent = TEXTOS.ajMotor.replace("{n}", n);
      if (this._mh && this._mhActivo()) this._mhPintar();   // la etiqueta «Decí {p}» sigue al nombre
      if (this._ajNombre) this._ajNombre.placeholder = this._nombrePorDefecto();
    }

    _mhActivo() { return this._mh.estado !== "apagado"; }
    // Despierta el modo voz: `palabra-activacion` si el anfitrión la fijó; si no, el nombre del asistente (decir «Lucas»
    // basta si se llama Lucas). Sin nombre propio, «asistente».
    _palabra() {
      return this.getAttribute("palabra-activacion")?.trim() || (this._nombre() !== NOMBRE_BASE ? this._nombre() : PALABRA_ACTIVACION);
    }

    _conmutarManosLibres() {
      if (this._mhActivo()) {                                  // ya encendido: el botón de la barra alterna entre «Voz» y «Chat»
        this._vista = this._vista === "chat" ? "voz" : "chat"; this._mhActividad(); this._aplicarVista(true);
        return;
      }
      if (!reconocimiento() || this._ocupado) return;
      this._detenerReco(true); this._detenerGrabacion(true);   // un solo micrófono a la vez
      this._pararVoz();
      this._avisarVoz("");
      this._mh.fallos = 0; this._mh.ultimoError = "";
      this._vista = "voz";
      this._mhEstado("armado");
      this._mhIniciarReco();                                   // dentro del gesto del usuario (el navegador lo exige)
      this._nivelIniciar();
    }

    // `motivo`: "" (lo pidió el usuario), "voz", "inactividad" o un código de ERRORES_VOZ.
    _mhApagar(motivo, silencioso = false) {
      const mh = this._mh;
      if (!this._mhActivo()) return;
      clearTimeout(mh.tReinicio); mh.tReinicio = null;
      const r = mh.reco; mh.reco = null;
      if (r) { try { r.abort(); } catch { /* ya terminó */ } }
      this._leerCortado = true; this._pararVoz();
      clearTimeout(this._tAcuse);
      this._nivelDetener();
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
      if (!activo) { this._vista = "chat"; this._mhDicho.replaceChildren(); }
      this._mhEtiqueta.textContent = ({
        armado: TEXTOS.mhArmado, capturando: TEXTOS.mhCapturando, confirmando: TEXTOS.mhConfirmando, respondiendo: TEXTOS.mhRespondiendo,
      }[e] || "").replace("{p}", p);
      this._mhParcial.textContent = "";
      this._mhEnviar.hidden = this._mhCancelar.hidden = !this._confirmarActivo() || !(e === "capturando" || e === "confirmando");
      this._manos.setAttribute("aria-pressed", String(activo));
      const t = activo ? TEXTOS.volverVoz : TEXTOS.manosLibres;
      this._manos.title = t; this._manos.setAttribute("aria-label", t);
      this._mhFase();
      this._mhPintarCampo();
      this._aplicarVista();
    }

    // Estado visual del orbe: «respondiendo» se muestra como «procesando» (esperando) o «hablando» (leyendo el resumen).
    _mhFase() {
      const e = this._mh.estado;
      this._mhCaja.dataset.estado = e === "respondiendo" ? (this._pendientesVoz > 0 ? "hablando" : "procesando") : (e === "apagado" ? "armado" : e);
    }

    _mhPintarCampo() { this._mhCampo.textContent = this._mhActivo() ? this._entrada.value : ""; }

    // Cambia entre el chat y la vista de voz (solo hay vista de voz con el modo encendido). El panel del micrófono es el
    // mismo en ambas: en la escena es el centro; en el chat va compacto sobre la entrada (siempre visible mientras el micrófono está abierto).
    _aplicarVista(foco = false) {
      const voz = this._mhActivo() && this._vista === "voz";
      this._raiz.classList.toggle("vista-voz", voz);
      if (voz) { if (this._mhCaja.parentNode !== this._escena) this._escena.insertBefore(this._mhCaja, this._mhDicho); }
      else if (this._mhCaja.parentNode !== this._cajaEntrada) this._cajaEntrada.insertBefore(this._mhCaja, this._form);
      if (foco) (voz ? this._verChat : this._entrada).focus();
      // el botón de la barra lleva a la otra vista: «Chat» desde la voz, «Voz» desde el chat
      const t = voz ? TEXTOS.chatBoton : this._mhActivo() ? TEXTOS.volverVoz : TEXTOS.manosLibres;
      this._manos.replaceChildren(icono(voz ? "chat" : "manos"), el("span", { textContent: voz ? TEXTOS.chatBoton : TEXTOS.manosLibres }));
      this._manos.title = t; this._manos.setAttribute("aria-label", t);
      this._tarjetaPosicionar();
      if (!voz) this._bajar();
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
      if (this._mh.estado === "capturando" && !this._mhCaja.classList.contains("pulso")) {   // un golpe del orbe por cada resultado del reconocimiento
        this._mhCaja.classList.add("pulso"); setTimeout(() => this._mhCaja.classList.remove("pulso"), 400);
      }
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
      if (!this._confirmarActivo()) this._mhEnviarTexto();
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

    // — volumen del orbe —
    // El nivel del MICRÓFONO es real: un AnalyserNode local sobre un segundo flujo de audio (no se graba ni se envía a ningún
    // lado). Si el navegador no lo da (permiso, micrófono ocupado, sin Web Audio) el orbe sigue con sus animaciones y el
    // reconocimiento no se entera. Para la voz del ASISTENTE el navegador no entrega amplitud: el orbe da un pulso por cada
    // palabra que dice (evento `boundary`), que sigue el ritmo real del habla pero no su volumen. Con
    // prefers-reduced-motion no se hace nada. Atributo `orbe-volumen="no"` lo apaga (no se abre el segundo flujo).
    async _nivelIniciar() {
      const n = this._niv;
      if (n.activo) return;
      if (window.matchMedia && window.matchMedia("(prefers-reduced-motion: reduce)").matches) return;
      n.activo = true;
      const AC = window.AudioContext || window.webkitAudioContext;
      const quiere = (this.getAttribute("orbe-volumen") || "auto").toLowerCase() !== "no";
      if (quiere && AC && navigator.mediaDevices && navigator.mediaDevices.getUserMedia) {
        try {
          const flujo = await navigator.mediaDevices.getUserMedia({ audio: true });
          if (!n.activo) { flujo.getTracks().forEach((t) => t.stop()); return; }   // se apagó mientras se pedía el permiso
          const ctx = new AC();
          const fuente = ctx.createMediaStreamSource(flujo), analizador = ctx.createAnalyser();
          analizador.fftSize = 512; fuente.connect(analizador);
          Object.assign(n, { flujo, ctx, analizador, buf: new Uint8Array(analizador.fftSize) });
        } catch { /* sin nivel de micrófono */ }
      }
      if (n.activo && !n.raf) this._nivelBucle();
    }

    _nivelBucle() {
      const n = this._niv;
      const paso = (t) => {
        n.raf = requestAnimationFrame(paso);
        if (t - n.ult < 33) return;                            // ~30 fotogramas por segundo bastan y gastan menos batería
        const dt = Math.min(0.1, (t - n.ult) / 1000); n.ult = t;
        const e = this._mhCaja.dataset.estado;
        let objetivo = 0;
        if (n.analizador && (e === "armado" || e === "capturando" || e === "confirmando")) {   // mientras el asistente habla, el micrófono lo oiría a él
          n.analizador.getByteTimeDomainData(n.buf);
          objetivo = nivelDe(n.buf);
        }
        n.pulso = Math.max(0, n.pulso - dt * 2.2);
        if (e === "hablando") {
          objetivo = Math.max(objetivo, n.pulso);
          if (this._vozAn) { this._vozAn.getByteTimeDomainData(this._vozBuf); objetivo = Math.max(objetivo, nivelDe(this._vozBuf)); }   // voz del servidor: volumen real
        }
        n.valor = suavizar(n.valor, objetivo, dt);
        const v = Math.round(n.valor * 100) / 100;
        if (v !== n.escrito) { n.escrito = v; this._mhCaja.style.setProperty("--nivel", String(v)); }
      };
      n.raf = requestAnimationFrame(paso);
    }

    _nivelPulso(x) { this._niv.pulso = Math.max(this._niv.pulso, x); }

    _nivelDetener() {
      const n = this._niv;
      n.activo = false;
      if (n.raf) cancelAnimationFrame(n.raf);
      if (n.flujo) n.flujo.getTracks().forEach((t) => { try { t.stop(); } catch { /* ya parado */ } });
      if (n.ctx) { try { n.ctx.close(); } catch { /* ya cerrado */ } }
      Object.assign(n, { raf: 0, flujo: null, ctx: null, analizador: null, buf: null, valor: 0, pulso: 0, escrito: -1, ult: 0 });
      if (this._mhCaja) this._mhCaja.style.removeProperty("--nivel");
    }

    // — acuse inmediato —
    // El silencio entre «enviar» y el resumen (mediana ≈ 2 s con el modelo actual, más si hay varias tools) se siente roto por voz.
    // Pasado MH_ACUSE_MS sin nada que decir se dice una frase corta; si el resumen llega antes, no se dice nada. Sin costo de LLM
    // y sin datos: es texto fijo. Nunca con una acción propuesta (ahí se dice la frase del sistema), ni tras interrumpir, ni si
    // el turno ya terminó o el modo se apagó. `acuse="no"` lo quita.
    _acuseProgramar() {
      clearTimeout(this._tAcuse);
      if (!this._acuseActivo() || !this._hablaPosible()) return;
      const t = this._t;
      this._tAcuse = setTimeout(() => {
        this._tAcuse = 0;
        if (!this._mhActivo() || this._t !== t || !this._ocupado || this._dichoTurno || this._propuestaTurno || this._leerCortado) return;
        const frases = TEXTOS.mhAcuse;
        t.acuse = performance.now();
        this._decir(frases[this._nAcuse++ % frases.length], undefined, undefined, { sinRespaldo: true, pausaMs: MH_ACUSE_PAUSA_MS });
      }, MH_ACUSE_MS);
    }

    // — tiempos del turno por voz: cuánto tarda en oírse algo desde «enviar» —
    // Evento `asistente:metricas` (ver contrato 7.3): acuse_ms (null si no hubo), primer_delta_ms, voz_ms (llegada del resumen), habla_ms (empieza a sonar),
    // tts_ms (de tener el texto a que suene) y los tiempos del servidor. No incluye texto ni datos del usuario.
    _metricasIniciar() { this._t = { envio: performance.now(), hablara: false, fin: false, emitido: false, servidor: null }; }

    _marca(nombre) { const t = this._t; if (t && t[nombre] === undefined) t[nombre] = performance.now(); }

    _metricasIntentar(forzar = false) {
      const t = this._t;
      if (!t || t.emitido || !t.fin || !(forzar || t.habla !== undefined || !t.hablara)) return;
      t.emitido = true;
      const ms = (x) => (x === undefined ? null : Math.round(x - t.envio));
      const detalle = {
        canal: "voz", fuente: t.fuente || null, acuse_ms: ms(t.acuse), primer_delta_ms: ms(t.primer_delta), voz_ms: ms(t.voz), habla_ms: ms(t.habla),
        tts_ms: t.habla !== undefined && t.texto !== undefined ? Math.round(t.habla - t.texto) : null, servidor: t.servidor,
      };
      try { console.debug("[asistente] tiempos del turno por voz", detalle); } catch { /* sin consola */ }
      this.dispatchEvent(new CustomEvent("asistente:metricas", { detail: detalle, bubbles: true, composed: true }));
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

    // — voz del asistente: servidor (ElevenLabs u otro) con respaldo en el navegador —
    // Lo que el usuario eligió en el panel manda sobre el atributo del anfitrión (salvo ajustes="no").
    _prefRespuesta() {
      if (this._ajustesActivos() && this._aj && this._aj.motor !== "auto") return this._aj.motor;
      return (this.getAttribute("voz-respuesta") || "auto").toLowerCase();
    }
    // ¿hay que decir «enviar» (o pulsar el botón) antes de mandar lo dictado? Sin ajustes, manda la constante del producto.
    _confirmarActivo() {
      if (!MANOS_LIBRES_CONFIRMAR) return false;
      return !(this._ajustesActivos() && this._aj && !this._aj.confirmar);
    }
    _volumen() { return this._ajustesActivos() && this._aj ? this._aj.volumen : 1; }
    _acuseActivo() {
      if (this._ajustesActivos() && this._aj && !this._aj.acuse) return false;
      return (this.getAttribute("acuse") || "auto").toLowerCase() !== "no";
    }
    _navegadorOk() { return puedeHablar() && this._prefRespuesta() !== "servidor"; }
    _hablaPosible() { return (this._ttsServidor && this._prefRespuesta() !== "navegador") || this._navegadorOk(); }
    // ¿se pide la próxima pieza al servidor? Tras un fallo reciente, no.
    _ttsActivo() { return this._ttsServidor && this._prefRespuesta() !== "navegador" && Date.now() >= this._ttsPausaHasta; }

    // Línea de tiempo de la voz en la consola (temporal, para diagnosticar). Solo largos y tiempos: nunca el texto.
    _tl(msg) { console.info("[asistente] voz " + Math.round(performance.now()) + "ms " + msg); }

    // Encola `texto` (ya sin Markdown); varias llamadas se dicen en orden. `alTerminar` al acabar esta pieza.
    // `opciones.sinRespaldo`: si la voz del servidor no llega o falla, esta pieza no se dice con la del navegador
    // (el acuse es relleno: mejor en silencio que con otra voz). `opciones.pausaMs`: silencio tras esta pieza
    // antes de decir la siguiente (la cola espera ese tiempo; si nada la sigue, no cambia nada).
    _decir(texto, alTerminar, alIniciar, opciones = {}) {
      if (!this._hablaPosible() || !texto.trim()) { if (alTerminar) alTerminar(); return; }
      // Sin voz de servidor y sin nada en cola: directo al navegador (cola propia de speechSynthesis).
      if (!this._ttsActivo() && !this._sonando && !this._cola.length) {
        if (!this._navegadorOk()) { if (alTerminar) alTerminar(); return; }
        const gen = this._genVoz;
        this._pendientesVoz++;
        const fin = () => {
          if (gen === this._genVoz) this._pendientesVoz = Math.max(0, this._pendientesVoz - 1);
          if (alTerminar) alTerminar();
          this._mhFase();
          this._mhRevisarFin();
        };
        this._hablarNavegador(texto, alIniciar, fin);
        this._mhFase();
        return;
      }
      // Cola: cada pieza pide su audio de inmediato (en paralelo) y suenan en orden.
      const gen = this._genVoz, usarServidor = this._ttsActivo();
      const trozos = usarServidor ? partirParaVoz(texto) : [texto];
      trozos.forEach((trozo, i) => {
        this._pendientesVoz++;
        this._tl(`encola ${trozo.length} car${opciones.sinRespaldo ? " (acuse)" : ""}${usarServidor ? "" : " [navegador]"}; cola=${this._cola.length} sonando=${this._sonando}`);
        this._cola.push({
          texto: trozo, gen,
          audio: usarServidor ? this._pedirAudio(trozo, gen, opciones.sinRespaldo === true) : null,
          alIniciar: i === 0 ? alIniciar : undefined,
          alTerminar: i === trozos.length - 1 ? alTerminar : undefined,
          sinRespaldo: opciones.sinRespaldo === true,
          pausaMs: i === trozos.length - 1 ? opciones.pausaMs || 0 : 0,
        });
      });
      this._mhFase();
      this._siguienteVoz();
    }

    _hablarNavegador(texto, alIniciar, alFin) {
      const u = new window.SpeechSynthesisUtterance(texto);
      const idioma = this.getAttribute("idioma") || "es-UY";
      // La voz elegida se recuerda: sin esto, si la lista de voces aún no cargó, una frase sale con otra voz.
      let v = elegirVoz(window.speechSynthesis.getVoices(), idioma, this.getAttribute("voz"));
      if (v) this._vozNav = v; else v = this._vozNav || null;
      if (v) { u.voice = v; u.lang = v.lang; } else u.lang = idioma;
      u.volume = this._volumen();
      u.onend = alFin; u.onerror = alFin;
      if (alIniciar) u.onstart = alIniciar;
      u.onboundary = () => { if (this._mhActivo()) this._nivelPulso(0.5 + Math.random() * 0.4); };
      window.speechSynthesis.speak(u);
    }

    // Pide el audio de una pieza; devuelve una promesa de URL (blob) o null si falló (nunca rechaza).
    async _pedirAudio(texto, gen, fija = false) {
      const corto = fija && texto.length <= TTS_CACHE_CHARS;
      if (corto && this._cacheTts.has(texto)) return this._cacheTts.get(texto);
      const senal = this._abortTts.signal;
      try {
        const pedir = () => this._conToken((h) => fetch(`${this._servidor}/v1/voz/sintetizar`, {
          method: "POST", headers: { ...h, "Content-Type": "application/json" }, signal: senal,
          body: JSON.stringify({ texto, idioma: this.getAttribute("idioma") || undefined }),
        }));
        let r = await pedir();
        // Un fallo pasajero (429/5xx) se reintenta una vez: caer a la voz del navegador a mitad de una respuesta cambia la voz.
        if (!r.ok && (r.status === 429 || r.status >= 500) && r.status !== 503) {
          await new Promise((res) => setTimeout(res, 700));
          if (gen === this._genVoz) r = await pedir();
        }
        if (!r.ok) {
          // 413/422: esa pieza no sirve, pero el servidor está bien. Cualquier otro fallo lo pausa un rato.
          console.warn("[asistente] /v1/voz/sintetizar respondió", r.status);
          if (r.status === 503) this._ttsServidor = false;
          else if (r.status !== 413 && r.status !== 422) this._ttsPausaHasta = Date.now() + TTS_PAUSA_MS;
          return null;
        }
        const blob = await r.blob();
        this._tl(`audio listo ${texto.length} car, ${blob.size} bytes, ${blob.type}`);
        const url = URL.createObjectURL(blob);
        if (gen !== this._genVoz) { URL.revokeObjectURL(url); return null; }
        if (corto) {
          this._cacheTts.set(texto, url);
          if (this._cacheTts.size > TTS_CACHE_MAX) {
            const [viejo, u] = this._cacheTts.entries().next().value;
            this._cacheTts.delete(viejo); URL.revokeObjectURL(u);
          }
        }
        return url;
      } catch (e) {
        if (!(e && e.name === "AbortError")) { console.warn("[asistente] /v1/voz/sintetizar falló:", e && e.name); this._ttsPausaHasta = Date.now() + TTS_PAUSA_MS; }
        return null;
      }
    }

    async _siguienteVoz() {
      if (this._sonando) return;
      const pieza = this._cola.shift();
      if (!pieza) return;
      this._sonando = true;
      this._tl(`toma ${pieza.texto.length} car; quedan ${this._cola.length}`);
      const gen = pieza.gen;
      const terminar = () => {
        if (gen !== this._genVoz) return;   // se cortó la voz: _pararVoz ya limpió todo
        this._tl(`termina ${pieza.texto.length} car${pieza.pausaMs ? "; pausa " + pieza.pausaMs + "ms" : ""}`);
        if (!pieza.pausaMs) this._sonando = false;   // con pausa, la cola sigue «ocupada» hasta que pase
        this._pendientesVoz = Math.max(0, this._pendientesVoz - 1);
        if (pieza.alTerminar) pieza.alTerminar();
        this._mhFase();
        this._mhRevisarFin();
        if (!pieza.pausaMs) { this._siguienteVoz(); return; }
        setTimeout(() => { if (gen === this._genVoz) { this._sonando = false; this._siguienteVoz(); } }, pieza.pausaMs);
      };
      let url = null;
      if (pieza.audio) url = await pieza.audio;
      if (gen !== this._genVoz) return;
      this._motivoRespaldo = pieza.audio ? "el servidor no devolvió audio" : "voz del servidor en pausa o desactivada";
      if (url && await this._sonarAudio(url, pieza, gen)) { if (!this._cacheTts.has(pieza.texto)) URL.revokeObjectURL(url); return terminar(); }
      if (gen !== this._genVoz) return;
      if (this._navegadorOk() && !pieza.sinRespaldo) {   // respaldo
        console.warn("[asistente] voz del navegador en lugar de la del servidor:", this._motivoRespaldo);
        this._hablarNavegador(pieza.texto, pieza.alIniciar, terminar);
      } else terminar();
    }

    // Reproduce `url`; resuelve true al terminar (o si falla ya empezado) y false si no llegó a sonar.
    // Si el primer `play()` falla antes de sonar (se ha visto en la primera reproducción de la página), se reintenta una vez.
    async _sonarAudio(url, pieza, gen) {
      await this._prepararAnalizador();
      if (gen !== this._genVoz) return true;
      if (await this._intentarAudio(url, pieza)) return true;
      if (gen !== this._genVoz) return true;
      console.warn("[asistente] el audio del servidor no arrancó (" + this._motivoRespaldo + "); se reintenta");
      try { this._audio.pause(); } catch { /* sin audio */ }
      await new Promise((r) => setTimeout(r, 150));
      if (gen !== this._genVoz) return true;
      const ok = await this._intentarAudio(url, pieza);
      if (!ok) console.warn("[asistente] el audio del servidor no arrancó tras reintentar:", this._motivoRespaldo);
      return ok;
    }

    _intentarAudio(url, pieza) {
      return new Promise((resolve) => {
        const a = this._audio;
        let empezo = false;
        const fin = (ok, motivo) => {
          if (!ok) this._motivoRespaldo = motivo || "error al reproducir el audio";
          a.onplaying = a.onended = a.onerror = null; this._finAudio = null;
          clearInterval(this._tPulso); this._tPulso = 0;
          resolve(ok);
        };
        this._finAudio = () => fin(true);
        const arrancar = () => {
          if (empezo) return;
          empezo = true;
          this._tl(`suena ${pieza.texto.length} car, dura ${isFinite(a.duration) ? a.duration.toFixed(2) : "?"}s`);
          if (pieza.alIniciar) pieza.alIniciar();
          if (!this._vozAn && !this._tPulso) this._tPulso = setInterval(() => { if (this._mhActivo()) this._nivelPulso(0.5 + Math.random() * 0.4); }, 140);
        };
        a.onplaying = arrancar;
        a.onended = () => { this._tl(`ended t=${a.currentTime.toFixed(2)}s`); fin(true); };
        a.onerror = () => fin(empezo, "el navegador no pudo decodificar el audio");
        a.src = url;
        a.volume = this._volumen();
        const p = a.play();
        if (p && p.catch) p.catch((e) => {
          const nombre = e && e.name;
          // AbortError: Chrome a veces rechaza el `play()` de la primera reproducción aunque el audio ya esté sonando.
          // Si a los 150 ms sigue sonando, no es un fallo (y reiniciarlo se oiría como un tartamudeo).
          if (nombre === "AbortError") {
            setTimeout(() => {
              if (!a.paused && !a.ended && a.currentTime > 0) arrancar();
              else fin(false, "play() rechazado: AbortError");
            }, 150);
            return;
          }
          fin(false, "play() rechazado: " + nombre);   // p. ej. NotAllowedError (autoplay): cae a la voz del navegador
        });
      });
    }

    // El <audio> y, solo si el orbe está activo, un analizador para que siga el volumen real de la voz del servidor.
    // Una vez conectado a Web Audio el sonido pasa por el contexto: solo se conecta si el contexto arranca.
    async _prepararAnalizador() {
      if (!this._audio) this._audio = new Audio();
      if (this._anIntentado || !this._niv.activo) return;
      this._anIntentado = true;
      const AC = window.AudioContext || window.webkitAudioContext;
      if (!AC) return;
      let ctx = null;
      try {
        ctx = new AC();
        if (ctx.state !== "running") await Promise.race([ctx.resume(), new Promise((r) => setTimeout(r, 400))]);   // sin gesto previo puede no resolverse
        if (ctx.state !== "running") { ctx.close(); return; }
        const fuente = ctx.createMediaElementSource(this._audio), an = ctx.createAnalyser();
        an.fftSize = 512; fuente.connect(an); an.connect(ctx.destination);
        this._vozAn = an; this._vozBuf = new Uint8Array(an.fftSize); this._vozCtx = ctx;
      } catch { try { if (ctx) ctx.close(); } catch { /* ya cerrado */ } }
    }

    _pararVoz() {
      if (this._sonando || this._cola.length) console.info("[asistente] voz cortada por:", (new Error().stack.split("\n")[2] || "").trim());
      this._genVoz++; this._pendientesVoz = 0;
      const pendientes = this._cola.splice(0);
      this._abortTts.abort(); this._abortTts = new AbortController();
      this._sonando = false;
      clearInterval(this._tPulso); this._tPulso = 0;
      if (this._audio) { try { this._audio.pause(); } catch { /* sin audio */ } }
      if (this._finAudio) this._finAudio();
      for (const p of pendientes) { if (p.alTerminar) { try { p.alTerminar(); } catch { /* callback ajeno */ } } }
      if (this._mhCaja) this._mhFase();
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
      if (!this._hablaPosible() || !md.trim()) return;
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
      this._mhFase();
      if (!si) this._mhRevisarFin();
    }

    async _enviarMensaje(texto) {
      this._pararVoz();
      // un turno nuevo empieza sin «interrumpido» (decir la palabra de activación para dictar lo deja en true hasta la respuesta)
      this._dichoTurno = false; this._propuestaTurno = false; this._leerCortado = false; this._mhDicho.replaceChildren();
      if (this._mhActivo()) { this._metricasIniciar(); this._acuseProgramar(); } else this._t = null;
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
      const canalVoz = this._mhActivo();   // en el modo voz el asistente agrega un resumen hablado (la respuesta completa va al chat igual)
      const cuerpo = JSON.stringify({ conversacion_id: this._convId, mensaje: texto, canal: canalVoz ? "voz" : "texto", zona_horaria: zonaHoraria() });
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
      const leer = this._leerAuto && !canalVoz && this._hablaPosible();   // lectura automática de la respuesta completa (no en el modo voz)
      const hablarVoz = canalVoz && this._hablaPosible();                 // modo voz: se dice el resumen, aunque la lectura automática esté apagada
      const pintar = () => {
        const acciones = burbuja.querySelector(".acciones");
        burbuja.replaceChildren(); markdown(acumulado, burbuja);
        if (acciones) burbuja.append(acciones);
        this._bajar();
      };
      await leerSSE(r.body, (evento, datos) => {
        switch (evento) {
          case "delta":
            this._marca("primer_delta");
            acumulado += datos.texto || ""; pintar();
            if (leer && !this._leerCortado) this._leerIncremental(acumulado, false);
            break;
          case "voz": this._marca("voz"); if (hablarVoz) this._resumenHablado(datos.texto, "resumen"); break;
          case "tool":
            estado.textContent = TEXTOS.consultando + "… " + (datos.herramientas || []).join(", ");
            if (!estado.isConnected) burbuja.append(estado);
            break;
          case "ui": this._acciones(datos.acciones || [], burbuja); break;
          case "confirmacion": this._confirmacion(datos); break;
          case "done":
            if (datos.conversacion_id) { this._convId = datos.conversacion_id; this._recordar(); }
            if (this._t) this._t.servidor = datos.tiempos_ms || null;
            break;
          case "token_expirado": resultado = "token_expirado"; break;
          case "error":
            if (!acumulado) burbuja.remove(); else estado.remove();
            this._error(datos.codigo); resultado = "error"; break;
        }
      });
      estado.remove();
      if (resultado === "ok" && !acumulado.trim() && !this._propuestaTurno) { burbuja.remove(); this._error("respuesta_vacia"); resultado = "error"; }
      if (resultado === "ok" && acumulado.trim()) {
        if (leer && !this._leerCortado) this._leerIncremental(acumulado, true);
        if (hablarVoz && !this._leerCortado) this._resumenHablado(resumenBreve(acumulado), "respaldo");   // respaldo: el modelo no mandó su resumen
        this._botonEscuchar(burbuja, acumulado);
      }
      if (this._t) {   // después de pedir la voz de respaldo: así sabe si hay que esperar a que empiece a sonar
        this._t.fin = true;
        this._metricasIntentar();
        const t = this._t;
        setTimeout(() => { if (this._t === t) this._metricasIntentar(true); }, 3000);   // algunos navegadores no avisan cuándo empieza a sonar
      }
      return resultado;
    }

    // Lo que se dice en el modo voz (resumen del modelo o, si falta, las primeras oraciones); también se muestra en la vista de voz.
    // Una sola vez por turno, y nunca si ese turno propuso una acción (ahí se dice la frase del sistema, ver _confirmacion).
    _resumenHablado(texto, fuente = "resumen") {
      if (typeof texto !== "string" || !texto.trim() || this._dichoTurno || this._propuestaTurno || this._leerCortado) return;
      this._dichoTurno = true;
      this._mostrarDicho(texto.trim());
      const t = this._t;
      if (t) { t.hablara = true; t.fuente = fuente; t.texto = performance.now(); }
      this._decir(textoParaVoz(texto), undefined, () => { this._marca("habla"); this._metricasIntentar(); });
    }

    _mostrarDicho(texto) {
      this._mhDicho.replaceChildren(el("small", { textContent: TEXTOS.mhDicho }), document.createTextNode(texto));
    }

    // — ajustes del usuario: engranaje y panel (se guardan en localStorage, por servidor) —
    _ajustesActivos() { return (this.getAttribute("ajustes") || "auto").toLowerCase() !== "no"; }

    _ajustesLeer() {
      const aj = { ...AJUSTES_BASE };
      try {
        const g = JSON.parse(localStorage.getItem(CLAVE_AJUSTES + this._servidor) || "{}");
        aj.nombre = nombreLimpio(g.nombre);
        if (MOTORES.includes(g.motor)) aj.motor = g.motor;
        if (typeof g.volumen === "number" && g.volumen >= 0 && g.volumen <= 1) aj.volumen = g.volumen;
        if (typeof g.acuse === "boolean") aj.acuse = g.acuse;
        if (typeof g.confirmar === "boolean") aj.confirmar = g.confirmar;
        if (typeof g.iniciarVoz === "boolean") aj.iniciarVoz = g.iniciarVoz;
      } catch { /* sin storage o JSON roto: valores por defecto */ }
      return aj;
    }

    _ajustesGuardar() {
      try {
        const igual = Object.keys(AJUSTES_BASE).every((k) => this._aj[k] === AJUSTES_BASE[k]);
        if (igual) localStorage.removeItem(CLAVE_AJUSTES + this._servidor);
        else localStorage.setItem(CLAVE_AJUSTES + this._servidor, JSON.stringify(this._aj));
      } catch { /* sin storage: vale para esta sesión */ }
    }

    _construirAjustes() {
      const radio = (valor, texto) => {
        const i = el("input", { type: "radio", name: "aj-motor", value: valor });
        i.addEventListener("change", () => { if (i.checked) this._ajustesCambiar({ motor: valor }); });
        return { i, fila: el("label", { class: "aj-op" }, i, el("span", { textContent: texto })) };
      };
      this._ajNombre = el("input", { type: "text", id: "aj-nombre", maxlength: String(NOMBRE_MAX), autocomplete: "off" });
      this._ajNombre.addEventListener("input", () => this._ajustesCambiar({ nombre: nombreLimpio(this._ajNombre.value) }));
      this._ajFilaNombre = el("div", { class: "aj-fila" }, el("label", { class: "aj-tit", for: "aj-nombre", textContent: TEXTOS.ajNombre }), this._ajNombre);
      this._ajRadios = { navegador: radio("navegador", TEXTOS.ajMotorNavegador), servidor: radio("servidor", TEXTOS.ajMotorServidor) };
      this._ajFilaMotor = el("fieldset", { class: "aj-fila" }, (this._ajMotorLeyenda = el("legend", { textContent: TEXTOS.ajMotor.replace("{n}", this._nombre()) })),
        this._ajRadios.navegador.fila, this._ajRadios.servidor.fila);
      this._ajVol = el("input", { type: "range", id: "aj-vol", min: "0", max: "100", step: "5" });
      this._ajVol.addEventListener("input", () => this._ajustesCambiar({ volumen: Number(this._ajVol.value) / 100 }));
      this._ajFilaVol = el("div", { class: "aj-fila" }, el("label", { class: "aj-tit", for: "aj-vol", textContent: TEXTOS.ajVolumen }), this._ajVol);
      this._ajLeer = el("input", { type: "checkbox", id: "aj-leer" });
      this._ajLeer.addEventListener("change", () => { if (this._ajLeer.checked !== this._leerAuto) this._conmutarLeerAuto(); });
      this._ajFilaLeer = el("div", { class: "aj-fila" }, el("label", { class: "aj-op" }, this._ajLeer, el("span", { textContent: TEXTOS.ajLeerAuto })));
      this._ajAcuse = el("input", { type: "checkbox", id: "aj-acuse" });
      this._ajAcuse.addEventListener("change", () => this._ajustesCambiar({ acuse: this._ajAcuse.checked }));
      this._ajFilaAcuse = el("div", { class: "aj-fila" }, el("label", { class: "aj-op" }, this._ajAcuse, el("span", { textContent: TEXTOS.ajAcuse })));
      this._ajConfirmar = el("input", { type: "checkbox", id: "aj-confirmar" });
      this._ajConfirmar.addEventListener("change", () => this._ajustesCambiar({ confirmar: this._ajConfirmar.checked }));
      this._ajFilaConfirmar = el("div", { class: "aj-fila" }, el("label", { class: "aj-op" }, this._ajConfirmar, el("span", { textContent: TEXTOS.ajConfirmar })));
      this._ajInicio = el("input", { type: "checkbox", id: "aj-inicio" });
      this._ajInicio.addEventListener("change", () => this._ajustesCambiar({ iniciarVoz: this._ajInicio.checked }));
      this._ajFilaInicio = el("div", { class: "aj-fila" }, el("label", { class: "aj-op" }, this._ajInicio, el("span", { textContent: TEXTOS.ajInicioVoz })));
      this._ajProbar = el("button", { type: "button", textContent: TEXTOS.ajProbar });
      this._ajProbar.addEventListener("click", () => { this._pararVoz(); this._decir(TEXTOS.ajPrueba); });
      const restablecer = el("button", { type: "button", textContent: TEXTOS.ajRestablecer });
      restablecer.addEventListener("click", () => { this._pararVoz(); this._aj = { ...AJUSTES_BASE }; this._ajustesGuardar(); this._ajustesPintar(); this._actualizarVoz(); this._aplicarNombre(); this._ajNombre.value = ""; });
      this._ajFilaAcc = el("div", { class: "aj-fila aj-acciones" }, this._ajProbar, restablecer);
      this._ajCerrar = el("button", { type: "button", textContent: TEXTOS.ajCerrar });
      this._ajCerrar.addEventListener("click", () => this._ajustesCerrar());
      this._ajPanel = el("section", { class: "ajustes-panel", hidden: true, role: "dialog", "aria-labelledby": "aj-titulo" },
        el("div", { class: "mem-cab" }, el("h2", { id: "aj-titulo", textContent: TEXTOS.ajustesTitulo }), this._ajCerrar),
        el("div", { class: "mem-cuerpo" }, el("div", { class: "mem-col" },
          this._ajFilaNombre, this._ajFilaMotor, this._ajFilaVol, this._ajFilaLeer, this._ajFilaAcuse, this._ajFilaConfirmar, this._ajFilaInicio, this._ajFilaAcc)));
      this._ajPanel.addEventListener("keydown", (e) => { if (e.key === "Escape") { e.stopPropagation(); this._ajustesCerrar(); } });
      // un clic fuera del menú (y del engranaje) lo cierra; composedPath atraviesa el Shadow DOM
      this._ajFuera = (e) => {
        if (this._ajPanel.hidden) return;
        const ruta = e.composedPath();
        if (!ruta.includes(this._ajPanel) && !ruta.includes(this._ajBtn)) this._ajustesCerrar(false);
      };
      document.addEventListener("pointerdown", this._ajFuera, true);
    }

    _ajustesCambiar(cambio) {
      Object.assign(this._aj, cambio);
      this._ajustesGuardar();
      if (this._audio) this._audio.volume = this._volumen();   // el volumen se oye ya en lo que está sonando
      if ("nombre" in cambio) this._aplicarNombre();
      if ("motor" in cambio) { this._pararVoz(); this._actualizarVoz(); }
      if ("confirmar" in cambio && this._mhActivo()) this._mhPintar();
      this._ajustesPintar();
    }

    // Muestra solo lo que tiene sentido ahora: el selector de motor necesita las dos voces; el resto, alguna voz.
    _ajustesPintar() {
      const nav = puedeHablar(), srv = this._ttsServidor;
      this._ajFilaMotor.hidden = !(nav && srv);
      const motor = this._prefRespuesta();   // lo que de verdad se usa (atributo del anfitrión incluido)
      this._ajRadios.navegador.i.checked = motor === "navegador" || (motor !== "servidor" && !srv);
      this._ajRadios.servidor.i.checked = !this._ajRadios.navegador.i.checked;
      const habla = this._hablaPosible();
      this._ajFilaVol.hidden = this._ajFilaLeer.hidden = this._ajFilaAcc.hidden = !habla;
      this._ajFilaAcuse.hidden = !habla || this._manos.hidden;
      this._ajVol.value = String(Math.round(this._aj.volumen * 100));
      this._ajVol.setAttribute("aria-valuetext", Math.round(this._aj.volumen * 100) + " %");
      this._ajLeer.checked = this._leerAuto;
      this._ajAcuse.checked = this._aj.acuse;
      this._ajFilaConfirmar.hidden = this._ajFilaInicio.hidden = this._manos.hidden;
      this._ajInicio.checked = this._aj.iniciarVoz;
      this._ajConfirmar.checked = this._aj.confirmar;
    }

    _ajustesAbrir() {
      if (!this._ajustesActivos()) return;
      if (this._memPanel && !this._memPanel.hidden) this._memoriaCerrar();
      this._ajNombre.value = this._aj.nombre;   // solo al abrir: mientras se escribe, el campo no se reescribe
      this._ajustesPintar();
      this._ajPanel.hidden = false; this._ajBtn.setAttribute("aria-expanded", "true");
      this._ajCerrar.focus();
    }

    _ajustesCerrar(foco = true) {
      this._ajPanel.hidden = true; this._ajBtn.setAttribute("aria-expanded", "false");
      if (foco) this._ajBtn.focus();
    }

    // — memoria por usuario: panel «Lo que recuerdo» (contrato 6.8) —
    // Todo con nodos DOM y textContent. Borrar es un clic del propio usuario sobre sus datos: no pide confirmación.
    _construirMemoria() {
      this._memLista = el("ul", { class: "mem-lista" });
      this._memVacio = el("p", { class: "mem-vacio", textContent: TEXTOS.memoriaVacio, hidden: true });
      this._memEstado = el("div", { class: "mem-estado", role: "status" });
      this._memError = el("div", { class: "mem-error", role: "alert" });
      this._memTodo = el("button", { type: "button", textContent: TEXTOS.memoriaOlvidarTodo });
      this._memTodo.addEventListener("click", () => this._memoriaOlvidar(null));
      this._memCerrar = el("button", { type: "button", textContent: TEXTOS.memoriaCerrar });
      this._memCerrar.addEventListener("click", () => this._memoriaCerrar());
      const titulo = el("h2", { id: "mem-titulo", textContent: TEXTOS.memoriaTitulo });
      this._memPanel = el("section", { class: "memoria-panel", hidden: true, role: "dialog", "aria-labelledby": "mem-titulo" },
        el("div", { class: "mem-cab" }, titulo, this._memCerrar),
        el("div", { class: "mem-cuerpo" }, el("div", { class: "mem-col" },
          el("p", { class: "mem-intro", textContent: TEXTOS.memoriaIntro }),
          this._memLista, this._memVacio, this._memEstado, this._memError)),
        el("div", { class: "mem-pie" }, el("div", { class: "mem-col" }, this._memTodo)));
      this._memPanel.addEventListener("keydown", (e) => { if (e.key === "Escape") { e.stopPropagation(); this._memoriaCerrar(); } });
    }

    _memoriaAbrir() {
      if (!this._memoria) return;
      this._memPanel.hidden = false; this._memBtn.setAttribute("aria-expanded", "true");
      this._memCerrar.focus();
      this._memoriaCargar();
    }

    _memoriaCerrar() {
      this._memPanel.hidden = true; this._memBtn.setAttribute("aria-expanded", "false");
      this._memBtn.focus();
    }

    async _memoriaCargar() {
      this._memError.textContent = ""; this._memEstado.textContent = TEXTOS.memoriaCargando;
      try {
        const r = await this._conToken((h) => fetch(this._servidor + "/v1/memoria", { headers: h }));
        if (!r.ok) throw new Error("memoria " + r.status);
        const datos = await r.json();
        this._memEstado.textContent = "";
        this._memoriaPintar(Array.isArray(datos) ? datos : []);
      } catch { this._memEstado.textContent = ""; this._memError.textContent = TEXTOS.memoriaErrorCargar; }
    }

    _memoriaPintar(lista) {
      const validos = lista.filter((x) => x && typeof x.id === "string" && typeof x.descripcion === "string");
      this._memLista.replaceChildren(...validos.map((x) => {
        const boton = el("button", { type: "button", textContent: TEXTOS.memoriaOlvidar, "aria-label": TEXTOS.memoriaOlvidarEsto.replace("{d}", x.descripcion) });
        boton.addEventListener("click", () => this._memoriaOlvidar(x.id));
        const vence = new Date(x.vence);
        return el("li", {},
          el("div", { class: "mem-dato" },
            el("div", { class: "mem-tipo", textContent: TEXTOS.memoriaTipos[x.tipo] || "" }),
            el("div", { class: "mem-desc", textContent: x.descripcion }),
            ...(Number.isNaN(vence.getTime()) ? [] : [el("div", { class: "mem-vence", textContent: TEXTOS.memoriaVence.replace("{f}", vence.toLocaleDateString()) })])),
          boton);
      }));
      this._memVacio.hidden = validos.length > 0;
      this._memTodo.disabled = validos.length === 0;
    }

    // `id` = null: olvidar todo.
    async _memoriaOlvidar(id) {
      this._memError.textContent = ""; this._memEstado.textContent = "";
      this._memPanel.querySelectorAll("button").forEach((b) => { b.disabled = true; });
      try {
        const url = this._servidor + "/v1/memoria" + (id ? "/" + encodeURIComponent(id) : "");
        const r = await this._conToken((h) => fetch(url, { method: "DELETE", headers: h }));
        if (!r.ok && r.status !== 404) throw new Error("memoria " + r.status);
        this._memEstado.textContent = id ? TEXTOS.memoriaOlvidado : TEXTOS.memoriaOlvidadoTodo;
      } catch { this._memError.textContent = TEXTOS.memoriaErrorBorrar; }
      this._memPanel.querySelectorAll("button").forEach((b) => { b.disabled = false; });
      const estado = this._memEstado.textContent, error = this._memError.textContent;
      await this._memoriaCargar();
      this._memCerrar.focus();   // el botón que se usó ya no existe: el foco no se pierde (y Escape sigue cerrando)
      if (estado) this._memEstado.textContent = estado;
      if (error) { this._memError.textContent = error; }
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
      this._propuestaTurno = true;
      if (this._mhActivo()) {
        // La tarjeta se muestra donde esté el usuario: en la vista de voz sale en la escena, sin pasar al chat. Se confirma siempre con un clic.
        const frase = TEXTOS.mhConfirmarPantalla.replace("{r}", d.resumen);
        this._mostrarDicho(frase);
        if (this._hablaPosible()) this._decir(frase);
        this._tarjetaPosicionar();
      }
      this._bajar();
    }

    // La tarjeta vive en el chat; en la vista de voz se lleva a la escena (el mismo nodo, con sus botones) y se devuelve a su sitio.
    _tarjetaPosicionar() {
      const t = this._tarjetaActiva;
      if (!t || t.cerrada || !t.tarjeta.isConnected) return;
      if (this._mhActivo() && this._vista === "voz") {
        if (!t.marca) { t.marca = document.createComment(""); t.tarjeta.before(t.marca); }
        this._escena.insertBefore(t.tarjeta, this._verChat);
      } else this._tarjetaDevolver(t);
    }
    _tarjetaDevolver(t) {
      if (t.marca) { t.marca.replaceWith(t.tarjeta); t.marca = null; }
    }

    _cerrarTarjeta(t, estado, texto) {
      if (t.cerrada) return;
      t.cerrada = true; clearInterval(t.timer);
      this._tarjetaDevolver(t);
      t.botones.hidden = true; t.err.textContent = "";
      t.tarjeta.classList.add("cerrada", estado);
      t.estado.textContent = texto || ESTADOS_ACCION[estado] || "";
      t.estado.classList.toggle("ok", estado === "ejecutada");
      if (this._tarjetaActiva === t) this._tarjetaActiva = null;
      if (estado !== "reemplazada" && this._mhActivo() && this._vista === "voz" && t.estado.textContent) this._mostrarDicho(t.estado.textContent);
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
        let r;
        if (t.d.local === true) {
          // Acción local del asistente (memoria): no escribe en el sistema anfitrión, así que no hay token de
          // escritura que pedirle. Basta la sesión normal; el clic humano (isTrusted) es la confirmación.
          r = await this._conToken((h) => fetch(`${this._servidor}/v1/confirmaciones/${encodeURIComponent(t.d.id)}/confirmar-local`, { method: "POST", headers: h }));
        } else {
          const token = await this._tokenEscritura(t.d);
          if (!token) { this._errorTarjeta(t, "sin_autorizacion"); return; }
          r = await fetch(`${this._servidor}/v1/confirmaciones/${encodeURIComponent(t.d.id)}/confirmar`, {
            method: "POST", headers: { Authorization: "Bearer " + token },
          });
        }
        let c = {}; try { c = await r.json(); } catch { /* sin cuerpo */ }
        if (r.status === 409) { this._cerrarTarjeta(t, c.estado in ESTADOS_ACCION ? c.estado : "fallida"); return; }
        if (r.ok && c.ok === true) {
          this._cerrarTarjeta(t, "ejecutada", typeof c.mensaje === "string" && c.mensaje ? c.mensaje : ESTADOS_ACCION.ejecutada);
          if (t.d.local === true && this._memPanel && !this._memPanel.hidden) this._memoriaCargar();
          this._acciones(Array.isArray(c.ui) ? c.ui : [], t.tarjeta);
          return;
        }
        if (r.ok) { this._cerrarTarjeta(t, "fallida", ERRORES_ACCION[c.error] || ESTADOS_ACCION.fallida); return; }  // incluye tope_alcanzado
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
