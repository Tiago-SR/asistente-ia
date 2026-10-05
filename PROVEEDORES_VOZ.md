# Proveedores de voz a comparar (STT y TTS)

> Fecha de los datos: **2026-10-04**. Los precios cambian seguido y varios son promociones: confirmar en la página oficial antes de decidir.
> **Estado (2026-10-05):** este documento nació para elegir un STT y un TTS remotos, pero la prueba manual cambió el plan: el camino principal es **la voz del navegador** (Web Speech), ya implementada en el widget (ver [Estado y pendientes](README.md#estado-y-pendientes) y el [contrato, sección 7.4](contrato/CONTRATO.md#74-voz-opcional)). Lo de abajo queda como referencia para un **respaldo remoto opcional** (clientes que no puedan enviar audio a Google, o una voz más natural). Nada de esto bloquea el trabajo actual.
> Contexto: el STT local de antes (Whisper `small` en un contenedor speaches) no daba la calidad necesaria.
> Idioma objetivo: español rioplatense (`es-UY`). La calidad en ese acento es lo primero que hay que medir; lo que sigue sobre calidad es orientativo y **no está probado por nosotros**.

## Resultados de nuestras pruebas (2026-10-05, banco `herramientas/probar_audio/`)

| Motor | Resultado |
|---|---|
| Whisper `small` local (speaches) | Malo: errores de vocabulario («soja» → «soca», «cuántas» → «cuantas»). Los números los transcribe bien. Unos 2 s de latencia en CPU |
| **`SpeechRecognition` del navegador** (Chrome) | **Mucho mejor** que Whisper `small`, según la prueba manual con voz real |
| Kokoro local (`ef_dora`) | Primer audio en ≈1,5–1,6 s en CPU; calidad inferior a la del navegador |
| **`speechSynthesis` del navegador, voz es-ES** | **Mejor** que Kokoro local |
| Detector de voz por energía (valores de Jarvis) | La interrupción funciona (corta el audio al hablar) |

Pendiente de medir: ElevenLabs, OpenAI, Deepgram y demás de las tablas de abajo. Por ahora no hay ninguna comparación contra un proveedor remoto.

### Los motores del navegador como candidatos

| Motor | Precio | Encaje | Ventajas | Desventajas |
|---|---|---|---|---|
| **`SpeechRecognition`** (Web Speech API; en Chrome usa el servicio de voz de Google) | $0 | Del lado del cliente: el widget lo usa directamente, sin pasar por el servidor del asistente | Gratis, sin clave ni infraestructura, buena calidad probada en español, resultados parciales mientras se habla | El audio va a Google (privacidad: pregunta abierta en [Estado y pendientes](README.md#estado-y-pendientes)). Solo Chrome/Edge/Safari, no hay control del modelo ni de la versión, sin garantía de servicio, y puede cambiar o dejar de funcionar. No hay forma de usarlo desde el servidor |
| **`speechSynthesis`** (voces del sistema o de Chrome) | $0 | Del lado del cliente | Gratis, sin latencia de red (las voces locales) y mejor que Kokoro en nuestra prueba | Las voces dependen del sistema operativo y del navegador: cada usuario oirá algo distinto, y en Linux a veces no hay ninguna en español. Mejor probada con es-ES que con es-UY. Calidad por debajo de los servicios comerciales neuronales |

## Cómo se lee la columna "Encaje"

El servicio ya habla con cualquier endpoint compatible con OpenAI (`/v1/audio/transcriptions`), configurado por `STT_BASE_URL`, `STT_MODELO` y `STT_API_KEY` (`core/voz/openai_compat.py`).

- **Directo:** solo se cambian variables de entorno.
- **Adaptador:** hay que escribir un adaptador nuevo en `core/voz/` (el puerto `STT` ya existe; el de `TTS` falta y se diseña igual).

## STT (voz → texto)

| Proveedor / modelo | Precio | Encaje | Ventajas | Desventajas |
|---|---|---|---|---|
| **Groq** `whisper-large-v3-turbo` | $0.04 por hora de audio (mínimo facturable de 10 s por petición). `whisper-large-v3`: $0.111/h | Directo (API compatible con OpenAI) | El más barato con diferencia y muy rápido (~216× tiempo real). Sigue siendo Whisper, pero el modelo grande, no el `small` que probamos | Sigue siendo Whisper: si lo que falla es la familia y no el tamaño, no mejora. Solo por lotes (el dictado envía el audio completo, así que alcanza). El mínimo de 10 s encarece los dictados muy cortos |
| **OpenAI** `gpt-4o-mini-transcribe` | $0.003/min ($1.25 por M tokens de entrada, $5 por M de salida) | Directo | Barato; no es Whisper (familia GPT-4o). Mismo proveedor que un posible TTS | Datos van a OpenAI. Sin streaming de resultados parciales en el endpoint simple |
| **OpenAI** `gpt-4o-transcribe` | $0.006/min ($2.50 por M entrada, $10 por M salida) | Directo | Mayor precisión que la versión mini según el propio proveedor | El doble de caro que la mini; mismos puntos sobre privacidad |
| **Deepgram** Nova-3 (multilingüe) | $0.0052/min por lotes; $0.0058/min en streaming (precios promocionales). $200 de crédito al registrarse | Adaptador | Streaming con baja latencia (útil para el modo Jarvis y para dictar sin esperar). Buena documentación | La página de precios no lista español explícitamente: confirmar en su documentación que `es` está en Nova-3 multilingüe. Habría que escribir un adaptador |
| **ElevenLabs** Scribe v2 | $0.22/hora ($0.0037/min); Scribe v2 Realtime: $0.39/hora | Adaptador | Precio bajo y variante en tiempo real. Mismo proveedor que un posible TTS | Hay cargos opcionales aparte (detección de entidades $0.07/h, palabras clave $0.05/h). Adaptador propio |
| **Cartesia** Ink (STT) | $0.39 por hora en el plan Scale (3 créditos por segundo de audio) | Adaptador | Pensado para voz en tiempo real; mismo proveedor que Sonic (TTS) | Precio por crédito en planes menores no verificado. Menos referencias de calidad en español rioplatense |
| **Google Cloud** Speech-to-Text (Chirp) | **No verificado**: la página no se pudo leer | Adaptador | Muchas variantes de idioma, incluida `es-UY` | Precios no confirmados; configuración más pesada (proyecto de GCP, credenciales) |
| **Azure** AI Speech | Real-time: tarifas por región y moneda (no verificadas). Gratis: 5 horas de audio por mes | Adaptador | Soporta `es-UY` de forma explícita; nivel gratuito | Precio depende de región; configuración más pesada |
| **Whisper local** con un modelo más grande (`medium` / `large-v3`) | Sin costo por uso; necesita CPU/GPU en el VPS | Directo (ya está en el compose) | Los datos no salen del servidor | El `small` ya dio mala calidad; modelos mayores en CPU son lentos y necesitan bastante RAM. Solo tiene sentido con GPU |

## TTS (texto → voz)

| Proveedor / modelo | Precio | Encaje | Ventajas | Desventajas |
|---|---|---|---|---|
| **ElevenLabs** v4 / v3 / Multilingual v2 / Flash | v4: $0.022 por 1K caracteres (promoción hasta el 12/10; $0.08 normal). v4 Turbo: $0.011 (normal $0.04). v3, v2 multilingüe: $0.08. Flash/Turbo: $0.04. Planes: Starter $6/mes (273 000 caracteres), Creator $22/mes (1 M), Pro $99/mes (4,5 M) | Adaptador | Suele ser la referencia en naturalidad; muchas voces y clonación. Streaming | De los más caros por carácter fuera de promoción. Hay que comprobar cómo suena en acento rioplatense |
| **OpenAI** `gpt-4o-mini-tts` | ≈ $0.015 por minuto de audio (cobra tokens de texto de entrada y de audio de salida) | Directo (compatible con `/v1/audio/speech`) | Se puede indicar el tono por instrucciones ("habla pausado, cálido"). Un solo proveedor para STT y TTS. Streaming | Pocas voces fijas; hay que evaluar el acento en español. El costo real por token a veces difiere de lo estimado (hay reportes en el foro de OpenAI) |
| **Cartesia** Sonic | Un minuto de audio = 750–800 créditos; 1 crédito = 1 carácter. Planes: Free (20K créditos/mes), Pro $5/mes, Startup $49, Scale $299 | Adaptador | Diseñado para latencia muy baja (clave para que "hable" fluido); mismo proveedor que Ink (STT) | Precio por crédito de cada plan no verificado. Menos catálogo de voces en español |
| **Deepgram** Aura-2 | $0.030 por 1K caracteres | Adaptador | Baja latencia, precio estable, un solo proveedor con su STT | Hay que confirmar voces en español de Aura-2 en su documentación |
| **Google Cloud** Chirp 3 HD | $30 por millón de caracteres; **primer millón de caracteres por mes gratis** (según el buscador; la página oficial no se pudo leer) | Adaptador | Gratis hasta un millón de caracteres por mes: cubre las pruebas y un uso moderado. Soporta `es-UY` | Configuración más pesada (proyecto de GCP, credenciales). Naturalidad a comprobar |
| **Azure** Neural TTS | Tarifas por región (no verificadas). Gratis: 0,5 M de caracteres por mes | Adaptador | Voces neuronales en `es-UY` (hay voces uruguayas) y control fino (SSML) | Precio depende de región; configuración más pesada |
| **Kokoro** (local, ya probado en speaches) | Sin costo por uso | Directo (speaches expone `/v1/audio/speech`) | Sin costo, los datos no salen del servidor. Ya generó el `voz.wav` de los e2e (voz `ef_dora`) | Calidad por debajo de los servicios comerciales; en CPU añade latencia. Cuesta el 2 GB de RAM del contenedor |

**Descartado:** Groq Orpheus TTS ($22 por millón de caracteres) solo ofrece inglés y árabe; PlayAI en Groq se cerró el 31/12/2025.

## Combinaciones razonables

1. **Todo OpenAI** (`gpt-4o-mini-transcribe` + `gpt-4o-mini-tts`): el camino más corto, porque ambos entran por `STT_*`/`TTS_*` sin adaptadores. Un solo proveedor y una sola factura.
2. **Groq STT + el TTS que mejor suene:** el STT más barato y rápido, y se elige el TTS aparte.
3. **ElevenLabs** (Scribe + voz): la mejor naturalidad esperable, a mayor costo.
4. **Cartesia o Deepgram** (STT + TTS del mismo proveedor): pensados para latencia baja y streaming, lo que importa para que el modo "Jarvis" se sienta fluido.

## Estimación de costo (aproximada)

Supuestos: 1 000 consultas al mes; dictado de 15 s (250 min en total); respuesta hablada de unos 600 caracteres (~0,75 min de audio, 600 000 caracteres en total).

| Concepto | Costo mensual |
|---|---|
| STT Groq turbo | ≈ $0.17 |
| STT OpenAI mini | ≈ $0.75 |
| STT ElevenLabs Scribe | ≈ $0.92 |
| STT Deepgram Nova-3 | ≈ $1.30–1.45 |
| TTS Google Chirp 3 HD | $0 (dentro del millón gratis) |
| TTS OpenAI mini | ≈ $11 |
| TTS Deepgram Aura-2 | ≈ $18 |
| TTS ElevenLabs Flash/Turbo ($0.04 por 1K) | ≈ $24 (v4 Turbo $0.011 durante la promoción: ≈ $6.60) |

El STT cuesta casi nada en cualquier opción: **la decisión de STT es de calidad, no de precio**. El TTS sí pesa en el costo, y es proporcional al largo de las respuestas (se puede limitar con el prompt).

## Cómo decidir (prueba propuesta)

1. Grabar 20–30 frases en español rioplatense: cifras, hectáreas, nombres de cultivos y de establecimientos, y alguna con ruido de fondo.
2. Pasarlas por 3–4 candidatos de STT y medir el porcentaje de error de palabras (WER), el error en cifras y la latencia.
3. Para TTS, generar 5–6 respuestas típicas del asistente con 3–4 voces y juzgar a ciegas: naturalidad, acento, pronunciación de cifras y unidades, y latencia hasta el primer audio.
4. Anotar privacidad: a dónde viaja el audio, si el proveedor lo retiene o entrena con él, y si ofrece acuerdo de no retención (pregunta abierta de privacidad, ver el README).

## Fuentes

- Deepgram: [deepgram.com/pricing](https://deepgram.com/pricing)
- ElevenLabs: [elevenlabs.io/pricing/api](https://elevenlabs.io/pricing/api)
- Cartesia: [cartesia.ai/pricing](https://cartesia.ai/pricing)
- OpenAI (no se pudo leer la página oficial; cifras de terceros): [cloudprice.net gpt-4o-transcribe](https://cloudprice.net/models/gpt-4o-transcribe), [cloudprice.net gpt-4o-mini-tts](https://cloudprice.net/models/gpt-4o-mini-tts), [foro de OpenAI sobre el precio del TTS](https://community.openai.com/t/new-tts-api-pricing-and-gotchas/1150616)
- Groq (resultados de búsqueda): [whisper-large-v3-turbo](https://console.groq.com/docs/model/whisper-large-v3-turbo), [Orpheus TTS](https://console.groq.com/docs/model/canopylabs/orpheus-v1-english)
- Google TTS: [precios de Text-to-Speech](https://cloud.google.com/text-to-speech/pricing)
- Azure: [precios de AI Speech](https://azure.microsoft.com/es-es/pricing/details/speech/)
