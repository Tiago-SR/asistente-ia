#!/usr/bin/env bash
# Despliegue/actualización en el VPS. Uso (desde la raíz del repo):  deploy/deploy.sh [rollback <tag>]
#   deploy/deploy.sh               pull + build etiquetado con el hash del repo + up + espera salud
#   deploy/deploy.sh rollback <t>  vuelve a una imagen ya construida (ver `docker images asistente`);
#                                  si cambió el esquema, hace backup y baja las migraciones (YES=1 sin preguntar)
# Variable COMPOSE_FILES (por defecto prod). Con Caddy en red externa:
#   COMPOSE_FILES="-f docker-compose.yml -f docker-compose.proxy-externo.yml" deploy/deploy.sh
set -euo pipefail
cd "$(dirname "$0")/.."

COMPOSE_FILES=${COMPOSE_FILES:--f docker-compose.yml -f docker-compose.prod.yml}
export COMPOSE_FILES
[ -f .env ] || { echo "Falta .env (cp .env.example .env y completarlo)"; exit 1; }
[ -f config/sistemas.yaml ] || { echo "Falta config/sistemas.yaml (cp config/sistemas.example.yaml config/sistemas.yaml)"; exit 1; }
dc() { docker compose $COMPOSE_FILES "$@"; }

if [ "${1:-}" = rollback ]; then
  destino=${2:?indicar el tag, p. ej. a1b2c3d}
  docker image inspect "asistente:$destino" >/dev/null
  # Revisión de esquema que espera la imagen de destino y la que tiene la BD ahora.
  rev_destino=$(docker run --rm --entrypoint python "asistente:$destino" -m asistente.store.migrar head)
  rev_bd=$(dc exec -T postgres psql -U asistente -d asistente -tAc "SELECT version_num FROM alembic_version")
  if [ "$rev_bd" != "$rev_destino" ]; then
    echo "El esquema de la BD ($rev_bd) no es el de $destino ($rev_destino)."
    echo "Hay que bajar las migraciones con la imagen actual (puede borrar tablas/columnas nuevas)."
    [ -n "$(dc ps -q --status running asistente)" ] || { echo "El asistente actual no está corriendo; restaurar con deploy/backup.sh restore <archivo>."; exit 1; }
    if [ "${YES:-}" != 1 ]; then read -r -p "Se hace backup y se baja a $rev_destino. ¿Seguir? [s/N] " r; [ "$r" = s ] || exit 1; fi
    deploy/backup.sh
    dc exec -T asistente python -m asistente.store.migrar downgrade "$rev_destino"
  fi
  export ASISTENTE_VERSION=$destino
  dc up -d --no-build
else
  git pull --ff-only
  ASISTENTE_VERSION=$(git rev-parse --short HEAD)
  export ASISTENTE_VERSION
  # Copia de seguridad previa a migrar, si la BD ya está corriendo.
  if [ -n "$(dc ps -q --status running postgres 2>/dev/null)" ]; then deploy/backup.sh; fi
  dc build asistente
  dc up -d
  docker tag "asistente:$ASISTENTE_VERSION" asistente:latest
fi

echo "Esperando salud (versión $ASISTENTE_VERSION)..."
for _ in $(seq 1 30); do
  if [ "$(docker inspect -f '{{.State.Health.Status}}' "$(dc ps -q asistente)" 2>/dev/null)" = healthy ]; then
    echo "OK: asistente healthy"; dc ps; exit 0
  fi
  sleep 2
done
echo "El asistente no quedó healthy. Logs:"; dc logs --tail=50 asistente; exit 1
