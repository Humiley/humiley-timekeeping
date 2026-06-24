#!/usr/bin/env bash
# Humiley People & Workplace Portal — restore the SQLite DB from a backup snapshot.
#
# Usage:  ./restore.sh /data/backups/timekeeping-2026-06-24_010000.db.gz
#
# RUNBOOK:
#   1. Stop the app   (docker stop humiley_portal   OR   systemctl stop humiley)
#   2. ./restore.sh <snapshot>     (keeps a safety copy of the current DB)
#   3. Start the app  (docker start humiley_portal  OR   systemctl start humiley)
#
# Env:  TK_DB_PATH  path to the live DB (default: ./timekeeping.db)
set -euo pipefail

SRC="${1:-}"
DB="${TK_DB_PATH:-$(cd "$(dirname "$0")" && pwd)/timekeeping.db}"

if [ -z "$SRC" ] || [ ! -f "$SRC" ]; then
  echo "Usage: $0 <backup-file(.db|.db.gz)>" >&2
  exit 1
fi

echo "This will OVERWRITE the live DB at: $DB"
echo "Make sure the app is STOPPED first. Continue? [y/N]"
read -r ans
[ "$ans" = "y" ] || { echo "Aborted."; exit 1; }

TMP="$(mktemp)"
case "$SRC" in
  *.gz) gunzip -c "$SRC" > "$TMP" ;;
  *)    cp "$SRC" "$TMP" ;;
esac

# Validate the snapshot before swapping it in.
if ! sqlite3 "$TMP" "PRAGMA integrity_check;" | grep -q '^ok$'; then
  echo "ERROR: snapshot failed integrity_check — not restoring." >&2
  rm -f "$TMP"; exit 1
fi

# Keep a safety copy of whatever is currently live.
[ -f "$DB" ] && cp "$DB" "$DB.before-restore-$(date +%Y%m%d%H%M%S)"

mv "$TMP" "$DB"
echo "Restored $DB from $SRC. You can start the app now."
