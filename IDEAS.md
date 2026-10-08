# Ideas pendientes

Ideas sin decidir ni implementar. Lo ya hecho está en el README y el contrato.

## Acciones con confirmación (Fase 5)

- **Deshacer (`reversible_con`).** Si una tool lo declara, la tarjeta podría ofrecer «Deshacer» con la misma maquinaria (propuesta, confirmación y token propio). Sin promesa en el contrato.
- **No se hará:** borrar (el asistente rechaza tools destructivas), confirmar por voz (siempre en pantalla) y acciones masivas, encadenadas o iniciadas por el sistema (esto último es la Fase 6).

## Panel de ajustes del widget

- Tono (pitch) de la voz: solo tiene efecto en voces locales del navegador (la de Google en Chrome probablemente lo ignora) y no hay forma simple con la voz del servidor.
- Elegir la voz concreta de la **voz del navegador** (la del servidor ya se elige: `config/voces.yaml`). Por sistema: hoy el catálogo es global.
- Idioma de voz y de reconocimiento (hoy sale de `locale_defecto` por sistema).
- Modo de entrada: pulsar para hablar o manos libres.
- Tamaño de letra, tema claro u oscuro y alto contraste.
- Sincronizar los ajustes en el servidor por usuario (hoy solo `localStorage`).

Preguntas abiertas:

- ¿Qué ajustes fija el administrador del sistema y cuáles deja libres al usuario (por ejemplo, ElevenLabs tiene costo)?
- ¿Se persiste solo en el navegador o también en el servidor por usuario?
