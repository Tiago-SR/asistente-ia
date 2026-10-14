# Evals — deepseek-flash (2026-10-11_2115)

> registro=bd, antes de eliminar modo YAML

- **Aciertos:** 9/12 (75%)
- **Por categoría:** voz-agregado 1/2, voz-comparacion 0/1, voz-consulta 2/2, voz-largo 1/1, voz-no-disponible 1/1, voz-pregunta 1/1, voz-sin-datos 1/1, voz-tabla 2/3
- **Con cifras no respaldadas:** 0 · **errores del servicio:** 0
- **Iteraciones por pregunta (llamadas al LLM):** 2.08
- **Latencia:** mediana 2.69 s, p95 5.1 s
- **Tokens por pregunta:** {'tokens_in': 9210, 'tokens_out': 246, 'tokens_in_cache': 8640} · caché de entrada 93.8 %
- **Hasta el resumen hablado:** mediana 2.42 s, p95 4.35 s
- **Costo por pregunta (USD):** valle 0.000259 · pico 0.000518

## Fallos

### v03 (voz-agregado, ana): Dame un resumen de mi superficie por cultivo.
- el resumen hablado no es más corto que la respuesta (la lee entera)
- el resumen hablado lee demasiadas cifras: [870.0, 660.0, 210.0]
- Tools: ['resumen_por_cultivo']
- Resumen hablado: 'Tenés 870 hectáreas y media en total: la soja es el cultivo principal, con casi 660 hectáreas en dos establecimientos, y el maíz suma 210 en uno. El detalle está en pantalla.'
- Respuesta: '| Cultivo | Superficie (ha) | Establecimientos |\n|---|---|---|\n| Soja | 660,5 | 2 |\n| Maíz | 210 | 1 |\n| **Total** | **870,5** | **3** |'

### v06 (voz-comparacion, ana): Compará El Matorral con San Pedro.
- el resumen hablado lee demasiadas cifras: [540.5, 120.0, 420.0]
- Tools: ['listar_establecimientos', 'listar_establecimientos']
- Resumen hablado: 'El Matorral tiene 540,5 hectáreas y San Pedro 120, ambos de soja. El Matorral es el mayor por unos 420 hectáreas; la comparación está en pantalla.'
- Respuesta: '| Establecimiento | Superficie (ha) | Cultivo |\n|---|---|---|\n| El Matorral | 540,5 | soja |\n| San Pedro | 120 | soja |\n\nDiferencia: 420,5 ha más en El Matorral (unas 4,5 veces la superficie de San Pedro). Unidades en hectáreas, datos actuales del sistema.'

### v12 (voz-tabla, ana): Dame en una tabla las hectáreas por cultivo con su porcentaje.
- el resumen hablado lee demasiadas cifras: [660.0, 76.0, 210.0, 24.0, 870.0]
- Tools: ['resumen_por_cultivo']
- Resumen hablado: 'Tenés dos cultivos: la soja ocupa la mayor parte, unas 660 hectáreas, casi el 76 por ciento, y el maíz unas 210, cerca del 24 por ciento. El total es de 870 hectáreas y media; el detalle está en pantalla.'
- Respuesta: '| Cultivo | Hectáreas | % del total |\n|---|---|---|\n| Soja | 660,5 | 75,9 % |\n| Maíz | 210 | 24,1 % |\n| **Total** | **870,5** | **100 %** |\n\nSuperficie total: 870,5 ha (2 establecimientos de soja, 1 de maíz).'
