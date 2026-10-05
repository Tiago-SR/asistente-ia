# Prueba manual de voz en navegadores reales

Checklist para probar a mano lo que los e2e no pueden juzgar (los e2e simulan `SpeechRecognition` y `speechSynthesis`: no dicen nada de la calidad ni de la disponibilidad reales). Tiempo estimado: 30 min en Chrome de escritorio, 10–15 min por cada navegador o dispositivo adicional. Contrato de referencia: [`contrato/CONTRATO.md`](contrato/CONTRATO.md) §7.3 y §7.4.

Lo ya probado (Chrome de escritorio, manos libres con auriculares) no se repite aquí salvo el caso B7.

## 0. Preparación

1. Stack arriba: `docker compose -f docker-compose.dev.yml up -d` (asistente, postgres, sistema-php) y el LLM configurado en `.env`.
2. Página de prueba: <http://localhost:8203/?usuario=ana> (sistema-php) o el mock en <http://localhost:8201/?usuario=ana>. Ana debe responder con datos reales de la tool (ej. «¿cuántas hectáreas tengo?» → 870,5).
3. Si editaste `widget.js`: `docker compose -f docker-compose.dev.yml restart asistente`.
4. Abre DevTools → Consola y pega esto para anotar las voces disponibles en ese navegador (si sale vacío, espera unos segundos y repite: algunos navegadores las cargan tarde):

```js
speechSynthesis.getVoices().filter(v => v.lang.toLowerCase().startsWith('es'))
  .map(v => `${v.name} | ${v.lang} | ${v.localService ? 'local' : 'remota'}`)
```

5. Anota navegador, versión, sistema operativo y salida de `navigator.userAgent`.

## 1. Matriz

Marca cada celda con ✅ / ⚠️ (funciona con reservas) / ❌ / — (no aplica o no se probó). El detalle de cada caso está en la sección 2.

| Caso | Chrome escritorio | Edge escritorio | Chrome Android | Safari macOS | Safari iOS |
|---|---|---|---|---|---|
| A1 Voces es-UY / es-ES | | | | | |
| A2 Voz elegida correcta | | | | | |
| A3 Atributo `voz` | | | | | |
| B1 Dictado al campo | | | | | |
| B2 Dictado → leer respuesta | | | | | |
| B3 Lectura automática | | | | | |
| B4 Silenciar al dictar/enviar | | | | | |
| B5 Pestaña en segundo plano / pantalla bloqueada | | | | | |
| B6 Permiso de micrófono denegado | | | | | |
| B7 Manos libres (auriculares) | ✅ | | | | |
| B8 Manos libres: reinicio tras silencio largo | | | | | |
| C1 Layout y teclado en móvil | — | — | | — | |

## 2. Casos

### A. Voces

- **A1 – Voces disponibles.** Con el snippet de la preparación, ¿hay voces `es-UY`? ¿`es-ES`? ¿`es-MX`/`es-AR`/otras? ¿Son locales o remotas? Anota los nombres. *Esperado:* al menos una voz en español; es-UY probablemente no exista y es normal.
- **A2 – Qué voz elige el widget.** Con `idioma` por defecto, haz leer una respuesta y comprueba en la consola cuál sonó (`speechSynthesis.speaking` no lo dice; fíjate en el acento o fuerza con A3). *Esperado:* es-UY si existe; si no, es-ES; si no, cualquiera en español. Anota si cayó en una voz que no es de español (sería un bug).
- **A3 – Atributo `voz`.** Pon `voz="<nombre exacto de A1>"` en la etiqueta y recarga. *Esperado:* suena esa voz. Con un nombre inexistente debe caer en la regla normal, sin error.

### B. Dictado, lectura y manos libres

- **B1 – Dictado.** Pulsa el micrófono, di «¿cuántas hectáreas de soja tengo?». *Esperado:* el texto parcial aparece mientras hablas, el final queda en el campo **sin enviarse**. Anota errores de transcripción (palabras mal reconocidas) y el retraso entre dejar de hablar y el texto final.
- **B2 – Dictado seguido de lectura.** Envía lo dictado y pulsa el botón de escuchar de la respuesta. *Esperado:* se lee completa, sin Markdown ni enlaces dictados («asterisco», «http…»). Tablas y listas: anota si se lee de forma comprensible.
- **B3 – Lectura automática.** Activa el interruptor de la barra, haz una pregunta larga. *Esperado:* empieza a leer por oraciones antes de que termine la respuesta, sin cortes raros entre oraciones ni silencios largos. Recarga la pestaña: ¿recuerda el interruptor?
- **B4 – Silenciar.** Con la lectura en curso: (a) pulsa el micrófono, (b) envía otro mensaje, (c) apaga el interruptor. *Esperado:* en los tres casos la lectura se detiene al instante.
- **B5 – Segundo plano.** Con una lectura en curso, cambia de pestaña, y en móvil bloquea la pantalla. Anota si la voz sigue, se corta o se queda colgada al volver (algunos navegadores pausan `speechSynthesis`). Un widget que queda sin poder leer tras volver es un bug a reportar.
- **B6 – Permiso denegado.** Bloquea el micrófono para el sitio y pulsa el micrófono y, aparte, Manos libres. *Esperado:* aviso claro, el widget sigue usable por texto, y Manos libres no queda «encendido» por error.
- **B7 – Manos libres con auriculares (regresión).** «asistente, ¿cuántas hectáreas tengo?» → pausa → «enviar» → lectura → interrumpir diciendo «asistente». Es el caso que ya pasó. **Si la interrupción vuelve a exigir hablar muy fuerte,** antes de tocar nada anota, por favor:
  - qué auriculares/micrófono (de cable, bluetooth, o parlantes con micrófono del portátil);
  - volumen de lectura del sistema y de la voz;
  - si la voz era local o remota (A1);
  - si pasa hablando justo cuando el asistente habla o también en los huecos entre oraciones;
  - lo que muestra el widget como texto parcial mientras hablas (¿aparece la palabra o no?). Eso distingue «el micrófono no te oye» de «te oye pero la palabra no llega al comienzo de la frase».
- **B8 – Manos libres tras silencio largo.** Déjalo armado ~2 minutos sin hablar y luego di la palabra. *Esperado:* sigue respondiendo (Chrome corta el reconocimiento y el widget lo reinicia). Anota si hubo un aviso o si se apagó solo antes de los 5 min por defecto.

### C. Móvil

- **C1 – Layout.** Ancho de teléfono: columna de mensajes usable, entrada fija abajo, el teclado virtual no tapa el campo ni deja la página desplazada, sin scroll horizontal. En iOS comprueba además la barra de Safari al hacer scroll.

## 3. Cómo probar en móvil y Safari

La Web Speech y el micrófono requieren un **contexto seguro** (HTTPS o `localhost`), así que `http://<IP-de-tu-PC>:8203` no sirve en el teléfono.

- **Chrome Android (más simple):** USB + depuración USB y, en el PC, `adb reverse tcp:8203 tcp:8203` y `adb reverse tcp:8100 tcp:8100`. Entonces `http://localhost:8203` abre desde el teléfono y cuenta como contexto seguro. El `servidor` del widget también debe ser `localhost:8100` visto desde el teléfono (el reverse del 8100 lo cubre).
- **Safari iOS / Safari macOS / sin cable:** un túnel HTTPS (por ejemplo `cloudflared tunnel --url http://localhost:8203`) para la página. El asistente también debe ser alcanzable por HTTPS desde el navegador (otro túnel para el 8100) y los dos orígenes deben estar en `origenes_permitidos` del sistema en `config/sistemas.yaml`. Es trabajo de preparación: si no quieres montarlo, anótalo como «no probado» y no bloquea nada.
- No pegues tokens ni URLs de túnel en reportes: son temporales, pero igual.

## 4. Qué esperamos (a confirmar, no asumir)

Son expectativas razonables, no hechos verificados; la prueba existe para confirmarlas:

- Edge de escritorio debería comportarse como Chrome (misma base), pero su servicio de voz es otro.
- Safari tiene `SpeechRecognition` con prefijo y menos estable; el reconocimiento continuo de manos libres es el punto más probable de fallo, sobre todo en iOS.
- El móvil suele cortar el micrófono y la síntesis al bloquear pantalla o cambiar de app.

Si manos libres no sirve en algún navegador, la salida prevista es ocultarlo ahí (ya se oculta sin Web Speech o sin contexto seguro), no parchearlo.

## 5. Formato del reporte

Pégame una tabla como la de la sección 1 y, por cada ⚠️/❌, una línea con: caso, navegador y versión, qué pasó y qué esperabas. Con eso decidimos si hace falta la opción (b) de endurecer manos libres o algún ajuste puntual del widget.
