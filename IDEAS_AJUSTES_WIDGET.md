# Ideas: panel de ajustes en el widget (engranaje)

Solo ideas, nada decidido ni implementado.

## Concepto

Un icono de engranaje en el widget que abre un panel pequeño con ajustes
del usuario. Se guardan por navegador (localStorage) y, si hay memoria por
usuario, podrían sincronizarse con las preferencias del usuario.

## Ajustes iniciales

- **Motor de texto a voz**: Google (Web Speech del navegador) o ElevenLabs.
  - ElevenLabs ya existe en `core/voz/elevenlabs.py`; el widget debería
    poder elegir cuál usar por sesión.
  - Mostrar solo los motores que el servidor tenga habilitados (el endpoint de
    estado/config indica cuáles hay).
  - Si ElevenLabs falla o se agota la cuota, caer a Google sin romper la voz.
- **Volumen del audio**: slider 0–100 %, aplicado a la reproducción de la
  respuesta hablada (y al acuse inmediato).

## Ideas a futuro

- Velocidad de la voz (rate) y tono (pitch, solo Web Speech).
- Elegir la voz concreta (lista de voces del navegador / de ElevenLabs).
- Idioma de voz y de reconocimiento (hoy sale de `locale_defecto` por sistema).
- Botón "probar voz" con una frase de ejemplo.
- Activar/desactivar la lectura automática de respuestas.
- Activar/desactivar el acuse inmediato ("estoy consultando...").
- Modo de entrada: pulsar para hablar vs. manos libres.
- Tamaño de letra / tema claro-oscuro / alto contraste.
- Ver y borrar lo que el asistente recuerda (enlaza con el panel de memoria).
- Restablecer ajustes a los valores por defecto.

## Preguntas abiertas

- ¿Qué ajustes puede fijar el administrador del sistema y cuáles deja libres
  al usuario (por ejemplo, ElevenLabs tiene costo)?
- ¿Se persiste solo en el navegador o también en el servidor por usuario?
- ¿Cómo se refleja el costo de ElevenLabs en `/admin/uso` si el usuario elige
  ese motor?
- Accesibilidad: el panel debe ser operable con teclado y lector de pantalla.
