# Asistente MVP

Servicio de **asistente conversacional multi-sistema**. Permite a los usuarios de cualquier sistema integrado (por ejemplo SGAgro) hacer preguntas en lenguaje natural sobre sus propios datos, primero por texto y más adelante por voz.

El asistente corre en su propio contenedor y es agnóstico a la tecnología de los sistemas que lo consumen. No accede a sus bases de datos ni decide permisos. Solo habla con ellos a través de un **contrato HTTP** (manifiesto de tools + ejecución) usando el **token JWT del usuario** que pregunta. Cada sistema aplica sus propios permisos.

Principios del MVP:

- Solo lectura.
- Aislamiento estricto entre sistemas y entre usuarios.
- Cifras siempre trazables a una tool (nada inventado).
- Proveedor de LLM intercambiable (formato neutro + adaptadores).

> Estado: Fases 1 y 2 completas (asistente de texto de solo lectura, widget, verificador, guía de tools y referencia PHP). **Fase 4 (voz) en curso**: el widget dicta y habla con la voz del navegador (Web Speech); falta el modo manos libres («Jarvis») y decidir el proveedor remoto de respaldo. Despliegue en el VPS nuevo, en espera. Hay registro de sistemas, auth JWT por sistema, conector HTTP, loop del agente con adaptador OpenAI-compatible, límites, auditoría y API `/v1/*` con SSE, con tests de aislamiento entre sistemas y usuarios (`tests/test_aislamiento.py`). El diseño completo, las fases y el checklist están en [`PLAN_ASISTENTE.md`](PLAN_ASISTENTE.md).

## Stack

Python 3.12 · FastAPI · httpx · Postgres 16 · SQLAlchemy 2 / Alembic · PyJWT · gestionado con `uv` dentro de Docker.

## Requisitos

- Docker y Docker Compose. No hace falta instalar Python ni `uv` en tu máquina.

## Levantar en desarrollo

```sh
# 1. Variables de entorno (una sola vez)
cp .env.example .env

# 2. Registro de sistemas (opcional por ahora; arranca vacío)
cp config/sistemas.example.yaml config/sistemas.yaml

# 3. Construir y levantar asistente + Postgres
docker compose -f docker-compose.dev.yml up --build
```

El servicio queda en <http://localhost:8100> con recarga automática al editar `src/`. Comprobación rápida:

```sh
curl localhost:8100/salud
# {"ok":true}
```

La documentación interactiva de la API está en <http://localhost:8100/docs> (solo dev: en prod `/docs` está apagado).

### LLM local

El servicio habla con cualquier endpoint OpenAI-compatible (`/v1/chat/completions` con streaming y tool calling). Para usar un `llama-server` en el host:

```sh
# en .env (el compose ya trae un default: http://host.docker.internal:8090/v1)
LLM_BASE_URL=http://host.docker.internal:8090/v1
ASISTENTE_MODELO_DEFAULT=<nombre del modelo>
```

`docker-compose.dev.yml` define `extra_hosts: host.docker.internal:host-gateway` para que el contenedor llegue al host en Linux. El `llama-server` debe escuchar en una interfaz alcanzable desde Docker (`--host 0.0.0.0`, no solo `127.0.0.1`) y conviene firewall que lo limite a la red local. `LLM_BASE_URL` debe incluir el `/v1`.

### Tests

Dos sistemas mock en memoria y Postgres real (los tests de BD se saltan sin `ASISTENTE_DATABASE_URL`):

```sh
docker compose -f docker-compose.dev.yml up -d postgres
docker compose -f docker-compose.dev.yml run --rm asistente sh -c 'ruff check src tests && pytest -q'
```

`tests/test_aislamiento.py` es el hito de la Fase 1: tokens entre sistemas, mismo `sub` en dos sistemas, ana vs. beto vía chat, prompt injection, redirecciones y `token_manifiesto`, tools de escritura, límites/cuotas y borrado.

### Comandos habituales

```sh
docker compose -f docker-compose.dev.yml run --rm asistente pytest          # tests
docker compose -f docker-compose.dev.yml run --rm asistente ruff check .    # lint
docker compose -f docker-compose.dev.yml logs -f asistente                  # logs
docker compose -f docker-compose.dev.yml down                               # parar (conserva la BD)
docker compose -f docker-compose.dev.yml down -v                            # parar y borrar la BD de desarrollo
```

Postgres de desarrollo se publica solo en `127.0.0.1:5433` (usuario, contraseña y base: `asistente`).

### Cambiar dependencias

Editar `pyproject.toml` y regenerar `uv.lock`:

```sh
docker run --rm -v "$PWD":/app -w /app --entrypoint sh python:3.12-slim \
  -c 'pip install -q uv && uv lock'
```

Luego reconstruir con `docker compose -f docker-compose.dev.yml build asistente`. Si el lock queda con dueño root, corregirlo con `sudo chown $USER uv.lock`.

## Widget

El asistente sirve el Web Component en `GET /widget.js` (sin dependencias ni build; código en `src/asistente/static/widget.js`). Es una **vista de chat a pantalla completa** (columna de mensajes y entrada fija abajo; solo muestra la conversación actual, con un botón para empezar otra, sin lista de chats por ahora), no una burbuja flotante: ocupa el 100% de su contenedor, así que el sistema lo coloca en una página o sección propia y le da alto. Se integra con dos líneas:

```html
<script src="https://asistente.example.com/widget.js" defer></script>
<asistente-chat style="display:block;height:100vh" servidor="https://asistente.example.com" token-url="/asistente/token"></asistente-chat>
```

Atributos opcionales: `titulo`, `placeholder`, `idioma` (voz, por defecto `es-UY`), `voz` (nombre de una voz del navegador) y `voz-motor` (`auto` | `navegador` | `servidor`). **Voz:** el widget dicta con el reconocimiento del navegador (en Chrome el audio se procesa en Google; `voz-motor="servidor"` lo evita usando el STT del asistente) y lee las respuestas con las voces del navegador (botón por mensaje e interruptor de lectura automática). Detalle en la sección 7.4 del contrato. Se personaliza con variables CSS (`--asistente-color`, `--asistente-fondo`, `--asistente-fuente`, `--asistente-ancho-lateral`, `--asistente-ancho-columna`, …) y avisa al anfitrión con los eventos `asistente:accion` (sugerencias `ui`) y `asistente:estado` (si no está disponible para el usuario, muestra un aviso en lugar del chat). El origen de la página debe estar en `origenes_permitidos` del sistema.

Demo local: el sistema mock sirve una página con el widget (`MOCK_ASISTENTE_URL` apunta al asistente, por defecto `http://localhost:8100`). Registrá el mock en `config/sistemas.yaml` con su origen en `origenes_permitidos`, levantalo con `uvicorn app:app --app-dir ejemplos/sistema-mock --port 8201` y abrí <http://localhost:8201/?usuario=ana>.

## Integrar un sistema (kit de integración)

- [`contrato/CONTRATO.md`](contrato/CONTRATO.md): lo que debe implementar el sistema (token, manifiesto, ejecución), credenciales y widget.
- [`contrato/GUIA_TOOLS.md`](contrato/GUIA_TOOLS.md): cómo diseñar las tools (elegirlas, describirlas, qué devolver, errores de negocio).
- `ejemplos/sistema-mock/`: implementación de referencia con datos ficticios. `MOCK_DEFECTO=<nombre>` rompe una regla del contrato a propósito (lo usan los tests del verificador).
- `ejemplos/sistema-php/`: implementación de referencia en PHP 8.2+ (router mínimo, portable a CodeIgniter 4), con tests PHPUnit y su [README](ejemplos/sistema-php/README.md). Servicio `sistema-php` en `docker-compose.dev.yml` (puerto 8203).
- `herramientas/probar_audio/`: banco de pruebas de audio, independiente del servicio. `python3 herramientas/probar_audio/servidor.py` y abrir <http://127.0.0.1:8400> (Chrome o Edge). Prueba el micrófono con detección de voz por energía, la transcripción con su latencia, el TTS en streaming, la interrupción y un modo eco. También puede usar el reconocimiento y la síntesis de voz del propio navegador (sin clave) para compararlos. Usa por defecto el speaches local (`--profile voz`); para otro proveedor, `STT_BASE_URL`/`STT_MODELO`/`STT_API_KEY` y `TTS_*` (cualquier endpoint compatible con OpenAI). La cabecera de `servidor.py` lista todas las variables.
- `herramientas/verificar_sistema.py`: verificador de conformidad; un sistema no se habilita en producción sin pasarlo. Los secretos se pasan por variables de entorno y no se imprimen:

```sh
V_MANIFIESTO=... V_SECRETO=... python herramientas/verificar_sistema.py \
  --base-url http://localhost:8201 \
  --token-url "http://localhost:8201/asistente/token?usuario=ana" \
  --token-url-otro "http://localhost:8201/asistente/token?usuario=beto" \
  --token-manifiesto-env V_MANIFIESTO --secreto-firma-env V_SECRETO
```

Opciones y comprobaciones en la [sección 6.5 del contrato](contrato/CONTRATO.md#65-verificar-la-integración). Los tests (`tests/test_verificador.py`) comprueban que detecta una variante rota del mock por cada comprobación.

## Producción

Guía completa para una VPS nueva (host, DNS, proxy con TLS, backups, rollback): [`deploy/VPS.md`](deploy/VPS.md). Resumen:

```sh
cp .env.example .env                                   # completar: POSTGRES_PASSWORD, ASISTENTE_ADMIN_TOKEN, LLM_*
cp config/sistemas.example.yaml config/sistemas.yaml
deploy/deploy.sh                                       # build etiquetado + up + espera salud (backup previo si ya hay BD)
```

`docker-compose.yml` es la base (imagen `prod`: sin dependencias de desarrollo, no-root, solo lectura, Postgres sin puertos, logs rotados, Whisper opcional con `COMPOSE_PROFILES=voz`); `docker-compose.prod.yml` publica el puerto en loopback y `docker-compose.proxy-externo.yml` conecta a un Caddy en la red `web`. Dockge usa el `docker-compose.yml` y el `.env` del stack. Hace falta un proxy con TLS, sin buffering (SSE) y sin exponer `/admin` ni `/docs`: ejemplos en `deploy/Caddyfile.example` y `deploy/nginx.conf.example`. Un `.env` por host (no se versiona).

## Estructura

```
Dockerfile               multi-stage: dev | prod
docker-compose.yml       producción (por defecto, Dockge)
docker-compose.dev.yml   desarrollo
docker-compose.prod.yml  override: puerto en loopback (VPS con proxy en el host)
deploy/                  VPS.md, deploy.sh, backup.sh, Caddyfile y nginx de ejemplo
src/asistente/           código del servicio
tests/                   tests
config/                  registro de sistemas (sistemas.yaml)
prompts/                 prompt base y de dominio
contrato/                contrato v1, schemas, OpenAPI y guía de tools
ejemplos/sistema-mock/   sistema de referencia con datos ficticios
ejemplos/sistema-php/    referencia PHP del contrato
tests_e2e/               e2e del widget en navegador (Playwright MCP)
herramientas/            verificador de conformidad
PLAN_ASISTENTE.md        plan completo del proyecto
```
