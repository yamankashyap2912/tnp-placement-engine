#!/usr/bin/env bash
# Restore a backup made by scripts/backup.sh into a (new) database.
# Usage: scripts/restore.sh backups/file.sql.gz [target_db]
set -euo pipefail
cd "$(dirname "$0")/.."
[ -f .env ] && set -a && . ./.env && set +a
FILE="${1:?usage: restore.sh backup.sql.gz [target_db]}"
DB="${2:-${TNP_DB_NAME:-tnp_placement}}"
ARGS=(-u"${TNP_ADMIN_USER:-root}")
[ -n "${TNP_ADMIN_PASSWORD:-}" ] && ARGS+=(-p"${TNP_ADMIN_PASSWORD}")
[ -n "${TNP_DB_SOCKET:-}" ] && ARGS+=(--socket="$TNP_DB_SOCKET") || ARGS+=(-h"${TNP_DB_HOST:-127.0.0.1}" -P"${TNP_DB_PORT:-3306}")
mysql "${ARGS[@]}" -e "CREATE DATABASE IF NOT EXISTS \`$DB\` CHARACTER SET utf8mb4"
gunzip -c "$FILE" | mysql "${ARGS[@]}" "$DB"
echo "restored $FILE into $DB"
