# Revisión de seguridad (2026-10-27)

Análisis estático, sin ejecutar nada. No hay hallazgos críticos ni altos. Marcar `[x]` al arreglar cada punto.

No cubierto: CVEs de dependencias (sin red), pruebas en ejecución, lado del host de la vinculación, los endpoints de admin uno por uno (solo auth, CSRF y permisos).

## Prioridad alta

- [ ] **A1. `ASISTENTE_ADMIN_TOKEN` corto (15 caracteres) en `.env`.** Regenerar con `openssl rand -hex 32`. Opcional: exigir longitud mínima de 32 al arrancar en `config.py`. Lectura en `api/admin.py:80-86`.
- [ ] **A2. `POSTGRES_PASSWORD` de 8 caracteres.** Regenerar con `openssl rand -hex 24`. Sin puertos publicados en prod, riesgo bajo.
- [ ] **A3. Exfiltración por inyección indirecta entre turnos.** `core/agent.py:302-313` bloquea `buscar_web` solo si el turno actual trajo datos del sistema. Un dato consultado en el turno 1 puede salir en una consulta del turno 2 inducida por una página leída. Arreglo: rechazar `buscar_web` tras `leer_pagina` en el mismo turno y mirar también el historial.
- [ ] **A4. Cuota evadida con medios.** `api/canal_flujo.py:203-221` descarga, convierte y lanza visión antes de `reservar_mensaje` (`core/agent.py:127`). Mismo patrón en `api/chat.py:151`. Arreglo: reservar la cuota antes de descargar o leer.
- [ ] **A5. PDF lento bloquea la conversión de todos.** `core/medios.py:228` (`wait_for` sobre `to_thread`) no cancela el hilo, que retiene el lock global de pdfium. Comparte pool con el login admin (argon2, `store/admin.py:201`) y Excel (`core/excel.py:109`). Arreglo: executor dedicado de 1-2 hilos, `acquire` con timeout y límite por contacto antes de convertir.
- [ ] **A6. Vinculación sin límite de intentos local.** `api/canal_flujo.py:94,148-152`. Códigos de 8 caracteres base32 (~40 bits, 10 min). El límite depende del host (contrato `CANAL_WHATSAPP.md` §3.2). Arreglo: confirmar el límite en el host y añadir uno local por contacto antes del POST.
- [ ] **A7. Teléfonos de desconocidos sin purga.** `store/canal.py:14-20` guarda `contacto` de cualquier remitente. `retencion.py` no purga `canal_mensajes` ni `canal_vinculos`, y `/privacidad` (`api/privacidad.py:95-96`) promete borrado. Arreglo: purgar ambas tablas y no guardar contactos no vinculados (o guardar un hash).

## Medio y bajo

- [ ] **B1. Escrituras normales tras leer la web.** `core/agent.py:292,470`: `con_web` bloquea solo destructivas y recuerdos. Mitigado por la confirmación en pantalla. Arreglo: bloquearlas también, o marcar la tarjeta como "propuesta tras contenido web".
- [ ] **B2. 500 en vez de 403 con cadenas no ASCII.** `core/canales/meta.py:40-41,49` y `core/canales/openwa.py:46`: `hmac.compare_digest` con `str` lanza `TypeError`. Arreglo: comparar bytes (`.encode()`), como `api/admin.py:85`.
- [ ] **B3. `ref` y URL de medio sin validar.** `core/canales/meta.py:118,121`. Exigir `^\d+$` en `ref` y enviar el Bearer solo a hosts de Meta.
- [ ] **B4. WireServer de Azure fuera de la denegación.** Añadir `168.63.129.16/32` a `_DENEGADAS` en `core/red.py:25-28`. Solo importa si el host corre en Azure.
- [ ] **B5. Bloqueo de login admin por email (DoS).** `store/admin.py:25-26,191-193`. Bloquear por (email, IP) o retardo progresivo, y dejar rastro en auditoría.
- [ ] **B6. Secreto en claro si `base_url` es http.** `sistemas/registro.py:47-61` y `api/canal_flujo.py:116`. Exigir `https` salvo hosts de `ASISTENTE_HOSTS_INTERNOS_PERMITIDOS`.
- [ ] **B7. Replay de estados.** `api/canal.py:56` aplica `actualizar_estado` sin deduplicar.
- [ ] **B8. `origenes_permitidos` sin validar.** `sistemas/registro.py:144` acepta `"null"` y `"*"`.
- [ ] **B9. `_fallos_ip` sin tope.** `api/admin.py:233-237`: crece con cada IP distinta y no se limpia.
- [ ] **B10. Prefijos de contador sin separador seguro.** `limits.py:86,110,118`: `usuario_ref` comparte columna con `voz:`, `web:`, `tts:`.
- [ ] **B11. Sin topes globales por sistema.** Búsquedas web (`limits.py:114-123`) y almacenamiento de archivos (`store/archivos.py:21-31`).
- [ ] **B12. Cabeceras en el proxy y `/privacidad`.** Añadir HSTS en `deploy/nginx.conf.example` y `deploy/Caddyfile.example`, y `frame-ancestors 'none'` / `X-Frame-Options: DENY` en `api/privacidad.py:29-34`.
- [ ] **B13. Dockerfile.** `USER` no root en el target `dev` y bases de prod fijadas por digest (`Dockerfile:4,14-19,22`, `docker-compose.yml:56`).
- [ ] **B14. Verificar el paquete npm `cn`.** `panel/package.json`; el estándar de shadcn es `clsx` + `tailwind-merge`.

## Verificado sin hallazgo

Firma HMAC de Meta, aislamiento entre sistemas, SSRF (`core/red.py`, `core/web/`), JWT (`sistemas/auth.py`), IDOR, CSRF y sesión del admin, CORS, límites de cuerpo, SQL (ORM o `text()` parametrizado), Excel (fórmulas neutralizadas), imágenes y PDF (topes), deserialización, secretos (AES-GCM, argon2id), XSS en panel y widget, endurecimiento del contenedor de prod, `backup.sh`, `deploy.sh`.
