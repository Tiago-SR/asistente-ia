# Ideas pendientes

Ideas sin decidir ni implementar. Lo ya hecho está en el README y el contrato.

## Acciones con confirmación (Fase 5)

- **Deshacer (`reversible_con`).** Si una tool lo declara, la tarjeta podría ofrecer «Deshacer» con la misma maquinaria (propuesta, confirmación y token propio). Sin promesa en el contrato.
- **No se hará:** borrar (el asistente rechaza tools destructivas), confirmar por voz (siempre en pantalla) y acciones masivas, encadenadas o iniciadas por el sistema (esto último es la Fase 6).

## Panel de ajustes del widget

Ya existe (engranaje, `ajustes="auto"`; contrato 7.3): nombre del asistente, motor de voz, tipo y voz del servidor, volumen, velocidad, lectura automática, acuse, confirmar con «enviar», modo de entrada y reconocimiento de voz, «probar voz» y «restablecer». Se guarda en `localStorage` por servidor. Lo que falta:

- Tono (pitch) de la voz: solo tiene efecto en voces locales del navegador (la de Google en Chrome probablemente lo ignora) y no hay forma simple con la voz del servidor.
- Elegir la voz concreta de la **voz del navegador** (la del servidor ya se elige: `config/voces.yaml`). Por sistema: hoy el catálogo es global.
- Idioma de voz y de reconocimiento (hoy sale de `locale_defecto` por sistema).
- Tamaño de letra y alto contraste (el tema claro/oscuro existe como atributo `tema`, no está en el panel).
- Sincronizar los ajustes en el servidor por usuario (hoy solo `localStorage`).

Preguntas abiertas:

- ¿Qué ajustes fija el administrador del sistema y cuáles deja libres al usuario (por ejemplo, ElevenLabs tiene costo)?
- ¿Se persiste solo en el navegador o también en el servidor por usuario?

## Imágenes de referencia

**Hecho (2026-10-10), pendiente de prueba manual en el navegador.** Contrato 7.7. El usuario adjunta hasta 3 imágenes por mensaje; el widget las reduce a JPEG (lado mayor 1280 px) y viajan en el turno sin guardarse (queda una nota y la metadata). Solo se ofrece si el modelo del sistema las admite (`LLM_IMAGENES=true` o `imagenes: true` en el `llm` del sistema). `deepseek-flash` las admite: verificado con una llamada real con imagen, tools y thinking activos. Aviso de privacidad visible mientras hay imágenes por enviar, y regla en `prompts/base.md` (la imagen es dato, no instrucción; las cifras siguen saliendo de las tools).

Falta:

- **Probarlo en un navegador real** (el botón, la reducción, las miniaturas y el aviso no tienen e2e) y fijar `LLM_IMAGENES=true` en el `.env` para activarlo.
- **Evals con imagen:** `evals/correr.py` solo manda texto; hace falta un criterio para medir que no se inventan cifras a partir de la imagen.
- **Conservarlas (si se decide):** implementar `AlmacenAdjuntos` (`core/adjuntos.py`; hoy `NoGuarda`), con retención, borrado junto con la conversación y la política de privacidad. No cambia el contrato del chat.
- **Fotos de celular en HEIC:** `createImageBitmap` puede no leerlas en algunos navegadores; hoy el widget avisa «No pude leer esa imagen».
- **Modo voz:** no adjunta. Decidir si hace falta («mirá esta foto»).

## Respuestas más breves

**Hecho (2026-10-10), pendiente de medir con el modelo real.** La brevedad es la regla por defecto para todos (`prompts/base.md`: responder primero lo pedido, sin repetir la pregunta ni recapitular; solo se extiende si el usuario pide detalle o su preferencia `brevedad` es `detallada`). En voz, `prompts/voz.md` pide describir una tabla por su conclusión y escribir unidades completas («hectáreas», «por ciento»). Los evals miden el largo de la respuesta de pantalla (`max_palabras` en `preguntas.yaml`) y la redacción de tablas para voz (`v11`, `v12` en `preguntas_voz.yaml`).

Falta correr los dos sets contra `deepseek-flash` (línea base: 32/32 y 213 tokens de salida por pregunta) y ajustar los límites de palabras, que son estimaciones. Si no basta, el siguiente paso sería un tope por sistema en `sistemas.yaml`.

## Modo voz en el celular sin pitidos

**Problema.** En Chrome Android el modo voz suena un pitido cada vez que el reconocedor arranca. Viene de `SpeechRecognition` (Web Speech): en Android lo implementa el servicio de reconocimiento del sistema, que emite su tono en cada sesión y la corta solo tras una frase o un silencio. La página no puede silenciarlo y el widget tiene que reiniciarlo (`_mhReprogramar`). Además, en Android el modo continuo entrega resultados finales acumulativos, y la síntesis de voz suele tumbar el reconocimiento mientras el asistente habla. Ya mitigado: no se abre el segundo flujo del orbe en Android, se unen los finales acumulativos (`unirFinal`), los reinicios se espacian y no se reinicia mientras el asistente habla. Los pitidos al rearmar no se eliminan mientras se use este API.

**Cómo lo resuelve ChatGPT.** Abre el micrófono **una sola vez** (`getUserMedia`, o captura nativa en la app) y lo mantiene abierto. Corta las frases con detección de actividad de voz (VAD) y transcribe en un servidor. No depende de `SpeechRecognition`, así que no hay arranques ni tonos.

Piezas que ya existen: `POST /v1/voz/transcribir` (audio crudo → texto, `STT_*`), `voz-motor="servidor"` (el dictado graba con `MediaRecorder` y usa ese endpoint), `POST /v1/voz/sintetizar` con streaming, y, en el historial de git, el banco de pruebas de audio que ya se retiró del repo.

### Opción 1: tocar para hablar (corto plazo) — implementada, pendiente de medir en un Android real

**Hecho (2026-10-10).** Atributo `modo-entrada` (`auto` | `tocar` | `libres`; `auto` = «tocar» en Android) y ajuste del usuario; un turno por toque con `SpeechRecognition` no continuo, o con `voz-motor="servidor"` (o el ajuste «Reconocimiento de voz») con `getUserMedia` + `MediaRecorder` + `/v1/voz/transcribir`, fin de frase por energía con histéresis (`vadPaso`); tocar el orbe corta la lectura. STT del servidor con ElevenLabs Scribe (`STT_PROVEEDOR=elevenlabs`, `scribe_v2`). Contrato §7.3 y §7.4 actualizados. Cómo probarlo en el celular: casos B13–B15 de `PRUEBA_MANUAL_VOZ.md`. **Falta** medir en el celular: pitidos por turno, latencia `stt_ms` (consola) y si los umbrales del VAD sirven con ese micrófono. El texto de abajo es el diseño original.


Un toque abre el micrófono para un turno; sin palabra de activación ni reconocimiento continuo.

- **Flujo.** Botón grande en la vista de voz → escucha una frase → al callarse (fin de frase) o al tocar de nuevo, se envía → el asistente responde con el resumen hablado → queda quieto hasta el próximo toque. Con `SpeechRecognition` en modo no continuo (`continuous=false`), como el dictado del chat, que ya funciona bien en el celular. Un arranque por turno = un pitido por turno, no una ráfaga.
- **Qué cambia en el widget.** Un modo de entrada «tocar» junto a «manos libres». En Android sería el valor por defecto. El orbe y la vista de voz se reutilizan; el estado «armado» pasa a «listo» y se omite la palabra de activación. Reutiliza el panel de ajustes (la lista ya trae «modo de entrada: pulsar para hablar o manos libres»).
- **Variante sin pitido.** Con `voz-motor="servidor"` el micrófono lo abre `getUserMedia`, no el servicio de reconocimiento, y no suena nada. Se pierde el texto parcial en vivo y se gana una latencia de transcripción por servidor (a medir).
- **Interrumpir al asistente.** Tocar el orbe corta la lectura y abre el micrófono. No hay interrupción por voz.
- **Alcance.** Solo `widget.js`, tests del widget y `PRUEBA_MANUAL_VOZ.md`. Sin cambios en el servidor ni en el contrato.
- **Riesgos.** Es menos «manos libres» que lo que se ve hoy en escritorio. Si Chrome no entrega finales a tiempo con `continuous=false`, hay que cortar por silencio propio.
- **Cómo se sabe que funciona.** En el celular, 5 preguntas seguidas con un único pitido por pregunta (o ninguno con servidor) y sin frases duplicadas; e2e de voz simulada para el nuevo estado.

### Opción 2: audio continuo propio, estilo ChatGPT (fase aparte)

El widget captura audio él mismo y el servidor transcribe; el navegador no hace reconocimiento.

- **Captura.** Un `getUserMedia` abierto mientras el modo voz está encendido, con `AudioWorklet` (o `MediaRecorder` en trozos) a 16 kHz mono. Es el único consumidor del micrófono, y el orbe puede usar ese mismo flujo para el volumen (adiós al segundo flujo).
- **Detección de voz (VAD).** En el cliente: energía con histéresis, o un modelo ligero (Silero VAD en WASM). Define inicio y fin de frase, y la interrupción mientras el asistente habla. Hay que ajustar umbrales por dispositivo, y para el eco usar `echoCancellation`/`noiseSuppression` de `getUserMedia` y probar en parlante.
- **Transcripción.**
  - *Por frase:* se envía cada frase a `POST /v1/voz/transcribir` apenas el VAD la cierra. Es lo más simple y reutiliza el endpoint actual.
  - *En streaming:* WebSocket o SSE con transcripción parcial. Requiere un STT que lo soporte y un endpoint nuevo en `api/voz.py`.
- **Palabra de activación.** Es el punto difícil. Alternativas: (a) no usarla (modo «escucha siempre» con botón de silenciar, como ChatGPT); (b) transcribir cada frase y buscar la palabra en el texto con `buscarActivacion`, que gasta STT en todo lo que se oiga en el ambiente; (c) un detector de palabra clave en el navegador (WASM, entrenado con el nombre del asistente), que es lo más complejo y depende de que el nombre cambie por sistema.
- **Servidor.** Un STT disponible y rápido: hoy `STT_*` apunta a un endpoint compatible con OpenAI (Whisper en `--profile voz`, o un proveedor). La decisión previa fue Web Speech (Google aceptado) y Whisper local descartado, así que habría que elegir proveedor (ver `PROVEEDORES_VOZ.md`), con costo por minuto y envío de todo el audio ambiente. El contrato (§7.3 y §7.4) y los límites por usuario deberían contemplarlo.
- **Qué desaparece.** Pitidos, reinicios, resultados acumulativos y la dependencia de la voz del navegador para entender. Aparecen: latencia de red por frase, costo de STT, VAD y privacidad a revisar (el audio sale del dispositivo mientras está activo).
- **Alcance estimado.** Widget (captura, VAD, estados), `api/voz.py` (streaming opcional), tests y e2e, evals de transcripción, y actualización del contrato y la política de privacidad.
- **Riesgos.** Eco y falsos disparos del VAD con parlante en el celular; consumo de batería; conectividad móvil; costo.

### Informe de la Fase B: spike de audio continuo (2026-10-10)

> **Estado: spike hecho y medido en el escritorio, incluido Scribe real; falta medir en un Android real.** Todo lo del celular está marcado «pendiente» y no se estima aquí como si fuera medido. La recomendación es provisional hasta completar P1–P5 de el protocolo P1–P6 (retirado).

**Qué se construyó** (sin tocar `widget.js` ni el contrato; todo el spike y el banco `herramientas/probar_audio/` se **retiraron del repo** el 2026-10-10 tras medir, y los resultados quedan solo en este informe): `continuo.html` (un `getUserMedia` con `echoCancellation`/`noiseSuppression`, `AudioWorklet` a 16 kHz mono, VAD por energía con histéresis y pre-roll de 300 ms, cada frase como WAV a `/stt` → Scribe, contadores de latencia, falsos disparos, CPU, costo y batería), `medir_vad.js` (VAD con audio grabado; energía o Silero v5 en WASM), `medir_stt.py` (Scribe por lotes y en tiempo real) y el protocolo para el celular.

#### Qué se midió y con qué

| Medición | Cómo | Resultado |
|---|---|---|
| Circuito completo en Chrome (worklet + VAD + envío) | Navegador real, micrófono simulado con 3 frases de TTS, STT simulado | 3/3 frases detectadas y enviadas, 0 falsos disparos, CPU del hilo principal 0,29 %, contexto a 16 kHz nativo (sin remuestrear) |
| Latencia fin de voz → texto | Mismo montaje | 708 ms = 700 ms de silencio de cierre + 8 ms de STT simulado. **La parte fija es el silencio de cierre**; con Scribe real se suma el STT (fila de Scribe) |
| Audio enviado por frase | Mismo montaje | La frase de 2,1 s viaja como 2,8 s: **+0,7–0,8 s por frase** (silencio de cierre + pre-roll) que se factura |
| Frase en silencio, 6 audios (voz TTS y `voz.wav`) | `medir_vad.js` | 6/6 una sola frase; el cierre llega 420–575 ms después del final del archivo (energía) y 500–640 ms (Silero); el inicio se detecta 56–120 ms tarde y el pre-roll lo cubre |
| Ruido de fondo sobre la voz (RMS 0,06) | `medir_vad.js`, ruido sintético | **Energía fija:** 6/6 hasta SNR 16 dB; **0/6 desde 10 dB** (el ruido queda sobre el umbral «bajo», la frase no cierra y se corta por el tope de 15 s). El adaptativo no lo arregla en 3 s de aprendizaje. **Silero:** 6/6 hasta 0 dB |
| Ruido solo, 10 min con variación lenta | `medir_vad.js` | Frases enviadas por hora con ruido RMS 0,005 / 0,01 / 0,02 / 0,04 / 0,08: energía fija 0 / 0 / 0 / 234 / 240; adaptativa 0 / 0 / 24 / 72 / 108; **Silero 0 en todos** |
| Golpes y clics, 30 en 5 min | `medir_vad.js` | Ninguno se envía (energía los descarta por duración mínima: 30/30; Silero ni los detecta como voz) |
| Pausas dentro de una frase | `medir_vad.js` | Con silencio de cierre de 700 ms una pausa de 900 ms **parte la frase en dos**; con 1200 ms hace falta ≥ 1,5 s. Es un compromiso: 500 ms menos de latencia contra más frases partidas (Scribe las transcribe por separado y la segunda mitad puede perder contexto) |
| CPU del VAD | `medir_vad.js` en Node, un núcleo de escritorio | Energía: 0,002 % de un núcleo. Silero (WASM, un hilo): 0,69 %. **En un celular no medido** (se espera bastante más; no hay estimación fiable) |
| Tamaño de Silero | `npm` en un directorio temporal | Modelo 2,3 MB + `onnxruntime-web` 11 MB de WASM (más su JS): pesado para un widget que hoy es un solo archivo; tendría que cargarse bajo demanda |
| Scribe real: latencia y error de palabras | `medir_stt.py` (retirado), 5 frases de TTS (2,1–9,3 s), 3 repeticiones, desde el escritorio por wifi | **Por lotes (`scribe_v2`):** 0,7–1,6 s desde que sale el WAV (mediana 0,8 s para 2,1 s de voz; 1,3–1,5 s para 9 s), crece con el largo. **Tiempo real, commit manual** (el audio llega al ritmo de hablar): **≈ 0,3 s** tras el fin de la voz, sin depender del largo. **Tiempo real con VAD del proveedor (0,7 s):** ≈ 1,0 s (0,7 s de silencio + 0,3 s). Error de palabras 0 % salvo «cuarenta y dos» → «42» (cifras como numerales: no es error para el asistente). Voz de TTS limpia: **optimista**, no es voz real |
| Pitidos, `stt_ms` real y umbrales con el micrófono del celular; falsos disparos con parlante y auriculares; batería | Protocolo P1–P6 | **Pendiente** (depende de un Android real) |

Limitaciones de lo medido: el audio es sintético (TTS) o un solo `voz.wav` de 2 s, sin micrófono, sala ni parlante reales; el ruido es filtrado y sintético, no voz ajena ni tele. Un VAD, sea de energía o Silero, **no distingue de quién es la voz**: la tele, otra persona o el propio parlante abren la frase igual. Eso solo lo cierra el eco cancelado del navegador, el silenciado mientras habla o la palabra de activación, y se mide en P2–P4.

#### Palabra de activación (la elige el usuario)

La palabra la define el usuario o el sistema (`palabra-activacion`), así que cualquier solución tiene que aceptar una palabra arbitraria en ejecución.

| Opción | Cumple «palabra elegida por el usuario» | Costo y privacidad | Complejidad | Observación |
|---|---|---|---|---|
| **(a) Sin palabra**, botón de silenciar | No aplica: toda frase cuenta | Se transcribe todo lo que el VAD abra, incluido el ambiente | La más simple | Es el modelo de ChatGPT, pero allí el usuario inició la conversación y hay un botón visible. Con ruido o gente cerca, el asistente recibe frases ajenas |
| **(b) Transcribir cada frase y buscar la palabra** con `buscarActivacion` | **Sí**, cualquier palabra y sin entrenar nada | Cada frase del ambiente viaja a Scribe y se paga aunque no tenga la palabra (ver costo) | Ya existe la lógica; solo se aplica al texto del servidor | La palabra puede transcribirse distinto («sofía» → «sofia», «Sofi»): la normalización actual cubre acentos, no fonética. Latencia: toda frase espera al STT para saber si la palabra estaba |
| **(c) Detector de palabra clave en el navegador (WASM)** | **Solo parcialmente.** Porcupine y openWakeWord requieren entrenar o generar un modelo **por palabra** (consola del proveedor; Porcupine además pide clave de acceso): no sirve para una palabra libre en ejecución. Un reconocedor con gramática restringida (p. ej. Vosk con modelo español pequeño, o sherpa-onnx con palabras abiertas) sí acepta palabras arbitrarias | El audio ambiente **no sale del dispositivo** hasta la activación | La mayor: modelo de decenas de MB, CPU continua en el celular, cadena de herramientas aparte | **No probado**: no hay medición propia, solo lo que declara la documentación de cada proyecto; la disponibilidad de modelos en español de sherpa-onnx no se pudo verificar |

Sin (c) no hay forma de que el audio ambiente no salga del dispositivo salvo no usar palabra y exigir un toque para abrir la sesión.

#### Costo de STT por hora de uso

Precios vigentes el 2026-10-10 en la página de ElevenLabs: **Scribe v2 $0,22/h por lotes, Scribe v2 Realtime $0,39/h** (confirma `PROVEEDORES_VOZ.md`; complementos de palabras clave +$0,05/h y +$0,08/h). Se factura audio enviado, y cada frase lleva ≈ 0,75 s de más (medido arriba).

| Escenario por hora de modo encendido | Voz abierta por el VAD | Frases/h | Audio enviado | Lotes ($0,22/h) | Tiempo real ($0,39/h) |
|---|---|---|---|---|---|
| Uso dirigido, cuarto tranquilo (habla el usuario ~10 % del tiempo) | 360 s | ≈ 120 | ≈ 450 s | **≈ $0,03** | ≈ $0,05 si solo se envía la voz; $0,39 si se mantiene abierto el flujo |
| Alguien conversando cerca (~30 %) | 1 080 s | ≈ 360 | ≈ 1 350 s | ≈ $0,08 | ≈ $0,15 con envío solo de voz |
| Tele o radio encendida (~60 % o más) | 2 160 s | ≈ 600 | ≈ 2 600 s | ≈ $0,16 | ≈ $0,28 con envío solo de voz |

**Latencia total estimada** (silencio de cierre del VAD local + STT medido; suma, no medición conjunta): por lotes ≈ 0,7 + 0,7–1,6 = **1,4–2,3 s**; tiempo real con commit al cerrar el VAD local ≈ 0,7 + 0,3 = **≈ 1,0 s**; la Fase A (1,2 s de silencio + lotes) ≈ 1,9–2,8 s.

Los porcentajes y frases por hora son supuestos, no mediciones: P2 los mide con el ruido real. No se verificó si el tiempo real factura el silencio dentro de una sesión abierta; la página lista el precio por hora de audio, y por eso se muestran las dos lecturas. **El STT sigue siendo barato; el riesgo es otro:** `ASISTENTE_VOZ_MAX_POR_MIN` vale 10 y el escenario de tele encendida (~10 frases/min) lo roza; pasado el tope el servidor responde 429 y el modo tendría que degradar con un aviso en vez de fallar en silencio.

#### Privacidad

- En modo continuo el micrófono queda abierto mientras el modo voz esté encendido, y **todo lo que el VAD abra viaja a ElevenLabs** (proveedor remoto, hoy `enable_logging` de Scribe en `true` por defecto en la API en tiempo real; confirmar retención con el proveedor antes de producción). Con la palabra de activación en el servidor (b), el audio ambiente es parte de lo enviado.
- Hoy el aviso de privacidad ya está visible en el modo voz (B10); en continuo habría que mostrarlo en cada sesión y recordar que se oye sin tocar.
- El aviso y el indicador de micrófono del sistema deben ser inequívocos; es parte de la decisión del producto, no solo técnica.

#### Riesgos

1. **Eco y voz ajena** abren el VAD (no medido con celular real; P3 y P4).
2. **Ruido sostenido** deja el VAD de energía «pegado» hasta el tope de 15 s (medido); Silero lo evita pero cuesta 13 MB de descarga.
3. **Frases partidas** por pausas: elegir el silencio de cierre es un compromiso entre latencia y contexto.
4. **Tope de 10 transcripciones por minuto** por usuario en el servidor.
5. **Batería y calor** con el micrófono y el worklet siempre activos (P5).
6. **Chrome Android** puede suspender el micrófono o el `AudioContext` con la pantalla apagada o la pestaña en segundo plano; el spike no lo contempla y es probable que el modo continuo solo valga con la pantalla encendida.
7. **Clave del proveedor:** con STT en tiempo real, el WebSocket no puede llevar `xi-api-key` desde el navegador; hace falta que el servidor emita un token de un solo uso o haga de pasarela (**cambio de contrato, ver abajo**).

#### Recomendación (provisional hasta P1–P5)

1. **Integrar al widget como modo opcional («escucha continua»), no como reemplazo de «tocar para hablar»**, y solo si P1–P3 salen bien en el celular. Hoy no hay evidencia propia de que el eco con parlante sea manejable; sin eso, «tocar» sigue siendo el modo recomendado en Android.
2. **STT: empezar por lotes por frase (`scribe_v2`), con el tiempo real como segunda etapa.** Por lotes usa el contrato vigente y cuesta $0,22/h. La medición muestra que el tiempo real **sí** gana: ≈ 0,3 s tras cerrar la frase frente a 0,7–1,6 s por lotes (una mejora de 0,4–1,3 s por turno, mayor cuanto más larga la frase), por $0,17/h más. Se justifica si P1 en el celular muestra que 1,4–2,3 s de espera total se siente lenta, o si se quiere el «estilo ChatGPT» del todo. Antes de decidir faltan dos datos que el escritorio no da: la latencia del WebSocket por datos móviles y si la sesión abierta factura el silencio.
3. **VAD por energía con pre-roll** primero; **Silero solo si** P2/P3 muestran falsos disparos o frases pegadas que la energía no resuelve (y cargado bajo demanda).
4. **Palabra de activación:** empezar con (a) más «tocar para abrir la sesión» y botón de silenciar; ofrecer (b) como opción con aviso claro de que el audio ambiente se envía. **Descartar (c) por ahora**: no cumple la palabra libre sin entrenar y no está probado.
5. **Subir o separar el límite por minuto** para voz continua (propuesta, no hecha: es una variable del servidor, `ASISTENTE_VOZ_MAX_POR_MIN`, y no cambia el contrato).

**Cambio de contrato (solo propuesta; no implementado, espera tu confirmación):** si se elige STT en tiempo real, haría falta `POST /v1/voz/token-stt` (o un WebSocket `GET /v1/voz/transcribir/stream`) que devuelva un token de un solo uso del proveedor o haga de pasarela, más su sección en §7.4 y límites propios. Con STT por lotes no hace falta nada nuevo.

#### Qué no se pudo probar

- Cualquier cosa del Android real: pitidos por turno, `stt_ms` real, umbrales con ese micrófono, eco con parlante y con auriculares, batería, comportamiento con la pantalla apagada o la pestaña en segundo plano y conectividad móvil.
- Scribe con voz real y desde datos móviles: las 5 frases medidas son de TTS (limpias) y se enviaron desde el escritorio por wifi; la conexión del WebSocket (apertura, reconexión, mantenimiento con la pantalla apagada) no se midió.
- Silero y el VAD por energía en un navegador móvil (solo se midieron en Node y en Chrome de escritorio con micrófono simulado).
- Voz ajena, tele y reverberación (el ruido de las pruebas es sintético).
- Los detectores de palabra clave en WASM de (c).

### Orden sugerido

1. Hacer la **opción 1** (con `voz-motor="servidor"` como variante) y medir en el celular. *(Hecho; falta medir.)*
2. Con ese resultado y los tiempos medidos, decidir si la opción 2 se justifica y qué proveedor de STT usar. *(Spike y mediciones de escritorio hechas, ver el informe; el spike se retiró, así que lo del celular (P1–P6) exigiría reconstruirlo.)*

Por decidir: ¿la palabra de activación sigue siendo requisito en el celular?, ¿qué proveedor y costo de STT son aceptables?, ¿se acepta enviar el audio ambiente al servidor? (ver el informe de arriba para las opciones y números)
