# Plan: panel de administración de sistemas (Jarvis)

> Documento de traspaso entre sesiones. Estado al 2026-10-12: **Fases 1 y 2 cerradas** (modo YAML eliminado), **Fase 3 cerrada
> salvo la prueba manual en navegador** (ver «Cierre de la Fase 3»); fase 4 sin empezar. Origen de la charla:
> `PlataformaJarvisArquitectura.md`. Copia del plan corto: `~/.claude/plans/estoy-interesado-en-darle-quiet-music.md`.
>
> Reglas del proyecto para quien continúe: responder en español, **no hacer `git commit`** (sugerir el mensaje),
> no usar worktrees salvo en jobs en segundo plano. Ver la memoria del proyecto (`pruebas-y-e2e`, `feedback-sin-commits`).

## 1. Qué se quiere y por qué

Hoy los sistemas (empresas) se gestionan editando `config/sistemas.yaml` por terminal y llamando a
`POST /admin/recargar`. Se quiere un **panel** para:

1. Gestionar los **sistemas/empresas** (alta, edición, baja, habilitar) sin tocar el archivo.
2. Gestionar las **integraciones**: qué **tools** puede usar cada sistema (lectura y escritura). Más adelante,
   canales (Telegram, WhatsApp, etc.), solo dejando el hueco en el modelo.
3. Ver y **mejorar el endpoint de uso** (`GET /admin/uso`).

Decisión de plataforma: **se mantiene FastAPI** (se evaluó cambiarlo; el usuario descartó "rehacer").

## 2. Decisiones tomadas (no re-litigar)

| Tema | Decisión |
|---|---|
| Fuente de verdad | Postgres. El YAML queda solo como importación inicial y exportación (sin secretos). |
| Secretos | Cifrados en BD con AES-256-GCM, clave maestra en variable de entorno. Escribibles, nunca legibles. |
| Acceso al panel | Usuarios admin con login. Roles: `admin` y `operador`. |
| Token admin actual | `ASISTENTE_ADMIN_TOKEN` se conserva **solo para automatización** (recargar, salud). El panel usa sesiones. |
| Integraciones | Habilitar/deshabilitar **por tool**, lectura y escritura. Sustituye a `acciones_habilitadas`. |
| Empresa | **Empresa = sistema.** No se crea entidad nueva. |
| Frontend | **React + TypeScript + Vite**. Ver sección 6 (multi-stage en prod, HMR en dev). |
| Canales | Solo diseño: dejar el hueco en el modelo, no implementarlos. |
| Framework backend | FastAPI, sin cambios. |

## 3. Estado actual del código (verificado)

Rutas relativas a `src/asistente/`.

- **Registro** (`sistemas/registro.py`): modelos pydantic `frozen`, `extra="forbid"` (`_Modelo`, línea 24).
  `Sistema` (89-143), `AuthConfig` (28-48), `ConectorConfig` (51-69), `LLMConfig` (72-80), `LimitesConfig` (83-86).
  `RegistroSistemas` (146-213): lee el YAML en `__init__` → `recargar()`; reemplaza el dict de golpe; un sistema
  inválido queda en `errores` y el resto sigue; `habilitado: false` no entra al índice; `_validar_entorno`
  deshabilita el sistema si falta alguna variable de entorno obligatoria.
- **Secretos hoy**: nombres de variable de entorno (`secreto_env`, `clave_publica_env`, `token_manifiesto_env`,
  `llm.base_url_env`, `llm.api_key_env`). Se resuelven con `Sistema.secreto(nombre_env, env)` (`registro.py:139`).
  Lecturas: `sistemas/auth.py:112-120` (`_clave`), `sistemas/manifiesto.py:199` (token del manifiesto),
  `servicios.py:71-72` (LLM por sistema, con fallback a `LLM_BASE_URL`/`LLM_API_KEY`).
- **Filtro de tools duplicado** (`sistemas/conector_http.py`): `tools_de` (126-138) usa
  `manifiesto.tools_accion(sistema.acciones_habilitadas)`; `_tool` (140-154) vuelve a comprobar
  `nombre in sistema.acciones_habilitadas` y `tool.accionable`. Si solo se oculta en uno, la tool sigue ejecutable
  por el otro. Las de lectura no tienen filtro alguno.
- **Auth** (`sistemas/auth.py`): el `iss` se lee sin verificar solo para buscar el sistema; luego se decodifica con
  el algoritmo fijo del sistema. **Bug existente**: `auth.py:119` hace `self._jwks.setdefault(sistema.id, ...)` y
  nunca invalida; si cambia `jwks_url` y se recarga, sigue usando la vieja.
- **CORS** (`api/cors.py:25`): unión de `origenes_permitidos` de todos los sistemas. No debe aplicarse a `/admin`.
- **Admin actual** (`api/admin.py`): router `/admin`, Bearer estático `ASISTENTE_ADMIN_TOKEN`
  (`hmac.compare_digest`; 503 `admin_deshabilitado` si no hay token). Endpoints: `POST /admin/recargar`,
  `GET /admin/sistemas`, `GET /admin/uso?mes=YYYY-MM`. Montado en `main.py:60-63`.
- **Cableado**: `servicios.py:134-160` (`construir`) crea `RegistroSistemas(settings.sistemas_path)`.
  `config.py:15` `sistemas_path` (env `ASISTENTE_SISTEMAS_PATH`, por defecto `/config/sistemas.yaml`),
  `config.py:17` `ASISTENTE_ADMIN_TOKEN`. Los tests de arquitectura (`tests/test_arquitectura.py:29`) impiden que
  `core/` importe `api`, `sistemas` ni `store`.
- **Uso** (`api/admin.py:50-104`): agregado **mensual** por sistema y modelo (`uso_modelo`: tokens in/in_cache/out,
  llamadas; `uso_voz`: caracteres TTS). El costo se calcula al vuelo con `config/precios.yaml` + `precios.py`
  (valle/pico, es una cota). Modelo sin tarifa → `sin_tarifa`.
  Tablas (`store/models.py`): `UsoModelo` 114-131, `UsoVoz` 134-150, `ContadorUso` 99-111, `LlamadaTool` 74-96,
  `Accion` 153-177, `MemoriaUsuario` 180-200, `Mensaje` 56-69.
  Escritura de uso: `limits.py:97-104` (`registrar_uso`), llamado desde `core/agent.py:172`; voz en
  `store/uso.py:26` desde `api/voz.py:137`.
- **Límites** (`limits.py`): `reservar_mensaje` (69-95) comprueba tokens del mes y luego incrementa `min`/`dia`;
  un rechazo también cuenta. **Los rechazos no se persisten** (solo evento SSE/429). `uso_modelo`/`uso_voz` no se
  purgan; las filas `min` de `contadores_uso` tampoco.
- **Usuarios finales**: no están en BD; llegan en el JWT del sistema cliente. El claim `tenants` no se persiste.
- **Infra**: FastAPI + SQLAlchemy 2 async (asyncpg) + Alembic (migraciones 0001-0006 en
  `store/migrations/versions/`, se aplican al arrancar con `python -m asistente.store.migrar`), Postgres 16, sin
  Redis ni worker (la purga de retención es una tarea asyncio en `main.py:33-38`). Contenedor `asistente`:
  `read_only`, `cap_drop ALL`, 512M. Widget: `static/widget.js` vanilla (3071 líneas), leído una vez al arrancar
  por `api/widget.py` (hay que reiniciar el contenedor tras cambiarlo).
- **Compose**: `docker-compose.yml` (base prod), `.dev.yml` (añade `mock-a`, `sistema-php`), `.prod.yml`,
  `.proxy-externo.yml`. Perfiles `voz` y `busqueda`.
- **`config/sistemas.yaml`** actual (dev): `stmgis`, `sistema-php` (límites holgados, `nombre_asistente: sofia`,
  `busqueda_web`, `llm.imagenes`), `mock-a` (`acciones_habilitadas: [agregar_nota, modificar_nota]`,
  `memoria_habilitada`). El archivo está en `.gitignore`; el ejemplo es `config/sistemas.example.yaml`.

## 4. Riesgos y salvaguardas (consejo del asesor)

1. **Campos que dan control total** si alguien los cambia desde el panel: `base_url` (el conector le reenvía el JWT
   del usuario y el token del manifiesto), la clave de `auth` (`secreto_env`/clave pública/`jwks_url`: permite firmar
   tokens como cualquiera) y `llm` (desvía conversaciones). → solo rol `admin`, auditados. **Cambiar `base_url`
   debe borrar `token_manifiesto`** y obligar a cargarlo de nuevo.
2. **XSS en el panel**: nombres y descripciones de tools vienen de un tercero (manifiesto). Nunca
   `dangerouslySetInnerHTML` con esos datos; CSP estricta en prod (`default-src 'self'`).
3. **Tool nueva en el manifiesto**: guardar solo **excepciones**. Lectura habilitada salvo que se apague;
   escritura deshabilitada salvo que se encienda (equivale a `acciones_habilitadas`). Una sola función
   `tool_permitida(sistema, tool, usuario)` para el filtro (lista y ejecución), para poder añadir empresa/tenant
   después sin tocar más sitios.
4. **CORS**: asegurar que la lista de orígenes de sistemas nunca aplique a `/admin` ni a `/panel`.
5. **Datos sensibles en modelos**: secretos descifrados con `SecretStr`; un `repr()`, log o error de pydantic no
   debe volcarlos.
6. **Un solo validador**: el registro en BD se valida con los **mismos** modelos pydantic; no duplicar reglas.
   `acciones_habilitadas` se migra a filas de excepción sin cambiar el comportamiento.
7. **JWKS**: invalidar la caché por sistema al recargar (bug existente, ver sección 3).

## 5. Modelo de datos (mínimo)

| Tabla | Contenido |
|---|---|
| `sistema` | `id` (PK, = `iss`), `nombre`, `habilitado`, `config` JSONB (todo lo no secreto, validado con `Sistema`), `version` (concurrencia optimista), `actualizado_en/por` |
| `sistema_secreto` | PK (`sistema_id`, `campo`); `campo` ∈ {`auth_hs256`, `token_manifiesto`, `llm_api_key`, …}; `kid`, `nonce`, `cifrado`, `actualizado_en/por` |
| `tool_estado` | PK (`sistema_id`, `tool`); `habilitada`; `actualizado_en/por`. Solo excepciones. |
| `registro_version` | una fila; se incrementa en la misma transacción que cada cambio |
| `admin_usuario` | `email` único, `hash` (argon2id), `rol`, `activo`, `fallos`, `bloqueado_hasta`, `ultimo_login` |
| `admin_sesion` | `token_hash` (SHA-256, PK), `usuario_id`, `csrf`, `creada`, `expira`, `ultimo_uso` |
| `admin_auditoria` | quién, acción, objetivo, antes/después en JSONB **sin secretos**, fecha |
| `evento_uso` (fase 4) | `sistema_id`, `usuario_ref`, `modelo`, `tipo` (llm/tts/stt), `resultado` (ok/error/limite_min/limite_dia/limite_mes), tokens, `latencia_ms`, `costo_usd`, canal, fecha |
| `canal` (hueco, sin implementar) | por `sistema_id`: `tipo`, config cifrada, `habilitado` |

No se crean tablas de empresas ni de usuarios finales.

### Cifrado de secretos
- AES-256-GCM (`AESGCM` de `cryptography`), AAD = `sistema_id:campo` (evita copiar el cifrado entre filas),
  guardar `kid` + nonce + texto cifrado.
- `ASISTENTE_CLAVES_MAESTRAS="k2:base64,k1:base64"`: la primera cifra, todas descifran. Rotación: añadir la nueva
  al principio → `rotar-clave` dentro del contenedor → retirar la vieja.
- No cifrar lo público (`jwks_url`, clave pública). Sí: secreto HS256, `token_manifiesto`, `api_key` del LLM.
- La API solo informa "configurado" + huella corta (4 caracteres de un SHA-256) + fecha.
- Si falta la clave o no descifra: ese sistema queda inválido en `errores` (como hoy con variable ausente), no
  tumba el proceso. **Si se pierde la clave no hay recuperación**: hay que re-emitir secretos con cada cliente →
  respaldar la clave fuera del backup de la BD y documentar el procedimiento.
- Al importar desde YAML se resuelven los `*_env` en ese momento y se cifran; después se elimina el camino por
  variables de entorno (no mantener dos fuentes). El export de YAML no incluye secretos.

### Registro en memoria y multi-réplica
- Mantener el dict en memoria con secretos ya descifrados; auth, conector y CORS **nunca** consultan la BD.
- Cada réplica sondea `registro_version` cada 5 s; si cambió, recarga y vacía caché de manifiestos y de JWKS de
  los sistemas afectados. La réplica que escribe recarga al momento. (Se prefiere polling a LISTEN/NOTIFY: más
  simple y funciona tras pgbouncer.) Deshabilitar un sistema puede tardar hasta 5 s en verse en otras réplicas.
- BD no disponible al arrancar → readiness en falso, no un registro vacío silencioso. BD caída en marcha →
  conservar la última copia buena.
- Ediciones simultáneas: `UPDATE ... WHERE version = :v`.

### Login admin
argon2id (`argon2-cffi`); sesión en servidor con token aleatorio de 32 bytes (solo se guarda su SHA-256); cookie
`__Host-admin` HttpOnly + Secure + SameSite=Strict + Path=/; caducidad 30 min por inactividad y 12 h absoluta;
rotar token al hacer login y revocar sesiones al cambiar contraseña o rol; CSRF: Origin = host propio + header
`X-CSRF` ligado a la sesión en todo lo que no sea GET; bloqueo temporal por intentos (por usuario e IP), mismo
mensaje para usuario inexistente y contraseña incorrecta; primer admin por comando CLI, no por variable de
entorno. TOTP queda fuera por ahora (añadible sin cambiar esquema).

## 6. Frontend: React + TS + Vite (prod multi-stage, dev con HMR)

Carpeta nueva `panel/` en la raíz del repo (`package.json`, `vite.config.ts`, `src/`). `base: "/panel/"`.
Librería de componentes a elegir al empezar (shadcn/ui o Mantine); gráficos para la fase 4 (recharts o similar).
El panel consume la API JSON de `/admin/...` (sesión por cookie) y no mezcla datos del manifiesto como HTML.

### Producción: multi-stage en el `Dockerfile`
```dockerfile
# etapa 1: compila el panel
FROM node:22-alpine AS panel-build
WORKDIR /panel
COPY panel/package.json panel/package-lock.json ./
RUN npm ci
COPY panel/ ./
RUN npm run build            # -> /panel/dist

# etapa final (la actual, python:3.12-slim + uv)
...
COPY --from=panel-build /panel/dist /app/src/asistente/static/panel
```
- La imagen final **no lleva Node ni `node_modules`**; el contenedor sigue `read_only` (los estáticos van en la
  imagen, no se escriben en runtime).
- FastAPI sirve `/panel` con `StaticFiles` + fallback a `index.html` (SPA) y añade cabeceras CSP/`X-Frame-Options`
  solo a esa ruta. A diferencia del widget, no hace falta cargar en memoria: es un directorio estático.
- Excluir `/panel` y `/admin` del middleware CORS de sistemas.

### Desarrollo: HMR
- Servicio nuevo `panel` en `docker-compose.dev.yml`: imagen `node:22-alpine`, `working_dir: /panel`, bind mount
  `./panel:/panel` (con volumen anónimo para `node_modules`), comando `npm run dev -- --host 0.0.0.0`,
  puerto `5173`. Vite sirve con HMR; el navegador entra por `http://localhost:5173/panel/`.
- `vite.config.ts` → `server.proxy` de `/admin` y `/v1` hacia `http://asistente:8000` (así el navegador ve un solo
  origen y la cookie de sesión funciona sin CORS). Si se usa HMR por WebSocket tras proxy/contenedor, fijar
  `server.hmr.clientPort = 5173` y `server.watch.usePolling = true` si el bind mount no emite eventos.
- Gotchas a resolver en la implementación:
  - La cookie `__Host-` exige `Secure`; los navegadores la aceptan en `http://localhost`, pero si falla en dev,
    permitir un ajuste (`ASISTENTE_ADMIN_COOKIE_SECURE`, por defecto verdadero) y un nombre sin prefijo en dev.
  - El chequeo CSRF por `Origin` debe aceptar el origen del dev server (`http://localhost:5173`) vía una lista
    configurable solo en dev; en prod, solo el host propio.
  - La CSP solo la aplica FastAPI a `/panel` en prod; en dev la sirve Vite (que necesita inline/WS), sin CSP.
  - Para desarrollar sin Docker: `cd panel && npm run dev` con el proxy apuntando a `localhost:8000`.
- Documentar ambos modos en `README.md`.

## 7. Fases entregables (con tareas)

### Fase 1 — Registro y secretos en BD, sin UI  *(empezar aquí)*
- [x] Migración Alembic 0007: `sistema`, `sistema_secreto`, `tool_estado`, `registro_version`.
- [x] Módulo de cifrado (AES-GCM, `kid`, lista de claves, AAD) con tests: ida y vuelta, AAD cruzada falla,
      rotación, clave ausente.
- [x] `RegistroSistemas` desde BD (misma validación pydantic), con la copia en memoria y sondeo de
      `registro_version` cada 5 s; `recargar()` invalida manifiestos y JWKS por sistema.
- [x] Comandos CLI: `importar-yaml`, `exportar-yaml` (sin secretos), `rotar-clave`.
- [x] `tool_permitida(...)` único; sustituir las comprobaciones de `tools_de` y `_tool` en `conector_http.py`.
      Migrar `acciones_habilitadas` a `tool_estado` conservando el comportamiento.
- [x] Corregir caché JWKS (`auth.py:119`): invalidar al recargar / al cambiar `jwks_url`.
- [x] Mover `llm.*_env` (`servicios.py:71-72`) y `token_manifiesto` / `secreto` a secretos cifrados; `SecretStr`.
- [x] Mantener `ASISTENTE_ADMIN_TOKEN` y `POST /admin/recargar`.
- **Hecho tal como quedó**: selector global `ASISTENTE_REGISTRO=yaml|bd` (YAML por defecto); modelo canónico sin
  `*_env` (adaptador `desde_yaml` resuelve el entorno al cargar; un solo validador `validar_sistema`); API única
  `registro.secreto(sistema, campo)`; módulos `sistemas/{cifrado,permisos,registro_bd,cli}.py`; lectura en una
  transacción REPEATABLE READ; `/salud` en 503 hasta cargar el registro en modo BD.
- **Cerrada (2026-10-11)**: e2e (`acciones` 20/20, `widget` 9/9, `memoria` 20/21: el fallo es de UI del widget, no del
  registro) y evals con el registro en BD sin regresiones atribuibles al registro (30/32, 20/21, 3/6, 9/12; ver
  `pytest-vacia-registro-dev` en la memoria). **Modo YAML eliminado**: `ASISTENTE_REGISTRO` ausente o `bd`; otro valor
  aborta el arranque; sin `RegistroSistemas(ruta)` ni `recargar()` síncrono; `registro_en_yaml` y `sistemas_path` fuera.
  `importar-yaml`/`exportar-yaml` se quedan. Tests con BD aparte `<bd>_test` recreada por sesión (antes vaciaban la
  BD dev). Migración de la VPS: `deploy/VPS.md` («Migrar desde el modo YAML»), **antes** de desplegar este código.
- **Salida**: todos los tests y e2e actuales pasan leyendo el registro desde BD; importar el YAML actual y
  exportarlo da un resultado equivalente.

### Fase 2 — Usuarios admin  *(implementada 2026-10-11)*
- [x] Migración 0008: `admin_usuario`, `admin_sesion`, `admin_auditoria`.
- [x] Login/logout/`/admin/yo`, sesiones, CSRF (Origin + `X-CSRF`), bloqueo por usuario (5 fallos → 15 min) e IP
      (10 fallos / 15 min, en memoria), auditoría de login/logout/recargar.
- [x] CLI: `crear-admin`, `cambiar-clave-admin` (revoca sesiones). `/admin` y `/panel` fuera de CORS.
- **Hecho tal como quedó**: `store/admin.py` (`AdminSql`); `api/admin.py` acepta Bearer (automatización, sin CSRF) o
  cookie `__Host-admin` (`admin` si `ASISTENTE_ADMIN_COOKIE_SECURE=false`); `ASISTENTE_ADMIN_ORIGENES` para dev.
  Los endpoints actuales las admiten ambas y cualquier rol (incl. `operador` recargando). **Pendiente**: aplicar
  `rol == admin` a los endpoints de escritura de la Fase 3 (base_url, auth, llm) y gestión de usuarios;
  retención de `admin_auditoria` sin decidir; el bloqueo por IP es por réplica (en memoria).

### Fase 3 — Panel (frontend)  *(en curso, 2026-10-11)*
**Hecho**: API bajo `/admin/api`; `sistemas/escritura.py` (una transacción por operación: `FOR UPDATE` → validar →
`version` → secretos/tools → `registro_version` → auditoría); `PERMISOS` por rol (`requiere(...)`: escritura solo
`admin` y solo con **sesión**, el token estático no escribe); 409 `registro_en_yaml` en modo YAML; endpoints
`POST/GET/PUT /sistemas[/{id}]`, `PUT|DELETE /sistemas/{id}/secretos/{campo}`, `GET /sistemas/{id}/tools`,
`PUT /sistemas/{id}/tools/{tool}`, `GET|POST /usuarios`, `PATCH /usuarios/{id}`, `POST /usuarios/{id}/clave`
(último admin protegido, sesiones revocadas). Seguridad (asesor): la clave global del LLM ya no viaja a un
`llm.base_url` propio; URLs sin credenciales/query/fragmento; cambiar `base_url`/`llm.base_url` borra su secreto
(sin token nuevo y habilitado → 409 `base_url_requiere_token`, no se apaga en silencio); errores de validación de
`/admin/api` no repiten el cuerpo. Frontend en `panel/` (shadcn/ui base-nova, Tailwind v4, enrutado por hash),
servido en `/panel` con CSP; Dockerfile multi-stage; servicio `panel` (perfil) en compose dev.
**Pendiente**: prueba manual en navegador (login, crear/editar, tools con un manifiesto real); decidir exposición
en los proxies de `deploy/` (hoy `/admin*` cerrado hacia fuera); SSRF a nivel de conector (loopback/privadas con
lista de permitidos para dev); retención de `admin_auditoria`; cambio de contraseña propia desde el panel;
(modo YAML ya eliminado).
- [ ] Andamiaje `panel/` (Vite + React + TS), `Dockerfile` multi-stage y servicio `panel` con HMR (sección 6).
- [ ] Pantallas: login; lista y estado de sistemas (usa `GET /admin/sistemas`); alta/edición; carga de secretos
      (solo escritura); tools del manifiesto en vivo con interruptores; usuarios admin (solo `admin`).
- [ ] Campos sensibles (`base_url`, `auth`, `llm`) solo `admin`; edición con control de `version`.

**Cierre de la Fase 3 (2026-10-12)**:
- **Acceso en prod: túnel SSH** (`ssh -N -L 8001:127.0.0.1:8000 deploy@asistente.<dominio>` → `http://localhost:8001/panel/`,
  `deploy/VPS.md` §5). Los proxies de ejemplo cierran también `/panel*`; `api/acceso_admin.py` responde 404 a `/admin` y
  `/panel` con cabeceras de proxy o `Host` fuera de `ASISTENTE_ADMIN_HOSTS` (lo fija `docker-compose.yml`);
  `FORWARDED_ALLOW_IPS` (`ASISTENTE_PROXY_IPS`) para que uvicorn solo confíe en `X-Forwarded-*` del proxy. El bloqueo de
  login por IP ignora IPs no globales (túnel/proxy compartido): queda el bloqueo por cuenta. Siguiente paso si el equipo
  crece: WireGuard/Tailscale.
- **Contraseña propia**: `POST /admin/api/yo/clave` (cualquier rol, solo sesión, pide la actual, un fallo cuenta para el
  bloqueo de la cuenta, revoca las demás sesiones, audita) y pantalla `/cuenta` en el panel.
- **Retención de `admin_auditoria`**: `ASISTENTE_ADMIN_AUDITORIA_DIAS` (365; 0 = no purgar) dentro del bucle de purga.
  Sigue sin endpoint ni pantalla de lectura de la auditoría; el CLI `cambiar-clave-admin` tampoco audita.
- **SSRF**: `core/red.py` (reglas + `TransporteSeguro`: resuelve, valida todas las IPs y conecta a la IP validada con
  Host/SNI originales) para conector, manifiesto, JWKS (ahora httpx, `ClienteJwks`, tope 256 KB, sin redirecciones) y LLM.
  Por defecto solo IPs públicas; `ASISTENTE_HOSTS_INTERNOS_PERMITIDOS` (nombres/CIDR); el host de `LLM_BASE_URL` se permite
  solo; denegación fija (metadatos, link-local, `0.0.0.0/8`, multicast) que ninguna lista salta; IPv4 mapeada/NAT64/6to4
  evaluadas por la IPv4 que llevan. Al guardar, el panel responde 422 `destino_no_permitido` (comodidad, no control).
  `directo.py` comparte `ip_publica`. Fuera de alcance: STT/TTS/SearXNG/Tavily (URLs del operador, no del panel).
- **Pendiente**: prueba manual en navegador (la hace el usuario); evals (`evals/correr.py`) y e2e con llama-server y
  stmgis levantados, y comprobar en la VPS que `FORWARDED_ALLOW_IPS` coincide con la red del proxy; Safari con la
  cookie `__Host-` sobre `http://localhost` sin verificar.

### Fase 4 — Métricas
- [ ] Migración `evento_uso`; registrar en `core/agent.py` / `limits.py` / `api/voz.py`: rechazos por límite,
      errores y latencia del LLM, canal, costo calculado **al registrar** (histórico estable).
- [ ] Endpoints: series diarias, por usuario (top, cuota restante), tools más usadas con ok/error y p50/p95,
      rechazos y errores; filtros por sistema y rango, paginación. Mantener `/admin/uso`.
- [ ] Retención: purgar `evento_uso` con `retencion_dias`; resumen diario sin `usuario_ref` si crece el volumen.
      Purgar también filas `min` de `contadores_uso`.
- [ ] Gráficos en el panel (usar el skill `dataviz` al diseñarlos).

## 8. Fuera de alcance (por ahora)
App de escritorio, implementación de canales (Telegram/WhatsApp), versionado de contratos de tools, entidad
empresa/tenants, usuarios finales en BD, TOTP, roles personalizados, LISTEN/NOTIFY, editar `config/precios.yaml`
desde el panel.

## 9. Verificación
- `uv run pytest` (incluye `tests/test_arquitectura.py`) y e2e de `tests_e2e/` sin cambios tras la fase 1
  (correr desde el contenedor/worktree como indica la memoria `pruebas-y-e2e`).
- Dos réplicas simuladas: deshabilitar un sistema en una y comprobar que la otra rechaza tokens de ese sistema en
  menos de 5 s.
- Importar el YAML actual → exportar → comparar; rotar clave y verificar descifrado de todos los secretos.
- Seguridad: secretos ausentes de respuestas, logs y `repr`; CSRF; bloqueo de login; escapado de datos del
  manifiesto en el panel; CSP en `/panel`; cambio de `base_url` borra `token_manifiesto`.
- Frontend: `npm run build` en el Dockerfile; HMR funcionando en dev (cambiar un componente y ver el cambio sin
  recargar); la imagen final no contiene `node_modules`.
- Evals (`evals/correr.py`) para confirmar que el comportamiento del agente no cambia.

## 10. Preguntas aún abiertas (decidir al llegar)
- Librería de gráficos para la Fase 4 (la de componentes ya es shadcn/ui).
- ~~Ruta del panel y API~~: decidido — panel en `/panel`, API en `/admin/api`; librería: shadcn/ui.
- Si `operador` puede recargar manifiestos y editar `limites`, o solo `admin`.
- Política de retención de `admin_auditoria` y de `evento_uso`.
- Qué hacer con `config/sistemas.yaml` tras migrar: ¿se conserva para dev como semilla (`importar-yaml` al
  arrancar si la BD está vacía) o se elimina del flujo?
- ~~Proxy~~: decidido — `/admin*` y `/panel*` cerrados en el proxy y acceso por túnel SSH.
