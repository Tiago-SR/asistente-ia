# Fase 5: acciones con confirmación (diseño, sin implementar)

Estado: **implementado en servicio, mock y widget (2026-10-05)**; el contrato quedó en la sección 8 de `contrato/CONTRATO.md`. Este documento conserva el razonamiento y las decisiones. Desviaciones respecto al borrador: el id de confirmación no se firma (fila en BD + id aleatorio); el widget no restaura la tarjeta pendiente tras recargar; faltan la referencia PHP, el verificador y los evals de acciones (§9, pasos 2, 1 y 6). Parte de lo que ya fija el README («Estado y pendientes», Fase 5) y los principios de seguridad vigentes; propone cómo cumplirlo y deja marcadas las decisiones que corresponden al dueño del producto.

## 1. Qué se quiere y qué no

**Se quiere:** que el usuario pueda pedir en lenguaje natural una acción acotada («anotá en el lote 3 que hubo helada») y que ocurra solo si el propio usuario la confirma en pantalla.

**No se quiere (límites de esta fase):**
- Acciones masivas, encadenadas o en lote. Una confirmación = una acción.
- Que el modelo, o cualquier texto que el modelo haya leído (resultados de tools), pueda causar una escritura sin un clic humano.
- Confirmar por voz. Ver §6.
- Acciones destructivas o irreversibles en la primera versión.

## 2. Principios (derivan de los vigentes)

1. **La autoridad es el sistema, no el asistente.** Hoy la capa de solo lectura que vale es la del sistema (rechaza escrituras con scope `asistente:lectura`). La escritura sigue igual: el sistema solo ejecuta si recibe un token de escritura que **él mismo emitió** para esa acción concreta. Si el asistente se compromete, no puede fabricarlo.
2. **Lo que el usuario confirma lo redacta el sistema, no el modelo.** El resumen de la confirmación sale de una llamada de «propuesta» al sistema, no del texto del modelo. Así una inyección de prompt no puede mostrar «Anotar observación» y ejecutar otra cosa.
3. **El clic humano es la prueba de intención.** La confirmación se da en el widget, con la sesión normal del usuario en el sistema; no por texto del chat ni por voz.
4. **Un solo uso, vida corta, atado a los parámetros.** Una confirmación no se puede reutilizar, ni cambiar sus parámetros, ni ejecutar tarde.
5. **Todo auditado**, por `(sistema_id, usuario_ref)` como el resto.
6. **Apagado por defecto**, habilitado por sistema y por tool.

## 3. Flujo

```
Usuario ──texto──▶ Asistente ──LLM propone tool de escritura (nombre + parámetros)
                      │
                      │ 1. valida parámetros contra el JSON Schema
                      │ 2. POST {base}/asistente/tools/{nombre}/propuesta   (token de LECTURA)
                      ▼
                   Sistema: valida y comprueba permisos, SIN efectos
                      │  devuelve { ok, resumen, detalle[], expira_s, huella }
                      ▼
                   Asistente: guarda la propuesta (estado «pendiente»), emite
                      evento SSE `confirmacion` { id, resumen, detalle, expira }
                      │  al modelo le devuelve: «pendiente de confirmación del
                      │  usuario; no afirmes que se hizo» y el turno termina
                      ▼
Widget muestra tarjeta «Confirmar / Cancelar» con el resumen del SISTEMA
   Confirmar:
     a. Widget → sistema (token-url con ?confirmacion=<id>&huella=<h>, sesión del
        usuario): el sistema comprueba su propia propuesta y emite un token
        `asistente:escritura` (ver §4.3)
     b. Widget → Asistente POST /v1/confirmaciones/{id}/confirmar con ese token
     c. Asistente → sistema POST /asistente/tools/{nombre} con ese token
        (Idempotency-Key = id de confirmación); registra el resultado
     d. Widget muestra el resultado; el asistente añade al historial un mensaje
        de sistema con el resultado (para que el modelo sepa qué pasó)
   Cancelar: POST /v1/confirmaciones/{id}/cancelar; no se llama al sistema.
```

Puntos finos:
- El token de escritura **no lo pide el asistente** con el token de lectura (eso permitiría que un asistente comprometido se escale). Lo pide el navegador del usuario al endpoint de token del sistema, igual que hoy pide el token de lectura, con su sesión.
- Si el sistema no implementa `propuesta`, la tool de escritura no se expone. No se ofrece «confirmar a ciegas».
- Si la propuesta falla (`sin_acceso`, `parametros_invalidos`), eso va al modelo como un resultado normal de tool; no hay tarjeta.
- Máximo **una confirmación pendiente por conversación**; una nueva propuesta cancela la anterior.

## 4. Cambios por componente

### 4.1 Contrato (sería v1.1, aditivo)

Manifiesto: las tools con `efecto: "escritura"` ya existen en el esquema; hoy solo se filtran. Campos opcionales nuevos:

| Campo | Para qué |
|---|---|
| `confirmacion.requerida` | siempre `true` para escritura (campo explícito por si más adelante hay efectos «sin confirmar» como marcar leído; **no** se habilita en esta fase) |
| `confirmacion.ttl_s` | vida de la propuesta (por defecto 120, máx. 300) |
| `reversible_con` | nombre de la tool que deshace esta, si existe (informativo; la UI de deshacer es opcional, §7) |

Endpoints nuevos del sistema:
- `POST /asistente/tools/{nombre}/propuesta` — mismo cuerpo que la ejecución, **token de lectura**. Responde `{ ok, resumen, detalle?, huella, expira_s }`. Obligatorio sin efectos secundarios: el verificador lo comprueba.
- La ejecución `POST /asistente/tools/{nombre}` para escrituras exige scope `asistente:escritura` (hoy rechaza escrituras con cualquier token del asistente).
- Emisión del token de escritura por el endpoint de token existente (query `confirmacion`, `huella`).

`huella` = SHA-256 de la forma canónica de `{tool, parametros, sub}` calculada por el sistema; el asistente la guarda y la compara, el sistema la vuelve a calcular al emitir el token y al ejecutar.

### 4.2 Registro de sistemas (`config/sistemas.yaml`)

Nueva lista por sistema, vacía por defecto: `acciones_habilitadas: [nombre_tool, …]`. Una tool de escritura del manifiesto que no esté en la lista sigue sin exponerse al modelo. Así el operador del asistente (no solo el sistema) decide qué acciones existen.

### 4.3 Token de escritura

JWT firmado por el sistema (misma clave y algoritmo), emitido solo con sesión válida y una propuesta suya vigente:

| Claim | Valor |
|---|---|
| `iss`, `aud`, `sub`, `iat`, `jti` | como el de lectura |
| `exp` | **≤ 60 s** |
| `scope` | `asistente:escritura` |
| `act` | nombre de la tool (solo sirve para esa) |
| `ph` | huella de los parámetros (solo sirve para esos) |
| `cid` | id de la confirmación |

El sistema, al ejecutar: valida firma, `act` = ruta, `ph` = huella recalculada, `jti` no usado antes (un solo uso) y `Idempotency-Key` repetido → devuelve el resultado anterior sin reejecutar. El asistente no necesita aceptar este scope en su `Autenticador` para sus propios endpoints de chat: `SCOPE_LECTURA` sigue siendo el único válido para `/v1/chat`, y el endpoint de confirmar verifica el token de escritura aparte (misma firma, scope distinto, `cid` = id de la ruta).

### 4.4 Asistente (servicio)

- `core/ports.py`: el puerto `Conector` gana `proponer(...)` y `ejecutar_confirmada(...)`; `core/` sigue sin importar `api/`, `sistemas/` ni `store/` (lo vigila `test_arquitectura.py`).
- `core/agent.py`: si el modelo llama una tool de escritura, no la ejecuta: llama a `proponer`, emite `confirmacion` y **corta el turno** tras devolver al modelo el resultado «pendiente». No se queda esperando.
- `core/events.py`: evento `CONFIRMACION`.
- Prompt base: nueva regla («una escritura nunca se hace en el turno; di que pediste confirmación y espera»). Es cambio de la capa base: sube su versión.
- `store/`: tabla `acciones` (migración nueva): `id` (uuid, 128 bits aleatorios, **no adivinable**), `sistema_id`, `usuario_ref`, `conversacion_id`, `tool`, `parametros`, `huella`, `resumen`, `estado` (`pendiente` · `confirmada` · `ejecutada` · `fallida` · `cancelada` · `expirada`), `creada`, `expira`, `decidida`, `jti_confirmacion`, resultado resumido (`ok`, `error`, `status_http`), mismas reglas de aislamiento: toda consulta filtra por `(sistema_id, usuario_ref)`. Transición pendiente→confirmada con `UPDATE … WHERE estado='pendiente' AND expira > now()` para que dos clics concurrentes no ejecuten dos veces.
- `api/`: `POST /v1/confirmaciones/{id}/confirmar` y `/cancelar`, con la verificación de `Origin` y de sistema del token como el resto. Con id ajeno o inexistente, `404` igual que `conversaciones`.
- Purga: la retención de `acciones` es una decisión aparte (§8).
- Límites: cuota de propuestas por usuario/hora y tope de confirmaciones pendientes, para que un modelo en bucle no inunde de tarjetas.

El «id firmado» del README: con la fila en la base y un id aleatorio de 128 bits, una firma HMAC adicional no suma seguridad (el estado en BD es la autoridad y es de un solo uso). Se propone **no** firmarlo salvo que se quiera un camino sin estado; es una desviación menor del texto del README, a confirmar.

### 4.5 Widget

- Tarjeta de confirmación inline en el chat (resumen y detalle del sistema, texto plano construido con nodos DOM como todo lo demás, nunca `innerHTML`), botones **Confirmar** y **Cancelar**, cuenta regresiva hasta `expira`, y estado final (hecho / falló / cancelada / venció).
- Los botones se activan solo con interacción real (`event.isTrusted`) y el widget no los dispara por ningún evento de la página anfitriona.
- Un solo `confirmacion` visible activo; si llega otro, el anterior pasa a «reemplazada».
- Evento `asistente:accion` / nuevo `asistente:confirmacion` hacia el anfitrión (para que el sistema pueda refrescar su pantalla tras una acción).

## 5. Qué defiende cada capa (modelo de amenazas)

| Amenaza | Defensa |
|---|---|
| El modelo, engañado por un dato de tool, propone una acción | Solo propone: nada se ejecuta sin clic; el resumen lo escribe el sistema |
| El modelo cambia los parámetros entre la propuesta y la ejecución | `huella` atada al token; el sistema la recalcula |
| Un asistente comprometido intenta ejecutar solo | No tiene credencial de escritura: el token lo emite el sistema contra la sesión del usuario |
| Replay de una confirmación | `jti` de un solo uso, `exp` ≤ 60 s, `Idempotency-Key`, estado atómico en BD |
| Un usuario confirma la acción de otro | id aleatorio, `404` ajeno, filtro por `(sistema_id, usuario_ref)` y `sub` del token de escritura |
| Script de la página anfitriona pulsa «Confirmar» | `isTrusted` (mitiga, no es una garantía: el anfitrión ya es de confianza para el token) |
| Doble clic / dos pestañas | UPDATE condicional; la segunda recibe el resultado de la primera |
| Texto del modelo que afirma «ya lo hice» sin haberlo hecho | Regla del prompt y el resultado «pendiente»; la fuente de verdad es el estado de la acción mostrado por el widget |

## 6. Voz y manos libres

**Propuesta: ninguna acción se confirma por voz en esta fase.** «Enviar» en manos libres confirma un *mensaje*; una escritura con efectos en el sistema merece un gesto distinto y deliberado. Además, con parlantes o con el micrófono abierto, el riesgo de una confirmación espuria es mayor, y la transcripción de Google puede equivocar «cancelar» por «confirmar». En manos libres, si el modelo propone una acción, el asistente la lee en voz alta («Te pido confirmar en pantalla: …») y la tarjeta espera el clic. Cambiable después, con una decisión explícita del dueño.

## 7. Reversibilidad

Opcional y fuera de la primera entrega. Si una tool declara `reversible_con`, tras ejecutarse la tarjeta puede ofrecer **Deshacer** (misma maquinaria: propuesta + confirmación + token propio). No se promete en el contrato: la reversibilidad real la define el sistema.

## 8. Decisiones del dueño (2026-10-05)

1. **Acciones de la primera versión: agregar y modificar; borrar queda para más adelante.** Concretamente (supuesto de ejemplo, el sistema real las nombrará): *agregar una nota/observación* a un lote o establecimiento y *modificar una nota* ya existente. Modificar es más delicado que agregar (pisa datos): la propuesta debe mostrar el valor anterior y el nuevo en `detalle`, y el sistema debe rechazar la modificación si el dato cambió desde la propuesta (`huella` incluye la versión del registro). Una tool de borrado no se declara ni se habilita en esta fase: el asistente rechaza `acciones_habilitadas` que incluyan una tool marcada como destructiva.
2. **En manos libres también se confirma en pantalla** (§6 queda como decisión firme). El asistente lee la propuesta en voz alta y espera el clic.
3. **Retención de la auditoría de acciones: 30 días**, igual que la de tools. Si un cliente exige más, se guarda del lado del sistema, que es quien tiene el registro de negocio.
4. **Responsabilidad:** la acción queda a nombre del usuario que confirma (`sub`), con el asistente como origen. Conviene reflejarlo en los términos con los clientes.
5. **Consentimiento por cliente:** la escritura se habilita aparte de la lectura (`acciones_habilitadas` vacío por defecto), de modo que un cliente puede usar el asistente solo para consultar.

## 9. Plan de implementación (cuando se decida)

Orden pensado para que cada paso se pueda probar solo y para que el sistema mock sirva de referencia, como en las fases anteriores:

1. **Contrato v1.1 + esquemas + OpenAPI** (propuesta, scope de escritura, claims, `Idempotency-Key`). Reglas nuevas en el verificador.
2. **Mock y referencia PHP**: tool de escritura de ejemplo (la nota) con `propuesta`, emisión del token de escritura y ejecución idempotente. `MOCK_DEFECTO` gana variantes rotas: propuesta con efectos, escritura con token de lectura, `ph` ignorado, replay aceptado, token que sirve para otra tool.
3. **Servicio**: tabla `acciones`, agente (propuesta + corte de turno), endpoints de confirmar/cancelar, límites, auditoría.
4. **Widget**: tarjeta, cuenta regresiva y e2e (`tests_e2e/acciones.e2e.js`: confirmar, cancelar, vencer, doble clic, reemplazo, recarga de página con propuesta pendiente).
5. **Tests de aislamiento ampliados** (`test_aislamiento.py`): confirmación de otro usuario y de otro sistema, token de lectura que intenta escribir, replay, huella alterada, inyección de prompt que busca acción sin clic.
6. **Evals**: preguntas que deben terminar en propuesta (no en ejecución), preguntas ambiguas que deben pedir un dato antes de proponer, e intentos de inyección. Correr por modelo.
7. **Documentación**: contrato, guía de tools (cómo diseñar una tool de escritura segura: idempotente, parametrizada, con resumen claro), README.

Esfuerzo orientativo (sin contar el sistema real): servicio + contrato + mock ≈ una sesión larga; widget + e2e + evals ≈ otra. El riesgo principal no es técnico sino de producto: elegir bien la primera acción.

## 10. Lo que este diseño no cubre

- Acciones iniciadas por el sistema o programadas (Fase 6).
- Aprobaciones de un segundo usuario.
- Permisos de acción por rol dentro del asistente: sigue decidiendo el sistema (si el usuario no puede escribir, la propuesta devuelve `sin_acceso`).
