# Contrato de integración v1

Lo que **cada sistema** debe implementar para que el asistente responda preguntas sobre sus datos. Es HTTP + JSON, con tres piezas obligatorias (token, manifiesto, ejecución) y una opcional (salud). Las rutas mostradas son las sugeridas; en `config/sistemas.yaml` son configurables.

Archivos de referencia:

- `schemas/*.schema.json`: JSON Schemas de cada mensaje.
- `openapi.yaml`: descripción OpenAPI de los endpoints.

Principio: **el asistente nunca accede a la BD del sistema ni decide permisos.** Solo llama a tools con el token del usuario, y el sistema aplica sus propios permisos.

## 1. Emisión del token de usuario

Ruta del sistema (p. ej. `GET /asistente/token`), accesible desde su UI con su sesión normal. Devuelve:

```json
{ "token": "<jwt>", "expira": "2026-10-03T15:30:00Z" }
```

Si el usuario no tiene permitido el asistente, responde `403` y el widget se oculta.

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

La calidad de las descripciones determina la calidad del asistente: deben decir qué hace la tool, cuándo usarla y qué significan los parámetros.

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
- **Verificar la integración:** `python herramientas/verificar_sistema.py` contra el sistema, con la URL de emisión de token y el token de manifiesto (ver el encabezado del script).

### 6.4 Rotación y manejo

- **Rotar** = generar un valor nuevo, cambiarlo en el sistema y en el `.env` del asistente y reiniciar el asistente. El asistente solo conoce una clave por sistema: entre ambos cambios, los tokens firmados con la clave anterior fallan (vida máxima 15 min, el widget pide uno nuevo). Hacerlo en una ventana de poco uso.
- Rotar de inmediato ante cualquier sospecha de filtración, y cuando alguien con acceso al valor deje el proyecto.
- No poner estos valores en el repositorio, en tickets, en logs ni en el código del front. El navegador solo ve el JWT de vida corta, nunca la clave ni el token de manifiesto.
- Un valor por sistema y por entorno: pruebas y producción no comparten claves.
