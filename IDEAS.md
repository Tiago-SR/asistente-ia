# Ideas pendientes

Ideas sin decidir ni implementar. Lo ya hecho está en el README y el contrato.

## Acciones con confirmación (Fase 5)

- **Deshacer (`reversible_con`).** Si una tool lo declara, la tarjeta podría ofrecer «Deshacer» con la misma maquinaria (propuesta, confirmación y token propio). Sin promesa en el contrato.
- **No se hará:** borrar (el asistente rechaza tools destructivas), confirmar por voz (siempre en pantalla) y acciones masivas, encadenadas o iniciadas por el sistema (esto último es la Fase 6).

## Panel de ajustes del widget

- Tono (pitch) de la voz: solo tiene efecto en voces locales del navegador (la de Google en Chrome probablemente lo ignora) y no hay forma simple con la voz del servidor.
- Elegir la voz concreta de la **voz del navegador** (la del servidor ya se elige: `config/voces.yaml`). Por sistema: hoy el catálogo es global.
- Idioma de voz y de reconocimiento (hoy sale de `locale_defecto` por sistema).
- Modo de entrada: pulsar para hablar o manos libres.
- Tamaño de letra, tema claro u oscuro y alto contraste.
- Sincronizar los ajustes en el servidor por usuario (hoy solo `localStorage`).

Preguntas abiertas:

- ¿Qué ajustes fija el administrador del sistema y cuáles deja libres al usuario (por ejemplo, ElevenLabs tiene costo)?
- ¿Se persiste solo en el navegador o también en el servidor por usuario?

## Imágenes de referencia

- **Subir imágenes como referencia para el modelo**, solo si el modelo configurado las admite (capacidad declarada por el adaptador del LLM, como caché o tools paralelas); si no, el widget no ofrece adjuntar.
- Por decidir: tamaño y formato máximos, dónde se guardan (o si solo viajan en el turno), retención y privacidad (la imagen sale hacia el LLM externo), y si el modelo actual (`deepseek-flash`) la admite.

## Respuestas más breves

- **Limitar la longitud de la respuesta** para que no genere mucho texto, pero sin perder lo esencial: debe contestar la pregunta o completar la actividad correctamente.
- Por decidir: dónde se aplica (regla en `prompts/base.md`, tope por sistema o preferencia por usuario; hoy existe la preferencia `brevedad` de la memoria) y cómo se mide en los evals (largo máximo sin que baje la corrección).

## Modo voz en el celular sin pitidos

**Problema.** En Chrome Android el modo voz suena un pitido cada vez que el reconocedor arranca. Viene de `SpeechRecognition` (Web Speech): en Android lo implementa el servicio de reconocimiento del sistema, que emite su tono en cada sesión y la corta solo tras una frase o un silencio. La página no puede silenciarlo y el widget tiene que reiniciarlo (`_mhReprogramar`). Además, en Android el modo continuo entrega resultados finales acumulativos, y la síntesis de voz suele tumbar el reconocimiento mientras el asistente habla. Ya mitigado: no se abre el segundo flujo del orbe en Android, se unen los finales acumulativos (`unirFinal`), los reinicios se espacian y no se reinicia mientras el asistente habla. Los pitidos al rearmar no se eliminan mientras se use este API.

**Cómo lo resuelve ChatGPT.** Abre el micrófono **una sola vez** (`getUserMedia`, o captura nativa en la app) y lo mantiene abierto. Corta las frases con detección de actividad de voz (VAD) y transcribe en un servidor. No depende de `SpeechRecognition`, así que no hay arranques ni tonos.

Piezas que ya existen: `POST /v1/voz/transcribir` (audio crudo → texto, `STT_*`), `voz-motor="servidor"` (el dictado graba con `MediaRecorder` y usa ese endpoint), `POST /v1/voz/sintetizar` con streaming, y `herramientas/probar_audio` con VAD por energía, interrupción y modo eco.

### Opción 1: tocar para hablar (corto plazo) — implementada, pendiente de medir en un Android real

**Hecho (2026-10-10).** Atributo `modo-entrada` (`auto` | `tocar` | `libres`; `auto` = «tocar» en Android) y ajuste del usuario; un turno por toque con `SpeechRecognition` no continuo, o con `voz-motor="servidor"` (o el ajuste «Reconocimiento de voz») con `getUserMedia` + `MediaRecorder` + `/v1/voz/transcribir`, fin de frase por energía con histéresis (`vadPaso`); tocar el orbe corta la lectura. STT del servidor con ElevenLabs Scribe (`STT_PROVEEDOR=elevenlabs`, `scribe_v2`). Contrato §7.3 y §7.4 actualizados. Cómo probarlo en el celular: casos B13–B15 de `PRUEBA_MANUAL_VOZ.md`. **Falta** medir en el celular: pitidos por turno, latencia `stt_ms` (consola) y si los umbrales del VAD sirven con ese micrófono. El texto de abajo es el diseño original.


Un toque abre el micrófono para un turno; sin palabra de activación ni reconocimiento continuo.

- **Flujo.** Botón grande en la vista de voz → escucha una frase → al callarse (fin de frase) o al tocar de nuevo, se envía → el asistente responde con el resumen hablado → queda quieto hasta el próximo toque. Con `SpeechRecognition` en modo no continuo (`continuous=false`), como el dictado del chat, que ya funciona bien en el celular. Un arranque por turno = un pitido por turno, no una ráfaga.
- **Qué cambia en el widget.** Un modo de entrada «tocar» junto a «manos libres». En Android sería el valor por defecto. El orbe y la vista de voz se reutilizan; el estado «armado» pasa a «listo» y se omite la palabra de activación. Reutiliza el panel de ajustes (la lista ya trae «modo de entrada: pulsar para hablar o manos libres»).
- **Variante sin pitido.** Con `voz-motor="servidor"` el micrófono lo abre `getUserMedia`, no el servicio de reconocimiento, y no suena nada. Se pierde el texto parcial en vivo y se gana una latencia de transcripción por servidor (a medir con `herramientas/probar_audio`).
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
- **Alcance estimado.** Widget (captura, VAD, estados), `api/voz.py` (streaming opcional), tests y e2e, evals de transcripción con `herramientas/probar_audio`, y actualización del contrato y la política de privacidad.
- **Riesgos.** Eco y falsos disparos del VAD con parlante en el celular; consumo de batería; conectividad móvil; costo.

### Orden sugerido

1. Hacer la **opción 1** (con `voz-motor="servidor"` como variante) y medir en el celular.
2. Con ese resultado y los tiempos de `herramientas/probar_audio`, decidir si la opción 2 se justifica y qué proveedor de STT usar.

Por decidir: ¿la palabra de activación sigue siendo requisito en el celular?, ¿qué proveedor y costo de STT son aceptables?, ¿se acepta enviar el audio ambiente al servidor?
