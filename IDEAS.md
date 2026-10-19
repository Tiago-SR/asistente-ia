# Ideas pendientes

Solo lo que falta; lo ya hecho está en el README y el contrato (limpiado 2026-10-19).

## Acciones con confirmación (Fase 5)

- **Deshacer (`reversible_con`).** Si una tool lo declara, la tarjeta podría ofrecer «Deshacer» con la misma maquinaria (propuesta, confirmación y token propio). Sin promesa en el contrato.

## Panel de ajustes del widget

- **Voces configurables por sistema.** Que el catálogo de voces se pueda activar y desactivar por sistema, dejando siempre al menos una de cada género.
- **Sincronizar los ajustes en el servidor por usuario** (hoy solo `localStorage`). Pregunta abierta: qué ajustes fija el administrador del sistema y cuáles deja libres al usuario.

## Imágenes de referencia

- **Decidir si se conservan.** Implementar `AlmacenAdjuntos` (`core/adjuntos.py`; hoy `NoGuarda`) con retención, borrado junto con la conversación y política de privacidad. No cambia el contrato del chat.

## Modo voz en el celular: audio continuo propio, estilo ChatGPT (opción 2, sin probar)

El widget captura audio él mismo y el servidor transcribe; el navegador no hace reconocimiento. Spike hecho y medido solo en escritorio (incluido Scribe real) y retirado del repo; **nada se probó en un Android real**, y reconstruirlo sería necesario para medirlo.

- **Captura y VAD.** Un `getUserMedia` abierto con `AudioWorklet` a 16 kHz mono; VAD por energía con histéresis y pre-roll primero, Silero (WASM, ~13 MB, bajo demanda) solo si hay falsos disparos o frases pegadas.
- **Transcripción.** Por lotes por frase (`scribe_v2`, $0,22/h, usa el endpoint actual) como primera etapa; tiempo real (≈0,3 s tras cerrar la frase, $0,39/h) como segunda, si 1,4–2,3 s de espera total se sienten lentos en el celular.
- **Palabra de activación.** Empezar con (a) sin palabra, con «tocar para abrir la sesión» y botón de silenciar; ofrecer (b) transcribir cada frase y buscar la palabra, con aviso de que el audio ambiente se envía. Descartar (c) detector WASM por ahora.
- **Integración.** Como modo opcional («escucha continua»), no como reemplazo de «tocar para hablar», y solo si salen bien las pruebas en el celular.
- **Límite por minuto.** Subir o separar `ASISTENTE_VOZ_MAX_POR_MIN` (hoy 10; la voz continua con ruido lo roza y el servidor responde 429). Es una variable del servidor, sin cambio de contrato.
- **Cambio de contrato (propuesta, espera confirmación).** Solo si se elige STT en tiempo real: `POST /v1/voz/token-stt` (o `GET /v1/voz/transcribir/stream`) con token de un solo uso o pasarela, más su sección en §7.4 y límites propios. Con STT por lotes no hace falta nada nuevo.
- **Privacidad.** Todo lo que el VAD abra viaja al proveedor de STT; el aviso debe mostrarse en cada sesión. Confirmar la retención (`enable_logging`) antes de producción.
- **Riesgos sin medir.** Eco y voz ajena con parlante; ruido sostenido que deja el VAD pegado (tope de 15 s); frases partidas por pausas; batería y calor; Chrome Android puede suspender el micrófono con la pantalla apagada o la pestaña en segundo plano.
- **Por medir en el Android real.** Pitidos por turno, `stt_ms`, umbrales con ese micrófono, eco con parlante y auriculares, batería, pantalla apagada, datos móviles, Scribe con voz real, VAD en móvil y voz ajena/tele.
- **Por decidir.** Si la palabra de activación sigue siendo requisito en el celular; qué proveedor y costo de STT son aceptables; si se acepta enviar el audio ambiente al servidor.
