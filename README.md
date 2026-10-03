# Asistente MVP

Servicio de **asistente conversacional multi-sistema**. Permite a los usuarios de cualquier sistema integrado (por ejemplo SGAgro) hacer preguntas en lenguaje natural sobre sus propios datos, primero por texto y más adelante por voz.

El asistente corre en su propio contenedor y es agnóstico a la tecnología de los sistemas que lo consumen. No accede a sus bases de datos ni decide permisos. Solo habla con ellos a través de un **contrato HTTP** (manifiesto de tools + ejecución) usando el **token JWT del usuario** que pregunta. Cada sistema aplica sus propios permisos.

Principios del MVP:

- Solo lectura.
- Aislamiento estricto entre sistemas y entre usuarios.
- Cifras siempre trazables a una tool (nada inventado).
- Proveedor de LLM intercambiable (formato neutro + adaptadores).

> Estado: en construcción, Fase 0. Hoy solo existe el esqueleto del servicio (`/salud`). El diseño completo, las fases y el checklist están en [`PLAN_ASISTENTE.md`](PLAN_ASISTENTE.md).

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
docker compose up --build
```

El servicio queda en <http://localhost:8100> con recarga automática al editar `src/`. Comprobación rápida:

```sh
curl localhost:8100/salud
# {"ok":true}
```

La documentación interactiva de la API está en <http://localhost:8100/docs>.

### Comandos habituales

```sh
docker compose run --rm asistente pytest          # tests
docker compose run --rm asistente ruff check .    # lint
docker compose logs -f asistente                  # logs
docker compose down                               # parar (conserva la BD)
docker compose down -v                            # parar y borrar la BD de desarrollo
```

Postgres de desarrollo se publica solo en `127.0.0.1:5432` (usuario, contraseña y base: `asistente`).

### Cambiar dependencias

Editar `pyproject.toml` y regenerar `uv.lock`:

```sh
docker run --rm -v "$PWD":/app -w /app --entrypoint sh python:3.12-slim \
  -c 'pip install -q uv && uv lock'
```

Luego reconstruir con `docker compose build asistente`. Si el lock queda con dueño root, corregirlo con `sudo chown $USER uv.lock`.

## Producción

Se usa `docker-compose.prod.yml`, que construye el target `prod` del `Dockerfile` (sin dependencias de desarrollo, usuario no-root, filesystem de solo lectura, Postgres sin puertos publicados).

```sh
cp .env.example .env.prod      # completar valores reales, incluido POSTGRES_PASSWORD
cp config/sistemas.example.yaml config/sistemas.yaml
docker compose -f docker-compose.prod.yml --env-file .env.prod up -d --build
```

Requiere un proxy inverso con TLS delante, con el buffering desactivado para SSE. Ver detalles en la sección 13 del plan.

## Estructura

```
Dockerfile               multi-stage: dev | prod
docker-compose.yml       desarrollo
docker-compose.prod.yml  producción
src/asistente/           código del servicio
tests/                   tests
config/                  registro de sistemas (sistemas.yaml)
prompts/                 prompt base y de dominio
PLAN_ASISTENTE.md        plan completo del proyecto
```
