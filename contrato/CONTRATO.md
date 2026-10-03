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

Firma recomendada: `RS256` o `EdDSA` (el sistema guarda la privada, el asistente solo la pública). Aceptado para sistemas legados: `HS256` con secreto compartido. `alg: none` se rechaza siempre.

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
