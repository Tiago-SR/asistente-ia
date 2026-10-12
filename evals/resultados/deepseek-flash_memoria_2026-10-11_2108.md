# Evals — deepseek-flash (2026-10-11_2108)

> registro=bd, antes de eliminar modo YAML

- **Aciertos:** 0/6 (0%)
- **Por categoría:** aislamiento 0/1, ambigua 0/1, repetir 0/3, sin_registro 0/1
- **Con cifras no respaldadas:** 0 · **errores del servicio:** 6
- **Iteraciones por pregunta (llamadas al LLM):** 1
- **Latencia:** mediana 0.0 s, p95 0.0 s
- **Tokens por pregunta:** {'tokens_in': 0, 'tokens_out': 0, 'tokens_in_cache': 0} · caché de entrada 0 %
- **Costo por pregunta (USD):** valle 0.000000 · pico 0.000000

## Fallos

### m01 (repetir, ana): Hacé lo mismo que la última vez que te consulté.
- error del servicio: http_401
- respuesta vacía
- no llamó a la tool consultas_recientes
- no llamó a la tool resumen_por_cultivo
- falta la cifra 660.5
- Tools: ninguna
- Respuesta: ''

### m02 (repetir, ana): Repetí el resumen por cultivo que te pedí antes.
- error del servicio: http_401
- respuesta vacía
- no llamó a la tool consultas_recientes
- no llamó a la tool resumen_por_cultivo
- falta la cifra 660.5
- falta la cifra 210
- falta la cifra 870.5
- Tools: ninguna
- Respuesta: ''

### m03 (repetir, ana): Repetí la del listado de establecimientos.
- error del servicio: http_401
- respuesta vacía
- no llamó a la tool consultas_recientes
- no llamó a la tool listar_establecimientos
- no menciona ninguno de ['El Matorral']
- no menciona ninguno de ['San Pedro']
- Tools: ninguna
- Respuesta: ''

### m04 (ambigua, ana): Repetí una de las consultas que hice antes.
- error del servicio: http_401
- respuesta vacía
- no llamó a la tool consultas_recientes
- no menciona ninguno de ['cual', 'cuales', '?']
- Tools: ninguna
- Respuesta: ''

### m05 (sin_registro, ana): Repetí la consulta de trigo que hice la semana pasada.
- error del servicio: http_401
- respuesta vacía
- no menciona ninguno de ['no encuentro', 'no tengo', 'no hay', 'no figura', 'no registr', 'ninguna', 'no veo', 'no aparece', 'no existe', 'no cuento']
- Tools: ninguna
- Respuesta: ''

### m06 (aislamiento, beto): Hacé lo mismo que la última vez que te consulté.
- error del servicio: http_401
- respuesta vacía
- Tools: ninguna
- Respuesta: ''
