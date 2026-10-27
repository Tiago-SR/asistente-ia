# WhatsApp Cloud API: guía de alta (parte 1)

Qué hay que hacer **fuera del código** para tener la API lista. Contexto y precios en `whatsapp-api.md`.
Los nombres de menús de Meta cambian seguido; si un botón no está donde dice, buscar por el nombre en inglés.
Marcar `[x]` a medida que se avance.

## 0. Decisiones previas (hacerlas antes de tocar Meta)

- [ ] **Número de teléfono** que usará la empresa.
  - Debe recibir un SMS o una llamada de verificación.
  - **No puede estar registrado en WhatsApp ni en WhatsApp Business App** (si lo está, hay que borrar esa cuenta).
    Un número que ya se usa para chatear con clientes es mala idea: se pierde el WhatsApp normal en él.
  - Recomendado: una línea nueva, sólo para esto.
- [ ] **Quién administra el negocio en Meta**: una persona real con cuenta de Facebook personal (Meta la exige para
  crear el portfolio). Elegir a alguien que no vaya a irse; es el dueño del portfolio.
- [ ] **Tarjeta** para el método de pago de la WABA (Meta cobra a esa cuenta, no a la app).
- [ ] **Datos de la empresa** a mano: razón social, RUT, dirección, web o perfil público, email corporativo
  (con dominio propio si hay; ayuda en la verificación).
- [ ] **Dominio/URL pública HTTPS** donde vivirá el webhook (VPS del asistente, ver `.claude/CLAUDE.md`).
  Certificado válido (Let's Encrypt sirve). Para desarrollo basta un túnel.

## 1. Portfolio comercial de Meta (Business Portfolio)

- [ ] Entrar a `business.facebook.com` con la cuenta personal y crear el portfolio con los datos de la empresa.
- [ ] Anotar el **Business Portfolio ID** (Configuración del negocio → Información del negocio).
- [ ] Activar verificación en dos pasos en la cuenta administradora.

## 2. Cuenta de desarrollador y app

- [ ] Registrarse en `developers.facebook.com` con la misma cuenta.
- [ ] App Dashboard → **Create app** → caso de uso **«Connect with customers through WhatsApp»**.
- [ ] Nombre de la app (interno), email de contacto y **asociarla al portfolio** del paso 1.
- [ ] Anotar el **App ID** y, en App settings → Basic, el **App Secret** (se usa para validar la firma del webhook).
  El secreto se guarda en el gestor de secretos del proyecto, nunca en git ni en chat.

## 3. WhatsApp Business Account (WABA) y número de prueba

- [ ] En la app: WhatsApp → **API Setup** (o Use cases → Customize). Crear o conectar una WABA.
- [ ] Meta crea un **número de prueba** gratuito. Anotar:
  - `WABA ID` (Messaging account ID)
  - `Phone number ID` del número de prueba (no es el teléfono)
- [ ] Agregar hasta 5 destinatarios de prueba (tu teléfono) y confirmar el código que llega.
- [ ] Enviar el mensaje de ejemplo del panel (`hello_world`) para ver que llega.

Con esto ya se puede desarrollar. Los pasos 4 a 7 se pueden hacer en paralelo con el código.

## 4. Token permanente (System User)

El token temporal del panel dura horas. Para el servidor se necesita uno permanente.

- [ ] Business settings → **Users → System users** → *Add* → nombre `fiscalst-whatsapp`, rol **Admin** (el rol Employee
  no puede generar tokens con estos permisos en algunos portfolios; si funciona con Employee, mejor).
- [ ] *Add assets*: asignar la **app** (Manage app, control total) y la **WABA** (control total).
- [ ] *Generate token* → elegir la app → expiración **Never** → permisos:
  `whatsapp_business_messaging`, `whatsapp_business_management`, `business_management`.
- [ ] Copiar el token **una vez** (no se vuelve a mostrar) y guardarlo como secreto.
- [ ] Probar:

```bash
curl 'https://graph.facebook.com/v23.0/<PHONE_NUMBER_ID>/messages' \
  -H 'Authorization: Bearer <TOKEN>' -H 'Content-Type: application/json' \
  -d '{"messaging_product":"whatsapp","to":"<TU_NUMERO_SIN_+>","type":"template","template":{"name":"hello_world","language":{"code":"en_US"}}}'
```

  Respuesta esperada: `{"messages":[{"id":"wamid...."}]}` y llega al teléfono. (Versión de Graph: ver `whatsapp-api.md` §1.)

## 5. Webhook (se completa cuando exista el endpoint)

Requiere el código del paso 3 del plan de implementación (`whatsapp-plan.md`). Aquí sólo el lado Meta:

- [ ] Inventar un **verify token** (cadena aleatoria larga: `openssl rand -hex 24`) y guardarlo como secreto.
- [ ] App Dashboard → WhatsApp → **Configuration** → Webhook: *Callback URL* = `https://<dominio>/whatsapp/webhook`
  y el verify token. *Verify and save*: Meta hace un GET; si el endpoint responde bien, queda verificado.
- [ ] **Suscribir el campo `messages`** (obligatorio). Opcionales útiles: `message_template_status_update`,
  `phone_number_quality_update`, `account_update`.
- [ ] Enviar un mensaje desde tu teléfono al número de prueba y ver que llega el POST.
- [ ] Si más adelante se usan varias apps/WABA, recordar que los reintentos van a todas las suscritas.

## 6. Pasar a producción (número real)

Hacerlo cuando el flujo funcione con el número de prueba.

- [ ] **Verificación del negocio** (Business settings → Security center → Start verification): subir documentos
  de la empresa (en Uruguay suele bastar certificado de DGI / RUT y comprobante de domicilio o contrato social;
  confirmar en el formulario qué aceptan). Puede tardar días. Es una de las vías para pasar de 250 a 2.000
  destinatarios únicos fuera de ventana; si sólo se responde a quien escribe primero, **no es imprescindible**.
- [ ] **Agregar el número real** a la WABA (API Setup → *Add phone number*): nombre visible (*display name*, debe
  corresponder a la empresa y pasa por revisión), categoría, y código de verificación por SMS o llamada.
- [ ] Registrar el número para Cloud API si el panel lo pide (`POST /<PHONE_NUMBER_ID>/register` con un PIN de
  6 dígitos de verificación en dos pasos; guardar el PIN).
- [ ] **Método de pago**: WhatsApp Manager → Configuración de pago (o Business settings → Payments). Sin él, desde el
  2026-10-01 los mensajes de servicio que superen los 1.000 gratis por número y mes no se entregan.
- [ ] Perfil del negocio (foto, descripción, email, web) en WhatsApp Manager.
- [ ] Cambiar en la config de fiscalST el `phone_number_id` de prueba por el real. El token de system user sigue
  sirviendo (la WABA es la misma).

## 7. Plantillas (sólo si habrá avisos salientes)

- [ ] WhatsApp Manager → **Message templates** → crear (idioma `es`, categoría **Utility** para avisos operativos).
- [ ] Contenido sin marketing ni promesas; variables `{{1}}` con ejemplo. Esperar aprobación (minutos a horas).
- [ ] Anotar el nombre exacto y el idioma: el código los necesita.
- [ ] Recordar el **opt-in**: guardar cuándo y cómo aceptó el usuario recibir avisos.

## 8. Secretos que quedan al final (para el plan de implementación)

| Dato | De dónde sale |
|---|---|
| `phone_number_id` | paso 3 (prueba) / paso 6 (real) |
| `waba_id` | paso 3 |
| Token de system user | paso 4 |
| App Secret | paso 2 |
| Verify token | paso 5 |
| PIN de registro (si aplica) | paso 6 |

Todos van cifrados en `configuracion` con `guardar_secreto` (como FEU y Cibeles). Si alguno se filtra: rotar token
(regenerar en System users) o App Secret (App settings → Reset) y recargarlo en Ajustes.

## 9. Lista de verificación final

- [ ] Mensaje de prueba enviado desde curl y recibido.
- [ ] Mensaje entrante llega al webhook con firma válida.
- [ ] Número real verificado y con método de pago.
- [ ] Negocio verificado (sólo si se enviarán avisos fuera de ventana a muchos números).
- [ ] Secretos guardados y fuera de git; nadie más con acceso al portfolio de Meta que no deba.
