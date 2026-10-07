# Ideas pendientes: panel de ajustes del widget

El panel (engranaje) ya tiene motor de voz, volumen, lectura automática, acuse, «probar voz» y «restablecer». Solo quedan estas ideas, ninguna decidida.

## Ideas

- Velocidad (rate) y tono (pitch) de la voz; el tono solo con Web Speech.
- Elegir la voz concreta (lista de voces del navegador o de ElevenLabs).
- Idioma de voz y de reconocimiento (hoy sale de `locale_defecto` por sistema).
- Modo de entrada: pulsar para hablar o manos libres.
- Tamaño de letra, tema claro u oscuro y alto contraste.
- Sincronizar los ajustes en el servidor por usuario (hoy solo `localStorage`).

## Preguntas abiertas

- ¿Qué ajustes fija el administrador del sistema y cuáles deja libres al usuario (por ejemplo, ElevenLabs tiene costo)?
- ¿Se persiste solo en el navegador o también en el servidor por usuario?
