# Avisos salientes: cómo enviarlos desde un sistema (guía para un LLM o un desarrollador)

Sección **opcional** del contrato (§9 de `CONTRATO.md`, junto a `CANAL_WHATSAPP.md`). Es aditiva: no cambia ningún
endpoint existente y no sube la versión (`"contrato": "1"`). A diferencia del resto del contrato, **estos endpoints los
implementa el asistente**; el sistema es el cliente. Léelo junto con `CANAL_WHATSAPP.md` (vinculación de números).

## 0. Qué es esto y por qué así

El sistema detecta un hecho de negocio (p. ej. entra una factura que una regla filtra) y quiere avisar por WhatsApp a un
usuario ya vinculado, que puede contestar desde el chat. **El sistema es la fuente de verdad del negocio; el asistente es
solo transporte**: guarda el aviso, lo entrega y deja constancia mínima en la conversación del usuario. No interpreta el
texto, no resuelve URLs, no ejecuta nada y **no usa el modelo** para el aviso.

Un aviso es una orden de envío, no una garantía de entrega: aceptar (`202`) no significa entregado. El estado
(`pendiente → enviando → enviado | fallido | incierto`) se consulta con `GET`.

Requisitos para que funcione: el sistema tiene el canal **OpenWA** configurado (con Meta, fuera de la ventana de 24 h el
texto libre falla de forma asíncrona, así que no se admite) y el operador habilitó `avisos` en el registro del asistente
(apagado por defecto) y cargó el token de avisos.

## 1. Endpoints (los implementa el asistente)

| Endpoint | Quién lo llama | Credencial |
|---|---|---|
| `POST /sistemas/{sistema_id}/avisos` | el sistema | token de avisos |
| `GET /sistemas/{sistema_id}/avisos/{id_evento}` | el sistema | token de avisos |

`{sistema_id}` es el `id` del sistema en el registro del asistente (el mismo `iss` de sus tokens). Las rutas son
relativas a la URL del asistente, no a la `base` del manifiesto.

## 1.1 Requisitos normativos

DEBE / NO DEBE / PUEDE se leen como en RFC 2119. Cada ID se verifica con el caso de §6 que lo cita.

| ID | Requisito |
|---|---|
| AVI-01 | Los dos endpoints DEBEN exigir el token de avisos (`Authorization: Bearer`, comparación en tiempo constante) y responder `403` si falta o no coincide. |
| AVI-02 | El token de avisos DEBE ser un secreto distinto del token de canal, del token de manifiesto y de cualquier otra credencial, y DEBE poder rotarse aceptando el actual y el anterior. El token de canal NO DEBE servir como token de avisos. |
| AVI-03 | Sistema inexistente, deshabilitado, sin avisos habilitados o credencial inválida DEBEN dar la misma `403` (no enumerar sistemas). El token de un sistema NO DEBE servir en la ruta de otro. |
| AVI-04 | `tipo` DEBE estar en la lista permitida del sistema (por defecto `refacturacion_pendiente` y `refacturacion_resultado`); otro → `422`. |
| AVI-05 | El cuerpo DEBE ser ≤ 16 KB y `texto` ≤ `max_texto` (1000 por defecto, máximo 4000); si no, `413` / `422`. El asistente NO DEBE truncar el texto en silencio. |
| AVI-06 | `adjunto` DEBE ser `null` u omitirse; cualquier otro valor → `422 adjunto_no_soportado` (reservado para una fase posterior). |
| AVI-07 | `destinatario.wa_id` DEBE ser 8–15 dígitos, como texto exacto (sin `+`, espacios ni sufijos; CAN-05 y CAN-15). |
| AVI-08 | El destinatario DEBE ser un vínculo **activo y vigente** de ese sistema y `usuario_ref` DEBE corresponder al usuario de ese vínculo; si no → `422 destinatario_invalido` (sin distinguir el motivo). El asistente vuelve a comprobarlo justo antes de enviar. |
| AVI-09 | `id_evento` DEBE ser estable por hecho de negocio y destinatario. Mismo `id_evento` y mismo contenido → `200` con el estado guardado; mismo `id_evento` y contenido distinto → `409` y auditoría. |
| AVI-10 | El `202` DEBE darse solo después de persistir el aviso: un aviso aceptado sobrevive a un reinicio del asistente. |
| AVI-11 | El `texto` es una plantilla armada por el sistema. El asistente NO DEBE interpretarlo, resolver sus URLs, acortar enlaces, reescribirlo ni pasarlo al modelo como instrucción. |
| AVI-12 | La entrega NO DEBE reintentarse si el resultado es ambiguo (timeout, 5xx, respuesta sin id): el aviso queda `incierto`. Solo se reintenta, con espera creciente y un máximo de intentos, un error que garantiza que no se envió. |
| AVI-13 | El asistente DEBE espaciar los envíos (con jitter) y respetar topes por número y por sistema en 24 h; lo que no cabe espera hasta `caducidad_h` y luego queda `fallido` (`vencido`). Demasiados avisos pendientes para un número → `429`. |
| AVI-14 | El historial de la conversación DEBE recibir solo un texto mínimo generado por el asistente (tipo y `contexto.ref`); NUNCA texto libre del sistema ni de terceros. El WhatsApp sí lleva el `texto` completo. |
| AVI-15 | Los logs NO DEBEN incluir el `texto` ni tokens, y de `wa_id` solo los últimos 4 dígitos. El `texto` se borra de la base al terminar el envío. |
| AVI-16 | Un aviso entregado NO DEBE contar como uso del vínculo (no renueva su caducidad de 30 días). |

## 2. Token de avisos

- Secreto **nuevo y distinto** (`openssl rand -hex 32`), cargado por el operador en el panel del asistente (secretos
  `token_avisos` y, durante una rotación, `token_avisos_anterior`). Sin él no se aceptan avisos. Va en el entorno del
  sistema (sugerido `STMGIS_AVISOS_TOKEN`), nunca en el repositorio.
- Viaja como `Authorization: Bearer <token_avisos>` y `Content-Type: application/json`.
- **Rotación sin corte**: el operador mueve el actual a `token_avisos_anterior` y carga el nuevo como `token_avisos`; el
  sistema pasa a usar el nuevo; después se borra el anterior.
- A diferencia del token de canal, este token **entra** al asistente: cambiar la `base_url` del sistema no lo borra.

## 3. `POST /sistemas/{sistema_id}/avisos`

```json
{
  "id_evento": "refact:1234:7",
  "tipo": "refacturacion_pendiente",
  "destinatario": { "usuario_ref": "7", "wa_id": "59899123456" },
  "texto": "Entró la factura F-1234 de ACME SA por $ 12.340. ...",
  "contexto": { "ref": "F-1234", "comprobante_id": 1234 },
  "adjunto": null
}
```

| Campo | Regla |
|---|---|
| `id_evento` | `^[A-Za-z0-9._:-]{1,128}$`. Único por sistema. |
| `tipo` | `^[a-z][a-z0-9_]{0,63}$`, dentro de la lista permitida del sistema. |
| `destinatario.usuario_ref` | El `sub` del usuario en el sistema (1–256 caracteres). Debe ser el del vínculo de `wa_id`. |
| `destinatario.wa_id` | 8–15 dígitos, texto. |
| `texto` | Obligatorio, 1–`max_texto` caracteres. Plantilla del sistema, texto plano. |
| `contexto.ref` | `^[A-Za-z0-9._:-]{1,40}$`. Es lo único del contexto que queda en el historial. |
| `contexto.comprobante_id` | Opcional, opaco: el asistente no lo guarda ni lo usa. |
| `adjunto` | `null` (por ahora). |

No se admiten campos desconocidos (`422`).

### 3.1 Respuestas

`202` (aceptado, nuevo) y `200` (repetido idéntico) llevan el mismo cuerpo:

```json
{ "id_evento": "refact:1234:7", "tipo": "refacturacion_pendiente", "estado": "pendiente", "intentos": 0,
  "error": null, "creado_en": "2026-11-09T15:00:00+00:00", "actualizado_en": "...", "enviado_en": null }
```

| Código | Cuándo |
|---|---|
| `202` | Aviso nuevo persistido (`estado: pendiente`). |
| `200` | `id_evento` ya existente con el mismo contenido: el estado guardado. No se vuelve a validar el vínculo. |
| `409` `id_evento_conflicto` | `id_evento` ya existente con contenido distinto. |
| `403` `no_autorizado` | Credencial ausente o inválida, sistema desconocido, deshabilitado o sin avisos (indistinguibles). |
| `413` `cuerpo_demasiado_grande` | Cuerpo > 16 KB. |
| `422` `solicitud_invalida` | Cuerpo mal formado o con campos fuera de formato; `campos` lista los nombres (nunca los valores). |
| `422` `tipo_no_permitido` / `texto_demasiado_largo` / `adjunto_no_soportado` | Ver AVI-04, AVI-05, AVI-06. |
| `422` `destinatario_invalido` | `wa_id` sin vínculo activo y vigente, o `usuario_ref` que no es el del vínculo. |
| `429` `demasiados_pendientes` | Demasiados avisos en cola para ese número. Reintentar más tarde (`Retry-After`). |
| `503` | Sin base de datos. |

El hash que decide `200` / `409` se calcula sobre el contenido completo, normalizado (no importa el orden de las
claves ni los espacios). Reintentar un `id_evento` más allá de la retención del sistema (30 días por defecto) se
trataría como nuevo: no lo hagas.

## 4. `GET /sistemas/{sistema_id}/avisos/{id_evento}`

`200` con el mismo cuerpo de §3.1 o `404 aviso_inexistente`. Sin el texto. `estado`:

| Estado | Significado |
|---|---|
| `pendiente` | Aceptado, a la espera de salir (espaciado, topes o reintento tras un error seguro). |
| `enviando` | Un worker lo tiene y está llamando al canal. |
| `enviado` | El canal aceptó el mensaje (no implica lectura; el estado de entrega llega por el webhook del canal). |
| `fallido` | No salió y no volverá a intentarse. `error`: `vencido`, `vinculo_no_vigente`, `avisos_deshabilitados`, `canal_no_disponible` o `no_enviado:<http>` tras agotar los reintentos. |
| `incierto` | Pudo haber salido (timeout, 5xx, respuesta ambigua, proceso caído a mitad del envío). **No se reintenta.** Decide el sistema: reenviar con otro `id_evento` o dejarlo. |

## 5. Entrega (lo que hace el asistente)

1. Un worker toma el aviso más viejo vencido de cada sistema con `FOR UPDATE SKIP LOCKED` y lo marca `enviando` con un
   lease antes de llamar al canal. Un `enviando` con el lease vencido (el proceso cayó) pasa a `incierto`.
2. Espera entre envíos de un mismo sistema (`pausa_min_s`–`pausa_max_s`, con jitter) y respeta `tope_diario_numero` y
   `tope_diario_sistema` (ventana móvil de 24 h). El texto sale tal cual.
3. Resultado: éxito → `enviado`; el canal lo rechazó antes de enviar → `pendiente` con espera creciente (hasta 5
   intentos, luego `fallido`); cualquier otra cosa → `incierto`.
4. Tras `enviado`, deja en la conversación del usuario un mensaje del asistente como «Aviso enviado: refacturación
   pendiente, ref F-1234». La fuente de verdad de lo pendiente es el sistema (una tool de lectura propia): el historial
   se recorta y es solo una pista para que el usuario pueda contestar «sí, esa».

## 6. Casos a verificar

- **V1** (AVI-01, AVI-02, AVI-03) Sin `Authorization`, con un token cualquiera o con el **token de canal** → `403`, mismo cuerpo que para un sistema inexistente o sin avisos.
- **V2** (AVI-02) Token actual y token anterior aceptados; tras retirar el anterior, `403`.
- **V3** (AVI-03, AVI-08) Token de un sistema en la ruta de otro → `403`; número vinculado solo en otro sistema → `422`.
- **V4** (AVI-08) Número no vinculado, vínculo revocado, caducado (30 días sin uso o 90 desde el alta) o `usuario_ref` ajeno → `422 destinatario_invalido`.
- **V5** (AVI-07) `wa_id` de 7 o 16 dígitos, con `+`, con espacios o numérico → `422`.
- **V6** (AVI-04, AVI-05, AVI-06) Cuerpo de 20 KB → `413`; `texto` demasiado largo, `tipo` desconocido o `adjunto` no nulo → `422`.
- **V7** (AVI-09) Mismo aviso dos veces → `202` y luego `200`; mismo `id_evento` con otro texto → `409`.
- **V8** (AVI-10) Reiniciar el asistente tras el `202` y antes del envío: el aviso sale igualmente.
- **V9** (AVI-12) Timeout del canal → `incierto`, un solo intento; error 4xx del canal → reintento con espera y luego `enviado` o `fallido`.
- **V10** (AVI-13) Superado el tope diario por número, el siguiente aviso queda `pendiente`; con muchos pendientes, `429`.
- **V11** (AVI-14) Tras enviar un aviso con un `texto` hostil, el historial solo contiene «Aviso enviado: …, ref …».
- **V12** (AVI-11) Enviar un aviso no dispara ninguna llamada al modelo ni a las tools del sistema.
- **V13** (AVI-15) Los logs del asistente no contienen el `texto` ni el `wa_id` completo.

## 7. Cómo implementarlo (pasos para el sistema)

1. Pide al operador que habilite `avisos` en tu sistema, el `token_avisos` y, si hace falta, ampliar `tipos`.
2. Guarda tus avisos en una tabla propia (outbox) en la misma transacción que el hecho de negocio, con un `id_evento`
   estable por hecho y destinatario.
3. Un proceso tuyo envía lo pendiente con `POST` y reintenta con el **mismo** `id_evento` ante timeout, `5xx` o `429`.
   `200`/`202` = aceptado; `409`/`422` = error tuyo, no reintentar igual.
4. Para saber si llegó, consulta el `GET`. Ante `incierto`, decide con criterio de negocio (no se reenvía solo).
5. Arma el `texto` con una plantilla fija (sin instrucciones para el asistente).
6. Verifica con los casos de §6.
