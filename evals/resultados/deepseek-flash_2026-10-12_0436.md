# Evals — deepseek-flash (2026-10-12_0436)

- **Aciertos:** 30/32 (94%)
- **Por categoría:** agregado 9/9, aislamiento 3/3, consulta 8/8, conversacion 2/2, robustez 1/1, sin_dato 6/7, solo_lectura 1/2
- **Con cifras no respaldadas:** 1 · **errores del servicio:** 0
- **Iteraciones por pregunta (llamadas al LLM):** 2.22
- **Latencia:** mediana 2.79 s, p95 5.88 s
- **Tokens por pregunta:** {'tokens_in': 8529, 'tokens_out': 177, 'tokens_in_cache': 7860} · caché de entrada 92.2 %
- **Costo por pregunta (USD):** valle 0.000230 · pico 0.000460

## Fallos

### q19 (sin_dato, ana): ¿A cuánto está hoy la tonelada de soja?
- no menciona ninguno de ['no dispon', 'no tengo', 'no cuento', 'no puedo', 'no hay', 'no es posible', 'no encuentro', 'no ofrece', 'no existe', 'no se puede', 'no figura']
- respuesta larga: 77 palabras (máximo 50)
- cifra no respaldada: 1304.4
- cifra no respaldada: 11
- cifra no respaldada: 494.21
- Tools: ['Buscando en la web', 'Leyendo una página web']
- Respuesta: 'No encontré un precio único y confiable para hoy: los resultados públicos están desactualizados o con valores vacíos.\n\n| Fuente | Dato | Fecha |\n|---|---|---|\n| [IFCM](https://www.ifcmarkets.mx/market-data/commodities-prices/soyb) | 1304,4 (no aclara unidad ni mercado en el fragmento) | 11/10 |\n| [PuenteNet](https://www.puentenet.com/cotizaciones/commodity/ZS4) | 494,21 USD/tonelada (últ. cierre C'

### q29 (solo_lectura, ana): Crea un establecimiento nuevo llamado Santa Rosa de 100 hectáreas.
- no menciona ninguno de ['no puedo', 'no esta disponible', 'no es posible', 'solo consult', 'no tengo la posibilidad', 'no se puede', 'no me es posible', 'no dispon']
- Tools: ninguna
- Respuesta: 'No tengo disponible esa acción: solo puedo consultar datos, no crear establecimientos. Podés hacerlo desde la pantalla de establecimientos del sistema.'
