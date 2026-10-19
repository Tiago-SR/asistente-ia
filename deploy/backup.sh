#!/usr/bin/env bash
# Volcado de Postgres a backups/asistente-<fecha>.sql.gz.gpg, cifrado con la clave PÚBLICA BACKUP_GPG_RECIPIENT
# (importada en este host; la privada se guarda fuera de él). Conserva los últimos KEEP (14).
# Cron diario: 0 3 * * *  cd /opt/asistente-mvp && deploy/backup.sh >> backups/backup.log 2>&1
# Restaurar:   deploy/backup.sh restore backups/archivo.sql.gz.gpg   (necesita la clave privada en gpg)
set -euo pipefail
umask 077
cd "$(dirname "$0")/.."
COMPOSE_FILES=${COMPOSE_FILES:--f docker-compose.yml -f docker-compose.prod.yml}
dc() { docker compose $COMPOSE_FILES "$@"; }
mkdir -p backups

if [ "${1:-}" = restore ]; then
  f=${2:?indicar el archivo .sql.gz.gpg}
  echo "Esto REEMPLAZA la base actual con $f. Ctrl-C para cancelar (5 s)"; sleep 5
  dc stop asistente
  dc exec -T postgres psql -U asistente -d postgres -c "DROP DATABASE IF EXISTS asistente" -c "CREATE DATABASE asistente"
  gpg --decrypt "$f" | gunzip | dc exec -T postgres psql -U asistente -d asistente -q
  dc start asistente
  exit 0
fi

receptor=${BACKUP_GPG_RECIPIENT:?indicar BACKUP_GPG_RECIPIENT (clave pública gpg)}
salida="backups/asistente-$(date +%Y%m%d-%H%M%S).sql.gz.gpg"
trap 'rm -f "$salida"' ERR  # un volcado parcial no se queda ni cuenta para la retención
dc exec -T postgres pg_dump -U asistente --no-owner asistente | gzip | gpg --batch --yes --encrypt --recipient "$receptor" -o "$salida"
[ -s "$salida" ] || { rm -f "$salida"; echo "Backup vacío"; exit 1; }
echo "Backup: $salida"
ls -1t backups/asistente-*.sql.gz.gpg | tail -n +$(( ${KEEP:-14} + 1 )) | xargs -r rm --
