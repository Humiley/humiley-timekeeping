#!/usr/bin/env bash
# Humiley People & Workplace Portal — daily SQLite backup.
# SQLite's online .backup makes a consistent snapshot while the app is running.
#
# Run daily from cron, e.g.:   0 1 * * *  /opt/humiley/backup.sh >> /var/log/humiley-backup.log 2>&1
# Or as a Docker sidecar / host cron with the data volume mounted.
#
# Env:
#   TK_DB_PATH    path to the live DB           (default: ./timekeeping.db, matches app.py/Dockerfile)
#   BACKUP_DIR    where snapshots are written   (default: <db dir>/backups)
#   RETAIN_DAYS   delete snapshots older than N  (default: 14)
set -euo pipefail

DB="${TK_DB_PATH:-$(cd "$(dirname "$0")" && pwd)/timekeeping.db}"
BACKUP_DIR="${BACKUP_DIR:-$(dirname "$DB")/backups}"
RETAIN_DAYS="${RETAIN_DAYS:-14}"

if [ ! -f "$DB" ]; then
  echo "ERROR: database not found at $DB" >&2
  exit 1
fi

mkdir -p "$BACKUP_DIR"
STAMP="$(date +%Y-%m-%d_%H%M%S)"
OUT="$BACKUP_DIR/timekeeping-$STAMP.db"

# Consistent online snapshot (safe while the server is serving requests).
sqlite3 "$DB" ".backup '$OUT'"
gzip -f "$OUT"
echo "[$(date +%F\ %T)] backup OK -> $OUT.gz ($(du -h "$OUT.gz" | cut -f1))"

# Retention: prune old compressed snapshots.
find "$BACKUP_DIR" -name 'timekeeping-*.db.gz' -type f -mtime +"$RETAIN_DAYS" -delete 2>/dev/null || true
echo "[$(date +%F\ %T)] pruned snapshots older than ${RETAIN_DAYS}d"

# TIP: copy the newest snapshot off-box (SharePoint/OneDrive) so a lost volume is recoverable:
#   rclone copy "$BACKUP_DIR" humiley-onedrive:Backups/Portal --max-age 25h
