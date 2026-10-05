# Evals — deepseek-flash (2026-10-05_1420)

- **Aciertos:** 31/32 (97%)
- **Por categoría:** agregado 8/9, aislamiento 3/3, consulta 8/8, conversacion 2/2, robustez 1/1, sin_dato 7/7, solo_lectura 2/2
- **Con cifras no respaldadas:** 1 · **errores del servicio:** 0
- **Iteraciones por pregunta (llamadas al LLM):** 2.19
- **Latencia:** mediana 2.9 s, p95 6.02 s
- **Tokens por pregunta:** {'tokens_in': 2235, 'tokens_out': 227, 'tokens_in_cache': 1800} · caché de entrada 80.5 %
- **Costo por pregunta (USD):** valle 0.000207 · pico 0.000414

## Fallos

### q14 (agregado, ana): Compará El Matorral y San Pedro.
- cifra no respaldada: 420.5
- cifra no respaldada: 4.5
- Tools: ['listar_establecimientos', 'listar_establecimientos']
- Respuesta: 'Encontré ambos establecimientos sin ambigüedad:\n\n| Establecimiento | id | Superficie (ha) | Cultivo |\n|---|---|---|---|\n| El Matorral | 1 | 540,5 | soja |\n| San Pedro | 4 | 120 | soja |\n\nAmbos son de soja. El Matorral tiene 420,5 ha más que San Pedro (540,5 vs. 120 ha), es decir, es aproximadamente 4,5 veces más grande.\n\n¿Querés que compare también contra el total de tu superficie por cultivo?'
