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

Prueba real de archivo pequeño realizada en fiscalST: recepción y apertura confirmadas
por el usuario, con revisión del archivo descargado y del registro saliente. Ver resultado y límites abajo.

## Uso y errores del flujo integrado

Un usuario vinculado puede pedir una planilla con los datos consultados o aportados en la conversación.
Tras guardar el turno, el backend intenta adjuntarla al mismo contacto. Si hay varios archivos, cada ID
se procesa una sola vez. El nombre, MIME y contenido se recuperan del almacenamiento autorizado.

- Archivo inexistente, ajeno o vencido: aviso de que no está disponible; no se envía.
- Rechazo o timeout de OpenWA: aviso de que no se pudo confirmar el envío de ese archivo, sin reintento.
  Los demás archivos se siguen procesando si el canal permite comunicar el fallo.
- Turno incompleto o fallo de persistencia: no se envían documentos.
- La copia del asistente vence según la retención configurada; la enviada por WhatsApp permanece fuera de ese control.

## Procedimiento de prueba manual

1. Identificar la sesión, sistema y contacto vinculado de prueba, con autorización explícita para enviarle el documento.
2. Pedir desde ese contacto una planilla pequeña con dos columnas y un valor conocido.
3. Comprobar que llega un adjunto `.xlsx`, que abre y conserva nombre, columnas y valor.
4. Verificar el registro saliente de tipo `documento` y su ID, distinguiendo aceptación de recepción observada.
5. Anotar aquí fecha, versión, resultado y cualquier límite observado, sin teléfonos, credenciales ni contenido sensible.

Fuente: [OpenAPI de v0.26.0](https://raw.githubusercontent.com/rmyndharis/OpenWA/v0.26.0/openapi.json).

## Prueba manual cumplida del 2026-11-04

En desarrollo con fiscalST, el usuario aportó el archivo descargado
`[DEV] prueba_excel.xlsx`: 4.885 bytes, ZIP sin errores de integridad y estructura
XLSX válida. La hoja contiene las columnas `Concepto` e `Importe`, con la fila
de prueba `Prueba` y el valor numérico `42`. El nombre descargado incluye `[DEV]`;
no se comprobó todavía si coincide con el nombre almacenado y enviado.

Existe un único registro saliente de tipo `documento` para este sistema, con ID
no vacío, a las 21:45:15 UTC (18:45:15 local), coincidente con la descarga aportada.
Su estado almacenado es `enviado`: acredita el registro de aceptación del proveedor,
no demuestra por sí solo recepción. El usuario confirmó explícitamente que descargó
el archivo del adjunto recibido en WhatsApp y pudo abrirlo. Esa confirmación acredita
la recepción y apertura observadas en esta prueba; no se deducen del estado del proveedor. No se enviaron mensajes desde esta revisión.

Versión de referencia del contrato: OpenWA 0.26.0; no se volvió a consultar la versión
efectiva en esta revisión. No se midió el MIME transmitido ni el máximo de tamaño:
solo se verificó este archivo pequeño. Se marca la aceptación manual como cumplida
para este caso, sin extender el resultado a otros tamaños o nombres ni afirmar una
comparación exacta con el nombre almacenado. No se verificó por separado el texto
final del modelo ni el identificador de sesión efectiva en esta revisión.
