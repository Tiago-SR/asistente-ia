# OpenWA: reducir el riesgo de que bloqueen el número (plan, NO implementado)

Estado: **anotado el 2026-11-09, sin decidir ni implementar**. Es una lista de ideas ordenadas por rendimiento/costo para
discutir; nada de esto está en el código salvo lo que se marca como «hoy».

OpenWA maneja WhatsApp Web, que no es oficial: WhatsApp puede restringir o bloquear el número sin aviso y sin
apelación práctica. No hay forma de **garantizar** que no pase; el objetivo es no parecer un bot masivo y poder
**degradar con gracia** (parar y avisar) si empieza a pasar. Si el canal es crítico para el negocio, la salida real es
Meta (ver sección 8).

> Alcance: este documento es para proteger **un número propio que envía mensajes de servicio a usuarios que ya
> aceptaron recibirlos** (escribieron `VINCULAR`). No es para evadir bloqueos de un uso abusivo, ni para rotar números.
> Rotar números para esquivar un bloqueo **no se recomienda**: es evasión y empeora la reputación.

## 1. Qué mira WhatsApp (hipótesis; no documentado oficialmente)

Estas señales son las que la experiencia general con clientes no oficiales indica que pesan. No están verificadas por
WhatsApp, tomarlas como hipótesis:

- **Ráfagas**: muchos mensajes en poco tiempo, o a intervalos perfectamente regulares.
- **Contactos nuevos**: escribir primero a números con los que no hay chat previo, sobre todo muchos seguidos.
- **Bajo ratio de respuesta**: enviar mucho y que casi nadie conteste. Y al revés: que contesten y sea bueno.
- **Reportes y bloqueos de los destinatarios** (la señal más fuerte).
- **Texto idéntico** a muchos destinatarios.
- **Cuenta joven / sin historial**, número virtual o sin foto/nombre, sesiones que se reconectan sin parar.
- **Actividad inhumana**: 24/7, sin pausas, respuesta instantánea siempre, sin «escribiendo…», sin leído.
- **Cliente no oficial detectable** (versión del protocolo/huella de OpenWA): fuera de nuestro control.

## 2. Cómo está hoy (verificado en el código)

| Aspecto | Hoy | Dónde |
|---|---|---|
| Espaciado de **avisos** del sistema | 8–20 s con jitter (`pausa_min_s`/`pausa_max_s`) | `AvisosConfig`, `avisos_flujo.procesar_uno` |
| Topes de avisos | 20/día por número, 200/día por sistema (ventana móvil 24 h) | `AvisosConfig` |
| Cola pendiente por número | máx. 50 (429 a partir de ahí) | `max_pendientes_numero` |
| Caducidad de un aviso en cola | 48 h → `vencido` | `caducidad_h` |
| Reintentos | solo si «no se envió» seguro; incierto no se reintenta; backoff 1 min × 2ⁿ | `avisos_flujo._enviar` |
| **Respuestas** de chat | espera aleatoria 1–5 s (+3–5 s si la conversación está activa) y, si no, un acuse previo | `canal_flujo._turno` |
| Entrada | 20/min y 300/día por número; 600/min y 10 000/día por sistema; después, silencio | `canal_flujo._cupo` |
| Un envío a la vez **por número** | lock por `(sistema, contacto)` | `canal_flujo.candado` |

### Huecos (lo que NO hay)

1. **No hay una cola de salida común.** El espaciado de los avisos solo cuenta **avisos** (`ultimo_envio` sale de la
   tabla `avisos`). Las respuestas de chat no pasan por esa cola ni cuentan en ese espaciado: cada turno duerme su
   propio 1–5 s y envía. Varios usuarios escribiendo a la vez generan **ráfagas simultáneas** desde el mismo número, y un
   aviso puede salir pegado a respuestas.
2. **No hay tope de salida total por número/sesión**, solo de avisos. Un día con mucho chat + avisos no tiene techo.
3. **El acuse duplica los mensajes** («un momento…» + la respuesta) para quien no estaba activo.
4. **No hay «escribiendo…» ni «leído»**. Un humano los produce; hoy el mensaje aparece de golpe.
5. **No distingue chats nuevos de conversaciones existentes**: un aviso a un número que nunca escribió (si el vínculo
   existiera sin chat) cuenta igual que una respuesta.
6. **No hay disyuntor**: si OpenWA empieza a devolver errores raros, desconexiones o `no_enviado`, el worker sigue
   intentando con backoff por aviso, no frena toda la sesión.
7. **No hay horario**: puede enviar a las 3 a. m.
8. **No hay calentamiento**: un número recién vinculado usa los mismos topes que uno con meses.
9. **Sin telemetría de salud** del número (ratio enviados/respondidos, desconexiones, fallos por hora) ni alerta.

## 3. Idea central: UNA cola de salida por sesión (número)

Todo lo que sale por un número pasa por **una sola cola** con un único «despachador» por sesión de OpenWA. Respuestas
de chat, acuses y avisos son «trabajos de salida» con prioridad. Así el espaciado, los topes y el disyuntor valen para
**todo** y no hay carreras entre las dos vías.

```
 chat entrante ──► turno ──► texto ──┐
 aviso del sistema ──────────────────┼──► salidas (cola durable) ──► despachador ──► OpenWA
 acuse / botones / documento ────────┘     prioridad, topes, pausas     1 a la vez por sesión
```

### 3.1 Modelo (esquema orientativo)

Tabla `salidas` (o generalizar `avisos`): `id`, `sistema_id`, `sesion` (número), `wa_id`, `tipo`
(`respuesta|acuse|aviso|documento`), `prioridad`, `payload`, `no_antes_de`, `caduca_en`, `estado`
(`pendiente|enviando|enviado|fallido|incierto`), `intentos`, `lease_hasta`. Reutiliza lo que ya existe de avisos:
`FOR UPDATE SKIP LOCKED`, lease, `incierto` sin reintento, persistir-antes-de-confirmar.

**Decisión abierta:** las respuestas de chat hoy son síncronas dentro del turno (esperan el id del mensaje y siguen con
botones/documentos). Encolarlas exige que el turno **no espere** el envío real o que espere el resultado de la cola
con timeout. Alternativa más barata: mantener el envío inline pero **adquirir un «turno de envío»** (un semáforo
distribuido por sesión con pausa mínima) antes de llamar a OpenWA; da el 80 % del beneficio sin reescribir el turno.

### 3.2 Reglas del despachador

- **Una sola salida a la vez por sesión** (lock por sesión, no solo por contacto).
- **Pausa mínima global** entre envíos de la sesión con jitter, p. ej. 3–8 s entre respuestas y 10–25 s entre avisos.
  Configurable. Las pausas **no son uniformes**: distribución con cola larga (a veces 30–90 s), no un rango plano.
- **Pausa por chat**: no dos mensajes seguidos al mismo contacto en menos de N s (salvo respuesta+resultado del mismo
  turno).
- **Prioridad**: respuesta a alguien que **acaba de escribir** > acuse > aviso saliente > resultado de cortesía. Los
  avisos ceden ante el chat humano, nunca al revés.
- **Topes por sesión** (ventanas móviles): por hora y por día, **totales** y **por tipo** (avisos aparte), más topes por
  contacto. Lo que no cabe espera en cola hasta `caduca_en`.
- **Contrapresión**: cola larga ⇒ 429 al productor (ya existe para avisos) y, en el chat, un mensaje honesto
  («estoy con muchas consultas, te respondo en unos minutos») en vez de silencio o de ráfaga.

## 4. Chats nuevos / primer contacto en cola

Es lo que pediste explícitamente. Hay dos casos distintos:

1. **Un usuario nuevo escribe `VINCULAR <código>`** (entrante). Es la situación de menor riesgo (la persona inició el
   chat). La respuesta («Listo, …») debe pasar igualmente por la cola, con pausa aleatoria y, si hay varios en un rato,
   escalonada.
2. **El sistema inicia contacto** (un aviso a alguien sin conversación reciente con el número). Es el caso de **mayor
   riesgo**. Ideas:
   - **Solo avisar a quien escribió primero** (ya se exige el `VINCULAR`) **y** dentro de una ventana razonable de
     actividad (p. ej. escribió en los últimos N días); si no, **no se envía por WhatsApp** y queda en la bandeja web
     (la web ya es la fuente de verdad).
   - **Tope aparte para «contactos fríos»** (sin mensaje entrante reciente): muy bajo (p. ej. 3–5 por día en total) y
     solo en horario hábil.
   - **Escalonar altas**: un máximo de usuarios nuevos activados por día en el número (rampa), el resto espera.
   - **Mensaje de bienvenida corto** que explique qué esperar y cómo darse de baja (`BAJA`), para que no lo reporten
     como spam.

## 5. Lista de ideas (de mayor a menor rendimiento)

### A. Alta relación beneficio/costo (hacer primero)

1. **Cola/semáforo de salida único por sesión** (sección 3). Es la que cierra el hueco principal.
2. **Tope total de salida por sesión** por hora y por día (no solo avisos), con valores conservadores al inicio.
3. **Disyuntor de sesión**: si en una ventana corta hay X fallos (`no_enviado`, 5xx de OpenWA, sesión desconectada),
   la sesión pasa a **pausa** (la cola no se descarta, solo espera), con backoff exponencial largo y **alerta** al
   operador. Reanudar a mano o tras N minutos con prueba de salud (`probar()` ya existe).
4. **Horario de silencio** por sistema (zona horaria ya existe en `Sistema`): fuera de, p. ej., 08:00–21:00 los avisos
   esperan. Las **respuestas** a quien escribe sí salen (lo inició la persona).
5. **Fusionar el acuse con la respuesta cuando el turno es corto**: no enviar «un momento…» si la respuesta va a salir
   en pocos segundos. Menos mensajes, mismo resultado.
6. **Reducir el volumen de avisos**: ya se agrupa **un mensaje por usuario y corrida** (fiscalST). Reforzar: máximo N
   avisos por usuario por día, resumen en vez de uno por evento, y descartar lo que dejó de ser pendiente antes de
   enviar (ya se hace).
7. **Calentamiento** (rampa) para números nuevos: semana 1 con topes muy bajos, subiendo gradualmente. Guardar la fecha
   de alta de la sesión y derivar los topes de ella.
8. **Telemetría y alertas** (sección 7).

### B. Imitar comportamiento humano (si OpenWA lo permite: verificar)

9. **«Escribiendo…» antes de cada mensaje**, con duración proporcional al largo (p. ej. 40–70 ms/caracter ± jitter,
   mínimo 1–2 s). Verificar si OpenWA 0.26 expone un endpoint de *typing/presence/chatstate*: **en el código actual
   no se usa** y no hay referencia en `whatsapp/`.
10. **Marcar como leído** el mensaje entrante unos segundos después de recibirlo y antes de contestar.
11. **Pausa de «lectura»** proporcional al largo del mensaje entrante antes de empezar a escribir.
12. **Variar la latencia**: no siempre 1–5 s; mezclar rápidas (1–2 s) y lentas (10–40 s), con alguna ocasional más
    larga. Evitar patrones periódicos exactos.
13. **No contestar al instante a todo en horario nocturno** (si se decide permitirlo): simular que «lo vio por la
    mañana» solo para avisos, nunca para respuestas a quien está escribiendo.
14. **Sesión estable**: evitar reconexiones/reescaneos de QR frecuentes; no reiniciar OpenWA en horas pico; un solo
    dispositivo/sesión por número.

### C. Contenido del mensaje

15. **Plantillas con variación mínima y natural** (saludo, orden de datos) para no enviar texto 100 % idéntico a
    muchos destinatarios. Sin trucos de ofuscación: el objetivo es que se lea humano, no engañar a un filtro.
16. **Sin enlaces acortados ni dominios dudosos**, sin mayúsculas/exclamaciones masivas, sin adjuntos innecesarios.
    (Ya: texto plano, sin URLs.)
17. **Primer mensaje a cada contacto con identidad clara** (quién escribe y por qué) y **forma de darse de baja**
    (`BAJA`/`PAUSA`) respetada de inmediato. Reduce reportes, que es lo que más daña.
18. **Respetar la baja**: marca `no_avisar` por usuario; la web sigue funcionando.
19. **Pedir que guarden el contacto** («agendá este número») al vincular: los contactos guardados reducen reportes.

### D. Producto / negocio

20. **WhatsApp como aviso, no como canal principal**: la bandeja web es la fuente de verdad. Por cada tipo de aviso,
    decidir si de verdad justifica un WhatsApp.
21. **Preferencias por usuario**: canal (web/WhatsApp), horario, resumen diario en vez de avisos sueltos.
22. **Resumen diario programado** (un mensaje por la mañana) como alternativa a avisos por evento.
23. **Número dedicado**, no el personal de nadie, con perfil completo (nombre, foto, descripción) y varios meses de
    antigüedad si es posible. **No** reutilizar un número con historial de spam.
24. **Tope de usuarios por número** (qué tan grande es el universo): con pocos usuarios internos el riesgo es bajo; no
    abrir el canal a clientes externos con OpenWA.

### E. Operación

25. **Kill switch** por sistema y por sesión (panel): apaga avisos sin tocar el chat.
26. **Modo «solo responder»**: apagar avisos salientes pero dejar el chat (el riesgo mayor son los salientes fríos).
27. **Runbook de bloqueo**: qué hacer si el número cae (avisar a usuarios por la web/mail, no reasignar a ciegas a otro
    número, pedir revisión en WhatsApp Business, plan de migración a Meta).
28. **Canario**: un usuario interno recibe todo primero; si algo falla, se ve antes.
29. **Entorno de pruebas con número separado**: el marcador `[DEV]` ya existe; evitar probar con el número de producción.

## 6. Propuesta de fases

| Fase | Contenido | Esfuerzo | Riesgo del cambio |
|---|---|---|---|
| **S1** | Semáforo/cola de salida por sesión con pausa mínima global y jitter de cola larga; chat y avisos comparten espaciado. Tope total por hora/día. | medio | bajo (no cambia el contrato) |
| **S2** | Disyuntor + alerta, horario de silencio para avisos, modo «solo responder», kill switch en panel. | medio | bajo |
| **S3** | Chats fríos: tope aparte, ventana de actividad, escalonar altas, `BAJA`. | medio | bajo |
| **S4** | Typing/leído si OpenWA lo soporta; variar latencias; fusionar acuse. | bajo–medio | medio (depende de OpenWA) |
| **S5** | Calentamiento por antigüedad de sesión; telemetría y panel de salud del número. | medio | bajo |
| **S6** | Evaluar migración a Meta (sección 8). | alto | — |

Cada fase con su criterio de aceptación medible (ver 9).

## 7. Métricas y alertas

Por sesión y por hora/día: enviados (por tipo), entrantes, **ratio respondidos/enviados**, `no_enviado`, `incierto`,
desconexiones de sesión, latencia de OpenWA, longitud de cola y edad del más viejo, bloqueos por tope, avisos
`vencido`. Alertas: sesión desconectada, ráfaga de fallos, ratio de respuesta muy bajo, cola envejeciendo, cualquier
mensaje de «cuenta restringida» que OpenWA exponga. Hoy hay métricas de uso del LLM, **ninguna de salud del canal**.

## 8. Alternativa estructural: Meta (Cloud API)

Es la única mitigación **de fondo**: número oficial, sin riesgo de baneo por «cliente no oficial». Costos y límites:

- Fuera de la ventana de 24 h solo se envían **plantillas aprobadas** (el `texto` de avisos ya es plantilla fija «por si
  se migra»). El contrato de avisos prohíbe hoy texto libre con Meta por eso.
- Cobro por conversación/mensaje, verificación de negocio y trámites de alta (`whatsapp/whatsapp-alta.md`).
- Recomendación: **diseñar todo lo anterior de forma que el despachador sea independiente del proveedor**; así el
  cambio a Meta es sustituir el adaptador y mantener cola, topes y horarios (que siguen valiendo para no pasarse de
  los límites de calidad de Meta).

## 9. Cómo verificarlo (pruebas)

- **Unitarias**: dos sesiones concurrentes no envían a menos de `pausa_min` entre sí; un aviso nunca sale dentro de la
  pausa tras una respuesta; la prioridad hace pasar la respuesta antes que el aviso; el tope por hora/día corta; el
  disyuntor pausa y reanuda; el horario de silencio difiere avisos pero no respuestas.
- **Carga simulada**: 20 usuarios escribiendo a la vez contra un OpenWA simulado (el del E2E sirve) que registra marcas
  de tiempo: verificar que la **distribución de intervalos** no tiene ráfagas y que no hay dos envíos solapados.
- **Observación en real** (con número de prueba): medir intervalos, revisar que no aparezcan restricciones durante
  semanas; registrar aquí fecha, versión de OpenWA y resultado, sin teléfonos ni contenido.

## 10. Preguntas abiertas

1. ¿Cuántos usuarios y cuántos mensajes/día se esperan realmente? Define los topes.
2. ¿OpenWA 0.26 expone *typing*, *seen* y *presence*? Hay que probarlo y anotarlo.
3. ¿Se acepta que las respuestas de chat pasen por la cola (más latencia a veces) o solo el semáforo?
4. ¿Qué pasa con los avisos cuando hay horario de silencio y el aviso caduca antes (48 h)?
5. ¿Hay presupuesto/plazo para migrar a Meta si el número cae?
6. ¿Quién recibe la alerta de sesión caída/restricción y cómo (mail, push, web)?
7. ¿Se quiere `BAJA`/preferencias por usuario desde ya? (afecta el contrato de vínculos con el sistema anfitrión).

## 11. Qué NO hacer

- Rotar o comprar números para esquivar bloqueos (evasión; agrava la reputación).
- Enviar a listas de contactos que no escribieron primero.
- Subir los topes «para probar» en el número de producción.
- Ocultar fallos: un `incierto` o una restricción se informa, no se reintenta a ciegas.
- Confiar en estas medidas como garantía: reducen el riesgo, no lo eliminan.
