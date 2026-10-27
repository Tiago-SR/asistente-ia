# Canal WhatsApp: cómo implementarlo en un sistema (guía para un LLM o un desarrollador)

Sección **opcional** del contrato (§9 de `CONTRATO.md`). No cambia ningún endpoint existente y no sube la versión
(`"contrato": "1"`). Léelo junto con `CONTRATO.md` §1 (token de usuario) y §8 (acciones con confirmación) e
`IMPLEMENTAR.md`. Este documento define **sólo lo que debe construir el sistema anfitrión**; el webhook de Meta y el
chat viven en el asistente (ver `whatsapp/whatsapp-plan.md`).

## 0. Qué es esto y por qué así

Un usuario del sistema chatea con el asistente por WhatsApp. El asistente sólo ve un número (`wa_id`); **el sistema
decide quién es ese número**. El asistente nunca fabrica identidades ni tokens: pide un token por mensaje al sistema,
y el sistema responde sólo si el número fue vinculado por su dueño desde su sesión web.

Resultado: un asistente comprometido sólo puede obtener tokens de lectura para números que sus dueños vincularon, y
la revocación es local al sistema.

## 1. Qué construir

| Endpoint | Obligatorio | Quién lo llama | Credencial |
|---|---|---|---|
| `POST /asistente/canal/codigo` | sí | el navegador del usuario (pantalla del sistema) | sesión normal del usuario |
| `POST /asistente/canal/vincular` | sí | el asistente | token de canal |
| `POST /asistente/canal/token` | sí | el asistente, en cada mensaje | token de canal |
| Revocar vínculo (pantalla propia, sin ruta fija) | sí | el usuario / un admin | sesión normal |

Más: una tabla de vínculos en el sistema, una pantalla «Vincular WhatsApp» y la credencial de servicio **token de
canal** (§2). Rutas relativas a la `base` del manifiesto, igual que `/asistente/token`.

## 2. Credencial de servicio: token de canal

- Secreto **nuevo y distinto** del token de manifiesto (`openssl rand -hex 32`). No reutilices ninguna otra
  credencial.
- Viaja como `Authorization: Bearer <token_canal>` en los dos endpoints del asistente.
- Compáralo en **tiempo constante** (`hash_equals` / `hmac.compare_digest`). Si falta o no coincide: `403`.
- Rotación sin corte: durante el cambio el sistema acepta el token actual y el anterior (añade el nuevo, cámbialo en el panel del asistente, retira el viejo).
- Va en el entorno del sistema (sugerido `STMGIS_CANAL_TOKEN`), nunca en el repositorio. El asistente lo lee de
  `conector.token_canal_env` en su registro (a implementar en el asistente).

## 3. Vincular un número

### 3.1 `POST /asistente/canal/codigo` (sesión normal del usuario)

Genera un código de **un solo uso** para el usuario autenticado. Respuesta:

```json
{ "codigo": "FST-7K2M9QXD", "expira": "2026-10-26T15:10:00Z" }
```

- Formato: `<PREFIJO>-<8 caracteres>` en base32 sin caracteres ambiguos (sin `0 O 1 I L`). El **prefijo** identifica
  al sistema (p. ej. `FST`) y es opcional: el asistente ya sabe el sistema por la ruta del webhook (`/canal/{sistema_id}/webhook`). Antes se usaba para enrutar el
  mensaje al sistema correcto.
- Vida: 10 minutos. Un código vigente por usuario: pedir otro invalida el anterior.
- Guárdalo **hasheado**, nunca en claro. Permiso: sólo si el usuario puede usar el asistente (mismo criterio que
  `GET /asistente/token`; si no, `403`).
- La pantalla muestra el código con la instrucción: «Envía por WhatsApp al número del asistente:
  `VINCULAR FST-7K2M9QXD`».

### 3.2 `POST /asistente/canal/vincular` (token de canal)

Cuerpo:

```json
{ "canal": "whatsapp", "wa_id": "59899123456", "codigo": "FST-7K2M9QXD" }
```

- `wa_id`: dígitos sin `+`. Valida formato (8–15 dígitos); si no, `400`.
- Respuestas: `200 {"ok": true, "nombre": "Ana"}` si vinculó. `404` si el código no existe, venció, ya se usó o es de
  otro usuario inactivo (**no distingas los casos**). `403` token de canal inválido. `429` si hay demasiados intentos.
- Efecto: consume el código y guarda `wa_id ↔ usuario`. Un `wa_id` pertenece a **un solo usuario**: si ya estaba
  vinculado a otro, el nuevo vínculo lo reemplaza y se avisa al usuario anterior. Un usuario puede tener varios números.
- **Avisa al usuario** por su canal habitual (correo o notificación del sistema): «Se vinculó WhatsApp (…3456). Si no
  fuiste tú, revócalo aquí».
- Antifuerza bruta: máximo 5 intentos fallidos por `wa_id` por hora y un tope global por minuto; tras eso `429`.
- Idempotencia: repetir la misma petición con el mismo `wa_id` ya vinculado al mismo usuario devuelve `200`.

### 3.3 Tabla de vínculos (sugerida)

`canal` (`whatsapp`), `wa_id` (único por canal), `usuario_id`, `creado_en`, `ultimo_uso`, `revocado_en` (nulo si
activo). Índice por `(canal, wa_id)`.

## 4. Pedir un token por mensaje

`POST /asistente/canal/token` (token de canal). Cuerpo para **lectura**:

```json
{ "canal": "whatsapp", "wa_id": "59899123456" }
```

Respuesta `200`, idéntica a `GET /asistente/token` (§1):

```json
{ "token": "<jwt>", "expira": "2026-10-26T15:20:00Z" }
```

- Claims = los de §1 (`iss`, `aud`, `sub`, `iat`, `exp` 5–15 min, `jti`, `scope: asistente:lectura`, `nombre`,
  `locale`) **más** `canal: "whatsapp"`. Mismas reglas de firma (RS256/EdDSA; nunca `alg: none`).
- El `sub` es el del usuario vinculado: el asistente construye su identidad `(sistema_id, usuario_ref)` de ahí.
- Actualiza `ultimo_uso` en cada emisión.
- **Sin vínculo activo, vínculo caducado, revocado o usuario inactivo: `404`** (el asistente calla; no des pistas).
  `403` si el token de canal es inválido. Límite de emisión por `wa_id` (p. ej. 30/min) → `429`.
- **Caducidad del vínculo**: 90 días desde `creado_en` (se renueva desde la web) o 30 días sin `ultimo_uso`. Pasado
  eso, `404` hasta que el usuario vuelva a vincular.

### 4.1 Token de escritura por el canal (§8)

Mismo endpoint, con la confirmación de §8.3 en el cuerpo en vez de en la query:

```json
{ "canal": "whatsapp", "wa_id": "59899123456", "confirmacion": "<id>", "huella": "<huella>" }
```

Respuesta y claims como el token de escritura de §8.3 (`scope: asistente:escritura`, `exp` ≤ 60 s, `jti` de un solo
uso, `act`, `ph`, `cid`) **más** `canal: "whatsapp"`. Reglas adicionales del canal:

1. Emite el token **sólo si** la `huella` salió de una propuesta (§8.2) del **mismo usuario** hecha con un token que
   llevaba `canal: "whatsapp"`. Una propuesta del widget web no puede confirmarse por este canal, ni al revés.
2. **Nunca** emitas token de escritura por el canal para tools destructivas (borrar), aunque el manifiesto las
   marque como acciones. Responde `403`.
3. El resto de la ejecución (`Idempotency-Key`, `jti` único, parámetros = propuesta, `conflicto`, consumir la
   propuesta en la misma transacción) no cambia.
4. Registra en auditoría que la acción vino por el canal.

## 5. Revocación y avisos

- Pantalla del sistema: lista de números vinculados (últimos 4 dígitos, fecha, último uso) con botón «Revocar».
  Revocar pone `revocado_en`; desde ese momento `/canal/token` da `404`.
- Un admin puede revocar los vínculos de un usuario (p. ej. al darlo de baja: **dar de baja al usuario debe dejar
  inactivos sus vínculos**).
- Avisa al usuario en cada alta y revocación.

## 6. Seguridad: lo no negociable

- El token de canal es una credencial de servicio **separada**; sin ella ni `/vincular` ni `/token` responden.
- Nunca devuelvas un token por un `wa_id` no vinculado, y nunca distingas en la respuesta entre «no existe», «caducó»
  y «revocado».
- Códigos de un solo uso, hasheados, con vida corta y límite de intentos. Sin el código, un número no se vincula.
- El `wa_id` lo afirma el asistente tras validar la firma de Meta; el sistema **no** prueba que el número sea del
  usuario salvo por el código enviado desde su sesión. Por eso el vínculo caduca y es revocable.
- Riesgo residual aceptado: SIM swap o número reciclado sobre un número vinculado da acceso de lectura hasta que el
  vínculo caduca o se revoca. Mitiga con la caducidad, el aviso al usuario y la revocación inmediata.
- No loguees `wa_id` completos, códigos ni tokens. Sólo últimos 4 dígitos.
- La escritura por este canal es opt-in del operador en el asistente (`canal_mensajeria.acciones`); aun así el sistema
  aplica las reglas de §4.1.

## 7. Códigos HTTP

| Código | Cuándo |
|---|---|
| `200` | Vinculado / token emitido |
| `400` | `wa_id` o cuerpo mal formado |
| `403` | Token de canal ausente o inválido; token de escritura para tool destructiva |
| `404` | Código inválido/vencido/usado; sin vínculo activo, caducado, revocado o usuario inactivo |
| `429` | Demasiados intentos o emisiones |

El cuerpo de error sigue lo que ya use tu sistema (el contrato no fija uno para `4xx`).

## 8. Cómo implementarlo (pasos)

1. Crea la tabla de vínculos y la de códigos (hash, `usuario_id`, `expira`, `usado_en`).
2. Genera y guarda el token de canal en el entorno.
3. Implementa `POST /asistente/canal/codigo` con la sesión normal y la pantalla «Vincular WhatsApp».
4. Implementa `/vincular` y `/token` reutilizando tu emisor de tokens de §1/§8 (añade el claim `canal`).
5. Añade la pantalla de revocación, el aviso al usuario y la baja de vínculos al dar de baja un usuario.
6. Verifica con los casos de abajo.

Referencias de implementación: `ejemplos/sistema-mock/app.py` (`emitir_token`, `_claims_de`, ejecución de acciones) y
`ejemplos/sistema-php/src/Auth/EmisorToken.php` (`emitir`, `emitirEscritura`) +
`Controllers/AsistenteController.php` (`token`, `ejecutarAccion`). El claim `canal` se añade en el mismo punto donde
hoy se arma `scope`.

## 9. Casos a verificar

- `/vincular` con código bueno → `200`; repetirlo con el mismo código → `404` (ya usado).
- Código vencido, ajeno o inexistente → `404` indistinguible.
- 6 intentos fallidos del mismo `wa_id` en una hora → `429`.
- `/token` de número vinculado → token con `canal: "whatsapp"` y `scope: asistente:lectura`.
- `/token` sin vínculo, tras revocar, tras 30 días sin uso o con usuario inactivo → `404`.
- Sin `Authorization` o con token de canal erróneo → `403`.
- Token de escritura con una `huella` de una propuesta hecha desde el widget → rechazado.
- Token de escritura para una tool destructiva → `403`.
- Dar de baja al usuario → `/token` pasa a `404`.
