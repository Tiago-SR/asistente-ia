# Producto: investigación y planes

Revisión del código local: 2026-11-04. Este documento detalla `PENDIENTES.md`; no cambia el contrato vigente ni
implementa funcionalidades. Las interfaces nuevas de abajo son propuestas para revisar con el asesor antes de
programarlas, según las reglas del proyecto. No se investigaron proveedores externos: el análisis se basa en el repo.

## 1. Deshacer acciones

### Situación comprobada

- `sistemas/manifiesto.py`: `Tool` no tiene `reversible_con`.
- `api/confirmaciones.py`: confirma, ejecuta, audita y anota el resultado. El mensaje y `ui` vuelven al cliente,
  pero no se persiste una referencia de compensación.
- `store/acciones.py`: conserva propuesta, parámetros y estado; `finalizar()` guarda éxito/error y estado HTTP.
- `sistemas/conector_http.py`: interpreta el resultado, pero no un descriptor de deshacer.
- La maquinaria actual ya ofrece reclamo atómico, huella, vencimiento, token ligado a acción e idempotencia.
  El anfitrión sigue siendo responsable de permisos, consistencia e idempotencia de la escritura real.

### Comportamiento propuesto

Deshacer es una **nueva acción compensatoria** definida por el anfitrión, no reproducir parámetros antiguos ni
restaurar automáticamente datos desde el asistente. Puede fallar si el registro cambió o el usuario perdió permisos.

1. La tool original declara `reversible_con` apuntando a una tool de escritura con confirmación.
2. Solo tras un éxito confirmado, el anfitrión devuelve una referencia opaca de operación reversible y su vigencia.
   El anfitrión conserva el estado necesario y la versión posterior a la operación. No se confía en ids o valores
   inventados por el modelo para construir la reversión.
3. La tarjeta ejecutada ofrece «Deshacer» mientras la referencia esté vigente. Pulsarlo solicita una propuesta de
   compensación con sesión de lectura; todavía no modifica datos.
4. El anfitrión comprueba propiedad, permisos, vigencia, operación no revertida y versión actual. Devuelve resumen,
   detalle Antes/Después y huella con la maquinaria de propuestas existente.
5. El usuario confirma esa nueva tarjeta. Se pide un token nuevo ligado a la tool compensatoria, huella y cid nuevo.
6. La compensación se ejecuta una vez. Se enlazan ambas acciones, se actualiza la tarjeta original y se anota el
   resultado en el historial. Cancelar la propuesta permite volver a pedirla mientras la operación siga vigente.

Alcance inicial recomendado: widget y una operación reversible del mock; luego referencia PHP. Sin deshacer en
cadena, acciones locales de memoria ni reversión de borrados en el MVP. Si la compensación elimina o anula datos,
se aplican las reglas de tools destructivas y su aprobación administrativa; `reversible_con` no las evita.

### Plan de implementación

1. Acordar contrato y schemas: forma de `reversible_con`, descriptor de resultado, parámetro de referencia,
   vigencia y errores de negocio. Validar destino existente, escritura confirmable y referencias inválidas/cíclicas.
   Incluir estos campos en la huella de definición para invalidar aprobaciones al cambiar la semántica.
2. Extender puertos/resultados y parser HTTP. El descriptor debe viajar fuera de los datos entregados al modelo.
3. Migrar `Accion`: descriptor de compensación, vencimiento, enlace a original y resultado mínimo necesario para
   restaurar tarjetas. No persistir indiscriminadamente todo `datos`. Definir retención alineada con la acción.
4. Añadir una operación autenticada para solicitar la propuesta de deshacer a partir del id de acción propia.
   Resolver destino desde el manifiesto y la referencia guardada; reutilizar confirmación y cancelación existentes.
5. Bloquear compensaciones duplicadas en el asistente y consumir la operación original atómicamente en el anfitrión.
   Un fallo de red puede dejar resultado incierto: no anunciar «revertida» ni reintentar con una identidad nueva;
   consultar el estado/idempotencia del anfitrión antes de habilitar otra compensación.
6. Widget: botón, segunda tarjeta, conflicto/vencimiento y restauración tras recarga. Ampliar la consulta del historial:
   hoy solo restaura propuestas pendientes, no tarjetas ejecutadas con capacidad de deshacer.
7. Implementar mock y PHP, ampliar verificador, contrato, guía, documentación y evals. Evaluar canales después:
   `api/canal_flujo.py` comparte confirmaciones, pero sus botones y sus restricciones requieren adaptación explícita.

### Pruebas y aceptación

- Parser/schema: destino ausente, lectura, sin confirmación, ciclo, descriptor malformado y cambio de huella.
- Integración PostgreSQL: persistencia y recuperación del enlace, propuesta propia/ajena, cancelación y vencimiento.
- Contrato anfitrión: alta → deshacer y modificación → restaurar estado anterior; propuesta sin efectos.
- Cambio posterior de versión → conflicto sin sobrescribir; permisos revocados → rechazo.
- Token original, token de otra tool/huella/usuario, vencido y reutilizado → rechazo.
- Doble clic, dos pestañas y dos propuestas simultáneas → una compensación efectiva; idempotencia conserva resultado.
- Corte de red/reinicio antes o después de ejecutar → estado incierto tratado sin duplicar ni afirmar éxito.
- E2E: ejecutar → Deshacer → revisar → confirmar; cancelar; recargar antes/después; vencimiento visible.
- Evals: el modelo no afirma haber deshecho antes de la confirmación ni fabrica referencias de reversión.

Terminado cuando el flujo completo funciona contra mock y PHP, pasa el verificador y restaura correctamente la UI.

## 2. Conservar imágenes de referencia

### Decisión de producto y alcance

Las imágenes se conservan hasta crear una nueva conversación para ese usuario. Al crearla se eliminan las imágenes
anteriores de ese usuario **dentro del mismo sistema**, aunque pertenezcan a varias conversaciones. No se borran
conversaciones ni mensajes por esta regla. Volver a abrir un historial antiguo no recupera las imágenes eliminadas.
El borrado explícito de una conversación y la purga de retención también eliminan sus imágenes.

Interpretación propuesta para implementar: crear significa una creación confirmada por el servidor, incluso antes
del primer mensaje; no basta con cambiar el estado visual del widget. La decisión del usuario no define el caso de
varias pestañas/canales: se propone un único conjunto vigente de imágenes por `(sistema, usuario)`. Las conversaciones
anteriores siguen siendo consultables, pero sus turnos tardíos no pueden volver a guardar imágenes tras el reinicio.

### Situación comprobada

- `core/adjuntos.py`: `AlmacenAdjuntos` solo tiene `guardar(sistema, usuario, adjuntos)`, sin conversación,
  recuperación ni borrado. `NoGuarda` devuelve referencias vacías y `marca()` dice que la imagen no se conserva.
- `api/chat.py` y `api/canal_flujo.py` usan `para_guardar()` al completar el turno.
- `store/repo.py` persiste metadata/ref y descripciones; reconstruye adjuntos con bytes vacíos.
- `core/llm/openai_compat.py` solo envía imágenes que tengan bytes: guardar una ref no permite volver a mirarla.
- `Repo.visibles()` no expone adjuntos; el widget no puede restaurar sus miniaturas desde ese historial.
- `widget.js:_nueva()` solo limpia `_convId`; `api/chat.py` genera el id y `guardar_turno()` crea la fila al final.
  Actualmente pulsar «Nueva conversación» no informa al servidor.
- El canal tiene una conversación determinista por número y usuario (`api/canal_flujo.py`); no equivale a crear una
  conversación nueva por cada mensaje. No debe borrar imágenes en cada turno.

### Plan de implementación

1. Acordar una operación idempotente de creación/reinicio en servidor y adaptar el widget. El camino compatible
   de `/v1/chat` sin id debe usar la misma operación al iniciar una conversación, no esperar al guardado final.
   Dos reintentos de creación deben identificar la misma operación. Borrar no debe depender de que responda el LLM.
2. Tabla de adjuntos con id opaco, sistema, usuario, conversación, generación vigente, MIME, tamaño y bytes.
   Propuesta inicial: bytes en PostgreSQL para poder crear la conversación y borrar los anteriores en una transacción.
   Si se elige almacenamiento externo, hace falta cola de borrado persistente y distinguir revocación inmediata
   de eliminación física; no ofrecer la misma garantía de atomicidad sin esa implementación.
3. Registrar la generación vigente por sistema/usuario. Bajo un lock transaccional por esa pareja, crear la nueva
   conversación, avanzar generación y borrar bytes previos. Los guardados de turnos deben comprobar generación
   bajo el mismo lock: un turno antiguo que termine tarde no puede recrear las imágenes eliminadas.
   Abrir una conversación antigua no cambia la generación ni borra las imágenes nuevas.
4. Ampliar `AlmacenAdjuntos` con contexto de conversación/generación, cargar y borrar. Guardar metadata y bytes
   de forma atómica con el turno; cancelación o error no debe dejar blobs huérfanos. Conectar implementación
   en `servicios.py`, chat y canales. No reutilizar el almacén de Excel sin revisar: tiene otro ciclo de vida.
5. Recuperar adjuntos propios para el historial del modelo, con límites de imágenes/bytes por petición y presupuesto
   de contexto. No reenviar todas las imágenes de todos los turnos. Reutilizar descripción cuando alcance; cargar
   originales recientes cuando haga falta visión y el modelo/sistema lo admita. Imagen ausente → metadata de
   eliminada, sin fallo del chat ni fingir que el modelo la volvió a ver.
6. Exponer metadata de disponibilidad y descarga autenticada para miniaturas, sin URLs públicas ni token en URL.
   Widget: conservar vista tras recarga, indicar eliminación en históricos y revocar URLs locales al cambiar/borrar.
7. Conectar borrado de conversación, retención y borrado de sistema/usuario donde exista. Definir cuota acumulada
   por usuario además del límite actual por mensaje: sin nueva conversación la retención podría ser larga.
   La cuota rechaza nuevos adjuntos sin borrar silenciosamente los anteriores.
8. Actualizar marca de historial, contrato §7 de imágenes, aviso de privacidad y documentación. Mantener saneamiento
   de descripciones y tratamiento como datos de terceros. El texto OCR existente sigue la retención del historial;
   esta decisión elimina imágenes, no todas las transcripciones ni sus menciones en respuestas.

El borrado propuesto es del almacenamiento operativo. Documentar también cuándo desaparecen de backups y qué
retención aplica el proveedor LLM: borrar localmente no borra retroactivamente las copias de terceros.

### Pruebas y aceptación

- Guardar JPEG/PNG válidos, recuperar contenido idéntico, restaurar miniatura y consultar la imagen en otro turno.
- Aislamiento: referencias ajenas/inexistentes con la misma respuesta; mismo usuario en otro sistema queda intacto.
- Crear nueva conversación sin enviar mensaje → bytes anteriores eliminados; recarga del historial muestra ausencia.
- Seguir en la misma conversación o abrir una antigua → no borra los adjuntos nuevos.
- Reintento de creación, dos pestañas, turno viejo terminando después del reinicio y cargas concurrentes:
  ninguna imagen de generaciones anteriores vuelve a aparecer ni borra una generación posterior.
- Error al crear → rollback; error/cancelación al guardar → sin huérfanos; reinicio del servicio conserva lo vigente.
- Borrado manual y purga → sin bytes asociados; referencias eliminadas no rompen el historial.
- Cuota acumulada, límites por turno/modelo, modelo sin visión y adjunto faltante → respuesta controlada.
- Canal: no reinicia por cada mensaje; respeta la generación vigente si el mismo usuario crea una conversación web.
- E2E: adjuntar → preguntar en otro turno → recargar → nueva conversación → comprobar desaparición anterior.

Terminado cuando la creación confirmada elimina los bytes anteriores de forma verificable, incluso bajo concurrencia,
y el acceso posterior devuelve eliminado. Añadir pruebas sobre PostgreSQL real para locks y transacciones.

## 3. Manifiesto por rol de usuario: investigación ampliada

### Problema y puntos afectados

Hoy `CacheManifiestos` usa sistema como clave y descarga con credencial de servicio. `ConectorHttp.tools_de()` recibe
solo sistema y aplica `tool_permitida()`, que expresa política administrativa por sistema. No conoce las capacidades
del usuario. `_preparar()` también resuelve la tool global. Esto causa ofrecimientos que el anfitrión rechaza.
Ocultar herramientas mejora relevancia; no sustituye permisos sobre registros ni autorización al ejecutar.

No alcanza con filtrar al construir el prompt: hay que revisar ejecución/propuesta, consultas recientes, consultas
guardadas, restauración de confirmaciones, canal y panel. Un cambio de rol debe invalidar la vista anterior.

### Alternativas

| Alternativa | Ventaja | Costo o límite |
|---|---|---|
| Catálogo global + capacidades en JWT firmado | Sin consulta adicional; conserva caché global y panel | Tamaño del token; permisos quedan viejos hasta renovación; revisar token de escritura/canal |
| Catálogo global + endpoint de capacidades con JWT de usuario | Permisos efectivos por usuario/tenant; token pequeño | Consulta adicional, TTL e invalidación; nueva ruta contractual |
| Manifiesto completo autenticado por usuario | Permite schemas/descripciones distintos por perfil | Cambia credenciales y caché; dificulta diff y aprobaciones globales; mayor riesgo de mezcla |

Recomendación para el primer caso real: catálogo global estable + capacidades efectivas emitidas por el anfitrión.
Preferir endpoint si hay muchos permisos o revocación frecuente; JWT si la lista es pequeña y basta su vida corta.
No codificar nombres como `admin` o `vendedor` en el asistente: un rol puede depender de empresa, sucursal o tenant.

La selección efectiva debe ser la intersección de catálogo válido, política administrativa y capacidades del usuario.
Las escrituras conservan habilitación/confirmación y aprobación destructiva; una capacidad no habilita esas barreras.
Ausencia por compatibilidad en sistemas antiguos debe distinguirse de lista vacía explícita y de fallo de consulta.
Si un sistema activa capacidades y no pueden obtenerse, no caer al catálogo completo.

### Plan para concretarlo y probarlo

1. Elegir dos perfiles reales con una herramienta que solo uno pueda usar y documentar revocación/tenant.
2. Acordar formato y fuente de capacidades, versionado y comportamiento de sistemas antiguos con el asesor.
3. Pasar identidad a selección y validación de tools. Si hay caché de capacidades, usar sistema, usuario, tenant y
   versión de permisos; TTL acotado, nunca solo rol ni tokens completos como claves/logs.
4. Revalidar al proponer/confirmar y en el anfitrión al ejecutar; no congelar permisos al crear la tarjeta.
5. Filtrar recientes/guardadas y adaptar tokens de canal/escritura para no perder contexto efectivo.
6. Panel conserva catálogo global y aprobaciones; una vista por perfil sería diagnóstico opcional sin exponer tokens.
7. Tests: dos usuarios y tenants con permisos distintos, lista vacía, fallo, token renovado, revocación, tool retirada,
   propuestas viejas, consulta guardada no permitida, canal y ausencia de filtración cruzada por caché.

Primera entrega útil: el modelo de cada perfil solo recibe sus tools y una revocación bloquea la escritura aunque
exista una propuesta anterior. Pendiente de elegir caso real y alternativa contractual; no requiere construir un
sistema de roles dentro del asistente.

## 4. Fase 6: asistente proactivo, investigación ampliada

### Qué existe y qué falta

Hay turnos bajo petición, auditoría, cuotas, métricas, purga periódica (`retencion.py`) y mensajería con deduplicación
y estado (`api/canal_flujo.py`, `store/canal.py`). No constituyen un motor general de eventos de negocio ni un
programador durable. La deduplicación de mensajes del canal no evita por sí misma duplicar un aviso de negocio.
Las tareas de un proceso pueden servir como mecanismo de ejecución, pero el trabajo pendiente debe quedar en BD.

Separar tres casos de producto:

- **Eventos del sistema:** el anfitrión detecta un hecho y envía un evento dirigido a usuarios autorizados.
- **Consultas programadas:** una suscripción ejecuta una consulta de lectura con cierta frecuencia y decide si avisar.
- **Seguimientos de conversación:** el usuario pide «avísame mañana» o una condición. Requiere extraer, mostrar y
  confirmar una suscripción; es una etapa adicional, no algo que el modelo deba activar silenciosamente.

### Primer alcance recomendado

Un evento de negocio de un sistema, aviso dentro del widget, texto redactado por plantilla del servidor y enlace
a consultar datos actuales. Sin LLM al ingerir el evento y sin ejecutar escrituras de negocio. El aviso puede estar
desactualizado: al abrirlo se revalida acceso y se consultan datos actuales. La bandeja se consulta al abrir el widget
y mediante sondeo acotado; no depende de que el usuario mantenga un SSE del chat abierto.

Esto permite validar utilidad antes de implementar cron, refresh tokens o entregas por WhatsApp/email/push.
Reutilizar transporte de mensajería no elimina la necesidad de preferencias y reglas propias del canal.

### Diseño propuesto y decisiones

1. Contrato de ingreso por sistema: autenticación de servicio con alcance mínimo, firma/fecha si se acuerda ese
   mecanismo, tipo permitido, id de evento estable, destinatarios y payload limitado. Rechazar identidad cruzada;
   no aceptar URLs arbitrarias ni instrucciones para el agente dentro del evento.
2. Tabla de entrada durable con unicidad `(sistema, id_evento)` y bandeja por destinatario. Guardar el evento antes
   de responder aceptación. Duplicados con contenido diferente deben producir conflicto y auditoría.
3. Worker reclama trabajo mediante locks/leases de BD, con estados, intentos, próximo intento y errores. Recuperar
   leases tras reinicio, reintentos acotados y destino de fallidos. La aceptación HTTP no significa entrega.
4. Entrega con idempotencia propia por evento/destinatario/canal. Con servicios externos habrá ventanas de resultado
   incierto: prometer deduplicación verificable, no entrega exactamente una vez sin soporte del proveedor.
5. Preferencias por usuario: activar tipos de aviso, baja, horarios y zona horaria. Límites por usuario/sistema,
   agrupación para ráfagas, retención, auditoría y métricas separadas de los turnos interactivos.
6. El destinatario no se valida solo por tener un id: el anfitrión debe confirmar que puede recibir ese aviso y
   volver a validar acceso al abrirlo. En MVP conservar pocos datos sensibles y preferir referencias opacas.
7. Segunda etapa, programaciones: guardar suscripción confirmada, consulta de lectura validada, zona horaria,
   próxima ejecución y política de ejecuciones perdidas. Resolver horario de verano, caídas y deduplicación por
   ocurrencia; presupuestos separados de tokens/consultas. No consultar todas las herramientas por defecto.
8. Resolver credenciales antes de ejecutar sin sesión: el JWT actual de usuario vence. No guardar JWTs vencidos ni
   convertir la credencial de manifiesto en token de datos. Acordar delegación revocable de lectura con el anfitrión
   o hacer que este ejecute la consulta y publique el resultado/evento. Relacionado con `INTEGRACIONES_FEU_GMAIL.md`.
9. Canales externos y uso de LLM solo después de validar el MVP: costos, consentimiento y políticas del proveedor
   requieren investigación actualizada específica. El modelo podría resumir datos saneados, nunca autorizar acciones.

### Pruebas y criterio para avanzar

- Ingreso: credencial incorrecta, sistema cruzado, replay, payload excesivo/tipo desconocido y duplicado conflictivo.
- Persistencia: caída después de aceptar, reclamo por dos workers, lease vencido, reintentos y evento fallido visible.
- Destinatarios: usuario ajeno, permiso revocado, preferencias desactivadas, límites y ráfagas.
- Bandeja: listar solo propios, marcar leído idempotentemente, recarga y aviso cuyo dato ya no existe.
- Programaciones posteriores: reloj controlado, cambio horario, reinicio, ocurrencia duplicada y consulta invalidada.
- Canal externo posterior: timeout tras posible entrega y reintento sin duplicar cuando el proveedor lo permita.

Antes de implementar, elegir un evento real, quién lo emite, quién lo recibe y cómo mediremos su utilidad.
Si aún no hay caso real, mantener esta fase en evaluación. No hace falta incorporar una cola externa para el primer
MVP: una tabla durable y un worker pueden bastar; dimensionar infraestructura al conocer volumen y latencia.

## Orden sugerido

1. Imágenes: decisión de retención ya tomada; revisar creación de conversación y generación antes de programar.
2. Deshacer: acordar el contrato compensatorio y elegir una operación del mock/PHP.
3. Capacidades por usuario: avanzar cuando haya dos perfiles reales para validar el diseño.
4. Proactividad: elegir un evento y probar bandeja en widget; luego evaluar programaciones y otros canales.

Para implementar cada entrega, ampliar las suites existentes: `tests/test_api.py`, `test_conector_http.py`,
`test_manifiesto.py`, `test_acciones.py`, `test_aislamiento.py`, `test_canal.py`, `tests_e2e/acciones.e2e.js`
y `tests_e2e/widget.e2e.js`, además del verificador y los tests PHP donde corresponda. Este cambio documental
no ejecuta esas pruebas ni afirma que las funcionalidades propuestas estén verificadas.
