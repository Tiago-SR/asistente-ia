# Excel descargable desde WhatsApp (OpenWA)

Estado: integración del flujo de turnos implementada, con pruebas automatizadas.
Pendiente la prueba real autorizada de envío, apertura y contenido en WhatsApp.
Fecha: 2026-11-04.

## Objetivo

Que un usuario vinculado pida una planilla por WhatsApp y pueda obtener el `.xlsx` generado desde ese canal,
respetando los permisos, cuotas y límites actuales. La generación y descarga del widget deben seguir funcionando.

## Diagnóstico del código actual

- `api/canal_flujo.py::_turno` ya pasa el servicio de archivos a `run_turn` cuando el sistema tiene
  `exportar_excel` habilitado. Por tanto, la herramienta puede generar el Excel también por WhatsApp.
- `core/excel.py` guarda el archivo y devuelve un evento de UI con `tipo: descarga`, `id` y `nombre`.
- El callback de WhatsApp solo recoge errores y confirmaciones: ignora esos eventos de UI y termina enviando texto.
- `core/canales/base.py` y `core/canales/openwa.py` no ofrecen envío de documentos.
- La descripción de la herramienta, su resultado y `prompts/excel.md` hablan de un botón de descarga, también
  cuando se ejecutan desde WhatsApp. Hay que adaptar las tres instrucciones al mecanismo elegido.
- `GET /v1/descargas/{id}` requiere un Bearer de usuario y verifica sistema, usuario y vigencia. Pegar esa URL en
  un mensaje no permite descargar desde el navegador de WhatsApp, porque no lleva esa autenticación.
- Los archivos viven en Postgres con vencimiento; por defecto, 24 horas. Los topes por defecto son 5.000 filas,
  50 columnas y 2.048 KB por archivo. Reutilizar estos límites y las cuotas existentes.
- Los compose fijan OpenWA `0.26.0` por versión y digest, salvo que se sobrescriba `OPENWA_IMAGEN`.

## Decisiones acordadas

- Entregar el Excel como documento adjunto (alternativa A), sin fallback automático a enlaces.
- El backend obtiene los bytes con la identidad ya validada y comprueba sistema, usuario y vigencia;
  el modelo no recibe URLs ni credenciales.
- No repetir envíos ambiguos ni volver a ejecutar el LLM por un fallo de transporte.
- Implementar únicamente OpenWA en esta etapa; Meta queda fuera.
- Deshabilitar `generar_excel` en canales sin entrega disponible y ajustar sus prompts para no ofrecerla.

## Alternativas evaluadas

A es la alternativa elegida. B y C se conservan como referencia y quedan fuera de esta etapa.

| Alternativa | Experiencia | Ventajas | Costos y límites |
| --- | --- | --- | --- |
| A. Documento adjunto | El chat recibe `reporte.xlsx`; el usuario lo descarga o abre en WhatsApp. | Flujo directo, sin login web ni enlace público al archivo. | Implementar envío de documentos; la copia enviada queda fuera del control de retención del asistente. |
| B. Enlace temporal | El usuario toca una URL y descarga en el navegador. | Permite controlar caducidad y revocar acceso futuro desde el asistente. | Nueva ruta y credencial de descarga; cualquiera con el enlace puede usarlo mientras sea válido. |
| C. Descarga con sesión web | El enlace abre el sistema anfitrión; tras iniciar sesión se descarga el Excel. | Verifica la identidad web y permite comprobar permisos en cada descarga. | Más pasos para el usuario y trabajo de integración en cada sistema anfitrión. |

### A. Adjuntar el Excel — elegida

Reutilizar el archivo guardado y enviarlo como documento al mismo contacto que hizo el pedido. El backend obtiene
los bytes con la identidad ya validada, sin dar al modelo acceso a credenciales ni a URLs de descarga.

Primero verificar el contrato de envío de documentos de la versión instalada: ruta, formato, nombre, MIME,
límites, respuesta y semántica de aceptación/envío. Preferir transferencia directa de bytes/base64 si está soportada.
Si OpenWA exige una URL, documentar esa limitación antes de resolver el transporte interno; no activar enlaces
como fallback ni hacer público el endpoint actual. No asumir que la API de otra biblioteca llamada OpenWA es compatible.

La caducidad de 24 horas seguirá aplicando a la copia del asistente. No elimina la copia enviada por WhatsApp ni
la descargada en el dispositivo. La aceptación de OpenWA tampoco demuestra por sí sola que el usuario la recibió.

### B. Enlace temporal

Crear una ruta específica con una credencial limitada a un archivo, con vencimiento corto —propuesta: 30 minutos,
sin superar la vigencia del archivo— y sin reutilizar el JWT del usuario. La URL la construye el backend.

Decidir entre token firmado (menos persistencia, revocación individual más difícil) o token aleatorio guardado
como hash (revocable, requiere almacenamiento). Impedir acceso a otros archivos y excluir tokens de logs.
No consumir la credencial con el primer GET: las previsualizaciones de enlaces podrían acceder antes que el usuario.
No ofrece identidad del visitante: reenviar el enlace transfiere acceso hasta su vencimiento.

### C. Enlace al sistema con sesión

Definir con el sistema anfitrión una pantalla o ruta de descarga autenticada. El sistema identifica al usuario
y obtiene el archivo por un mecanismo de integración autorizado. El JWT de WhatsApp no debe viajar en la URL.
El widget actual no basta por sí solo: las conversaciones de WhatsApp tienen su propio identificador y el flujo
no guarda hoy las tarjetas de descarga como lo hace el chat web.

Es una alternativa si se exige autenticación web para descargar, pero aumenta el alcance fuera de este repositorio.

## Plan de implementación de A

1. **Validar el transporte.** Revisar la API de la instancia instalada y probar el envío de un `.xlsx` pequeño
   a un contacto de prueba autorizado. Documentar el contrato y los límites observados. No actualizar OpenWA
   como parte implícita de esta feature.
2. **Añadir capacidad de documentos.** Extender la interfaz de canal con capacidad explícita y operación de envío
   con bytes, nombre y MIME. Implementarla en OpenWA. Meta queda sin soporte nuevo en esta primera etapa;
   deshabilitar la herramienta Excel en canales sin entrega disponible, tanto en tools como en prompts.
3. **Recoger los archivos del turno.** Acumular los eventos de descarga en `_turno`, deduplicar por ID y resolver
   los archivos con `sistema_id`, `usuario_ref` y vigencia. Nombre, MIME y bytes deben venir del almacenamiento.
4. **Persistir y entregar.** Guardar el turno completo antes del envío externo y asociar los archivos al mensaje
   final siguiendo el patrón del widget. Enviar cada documento una vez dentro del procesamiento normal del turno.
   Un turno incompleto no envía documentos. No volver a ejecutar el LLM para resolver un fallo de transporte.
5. **Ajustar las respuestas.** El modelo describe qué contiene el Excel sin anunciar botones ni asegurar entrega.
   El backend comunica el fallo si el envío se rechaza. Si hay varios archivos y falla uno, informar el resultado
   parcial sin ocultar los que sí se enviaron. Mantener las instrucciones del widget acordes a su botón.
6. **Registrar las salidas.** Extender `_Registrando` para documentos, guardando el ID devuelto y el tipo sin bytes
   ni contenido de la planilla en logs. Separar archivo generado, envío aceptado y entrega confirmada si existe
   información fiable del proveedor.
7. **Verificar y documentar.** Pruebas mínimas de integración con proveedor simulado y una prueba manual con la
   instancia real. Actualizar la documentación de uso y de errores.

### Fallos y reintentos

La deduplicación de entrada actual evita volver a procesar el mismo webhook en condiciones normales. No garantiza
entrega exactamente una vez ante caídas entre el envío externo y su registro. Un timeout puede ocurrir después
de que OpenWA aceptó el documento: no repetir un envío ambiguo en esta etapa.

Informar cuando no se pudo confirmar el envío, sin regenerar el archivo ni volver a ejecutar el LLM por ese fallo.
Un pedido explícito posterior del usuario puede iniciar un nuevo turno. Reenvío del mismo archivo mediante comando,
cola durable y recuperación automática tras reinicios quedan fuera de esta etapa.

## Criterios de aceptación de A

- Un usuario vinculado pide un Excel y recibe un documento `.xlsx` válido con nombre y contenido correctos.
- La respuesta en WhatsApp no menciona un botón de descarga ni afirma una entrega que no se pudo confirmar.
- Un usuario sin vínculo no genera ni recibe archivos; no se puede enviar un archivo de otro usuario o sistema.
- Archivo vencido, inexistente o ajeno no se envía; las cuotas y límites existentes siguen aplicándose.
- Varios archivos en un turno se procesan sin duplicar IDs y un fallo parcial se comunica con claridad.
- Un error de OpenWA no vuelve a generar el Excel ni dispara reintentos ciegos que puedan duplicar documentos.
- Un webhook duplicado no produce un segundo envío en el flujo normal; se documenta el límite ante caídas.
- El widget conserva su generación, botón, descarga autenticada y tratamiento de archivos vencidos.
- Canales sin soporte no ofrecen una herramienta cuyo resultado no pueden entregar.
- No se generan enlaces de descarga como fallback y el modelo no recibe URLs ni credenciales de archivos.
- Meta no ofrece `generar_excel` en esta etapa; el widget y OpenWA la ofrecen solo cuando están habilitados
  la exportación y el servicio de archivos, y existe capacidad de entrega en el canal correspondiente.

## Validación técnica pendiente

Contrato de OpenWA 0.26.0 contrastado con el código de la imagen instalada: admite base64,
nombre y MIME, sin exigir URL. Adaptador y pruebas de transporte añadidos (parte del paso 2).
Detalles y límites documentados en [openwa-documentos.md](openwa-documentos.md).
La integración de los pasos 2–6 está implementada. El paso 7 tiene cobertura automatizada;
falta la prueba real a un contacto autorizado del paso 1 para cerrar la aceptación manual.

## Avance del 2026-11-04: integración del turno

- [x] **Capacidad y habilitación (paso 2).** `armar_turno` recibe la disponibilidad de entrega del canal.
  Solo ofrece Excel cuando también existen exportación habilitada y almacenamiento. Meta queda sin la tool;
  su prompt indica que no ofrezca planillas. Motivo: evitar generar un resultado que el canal no puede entregar.
- [x] **Recolección y persistencia (pasos 3–4).** `_turno` recoge eventos `descarga`, deduplica por ID y guarda
  sus referencias en el mensaje final con el mecanismo del widget. Solo después de guardar un turno completo
  empieza la entrega. Motivo: no enviar documentos de turnos incompletos o cuya persistencia falló.
- [x] **Entrega autorizada (pasos 3–4).** Cada lectura usa `sistema_id`, `usuario_ref` y el filtro de vigencia
  de `ArchivosSql.obtener`; bytes, nombre y MIME proceden del almacenamiento, no del evento del modelo.
  Motivo: conservar el aislamiento y la caducidad existentes sin URLs ni credenciales en el modelo.
- [x] **Errores y respuestas (paso 5).** Se informa por archivo si está indisponible o si no pudo confirmarse
  el envío; un rechazo de documento permite continuar con los siguientes. No hay reintentos ni regeneración.
  La descripción y el resultado de la tool son neutrales respecto del canal; el prompt distingue botón del widget
  y adjunto de WhatsApp. Motivo: evitar promesas de recepción y duplicados ante timeouts ambiguos.
- [x] **Registro (paso 6).** `_Registrando.enviar_documento` guarda el ID aceptado y tipo `documento`, sin
  bytes ni filas. Motivo: seguir las salidas mediante el mecanismo existente sin registrar la planilla.
  La aceptación sigue sin equivaler a entrega confirmada; no se agregó un estado de recepción ficticio.
- [x] **Pruebas automatizadas (paso 7).** Nuevos casos verifican deduplicación, persistencia previa, ausencia
  de envío si el turno falla, fallos parciales sin reintentos, filtro de identidad y registro sin contenido.
  También se prueba generación de un `.xlsx` real y habilitación según capacidad con LLM simulado.
- [ ] **Prueba manual real (pasos 1 y 7).** Falta identificar y autorizar el contacto de prueba. No se envió
  ningún documento real durante esta implementación. Ver procedimiento en `openwa-documentos.md`.

Decisiones de comportamiento: la frase «sin Excel» del prompt solo se añade si el sistema tiene `exportar_excel` y
almacenamiento pero el canal no puede entregar. Los documentos se envían antes del texto final del modelo (así
el usuario no pierde el archivo si falla ese texto). Si no se puede guardar el turno no se entrega nada ni se
responde, igual que en el resto del flujo.

No se cambió la deduplicación de webhooks ni se añadió recuperación durable. Sigue vigente el límite ante
una caída entre envío y registro. Las cuotas, límites y descarga autenticada del widget se reutilizan.

Validación ejecutada en el contenedor de desarrollo: **235 pruebas pasaron** (2026-11-04, tras los ajustes de la revisión) con
`pytest -q tests/test_canal.py tests/test_canal_excel.py tests/test_api.py tests/test_agent.py tests/test_seguridad.py tests/test_memoria.py`.
Incluye pruebas del chat web, del transporte OpenWA simulado y del aislamiento de archivos en Postgres.
No se ejecutó el navegador E2E del widget ni se confirmó recepción real en WhatsApp.

## Referencias

- Código local: `core/excel.py`, `core/canales/{base,openwa}.py`, `api/{chat,canal_flujo,descargas}.py`,
  `store/archivos.py`, `prompts/{excel,whatsapp}.md` (rutas relativas a `src/asistente`, excepto prompts).
- Proyecto del proveedor: https://github.com/rmyndharis/OpenWA
- OpenAPI de la rama actual: https://raw.githubusercontent.com/rmyndharis/OpenWA/main/openapi.json
  (consulta orientativa; no demuestra compatibilidad con la versión 0.26.0 instalada).
