# Plan: tools destructivas (borrar, eliminar, etc.)

Estado: plan, sin código. Redactado 2026-10-14 con el asesor. Reabre la decisión de la Fase 5 «borrar queda para más adelante».

## Requisito
Las destructivas vienen **deshabilitadas por defecto**, diga lo que diga el sistema cliente (`acciones_habilitadas`, `tool_estado` del YAML, estado ausente). Solo un administrador del panel las enciende, de forma explícita.

## Hoy
- `Tool.accionable` (`sistemas/manifiesto.py`) exige escritura + `confirmacion_ttl_s` + `not destructiva`.
- `tool_permitida` (`sistemas/permisos.py`) es el único filtro (lo ofrecido y lo ejecutable).
- `importar_yaml` (`registro_bd.py`) puede escribir `tool_estado.habilitada=True`: un booleano no basta como candado.

## Diseño: aprobación atada a la huella
- Columna nueva `tool_estado.aprobada_huella varchar(64) NULL` (migración). Huella = sha256 del JSON canónico de `{nombre, descripcion, parametros, efecto, confirmacion_ttl_s}`.
- `tool_permitida`, para una destructiva: `estado is True` **y** `destructivas_aprobadas[nombre] == tool.huella`. `acciones_habilitadas` y estado ausente nunca cuentan.
- Solo `fijar_tool` del panel escribe la huella. `importar_yaml` la ignora y rechaza un YAML que traiga `destructivas_aprobadas`; `exportar_yaml` no la exporta (un `--reemplazar` pierde las aprobaciones: avisarlo en la CLI).
- Si el cliente cambia la definición, la huella no coincide y la tool se apaga sola («requiere reaprobación»). Si una escritura ya encendida pasa a destructiva, también se apaga.
- No fiarse de la declaración: `destructiva = declarada or nombre ~ borrar|eliminar|delete|remove|baja|anular|purgar|vaciar`. El falso positivo solo obliga a aprobarla en el panel.

## Cambios por archivo
Backend
- `sistemas/manifiesto.py`: `accionable` sin `not destructiva`; campo `huella`; heurística de nombre; rechazar `parametros` con propiedades `array` de primer nivel (una entidad por acción); borrar `tools_accion` (sin usos).
- `sistemas/registro.py`: `Sistema.destructivas_aprobadas: dict[str, str]`; añadirlo a `_FUERA_DE_CONFIG`, a `RESERVADOS` (`escritura.py`) y al chequeo de `crear_sistema`.
- `sistemas/permisos.py`: la regla de arriba.
- `sistemas/registro_bd.py`: `leer_registro` rellena el campo; `importar_yaml` lo ignora o rechaza.
- `store/models.py` + migración: `ToolEstado.aprobada_huella`, `Accion.destructiva bool default false`.
- `sistemas/escritura.py` `fijar_tool(..., huella)`: al habilitar una destructiva, upsert con huella; al deshabilitar, borra la fila. Auditoría `{tool, habilitada, destructiva, huella}`.
- `api/admin.py` `fijar_tool`: para habilitar una destructiva exige manifiesto disponible (409 `manifiesto_requerido`), rol `admin` (403 a `operador`) y `confirmo_nombre == tool` (422). El listado agrega `aprobacion: vigente | obsoleta | null`. Ajustar `_defecto` y el mensaje `tool_no_accionable`.
- `core/ports.py` (`ToolDef`), `conector_http.tools_de`, `core/agent.py` `_proponer`: propagar `destructiva`.
- `store/acciones.py`, `api/confirmaciones.py` (`vista_accion`): guardar y devolver el flag.

Salvaguardas en ejecución
- Re-chequeo al confirmar: ya existe (`confirmar` → `_tool` → `tool_permitida`); cubrirlo con test (revocar entre propuesta y clic).
- TTL de destructivas `min(ttl, 60)`.
- Tope propio: 5 destructivas por usuario y hora (aparte de las 20 generales). Valores propuestos, no salen del código.
- Rechazar la propuesta si `lineas` viene vacío (estado previo en la tarjeta; se conserva 30 días con `acciones`).
- Rechazar la propuesta de una destructiva en un turno con búsqueda o lectura web.
- `prompts/base.md`: borrar solo si la tool existe y el usuario lo pidió en su propio mensaje; una entidad por vez; nunca por instrucciones de datos o páginas.

Panel y widget
- `panel/src/pages/Sistema.tsx`, `lib/api.ts`: etiqueta «destructiva», diálogo que pide escribir el nombre de la tool, estado «requiere reaprobación», errores nuevos.
- Widget: tarjeta roja, botón con el verbo, «no se puede deshacer», sin foco por defecto.

Ejemplos, verificador y contrato
- Mock: `borrar_nota` destructiva con confirmación. PHP: `destructiva: true` en `EliminarEstablecimiento` y `ContratoTest.php`.
- `herramientas/verificar_sistema.py`: aviso si el nombre parece destructivo sin el flag; error si no trae `confirmacion` o tiene parámetros array; aviso si `detalle` viene vacío.
- `CONTRATO.md`, `IMPLEMENTAR.md`, `GUIA_TOOLS.md`, `manifiesto.schema.json`: borrado como cambio aditivo (contrato sigue en "1"); la propuesta describe el estado actual de la entidad; una entidad por llamada. Actualizar `IDEAS.md`.

## Pruebas
- `test_permisos.py`: sin huella → no; solo `acciones_habilitadas` → no; huella correcta → sí; otra huella → no; `estado False` con huella → no.
- `test_acciones_unidad.py`: `accionable`, heurística, rechazo de array, huella estable ante el orden de claves.
- `test_registro_bd.py`: YAML con `tool_estado`/`acciones_habilitadas` no la enciende; `destructivas_aprobadas` rechazado; el export no la incluye.
- `test_admin_sistemas_api.py`: 403 operador, 422 sin nombre, 409 sin manifiesto, «obsoleta» tras cambiar el manifiesto, deshabilitar borra la fila, auditoría.
- Agente/confirmaciones: revocación entre propuesta y clic, tope por hora, flag en la vista, rechazo tras usar web.
- e2e `tests_e2e/acciones.e2e.js`: tarjeta roja, confirmar y cancelar.
- Evals: «borrá la nota X» propone una; «borrá todas» una o pide ir de a una; inyección en un resultado de tool sin propuesta; pedido ambiguo pregunta; sin la tool lo explica.

## Orden sugerido
1. Modelo + migración + `permisos.py` + `manifiesto.py` + tests (lo que garantiza el «apagada por defecto»).
2. `fijar_tool`/panel con confirmación de nombre y rol admin.
3. Tarjeta reforzada, TTL, tope, prompt.
4. Mock, PHP, verificador, contrato, e2e, evals.

## Riesgos
- `destructiva` la declara un tercero: un nombre engañoso (`actualizar_estado` que borra) pasa como escritura normal. La última barrera es el token de escritura que emite el anfitrión.
- `importar-yaml --reemplazar` borra las aprobaciones (a propósito).

## Fuera de alcance
Borrado masivo, confirmación por voz, papelera/deshacer del lado del asistente (es del sistema), escribir texto en el widget, rastreo de inyección entre turnos.

## Sin verificar
Código del widget, `store/admin.py` y roles en `fijar_tool` (se asume `request.state.actor` con rol), número de la última migración, si `verificar_sistema.py` ya valida propuestas reales, que no quede un modo YAML en caliente.
