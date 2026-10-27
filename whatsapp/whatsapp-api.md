# WhatsApp Business Platform (Cloud API): cómo implementarla en fiscalST

Investigado el 2026-10-26. Fuente principal: documentación oficial de Meta
(`developers.facebook.com/documentation/business-messaging/whatsapp/`). Lo que no pude confirmar en fuente oficial
está marcado **[sin confirmar]**.

## 1. Qué es y qué usar

- **Cloud API** (alojada por Meta) es la única vía vigente. La On-Premises API fue retirada; no considerarla.
- Todo va por HTTPS contra Graph API: `https://graph.facebook.com/<versión>/<PHONE_NUMBER_ID>/messages`.
- Versión de Graph API: los ejemplos oficiales usan **v23.0**. Mantenerla en una variable de entorno
  (`WHATSAPP_GRAPH_VERSION`) y revisar la vigente al implementar **[sin confirmar que v23.0 sea la última]**.
- Alternativa a hablar directo con Meta: un BSP (Twilio, 360dialog, etc.). Añade comisión por mensaje y otra
  dependencia; para una sola empresa y bajo volumen, directo con Meta es más simple.

## 2. Qué casos tendría en fiscalST

Según el README, las facturas llegan por FEU y los eTickets/fotos entran por el asistente (`crear_comprobante`).
Usos razonables de WhatsApp, de menor a mayor esfuerzo:

1. **Recibir fotos/PDF de tickets** que el usuario manda al número de la empresa → descargar el medio → pasarlo
   al asistente (LLM/OCR) → fiscalST valida y guarda como propuesta. Solo mensajes entrantes + respuestas dentro
   de la ventana de 24 h (ver precios).
2. **Avisos salientes** (comprobante en bandeja sin imputar, mes por cerrar): requieren *plantillas* aprobadas.
3. Chat con el asistente por WhatsApp (equivale a la pantalla «Asistente» de la web).

Restricciones del proyecto que aplican: el LLM nunca calcula impuestos, montos con `Decimal`, y el LLM/OCR vive en
el asistente (ver memoria «Rol del asistente»). Por tanto fiscalST sólo debería hacer de **canal**: recibe el
webhook, identifica al usuario, entrega el contenido al asistente y devuelve la respuesta. Falta decidir si el
webhook de Meta lo recibe fiscalST o el asistente (ver §9). No modificar `~/dev/asistente-mvp`.

## 3. Alta en Meta (una sola vez)

1. Cuenta de desarrollador en `developers.facebook.com` y un **business portfolio** (Meta Business).
2. Crear una app en el App Dashboard con el caso de uso «Connect with customers through WhatsApp».
3. «Start using the API»: crear o conectar una **WhatsApp Business Account (WABA)**. Guardar el *Messaging account ID*
   (WABA ID).
4. **Número de teléfono**: debe poder recibir un código SMS/llamada y **no estar registrado** en WhatsApp ni en la
   app WhatsApp Business (si lo está, hay que borrarlo de allí primero). Meta ofrece un número de prueba sin costo
   para desarrollar. Guardar el `phone_number_id` (no es el teléfono).
5. **Token permanente**: Business Settings → System users → crear usuario de sistema, asignarle la app (Manage app)
   y la WABA (control total) y generar token con permisos `whatsapp_business_messaging`,
   `whatsapp_business_management` y `business_management`. El token temporal de «API Setup» caduca en horas; sólo
   sirve para probar.
6. Guardar también el **App Secret** (para validar la firma del webhook) y elegir un **verify token** propio
   (cadena aleatoria larga).
7. **Verificación del negocio**: opcional para empezar, pero es una de las vías para subir de 250 a 2.000
   destinatarios únicos fuera de ventana (ver §7).
8. Agregar un **método de pago** en la WABA; sin él no se entregan mensajes cobrables (ver §6).

Secretos: usar el mecanismo existente de `integraciones`/`guardar_secreto` (como FEU), no variables sueltas en
el repo. Nada de esto va a git.

## 4. Webhook (recibir mensajes)

Endpoint público HTTPS (certificado válido; en dev, túnel tipo cloudflared/ngrok), por ejemplo
`POST/GET /whatsapp/webhook` en FastAPI. En el App Dashboard → WhatsApp → Configuration: pegar la URL y el verify
token, y **suscribir el campo `messages`** (mensajes entrantes y estados de los enviados).

**Verificación (GET)** — Meta envía `hub.mode=subscribe`, `hub.verify_token`, `hub.challenge`. Si el token coincide,
responder **200 con el `hub.challenge` en texto plano** (no JSON); si no, 403.

**Eventos (POST)**:
- Validar la cabecera `X-Hub-Signature-256`: `sha256=` + HMAC-SHA256 del **cuerpo crudo** con el App Secret
  (comparar con `hmac.compare_digest`; leer `await request.body()` antes de parsear el JSON).
- Responder **200 rápido**; procesar en segundo plano. Cualquier otro código dispara reintentos: inmediato y luego
  con frecuencia decreciente **hasta 7 días**, y pueden llegar duplicados → **deduplicar por `messages[].id`**
  (tabla con unique, como se hace con `jti` en `asistente.py`).
- Un POST puede traer hasta 1.000 actualizaciones; iterar todas las `entry[].changes[]`. Payload máx. 3 MB.
- Estructura: `object = "whatsapp_business_account"` → `entry[].changes[].value` con `metadata`
  (`display_phone_number`, `phone_number_id`), `contacts[]` (`wa_id`, `profile.name`) y `messages[]`
  (`from`, `id`, `timestamp`, `type`, y el objeto del tipo: `text.body`, `image.id`, `document.id`, …).
  Los estados de envío llegan en `value.statuses[]` (sent/delivered/read/failed). El 2026-10-12 Meta añadió un campo
  `subtype` a los estados.
- Opcional: mTLS para webhooks (Meta lo soporta); las IP de Meta cambian, no confiar en una lista de IP fija.

## 5. Enviar mensajes

```bash
curl 'https://graph.facebook.com/v23.0/<PHONE_NUMBER_ID>/messages' \
  -H 'Authorization: Bearer <TOKEN_SYSTEM_USER>' -H 'Content-Type: application/json' \
  -d '{"messaging_product":"whatsapp","to":"<wa_id>","type":"text","text":{"body":"Hola"}}'
```

- **Dentro de la ventana de servicio** (24 h desde el último mensaje del usuario; se renueva con cada mensaje
  suyo) se puede enviar texto libre, imágenes, botones, etc.
- **Fuera de la ventana** sólo **plantillas** (`"type":"template"`) previamente creadas y aprobadas (WhatsApp
  Manager o API de plantillas). Categorías: marketing, utility, authentication. La aprobación suele tardar minutos
  a horas; Meta puede recategorizarlas.
- El destinatario debe haber dado **opt-in** para mensajes iniciados por la empresa.
- Los números se envían en formato internacional sin `+` (Uruguay: `598…`).
- Marcar leído / indicador de escritura: mismo endpoint con `status: "read"` y el `message_id` entrante.

## 6. Descargar fotos y PDF recibidos (el caso de tickets)

1. El webhook trae `image.id` / `document.id` (ID válido **7 días**, descargar pronto).
2. `GET https://graph.facebook.com/v23.0/<MEDIA_ID>` con `Authorization: Bearer` → devuelve `url`, `mime_type`,
   `sha256`, `file_size`.
3. `GET <url>` **con el mismo header Authorization** (sin él falla). La URL caduca a los **5 minutos**; si da 404,
   pedir otra.
4. Límite de entrada 100 MB (si no, error 131052). Tipos: imágenes `image/jpeg`, `image/png`; documentos PDF,
   Office, txt. Validar `mime_type` y `sha256` y limitar tamaño antes de pasarlo al asistente.

Ojo: el widget del asistente hoy sólo adjunta JPEG/PNG (README). Si llegan PDF por WhatsApp, o se rasterizan o se
rechazan con un mensaje claro.

## 7. Límites

- **Fuera de ventana**: tope de destinatarios únicos en 24 h móviles, por *business portfolio* (compartido entre
  números): 250 (inicial) → 2.000 → 10.000 → 100.000 → ilimitado. A 2.000 se sube verificando el negocio o enviando
  2.000 mensajes de calidad en 30 días; después sube solo si usas ≥50 % del límite en 7 días con buena calidad.
  Para una empresa sola, 250 sobra.
- Los mensajes dentro de la ventana de servicio no cuentan para ese tope.
- Throughput por número y límites por usuario de marketing: **[sin confirmar cifras]**; irrelevantes a este volumen.

## 8. Precios (vigente al 2026-10-26)

Modelo **por mensaje entregado** desde 2025-07-01 (se acabó el cobro por conversación). Se cobra por categoría y por
país del **destinatario**. Uruguay (+598) está en la región **«Rest of Latin America»**.

| Tipo | Cobro |
|---|---|
| Marketing (plantilla) | Siempre se cobra |
| Utility (plantilla) | Se cobra fuera de ventana; **desde 2026-10-01 también dentro** de ventana |
| Authentication (plantilla) | Se cobra; tarifa «international» más alta si emisor y destinatario están en países distintos |
| Service (texto libre en ventana) | **Cambio 2026-10-01**: 1.000 gratis por número y mes, sin acumulación; después se cobra |
| Entry point gratuito | Respuesta a un usuario que llegó desde un anuncio Click-to-WhatsApp: gratis hasta 7 días |
| Meta Business Agent (IA de Meta) | USD 2,00 por millón de tokens; no lo usaríamos (el LLM es el nuestro) |

- Sin método de pago, los mensajes de servicio que superen los 1.000 gratis **no se entregan**.
- En los webhooks de estado, `pricing.type` = `free_customer_service` (gratis) o `regular` (cobrado).
- Las tarifas cambian sólo el 1 de enero/abril/julio/octubre, con 1 a 6 meses de aviso. Las cifras exactas para
  «Rest of Latin America» están en los CSV/PDF de la tarifa de Meta (por moneda) y **no las pude leer**: consultar
  `developers.facebook.com/docs/whatsapp/pricing` antes de presupuestar. Los blogs de terceros se contradicen.
- Para el caso 1 (el usuario escribe, el sistema responde) el costo esperado es **0**: queda bajo los 1.000 mensajes
  de servicio mensuales.
- El cambio del 2026-10-01 es muy reciente; releer la página de precios al implementar.

## 9. Diseño propuesto en fiscalST (mínimo)

Decisión abierta antes de codificar (consultar al asesor / al usuario): **¿quién expone el webhook?**

- **A. fiscalST** (recomendada): nuevo `api/fiscalst/whatsapp.py` con `APIRouter(prefix="/whatsapp")`.
  Webhook → valida firma → deduplica → mapea `wa_id` a un `usuarios` activo (tabla de teléfonos autorizados; un
  número desconocido recibe respuesta genérica o se ignora) → descarga el medio → llama al asistente con el
  contrato existente (JWT del usuario) → envía la respuesta. Ventaja: la autenticación y las reglas de negocio
  (mes cerrado, total vs IVA, duplicados) ya están aquí.
- **B. asistente**: el asistente atiende el webhook y llama a fiscalST con el contrato. Implica tocar
  `asistente-mvp`, que es de solo lectura para mí.

Piezas (opción A):
1. Config en `integraciones` (phone_number_id, token, app secret, verify token, versión Graph).
2. Tabla `whatsapp_mensajes` (`id` de Meta unique, `wa_id`, estado, `creado`) para idempotencia y trazabilidad.
3. Cliente HTTP delgado (`httpx`) con `enviar_texto`, `descargar_medio`; sin SDK.
4. Procesamiento con `BackgroundTasks` o el mecanismo que ya use el proyecto; el webhook sólo encola y devuelve 200.
5. Identidad: sólo números previamente registrados por un admin (vinculados a `usuarios`). Una escritura sigue el
   flujo propuesta/confirmación; confirmar con botones interactivos o respondiendo «sí».
6. Ajustes: botón «Probar conexión» como en FEU (GET `/<phone_number_id>` con el token).

## 10. Seguridad y operación

- Rechazar todo POST sin firma válida; nunca loguear tokens ni contenido de tickets completo.
- El token de system user no caduca: guardarlo cifrado y rotarlo si se filtra.
- Los medios contienen datos fiscales/personales: no persistir más de lo necesario y borrar el temporal tras pasarlo.
- WhatsApp es un canal sin sesión web: la autorización es el número de origen. Para acciones de escritura exigir
  confirmación explícita y limitar quién puede.
- Monitorizar `account_update`, `phone_number_quality_update` y `message_template_status_update` si se usan
  plantillas; una baja calidad reduce los límites.
- Probar con el número de prueba de Meta (hasta 5 destinatarios verificados) antes de migrar un número real.

## 11. Orden de implementación sugerido

1. Alta en Meta + número de prueba + curl de envío (sin código).
2. Webhook con verificación, firma y deduplicación; sólo registra.
3. Cliente de envío y descarga de medios; eco de prueba.
4. Mapeo de número a usuario + entrega al asistente.
5. Plantillas y avisos salientes (sólo si hacen falta).
6. Pasar a número real y añadir método de pago.

## Fuentes

- Pricing: https://developers.facebook.com/docs/whatsapp/pricing
- Get started: https://developers.facebook.com/documentation/business-messaging/whatsapp/get-started
- Webhooks: https://developers.facebook.com/documentation/business-messaging/whatsapp/webhooks/overview
- Crear endpoint de webhook: https://developers.facebook.com/documentation/business-messaging/whatsapp/webhooks/create-webhook-endpoint
- Medios: https://developers.facebook.com/documentation/business-messaging/whatsapp/business-phone-numbers/media
- Límites de mensajería: https://developers.facebook.com/documentation/business-messaging/whatsapp/messaging-limits
- Índice completo de la doc: https://developers.facebook.com/documentation/business-messaging/whatsapp/llms.txt
