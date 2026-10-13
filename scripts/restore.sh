#!/usr/bin/env bash
# Restore a backup.sh dump: scripts/restore.sh <file> [--yes]
# Drops and recreates the dumped objects (pg_restore --clean); prefer an empty database.
set -euo pipefail
export MSYS_NO_PATHCONV=1   # Git Bash on Windows: do not rewrite /backups paths passed to docker
cd "$(dirname "$0")/.."

FILE="${1:-}"; [ -f "$FILE" ] || { echo "usage: $0 <backup.dump> [--yes]" >&2; exit 2; }
from_env_file() { [ -f .env ] && grep -E "^$1=" .env | head -1 | cut -d= -f2- || true; }
URL="${RESTORE_DATABASE_URL:-${MIGRATION_DATABASE_URL:-${DATABASE_URL:-}}}"
[ -n "$URL" ] || URL="$(from_env_file MIGRATION_DATABASE_URL)"
[ -n "$URL" ] || URL="$(from_env_file DATABASE_URL)"
[ -n "$URL" ] || { echo "No database URL: set RESTORE_DATABASE_URL or fill .env" >&2; exit 2; }
URL="${URL/postgresql+psycopg:\/\//postgresql://}"

if [ "${2:-}" != "--yes" ]; then
  echo "About to restore $FILE into: ${URL%%@*}@${URL#*@}" | sed -E 's#://[^:]+:[^@]+@#://***:***@#'
  read -r -p "This replaces existing objects. Type 'restore' to continue: " ans
  [ "$ans" = "restore" ] || { echo "aborted"; exit 1; }
fi

IMAGE="${PG_IMAGE:-postgres:17-alpine}"
if command -v pg_restore >/dev/null 2>&1; then
  pg_restore --dbname "$URL" --clean --if-exists --no-owner --no-privileges "$FILE"
else
  DURL="${URL/@localhost/@host.docker.internal}"; DURL="${DURL/@127.0.0.1/@host.docker.internal}"
  docker run --rm --add-host=host.docker.internal:host-gateway \
    -v "$PWD/$(dirname "$FILE"):/backups:ro" "$IMAGE" \
    pg_restore --dbname "$DURL" --clean --if-exists --no-owner --no-privileges \
    "/backups/$(basename "$FILE")"
fi
echo "Restore finished."
