# Despliegue en un VPS nuevo

Pensado para una VPS Linux limpia (Debian/Ubuntu) con un dominio apuntando a ella. Todo corre con Docker; el TLS lo pone un proxy (Caddy o nginx).

## 1. Preparar el host (una vez)

```sh
# Docker Engine + plugin compose: https://docs.docker.com/engine/install/
sudo adduser --disabled-password deploy && sudo usermod -aG docker deploy
# Firewall: solo SSH, HTTP y HTTPS. Los servicios del asistente no publican nada más:
sudo ufw allow OpenSSH && sudo ufw allow 80,443/tcp && sudo ufw enable
```

DNS: un registro `A` (y `AAAA` si hay IPv6) de `asistente.<dominio>` hacia la VPS.

## 2. Instalar

```sh
sudo mkdir -p /opt/asistente-mvp && sudo chown deploy: /opt/asistente-mvp
git clone <repo> /opt/asistente-mvp && cd /opt/asistente-mvp
cp .env.example .env
cp config/sistemas.example.yaml config/sistemas.yaml
```

Completar `.env`:

| Variable | Valor |
|---|---|
| `POSTGRES_PASSWORD` | `openssl rand -hex 24` (obligatoria; sin ella el compose no arranca) |
| `ASISTENTE_ADMIN_TOKEN` | `openssl rand -hex 32` (vacío = `/admin` deshabilitado) |
| `LLM_BASE_URL`, `LLM_API_KEY`, `ASISTENTE_MODELO_DEFAULT` | el proveedor de producción |
| `ASISTENTE_HOSTS_INTERNOS_PERMITIDOS` | solo si algún sistema (`base_url`, `jwks_url`) o un LLM por sistema vive en el mismo host o red docker: nombres y/o CIDR, coma (`mi-sistema,host.docker.internal,10.0.5.0/24`). Vacío = solo IPs públicas; `169.254.0.0/16` (metadatos) nunca |
| `COMPOSE_PROFILES=voz` + `STT_*` | solo si se quiere dictado con Whisper local (2 GB de RAM) |

`config/sistemas.yaml`: un bloque por sistema, con `origenes_permitidos` = origen de la página con el widget, `auth.algoritmo: RS256` y `clave_publica_env` (el PEM va en `.env`). HS256 solo para pruebas.

## 3. Levantar

```sh
deploy/deploy.sh
```

Construye la imagen etiquetada con el hash del repo, levanta todo y espera a que `asistente` esté `healthy`. Las migraciones se aplican solas al arrancar. El servicio queda en `127.0.0.1:8000` (cambiable con `ASISTENTE_PUERTO`).

### Primer arranque: cargar el registro

El registro vive en Postgres y arranca vacío (`/salud` responde `"sistemas":0`). Una vez levantado:

```sh
dc="docker compose -f docker-compose.yml -f docker-compose.prod.yml"
$dc run --rm asistente python -m asistente.sistemas.cli generar-clave   # copiar a ASISTENTE_CLAVES_MAESTRAS en .env
# ¡Respaldar la clave FUERA del servidor (gestor de contraseñas) antes de seguir: sin ella los secretos de la BD
# y de sus backups no se recuperan!
$dc up -d                                                               # el contenedor lee la clave
$dc exec asistente python -m asistente.sistemas.cli importar-yaml       # lee /config/sistemas.yaml y cifra los *_env
$dc exec asistente python -m asistente.sistemas.cli crear-admin tu@correo.com --rol admin
curl -s http://127.0.0.1:8000/salud                                     # "sistemas": N
```

### Migrar desde el modo YAML (VPS existente)

El modo YAML se eliminó: con `ASISTENTE_REGISTRO=yaml` en `.env`, `deploy/deploy.sh` aborta y el contenedor no arranca.
Orden seguro (todo reversible hasta el paso 6):

1. `deploy/backup.sh` y copia de `.env` y `config/sistemas.yaml`.
2. Con la imagen **actual** (aún con modo YAML): `generar-clave`, ponerla en `.env` como `ASISTENTE_CLAVES_MAESTRAS`
   y **respaldarla fuera del servidor**; `dc up -d`.
3. `importar-yaml` y `crear-admin` (como arriba). Las variables `*_env` deben seguir en `.env`: se resuelven al importar.
4. `exportar-yaml /tmp/s.yaml` y compararlo con `config/sistemas.yaml` (mismos ids y flags, `*_env` esperados).
5. Poner `ASISTENTE_REGISTRO=bd` en `.env`, `dc up -d`, y comprobar `/salud` (`sistemas` = N), `/admin/api/sistemas`
   sin `invalidos`, un login real del widget y una tool de lectura por sistema (prueba que `token_manifiesto` descifra).
6. Dejarlo varios días y recién entonces desplegar la versión sin modo YAML con `deploy/deploy.sh`. Mantener
   `ASISTENTE_REGISTRO=bd` (o ausente) en `.env`: así un `deploy.sh rollback` a una imagen anterior sigue en modo BD.
   Solo se puede volver a imágenes que ya tengan modo BD; para anteriores hay que restaurar el modo YAML a mano.
7. **Irreversible, al final:** quitar de `.env` los secretos de sistema en claro (`*_env`). Hasta entonces son la vía
   de recuperación con `importar-yaml --reemplazar`.

## 4. Proxy con TLS

- **Caddy en el host** (lo más simple): `deploy/Caddyfile.example` → `/etc/caddy/Caddyfile`, ajustar el dominio, `systemctl reload caddy`. El TLS es automático.
- **nginx**: `deploy/nginx.conf.example` → `sites-available`, ajustar el dominio, `sudo certbot --nginx -d asistente.<dominio>`.
- **Caddy en otro stack de compose** (red externa `web`): `COMPOSE_FILES="-f docker-compose.yml -f docker-compose.proxy-externo.yml" deploy/deploy.sh` y `reverse_proxy asistente:8000` en ese Caddy.

Los ejemplos devuelven 404 para `/admin`, `/panel`, `/docs` y `/openapi.json` desde fuera, y desactivan el buffering (SSE). Ambos requisitos son obligatorios en cualquier otro proxy. `/docs` además está apagado en el servicio salvo `ASISTENTE_DOCS=1` (solo dev).

Defensa en profundidad: aunque el proxy no bloquee `/admin` ni `/panel`, el servicio responde 404 si la petición trae cabeceras de proxy (`X-Forwarded-*`) o si su `Host` no está en `ASISTENTE_ADMIN_HOSTS` (por defecto, `localhost`/`127.0.0.1` en los puertos 8001 y 8000). Uvicorn solo toma la IP real de `X-Forwarded-For` cuando el peer está en `ASISTENTE_PROXY_IPS` (por defecto loopback y las redes de docker).

## 5. Acceder al panel (túnel SSH)

El panel **no** se publica en internet: se entra por un túnel SSH hacia el puerto en loopback de la VPS. Desde tu
máquina (usuario `deploy` de la sección 1, con clave SSH; el usuario no tiene contraseña):

```sh
ssh -N -L 8001:127.0.0.1:8000 deploy@asistente.<dominio>
```

Con el túnel abierto, en el navegador: **`http://localhost:8001/panel/`**.

- `-N` no abre shell; `-L 8001:127.0.0.1:8000` publica el puerto 8000 de la VPS en el 8001 de tu máquina (se usa
  8001 para no chocar con un servidor de dev local en el 8000). Si en la VPS cambiaste `ASISTENTE_PUERTO`, usa ese
  puerto en lugar de `8000` a la derecha.
- Usa exactamente `localhost:8001` o `127.0.0.1:8001`: cualquier otro `Host` da 404 (`ASISTENTE_ADMIN_HOSTS`).
  Si usas otro puerto local, agrégalo a `ASISTENTE_ADMIN_HOSTS` en el `.env` de la VPS y haz `dc up -d`.
- La cookie de sesión es `__Host-admin` (Secure): Chrome y Firefox la aceptan sobre `http://localhost`. Safari no
  está verificado.
- Cierra el túnel con `Ctrl+C` al terminar. Las sesiones caducan a los 30 min de inactividad.

Atajo con `~/.ssh/config` (en tu máquina):

```
Host asistente-vps
    HostName asistente.<dominio>
    User deploy
    LocalForward 8001 127.0.0.1:8000
    ExitOnForwardFailure yes
    ServerAliveInterval 30
```

y entonces `ssh -N asistente-vps`. Para una sesión de terminal además del túnel, quita `-N`.

## 6. Comprobar

```sh
curl https://asistente.<dominio>/salud                  # {"ok":true,"bd":true,"sistemas":N}
curl https://asistente.<dominio>/widget.js | head -3
curl -o /dev/null -w '%{http_code}\n' https://asistente.<dominio>/admin/api/sistemas   # 404 desde fuera
curl -o /dev/null -w '%{http_code}\n' https://asistente.<dominio>/panel/               # 404 desde fuera
# Desde el host (o por el túnel, en localhost:8001), con el token de admin:
curl -H "Authorization: Bearer $ASISTENTE_ADMIN_TOKEN" http://127.0.0.1:8000/admin/api/sistemas
```

Antes de habilitar un sistema, pasarle `herramientas/verificar_sistema.py` (ver el README).

## 7. Operación

| Tarea | Comando |
|---|---|
| Actualizar | `deploy/deploy.sh` (hace backup antes de migrar) |
| Volver atrás | `docker images asistente` → `deploy/deploy.sh rollback <tag>`. Si el esquema cambió, hace backup y baja las migraciones con la imagen actual (pregunta antes; `YES=1` lo salta). Si el asistente actual no corre, restaurar el backup |
| Cambiar un sistema | desde el panel (`/panel`), o `importar-yaml --reemplazar` con las variables `*_env` en el entorno del contenedor. Se toma solo en ~5 s (`POST /admin/api/recargar` lo fuerza). Sin reiniciar |
| Costo del mes por sistema | `curl -H "Authorization: Bearer $ASISTENTE_ADMIN_TOKEN" "http://127.0.0.1:8000/admin/api/uso?mes=2026-10"` (tokens, caché y USD por sistema y modelo, y los caracteres y USD de la voz del servidor; las tarifas están en `config/precios.yaml`, a revisar contra el proveedor) |
| Métricas de uso (gráficos) | en el panel, pantalla **Métricas** (admin y operador): turnos, errores y rechazos, costo (cota valle/pico), tools con p50/p95 y usuarios con cuota restante. Por API: `GET /admin/api/metricas/{series,usuarios,tools}` con sesión de usuario (el token estático no vale: `403`) |
| Logs | `docker compose -f docker-compose.yml -f docker-compose.prod.yml logs -f asistente` (rotan a 5 × 10 MB) |
| Backup | `deploy/backup.sh` (guarda los últimos 14 en `backups/`) |
| Restaurar | `deploy/backup.sh restore backups/<archivo>.sql.gz.gpg` (cifrado con `BACKUP_GPG_RECIPIENT`; la clave privada va fuera del host) |

Backup diario con cron (`crontab -e` como `deploy`):

```
0 3 * * *  cd /opt/asistente-mvp && deploy/backup.sh >> backups/backup.log 2>&1
```

Copiar `backups/` fuera de la VPS (rsync, rclone, snapshot del proveedor): un backup en el mismo disco no protege de perder la VPS.

### Métricas: migración y retención

- Las migraciones `0009` (`evento_uso`, `uso_diario`) y `0010` (`uso_diario.n_sin_tarifa`, índice en `llamadas_tool`) se aplican solas al arrancar. `deploy.sh` ya hace backup antes; el rollback las baja con `migrar downgrade 0008` (se pierden solo las métricas).
- Las métricas se escriben en lote desde memoria: **un reinicio puede perder los últimos segundos**. Lo que factura (`uso_modelo`, `uso_voz`, `/admin/api/uso`) no depende de esto.
- La purga (al arrancar y luego cada `ASISTENTE_PURGA_INTERVALO_S`, 24 h por defecto: hasta entonces los días recientes se calculan al vuelo desde los crudos) resume antes de borrar: `uso_diario` se recalcula de los últimos 7 días UTC y se conserva sin límite (no lleva `usuario_ref`; son pocas filas por día). Los eventos crudos con usuario (`evento_uso`) duran `min(90, retencion_dias)` del sistema y se borran por días completos ya resumidos; `llamadas_tool` sigue en `retencion_dias`.
- Si el servicio estuvo caído más de 7 días, los agregados de **tools** de esos días se pierden (`llamadas_tool` se purga sin resumen); los de chat y voz no.
- `contadores_uso`: se borran las ventanas `min` y `dia` de más de 2 días; la del mes se conserva.
- La cuota diaria que muestra el panel se reinicia a medianoche UTC (21:00 en Uruguay), como la del servidor.
- Las consultas del panel tienen un tope de 5 s (`504 consulta_lenta`): si pasa con «Todos los sistemas», elegir un sistema o un rango menor.

## Dev frente a prod

| | Dev (`docker-compose.dev.yml`) | Prod (`docker-compose.yml` + `.prod.yml`) |
|---|---|---|
| Imagen | target `dev`, código montado, `--reload` | target `prod`, no-root, solo lectura |
| Postgres | `127.0.0.1:5433`, credenciales fijas | sin puertos, `POSTGRES_PASSWORD` |
| `/docs` | sí (`ASISTENTE_DOCS=1`) | no |
| Whisper | `--profile voz` | `COMPOSE_PROFILES=voz` |
| Sistemas de ejemplo | mock-a, sistema-php | ninguno |
