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
# Handles encrypted (.db.gz.enc), compressed (.db.gz) and plain (.db) snapshots.
#
# Env:  TK_DB_PATH      path to the live DB     (default: ./timekeeping.db)
#       BACKUP_KEYFILE  AES-256 passphrase file (default: <snapshot-dir>/.backup-key) — needed for .enc
set -euo pipefail

SRC="${1:-}"
DB="${TK_DB_PATH:-$(cd "$(dirname "$0")" && pwd)/timekeeping.db}"
KEYFILE="${BACKUP_KEYFILE:-$(cd "$(dirname "$SRC")" 2>/dev/null && pwd)/.backup-key}"

if [ -z "$SRC" ] || [ ! -f "$SRC" ]; then
  echo "Usage: $0 <backup-file(.db|.db.gz|.db.gz.enc)>" >&2
  exit 1
fi

echo "This will OVERWRITE the live DB at: $DB"
echo "Make sure the app is STOPPED first. Continue? [y/N]"
read -r ans
[ "$ans" = "y" ] || { echo "Aborted."; exit 1; }

TMP="$(mktemp)"
case "$SRC" in
  *.gz.enc|*.enc)
    [ -f "$KEYFILE" ] || { echo "ERROR: encrypted snapshot but no key at $KEYFILE (set BACKUP_KEYFILE)." >&2; rm -f "$TMP"; exit 1; }
    # decrypt -> the intermediate is the gzip stream; decompress it into $TMP
    openssl enc -d -aes-256-cbc -pbkdf2 -iter 200000 -in "$SRC" -pass "file:$KEYFILE" | gunzip -c > "$TMP" ;;
  *.gz)
    gunzip -c "$SRC" > "$TMP" ;;
  *)
    cp "$SRC" "$TMP" ;;
esac

# Validate the snapshot before swapping it in. Prefer the host sqlite3 CLI; fall back to python3
# (always present via the app image / most hosts) so a host without the CLI can still verify.
check_ok() {
  if command -v sqlite3 >/dev/null 2>&1; then
    sqlite3 "$1" "PRAGMA integrity_check;" 2>/dev/null | grep -q '^ok$'
  elif command -v python3 >/dev/null 2>&1; then
    python3 -c "import sqlite3,sys; r=sqlite3.connect(sys.argv[1]).execute('PRAGMA integrity_check').fetchone(); sys.exit(0 if r and r[0]=='ok' else 1)" "$1"
  else
    echo "WARN: neither sqlite3 nor python3 found — skipping integrity check." >&2
    return 0
  fi
}
if ! check_ok "$TMP"; then
  echo "ERROR: snapshot failed integrity_check — not restoring." >&2
  rm -f "$TMP"; exit 1
fi

# Keep a safety copy of whatever is currently live.
[ -f "$DB" ] && cp "$DB" "$DB.before-restore-$(date +%Y%m%d%H%M%S)"

mv "$TMP" "$DB"
echo "Restored $DB from $SRC. You can start the app now."
