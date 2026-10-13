#!/usr/bin/env bash
# pg_dump the public schema to backups/syncviewer-<timestamp>.dump (local pg_dump, else Docker).
# URL: BACKUP_DATABASE_URL, then MIGRATION_DATABASE_URL, then DATABASE_URL. Not the 6543 pooler.
set -euo pipefail
export MSYS_NO_PATHCONV=1   # Git Bash on Windows: do not rewrite /backups paths passed to docker
cd "$(dirname "$0")/.."

from_env_file() { [ -f .env ] && grep -E "^$1=" .env | head -1 | cut -d= -f2- || true; }
URL="${BACKUP_DATABASE_URL:-${MIGRATION_DATABASE_URL:-${DATABASE_URL:-}}}"
[ -n "$URL" ] || URL="$(from_env_file MIGRATION_DATABASE_URL)"
[ -n "$URL" ] || URL="$(from_env_file DATABASE_URL)"
[ -n "$URL" ] || { echo "No database URL: set BACKUP_DATABASE_URL or fill .env" >&2; exit 2; }
URL="${URL/postgresql+psycopg:\/\//postgresql://}"

mkdir -p backups
FILE="syncviewer-$(date +%Y%m%d-%H%M%S).dump"
IMAGE="${PG_IMAGE:-postgres:17-alpine}"

if command -v pg_dump >/dev/null 2>&1; then
  pg_dump "$URL" --schema=public --format=custom --no-owner --no-privileges --file "backups/$FILE"
else
  # inside Docker, "localhost" is the container itself
  DURL="${URL/@localhost/@host.docker.internal}"; DURL="${DURL/@127.0.0.1/@host.docker.internal}"
  docker run --rm --add-host=host.docker.internal:host-gateway -v "$PWD/backups:/backups" "$IMAGE" \
    pg_dump "$DURL" --schema=public --format=custom --no-owner --no-privileges --file "/backups/$FILE"
fi
echo "Backup written: backups/$FILE ($(du -h "backups/$FILE" | cut -f1))"
