#!/usr/bin/env bash
# Humiley Procurement — restore the Postgres database and/or the uploaded-files volume.
#
# The portal's SQLite has ./restore.sh; this is its counterpart for the Procurement side, which lives
# in a completely different engine (Postgres in the `procdb` container) and a Docker volume
# (`proc_storage`, the uploaded invoices and bills). Both are produced by ./backup.sh.
#
# Usage:
#   ./restore-procurement.sh --db      /root/humiley-backups/procurement-2026-08-04_020000.sql.gz.enc
#   ./restore-procurement.sh --files   /root/humiley-backups/proc-storage-2026-08-04_020000.tgz.enc
#   ./restore-procurement.sh --db X --files Y            # both, in the right order
#   ./restore-procurement.sh --db X --dry-run            # decrypt + validate, change nothing
#
# RUNBOOK:
#   1. docker compose stop procurement          # stop the app, LEAVE procdb running
#   2. ./restore-procurement.sh --db <snap> --files <snap>
#   3. docker compose start procurement
#
# Handles encrypted (.enc), compressed (.gz/.tgz) and plain inputs.
#
# Env:  PROC_DB_CONTAINER   default humiley_proc_db
#       PROC_APP_CONTAINER  default humiley_proc_app   (used only to resolve the storage volume)
#       BACKUP_KEYFILE      AES-256 passphrase file (default: <snapshot-dir>/.backup-key)
set -euo pipefail

PROC_DB_CONTAINER="${PROC_DB_CONTAINER:-humiley_proc_db}"
PROC_APP_CONTAINER="${PROC_APP_CONTAINER:-humiley_proc_app}"
DB_SNAP=""; FILES_SNAP=""; DRY=0

while [ $# -gt 0 ]; do
  case "$1" in
    --db)      DB_SNAP="${2:-}"; shift 2 ;;
    --files)   FILES_SNAP="${2:-}"; shift 2 ;;
    --dry-run) DRY=1; shift ;;
    -h|--help) sed -n '2,22p' "$0"; exit 0 ;;
    *) echo "unknown argument: $1" >&2; exit 2 ;;
  esac
done

if [ -z "$DB_SNAP" ] && [ -z "$FILES_SNAP" ]; then
  echo "Nothing to do — pass --db and/or --files. See --help." >&2; exit 2
fi
for f in "$DB_SNAP" "$FILES_SNAP"; do
  if [ -n "$f" ] && [ ! -f "$f" ]; then echo "✖ not found: $f" >&2; exit 1; fi
done

# The key defaults to the snapshot directory's own .backup-key, matching backup.sh/restore.sh.
_dir_of() { (cd "$(dirname "$1")" && pwd); }
KEYFILE="${BACKUP_KEYFILE:-$(_dir_of "${DB_SNAP:-$FILES_SNAP}")/.backup-key}"

# Stream a snapshot to stdout, decrypting first when it is .enc. Kept as one function so the DB and
# the files path can never disagree about how a snapshot is opened.
_open() { # $1 = path
  case "$1" in
    *.enc)
      if [ ! -f "$KEYFILE" ]; then
        echo "✖ $1 is encrypted but no key at $KEYFILE (set BACKUP_KEYFILE)." >&2; return 1
      fi
      openssl enc -d -aes-256-cbc -pbkdf2 -iter 200000 -in "$1" -pass "file:$KEYFILE" ;;
    *) cat "$1" ;;
  esac
}

say() { printf '\n\033[1;34m==>\033[0m %s\n' "$*"; }

# ── Validate BEFORE touching anything. A restore that fails halfway is worse than one that
#    never started, so every snapshot is decrypted and inspected first.
if [ -n "$DB_SNAP" ]; then
  say "Checking the database snapshot…"
  TABLES="$(_open "$DB_SNAP" | gzip -dc 2>/dev/null | grep -c 'CREATE TABLE' || true)"
  if [ "${TABLES:-0}" -lt 1 ]; then
    echo "✖ $DB_SNAP decrypts but contains no CREATE TABLE — refusing to restore an empty dump." >&2
    exit 1
  fi
  echo "    OK — $TABLES table(s) in the dump."
fi
if [ -n "$FILES_SNAP" ]; then
  say "Checking the uploads snapshot…"
  if ! _open "$FILES_SNAP" | tar tz >/dev/null 2>&1; then
    echo "✖ $FILES_SNAP is not a readable tar.gz." >&2; exit 1
  fi
  echo "    OK — $(_open "$FILES_SNAP" | tar tz 2>/dev/null | wc -l | tr -d ' ') entry(ies) in the archive."
fi

if [ "$DRY" -eq 1 ]; then say "--dry-run: snapshots are valid. Nothing was changed."; exit 0; fi

echo
echo "This will OVERWRITE live Procurement data:"
[ -n "$DB_SNAP" ]    && echo "  • the '$PROC_DB_CONTAINER' database  <- $DB_SNAP"
[ -n "$FILES_SNAP" ] && echo "  • the uploaded invoices/bills volume <- $FILES_SNAP"
echo "Stop the Procurement APP first (docker compose stop procurement); leave procdb running."
echo "Continue? [y/N]"
read -r ans
[ "$ans" = "y" ] || { echo "Aborted."; exit 1; }

if [ -n "$DB_SNAP" ]; then
  if ! docker ps --format '{{.Names}}' | grep -qx "$PROC_DB_CONTAINER"; then
    echo "✖ '$PROC_DB_CONTAINER' is not running — start it first (docker compose up -d procdb)." >&2; exit 1
  fi
  # Safety net: dump what is there NOW before overwriting it, so a wrong-snapshot restore is undoable.
  SAFETY="$(_dir_of "$DB_SNAP")/pre-restore-$(date +%Y-%m-%d_%H%M%S).sql.gz"
  say "Saving the CURRENT database first -> $SAFETY"
  docker exec "$PROC_DB_CONTAINER" sh -c 'pg_dump --clean --if-exists -U "$POSTGRES_USER" "$POSTGRES_DB"' \
    | gzip -c > "$SAFETY" || { echo "✖ could not snapshot the current DB — aborting." >&2; exit 1; }

  say "Restoring the database…"
  # The dump was taken with --clean --if-exists, so it drops and recreates each object itself.
  # ON_ERROR_STOP makes psql fail loudly instead of limping through a half-applied restore.
  if ! _open "$DB_SNAP" | gzip -dc | docker exec -i "$PROC_DB_CONTAINER" \
        sh -c 'psql -v ON_ERROR_STOP=1 -U "$POSTGRES_USER" -d "$POSTGRES_DB"' ; then
    echo "✖ restore FAILED. Your pre-restore snapshot is at: $SAFETY" >&2
    exit 1
  fi
  echo "    database restored."
fi

if [ -n "$FILES_SNAP" ]; then
  STOR_VOL="$(docker inspect "$PROC_APP_CONTAINER" \
      --format '{{range .Mounts}}{{if eq .Destination "/app/storage"}}{{.Name}}{{end}}{{end}}' 2>/dev/null || true)"
  if [ -z "$STOR_VOL" ]; then
    echo "✖ could not resolve the proc_storage volume from '$PROC_APP_CONTAINER'." >&2
    echo "   Start the container once (docker compose up -d procurement) so the mount exists, then retry." >&2
    exit 1
  fi
  say "Restoring uploads into volume $STOR_VOL …"
  # Extract into the volume. Existing files with the same path are overwritten; anything uploaded
  # since the snapshot is left in place rather than deleted — losing newer files to an older archive
  # would be the more destructive default.
  _open "$FILES_SNAP" | docker run --rm -i -v "$STOR_VOL":/data alpine tar xzf - -C /data
  echo "    uploads restored."
fi

say "Done. Start the app:  docker compose start procurement"
echo "Then verify in the UI: open a PO and a GRN, and download one uploaded invoice."
