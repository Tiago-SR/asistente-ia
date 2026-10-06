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
| `scope` | sí | `"asistente:lectura"` (el de escritura, `"asistente:escritura"`, solo existe para confirmar una acción: [sección 8](#8-acciones-con-confirmación-opcional)) |
| `nombre` | no | nombre a mostrar |
| `tenants` | no | ids de organización del usuario, solo para métricas y cuotas. **Nunca se usa para autorizar** |
| `locale` | no | p. ej. `es-UY` (si falta, el `locale_defecto` del registro, ver 6.3) |

Ejemplo del payload de un token (RS256, 10 minutos de vida):

```json
{ "iss": "sgagro", "aud": "asistente", "sub": "u-4821", "scope": "asistente:lectura",
  "iat": 1790000000, "exp": 1790000600, "jti": "3f6c2a9e-8d1b-4c77-9a52-0b7e5d1c4f10",
  "nombre": "Ana Pérez", "tenants": ["org-17"], "locale": "es-UY" }
```

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

- `nombre`: `^[a-z][a-z0-9_]{0,63}$`, único. `consultas_recientes`, `recordar` y `olvidar` están **reservados**: son tools locales del asistente ([6.7](#67-lo-mismo-que-ayer-consultas_recientes) y [6.8](#68-memoria-por-usuario-recordar-y-olvidar)) y una tool del sistema con alguno de esos nombres se descarta.
- `descripcion`: ≤ 1 000 caracteres. `parametros`: JSON Schema válido, tipo `object`.
- `efecto` ∈ {`lectura`, `escritura`}. Al modelo solo se exponen las de `lectura`, salvo las escrituras que declaran `confirmacion` y que el operador del asistente habilitó explícitamente ([sección 8](#8-acciones-con-confirmación-opcional)); ni siquiera esas se ejecutan sin la confirmación del usuario.
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
| Error de negocio | `200`, `ok: false`, `error` ∈ {`no_encontrado`, `sin_acceso`, `parametros_invalidos`, `no_disponible`, `conflicto`}; `conflicto` solo en escrituras (sección 8) | lo pasa al modelo, que no debe rellenar con suposiciones |
| Token inválido/vencido | `401` | corta el turno y emite `token_expirado` al widget, que renueva y reintenta |
| Scope insuficiente | `403` | `sin_acceso` |
| Error del sistema | `5xx` / timeout / JSON inválido | `error_sistema` / `timeout` / `respuesta_invalida` al modelo |

Requisitos para el sistema:

- **Validar el token con su propia clave** y rechazar (`403`) el `token_manifiesto` en este endpoint.
- **Rechazar toda escritura** con scope `asistente:lectura`. Esta es la capa de solo lectura que vale: el asistente no puede verificar qué hace realmente una tool remota. Una escritura solo se acepta con el token de escritura de la sección 8.
- Tratar los ids y parámetros que llegan como **no confiables**: validar y aplicar permisos como con cualquier input.

Recomendaciones:

- Datos agregados y compactos, con unidades en el nombre del campo (`superficie_ha`, `rinde_kg_ha`) y fechas ISO 8601.
- No devolver geometrías ni listas de miles de filas: resumir del lado del sistema.
- El asistente trunca respuestas por encima de un límite configurable (p. ej. 50 KB) y se lo indica al modelo.
- Cada cifra con su unidad, su entidad y su período en el mismo objeto. Hace falta para el modo voz ([7.4](#74-voz-opcional)): el asistente dice un resumen de una o dos cifras y deja el detalle en pantalla, y ese resumen solo puede usar cifras que salieron de la tool.
- Más criterios y ejemplos buenos y malos en la [guía de diseño de tools](GUIA_TOOLS.md).

**Ejemplo: una tool pensada para texto y voz.** `resumen_por_cultivo` devuelve el agregado ya calculado (el modelo no suma listas), con unidades y entidades en los nombres, y una sugerencia `ui` para ver el detalle:

```json
{
  "ok": true,
  "datos": {
    "periodo": "zafra 2025/26",
    "superficie_total_ha": 870.5,
    "por_cultivo": [
      { "cultivo": "soja", "superficie_ha": 660.5, "establecimientos": 2 },
      { "cultivo": "maíz", "superficie_ha": 210.0, "establecimientos": 1 }
    ]
  },
  "fuente": "resumen_por_cultivo",
  "ui": [ { "tipo": "navegar", "url": "/cultivos/resumen", "etiqueta": "Ver el detalle por cultivo" } ]
}
```

Con eso, en el chat el asistente escribe la tabla completa y, en el modo voz, solo dice algo como «Tenés unas 660 hectáreas de soja y 210 de maíz; el desglose está en pantalla». El sistema no hace nada especial para el canal de voz.

## 4. Salud (opcional)

`GET {base_url}/asistente/salud` → `{"ok": true}`. Lo usan el verificador y el monitoreo.

## 5. Versionado

- El manifiesto declara `contrato`. El asistente acepta las versiones que soporta y rechaza las demás con un error claro en el log.
- Cambios compatibles (campos opcionales nuevos) no suben versión; los incompatibles sí. La sección 8 (acciones con confirmación) es de este tipo: un sistema que solo lee no cambia nada.

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
- **`locale_defecto` (opcional):** idioma (`es-UY`) de los usuarios cuyo token no trae el claim `locale`; si el token lo trae, manda el del token. Lo usan el prompt («idioma preferido del usuario») y el dictado del servidor.
- **`zona_horaria` (opcional):** zona IANA (`America/Montevideo`) de los usuarios cuyo navegador no la informa. El widget envía la del navegador en cada mensaje y esa manda; sin ninguna de las dos se usa UTC. Define qué día es «hoy» para el asistente (la fecha de la sesión) y se guarda con cada consulta. Una zona desconocida en el registro deshabilita ese sistema; una inválida enviada por el navegador se ignora.
- **`consultas_recientes` (opcional, `true` por defecto):** `false` desactiva para este sistema la tool local de «lo mismo que ayer» ([6.7](#67-lo-mismo-que-ayer-consultas_recientes)).
- **`memoria_habilitada` (opcional, `false` por defecto):** `true` enciende para este sistema la memoria por usuario ([6.8](#68-memoria-por-usuario-recordar-y-olvidar)): tools locales `recordar` y `olvidar`, sección «lo que el usuario pidió recordar» en el prompt, endpoints `/v1/memoria` y panel en el widget. Apagada, nada de eso existe.
- **Variables faltantes:** si falta alguna variable referenciada, **ese sistema** queda deshabilitado (el resto sigue) y el motivo queda en el log y en `GET /admin/sistemas`.
- **Verificar la integración:** ver [6.5](#65-verificar-la-integración).

**Ejemplo de entrada completa en `config/sistemas.yaml`** (todo lo que va después de `conector` es opcional):

```yaml
sistemas:
  - id: sgagro                      # = claim iss
    nombre: "SGAgro"
    base_url: https://sgagro.example.com
    origenes_permitidos: [https://sgagro.example.com]
    auth: { algoritmo: RS256, clave_publica_env: SGAGRO_PUBKEY, audiencia: asistente }
    conector:
      tipo: http
      ruta_manifiesto: /asistente/tools
      ruta_ejecucion: /asistente/tools/{nombre}
      token_manifiesto_env: SGAGRO_MANIFEST_TOKEN
    prompt_dominio: prompts/dominio/sgagro.md   # vocabulario y reglas del negocio
    locale_defecto: es-UY                       # idioma si el token no trae `locale`
    acciones_habilitadas: [agregar_nota, modificar_nota]   # escrituras que el modelo puede proponer (vacío = solo lectura)
    zona_horaria: America/Montevideo            # «hoy» para usuarios cuyo navegador no informa la suya
    consultas_recientes: true                   # tool local «lo mismo que ayer» (false = apagada)
    memoria_habilitada: false                   # memoria por usuario: preferencias, alias y consultas guardadas (true = encendida)
    limites:
      mensajes_por_usuario_min: 10
      mensajes_por_usuario_dia: 200
      tokens_por_mes: 5000000
    retencion_dias: 30
```

**Costo por sistema.** `GET /admin/uso?mes=2026-10` (cabecera de administración; no se expone en el proxy) devuelve el consumo y el costo en USD por modelo, con una cota `valle` y otra `pico` porque la tarifa depende del horario del proveedor (tarifas en `config/precios.yaml`):

```json
{ "mes": "2026-10", "sistemas": [ { "id": "sgagro", "nombre": "SGAgro",
  "modelos": [ { "modelo": "deepseek-flash", "llamadas": 412, "tokens_in": 1650000, "tokens_in_cache": 1440000,
                 "tokens_out": 98000, "costo_usd": { "valle": 0.12, "pico": 0.24 } } ],
  "voz": [ { "proveedor": "elevenlabs", "modelo": "eleven_flash_v2_5", "llamadas": 530, "caracteres": 41200,
             "costo_usd": 1.648 } ],
  "costo_usd": { "valle": 1.768, "pico": 1.888 }, "sin_tarifa": [] } ] }
```

`voz` es la voz del servidor (TTS): cada síntesis correcta suma una llamada y sus caracteres a `uso_voz` (sistema, mes, proveedor y modelo; solo números, nunca el texto; no se purga). Se factura por carácter y no por horario, así que `costo_usd` es un solo número (precio de lista de `config/precios.yaml`, clave `proveedor:modelo`; un plan de créditos mensuales puede salir más barato) que se suma a las dos cotas del total del sistema. Un motor sin tarifa figura en `sin_tarifa` y no entra en el total. La voz del navegador no cuesta y no aparece.

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

**Acciones con confirmación (sección 8).** Solo si el manifiesto trae alguna tool con `confirmacion`; un sistema de solo lectura las omite y sigue siendo conforme. Comprueban `ttl_s` (10–300), la propuesta (schema, **sin efectos**: los datos de las lecturas sin parámetros no cambian), la emisión del token de escritura (no se emite para una huella desconocida ni para la de otro usuario; claims `act`, `ph`, `cid`; vida ≤ 60 s), el rechazo (`403`) de la propuesta con token de escritura, de una lectura con token de escritura y de un token usado en otra tool, el token vencido (`401`, con `--secreto-firma-env`), parámetros distintos a los propuestos (`403`), un token de un solo uso (`403`) y la `Idempotency-Key` repetida (mismo resultado, sin reejecutar). Cada defecto del mock de la sección 8 tiene su comprobación. **Ejecutan una escritura real** con los parámetros que indiques en `--accion`, así que usar solo un entorno de pruebas; sin `--accion` se omiten. No verifican el `conflicto` de una modificación (no se puede forzar desde fuera).

| Opción | Habilita |
|---|---|
| `--secreto-firma-env VAR` | token vencido (`401`), de otra audiencia (`401`) y con scope ajeno (`403`). Sin ella se omiten. Con claves `RS256`/`EdDSA`, `VAR` contiene la privada PEM y se indica `--algoritmo-firma` |
| `--token-url-otro URL` o `--id-ajeno ID` | probar un id de otro usuario. Requiere una tool de lectura con un id obligatorio (`--tool-id` si hay varias) |
| `--cabecera-token-env VAR` | enviar a la ruta de token una cabecera `Nombre: valor` (cookie de sesión, API key) leída del entorno |
| `--accion NOMBRE='{json}'` (repetible) | parámetros válidos de una tool con `confirmacion`; habilita las comprobaciones de la sección 8. Con una segunda acción se prueba también el token usado en otra tool; `--token-url-otro` añade la huella de otro usuario |
| `--max-kb`, `--max-ms` | topes de tamaño (50 KB) y de tiempo (por defecto, el `timeout_s` de la tool) |

Imprime un reporte por secciones con un resumen y termina con código `0` si todo pasa, `1` si algo falla. Sirve igual en CI.

### 6.6 Evals propios del sistema

Pasar el verificador prueba el **contrato**, no la **calidad** de las respuestas. Cada sistema debería tener su propio set de preguntas con respuestas verificables y correrlo antes de cambiar de modelo o de tocar el prompt de dominio: un modelo puede pasar las pruebas de conversación y aun así inventar cifras o romper el formato de las tools. Formato (`evals/preguntas.yaml` es el ejemplo; `preguntas_acciones.yaml` cubre propuestas de acción y `preguntas_voz.yaml` el resumen hablado):

```yaml
sistema: sgagro
token_url: https://sgagro-pruebas.example.com/asistente/token
base_numeros: [540.5, 210, 870.5, 660.5]     # cifras legítimas: toda otra cifra en la respuesta cuenta como inventada
preguntas:
  - {id: q09, categoria: agregado, usuario: ana, turnos: ["¿Cuántas hectáreas de soja tengo?"],
     tools_requeridas: [resumen_por_cultivo], numeros: [660.5]}
  - {id: q20, categoria: aislamiento, usuario: beto, turnos: ["¿Cuántas hectáreas tiene El Matorral?"],
     sin_numeros: [540.5]}                    # El Matorral es de ana: beto no debe verlo
```

`docker compose run --rm asistente python evals/correr.py --preguntas evals/preguntas.yaml` mide aciertos, cifras no respaldadas, latencia, tokens y costo por pregunta (usa el LLM real: cuesta tokens).

### 6.7 «Lo mismo que ayer» (`consultas_recientes`)

El asistente ofrece al modelo una tool **propia** (no del sistema) que lista las consultas de lectura que el usuario ya hizo: la tool y sus parámetros, de la más reciente a la más antigua, agrupadas cuando se repiten. **Nunca devuelve resultados**: para repetir una consulta («lo mismo que ayer», «la del lunes»), el modelo vuelve a llamar a la tool original, así que las cifras son siempre las de ahora y se mantiene la regla de que toda cifra sale de una tool consultada en la conversación.

- **De dónde sale:** de la auditoría de tools (`llamadas_tool`), que ya existía. No guarda nada nuevo salvo la zona horaria del usuario en cada llamada. Solo se listan las consultas exitosas de tools de lectura que el manifiesto ofrece **hoy** (una tool retirada, una escritura o una propuesta no aparecen) y solo las de ese `(sistema, usuario)`.
- **Ventana:** la `retencion_dias` del sistema (30 por defecto). Pasado ese plazo la auditoría se borra: la purga de retención ahora también alcanza a `llamadas_tool`, que antes no se purgaba.
- **Fechas y zona:** cada consulta lleva su `fecha` en la zona **actual** del usuario. Si cuando la hizo estaba en otra zona y eso cambia el día (p. ej. viajó), se agrega `zona_original` y `fecha_en_zona_original`, y el modelo pregunta ante la duda.
- **Lo que el sistema anfitrión debe saber:** nada cambia en el contrato con el sistema, salvo que el nombre `consultas_recientes` queda reservado. Si el sistema no quiere que el asistente recuerde sus consultas, lo apaga con `consultas_recientes: false`.

### 6.8 Memoria por usuario (`recordar` y `olvidar`)

Con `memoria_habilitada: true`, el asistente recuerda **por usuario y por sistema** (clave `(sistema_id, usuario_ref)`, como todo lo demás) tres cosas que el usuario le pide **de forma explícita**, y las usa en conversaciones futuras:

| Tipo | Ejemplo | Qué se guarda |
|---|---|---|
| **Preferencia** | «dame las hectáreas sin decimales», «hablame más corto», «mi campo principal es El Matorral» | clave de un conjunto cerrado: `decimales` (0 a 3), `brevedad` (`corta`, `normal`, `detallada`), `entidad_principal` (`{entidad, id}`) |
| **Alias** | «cuando digo “la sojera” me refiero a San Pedro» | la palabra, la entidad y el **id** (más una etiqueta con el nombre, solo para mostrar) |
| **Consulta guardada** | «guardá esta consulta como “la de siempre”» | el nombre y `{tool, parametros}` tal como se ejecutó (fechas fijas: no hay fechas relativas) |

- **Guardar y olvidar siempre con botón.** `recordar` y `olvidar` son tools locales que solo **proponen**: reutilizan el ciclo de la [sección 8](#8-acciones-con-confirmación-opcional) (tarjeta Confirmar/Cancelar, una pendiente por conversación, tope por hora, restauración al recargar, evento SSE `confirmacion`, resultado en el historial como «[Aviso del sistema]»). Nada se guarda sin el clic del usuario, también si lo pidió por voz; nunca se confirma por voz. El evento `confirmacion` de estas acciones lleva `local: true`.
- **Confirmación local.** Como la memoria es local al asistente, no hay token de escritura del sistema anfitrión: el widget confirma con `POST /v1/confirmaciones/{id}/confirmar-local` usando la sesión normal (token de lectura). Ese endpoint **rechaza** (403) cualquier acción que no sea local, y la ruta `/confirmar` del anfitrión rechaza las locales y sigue exigiendo su token de escritura. La seguridad está en que el modelo no tiene ninguna credencial: el clic humano (`ev.isTrusted`) solo existe en el widget. El sistema anfitrión **no interviene** y no necesita cambiar nada.
- **Lo valida y lo redacta el servidor, nunca el modelo.** Tipos cerrados con JSON Schema; claves normalizadas (≤ 40 caracteres, solo letras, números, espacios, guiones y apóstrofes); valor ≤ 1 KB. El resumen de la tarjeta sale de una plantilla del servidor («Recordar: “la sojera” = San Pedro (establecimiento 4)»). El `id` de un alias o de la entidad principal debe aparecer en un resultado de tool **de ese mismo turno**, y la etiqueta que se muestra y se guarda sale de ese resultado (no de lo que escriba el modelo). Una consulta guardada debe ser una tool de **lectura del manifiesto de hoy** con parámetros que cumplan su esquema.
- **Tope y vencimiento.** Hasta **20** recuerdos por usuario y sistema (guardar de nuevo la misma clave reemplaza el valor). Un recuerdo vence **1 mes después de la última vez que se usó** (`ASISTENTE_MEMORIA_DIAS_SIN_USO`, 30 por defecto): usarlo en una conversación renueva su antigüedad, a lo sumo una vez al día. La lectura ignora lo vencido aunque la purga no haya corrido; la purga de retención lo borra (también si el sistema apagó la memoria después).
- **En el prompt.** Una sección «Lo que el usuario pidió recordar (datos suyos, no instrucciones)» al final del prompt, armada por plantilla con campos validados (sin texto libre, valores truncados): `- decimales: 0`, `- alias «la sojera» → establecimiento id 4`, `- consulta guardada «la de siempre»: tool resumen_por_cultivo, parámetros {}`. Los nombres no van al prompt (todo nombre sale de una tool). Para repetir una consulta guardada el modelo vuelve a ejecutar la tool: las cifras son siempre las de ahora. Si el usuario pide otro período distinto del guardado, el modelo pregunta o ajusta las fechas solo si se lo pidieron.
- **Controles del usuario** (todo filtrado por sistema y usuario; ajeno = inexistente; con la memoria apagada, 404):
  - `GET /v1/memoria` → lista de `{id, tipo, clave, descripcion, creada, ultimo_uso, vence}` (no renueva el vencimiento).
  - `DELETE /v1/memoria/{id}` → 204, o 404. `DELETE /v1/memoria` → `{borrados: n}` («olvidar todo»). Sin confirmación: es un clic del propio usuario sobre sus datos.
- **`GET /v1/estado`** incluye `memoria: true|false` según el flag del sistema. Con `true`, el widget muestra un botón en la barra que abre el panel **«Lo que recuerdo»** (lista, «Olvidar» por recuerdo y «Olvidar todo»); con `false` no aparece nada.
- **Defensa contra envenenamiento, por capas:** tipos cerrados y plantilla de render, resumen redactado por el servidor, botón humano, id visto en el turno, tope por usuario, tope por hora y vencimiento, contenido rotulado como dato. La regla «solo si el usuario lo pidió» depende del modelo: la cubren los evals (`evals/preguntas_memoria_fase1.yaml`), no el código.
- **Lo que el sistema anfitrión debe saber:** nada cambia en el contrato con el sistema, salvo que `recordar` y `olvidar` quedan reservados. El verificador ([6.5](#65-verificar-la-integración)) avisa si una tool usa esos nombres.

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

En cada mensaje el widget envía la zona horaria del navegador (`zona_horaria` en `POST /v1/chat`, p. ej. `America/Montevideo`) para que «hoy» y «ayer» sean los del usuario; no la guarda.

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
| `voz-respuesta` | `auto` (por defecto), `servidor` o `navegador`: con qué voz habla el asistente. `auto` usa la voz del servidor (`POST /v1/voz/sintetizar`) si el sistema la tiene (`voz.respuesta` en `/v1/estado`) y, si falla o no existe, la del navegador; `navegador` no envía el texto de las respuestas a ningún tercero; `servidor` no cae al navegador (ver [7.4](#74-voz-opcional)). |
| `palabra-activacion` | Palabra que despierta el modo voz (por defecto `asistente`). |
| `manos-libres-inactividad` | Minutos sin interacción tras los que el modo voz se apaga solo (por defecto 5; `0` = no se apaga; el atributo conserva su nombre anterior por compatibilidad). |
| `ajustes` | `auto` (por defecto) o `no`: engranaje con el panel de ajustes del usuario (voz del asistente —navegador o servidor, si hay las dos—, volumen, lectura automática, acuse, «probar voz» y «restablecer»). Se guardan en el navegador (`localStorage`, por servidor; nunca el token ni texto del chat) y lo que el usuario elige manda sobre `voz-respuesta` y `acuse`; con `no` no hay panel y mandan los atributos. |
| `acuse` | `auto` (por defecto) o `no`: en el modo voz, si pasan unos 0,9 s desde «enviar» sin nada que decir, el widget dice una frase corta («Un momento, lo consulto») para que no haya silencio; `no` la quita (ver [7.4](#74-voz-opcional)). |
| `orbe-volumen` | `auto` (por defecto) o `no`: si el orbe del modo voz sigue el volumen del micrófono (ver [7.4](#74-voz-opcional)); `no` evita abrir el segundo flujo de audio que lo mide. |
| `tema` | `claro`, `oscuro` o `auto` (por defecto). `auto` sigue `prefers-color-scheme` del navegador y reacciona si el usuario cambia el tema del sistema con la página abierta. Se puede cambiar en caliente (no reinicia la conversación). Un valor no reconocido equivale a `auto`. |

Colores, tipografía y anchos se personalizan con variables CSS definidas en el elemento o en un ancestro: `--asistente-color`, `--asistente-color-texto`, `--asistente-fondo`, `--asistente-texto`, `--asistente-borde`, `--asistente-fuente`, `--asistente-radio`, `--asistente-ancho-lateral` (reservada para cuando se active el historial) y `--asistente-ancho-columna`.

**Tema y variables.** El widget trae dos paletas (clara y oscura; texto normal con contraste ≥ 4,5:1, verificado por tests) que cubren la tarjeta de confirmación, el modo manos libres, los errores, el código y las tablas, y declara `color-scheme` para que los controles y barras de desplazamiento nativos sigan el tema. Las variables `--asistente-*` que defina el sistema **mandan siempre** sobre la paleta del tema activo. Quien personalice colores debe fijar los pares completos (`--asistente-fondo` con `--asistente-texto`, y `--asistente-color` con `--asistente-color-texto`); si solo los diseñó para un tema, debe fijar también `tema="claro"` u `"oscuro"`, porque con `auto` el otro tema aportaría los colores que no definió. El widget no incluye un botón para alternar el tema: lo decide el sistema (con su propio interruptor que cambie el atributo `tema`) o el sistema operativo.

El widget emite eventos DOM (`CustomEvent`, que burbujean y atraviesan el Shadow DOM):

| Evento | `detail` | Cuándo |
|---|---|---|
| `asistente:accion` | `{ tipo, url, etiqueta }` | Una tool devolvió una sugerencia `ui` (ver sección 3). Si el sistema llama a `preventDefault()`, el widget no muestra su botón y el sistema decide qué hacer (navegar, abrir un mapa, filtrar una tabla). Por defecto, solo se muestra un botón para URLs relativas del mismo origen. |
| `asistente:estado` | `{ habilitado }` | Al decidir si el asistente está disponible. Si no lo está (`403` del token o sistema deshabilitado), el widget muestra un aviso en lugar del chat. |
| `asistente:metricas` | `{ canal, fuente, acuse_ms, primer_delta_ms, voz_ms, habla_ms, tts_ms, servidor }` | Al terminar cada turno por voz: cuánto tardó en llegar el resumen hablado y en empezar a sonar (ver [7.4](#74-voz-opcional)). Solo números: no lleva el mensaje ni la respuesta. |
| `asistente:confirmacion` | `{ id, tool, estado }` | Una acción propuesta por el asistente terminó (`ejecutada`, `cancelada`, `expirada`, `reemplazada` o `fallida`; [sección 8](#8-acciones-con-confirmación-opcional)). El sistema puede refrescar su pantalla tras una `ejecutada`. |

#### Ejemplo: integración completa

Una página con el tema atado al interruptor del propio sistema, colores de marca para ambos temas y los cuatro eventos del widget:

```html
<script src="https://asistente.example.com/widget.js" defer></script>
<asistente-chat id="asistente" style="display:block;height:100vh"
    servidor="https://asistente.example.com" token-url="/asistente/token"
    titulo="Asistente SGAgro" idioma="es-UY" tema="auto"></asistente-chat>

<style>
  /* Colores de marca: siempre los pares completos (color con color-texto). El selector sigue al widget:
     con tema="auto" manda el sistema operativo; con un tema fijado, el atributo. */
  asistente-chat { --asistente-color: #2f6f3e; --asistente-color-texto: #fff; }
  asistente-chat[tema="oscuro"] { --asistente-color: #6fcf88; --asistente-color-texto: #0d1a11; }
  @media (prefers-color-scheme: dark) {
    asistente-chat:not([tema="claro"]) { --asistente-color: #6fcf88; --asistente-color-texto: #0d1a11; }
  }
</style>

<script>
  const asistente = document.getElementById("asistente");

  // El interruptor propio del sistema manda sobre el sistema operativo; el widget se repinta sin recargar ni perder la conversación.
  document.getElementById("modo-oscuro").addEventListener("change", (e) =>
    asistente.setAttribute("tema", e.target.checked ? "oscuro" : "claro"));

  // Los oyentes van en `document` (los eventos burbujean y atraviesan el Shadow DOM) para no perder el primero.
  document.addEventListener("asistente:estado", (e) => { menuAsistente.hidden = !e.detail.habilitado; });

  // Tras una acción ejecutada, refrescar la pantalla para que el usuario vea el cambio sin recargar.
  document.addEventListener("asistente:confirmacion", (e) => {
    if (e.detail.estado === "ejecutada" && e.detail.tool === "agregar_nota") recargarNotas();
  });

  // Una sugerencia `ui` de una tool: navegar con el router propio en vez de un enlace.
  document.addEventListener("asistente:accion", (e) => {
    if (e.detail.tipo === "navegar") { e.preventDefault(); router.push(e.detail.url); }
  });

  // Latencia del modo voz a tu sistema de métricas (solo números).
  document.addEventListener("asistente:metricas", (e) => enviarMetrica("asistente_voz", e.detail));
</script>
```

### 7.4 Voz (opcional)

#### Voz del navegador (camino por defecto)

El widget usa la **Web Speech API** del navegador, sin configurar nada en el servidor:

- **Dictado:** `SpeechRecognition`. El botón de micrófono aparece si el navegador la ofrece (Chrome, Edge, Safari). Muestra el texto parcial mientras se habla y deja el final **en el campo de entrada, sin enviarlo**. Lo procesa el servicio de voz del propio navegador: **en Chrome, el audio se envía a Google**. Un sistema cuyos usuarios no deban enviar audio a un tercero debe fijar `voz-motor="servidor"` (ver abajo).
- **Respuesta hablada:** `speechSynthesis`, con las voces instaladas en el dispositivo del usuario (cada usuario oye lo que su sistema tenga). Cada respuesta del asistente trae un botón para escucharla, y la barra superior tiene un interruptor para leerlas automáticamente (se recuerda en la pestaña). La lectura empieza por oraciones completas, antes de que termine la respuesta; se quitan el Markdown, los enlaces y el código. Dictar, enviar un mensaje o apagar el interruptor la detienen.
- **Voz del servidor (opcional, con respaldo):** si el servicio tiene un TTS configurado (`TTS_PROVEEDOR`; `GET /v1/estado` informa `voz.respuesta: true`), el widget le pide el audio de cada frase a `POST /v1/voz/sintetizar` y lo reproduce; las frases largas se parten en trozos de hasta 900 caracteres, se piden en paralelo y suenan en orden. Si el servidor falla (red, límite, error del proveedor) o el navegador bloquea la reproducción, esa frase se dice con la voz del navegador, y durante 30 s las siguientes también. El atributo `voz-respuesta` lo fija: `navegador` evita enviar el texto de las respuestas a un tercero; `servidor` no cae al navegador. Los acuses y otras frases fijas cortas se guardan en memoria para no pedirlas de nuevo. **Privacidad:** con la voz del servidor, el texto que se lee (el resumen en el modo voz, o la respuesta entera si se la lee) viaja al proveedor de voz. En el modo voz el orbe sigue el **volumen real** de esta voz (analizador de Web Audio sobre el audio recibido); con la del navegador sigue dando un pulso por palabra.
- **Voz elegida (del navegador):** la de `voz` si existe; si no, la del `idioma` pedido; si no, `es-ES`; si no, cualquiera en español. Sin ninguna voz en español, el navegador usa la suya por defecto.
- **Sin garantías de servicio:** son APIs del navegador; su calidad, disponibilidad y versión no las controla el asistente.

#### Modo voz (antes «manos libres»)

Un segundo modo del widget, además del chat de siempre. Un botón **Voz** en la barra superior lo enciende; la primera vez lo inicia el usuario con ese clic (el navegador exige un gesto del usuario para abrir el micrófono) y después el widget queda escuchando solo la **palabra de activación**.

- **Dos vistas, siempre alternables.** Al encender el modo se abre la **vista de voz**: una ventana propia, sin chat ni campo de texto, con un orbe que muestra el estado, lo que se va dictando, lo que el asistente dice y los botones. «**Ver el chat**» pasa a la vista de chat sin apagar nada (el micrófono sigue abierto y el panel del modo, compacto y con el aviso de privacidad, queda sobre la entrada); el botón **Voz** de la barra vuelve a la vista de voz. El chat es el registro completo: conserva lo que dijiste y la **respuesta completa** (con sus tablas y cifras), no solo lo que se dijo en voz alta.
- **Disponibilidad:** el botón aparece solo si el navegador tiene reconocimiento y síntesis de voz, la página es un contexto seguro (HTTPS o `localhost`) y `voz-motor` no es `servidor`. Con `voz-motor="servidor"` no hay modo voz: la palabra de activación necesita el reconocimiento continuo del navegador, que es justo lo que ese valor evita.
- **Estados:** apagado → **armado** (solo escucha la palabra de activación) → **capturando** (lo que se dice se acumula en el campo de texto, oculto en la vista de voz pero visible en la escena) → **confirmando** (el texto queda pendiente; se envía con el botón o diciendo «enviar», se descarta con el botón o diciendo «cancelar») → **respondiendo** (el asistente responde y dice su resumen en voz alta, aunque el interruptor de lectura automática esté apagado) → armado de nuevo. El orbe distingue dentro de «respondiendo» entre **procesando** (esperando la respuesta) y **hablando** (diciendo el resumen); es solo presentación.
- **Resumen hablado.** En el modo voz el widget pide el canal `voz` (`POST /v1/chat` con `{"canal": "voz"}`; el chat de texto envía `"texto"` o nada) y el asistente agrega a su respuesta final un bloque `<voz>…</voz>` con una a tres frases que cuentan *qué trae* la respuesta, sin leerla entera: a lo sumo una o dos cifras clave, con las mismas reglas que el resto (solo cifras de una tool; nada inventado), y la remisión a la pantalla para el detalle. El servicio lo separa del texto: lo emite como evento SSE `voz` (`{ "texto" }`), no lo incluye en los `delta` ni lo guarda en el historial, y registra en la versión del prompt que se usó la capa de voz. El widget dice solo ese resumen. Si el modelo no lo manda, el widget dice las dos primeras oraciones de la respuesta (con tope). La respuesta completa se escribe igual en el chat, con su botón para escucharla entera. El canal es opcional y no cambia el contrato con los sistemas anfitriones (las tools no se enteran del canal); un valor desconocido da `422`.
- **Nada se envía solo al terminar de hablar.** Tras un silencio de unos 2 s, lo dictado pasa a confirmación; si se sigue hablando, se añade al texto. «Enviar», «cancelar» y «salir del modo voz» (también «apagar manos libres», alias anterior) solo valen como frase completa y tras una pausa (no dentro de una frase como «quiero enviar un informe»). La exigencia de confirmación es la constante `MANOS_LIBRES_CONFIRMAR` del widget: en `false`, el mismo cierre de frase envía directamente.
- **Una acción propuesta nunca se confirma por voz y su tarjeta siempre queda a la vista:** si llega una propuesta mientras se está en la vista de voz, el widget pasa solo al chat (donde está la tarjeta con Confirmar/Cancelar), avisa en pantalla y dice la frase redactada por el sistema («Te pido confirmar en pantalla: …») en lugar del resumen del modelo. Ninguna orden de voz confirma.
- **Palabra de activación:** `asistente` por defecto (atributo `palabra-activacion`; puede ser de varias palabras). Debe estar al comienzo de la frase (admite hasta dos palabras antes, como «oye asistente»); se ignoran mayúsculas, acentos y puntuación. Lo que se dice a continuación en la misma frase ya cuenta como dictado.
- **Interrumpir la lectura:** la lectura se corta al tocar el botón de escuchar del mensaje o al decir la palabra de activación mientras el asistente habla. No hay detector de energía ni cancelación de eco: **por ahora hay que usar auriculares**, porque con parlantes el micrófono oiría al asistente.
- **Privacidad:** mientras está encendido, el micrófono está abierto (para el reconocimiento y, aparte y solo en local, para medir el volumen del orbe) y, en Chrome, **todo el audio se envía de forma continua al servicio de voz del navegador (Google)**, no solo lo que sigue a la palabra de activación. Por eso el widget muestra un indicador siempre visible, en las dos vistas (orbe, estado, aviso de privacidad), con el botón **Salir del modo voz**, y se apaga también con la tecla Esc, diciendo «salir del modo voz» o solo tras `manos-libres-inactividad` minutos sin interacción (se avisa en pantalla). Un sistema cuyos usuarios no deban enviar audio a un tercero fija `voz-motor="servidor"` y el modo no aparece.
- **Continuidad:** Chrome corta el reconocimiento continuo tras un rato de silencio o unos 60 s; el widget lo reinicia solo mientras el modo siga encendido, con espera creciente si hay errores y se apaga con un aviso tras cinco fallos seguidos o si se deniega el micrófono. Mientras está encendido, el botón de dictado manual queda deshabilitado (dos reconocedores a la vez competirían por el micrófono).
- **Accesibilidad y movimiento:** el orbe es decorativo (`aria-hidden`); el estado lo anuncia el texto `aria-live` del panel. Cada estado tiene su propio glifo y trazo, así que se distingue sin color ni movimiento. Con `prefers-reduced-motion: reduce` no hay ninguna animación. Los colores salen de las mismas variables (`--asistente-color` y el tema claro/oscuro); el ámbar de «confirmando» es del tema.

#### Orbe, volumen y tiempos del modo voz

- **El orbe reacciona al volumen real del micrófono** del usuario: el widget abre un **segundo flujo de audio local** (`getUserMedia` + un analizador de Web Audio) solo para medir el nivel. No se graba ni se envía a ningún lado; el audio que va al servicio de voz del navegador sigue siendo el del reconocimiento, sin cambios. Si el navegador no lo da (permiso, micrófono ocupado), el orbe sigue con sus animaciones y el reconocimiento no se entera. Se omite con `orbe-volumen="no"` y con `prefers-reduced-motion: reduce`. Mientras habla el asistente no se lee el micrófono (se oiría a él). Si en algún navegador abrir ese segundo flujo degrada el reconocimiento, se apaga con `orbe-volumen="no"` sin perder nada más.
- **Con la voz del asistente el orbe da un pulso por palabra** (evento `boundary` de `speechSynthesis`). Los navegadores no entregan la amplitud de la síntesis, así que sigue el ritmo del habla pero no su volumen; algunas voces pueden no emitir `boundary` (se ha visto con voces de red) y entonces el orbe usa solo su animación.
- **Acuse inmediato.** Con el modelo actual el resumen llega a los ~2 s (más si hay varias tools) y por voz ese silencio se siente roto. Pasados ~0,9 s desde «enviar» sin nada que decir, el widget dice una frase corta de texto fijo («Un momento, lo consulto», «Ya lo busco», «Dame un segundo»; rotan), sin costo de LLM y sin datos. Si el resumen llega antes, no se dice nada. Nunca se dice si el turno propuso una acción (ahí se dice la frase del sistema), si el usuario interrumpió, si el turno ya terminó o si se salió del modo voz. No se muestra en pantalla como respuesta. `acuse="no"` lo quita.
- **Tiempos.** Cada turno por voz mide cuánto tarda en oírse algo desde que el usuario envía: el servicio lo informa en `done.tiempos_ms` (`voz`, `primer_delta`, `total`, en milisegundos desde que empezó el turno, y lo deja en el log) y el widget emite `asistente:metricas` con lo que ve el cliente. Con un modelo rápido, el resumen llega con el primer texto: lo que domina la espera es la primera vuelta del modelo con sus tools, no la generación de la respuesta.

Ejemplo del flujo de un turno por voz en el flujo SSE de `POST /v1/chat` (con `{"canal": "voz"}`):

```
event: tool
data: {"herramientas":["Consultando resumen_por_cultivo"]}

event: voz
data: {"texto":"Tenés unas 660 hectáreas de soja; el desglose por cultivo está en pantalla."}

event: delta
data: {"texto":"Tenés **660,5 ha** de soja en 2 establecimientos y **210 ha** de maíz.\n\n| Cultivo | Superficie (ha) |\n..."}

event: done
data: {"conversacion_id":"…","uso":{"tokens_in":4085,"tokens_out":187,"tokens_in_cache":3584},"tiempos_ms":{"voz":2327,"primer_delta":2327,"total":2475}}
```

y el evento del widget que resulta, al empezar a sonar el resumen:

```json
{ "canal": "voz", "fuente": "resumen", "acuse_ms": 930, "primer_delta_ms": 2410, "voz_ms": 2410, "habla_ms": 2690, "tts_ms": 280,
  "servidor": { "voz": 2327, "primer_delta": 2327, "total": 2475 } }
```

`acuse_ms` es cuándo empezó a decirse el acuse (`null` si no hizo falta, porque el resumen llegó antes del plazo o `acuse="no"`). `fuente` es `"respaldo"` (y `voz_ms` es `null`) cuando el modelo no mandó su bloque `<voz>` y el widget dijo las dos primeras oraciones.

#### Ejemplo: el modo voz dentro de un `iframe`

El micrófono exige un contexto seguro y permiso delegado. Si el asistente va en un `iframe`, y el sistema usa `Permissions-Policy` y Content Security Policy:

```html
<iframe src="https://sgagro.example.com/asistente" allow="microphone" style="width:100%;height:100vh;border:0"></iframe>
```

```
Permissions-Policy: microphone=(self)
Content-Security-Policy: script-src 'self' https://asistente.example.com; connect-src 'self' https://asistente.example.com
```

Si los usuarios no deben enviar audio a un tercero (en Chrome el reconocimiento de voz va a Google), se fija `voz-motor="servidor"`: el modo voz no aparece y el dictado usa el STT del propio asistente, si el operador lo configuró.

#### STT del servidor (alternativa)

Si el servicio tiene un STT configurado (`/v1/estado` → `voz.dictado: true`), el widget puede dictar con él. Es lo que se usa si el navegador no tiene `SpeechRecognition`, o siempre con `voz-motor="servidor"` (el audio no va a Google, sino al proveedor configurado en el asistente). Con `voz-motor="navegador"` solo se usa el del navegador. Sin ninguna de las dos opciones, el botón no aparece y el widget se comporta como siempre.

- El usuario graba (`MediaRecorder`, con permiso del navegador); al detener, el widget envía el audio a `POST /v1/voz/transcribir` (mismo token y verificación de origen) y **pone el texto en el campo de entrada, sin enviarlo**: el usuario lo revisa y lo envía. La grabación se corta sola al llegar a `voz.max_audio_s`.
- El navegador requiere un contexto seguro (HTTPS o `localhost`) para usar el micrófono; el sistema anfitrión debe servir la página así y no bloquear `microphone` en su `Permissions-Policy` (si la página va en un `<iframe>`, necesita `allow="microphone"`).
- El audio no se guarda en el asistente; solo se registra su duración. Hay topes de tamaño y duración y un límite de dictados por minuto y usuario.

`POST /v1/voz/sintetizar`: cuerpo JSON `{ "texto", "idioma"? }` (`texto` hasta `ASISTENTE_VOZ_TTS_MAX_CHARS`, 1000 por defecto); responde el audio (`audio/mpeg`, `Cache-Control: no-store`) de esa pieza. Solo existe si el servicio tiene un TTS configurado (`TTS_PROVEEDOR`); `GET /v1/estado` informa `voz.respuesta`. El texto viaja al proveedor y no se guarda. Errores: `503 voz_no_disponible`, `422 texto_invalido`, `413 texto_demasiado_largo`, `429 limite_excedido` (contador propio, `ASISTENTE_VOZ_TTS_MAX_POR_MIN`, 60 por defecto), `502 voz_error`.

`POST /v1/voz/transcribir`: cuerpo = audio crudo; `Content-Type` `audio/webm`, `audio/ogg`, `audio/mp4`, `audio/mpeg` o `audio/wav`; cabecera `X-Audio-Duracion-S`; query opcional `?idioma=`. Responde `{ "texto" }`. Errores: `503 voz_no_disponible`, `415 audio_tipo_no_permitido`, `413 audio_demasiado_grande` / `audio_demasiado_largo`, `422 audio_invalido`, `429 limite_excedido`, `502 voz_error`.

### 7.5 Seguridad

- El contenido del modelo (Markdown) se construye con nodos DOM, nunca con `innerHTML`; los enlaces del modelo solo admiten `http`, `https` y `mailto`.
- El navegador solo ve el JWT de vida corta, nunca la clave de firma ni el token de manifiesto.

### 7.6 Lo que hoy no existe

Para no dar por hecho algo que no está: **contexto de la pantalla actual** (que el asistente sepa en qué ficha está el usuario), **manifiesto de tools por rol** (es global por sistema: el sistema rechaza lo que el usuario no puede hacer, pero el modelo puede ofrecerlo), **avisos proactivos** (webhooks o consultas programadas), **memoria de hechos de negocio** entre conversaciones (lo único que cruza conversaciones es repetir una consulta anterior con [`consultas_recientes`](#67-lo-mismo-que-ayer-consultas_recientes) y, si el sistema la habilita, lo que el usuario pida guardar: preferencias, alias y consultas guardadas ([6.8](#68-memoria-por-usuario-recordar-y-olvidar)); nunca cifras ni datos de negocio), **síntesis de voz de servidor** (las respuestas se leen con las voces del navegador) y **borrar o deshacer** desde el asistente. Son decisiones de producto: conviene acordar el caso de uso antes de pedirlas.

## 8. Acciones con confirmación (opcional)

Un sistema puede dejar que el asistente **proponga** escrituras acotadas (agregar o modificar un dato). Nunca se ejecutan sin que el usuario las confirme con un clic en el widget. Es opcional y está apagado por defecto: un sistema que no lo implemente sigue siendo de solo lectura. El borrado no se admite en esta versión (una tool marcada `destructiva: true` no se ofrece nunca).

**Quién manda.** La autoridad es el sistema: ejecuta una escritura solo con un token de escritura que él mismo emitió para esa acción. Un asistente comprometido no puede fabricarlo. El resumen que el usuario confirma lo redacta el sistema, no el modelo.

**Ejemplo punta a punta.** El usuario dice «anotá en El Matorral que hubo helada»: el modelo llama a `agregar_nota`; el asistente pide la propuesta al sistema (sin efectos), la guarda como pendiente y avisa al widget con este evento SSE:

```
event: confirmacion
data: {"id":"c41f…","tool":"agregar_nota","resumen":"Agregar una nota al establecimiento «El Matorral»","lineas":["Texto: Hubo helada"],"huella":"9f2c…","expira":"2026-10-05T21:32:10Z"}
```

El widget dibuja la tarjeta **Confirmar / Cancelar** con ese resumen; solo un clic real confirma (nunca la voz). Al pulsar Confirmar, pide el token de escritura al `token-url` del sistema (`/asistente/token?confirmacion=c41f…&huella=9f2c…`), el asistente ejecuta la tool con ese token y la tarjeta muestra el `mensaje` del resultado. El sistema anfitrión se entera con `asistente:confirmacion` (`{ id, tool, estado: "ejecutada" }`) y puede refrescar su pantalla (ejemplo en [7.3](#73-atributos-estilos-y-eventos)).

### 8.1 Declararla en el manifiesto

```json
{ "nombre": "agregar_nota",
  "descripcion": "Agrega una nota a un establecimiento. El usuario debe confirmarla en pantalla.",
  "parametros": { "type": "object", "properties": { "establecimiento_id": {"type": "string"}, "texto": {"type": "string", "maxLength": 500} },
                  "required": ["establecimiento_id", "texto"], "additionalProperties": false },
  "efecto": "escritura",
  "confirmacion": { "ttl_s": 120 } }
```

`confirmacion.ttl_s` (10–300, por defecto 120) es lo que dura una propuesta. Sin `confirmacion`, la tool de escritura no se ofrece al modelo. Además, el operador del asistente debe listarla en `acciones_habilitadas` del sistema en `config/sistemas.yaml` (vacío por defecto): la escritura se habilita por sistema y por tool, aparte de la lectura.

### 8.2 Propuesta (sin efectos)

`POST {base_url}/asistente/tools/{nombre}/propuesta`: mismo cuerpo que la ejecución y **token de lectura**. El sistema valida los parámetros y los permisos **sin escribir nada** y responde:

```json
{ "ok": true,
  "resumen": "Modificar la nota n1 del establecimiento «El Matorral»",
  "detalle": ["Antes: Revisar el alambrado", "Después: Revisar el alambrado y la tranquera"],
  "huella": "9f2c…(SHA-256, 64 hex)",
  "expira_s": 120 }
```

- `resumen` (≤ 300 caracteres) y `detalle` (≤ 10 líneas de ≤ 200) son lo que el usuario ve. Una modificación debe mostrar el valor anterior y el nuevo.
- `huella`: SHA-256 de la forma canónica de `{sub, tool, parametros, versión del registro que se modifica}`. **El sistema la recuerda hasta `expira_s`** y solo emite tokens de escritura para huellas que él produjo, para ese usuario y vigentes.
- Errores de negocio como en la sección 3 (`ok: false`).

### 8.3 Token de escritura

Cuando el usuario pulsa **Confirmar**, el widget pide al `token-url` del sistema (con la sesión del usuario) un token para esa confirmación: la misma ruta con `?confirmacion=<id>&huella=<huella>` añadidos a la query. El sistema comprueba que la huella es de una propuesta suya, vigente y de ese usuario, y emite un JWT con los claims habituales más:

| Claim | Valor |
|---|---|
| `scope` | `asistente:escritura` |
| `exp` | **≤ 60 s** después de `iat` (el asistente rechaza más de 120 s) |
| `jti` | único; **un solo uso** |
| `act` | nombre de la única tool para la que sirve |
| `ph` | la huella confirmada |
| `cid` | el id de la confirmación (`confirmacion` de la query) |

Un usuario sin permiso de escritura recibe `403` y la tarjeta lo informa.

### 8.4 Ejecución

El asistente llama al endpoint de ejecución de siempre (sección 3) con ese token y la cabecera **`Idempotency-Key`** (el id de la confirmación). El sistema debe:

1. Validar firma y vigencia, y exigir `scope: asistente:escritura`, `act` = la tool pedida y `cid` presente.
2. Aceptar cada `jti` **una sola vez**.
3. Comprobar que los parámetros recibidos son los de la propuesta cuya huella es `ph` (si cambiaron, `403`).
4. Para una modificación, comprobar que el dato **no cambió** desde la propuesta; si cambió, `{"ok": false, "error": "conflicto"}`.
5. Tratar la `Idempotency-Key` repetida devolviendo el resultado anterior sin reejecutar.
6. Responder `{"ok": true, "datos": {"mensaje": "Nota agregada."}, "fuente": …, "ui": […]}`; `datos.mensaje` (≤ 300 caracteres) es lo que muestra la tarjeta.

Rechazar con `403` una escritura con token de lectura, una de lectura con token de escritura y un token de escritura para otra tool. El asistente nunca reintenta una ejecución.

### 8.5 En el asistente y el widget

- El modelo propone con la tool de escritura; el asistente pide la propuesta, la guarda como **pendiente** (`/v1/confirmaciones/{id}`), avisa al widget con el evento SSE `confirmacion` (`{ id, tool, resumen, lineas, huella, expira }`) y el modelo recibe «pendiente: no se ejecutó». Una propuesta por turno, una pendiente por conversación (la nueva reemplaza a la anterior) y un tope de propuestas por usuario y hora (`ASISTENTE_ACCIONES_MAX_POR_HORA`, 20).
- **El widget muestra una tarjeta** con el resumen del sistema, los botones Confirmar y Cancelar y la cuenta regresiva hasta el vencimiento. Solo un clic real confirma; el texto va como texto, nunca como HTML.
- **Recargar la página:** `GET /v1/conversaciones/{id}` devuelve además `pendiente`: la propuesta vigente de esa conversación (`{ id, tool, estado, resumen, lineas, huella, expira }`) o `null`. El widget, al restaurar la conversación, vuelve a dibujar la tarjeta con su cuenta regresiva; una propuesta cancelada, confirmada, vencida o reemplazada no se restaura.
- `POST /v1/confirmaciones/{id}/confirmar` (token de escritura) y `POST /v1/confirmaciones/{id}/cancelar` (token de lectura). Cada transición es atómica: dos clics o dos pestañas no ejecutan dos veces (`409 accion_no_pendiente` con el `estado` actual). Una acción ajena o inexistente da `404`.
- **Nunca se confirma por voz**, tampoco en el modo voz: allí el asistente dice la propuesta en voz alta («Te pido confirmar en pantalla: …»), el widget pasa al chat para que se vea la tarjeta y espera el clic.
- Auditoría: la propuesta (`{tool}#propuesta`) y la ejecución quedan en `llamadas_tool`, y el ciclo de vida completo en la tabla `acciones`, con la misma retención que las conversaciones (30 días por defecto). El resultado se agrega al historial de la conversación. La acción queda a nombre del usuario que confirma (`sub`), con el asistente como origen.

Las referencias de esta sección son el sistema mock (`ejemplos/sistema-mock`, tools `agregar_nota` y `modificar_nota`), la referencia PHP (`ejemplos/sistema-php`, mismas tools sobre SQLite, para copiar y adaptar) y `tests/test_mock_acciones.py`; el verificador (sección 6.5) las comprueba contra un sistema en marcha; cada regla de 8.2–8.4 tiene su prueba y su defecto deliberado (`propuesta_con_efectos`, `ph_ignorado`, `replay_aceptado`, `token_otra_tool`, `sin_idempotencia`, `token_escritura_largo`).
