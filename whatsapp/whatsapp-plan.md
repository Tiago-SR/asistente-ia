# WhatsApp: plan de implementación (parte 2)

Para ejecutar en otra conversación, paso por paso. **Marcar `[x]` al terminar cada punto** y anotar fecha/commit
sugerido en «Registro». Referencias: `whatsapp-api.md` (investigación y contrato de Meta), `whatsapp-alta.md`
(alta fuera del código; las fases 1 y 2 sólo necesitan hasta su §4).

Reglas del proyecto: responder en español, no hacer `git commit` (sugerir mensaje), tests sólo al terminar cada
feature (suite mínima), brevedad en las respuestas del asistente. Adaptado al código de `asistente-mvp` el 2026-10-26.

## Cómo retomar en un chat limpio

1. Leer este plan y `contrato/CANAL_WHATSAPP.md` (contrato con el sistema anfitrión). `whatsapp-api.md` y
   `whatsapp-alta.md` sólo como consulta.
2. Estado: **Fases 1 y 2 (hasta el paso 6) hechas** (2026-10-26) y **rehechas con strategy por sistema** (ver «Decisiones»: `core/canales/`, `canal_mensajeria` en la config del sistema, secretos `wa_*` en `sistema_secreto`, webhook `/canal/{sistema_id}/webhook`, tablas `canal_mensajes`/`canal_vinculos`, panel en `Sistema.tsx`). Ya no hay nada global. Falta el paso 7 (configurar Meta, lo hace el usuario); luego **Fase 3**. Webhook en `api/whatsapp.py`; `procesar()` es el punto de enganche de la Fase 3. Secretos globales en `store/whatsapp.py` (tabla `secreto_global`, AAD `global:campo`); endpoints `/admin/api/whatsapp*`.
   El alta en Meta (`whatsapp-alta.md`) la hace el usuario en paralelo; la Fase 1 no la necesita.
3. Mapa del código (verificado el 2026-10-26, los números de línea pueden moverse):
   - Turno: `core/agent.py:95` `run_turn(...)`, eventos por callback `emit`; el llamador guarda con `guardar_turno`
     sólo si `res.completo` (ver `api/chat.py:159-179`). Identidad: `sistemas/auth.py:48` `Usuario`; sesión:
     `api/deps.py:14`; conector: `svc.conector.para(usuario, request_id)`.
   - Confirmaciones: `api/confirmaciones.py` (`vista_accion:35`, `confirmar:107`), `store/acciones.py`.
   - Persistencia: SQLAlchemy 2.x/PostgreSQL, `store/models.py`, migraciones `store/migrations/versions/` (última
     `0014`), clases `XxxSql` (ver `store/auditoria.py`).
   - Secretos: `sistemas/cifrado.py` `Cifrador`, `sistemas/escritura.py:276` `guardar_secreto`,
     `sistemas/registro.py:202` `CAMPOS_SECRETOS`.
   - Panel/admin: `api/admin.py`, `panel/src/pages/Sistema.tsx`. Ajustes globales: `config.py` `Settings`.
   - Imágenes: `core/adjuntos.py` `decodificar()`, límites en `config.py:56-57`.
4. Reglas: no `git commit` (sugerir mensaje), responder en español, tests sólo al terminar cada feature, consultar al
   `asesor` antes de decisiones difíciles de revertir.

> Propuesta pendiente (no implementada): un número compartido entre sistemas, ver `whatsapp/numero-compartido.md`.

## Objetivo

El usuario habla por WhatsApp con el asistente igual que en el chat web: **consultar y dar de alta/modificar** (con
confirmación; **borrar nunca**). Flujo de cada mensaje de un número vinculado:

1. Llega el mensaje (webhook firmado), se deduplica por wamid y se responde 200 enseguida.
2. Espera aleatoria de **1 a 5 s** y envío de una **bienvenida breve** («recibí tu solicitud, la estoy procesando»).
3. Se corre el turno del asistente y se envía su respuesta como texto (conversación mínima).
4. Número desconocido o sin vínculo: **silencio** (ni respuesta ni log del contenido).
5. Fotos: JPEG/PNG directo (reducidas si pasan el tope); **PDF: se rasteriza** a imagen.

## Decisiones tomadas

- [x] El webhook y la conexión viven en el asistente (opción B de `whatsapp-api.md` §9). 2026-10-26.
- [x] Número desconocido: silencio. PDF: rasterizar. Confirmaciones: el TTL actual alcanza (`confirmacion_ttl_s`,
  120 s por defecto, tope del operador; no existe `TTL_PROPUESTA` en este repo). 2026-10-26.
- [x] **Identidad: el mapeo número-usuario vive en el sistema anfitrión** (aprobado por el usuario, 2026-10-26;
  recomendación del asesor). Contrato escrito en `contrato/CANAL_WHATSAPP.md` (+ `CONTRATO.md` §9). Rutas finales:
  `POST /asistente/canal/codigo`, `/canal/vincular`, `/canal/token` (en este plan, `token-canal` = `/canal/token`).
  Falta implementarlo **en el asistente** (fase 3) y en los ejemplos (`sistema-mock`, `sistema-php`) y el verificador
  (`herramientas/verificar_sistema.py`), que hoy no lo conocen.

- [x] **Strategy por sistema** (2026-10-26, tras consultar al asesor): cada sistema elige proveedor de canal o ninguno; el
  proveedor trae sus campos y secretos. Reemplaza lo «global». `canal.whatsapp.prefijo` ya no es necesario para enrutar
  (la ruta identifica al sistema); `acciones_whatsapp` pasa a `canal_mensajeria.acciones`. Una App de Meta por sistema
  (el webhook es por App; `parsear` descarta lo que no sea de su `phone_number_id`). Interfaz neutra en
  `core/canales/base.py` (`Canal`: verificar_suscripcion, autenticar, parsear, enviar_texto, descargar_medio, probar;
  `enviar_botones` se añade en la Fase 3, paso 11). Las menciones a `/whatsapp/webhook`, `core/whatsapp/`, `wa_id`→
  `contacto` y «secretos globales» de abajo son anteriores a este cambio.

- [x] **Proveedor `openwa`** (2026-10-26, tras consultar al asesor): segundo proveedor del strategy, solo lectura
  (`acciones` vacío por validador), webhook firmado obligatorio, solo chats individuales con teléfono resoluble
  (`@lid` sin `senderPhone` = silencio), contacto = dígitos (`@c.us` se añade al enviar), sin botones (las
  confirmaciones con botón de la Fase 3 solo valen con Meta), alta de sesión y webhook manual. **Formatos tomados de su
  documentación, sin captura real**: pendiente levantar OpenWA en dev y verificar firma, `data.id`, si el webhook trae
  `media.data` en base64 (choca con `TopeCuerpo`), ruta de media y si bloquea webhooks a hosts privados.

## Identidad: wa_id → usuario del sistema

Hoy el asistente sólo **valida** JWT que emite el sistema anfitrión con la sesión del usuario (`CONTRATO.md` §1 y
§8); no puede pedir un token sin sesión, y la identidad es `(sistema_id, usuario_ref)` (`sistemas/auth.py:48`). No hay
teléfono en ninguna tabla. Recomendación: **el mapeo vive en el sistema, no en el asistente**.

- **Vinculación** iniciada desde la sesión web del sistema: genera un código de un solo uso (~10 min); el usuario lo
  manda por WhatsApp; el asistente llama `POST {base}/asistente/canal/vincular {canal:"whatsapp", wa_id, codigo}` con
  un **token de canal** (credencial de servicio nueva, distinta del token de manifiesto). El sistema guarda
  `wa_id ↔ usuario` y avisa al usuario.
- **Token por mensaje**: `POST {base}/asistente/token-canal {canal, wa_id}` → mismo `{token, expira}` de §1, con
  claim nuevo `canal:"whatsapp"`. Sin vínculo: 403/404 y el asistente calla.
- **Escritura**: `token-canal` acepta `confirmacion` y `huella` como hoy §8.3; `act`, `ph`, `cid` no cambian. El
  sistema verifica que la huella salió de una propuesta del mismo `sub` con un token de `canal:"whatsapp"`.
- El asistente sólo guarda `wa_id → sistema_id` para enrutar (tabla no autoritativa).
- **Por qué no firmar en el asistente ni guardar credenciales largas**: un asistente o BD comprometidos no deben poder
  fabricar identidades (principio de §8).
- **SIM swap / número reciclado** (riesgo residual): el vínculo caduca (90 días, o 30 sin uso) y se renueva desde la
  web; el usuario lo revoca desde el sistema; borrar el vínculo ante el evento de cambio de número de Meta si llega.
- **Escritura por WhatsApp apagada por defecto**: interruptor por sistema y por tool (`acciones_whatsapp`, aparte de
  `acciones_habilitadas`); las destructivas nunca se ofrecen por este canal.
- **Confirmación atada al mensaje**: sólo con botón interactivo cuyo `id` lleve `cid` + nonce y con `context.id` igual
  al wamid de la tarjeta enviada. Nunca vale un «sí» en texto libre, ni un texto del modelo. La tarjeta muestra el
  `resumen`/`detalle` del sistema. Límite de propuestas por número y hora. Una propuesta por vez.
- Cambio de contrato **hecho**: `contrato/CANAL_WHATSAPP.md` (guía para implementar en el sistema) y `CONTRATO.md`
  §9. No cambia ningún endpoint existente; el widget sigue igual. Implementarlo en un sistema anfitrión real queda
  fuera de este repo; en este repo sólo van los ejemplos y el lado del asistente.
- Lado asistente a implementar: `conector.token_canal_env` y `canal.whatsapp.prefijo` en el registro de sistemas
  (`sistemas/registro.py`), cliente de `/canal/vincular` y `/canal/token`, `acciones_whatsapp` por sistema/tool.

## Fase 1: base (sin Meta real, todo testeable local)

1. [x] **Modelo y migración** (`store/models.py` + `store/migrations/versions/0015_whatsapp.py`; patrón `XxxSql`
   en `store/`, ver `auditoria.py`).
   - `whatsapp_mensajes`: `id` (wamid, PK texto = deduplicación), `wa_id`, `direccion` (`entrada`/`salida`), `tipo`,
     `estado`, `error`, `creado_en`. Índice para purga (como `0014_indices_purga`).
   - `whatsapp_vinculos`: `wa_id` (PK), `sistema_id`, `activo`, `creado_en`, `ultimo_uso`. Sin `usuario_ref`: la
     identidad la resuelve el sistema (ver «Identidad»).
2. [x] **Configuración y secretos** (global, no por sistema: el número de WhatsApp es del operador)
   - Secretos cifrados con `Cifrador` (`sistemas/cifrado.py`): `token`, `app_secret`, `verify_token`. Revisar si
     `guardar_secreto`/`CAMPOS_SECRETOS` (`sistemas/escritura.py:276`, `registro.py:202`) sirven tal cual o si hace
     falta un hermano sin `sistema_id` real (AAD `sistema_id:campo`).
   - No secretos (`phone_number_id`, `waba_id`, `graph_version` = `v23.0`) en `config.py` (`Settings`, env) o en BD.
   - Endpoints admin en `api/admin.py` (permiso como `_ESCRIBIR`/`_LEER`), sin devolver valores (`configurado` +
     `huella`).
3. [x] **Cliente Graph** (`core/whatsapp/`, `httpx`, sin SDK; mismo estilo que `core/web/` y `core/voz/`)
   - `enviar_texto`, `marcar_leido`, `info_medio`, `descargar_medio` (header `Authorization`), timeouts, reintento en
     5xx/429, errores tipados (`WhatsAppError`). `probar_conexion()` = GET `/<phone_number_id>`.
   - Test mínimo con `httpx.MockTransport`.

## Fase 2: webhook

4. [x] **GET `/whatsapp/webhook`**: verificación (`hub.mode`, `hub.verify_token` con `hmac.compare_digest`,
   devuelve `hub.challenge` como `PlainTextResponse`; 403 si no). Router nuevo en `api/`, montado en `main.py`
   junto a los otros (`main.py:112-116`).
5. [x] **POST `/whatsapp/webhook`**
   - Cuerpo crudo, validar `X-Hub-Signature-256` (HMAC-SHA256 con App Secret) antes de parsear; 403 si falla.
     Respetar `TopeCuerpo` (`api/`).
   - Parsear `entry[].changes[].value`; `messages[]` → insertar en `whatsapp_mensajes` (si el `id` ya existe,
     ignorar, **sin segunda respuesta**); `statuses[]` → actualizar estado y registrar `failed`.
   - Responder 200 enseguida; el trabajo va a `BackgroundTasks`. Payloads desconocidos: log y 200.
   - Tests: firma buena/mala, duplicado, payload de estado.
6. [x] **Despliegue**: exponer sólo `/whatsapp/webhook` sin sesión ni CSRF (autenticidad = firma). README: variables,
   `location` del proxy, túnel para dev.
7. [ ] **Configurar el webhook en Meta** (`whatsapp-alta.md` §5) y probar con el número de prueba. *Hito: eco.*

## Fase 3: identidad y entrega al asistente (contrato en `contrato/CANAL_WHATSAPP.md`)

7b. [~] (mock hecho 2026-10-27, solo lectura; faltan PHP y verificador) **Ejemplos y verificador** (para poder probar de punta a punta sin un sistema real): implementar el canal en
   `ejemplos/sistema-mock/app.py` (y, si se quiere, en `ejemplos/sistema-php`), y añadir comprobaciones en
   `herramientas/verificar_sistema.py` (sólo si el sistema declara el canal). Casos en `CANAL_WHATSAPP.md` §9.
8. [x] (`api/canal_flujo.py`, 2026-10-27) **Vinculación**: mensaje `VINCULAR <PREFIJO>-XXXXXXXX` → elegir sistema por prefijo → `canal/vincular` →
   guardar `whatsapp_vinculos` (`wa_id → sistema_id`). Sin vínculo y sin código válido: silencio. Normalizar `wa_id`
   (sin `+`). `404` del sistema = silencio.
9. [x] (solo texto y lectura; `acciones=None`; lock en memoria por número) **Turno por WhatsApp** (`core/whatsapp/turno.py`, reutiliza `run_turn`, `core/agent.py:95`; no hay SSE)
   - `sleep(random.uniform(1, 5))` → bienvenida → pedir `token-canal` → armar `Contexto` (`core/ports.py:46`),
     `svc.llm_para(sistema)`, `svc.conector.para(usuario, request_id)` → `run_turn(..., emit=acumulador)`.
   - Si `res.completo`, `guardar_turno` en el mismo orden que `api/chat.py:159-179`. Renovar el token ante 401.
   - Enviar la respuesta con `enviar_texto`, cortada a 4.096 caracteres. Respetar `limites` y `metricas`.
   - Una conversación por `wa_id` (serializar mensajes del mismo número con un lock; no dos turnos a la vez).
10. [x] (pypdfium2 + Pillow, `core/medios.py`; sin tests aún, van en el paso 12) **Medios**
    - `info_medio` + `descargar_medio` (URL dura 5 min), validar `mime_type`, tope propio y `sha256`.
    - JPEG/PNG → `core/adjuntos.py` `decodificar()` (hoy 3 imágenes, 700 KB c/u, `config.py:56-57`): reducir/recomprimir
      antes de entregar. **PDF → rasterizar** (hace falta dependencia nueva, p. ej. `pymupdf`; no está en
      `pyproject.toml`) primera página o hasta el tope de imágenes. Respetar `adjuntos.habilitado` y
      `soporta_imagenes` del sistema. No se guarda nada (`NoGuarda`).
11. [x] (2026-10-27 hecho: botón `ok|no:<cid>:<hmac>` (clave `wa_app_secret`, ata acción+número) en lugar de `context.id`, sin migración; `canal_mensajeria.acciones` por sistema; destructivas y locales fuera; una tarjeta por vez) **Confirmación de propuestas**: tarjeta con botones interactivos según «Identidad» (cid + nonce,
    `context.id`). Confirmar vía el flujo existente (`api/confirmaciones.py:107`, token de escritura con
    `act`/`ph`/`cid`), sin atajos nuevos en el endpoint HTTP. Vencida: volver a proponer.
12. [x] (hecho: tests en `tests/test_canal.py` (botón, cancelar, firma falsa, sin acciones, estados)) Tests mínimos del flujo con LLM y conector simulados: vinculado/no vinculado (silencio), texto, imagen, PDF,
    confirmación, duplicado.

## Fase 4: operación y producción

13. [x] (hecho: `CanalEstado.tsx` (vínculos con revocar, fallos 24 h) + endpoints `/canal/vinculos`, `/canal/vinculos/revocar`, `/canal/errores`; campo de acciones del canal) **Panel** (`panel/src/pages/`, página nueva o sección en `Sistema.tsx`; ya hay campos de secreto en
    `Sistema.tsx:266-283`): credenciales, «Probar conexión», vínculos activos con revocar, últimos errores.
14. [x] (hecho: tope por número (20/min, 300/día) y por sistema, salidas registradas con estado/código, log.error con ≥5 fallos/h, auditoría `canal_probar`/`canal_revocar` (`AdminSql.auditar`, no `AuditoriaSql`)) **Registro y límites**: log sin tokens ni contenido; límite de mensajes por número y por minuto; alerta si hay
    `failed` repetidos (131047 fuera de ventana, 131026 no entregable, 131052 medio grande). Purga de
    `whatsapp_mensajes`. Auditoría con `AuditoriaSql`.
15. [ ] **Número real** (`whatsapp-alta.md` §6): cambiar `phone_number_id`, método de pago, perfil. Probar con un
    ticket real.
16. [ ] **(Opcional) Avisos salientes con plantilla**: sólo si el cliente lo pide; implica costos de utility.
17. [ ] **README**: sección «WhatsApp» (variables, alta resumida, despliegue, rotación) y quitar de `PENDIENTES.md`
    lo que corresponda.

## Criterios de aceptación

- Un mensaje de un número vinculado recibe bienvenida a los 1-5 s y luego la respuesta del asistente.
- Una foto o PDF de ticket genera una propuesta, confirmada por botón, que queda con `origen = asistente`.
- Un número sin vínculo no recibe nada y no consulta ni escribe nada.
- Reenvíos de Meta (mismo wamid) no duplican ejecuciones ni respuestas.
- POST sin firma válida da 403; ningún secreto aparece en logs ni en respuestas de la API.
- Ninguna tool destructiva se ofrece por WhatsApp.

## Riesgos y preguntas abiertas

- **Identidad**: el cambio de contrato exige trabajo en cada sistema anfitrión; hasta decidirlo no se puede empezar la
  fase 3.
- Verificar con la versión de Graph elegida que `button_reply` trae `context.id` y si existe el evento de cambio de
  número (no confirmado).
- Cambio de precios del 2026-10-01 muy reciente: releer `developers.facebook.com/docs/whatsapp/pricing` en la fase 4.
- Versión de Graph API (v23.0 en los ejemplos oficiales): confirmar al empezar la fase 1.
- SIM swap sobre un número vinculado: lectura hasta que el vínculo vence o se revoca; aceptarlo por escrito.
- Persona dueña del portfolio de Meta: punto único de fallo organizativo.

## Registro de avance

| Fecha | Paso | Notas / mensaje de commit sugerido |
|---|---|---|
| 2026-10-26 | Adaptación del plan | Plan traducido al código del asistente; decisiones de silencio/PDF/TTL; identidad pendiente |
| 2026-10-26 | Fase 1 (pasos 1-3) | Migración 0015 sin probar con alembic (tests usan create_all); `core/whatsapp/cliente.py` + `store/whatsapp.py` + admin; sin test de BD de secretos. Commit: `WhatsApp: modelo, secretos globales y cliente Graph` |
| 2026-10-26 | Fase 2 (pasos 4-6) | `api/whatsapp.py`, `core/whatsapp/webhook.py`, tests; `procesar()` aún no responde. Commit: `WhatsApp: webhook firmado con deduplicación` |
| 2026-10-26 | Rehecho como strategy por sistema | `core/canales/{base,config,meta,__init__}.py`, `api/canal.py`, `store/canal.py`, migración 0015 reescrita (`canal_*`), panel, `tests/test_canal.py`; suite 406 OK. Commit: `Canal de mensajería por sistema (strategy) con proveedor Meta` |
| 2026-10-26 | Proveedor OpenWA | `core/canales/openwa.py`, unión discriminada en `registro.py`, `_verificar_destinos`, panel, tests (410 OK). Commit: `Canal de mensajería: proveedor OpenWA (solo lectura, no oficial)` |
