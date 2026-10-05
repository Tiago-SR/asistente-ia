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
| `COMPOSE_PROFILES=voz` + `STT_*` | solo si se quiere dictado con Whisper local (2 GB de RAM) |

`config/sistemas.yaml`: un bloque por sistema, con `origenes_permitidos` = origen de la página con el widget, `auth.algoritmo: RS256` y `clave_publica_env` (el PEM va en `.env`). HS256 solo para pruebas.

## 3. Levantar

```sh
deploy/deploy.sh
```

Construye la imagen etiquetada con el hash del repo, levanta todo y espera a que `asistente` esté `healthy`. Las migraciones se aplican solas al arrancar. El servicio queda en `127.0.0.1:8000` (cambiable con `ASISTENTE_PUERTO`).

## 4. Proxy con TLS

- **Caddy en el host** (lo más simple): `deploy/Caddyfile.example` → `/etc/caddy/Caddyfile`, ajustar el dominio, `systemctl reload caddy`. El TLS es automático.
- **nginx**: `deploy/nginx.conf.example` → `sites-available`, ajustar el dominio, `sudo certbot --nginx -d asistente.<dominio>`.
- **Caddy en otro stack de compose** (red externa `web`): `COMPOSE_FILES="-f docker-compose.yml -f docker-compose.proxy-externo.yml" deploy/deploy.sh` y `reverse_proxy asistente:8000` en ese Caddy.

Los ejemplos devuelven 404 para `/admin`, `/docs` y `/openapi.json` desde fuera, y desactivan el buffering (SSE). Ambos requisitos son obligatorios en cualquier otro proxy. `/docs` además está apagado en el servicio salvo `ASISTENTE_DOCS=1` (solo dev).

## 5. Comprobar

```sh
curl https://asistente.<dominio>/salud                  # {"ok":true,"bd":true,"sistemas":N}
curl https://asistente.<dominio>/widget.js | head -3
curl -o /dev/null -w '%{http_code}\n' https://asistente.<dominio>/admin/sistemas   # 404 desde fuera
# Desde el host, con el token de admin:
curl -H "Authorization: Bearer $ASISTENTE_ADMIN_TOKEN" http://127.0.0.1:8000/admin/sistemas
```

Antes de habilitar un sistema, pasarle `herramientas/verificar_sistema.py` (ver el README).

## 6. Operación

| Tarea | Comando |
|---|---|
| Actualizar | `deploy/deploy.sh` (hace backup antes de migrar) |
| Volver atrás | `docker images asistente` → `deploy/deploy.sh rollback <tag>`. Si el esquema cambió, hace backup y baja las migraciones con la imagen actual (pregunta antes; `YES=1` lo salta). Si el asistente actual no corre, restaurar el backup |
| Cambiar `sistemas.yaml` | editar y `POST /admin/recargar` desde el host (sin reiniciar) |
| Costo del mes por sistema | `curl -H "Authorization: Bearer $ASISTENTE_ADMIN_TOKEN" "http://127.0.0.1:8000/admin/uso?mes=2026-10"` (tokens, caché y USD por sistema y modelo; las tarifas están en `config/precios.yaml`, a revisar contra el proveedor) |
| Logs | `docker compose -f docker-compose.yml -f docker-compose.prod.yml logs -f asistente` (rotan a 5 × 10 MB) |
| Backup | `deploy/backup.sh` (guarda los últimos 14 en `backups/`) |
| Restaurar | `deploy/backup.sh restore backups/<archivo>.sql.gz` |

Backup diario con cron (`crontab -e` como `deploy`):

```
0 3 * * *  cd /opt/asistente-mvp && deploy/backup.sh >> backups/backup.log 2>&1
```

Copiar `backups/` fuera de la VPS (rsync, rclone, snapshot del proveedor): un backup en el mismo disco no protege de perder la VPS.

## Dev frente a prod

| | Dev (`docker-compose.dev.yml`) | Prod (`docker-compose.yml` + `.prod.yml`) |
|---|---|---|
| Imagen | target `dev`, código montado, `--reload` | target `prod`, no-root, solo lectura |
| Postgres | `127.0.0.1:5433`, credenciales fijas | sin puertos, `POSTGRES_PASSWORD` |
| `/docs` | sí (`ASISTENTE_DOCS=1`) | no |
| Whisper | `--profile voz` | `COMPOSE_PROFILES=voz` |
| Sistemas de ejemplo | mock-a, mock-b, sistema-php | ninguno |
