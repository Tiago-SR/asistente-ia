# Pruebas e2e del widget (navegador real)

Fuera de la suite pytest (`tests/`). Son funciones de Playwright que se ejecutan con el MCP de Playwright
(`browser_run_code_unsafe` con `filename`); no hay dependencias que instalar en el repo. Cada archivo devuelve
`{resultados: [{nombre, ok, detalle}], resumen}` y corre todos los casos aunque alguno falle. Capturas en `.playwright-mcp/e2e/` (ignorado por git).

## Requisitos

- `docker compose -f docker-compose.dev.yml up -d` con `asistente`, `postgres` y `sistema-php` (página en <http://localhost:8203/?usuario=ana>).
- `config/sistemas.yaml` con la entrada `sistema-php` y `PHP_SECRETO` / `PHP_MANIFEST_TOKEN` en el `.env` (valores en `ejemplos/sistema-php/README.md`).
- `widget.e2e.js` usa el **LLM real** (llama-server en :8090) y verifica las cifras de la tool (870,5 para ana, 88,2 para beto), no el texto del modelo. Puede tardar un par de minutos.
- Tras cambiar `src/asistente/static/widget.js` hay que **reiniciar el contenedor `asistente`**: el servidor lee el archivo una sola vez al arrancar.

## Archivos

| Archivo | Usa LLM | Cubre |
|---|---|---|
| `widget.e2e.js` | sí | carga, streaming SSE, cifras de la tool, historial de la conversación actual tras recargar, aislamiento ana/beto (incluido `GET /v1/conversaciones/{id}` ajeno → 404), tabla Markdown y sanitizado de `<script>`, `onerror` y `javascript:` (SSE fabricado) |
| `layout.e2e.js` | no (SSE fabricado) | vista completa a 1280 y 390 px: widget a todo el ancho, columna central centrada, entrada fija abajo, sin desborde horizontal, sin lateral/menú/elementos `fixed`, `modo`/`abierto` ignorados, nueva conversación, página sin avisos de PHP |
| `voz-navegador.e2e.js` | no (todo simulado) | dictado con `SpeechRecognition` (parcial, final al campo sin enviar, errores de red y silencio), respuesta hablada con `speechSynthesis` (botón por mensaje, lectura automática por oraciones, preferencia recordada, silenciar al dictar, voz es-ES de respaldo) y `voz-motor="servidor"`. Simula las APIs de voz: no juzga su calidad (para eso, `herramientas/probar_audio`) |
| `modo-voz.e2e.js` | no (chat y voz simulados) | vista del modo voz: se abre como ventana propia (orbe, sin chat ni campo), lo dictado se ve en ella, enviar pide el canal `voz`, se dice solo el resumen (evento `voz`; sin él, las dos primeras oraciones) y la respuesta completa queda en el chat, alternar «Ver el chat» / «Voz» con el panel compacto y el aviso de privacidad siempre visibles, Esc y «Salir del modo voz», una propuesta de acción saca al chat con la tarjeta visible y nada se confirma por voz, chat de texto con canal `texto`, `prefers-reduced-motion` sin animaciones con un glifo por estado (claro y oscuro), volumen del orbe (micrófono y Web Audio simulados: sube y baja con el nivel, no se mueve mientras habla el asistente, pulso por palabra, se degrada si no hay segundo flujo de audio, `orbe-volumen="no"`, movimiento reducido, se paran pistas y contexto al salir) el acuse inmediato (si el resumen tarda se dice una frase corta antes del resumen y rota entre turnos; con respuesta rápida, `acuse="no"`, modo apagado o interrupción no suena; no cuenta como respuesta ni como `habla_ms`) y el evento `asistente:metricas` (fuente `resumen`/`respaldo`, solo números, una vez por turno) |
| `manos-libres.e2e.js` | no (todo simulado) | modo voz (máquina de estados): disponibilidad (sin Web Speech o con `voz-motor="servidor"` no aparece), armado con indicador y aviso de privacidad, palabra de activación (parcial y final), captura al campo sin enviar, confirmación y «enviar»/«cancelar»/botones, «enviar» dentro de una frase es texto, lectura de la respuesta y vuelta a armado, reinicio del reconocimiento, apagado (botón, Esc, voz, permiso denegado, errores de red, inactividad) e interrupción de la lectura con la palabra. El reconocimiento se guía con `window.__decir(texto, final)` / `__terminar()` / `__error(codigo)`: no juzga el reconocimiento real |
| `tema.e2e.js` | no (chat y voz simulados) | tema claro/oscuro: `prefers-color-scheme` emulado, atributo `tema` (forzar, auto, inválido, en caliente sin reiniciar la sesión), reacción al cambio del sistema, variables `--asistente-*` del anfitrión por encima de la paleta, y auditoría de contraste computado (≥ 4,5:1) de todo el texto visible en ambos temas con conversación (tabla, código, enlace), tarjeta de confirmación, error y cada estado de manos libres. Capturas `2x-tema-*.png` |
| `acciones.e2e.js` | no (chat y endpoints fabricados) | tarjeta de confirmación de acciones (Fase 5): resumen y detalle del sistema como texto, un clic de script no confirma, Confirmar pide el token de escritura al sistema y lo usa, Cancelar usa el de lectura, resultados (hecho, conflicto, sin permiso, 409 cancelada/vencida, 403), reintento si el sistema no emite el token, vencimiento y reemplazo en pantalla, evento `asistente:confirmacion` y propuesta mal formada |
| `memoria.e2e.js` | no (estado, chat y endpoints fabricados) | memoria por usuario (Fase 1): sin `memoria` en `/v1/estado` no hay botón ni panel; panel «Lo que recuerdo» (lista, olvidar uno y todo con la sesión y sin diálogo, Escape y foco, texto del servidor sin HTML, contraste computado en ambos temas, oculto en la vista de voz); tarjeta local (un clic de script no confirma, Confirmar usa `confirmar-local` con la sesión y no pide token al anfitrión, cancelar, tope, 403 y 409) y control de que la del anfitrión sigue pidiendo su token |
| `ajustes.e2e.js` | no (estado, TTS y reproducción simulados) | panel de ajustes (engranaje): accesibilidad (etiquetas, foco al abrir y al cerrar con Esc, volumen con flechas), `ajustes="no"` sin engranaje, selector de voz solo si hay navegador y servidor, elección de tipo y voz del servidor (la voz viaja en la petición, el caché es por voz, una voz retirada cae a la predeterminada, una sola voz no muestra selector), volumen y velocidad aplicados a `speechSynthesis` (`rate`) y al `<audio>` (`playbackRate`) y guardados en `localStorage` (sobrevive a recargar; un guardado inválido se ignora), «probar voz» con la voz elegida (sin pedir audio al servidor si se elige la del navegador), lectura automática sincronizada con el altavoz, acuse solo con modo voz, «restablecer». Para probar un `widget.js` aún no desplegado: `WIDGET_LOCAL` (ver el encabezado del archivo) |
| `voz.e2e.js` | sí (la respuesta) | dictado con el STT del **servidor** (desactiva Web Speech): botón de micrófono, grabación real con `MediaRecorder` sobre un micrófono simulado, transcripción con whisper, el campo se rellena sin enviar, el texto dictado se envía y trae la cifra de la tool (660,5), y el aviso de "sin texto" con audio en silencio |

## Voz (`voz.e2e.js`)

Requiere whisper y un wav con voz (no se versiona; `tests_e2e/voz.wav` está en `.gitignore`). Se genera con el propio speaches:

```sh
docker compose -f docker-compose.dev.yml --profile voz up -d whisper      # y reiniciar `asistente` si estaba arrancado sin él
curl -X POST localhost:8300/v1/models/speaches-ai/Kokoro-82M-v1.0-ONNX     # una vez (descarga el TTS)
curl localhost:8300/v1/audio/speech -H 'Content-Type: application/json' -o tests_e2e/voz.wav \
  -d '{"model":"speaches-ai/Kokoro-82M-v1.0-ONNX","voice":"ef_dora","input":"¿Cuántas hectáreas de soja tengo?","response_format":"wav"}'
python3 -m http.server 8299 -d tests_e2e    # el sandbox del MCP no tiene fs: el test lee el wav por HTTP
```

La aserción sobre la transcripción es laxa (`hectáreas|soja`): whisper-small puede equivocar palabras sueltas.
