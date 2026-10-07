# Fase 5: lo que queda por hacer

La Fase 5 (acciones con confirmación: el modelo propone, el usuario confirma en pantalla, el sistema ejecuta con un token de un solo uso) está implementada. Lo normativo está en la sección 8 de [`contrato/CONTRATO.md`](contrato/CONTRATO.md). Aquí solo queda lo pendiente.

## Pendiente

- **Una acción real de SGAgro.** Elegir cuál (la primera) e implementarla en su sistema, con `propuesta`, token de escritura y ejecución idempotente (ver `contrato/IMPLEMENTAR.md` y `ejemplos/sistema-php`). Hoy solo existen las notas de ejemplo (agregar y modificar). Si es una modificación, la propuesta debe mostrar el valor anterior y el nuevo, y el sistema rechazarla si el dato cambió desde la propuesta.
- **Deshacer (`reversible_con`), opcional.** Fuera de la primera entrega y sin promesa en el contrato. Si una tool lo declara, la tarjeta podría ofrecer «Deshacer» con la misma maquinaria (propuesta, confirmación y token propio).

## Decisiones firmes (no hacer)

- Borrar: el asistente rechaza `acciones_habilitadas` con tools marcadas como destructivas.
- Confirmar por voz: la confirmación es siempre en pantalla, también en modo voz.
- Acciones masivas, encadenadas o iniciadas por el sistema (esto último es la Fase 6).
