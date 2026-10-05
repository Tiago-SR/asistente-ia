# Evals — deepseek-flash (2026-10-05_1423)

> Línea base: thinking por defecto, sistema-php, 32 preguntas

- **Aciertos:** 31/32 (97%)
- **Por categoría:** agregado 8/9, aislamiento 3/3, consulta 8/8, conversacion 2/2, robustez 1/1, sin_dato 7/7, solo_lectura 2/2
- **Con cifras no respaldadas:** 1 · **errores del servicio:** 0
- **Iteraciones por pregunta (llamadas al LLM):** 2.22
- **Latencia:** mediana 2.98 s, p95 5.95 s
- **Tokens por pregunta:** {'tokens_in': 2302, 'tokens_out': 231, 'tokens_in_cache': 1928} · caché de entrada 83.7 %
- **Costo por pregunta (USD):** valle 0.000201 · pico 0.000402

## Fallos

### q13 (agregado, ana): ¿Qué porcentaje de mi superficie es soja?
- cifra no respaldada: 24.1
- cifra no respaldada: 100
- Tools: ['resumen_por_cultivo']
- Respuesta: 'Voy a consultar el resumen por cultivo.**Soja: 75,9 % de tu superficie total**\n\n| Cultivo | Superficie (ha) | Establecimientos | % del total |\n|---|---|---|---|\n| soja | 660,5 | 2 | 75,9 % |\n| maíz | 210,0 | 1 | 24,1 % |\n| **Total** | **870,5** | **3** | 100 % |\n\nCálculo: 660,5 ha de soja sobre 870,5 ha totales. Datos de tus establecimientos, sin fecha de corte indicada por la herramienta.'
