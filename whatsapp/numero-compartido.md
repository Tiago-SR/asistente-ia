# Número de WhatsApp compartido entre sistemas (propuesta, NO implementada)

Estado: **anotado el 2026-10-28, sin decidir**. Decisión del usuario: por ahora se prueba con fiscalST en el modo
actual (un sistema, su número y su app). Se retoma cuando haya un segundo sistema real que lo necesite.

## Qué se quiere

Un solo número de WhatsApp y una sola app de Meta para todos los sistemas, en lugar de una app y un número por
sistema. Desde el mismo chat se consulta el sistema al que el usuario esté vinculado.

## Cómo es hoy (modo por sistema)

- `canal_mensajeria` en la config de cada sistema (`core/canales/config.py`, `CanalMetaConfig` con `phone_number_id`).
- Secretos por sistema: `wa_token`, `wa_app_secret`, `wa_verify_token`, `token_canal` (`SECRETOS_CANAL`, tabla
  `sistema_secreto`).
- Webhook `/canal/{sistema_id}/webhook` (`api/canal.py`); flujo en `api/canal_flujo.py`.
- Tablas `canal_mensajes` (PK `sistema_id, id`) y `canal_vinculos` (PK `sistema_id, contacto`).
- Botones de confirmación firmados con HMAC usando el `wa_app_secret` del sistema (`canal_flujo._boton_id`).
- La identidad la decide cada sistema anfitrión (`contrato/CANAL_WHATSAPP.md`): el asistente no puede fabricarla.
  Esto **no cambia** con un número compartido: cada sistema sigue necesitando sus endpoints `canal/codigo`,
  `canal/vincular` y `canal/token`.

## Ventajas

- Una sola configuración en Meta: un número, una app, un webhook, un método de pago, una verificación de negocio.
- Operación más simple: los secretos de Meta se cargan y rotan en un solo lugar.
- Un único contacto para los usuarios; un mismo teléfono puede estar en varios sistemas y cambiar con `CAMBIAR`.
- Los vínculos actuales siguen valiendo: dependen del teléfono del usuario, no del número del negocio. Solo cambia
  la URL del webhook en Meta.

## Desventajas y riesgos

- **Un solo punto de falla**: si Meta bloquea o limita el número, caen todos los sistemas.
- **Mayor impacto de una filtración**: con `wa_app_secret` se pueden falsificar mensajes de cualquier usuario
  vinculado en todos los sistemas; con `wa_token` se puede enviar como el asistente a todos y bajar medios. Por eso
  estos secretos irían solo en el entorno (no editables desde el panel), con rotación documentada.
- **Un solo nombre y marca** en WhatsApp para todos los sistemas.
- **Más complejidad**: enrutar cada mensaje a un sistema, usuarios en 2+ sistemas, botones firmados con el sistema,
  tope global por número, y `canal_mensajes` ya no puede asumir un sistema al recibir.
- **Depende del prefijo del código**: cada sistema debe emitir un prefijo único (`FST-`, `PAT-`…). En el contrato es
  opcional (`CANAL_WHATSAPP.md` §3.1 dice que ya no se usa para enrutar; habría que actualizarlo). Si un sistema no
  lo emite (Patrinal, por confirmar), hay que pedírselo o aceptar un único sistema «sin prefijo» por defecto.
- **Aislamiento menos evidente**: sigue garantizado por el `token_canal` de cada sistema, no por una app de Meta
  separada. Nunca listar ni insinuar a un número en qué sistemas es cliente.

## Diseño recomendado (asesor, 2026-10-28)

1. **Config global** en Settings, desde el entorno: `wa_phone_number_id`, `wa_token`, `wa_app_secret`,
   `wa_verify_token`. Por sistema quedan solo `canal_mensajeria: {proveedor: meta, prefijo: "PAT", acciones: [...]}`
   (sin `phone_number_id`) y su `token_canal`. El registro debe exigir `prefijo` único.
2. **Webhook único** `/canal/whatsapp/webhook`: valida la firma con el secreto global, deduplica y enruta.
3. **Enrutamiento**:
   - `VINCULAR PAT-XXXX`: el prefijo elige el sistema y solo a ese se le llama `canal/vincular`. Prefijo desconocido
     o ausente: silencio. **Nunca** repartir el código entre todos los sistemas (revela el número a sistemas ajenos
     y multiplica la fuerza bruta).
   - Otros mensajes: buscar los vínculos activos del número en `canal_vinculos`. Con 0, silencio; con 1, ese
     sistema; con 2 o más, el sistema activo.
4. **Sistema activo**: columna `elegido_en` en `canal_vinculos`; el activo es el de valor más alto. Vincular lo pone
   en «ahora», así que el último vinculado queda activo y nunca hay «2+ vínculos y ninguno activo».
5. **Comando `CAMBIAR`**: responde con botones, uno por sistema vinculado (WhatsApp admite 3; con más, menú
   numerado). Si el número tiene 2+ vínculos, cada respuesta empieza con `[Nombre del sistema]`.
6. **Lock por número** (no por par sistema-número), para que no corran dos turnos a la vez durante un cambio.
7. **Botones**: el id lleva el sistema: `ok:<sis>:<uuid>:<mac>` con MAC sobre `decision|sis|accion|contacto` y una
   clave derivada (`hmac(app_secret, "botones")`). El botón se enruta por el sistema que lleva dentro, no por el
   activo. Los botones de elegir sistema también se firman. Las tarjetas pendientes al migrar dejan de validar
   (duran minutos).
8. **Topes**: tope global por número antes de enrutar, además del de cada sistema (si no, rotar entre sistemas lo
   evade).

## Migración

- Usar como número global el que ya está en producción (número y app de prueba de «PruebaJarvis» hoy). Los vínculos
  viven en cada sistema y van atados al `wa_id`: siguen valiendo. Cambia solo la URL del webhook en Meta.
- Mantener la ruta por sistema solo hasta comprobar en prod que la nueva funciona; después borrarla (dos caminos
  duplican la superficie). OpenWA sigue por sistema, sin cambios.

## Cambio mínimo cuando se haga

- Settings globales; `prefijo` en la config con `phone_number_id` opcional.
- Ruta única y función de enrutado (código → prefijo; si no, vínculo activo).
- `elegido_en` y `canal_vinculos.sistemas_de(contacto)`.
- Comando `CAMBIAR` con botones.
- Botones con `sistema_id` en el MAC.
- Lock y tope global por número.
- `canal_mensajes`:
  - entradas: deduplicar bajo un id centinela (p. ej. `_wa`), porque el sistema aún no se conoce;
  - salidas: con el `sistema_id` real;
  - estados: Meta no dice a qué sistema pertenecen, así que `actualizar_estado` busca solo por id;
  - comprobar que `retencion.py` también purga el centinela.

## Para después

Panel de la config global (`CanalEstado` consulta el número de cada sistema), menú de lista de Meta para más de 3
sistemas, reprocesar el mensaje original tras elegir sistema, locks entre réplicas, quitar el modo por sistema.

## Verificar antes de empezar

- Qué prefijo emite cada sistema en `canal/codigo` (fiscalST: `FST`; Patrinal: por confirmar).
- Límites de Meta: 3 botones por mensaje, id de botón hasta 256 caracteres, título hasta 20 (cortar nombres de
  sistema).
- Que los `wamid` de Meta sean únicos entre conversaciones.
- Actualizar `contrato/CANAL_WHATSAPP.md` §3.1 (el prefijo pasa a ser obligatorio y único).

## Recomendación vigente

Probar primero con fiscalST en el modo actual: valida lo que falta (botones y estados de Meta en vivo) sin tocar la
arquitectura. Hacer este cambio cuando haya un segundo sistema real que lo necesite.
