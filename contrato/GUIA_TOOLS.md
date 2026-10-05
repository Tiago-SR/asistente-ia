# Guía de diseño de tools

Complementa el [contrato](CONTRATO.md): el contrato dice **qué** debe cumplir una tool para que el asistente la acepte; esta guía dice **cómo diseñarlas** para que el asistente responda bien. El modelo solo ve el nombre, la descripción y el schema de cada tool, y lo que ellas devuelven. Si eso es ambiguo, inventará o se confundirá.

Los ejemplos salen del [sistema mock](../ejemplos/sistema-mock/app.py) y de las tools de STMGIS (`backend/asistente/tools.py`).

## 1. Cómo elegir las tools

- **Pocas y de alto nivel.** Una tool por pregunta que los usuarios hacen de verdad, no una por tabla ni por endpoint. Entre 5 y 15 suele alcanzar; el límite duro es 40 y cada una cuesta tokens en cada turno.
- **Una tool = una intención.** Si la descripción necesita un "o" para explicar qué hace, son dos tools.
- **Que resuelva la pregunta completa.** Si responder "¿cuántas hectáreas tiene la empresa X?" requiere sumar cien filas, la tool debe devolver el total (ver [sección 4](#4-qué-devolver)), no las cien filas.
- **Una de listado por entidad principal**, con filtro `texto` (ver [sección 5](#5-listados-con-filtro-texto-para-resolver-nombres)).
- **Solo lectura por defecto.** Las `escritura` no llegan al modelo salvo que declaren `confirmacion` y el operador las habilite (agregar o modificar; nunca borrar), y aun así el usuario confirma cada una en pantalla ([sección 8 del contrato](CONTRATO.md#8-acciones-con-confirmación-opcional)). El sistema debe rechazar siempre una escritura con el scope de lectura.
- **Empezar por las preguntas.** Escribir 10 preguntas reales de usuarios y comprobar que cada una se contesta con 1 a 3 llamadas. Esas preguntas son además la base del set de evaluación (`evals/`).

| Mal | Bien |
|---|---|
| `get_tabla_lotes`, `get_tabla_lotes_2`, `get_lotes_join_campanas` (el modelo no sabe cuál elegir) | `resumen_lotes` con filtros opcionales `establecimiento_id` y `campania` |
| `ejecutar_consulta(sql)` (salta los permisos; el sistema no controla qué se pregunta) | tools específicas que aplican los permisos del usuario |
| `listar_campos` y `listar_campos_con_empresa` y `buscar_campo` | `listar_campos` con `empresa_id` y `texto` opcionales (como en STMGIS) |

## 2. Nombres y descripciones

**Nombre:** verbo + objeto en `snake_case` (`^[a-z][a-z0-9_]{0,63}$`): `listar_campos`, `resumen_establecimiento`. Sin versiones ni abreviaturas internas.

**Descripción** (≤ 1 000 caracteres, pero casi siempre bastan 2 o 3 frases). Debe contestar tres cosas, en este orden:

1. **Qué hace**, en una frase.
2. **Cuándo usarla** (y cuándo no, si hay una tool parecida).
3. **Qué devuelve**, con las unidades y los límites relevantes.

```text
✔ "Lista los campos (establecimientos) activos con su empresa, departamento y superficie en
   hectáreas. Se puede filtrar por empresa (id obtenido con listar_empresas) y/o por nombre.
   No devuelve geometrías."                                              ← STMGIS, listar_campos

✔ "Lista los establecimientos que el usuario puede ver. Usar primero para resolver nombres a
   ids."                                                                 ← mock, listar_establecimientos

✘ "Establecimientos."                    (no dice cuándo usarla ni qué devuelve)
✘ "Devuelve datos del establecimiento."  (¿qué datos?; el modelo no sabrá si sirve para su pregunta)
✘ "Consulta la tabla est_01 con joins"   (describe la implementación, no la intención)
```

Reglas prácticas:

- Usar **los mismos términos que el usuario**, no los de la base de datos: "campo", no `tbl_predio`. Si el sistema usa dos nombres para lo mismo (campo/establecimiento), decirlo una vez en la descripción.
- **Encadenar tools** de forma explícita: "id obtenido con `listar_empresas`". El modelo sigue esas indicaciones al pie de la letra.
- Contar lo que **no** devuelve cuando el usuario podría esperarlo ("No devuelve geometrías", "solo campañas cerradas").
- Cada parámetro lleva `description` con unidad o formato cuando aplica (`"fecha_desde": "ISO 8601, p. ej. 2026-03-01"`). El verificador avisa de los que faltan.
- Usar `enum`, `format` (`uuid`, `date`), `minimum`/`maximum` y `required` en el schema: el sistema los valida y responde `parametros_invalidos`, y el modelo ve los valores permitidos.
- `additionalProperties: false`, para que un parámetro inventado se rechace en vez de ignorarse.

## 3. Parámetros

- **Pocos y opcionales.** Todo lo que pueda tener un valor por defecto razonable no debe ser obligatorio.
- **Ids como `string`**, opacos, aunque en la base sean enteros. Siempre se obtienen de otra tool; el modelo no debe adivinarlos.
- **Nunca pedir al modelo datos de seguridad** (usuario, empresa, rol): el sistema los saca del token. Un parámetro `usuario_id` invita a probar con el de otro.
- **Tratar todo parámetro como no confiable**: validar el tipo y comprobar que el recurso pertenece al usuario, como con cualquier input.

## 4. Qué devolver

El modelo lee todo lo que devuelve la tool y lo paga en tokens: más datos no significa mejores respuestas.

### Agregada y compacta

Resumir **del lado del sistema**. El modelo suma mal listas largas y se pierde en ellas.

```jsonc
// ✘ 3 000 filas para responder "¿cuál fue el rinde medio por cultivo?"
{ "ok": true, "datos": { "mediciones": [ {"lote": "A1", "kg": 1200, "...": "..."}, /* … */ ] } }

// ✔
{ "ok": true, "datos": { "rinde_medio_kg_ha_por_cultivo": [
    {"cultivo": "soja", "rinde_kg_ha": 3150.5, "lotes": 12},
    {"cultivo": "maíz", "rinde_kg_ha": 9800.0, "lotes": 7} ] },
  "fuente": "rendimientos" }
```

Si la lista puede ser larga, **limitar** (STMGIS corta en un `LIMITE` fijo) y decirlo en el resultado: `"total": 240, "mostrados": 50`. Así el modelo sabe que faltan filas y puede pedir un filtro más específico, en lugar de afirmar un total falso.

### Sin geometrías

Nada de GeoJSON, WKT ni coordenadas de polígonos: ocupan decenas de KB y no sirven para responder en texto. Devolver lo que se pregunta (superficie, centroide, cantidad de lotes) y dejar que `ui` lleve al usuario al mapa:

```jsonc
{ "ok": true,
  "datos": { "nombre": "El Matorral", "superficie_ha": 540.5, "lotes": 8 },
  "fuente": "establecimientos",
  "ui": [ { "tipo": "navegar", "url": "/establecimientos/1", "etiqueta": "Ver en el mapa" } ] }
```

El verificador avisa si detecta claves como `geometry` o `coordinates`.

### Nombres de campo con unidades

La unidad va **en el nombre**, no en la cabeza de quien lo escribió. Es lo que evita que el modelo diga "540 toneladas" donde eran hectáreas.

| Mal | Bien |
|---|---|
| `superficie: 540.5` | `superficie_ha: 540.5` (así está en el mock y en STMGIS) |
| `humedad: 14` | `humedad_minima_pct: 14` (STMGIS) |
| `rinde: 3.15` | `rinde_kg_ha: 3150` |
| `fecha: "03/10/26"` | `fecha_inicio: "2026-10-03"` (ISO 8601) |
| `precio: 12` | `precio_usd_t: 12` (moneda y base) |
| `activo: "S"` | `activo: true` |

Además: textos ya legibles (el nombre, no un código interno: devolver `"cultivo": "soja"`, no `"cultivo_id": 7`), números sin formato (`1200.5`, no `"1.200,5"`), y datos anidados solo si ayudan (`"empresa": {"id": "…", "nombre": "…"}` evita una segunda llamada).

### Qué más no devolver

- Campos que el modelo no necesita: ids internos, timestamps de auditoría, flags técnicos.
- Datos personales que la pregunta no requiere.
- Texto de usuarios sin acotar (observaciones libres largas): puede traer instrucciones que el modelo interprete como suyas.

### Tamaño

El asistente trunca por encima de un límite configurable (50 KB por defecto) y se lo indica al modelo, que entonces responde con información incompleta. Apuntar a **menos de 10 KB** por respuesta y a **menos de 3 s**. El verificador falla si se supera el tamaño o el `timeout_s` de la tool, y avisa a partir de la mitad.

## 5. Listados con filtro `texto` para resolver nombres

Los usuarios hablan de nombres ("el campo El Matorral") y las tools suelen necesitar ids. Para cada entidad principal, una tool de listado con filtro `texto` es el puente:

```jsonc
{ "nombre": "listar_establecimientos",
  "descripcion": "Lista los establecimientos que el usuario puede ver. Usar primero para resolver nombres a ids.",
  "parametros": { "type": "object",
    "properties": { "texto": { "type": "string", "description": "filtro por nombre" } },
    "additionalProperties": false },
  "efecto": "lectura" }
```

- `texto` opcional, filtra por nombre con "contiene" y **sin distinguir mayúsculas ni tildes**, si es posible.
- Siempre aplica los permisos del usuario: solo lista lo que él puede ver.
- Devuelve `id` y `nombre` más lo imprescindible para desambiguar (empresa, departamento). Si hay varios resultados, el modelo pregunta al usuario cuál.
- Las demás tools piden el `id` y lo documentan: `"id": "id del establecimiento (obtenido con listar_establecimientos)"`.
- No hace falta una tool de detalle por id si el listado ya trae lo necesario: STMGIS resuelve así sus cuatro entidades, con solo tools de listado.

## 6. Errores de negocio

Una tool que no puede dar el dato responde `200` con `ok: false`, un código del contrato y un `detalle` que el modelo pueda **leer y transmitir**:

| `error` | Cuándo | Ejemplo de `detalle` |
|---|---|---|
| `no_encontrado` | El id no existe **o** existe pero es de otro usuario | `"No existe o no tenés acceso"` |
| `sin_acceso` | El usuario no puede usar la tool | `"Usuario sin acceso al asistente"` |
| `parametros_invalidos` | Falta un parámetro, tipo incorrecto, formato inválido | `"`id` debe ser string"` |
| `no_disponible` | Tool desconocida o dato temporalmente inaccesible | `"El servicio de mapas no responde; probar más tarde"` |

```jsonc
// ✔ no revela si el id existe en otro usuario
{ "ok": false, "error": "no_encontrado", "detalle": "No existe o no tenés acceso" }

// ✘ filtra información y no ayuda
{ "ok": false, "error": "no_encontrado", "detalle": "El establecimiento 3 pertenece a beto" }
{ "ok": true,  "datos": {} }                      // "no hay datos" disfrazado de éxito
{ "ok": true,  "datos": {"error": "falló"} }      // error escondido en datos
```

- **Mismo mensaje** para "no existe" y "es de otro": quien prueba ids ajenos no debe aprender nada.
- **Lista vacía** es éxito (`"establecimientos": []`), no error; el modelo dice "no encontré".
- **Mensajes accionables**: qué falló y qué probar (`"texto" debe tener al menos 2 caracteres`).
- **Sin detalles internos**: nada de trazas, SQL ni rutas de archivos.
- `401` solo para token inválido o vencido; `403` solo para scope insuficiente o credencial de manifiesto usada donde no corresponde; `5xx` para fallos reales del sistema.

## 7. Checklist y verificación

Antes de habilitar una tool:

- [ ] Responde una pregunta real y se resuelve en 1 a 3 llamadas.
- [ ] Descripción con qué hace, cuándo usarla y qué devuelve; parámetros documentados.
- [ ] Schema estricto (`required`, `format`, `additionalProperties: false`).
- [ ] Unidades en los nombres de campo; fechas ISO 8601; ids como string.
- [ ] Sin geometrías; salida resumida y limitada; < 10 KB y < 3 s.
- [ ] Aplica permisos con el usuario del token; un id ajeno da `no_encontrado`.
- [ ] Errores de negocio con código y detalle legibles.

Y luego, el [verificador](../herramientas/verificar_sistema.py), que comprueba lo que se puede automatizar (manifiesto, autenticación, parámetros inválidos, ids ajenos, tamaños, tiempos, geometrías, descripciones cortas):

```sh
export V_MANIFIESTO=...    # token de manifiesto; los secretos van por entorno, nunca por argumentos
export V_SECRETO=...       # opcional: permite probar tokens vencidos / de otra audiencia / scope ajeno
python herramientas/verificar_sistema.py --base-url http://localhost:8201 \
    --token-url "http://localhost:8201/asistente/token?usuario=ana" \
    --token-url-otro "http://localhost:8201/asistente/token?usuario=beto" \
    --token-manifiesto-env V_MANIFIESTO --secreto-firma-env V_SECRETO
```

Si la ruta de token exige sesión, `--cabecera-token-env VAR` (con `VAR="Cookie: …"` o `"Authorization: …"`) la envía sin imprimirla. Las pruebas de ids ajenos necesitan una tool de lectura con un id obligatorio y otro usuario (`--token-url-otro` o `--id-ajeno`); si no, se informan como omitidas. Sale con código distinto de cero si algo falla. **Un sistema no se habilita en producción sin pasar el verificador.**
