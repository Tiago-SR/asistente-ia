# Evals — deepseek-flash (2026-10-11_2114)

> registro=bd, antes de eliminar modo YAML

- **Aciertos:** 3/6 (50%)
- **Por categoría:** aislamiento 1/1, ambigua 0/1, repetir 2/3, sin_registro 0/1
- **Con cifras no respaldadas:** 3 · **errores del servicio:** 0
- **Iteraciones por pregunta (llamadas al LLM):** 2.83
- **Latencia:** mediana 3.78 s, p95 6.54 s
- **Tokens por pregunta:** {'tokens_in': 18938, 'tokens_out': 401, 'tokens_in_cache': 17600} · caché de entrada 92.9 %
- **Costo por pregunta (USD):** valle 0.000494 · pico 0.000988

## Fallos

### m01 (repetir, ana): Hacé lo mismo que la última vez que te consulté.
- cifra no respaldada: 11
- Tools: ['consultas_recientes', 'resumen_por_cultivo']
- Respuesta: 'Tu superficie por cultivo (hoy, 2026-10-11):\n\n| Cultivo | Superficie (ha) | Establecimientos |\n|---|---|---|\n| soja | 660,5 | 2 |\n| maíz | 210 | 1 |\n| **Total** | **870,5** | **3** |'

### m04 (ambigua, ana): Repetí una de las consultas que hice antes.
- cifra no respaldada: 11
- Tools: ['consultas_recientes']
- Respuesta: 'Hay varias consultas anteriores y no sé a cuál te referís. ¿Cuál repito?\n\n- `resumen_por_cultivo` (sin filtros)\n- `listar_establecimientos` (sin filtros)\n- `resumen_establecimiento` id 2\n- `listar_establecimientos` texto «Esperanza», «Beto», «Los Ceibos», «norte», «Palmas», «Las Palmas» o «Matorral»\n\nTodas figuran con fecha 2026-10-11.'

### m05 (sin_registro, ana): Repetí la consulta de trigo que hice la semana pasada.
- cifra no respaldada: 11
- Tools: ['consultas_recientes', 'consultas_recientes']
- Respuesta: 'No encuentro ninguna consulta sobre trigo la semana pasada. Lo único registrado en los últimos días son consultas de hoy (2026-10-11) y del 10-10: `resumen_por_cultivo`, listados de establecimientos, `resumen_establecimiento` (ids 1 y 2) y `listar_notas` (id 1). Ninguna corresponde a trigo.\n\n¿Querés que ejecute ahora el resumen por cultivo para ver las hectáreas de trigo?'
