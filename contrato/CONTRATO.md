# Contrato de integración v1

Lo que **cada sistema** debe implementar para que el asistente responda preguntas sobre sus datos. Es HTTP + JSON, con tres piezas obligatorias (token, manifiesto, ejecución) y una opcional (salud). Las rutas mostradas son las sugeridas; en `config/sistemas.yaml` son configurables. La interfaz para el usuario es el [widget de la sección 7](#7-widget-de-chat-interfaz-para-el-usuario), que el sistema inserta en una página.

Archivos de referencia:

- `schemas/*.schema.json`: JSON Schemas de cada mensaje.
- `openapi.yaml`: descripción OpenAPI de los endpoints.
- [`GUIA_TOOLS.md`](GUIA_TOOLS.md): cómo diseñar las tools (qué exponer, cómo describirlas, qué devolver).
- `../herramientas/verificar_sistema.py`: verificador de conformidad (ver [6.5](#65-verificar-la-integración)).

Principio: **el asistente nunca accede a la BD del sistema ni decide permisos.** Solo llama a tools con el token del usuario, y el sistema aplica sus propios permisos.

## 1. Emisión del token de usuario

Ruta del sistema (p. ej. `GET /asistente/token`), accesible desde su UI con su sesión normal. Devuelve:

```json
{ "token": "<jwt>", "expira": "2026-10-03T15:30:00Z" }
```

Si el usuario no tiene permitido el asistente, responde `403` y el widget muestra un aviso de que no está disponible (ver [sección 7](#7-widget-de-chat-interfaz-para-el-usuario)).

| Claim | Obligatorio | Contenido |
|---|---|---|
| `iss` | sí | id del sistema, igual al `id` en el registro del asistente |
| `aud` | sí | `"asistente"` (configurable) |
| `sub` | sí | identificador estable del usuario (string opaco) |
| `iat`, `exp` | sí | vida corta: **5–15 min** |
| `jti` | sí | id único (auditoría) |
| `scope` | sí | `"asistente:lectura"` |
| `nombre` | no | nombre a mostrar |
| `tenants` | no | ids de organización del usuario, solo para métricas y cuotas. **Nunca se usa para autorizar** |
| `locale` | no | p. ej. `es-UY` |

Firma recomendada: `RS256` o `EdDSA` (el sistema guarda la privada, el asistente solo la pública). Aceptado para sistemas legados y pruebas locales: `HS256` con secreto compartido. `alg: none` se rechaza siempre. Cómo se generan y dónde se guardan las claves: ver [sección 6](#6-credenciales-y-registro-del-sistema).

## 2. Manifiesto de tools

`GET {base_url}/asistente/tools` con `Authorization: Bearer <token_manifiesto>` (credencial de servicio, solo sirve para esto; no contiene datos de usuarios).

```json
{
  "contrato": "1",
  "sistema": { "nombre": "SGAgro – Cliente A", "version": "4.2.0" },
  "tools": [
    {
      "nombre": "listar_establecimientos",
      "descripcion": "Lista los establecimientos que el usuario puede ver. Usar primero para resolver nombres a ids.",
      "parametros": {
        "type": "object",
        "properties": { "texto": { "type": "string", "description": "filtro por nombre" } },
        "additionalProperties": false
      },
      "efecto": "lectura",
      "timeout_s": 15
    }
  ]
}
```

Reglas (si no se cumplen, la tool o el manifiesto se rechazan y se loguea):

- `nombre`: `^[a-z][a-z0-9_]{0,63}$`, único.
- `descripcion`: ≤ 1 000 caracteres. `parametros`: JSON Schema válido, tipo `object`.
- `efecto` ∈ {`lectura`, `escritura`}. **En el MVP solo se exponen al modelo las de `lectura`.**
- Máximo 40 tools por sistema y 256 KB por manifiesto.
- Se cachea con TTL configurable y se puede recargar a mano.

La calidad de las descripciones determina la calidad del asistente: deben decir qué hace la tool, cuándo usarla y qué significan los parámetros. Ver la [guía de diseño de tools](GUIA_TOOLS.md).

## 3. Ejecución de una tool

`POST {base_url}/asistente/tools/{nombre}`

```http
Authorization: Bearer <token de usuario>
X-Asistente-Contrato: 1
X-Asistente-Request-Id: 7b1e…
Content-Type: application/json

{ "parametros": { "texto": "El Matorral" } }
```

Éxito (`200`):

```json
{
  "ok": true,
  "datos": { "establecimientos": [ { "id": "123", "nombre": "El Matorral", "superficie_ha": 540.5 } ] },
  "fuente": "establecimientos",
  "ui": [ { "tipo": "navegar", "url": "/establecimientos/123", "etiqueta": "Ver establecimiento" } ]
}
```

Error de negocio (`200` con `ok: false`):

```json
{ "ok": false, "error": "no_encontrado", "detalle": "No existe o no tenés acceso" }
```

| Situación | Respuesta del sistema | Qué hace el asistente |
|---|---|---|
| OK | `200`, `ok: true` | pasa `datos` (y `fuente`) al modelo; `ui` va al widget, **no** al modelo |
| Error de negocio | `200`, `ok: false`, `error` ∈ {`no_encontrado`, `sin_acceso`, `parametros_invalidos`, `no_disponible`} | lo pasa al modelo, que no debe rellenar con suposiciones |
| Token inválido/vencido | `401` | corta el turno y emite `token_expirado` al widget, que renueva y reintenta |
| Scope insuficiente | `403` | `sin_acceso` |
| Error del sistema | `5xx` / timeout / JSON inválido | `error_sistema` / `timeout` / `respuesta_invalida` al modelo |

Requisitos para el sistema:

- **Validar el token con su propia clave** y rechazar (`403`) el `token_manifiesto` en este endpoint.
- **Rechazar toda escritura** con scope `asistente:lectura`. Esta es la capa de solo lectura que vale: el asistente no puede verificar qué hace realmente una tool remota.
- Tratar los ids y parámetros que llegan como **no confiables**: validar y aplicar permisos como con cualquier input.

Recomendaciones:

- Datos agregados y compactos, con unidades en el nombre del campo (`superficie_ha`, `rinde_kg_ha`) y fechas ISO 8601.
- No devolver geometrías ni listas de miles de filas: resumir del lado del sistema.
- El asistente trunca respuestas por encima de un límite configurable (p. ej. 50 KB) y se lo indica al modelo.
- Más criterios y ejemplos buenos y malos en la [guía de diseño de tools](GUIA_TOOLS.md).

## 4. Salud (opcional)

`GET {base_url}/asistente/salud` → `{"ok": true}`. Lo usan el verificador y el monitoreo.

## 5. Versionado

- El manifiesto declara `contrato`. El asistente acepta las versiones que soporta y rechaza las demás con un error claro en el log.
- Cambios compatibles (campos opcionales nuevos) no suben versión; los incompatibles sí.

## 6. Credenciales y registro del sistema

Hay **dos credenciales** distintas. Las crea quien integra el sistema (no las entrega ningún servicio), cada una se guarda en dos lugares y **nunca se escribe en `config/sistemas.yaml`**: el archivo solo referencia el *nombre* de la variable de entorno.

| Credencial | Para qué sirve | Quién la usa | Qué acepta quien la recibe |
|---|---|---|---|
| **Clave de firma de tokens** | Firmar (sistema) y validar (asistente) los JWT de usuario de la sección 1 | El sistema firma; el asistente valida | Solo tokens con `iss`, `aud`, `exp` y firma correctos |
| **Token de manifiesto** | Autenticar al asistente cuando lee el manifiesto (sección 2) | El asistente la envía; el sistema la compara | Solo en `GET /asistente/tools`. En la ejecución (sección 3) el sistema la rechaza con `403` |

Son independientes: no reutilizar un valor por otro. La clave de firma identifica a un *usuario*; el token de manifiesto, al *servicio* y no da acceso a datos.

### 6.1 Opción A: `HS256` con secreto compartido (pruebas locales y sistemas legados)

El mismo secreto está en el sistema y en el asistente. Quien lo conozca puede emitir tokens como cualquier usuario del sistema, así que se trata como una contraseña.

1. Generar los dos valores, una sola vez (mínimo 32 bytes aleatorios; el comando da 64 caracteres hex):
   ```sh
   openssl rand -hex 32   # → clave de firma
   openssl rand -hex 32   # → token de manifiesto
   ```
2. **En el asistente**, en `.env` (fuera de git), con los nombres que referencia el registro:
   ```sh
   STMGIS_SECRETO=<clave de firma>
   STMGIS_MANIFEST_TOKEN=<token de manifiesto>
   ```
3. **En el sistema**, los mismos valores en su configuración o variables de entorno (también fuera del control de versiones):
   - la clave de firma, para firmar los JWT con `HS256`;
   - el token de manifiesto, para comparar el `Authorization: Bearer` de `GET /asistente/tools`. Usar una comparación de tiempo constante (`hash_equals` en PHP, `hmac.compare_digest` en Python).
4. Registrar el sistema (`config/sistemas.yaml`):
   ```yaml
   sistemas:
     - id: stmgis                  # = claim `iss` de todos sus tokens
       nombre: "STMGIS"
       base_url: http://host.docker.internal:8002   # backend; ver 6.3
       origenes_permitidos:
         - http://localhost:8002   # origen de la página con el widget
       auth:
         algoritmo: HS256
         secreto_env: STMGIS_SECRETO
         audiencia: asistente      # = claim `aud`
       conector:
         token_manifiesto_env: STMGIS_MANIFEST_TOKEN
   ```
5. Reiniciar el asistente (las variables de entorno se leen al arrancar; `POST /admin/recargar` relee el YAML pero **no** cambia variables de entorno).

### 6.2 Opción B: `RS256` o `EdDSA` (recomendada fuera de pruebas)

El sistema guarda la clave **privada** y firma con ella; al asistente solo llega la **pública**, que no permite emitir tokens aunque se filtre.

```sh
openssl genpkey -algorithm RSA -pkeyopt rsa_keygen_bits:3072 -out sistema-priv.pem
openssl pkey -in sistema-priv.pem -pubout -out sistema-pub.pem
```

En el registro se reemplaza `secreto_env` por `clave_publica_env: STMGIS_PUBKEY` (el contenido PEM de la pública en esa variable) o por `jwks_url`, y `algoritmo` pasa a `RS256` o `EdDSA`. El token de manifiesto se genera y guarda igual que en la opción A.

### 6.3 Reglas del registro

- **`id` = `iss`:** el `id` del YAML debe ser idéntico al claim `iss` de los tokens, y `audiencia` al claim `aud`. Si no coinciden, el asistente responde `token_invalido`. El `id` es solo un identificador que se elige (`^[a-z0-9][a-z0-9_-]{0,63}$`) y no tiene que existir en otro lugar.
- **`base_url`:** el **backend** que sirve `/asistente/*`; el asistente lo llama de servidor a servidor. Si el asistente corre en Docker y el sistema en el host, usar `host.docker.internal:<puerto>` y que el sistema escuche en `0.0.0.0` (no solo `127.0.0.1`).
- **`origenes_permitidos`:** orígenes exactos (esquema + host + puerto) de las **páginas** donde se inserta el widget. Se usan para CORS y se verifican contra el `Origin` de cada request. `http://localhost:8002` y `http://127.0.0.1:8002` son orígenes distintos.
- **Variables faltantes:** si falta alguna variable referenciada, **ese sistema** queda deshabilitado (el resto sigue) y el motivo queda en el log y en `GET /admin/sistemas`.
- **Verificar la integración:** ver [6.5](#65-verificar-la-integración).

### 6.4 Rotación y manejo

- **Rotar** = generar un valor nuevo, cambiarlo en el sistema y en el `.env` del asistente y reiniciar el asistente. El asistente solo conoce una clave por sistema: entre ambos cambios, los tokens firmados con la clave anterior fallan (vida máxima 15 min, el widget pide uno nuevo). Hacerlo en una ventana de poco uso.
- Rotar de inmediato ante cualquier sospecha de filtración, y cuando alguien con acceso al valor deje el proyecto.
- No poner estos valores en el repositorio, en tickets, en logs ni en el código del front. El navegador solo ve el JWT de vida corta, nunca la clave ni el token de manifiesto.
- Un valor por sistema y por entorno: pruebas y producción no comparten claves.

### 6.5 Verificar la integración

`herramientas/verificar_sistema.py` comprueba el contrato contra un sistema en marcha. **Un sistema no se habilita en producción sin pasar el verificador.** Los secretos se pasan por variables de entorno y se ocultan en el reporte.

```sh
export V_MANIFIESTO=<token de manifiesto>
export V_SECRETO=<clave de firma HS256>     # opcional, ver abajo
python herramientas/verificar_sistema.py --base-url http://localhost:8201 \
    --token-url "http://localhost:8201/asistente/token?usuario=ana" \
    --token-url-otro "http://localhost:8201/asistente/token?usuario=beto" \
    --token-manifiesto-env V_MANIFIESTO --secreto-firma-env V_SECRETO
```

Comprueba: salud; token (schema, claims, `alg`, vida ≤ 15 min); manifiesto (credencial, schema, versión, nombres, límites); ejecución sin token, con token ilegible, firmado con otra clave, `alg=none` y con el token de manifiesto (deben rechazarse); parámetros inválidos (`parametros_invalidos`); ids inexistentes y de otro usuario (`no_encontrado`/`sin_acceso`); rechazo de escrituras con scope de lectura; y tiempos, tamaño y geometrías de las respuestas. Los **avisos** (descripciones cortas, respuestas lentas o grandes, geometrías) no hacen fallar.

| Opción | Habilita |
|---|---|
| `--secreto-firma-env VAR` | token vencido (`401`), de otra audiencia (`401`) y con scope ajeno (`403`). Sin ella se omiten. Con claves `RS256`/`EdDSA`, `VAR` contiene la privada PEM y se indica `--algoritmo-firma` |
| `--token-url-otro URL` o `--id-ajeno ID` | probar un id de otro usuario. Requiere una tool de lectura con un id obligatorio (`--tool-id` si hay varias) |
| `--cabecera-token-env VAR` | enviar a la ruta de token una cabecera `Nombre: valor` (cookie de sesión, API key) leída del entorno |
| `--max-kb`, `--max-ms` | topes de tamaño (50 KB) y de tiempo (por defecto, el `timeout_s` de la tool) |

Imprime un reporte por secciones con un resumen y termina con código `0` si todo pasa, `1` si algo falla. Sirve igual en CI.

## 7. Widget de chat (interfaz para el usuario)

El asistente sirve un Web Component, `<asistente-chat>`, que el sistema inserta en una de sus páginas. No requiere framework ni build, y es independiente del stack del sistema. Es una **vista de chat a pantalla completa** (mensajes y entrada fija abajo; muestra solo la conversación actual, con un botón "Nueva conversación" en la barra superior y sin lista de chats por ahora), no una burbuja flotante.

### 7.1 Integración

```html
<script src="https://asistente.example.com/widget.js" defer></script>
<asistente-chat
    style="display:block;height:100vh"
    servidor="https://asistente.example.com"
    token-url="/asistente/token"></asistente-chat>
```

- **El widget ocupa el 100% de su contenedor y no se superpone a la página.** El sistema le da el tamaño: una ruta propia (p. ej. `/asistente`) con `height:100vh`, o un contenedor con alto definido. Si el contenedor no tiene alto, el widget se ve con un mínimo de 360 px.
- Conviene una página o pestaña dedicada y una entrada de menú que lleve a ella. Si el sistema quiere ocultar esa entrada cuando el asistente no está disponible, puede escuchar `asistente:estado` (ver 7.3).
- `token-url` es la ruta de emisión del [token de usuario](#1-emisión-del-token-de-usuario). Es **del mismo origen que la página** y se pide con las cookies de sesión del usuario, así que el widget nunca ve credenciales del sistema. Debe responder `{ "token", "expira" }`, o `403` si el usuario no tiene permitido el asistente.
- `servidor` es la URL del asistente. Si se omite, se usa el origen desde el que se cargó `widget.js`.

### 7.2 Qué necesita el sistema

1. **Registrar el origen de la página** en `origenes_permitidos` (sección [6.3](#63-reglas-del-registro)). Sin eso, el asistente rechaza los requests del widget con `origen_no_permitido`.
2. **La ruta de emisión del token** accesible desde esa página (sección 1). Debe estar protegida por la sesión del sistema, no ser pública.
3. Opcional: Content Security Policy que permita `script-src` y `connect-src` hacia el asistente.

El widget guarda el token solo en memoria (nunca en `localStorage`) y, en `sessionStorage`, únicamente el id de la conversación actual para retomarla al recargar la página (se descarta al cerrar la pestaña). Renueva el token antes de que venza y, ante `token_expirado`, renueva y reintenta el mensaje una vez.

### 7.3 Atributos, estilos y eventos

| Atributo | Contenido |
|---|---|
| `token-url` | Obligatorio. Ruta de emisión del token. |
| `servidor` | URL base del asistente. |
| `titulo` | Título de la barra superior. Por defecto, "Asistente · {nombre del sistema}". |
| `placeholder` | Texto del campo de entrada. |
| `idioma` | Idioma de la voz (BCP 47). Por defecto `es-UY`; si el sistema no tiene voces de ese idioma, el widget usa `es-ES` o la primera en español disponible. |
| `voz` | Nombre exacto de una voz del navegador, para forzarla. |
| `voz-motor` | `auto` (por defecto), `navegador` o `servidor`: qué usa el dictado (ver [7.4](#74-voz-opcional)). |
| `palabra-activacion` | Palabra que despierta el modo manos libres (por defecto `asistente`). |
| `manos-libres-inactividad` | Minutos sin interacción tras los que el modo manos libres se apaga solo (por defecto 5; `0` = no se apaga). |

Colores, tipografía y anchos se personalizan con variables CSS definidas en el elemento o en un ancestro: `--asistente-color`, `--asistente-color-texto`, `--asistente-fondo`, `--asistente-texto`, `--asistente-borde`, `--asistente-fuente`, `--asistente-radio`, `--asistente-ancho-lateral` (reservada para cuando se active el historial) y `--asistente-ancho-columna`.

El widget emite eventos DOM (`CustomEvent`, que burbujean y atraviesan el Shadow DOM):

| Evento | `detail` | Cuándo |
|---|---|---|
| `asistente:accion` | `{ tipo, url, etiqueta }` | Una tool devolvió una sugerencia `ui` (ver sección 3). Si el sistema llama a `preventDefault()`, el widget no muestra su botón y el sistema decide qué hacer (navegar, abrir un mapa, filtrar una tabla). Por defecto, solo se muestra un botón para URLs relativas del mismo origen. |
| `asistente:estado` | `{ habilitado }` | Al decidir si el asistente está disponible. Si no lo está (`403` del token o sistema deshabilitado), el widget muestra un aviso en lugar del chat. |

### 7.4 Voz (opcional)

#### Voz del navegador (camino por defecto)

El widget usa la **Web Speech API** del navegador, sin configurar nada en el servidor:

- **Dictado:** `SpeechRecognition`. El botón de micrófono aparece si el navegador la ofrece (Chrome, Edge, Safari). Muestra el texto parcial mientras se habla y deja el final **en el campo de entrada, sin enviarlo**. Lo procesa el servicio de voz del propio navegador: **en Chrome, el audio se envía a Google**. Un sistema cuyos usuarios no deban enviar audio a un tercero debe fijar `voz-motor="servidor"` (ver abajo).
- **Respuesta hablada:** `speechSynthesis`, con las voces instaladas en el dispositivo del usuario (cada usuario oye lo que su sistema tenga). Cada respuesta del asistente trae un botón para escucharla, y la barra superior tiene un interruptor para leerlas automáticamente (se recuerda en la pestaña). La lectura empieza por oraciones completas, antes de que termine la respuesta; se quitan el Markdown, los enlaces y el código. Dictar, enviar un mensaje o apagar el interruptor la detienen.
- **Voz elegida:** la de `voz` si existe; si no, la del `idioma` pedido; si no, `es-ES`; si no, cualquiera en español. Sin ninguna voz en español, el navegador usa la suya por defecto.
- **Sin garantías de servicio:** son APIs del navegador; su calidad, disponibilidad y versión no las controla el asistente.

#### Modo «manos libres»

Un segundo modo del widget, además del chat de siempre (que no cambia). Un botón **Manos libres** en la barra superior lo enciende; la primera vez lo inicia el usuario con ese clic (el navegador exige un gesto del usuario para abrir el micrófono) y después el widget queda escuchando solo la **palabra de activación**.

- **Disponibilidad:** el botón aparece solo si el navegador tiene reconocimiento y síntesis de voz, la página es un contexto seguro (HTTPS o `localhost`) y `voz-motor` no es `servidor`. Con `voz-motor="servidor"` no hay manos libres: la palabra de activación necesita el reconocimiento continuo del navegador, que es justo lo que ese valor evita.
- **Estados:** apagado → **armado** (solo escucha la palabra de activación) → **capturando** (lo que se dice va al campo de texto) → **confirmando** (el texto queda en el campo; se envía con el botón o diciendo «enviar», se descarta con el botón o diciendo «cancelar») → **respondiendo** (el asistente responde y la respuesta se lee en voz alta, aunque el interruptor de lectura automática esté apagado) → armado de nuevo.
- **Nada se envía solo al terminar de hablar.** Tras un silencio de unos 2 s, lo dictado pasa a confirmación; si se sigue hablando, se añade al texto. «Enviar», «cancelar» y «apagar manos libres» solo valen como frase completa y tras una pausa (no dentro de una frase como «quiero enviar un informe»). La exigencia de confirmación es la constante `MANOS_LIBRES_CONFIRMAR` del widget: en `false`, el mismo cierre de frase envía directamente.
- **Palabra de activación:** `asistente` por defecto (atributo `palabra-activacion`; puede ser de varias palabras). Debe estar al comienzo de la frase (admite hasta dos palabras antes, como «oye asistente»); se ignoran mayúsculas, acentos y puntuación. Lo que se dice a continuación en la misma frase ya cuenta como dictado.
- **Interrumpir la lectura:** la lectura se corta al tocar el botón de escuchar del mensaje o al decir la palabra de activación mientras el asistente habla. No hay detector de energía ni cancelación de eco: **por ahora hay que usar auriculares**, porque con parlantes el micrófono oiría al asistente.
- **Privacidad:** mientras está encendido, el micrófono está abierto y, en Chrome, **todo el audio se envía de forma continua al servicio de voz del navegador (Google)**, no solo lo que sigue a la palabra de activación. Por eso el widget muestra un indicador siempre visible (punto rojo, estado, aviso de privacidad) con el botón **Apagar manos libres**, y se apaga también con la tecla Esc, diciendo «apagar manos libres» o solos tras `manos-libres-inactividad` minutos sin interacción (se avisa en pantalla). Un sistema cuyos usuarios no deban enviar audio a un tercero fija `voz-motor="servidor"` y el modo no aparece.
- **Continuidad:** Chrome corta el reconocimiento continuo tras un rato de silencio o unos 60 s; el widget lo reinicia solo mientras el modo siga encendido, con espera creciente si hay errores y se apaga con un aviso tras cinco fallos seguidos o si se deniega el micrófono. Mientras está encendido, el botón de dictado manual queda deshabilitado (dos reconocedores a la vez competirían por el micrófono).

#### STT del servidor (alternativa)

Si el servicio tiene un STT configurado (`/v1/estado` → `voz.dictado: true`), el widget puede dictar con él. Es lo que se usa si el navegador no tiene `SpeechRecognition`, o siempre con `voz-motor="servidor"` (el audio no va a Google, sino al proveedor configurado en el asistente). Con `voz-motor="navegador"` solo se usa el del navegador. Sin ninguna de las dos opciones, el botón no aparece y el widget se comporta como siempre.

- El usuario graba (`MediaRecorder`, con permiso del navegador); al detener, el widget envía el audio a `POST /v1/voz/transcribir` (mismo token y verificación de origen) y **pone el texto en el campo de entrada, sin enviarlo**: el usuario lo revisa y lo envía. La grabación se corta sola al llegar a `voz.max_audio_s`.
- El navegador requiere un contexto seguro (HTTPS o `localhost`) para usar el micrófono; el sistema anfitrión debe servir la página así y no bloquear `microphone` en su `Permissions-Policy` (si la página va en un `<iframe>`, necesita `allow="microphone"`).
- El audio no se guarda en el asistente; solo se registra su duración. Hay topes de tamaño y duración y un límite de dictados por minuto y usuario.

`POST /v1/voz/transcribir`: cuerpo = audio crudo; `Content-Type` `audio/webm`, `audio/ogg`, `audio/mp4`, `audio/mpeg` o `audio/wav`; cabecera `X-Audio-Duracion-S`; query opcional `?idioma=`. Responde `{ "texto" }`. Errores: `503 voz_no_disponible`, `415 audio_tipo_no_permitido`, `413 audio_demasiado_grande` / `audio_demasiado_largo`, `422 audio_invalido`, `429 limite_excedido`, `502 voz_error`.

### 7.5 Seguridad

- El contenido del modelo (Markdown) se construye con nodos DOM, nunca con `innerHTML`; los enlaces del modelo solo admiten `http`, `https` y `mailto`.
- El navegador solo ve el JWT de vida corta, nunca la clave de firma ni el token de manifiesto.
