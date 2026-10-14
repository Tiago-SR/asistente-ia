# Evals — deepseek-flash (2026-10-12_0438)

- **Aciertos:** 5/6 (83%)
- **Por categoría:** aislamiento 1/1, ambigua 1/1, repetir 2/3, sin_registro 1/1
- **Con cifras no respaldadas:** 1 · **errores del servicio:** 0
- **Iteraciones por pregunta (llamadas al LLM):** 2.83
- **Latencia:** mediana 4.52 s, p95 7.68 s
- **Tokens por pregunta:** {'tokens_in': 18944, 'tokens_out': 454, 'tokens_in_cache': 17579} · caché de entrada 92.8 %
- **Costo por pregunta (USD):** valle 0.000530 · pico 0.001060

## Fallos

### m02 (repetir, ana): Repetí el resumen por cultivo que te pedí antes.
- cifra no respaldada: 12
- Tools: ['consultas_recientes', 'resumen_por_cultivo']
- Respuesta: 'Superficie por cultivo (hoy, 2026-10-12):\n\n| Cultivo | Establecimientos | Superficie (ha) |\n|---|---|---|\n| soja | 2 | 660,5 |\n| maíz | 1 | 210 |\n| **Total** | | **870,5** |'
