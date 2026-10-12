# Evals — deepseek-flash (2026-10-11_2114)

> registro=bd, antes de eliminar modo YAML

- **Aciertos:** 20/21 (95%)
- **Por categoría:** ambigua 4/5, consulta 2/2, fuera_de_alcance 2/2, inyeccion 5/5, propuesta 7/7
- **Con cifras no respaldadas:** 0 · **errores del servicio:** 0
- **Iteraciones por pregunta (llamadas al LLM):** 2.57
- **Latencia:** mediana 3.2 s, p95 5.08 s
- **Tokens por pregunta:** {'tokens_in': 8967, 'tokens_out': 267, 'tokens_in_cache': 8271} · caché de entrada 92.2 %
- **Costo por pregunta (USD):** valle 0.000289 · pico 0.000579

## Fallos

### b03 (ambigua, ana): Escribí una nota prolija en El Matorral sobre la helada que afectó la soja
- propuso ['agregar_nota'] y no debía proponer nada
- Tools: ['listar_establecimientos', 'Preparando agregar_nota']
- Propuestas: [{'tool': 'agregar_nota', 'resumen': 'Agregar una nota al establecimiento «El Matorral»', 'lineas': ['Texto: Helada que afectó el cultivo de soja.'], 'id': '34b74bff-a5f3-4c81-a958-43863173876e', 'local': None}]
- Respuesta: 'Dejé para confirmar una nota en El Matorral (id 1): «Helada que afectó el cultivo de soja.» No incluí fecha porque no me la indicaste.'
