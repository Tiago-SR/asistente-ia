# Pendientes

Único documento de pendientes (2026-10-19). Cada punto se verificó contra el código: nada de lo listado existe aún.
Reglas del proyecto: responder en español, no hacer `git commit` (sugerir el mensaje), consultar al `asesor` antes de
decisiones de API pública o difíciles de revertir.

## Producto

- **Deshacer acciones (`reversible_con`).** Si una tool lo declara, la tarjeta ofrece «Deshacer» con la misma maquinaria
  (propuesta, confirmación, token propio). Hoy no hay nada y el contrato dice que no se ofrece.
- **Voces por sistema.** El catálogo (`config/voces.yaml`) es global; falta activar/desactivar por sistema, con al
  menos una voz de cada género.
- **Ajustes del widget en el servidor por usuario.** Hoy solo `localStorage`. Abierto: qué fija el administrador del
  sistema y qué deja libre al usuario.
- **Imágenes de referencia.** `AlmacenAdjuntos` es `NoGuarda`. Decidir si se conservan; si sí: retención, borrado con la
  conversación y política de privacidad. No cambia el contrato del chat.
- **Manifiesto por rol de usuario.** Hoy es global; el sistema rechaza lo no permitido, pero el modelo ofrece tools que
  fallarán. Esperar a que algún sistema tenga roles con tools distintas.
- **Fase 6, proactivo (a evaluar).** Webhooks del sistema hacia el asistente o consultas programadas; exige cola o cron
  en el contenedor. Decisión de producto pendiente.

## Modo voz continuo en el celular (spike sin probar)

Hoy el modo voz usa `SpeechRecognition` del navegador (y, con `voz-motor="servidor"`, captura por turno con VAD por
energía). Nada de lo siguiente existe; el spike previo se retiró y nunca se midió en un Android real.

- Captura con `AudioWorklet` a 16 kHz mono; VAD por energía con histéresis y pre-roll (Silero WASM solo si falla).
- STT por lotes por frase (`scribe_v2`) primero; tiempo real solo si la espera de 1,4-2,3 s se siente lenta. El tiempo
  real exigiría `POST /v1/voz/token-stt` (cambio de contrato, pedir confirmación).
- Palabra de activación: empezar sin ella («tocar para abrir la sesión» + silenciar); luego transcribir cada frase y
  buscarla, avisando de que el audio ambiente se envía.
- Subir o separar `ASISTENTE_VOZ_MAX_POR_MIN` (hoy 10; la voz continua con ruido lo roza y da 429).
- Como modo opcional («escucha continua»), nunca reemplazo de «tocar para hablar».
- Medir en un Android real: eco con parlante, ruido sostenido (tope 15 s), frases partidas, batería, pantalla apagada o
  pestaña en segundo plano, datos móviles, privacidad (`enable_logging`) y qué proveedor/costo se acepta.

## Apps cliente (escritorio y móvil): solo análisis, sin código

Se retoma con el panel cerrado (ya lo está). Objetivo: app instalable de escritorio (Win/macOS/Linux) y móvil
(Android/iOS); el widget web sigue igual para quien lo incruste.

- **Voz fuera del navegador:** Web Speech no funciona en WebView. Móvil: reconocimiento nativo por plugin. Escritorio:
  STT del servidor (hoy solo «tocar»; «libres» necesitaría VAD en cliente).
- **Shell (sin decidir):** recomendación provisional un cliente web con Capacitor (móvil) y Tauri 2 (escritorio)
  cargando `<asistente-chat>`. Alternativas: Tauri solo, RN/Expo + Electron, Flutter.
- **Login y JWT (el mayor riesgo; decisión de API pública, consultar al asesor):** el widget pide el token con cookies
  de la página del sistema (`credentials: same-origin`); una app no las tiene. Falta un flujo: login del sistema →
  deep link con código de un solo uso → canje por `{token, expira}` + renovación (Keychain/Keystore o BFF). Choca con
  «token solo en memoria» (CONTRATO §7). ZetaSoftware (auth por empresa, sin usuarios) no encaja.
- **CORS:** `origenes_permitidos` es por sistema; las apps usan orígenes compartidos (`capacitor://localhost`,
  `https://localhost`, `tauri://localhost`) → lista global de «orígenes de plataforma»; lo que separa empresas pasa a
  ser `iss`/`aud`.
- **Push:** no hay nada en el backend; confirmar antes si hace falta (APNs/FCM).
- **Distribución:** Apple Developer y Google Play, firma Windows/macOS (notarización), CI con matriz, updater de Tauri;
  Apple 4.2 rechaza webs envueltas sin funciones nativas.
- **Versionado de contratos:** solo v1; definir política antes de abrir más clientes.
- **Roles configurables del panel** y **baja de empresas** (hoy solo `habilitado=false`, sin `DELETE`).
- **Orden para validar barato:** (1) login/token en papel con el asesor y prototipo contra STMGIS (`localhost:8201`);
  (2) Tauri con voz del servidor; (3) Capacitor con voz nativa en iPhone y Android reales; (4) orígenes de plataforma,
  push, firma; (5) preguntar a 1-2 clientes si exigen instalador y push.

## Privacidad y proveedores

- Quién informa a los clientes de cada sistema de que sus datos van a un LLM externo y cómo se habilita por cliente
  (`habilitado` por sistema permite excluir; un modelo local es la salida si lo exigen).
- Cómo se informa que en Chrome el audio del dictado y del modo voz se procesa en Google (aceptado hoy;
  `voz-motor="servidor"` lo evita).
- Respaldo remoto de voz (opcional): medir ElevenLabs, OpenAI y Deepgram (ver `PROVEEDORES_VOZ.md`).

## Panel de administración

Sin pendientes de implementación (roles, retención de `admin_auditoria` y cambio de contraseña propia están hechos).
Menores: e2e de sistemas/login/cuenta (solo existe `tests_e2e/panel-metricas.e2e.js`); la Fase 4 (métricas) no tuvo
prueba manual con datos reales ni evals.
