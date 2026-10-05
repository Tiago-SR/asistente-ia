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
