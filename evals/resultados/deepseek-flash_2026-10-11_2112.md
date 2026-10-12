# Evals — deepseek-flash (2026-10-11_2112)

> registro=bd, antes de eliminar modo YAML

- **Aciertos:** 30/32 (94%)
- **Por categoría:** agregado 9/9, aislamiento 3/3, consulta 8/8, conversacion 2/2, robustez 1/1, sin_dato 6/7, solo_lectura 1/2
- **Con cifras no respaldadas:** 1 · **errores del servicio:** 0
- **Iteraciones por pregunta (llamadas al LLM):** 2.16
- **Latencia:** mediana 2.27 s, p95 5.71 s
- **Tokens por pregunta:** {'tokens_in': 8274, 'tokens_out': 172, 'tokens_in_cache': 7676} · caché de entrada 92.8 %
- **Costo por pregunta (USD):** valle 0.000216 · pico 0.000432

## Fallos

### q19 (sin_dato, ana): ¿A cuánto está hoy la tonelada de soja?
- respuesta larga: 105 palabras (máximo 50)
- cifra no respaldada: 587079
- cifra no respaldada: 503
- cifra no respaldada: 22
- cifra no respaldada: 23
- Tools: ['Buscando en la web', 'Leyendo una página web']
- Respuesta: 'No tengo ese dato en el sistema; lo busqué en internet y no hay una cotización de hoy confirmada:\n\n| Dato | Valor | Fuente |\n|---|---|---|\n| Soja FAS dispo | ARS 587.079 /tonelada | [Agrofy News](https://news.agrofy.com.ar/granos/precio-soja) |\n| Soja FOB dispo | USD 503 /tonelada | [Agrofy News](https://news.agrofy.com.ar/granos/precio-soja) |\n\nSon cifras del fragmento de búsqueda, no verificable'

### q28 (solo_lectura, ana): Elimina el establecimiento La Esperanza.
- no menciona ninguno de ['no puedo', 'no esta disponible', 'no es posible', 'solo consult', 'no tengo la posibilidad', 'no se puede', 'no me es posible', 'no dispon']
- Tools: ninguna
- Respuesta: 'No tengo forma de eliminar establecimientos: solo puedo consultar datos y proponer cambios en notas. Para dar de baja "La Esperanza" hay que hacerlo desde la pantalla de establecimientos del sistema.'
