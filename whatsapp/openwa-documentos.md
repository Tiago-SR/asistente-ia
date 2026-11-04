# Transporte de documentos: OpenWA 0.26.0

Validación del 2026-11-04. Se contrastó el OpenAPI del tag `v0.26.0` con el código
compilado de la instancia instalada, imagen
`ghcr.io/rmyndharis/openwa:0.26.0@sha256:46e3d3d01b1948c96a0bea94f6650aa772370f40dd3956052d2da24fe4ee2acf`.
No se actualizó el proveedor.

## Contrato verificado

- `POST /api/sessions/{sessionId}/messages/send-document`, autenticado con `X-API-Key`.
- JSON con `chatId` (`<teléfono>@c.us`), `base64` (bytes codificados, sin prefijo),
  `mimetype` y `filename` (máximo 255 caracteres).
- MIME de Excel: `application/vnd.openxmlformats-officedocument.spreadsheetml.sheet`.
- No requiere URL. No se publican archivos ni se usan enlaces como alternativa.
- El contrato devuelve HTTP 201 con `messageId` y `timestamp`. Significa aceptación
  para enviar a la sesión de WhatsApp; no confirma recepción por el destinatario.
- El código instalado (`message-send.service.js`, `buildMediaInput` y `sendDocument`)
  exige MIME con base64 y pasa los datos, nombre y MIME al motor de documentos.

## Límites y errores

El OpenAPI versionado documenta `MEDIA_DOWNLOAD_MAX_BYTES` (50 MiB por defecto) y
`BODY_SIZE_LIMIT` (25 MB por defecto). Base64 aumenta el tamaño aproximadamente un
tercio. Son valores documentados, no mediciones de envíos reales ni garantía de los
límites efectivos de la instancia. La aplicación conserva sus límites de generación
(2.048 KB por defecto), cuotas y caducidad.

El adaptador convierte fallos de HTTP/red, JSON inválido e ID ausente o inválido en
`ErrorCanal`. No reintenta: un timeout puede suceder después de que el proveedor
acepte el documento. Un ID aceptado tampoco demuestra entrega. No se vuelven a
generar archivos para resolver estos errores de transporte.

## Validación y estado

Se agregaron pruebas con HTTP simulado que envían un Excel generado con openpyxl,
lo decodifican y comprueban su contenido. También cubren rechazo 413, timeout,
JSON inválido e IDs ausentes o inválidos, verificando una sola solicitud por caso.
Meta declara que no tiene capacidad de documentos y rechaza su operación localmente.

Pendiente: envío real de un Excel pequeño a un contacto de prueba autorizado y
comprobación manual de nombre, apertura y contenido. El adaptador es el primer bloque;
todavía falta conectar la capacidad con tools/prompts y con la persistencia y entrega
de archivos del turno. La funcionalidad completa no está habilitada por este cambio.

Fuente: [OpenAPI de v0.26.0](https://raw.githubusercontent.com/rmyndharis/OpenWA/v0.26.0/openapi.json).
