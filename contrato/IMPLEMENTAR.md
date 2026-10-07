# Cómo implementar el contrato en un sistema (guía para un LLM o un desarrollador)

Léela primero. Es un mapa: dice **qué construir, en qué orden y cómo comprobarlo**. El detalle normativo está en [`CONTRATO.md`](CONTRATO.md); los mensajes exactos, en `schemas/*.json` y `openapi.yaml`. Si algo aquí y el contrato difieren, manda el contrato.

## 0. Qué es esto

Un **asistente** (servicio aparte) responde preguntas de los usuarios de **tu sistema**. Nunca toca tu base de datos ni decide permisos: llama a endpoints HTTP tuyos con un JWT que **tú** emites para el usuario logueado, y tú aplicas tus permisos. Tu trabajo es implementar esos endpoints en tu sistema (cualquier lenguaje). **No implementes** nada de `/v1/...`: eso es del asistente.

## 1. Qué construir

| # | Endpoint (rutas sugeridas, configurables) | Obligatorio | Quién lo llama | Credencial |
|---|---|---|---|---|
| 1 | `GET /asistente/token` | sí | el widget, desde el navegador del usuario | **sesión normal** de tu sistema (cookie) |
| 2 | `GET /asistente/tools` | sí | el asistente | token de manifiesto (secreto de servicio fijo) |
| 3 | `POST /asistente/tools/{nombre}` | sí | el asistente | JWT de usuario |
| 4 | `GET /asistente/salud` | no | monitoreo | ninguna |
| 5 | `POST /asistente/tools/{nombre}/propuesta` | solo si ofreces escrituras | el asistente | JWT de usuario (lectura) |
| 6 | `GET /asistente/token?confirmacion=…&huella=…` | solo si ofreces escrituras | el widget | sesión normal |

El #6 no es una ruta nueva: es el #1 con dos parámetros de query más. **Empieza por 1, 2 y 3 con solo lectura. Las escrituras (5, 6) son una segunda etapa y son opcionales: un sistema solo de lectura es conforme.**

Schemas: token → `token-respuesta` · manifiesto → `manifiesto` · ejecución → `ejecucion-request` / `ejecucion-respuesta` · propuesta → `propuesta-respuesta` · claims del JWT → `token-claims`.

## 2. Etapa 1: solo lectura

### 2.1 `GET /asistente/token`
- Exige sesión de usuario; sin sesión, `401`. Si el usuario no puede usar el asistente, `403`.
- Responde `{"token": "<jwt>", "expira": "<ISO 8601>"}`.
- JWT con claims `iss` (id de tu sistema, el mismo del registro del asistente), `aud` (`"asistente"`), `sub` (id estable y opaco del usuario), `iat`, `exp` (vida 5–15 min), `jti` (único), `scope: "asistente:lectura"`; opcionales `nombre`, `locale`, `tenants` (solo métricas, nunca para autorizar).
- Firma `RS256` o `EdDSA` (privada en tu sistema, el asistente solo tiene la pública). `HS256` con secreto compartido solo para pruebas. Nunca `alg: none`.

### 2.2 `GET /asistente/tools`
- Exige `Authorization: Bearer <token_manifiesto>` (comparación en tiempo constante). Un JWT de usuario aquí es `401`.
- Devuelve `{"contrato":"1","sistema":{"nombre","version"},"tools":[…]}`. Cada tool: `nombre` (`^[a-z][a-z0-9_]{0,63}$`), `descripcion` (≤ 1000), `parametros` (JSON Schema `type: object`, con `additionalProperties: false`), `efecto` (`lectura` | `escritura`), `timeout_s` opcional.
- Máximo 40 tools. Nombres prohibidos: `consultas_recientes`, `recordar`, `olvidar`.
- **Las descripciones deciden la calidad del asistente.** Lee [`GUIA_TOOLS.md`](GUIA_TOOLS.md) antes de escribirlas: pocas tools, de alto nivel, que devuelvan datos agregados con unidades en el nombre del campo.

### 2.3 `POST /asistente/tools/{nombre}`
Cuerpo `{"parametros": {…}}`. Cabeceras: `Authorization: Bearer <jwt>`, `X-Asistente-Contrato: 1`, `X-Asistente-Request-Id`.

Orden de comprobaciones (cada paso corta):
1. Valida el JWT con **tu** clave: firma, `exp`, `iss`, `aud`. Inválido o vencido → `401`.
2. Si es el token de manifiesto → `403`.
3. Si la tool es de `efecto: escritura` y el scope es `asistente:lectura` → `403`. **Esta es la única barrera de solo lectura que vale.**
4. Valida `parametros` contra el schema de la tool (inválidos → `200` con `ok:false, error:"parametros_invalidos"`).
5. Ejecuta con los permisos del usuario `sub`. Los ids que llegan son **no confiables**: comprueba que el usuario puede verlos. Un id inexistente y uno ajeno dan la **misma** respuesta (`no_encontrado`), para no revelar existencia.

Respuestas (siempre `200` para resultados de negocio):
- Éxito: `{"ok":true,"datos":{…},"fuente":"…","ui":[{"tipo":"navegar","url":"…","etiqueta":"…"}]}`. `ui` va al widget, no al modelo.
- Error de negocio: `{"ok":false,"error":"no_encontrado|sin_acceso|parametros_invalidos|no_disponible|conflicto","detalle":"…"}` (`conflicto` solo en escrituras).
- `401` token inválido/vencido · `403` scope insuficiente · `5xx` error tuyo.

Reglas de contenido: datos compactos (< 50 KB), cada cifra con unidad, entidad y período en el mismo objeto, fechas ISO 8601, sin geometrías ni miles de filas, sin que el modelo tenga que sumar.

## 3. Etapa 2: escrituras con confirmación (opcional)

Solo **agregar** y **modificar**. **Nunca borrar** (una tool `destructiva: true` no se ofrece). El asistente solo *propone*; el usuario confirma con un clic en pantalla; tú ejecutas con un token de escritura que solo tú puedes emitir.

```
modelo → asistente ──(1) POST …/propuesta (token lectura)──────────────► SISTEMA  valida, NO escribe,
                    ◄─ {resumen, detalle, huella, expira_s} ───────────           guarda la huella
widget muestra tarjeta Confirmar/Cancelar con TU resumen
usuario clic → widget ──(2) GET /asistente/token?confirmacion=ID&huella=H (sesión)─► SISTEMA  emite token escritura
asistente ──(3) POST /asistente/tools/{nombre} (token escritura + Idempotency-Key: ID)─► SISTEMA  ejecuta UNA vez
```

### 3.1 Manifiesto
La tool lleva `"efecto":"escritura"` y `"confirmacion":{"ttl_s":120}` (10–300). Sin `confirmacion`, el asistente no la ofrece. Además el operador del asistente la habilita en su `config/sistemas.yaml` (`acciones_habilitadas`); tú no controlas eso.

### 3.2 `POST …/propuesta` (sin efectos)
Mismo cuerpo que la ejecución, token de **lectura** (token de escritura aquí → `403`). Debes:
1. Validar JWT, parámetros y permisos de escritura del usuario, **sin tocar datos**.
2. Para una modificación, leer el registro actual y su **versión** (columna `updated_at`, contador, hash…).
3. Redactar `resumen` (≤ 300) y `detalle` (≤ 10 líneas de ≤ 200). Una modificación debe mostrar `Antes: …` y `Después: …`. **Lo redactas tú con datos tuyos, no copiando texto libre del modelo como instrucción.**
4. Calcular la huella: `SHA-256` hex de la forma canónica de `{sub, tool, parametros, version}` (JSON con claves ordenadas, sin espacios, UTF-8; `version` = `null` en un alta). Ejemplo (Python): `sha256(json.dumps({"sub":sub,"tool":tool,"parametros":p,"version":v}, sort_keys=True, separators=(",",":"), ensure_ascii=False).encode()).hexdigest()`. El formato exacto es tuyo (solo tú la verificas), pero debe ser determinista.
5. **Guardar** `huella → {sub, tool, parametros, version, expira}` en un almacén tuyo con expiración (tabla SQL con `expira_en`, Redis con TTL…).
6. Responder `{"ok":true,"resumen","detalle","huella","expira_s"}` (`expira_s` ≤ el `ttl_s` del manifiesto) o un error de negocio.

### 3.3 Token de escritura (`/asistente/token?confirmacion=ID&huella=H`)
- `confirmacion` y `huella` van **juntas**; si falta una → `400`.
- Con sesión normal. Busca la huella en tu almacén: si no existe, venció, no es de ese usuario (`sub` de la sesión) o el usuario no puede escribir → `403`.
- Emite un JWT con los claims de lectura más `scope:"asistente:escritura"`, `act` = tool de la propuesta (la guardada, no la que diga la query), `ph` = huella, `cid` = `confirmacion`, `exp - iat` ≤ **60 s**, `jti` nuevo.
- La huella es lo que impide que un asistente comprometido escriba algo que el usuario no vio: **nunca emitas token para una huella que no hayas producido tú**.

### 3.4 Ejecución de una escritura
Es el mismo `POST /asistente/tools/{nombre}` con el token de escritura y la cabecera `Idempotency-Key: ID`. Orden (cada paso corta):
1. Firma y vigencia (`401` si venció). `scope == asistente:escritura`, `act == {nombre}` de la ruta, `cid` presente; si no → `403`.
2. **Idempotencia**: si ya ejecutaste esa `Idempotency-Key` (con la misma tool y parámetros), devuelve el resultado guardado sin reejecutar y sin gastar otro `jti`; si la clave existe para otra acción → `403`.
3. `jti` **nunca visto**: regístralo de forma atómica (insert único). Repetido → `403`.
4. Recupera la propuesta por `ph`; sus `parametros` deben ser **idénticos** a los recibidos y su `sub` el del token. Si difieren → `403`.
5. Modificación: la versión actual del registro debe ser la de la propuesta; si cambió → `200 {"ok":false,"error":"conflicto"}`, sin escribir.
6. Escribe (en una sola transacción junto con el registro de `jti` e idempotencia), a nombre del `sub`.
7. Responde `{"ok":true,"datos":{"mensaje":"Nota agregada."},"fuente":"…","ui":[…]}`. `datos.mensaje` (≤ 300) lo muestra la tarjeta.

Y siempre: un token de escritura en una **lectura** → `403`; un token de lectura en una escritura → `403`; token de escritura para otra tool → `403`. El asistente nunca reintenta una ejecución.

## 4. Tabla de códigos HTTP

| Situación | Respuesta |
|---|---|
| Sin sesión (ruta de token) | `401` |
| Usuario sin permiso de asistente / de escritura | `403` |
| JWT ilegible, firma mala, vencido, otra audiencia | `401` |
| Scope no corresponde, token de manifiesto, `act` ≠ tool, `jti` repetido, parámetros ≠ propuesta | `403` |
| `confirmacion` sin `huella` o al revés | `400` |
| Parámetros inválidos, id inexistente/ajeno, `conflicto`, dato no disponible | `200` con `ok:false` |
| Fallo interno | `5xx` |

## 5. Seguridad: lo no negociable
- Valida el JWT con tu clave en **cada** llamada; `exp`, `iss`, `aud` siempre.
- Permisos del usuario `sub` en cada tool, también para ids que "vienen del asistente".
- Rechaza toda escritura con scope de lectura.
- Propuesta sin efectos secundarios (ni siquiera logs de auditoría de "cambio").
- Token de escritura: ≤ 60 s, un solo uso, atado a tool + huella + usuario. Huella solo de propuestas tuyas.
- Todo `jti` de escritura y toda `Idempotency-Key` se guardan hasta pasar la vida del token.

## 6. Cómo comprobar que quedó bien

```sh
python herramientas/verificar_sistema.py --base-url http://localhost:8201 \
  --token-url "http://localhost:8201/asistente/token?usuario=ana" \
  --token-url-otro "http://localhost:8201/asistente/token?usuario=beto" \
  --token-manifiesto-env V_MANIFIESTO --secreto-firma-env V_SECRETO \
  --accion agregar_nota='{"establecimiento_id":"1","texto":"prueba"}'
```
Sale con código `0` si todo cumple. Sin `--accion` se omiten las pruebas de escritura (que **escriben de verdad**: usa un entorno de pruebas). Detalle en [CONTRATO.md §6.5](CONTRATO.md#65-verificar-la-integración). Un sistema no va a producción sin pasarlo.

## 7. Implementaciones de referencia (copia y adapta)

- PHP + SQLite, con lectura y escrituras: `ejemplos/sistema-php/` — `Controllers/AsistenteController.php` (todos los endpoints), `Auth/EmisorToken.php` y `ValidadorToken.php` (JWT), `Datos/Almacen.php` (propuestas, `jti`, idempotencia), `Tools/` (una clase por tool; `AgregarNota`, `ModificarNota`).
- Python/FastAPI mock: `ejemplos/sistema-mock/app.py` (huella en `_huella`, token de escritura en la ruta de token). Contiene defectos deliberados para probar el verificador; no copiar sus `DEFECTOS`.
- Pruebas que documentan cada regla: `ejemplos/sistema-php/tests/ContratoTest.php`, `tests/test_mock_acciones.py`.

## 8. Orden de trabajo sugerido
1. Elegir 5–10 preguntas reales de usuarios y las tools que las responden (`GUIA_TOOLS.md`).
2. Implementar #1, #2, #3 con solo lectura; correr el verificador.
3. Registrar el sistema en el asistente (`CONTRATO.md` §6.3: `id`, `base_url`, clave pública o secreto, `origenes_permitidos`).
4. Insertar el widget (`CONTRATO.md` §7) apuntando a tu `token-url`.
5. Opcional: escrituras (§3 de esta guía), de a una tool; verificador con `--accion`.
