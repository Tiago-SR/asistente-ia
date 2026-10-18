# Auditoría 2026-10-18: Should fix

Código riesgoso sin test, lentitud real, duplicación y cosas que no deberían existir.
La numeración sigue la de `1-must-fix.md` (esta empieza en el 9).

## 9. Se borraron los tests de la defensa anti-SSRF y de seguridad
- **Dónde:** `tests/` (git status: `test_red.py`, `test_web.py`, `test_voz.py`, `test_adjuntos.py`, `test_llm_openai_compat.py`, `test_cifrado.py`, `test_retencion.py` y otros como borrados)
- **Qué es:** la suite se recortó al core a propósito.
- **Problema:** hoy ningún test cubre `validar_url`, `TransporteSeguro` (`core/red.py`), `AccesoAdmin`, descargas ajenas (`api/descargas.py`), rotación de claves (`sistemas/cifrado.py`), retención (`retencion.py`), el bloqueo de login ni `ClienteJwks`.
- **Fix:** restaurar `test_red.py` y la parte SSRF de `test_web.py` (`git restore --staged` y `git checkout HEAD -- <archivo>`). Añadir un test del bloqueo de login y de la descarga ajena. No commitear.
- **Si no se arregla:** un cambio puede abrir un SSRF o un IDOR sin que nada falle.

## 10. JWKS sin respaldo ni single-flight
- **Dónde:** `src/asistente/sistemas/auth.py:94-101`
- **Qué es:** descarga las claves públicas del sistema cliente, con TTL de 300 s.
- **Problema:** si el emisor cae al vencer el TTL, cada petición espera 5 s y responde 401, aunque las claves viejas sirvan. Sin lock, N peticiones descargan N veces. Si nunca hubo una descarga buena, cada petición vuelve a intentar.
- **Fix:** si falla y hay claves previas, seguir con ellas (con `log.warning`) hasta un tope de edad, y un `asyncio.Lock` en `_descargar`.
- **Si no se arregla:** una caída corta del sistema cliente tumba el chat de todos sus usuarios.

## 11. Ningún fetch del widget ni del panel tiene timeout
- **Dónde:** `src/asistente/static/widget.js:1306, 1344, 2613`, `panel/src/lib/api.ts:29`
- **Problema:** con un servidor colgado, el widget queda en "Pensando…" con la entrada bloqueada y el panel en "Cargando…".
- **Fix:** `AbortController` con timeout que se limpie al recibir cabeceras (no uno fijo, que cortaría el SSE). Para el chat, un timeout de inactividad.
- **Si no se arregla:** el usuario tiene que recargar la página.

## 12. Texto inyectado en imágenes o web puede persistir
- **Dónde:** `src/asistente/core/adjuntos.py:110-117, 154-164`, `src/asistente/store/repo.py:45-46`, `src/asistente/core/agent.py:450`
- **Problema:** si una imagen trae una frase de inyección, solo se avisa y la descripción se guarda y se reinyecta en turnos posteriores. Además, el bloqueo tras leer web cubre `destructiva` pero no `recordar`, que también escribe: una página puede hacer que se proponga guardar una "entidad principal" falsa.
- **Fix:** en `_leer_una` devolver `""` si es sospechosa, y usar `(destructiva or local) and con_web`.
- **Si no se arregla:** una foto o página manipulada afecta a turnos futuros. La confirmación en pantalla limita el daño.

## 13. El dominio del prompt se descarta en silencio
- **Dónde:** `src/asistente/core/prompts.py:41-56`
- **Problema:** si el archivo pasa de 20 KB, sale de la ruta o no se lee, devuelve `""` con un `log.error` y el asistente arranca sin las reglas del dominio.
- **Fix:** validar al arrancar y fallar.
- **Si no se arregla:** pierde reglas como "no inventes cifras" y nadie lo nota.

## 14. No hay tope de tamaño de cuerpo en la app
- **Dónde:** `src/asistente/main.py:106-111`, `src/asistente/api/voz.py:87-92`
- **Problema:** FastAPI parsea el JSON de `/v1/chat` antes de validar la sesión. El único tope es `client_max_body_size 4m` del nginx de ejemplo (`deploy/nginx.conf.example:8`). El dictado lee el audio entero antes de reservar la cuota.
- **Fix:** un middleware que corte por `Content-Length` y por bytes leídos, y reservar la cuota antes de leer el audio.
- **Si no se arregla:** sin ese proxy, cualquiera manda cuerpos enormes.

## 15. Topes de acciones y de archivos sin lock
- **Dónde:** `src/asistente/store/acciones.py:47-65`, `src/asistente/store/archivos.py:25-35`
- **Problema:** cuentan, comparan e insertan sin lock. Dos pestañas a la vez superan el tope por hora de acciones o `max_por_dia` de Excel.
- **Fix:** `pg_advisory_xact_lock` por `(sistema, usuario)`, como ya hace `store/memoria.py:82-85`.
- **Si no se arregla:** el exceso es pequeño, pero los topes dejan de ser exactos.

## 16. Dos implementaciones de anti-SSRF
- **Dónde:** `src/asistente/core/web/directo.py:66-68, 157-178` y `src/asistente/core/red.py:98-146`; `src/asistente/sistemas/auth.py:113`
- **Problema:** son copias casi iguales con reglas un poco distintas, así que pueden divergir. `Autenticador` usa un `httpx.AsyncClient` sin `TransporteSeguro` si no se le pasa cliente (en prod sí se pasa, `servicios.py:187`). Además el tope de bytes de `directo.py:199-203` se aplica después de descomprimir.
- **Fix:** que `directo.py` importe de `red.py`, hacer obligatorio el cliente del `Autenticador` y añadir `"Accept-Encoding": "identity"` en `directo.py:176`.
- **Si no se arregla:** un arreglo en un lado no llega al otro.

## 17. El backup no está cifrado y deja parciales
- **Dónde:** `deploy/backup.sh:22-23`
- **Problema:** vuelca datos de usuarios a `backups/` sin cifrar, en el mismo host que `.env` con las claves maestras. Si `pg_dump` falla, el fichero parcial queda y cuenta para la retención.
- **Fix:** `umask 077`, cifrar con age o gpg guardando la clave fuera del host, y `trap 'rm -f "$salida"' ERR`.
- **Si no se arregla:** quien lea el disco tiene datos y claves juntos.

## 18. Panel: sesión caducada pierde la edición, accesibilidad y "Cargar más"
- **Dónde:** `panel/src/lib/api.ts:36`, `panel/src/App.tsx:21-22`, `panel/src/pages/Sistemas.tsx:78`, `panel/src/pages/Sistema.tsx:281`, `panel/src/pages/Auditoria.tsx:19, 115`
- **Problema:** cualquier 401 desmonta la pantalla y se pierden los cambios sin guardar. Las filas de sistemas solo abren con clic (sin teclado). El `Switch` de tools no tiene nombre accesible. "Cargar más" no se deshabilita, así que un doble clic duplica filas, y `cargar` no descarta respuestas viejas al cambiar el filtro.
- **Fix:** aviso "sesión caducada" y volver a la ruta tras entrar; un `<a href="#/sistemas/${s.id}">` en la celda del id; `aria-label={t.nombre}`; estado `cargando` con `disabled` y una guarda `vigente` como en `Metricas.tsx:90-110`.
- **Si no se arregla:** pérdida de trabajo y panel inutilizable con teclado o lector de pantalla.
