# Evals — deepseek-flash (2026-10-11_2108)

> registro=bd, antes de eliminar modo YAML

- **Aciertos:** 0/12 (0%)
- **Por categoría:** voz-agregado 0/2, voz-comparacion 0/1, voz-consulta 0/2, voz-largo 0/1, voz-no-disponible 0/1, voz-pregunta 0/1, voz-sin-datos 0/1, voz-tabla 0/3
- **Con cifras no respaldadas:** 0 · **errores del servicio:** 12
- **Iteraciones por pregunta (llamadas al LLM):** 1
- **Latencia:** mediana 0.0 s, p95 0.0 s
- **Tokens por pregunta:** {'tokens_in': 0, 'tokens_out': 0, 'tokens_in_cache': 0} · caché de entrada 0 %
- **Costo por pregunta (USD):** valle 0.000000 · pico 0.000000

## Fallos

### v01 (voz-consulta, ana): ¿Qué establecimientos tengo?
- error del servicio: http_401
- respuesta vacía
- no llamó a la tool listar_establecimientos
- no menciona ninguno de ['El Matorral']
- no menciona ninguno de ['La Esperanza']
- no menciona ninguno de ['San Pedro']
- Tools: ninguna
- Respuesta: ''

### v02 (voz-consulta, ana): ¿Cuántas hectáreas tiene El Matorral?
- error del servicio: http_401
- respuesta vacía
- falta la cifra 540.5
- Tools: ninguna
- Respuesta: ''

### v03 (voz-agregado, ana): Dame un resumen de mi superficie por cultivo.
- error del servicio: http_401
- respuesta vacía
- no llamó a la tool resumen_por_cultivo
- falta la cifra 660.5
- falta la cifra 210
- falta la cifra 870.5
- Tools: ninguna
- Respuesta: ''

### v04 (voz-agregado, ana): ¿Cuántas hectáreas de soja tengo?
- error del servicio: http_401
- respuesta vacía
- no llamó a la tool resumen_por_cultivo
- falta la cifra 660.5
- Tools: ninguna
- Respuesta: ''

### v05 (voz-tabla, ana): Armame una tabla con cada establecimiento, su cultivo y sus hectáreas.
- error del servicio: http_401
- respuesta vacía
- no llamó a la tool listar_establecimientos
- falta la cifra 540.5
- falta la cifra 210
- falta la cifra 120
- Tools: ninguna
- Respuesta: ''

### v06 (voz-comparacion, ana): Compará El Matorral con San Pedro.
- error del servicio: http_401
- respuesta vacía
- falta la cifra 540.5
- falta la cifra 120
- Tools: ninguna
- Respuesta: ''

### v07 (voz-sin-datos, ana): ¿Cuántas hectáreas tengo de girasol?
- error del servicio: http_401
- respuesta vacía
- Tools: ninguna
- Respuesta: ''

### v08 (voz-pregunta, ana): Mostrame los datos de Los Ceibos
- error del servicio: http_401
- respuesta vacía
- Tools: ninguna
- Respuesta: ''

### v09 (voz-no-disponible, ana): Borrá el establecimiento San Pedro
- error del servicio: http_401
- respuesta vacía
- Tools: ninguna
- Respuesta: ''

### v10 (voz-largo, ana): Explicame con detalle cómo está repartida mi superficie entre cultivos y establecimientos.
- error del servicio: http_401
- respuesta vacía
- no llamó a la tool resumen_por_cultivo
- falta la cifra 660.5
- falta la cifra 210
- Tools: ninguna
- Respuesta: ''

### v11 (voz-tabla, ana): Hacé una tabla con cada establecimiento, su cultivo, sus hectáreas y el porcentaje del total.
- error del servicio: http_401
- respuesta vacía
- no llamó a la tool listar_establecimientos
- falta la cifra 540.5
- falta la cifra 210
- falta la cifra 120
- Tools: ninguna
- Respuesta: ''

### v12 (voz-tabla, ana): Dame en una tabla las hectáreas por cultivo con su porcentaje.
- error del servicio: http_401
- respuesta vacía
- no llamó a la tool resumen_por_cultivo
- falta la cifra 660.5
- falta la cifra 210
- falta la cifra 870.5
- Tools: ninguna
- Respuesta: ''
