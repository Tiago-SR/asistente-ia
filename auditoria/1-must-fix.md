# Auditoría 2026-10-18: Must fix

Bugs, seguridad y pérdida de datos. Todo salió de leer el código; nada se reprodujo ni se ejecutó.
Carga asumida: una VPS, un solo proceso, decenas de usuarios a la vez.

## 1. El bloqueo de login del panel se salta con peticiones en paralelo
- **Dónde:** `src/asistente/store/admin.py:166-181`, `src/asistente/api/admin.py:243-249`, `admin.py:110-115` (`cambiar_clave_propia`)
- **Qué es:** el login de administradores cuenta los fallos y bloquea tras 5 por cuenta, y tras un tope por IP.
- **Problema:** cada intento lee `fallos`, verifica la clave y escribe `lee+1`. Con 10 intentos a la vez todos leen 0 y escriben 1, así que nunca se llega a 5. El límite por IP también comprueba antes de registrar el fallo.
- **Fix:** `UPDATE admin_usuario SET fallos = fallos + 1 ... RETURNING fallos` y decidir el bloqueo con ese valor. Para la IP, registrar el intento antes del `await`.
- **Si no se arregla:** alguien puede probar claves del panel sin límite real.

## 2. Una respuesta cortada se guarda como completa
- **Dónde:** `src/asistente/core/llm/openai_compat.py:92-123`
- **Qué es:** lee la respuesta del LLM en streaming.
- **Problema:** si el stream termina sin `finish_reason`, o llega un evento `error` con HTTP 200, el motivo queda en `None` y la línea 109 lo convierte en `"fin"`. La media frase se guarda y se reenvía al modelo como entera.
- **Fix:** lanzar `LLMError` si hay `error` o `motivo is None`.
- **Si no se arregla:** el usuario ve respuestas a medias sin aviso y el historial se contamina.

## 3. `buscar_web` puede sacar datos del sistema
- **Dónde:** `src/asistente/core/web/herramientas.py:36`, `src/asistente/core/agent.py:450`
- **Qué es:** el modelo puede buscar en internet (Tavily o SearXNG).
- **Problema:** nada valida lo que se busca. Si el turno ya trajo datos de una tool, una página leída puede inducir al modelo a buscar "Cliente 4521 deuda". Esa consulta sale a un tercero. El bloqueo de la línea 450 solo cubre acciones destructivas.
- **Fix:** no permitir `buscar_web` en turnos con resultados de tools del sistema, o rechazar consultas con dígitos o ids.
- **Si no se arregla:** los datos del cliente pueden filtrarse por inyección de prompt.

## 4. El tope mensual de tokens es blando y los turnos fallidos no cuentan
- **Dónde:** `src/asistente/limits.py:73-84`, `src/asistente/core/agent.py:228-236`
- **Qué es:** un sistema tiene un cupo mensual de tokens, que el README presenta como duro.
- **Problema:** el check pasa y el consumo se suma al final del turno. Con N turnos a la vez, todos pasan. Si el turno cae por `LLMError` o timeout, no se suma nada. `registrar_uso` (agent.py:236) no tiene try: si la BD falla, se pierde la respuesta ya generada.
- **Fix:** reservar un estimado al empezar y ajustarlo al terminar, registrar un mínimo en los fallos, y proteger `registrar_uso` con try/log (como `api/voz.py:161`). Si no, documentar el tope como aproximado.
- **Si no se arregla:** el gasto real puede pasar del cupo y repetir un turno fallido sale gratis.

## 5. El rol "operador" ve la configuración de los sistemas
- **Dónde:** `src/asistente/api/admin.py:293, 314, 394, 535, 745`
- **Qué es:** los usuarios del panel tienen roles. `PERMISOS` (admin.py:114-117) da al operador solo `metricas.leer`.
- **Problema:** esas rutas solo piden sesión, no permiso. Un operador ve `base_url`, `jwks_url`, huellas de secretos y puede disparar llamadas de manifiesto.
- **Fix:** añadir un permiso `sistemas.leer` y usar `requiere(...)` en esas rutas.
- **Si no se arregla:** el rol limitado lee configuración que no debería.

## 6. El ejemplo PHP deja suplantar a cualquier usuario
- **Dónde:** `ejemplos/sistema-php/public/index.php:27-30`, `ejemplos/sistema-php/src/Config.php:67`
- **Qué es:** el sistema de ejemplo que los integradores copian.
- **Problema:** lee la cookie `usuario` sin comprobar `$cfg->local`. `/asistente/token` emite token para el usuario que diga la cookie, en cualquier entorno (por defecto es `production`).
- **Fix:** envolver la lectura en `if ($cfg->local)` o quitarla.
- **Si no se arregla:** un integrador que copie el ejemplo deja a cualquiera entrar como cualquier usuario.

## 7. `/admin` queda abierto si no se configura `admin_hosts`
- **Dónde:** `src/asistente/config.py:39`, `src/asistente/api/acceso_admin.py:34-36`, `docker-compose.dev.yml:33`
- **Qué es:** una defensa extra que comprueba el `Host` y las cabeceras de proxy.
- **Problema:** con la lista vacía (valor por defecto) se salta entera. Prod la fija en `docker-compose.yml:32`, pero cualquier otro despliegue queda sin defensa. En dev, `8100:8000` se publica en todas las interfaces, con `/docs` activo.
- **Fix:** por defecto `localhost:8000,127.0.0.1:8000` (o fallar al arrancar si está vacío en prod). En dev: `127.0.0.1:8100:8000`.
- **Si no se arregla:** el panel de admin queda a un token de distancia de la red local.

## 8. Una acción puede quedar atascada en `confirmada`
- **Dónde:** `src/asistente/store/acciones.py:113-148`
- **Qué es:** al confirmar, `reclamar` pasa la acción a `confirmada` y solo `finalizar` la saca de ahí.
- **Problema:** si el proceso cae entre los dos pasos, la fila queda así para siempre y no se sabe si la escritura ocurrió.
- **Fix:** un barrido que pase a `fallida` ("interrumpida") las `confirmada` de más de N minutos. Sin reintento, porque la escritura pudo ejecutarse.
- **Si no se arregla:** acciones fantasma que el usuario no puede resolver ni reintentar con seguridad.
