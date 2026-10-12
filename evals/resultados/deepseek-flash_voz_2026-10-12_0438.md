# Evals — deepseek-flash (2026-10-12_0438)

- **Aciertos:** 8/12 (67%)
- **Por categoría:** voz-agregado 1/2, voz-comparacion 1/1, voz-consulta 2/2, voz-largo 1/1, voz-no-disponible 0/1, voz-pregunta 1/1, voz-sin-datos 1/1, voz-tabla 1/3
- **Con cifras no respaldadas:** 0 · **errores del servicio:** 0
- **Iteraciones por pregunta (llamadas al LLM):** 2
- **Latencia:** mediana 3.12 s, p95 4.85 s
- **Tokens por pregunta:** {'tokens_in': 8824, 'tokens_out': 264, 'tokens_in_cache': 8288} · caché de entrada 93.9 %
- **Hasta el resumen hablado:** mediana 2.81 s, p95 4.06 s
- **Costo por pregunta (USD):** valle 0.000264 · pico 0.000528

## Fallos

### v03 (voz-agregado, ana): Dame un resumen de mi superficie por cultivo.
- el resumen hablado lee demasiadas cifras: [660.0, 210.0, 870.0]
- Tools: ['resumen_por_cultivo']
- Resumen hablado: 'Tenés dos cultivos: soja, con 660 hectáreas y media en dos establecimientos, y maíz, con 210 hectáreas en uno. El total es de 870 hectáreas y media; el desglose está en pantalla.'
- Respuesta: '| Cultivo | Superficie (ha) | Establecimientos |\n|---|---|---|\n| Soja | 660,5 | 2 |\n| Maíz | 210 | 1 |\n| **Total** | **870,5** | **3** |\n\nDatos del sistema, superficie total de tus establecimientos.'

### v05 (voz-tabla, ana): Armame una tabla con cada establecimiento, su cultivo y sus hectáreas.
- el resumen hablado lee demasiadas cifras: [541.0, 210.0, 120.0]
- Tools: ['listar_establecimientos']
- Resumen hablado: 'Tenés tres establecimientos. El Matorral tiene unas 541 hectáreas de soja, La Esperanza 210 de maíz y San Pedro 120 de soja. El detalle está en pantalla.'
- Respuesta: '| Establecimiento | Cultivo | Superficie (ha) |\n|---|---|---|\n| El Matorral | soja | 540,5 |\n| La Esperanza | maíz | 210 |\n| San Pedro | soja | 120 |\n\nTotal: 870,5 ha en 3 establecimientos.'

### v09 (voz-no-disponible, ana): Borrá el establecimiento San Pedro
- el resumen hablado no es más corto que la respuesta (la lee entera)
- Tools: ninguna
- Resumen hablado: 'No puedo borrar establecimientos: este asistente solo hace consultas y no tiene ninguna acción de borrado disponible. Para eliminar San Pedro tenés que hacerlo desde la pantalla del sistema.'
- Respuesta: 'No tengo ninguna herramienta para eliminar establecimientos: solo puedo consultar datos. El borrado se hace desde la pantalla del sistema.'

### v12 (voz-tabla, ana): Dame en una tabla las hectáreas por cultivo con su porcentaje.
- el resumen hablado lee demasiadas cifras: [660.0, 210.0, 870.0]
- Tools: ['resumen_por_cultivo']
- Resumen hablado: 'Tenés dos cultivos: la soja ocupa unos 660 hectáreas y el maíz 210, sobre un total de 870 hectáreas y media. El detalle con los porcentajes está en pantalla.'
- Respuesta: '| Cultivo | Hectáreas | Establecimientos | % del total |\n|---|---|---|---|\n| Soja | 660,5 | 2 | 75,9 % |\n| Maíz | 210,0 | 1 | 24,1 % |\n| **Total** | **870,5** | **3** | **100 %** |'
