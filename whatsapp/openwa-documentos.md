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

La capacidad ya está conectada con tools/prompts y con la persistencia y entrega de archivos del turno.
La exportación requiere `exportar_excel`, servicio de archivos y capacidad de documentos del canal.
Meta no ofrece esta herramienta. El widget conserva su botón y descarga autenticada.

Pendiente: envío real de un Excel pequeño a un contacto de prueba autorizado y
comprobación manual de nombre, apertura y contenido. La aceptación automatizada no reemplaza esa validación.

## Uso y errores del flujo integrado

Un usuario vinculado puede pedir una planilla con los datos consultados o aportados en la conversación.
Tras guardar el turno, el backend intenta adjuntarla al mismo contacto. Si hay varios archivos, cada ID
se procesa una sola vez. El nombre, MIME y contenido se recuperan del almacenamiento autorizado.

- Archivo inexistente, ajeno o vencido: aviso de que no está disponible; no se envía.
- Rechazo o timeout de OpenWA: aviso de que no se pudo confirmar el envío de ese archivo, sin reintento.
  Los demás archivos se siguen procesando si el canal permite comunicar el fallo.
- Turno incompleto o fallo de persistencia: no se envían documentos.
- La copia del asistente vence según la retención configurada; la enviada por WhatsApp permanece fuera de ese control.

## Prueba manual pendiente

1. Identificar la sesión, sistema y contacto vinculado de prueba, con autorización explícita para enviarle el documento.
2. Pedir desde ese contacto una planilla pequeña con dos columnas y un valor conocido.
3. Comprobar que llega un adjunto `.xlsx`, que abre y conserva nombre, columnas y valor.
4. Verificar el registro saliente de tipo `documento` y su ID, distinguiendo aceptación de recepción observada.
5. Anotar aquí fecha, versión, resultado y cualquier límite observado, sin teléfonos, credenciales ni contenido sensible.

Fuente: [OpenAPI de v0.26.0](https://raw.githubusercontent.com/rmyndharis/OpenWA/v0.26.0/openapi.json).
