# syntax=docker/dockerfile:1

# ---------- base: Python + uv ----------
FROM python:3.12-slim AS base
COPY --from=ghcr.io/astral-sh/uv:0.12.23 /uv /usr/local/bin/uv
ENV PYTHONUNBUFFERED=1 \
    PYTHONDONTWRITEBYTECODE=1 \
    UV_LINK_MODE=copy \
    UV_PROJECT_ENVIRONMENT=/opt/venv \
    PATH="/opt/venv/bin:$PATH"
WORKDIR /app

# ---------- dev: con dependencias de desarrollo, código montado por volumen ----------
FROM base AS dev
COPY pyproject.toml uv.lock ./
RUN --mount=type=cache,target=/root/.cache/uv \
    uv sync --frozen --no-install-project --group dev
ENV PYTHONPATH=/app/src
CMD ["uvicorn", "asistente.main:app", "--host", "0.0.0.0", "--port", "8000", "--reload", "--reload-dir", "/app/src"]

# ---------- build-prod: solo dependencias de ejecución ----------
FROM base AS build-prod
COPY pyproject.toml uv.lock ./
RUN --mount=type=cache,target=/root/.cache/uv \
    uv sync --frozen --no-install-project --no-dev
COPY src ./src
COPY README.md* ./
RUN --mount=type=cache,target=/root/.cache/uv \
    uv sync --frozen --no-dev --no-editable

# ---------- prod: imagen final, sin uv ni herramientas de build ----------
FROM python:3.12-slim AS prod
ENV PYTHONUNBUFFERED=1 \
    PYTHONDONTWRITEBYTECODE=1 \
    PATH="/opt/venv/bin:$PATH"
RUN useradd --system --uid 10001 --no-create-home asistente
COPY --from=build-prod /opt/venv /opt/venv
WORKDIR /app
COPY prompts ./prompts
USER asistente
EXPOSE 8000
HEALTHCHECK --interval=30s --timeout=5s --start-period=15s --retries=3 \
    CMD python -c "import urllib.request,sys; sys.exit(0 if urllib.request.urlopen('http://127.0.0.1:8000/salud', timeout=3).status==200 else 1)"
# Aplica migraciones al arrancar (idempotente) y luego sirve.
CMD ["sh", "-c", "python -m asistente.store.migrar && exec uvicorn asistente.main:app --host 0.0.0.0 --port 8000 --proxy-headers --no-access-log"]
