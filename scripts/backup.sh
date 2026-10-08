#!/usr/bin/env bash
# Logical backup of the whole database (schema + data + routines + triggers + events).
# Usage: scripts/backup.sh [outfile]      uses TNP_* variables from .env if present
set -euo pipefail
cd "$(dirname "$0")/.."
[ -f .env ] && set -a && . ./.env && set +a
DB="${TNP_DB_NAME:-tnp_placement}"
OUT="${1:-backups/${DB}_$(date +%Y%m%d_%H%M%S).sql.gz}"
mkdir -p "$(dirname "$OUT")"
ARGS=(-u"${TNP_ADMIN_USER:-root}")
[ -n "${TNP_ADMIN_PASSWORD:-}" ] && ARGS+=(-p"${TNP_ADMIN_PASSWORD}")
[ -n "${TNP_DB_SOCKET:-}" ] && ARGS+=(--socket="$TNP_DB_SOCKET") || ARGS+=(-h"${TNP_DB_HOST:-127.0.0.1}" -P"${TNP_DB_PORT:-3306}")
# --single-transaction: consistent snapshot of InnoDB tables without locking writers
mysqldump "${ARGS[@]}" --single-transaction --routines --triggers --events --set-gtid-purged=OFF "$DB" | gzip > "$OUT"
echo "backup written to $OUT ($(du -h "$OUT" | cut -f1))"
