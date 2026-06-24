#!/usr/bin/env bash
# Humiley People & Workplace Portal — nightly SQLite backup (Docker deployment).
# Makes a CONSISTENT online backup of the live DB INSIDE the running container
# (Python's sqlite3 .backup is safe while the app is serving), copies it to the
# host, gzip-compresses it, and prunes copies older than RETAIN_DAYS.
#
# Run daily from cron, e.g.:
#   0 2 * * *  /opt/humiley-timekeeping/backup.sh >> /var/log/humiley-backup.log 2>&1
#
# Env (all optional):
#   TK_CONTAINER   app container name      (default: humiley_portal)
#   BACKUP_DIR     where snapshots go      (default: /root/humiley-backups)
#   RETAIN_DAYS    delete older than N     (default: 14)
set -euo pipefail

CONTAINER="${TK_CONTAINER:-humiley_portal}"
BACKUP_DIR="${BACKUP_DIR:-/root/humiley-backups}"
RETAIN_DAYS="${RETAIN_DAYS:-14}"
STAMP="$(date +%Y-%m-%d_%H%M%S)"
OUT="$BACKUP_DIR/timekeeping-$STAMP.db"

mkdir -p "$BACKUP_DIR"

# 1) Consistent online snapshot inside the container (uses the app's own Python; no host sqlite3 needed).
docker exec "$CONTAINER" python3 -c "import sqlite3,os; \
src=sqlite3.connect(os.environ.get('TK_DB_PATH','/data/timekeeping.db')); \
dst=sqlite3.connect('/data/_backup.db'); src.backup(dst); dst.close(); src.close()"

# 2) Copy out to the host, compress, remove the temp copy from the volume.
docker cp "$CONTAINER:/data/_backup.db" "$OUT"
gzip -f "$OUT"
docker exec "$CONTAINER" rm -f /data/_backup.db 2>/dev/null || true
echo "[$(date +%F\ %T)] backup OK -> $OUT.gz ($(du -h "$OUT.gz" | cut -f1))"

# 3) Retention: prune old compressed snapshots.
find "$BACKUP_DIR" -name 'timekeeping-*.db.gz' -type f -mtime +"$RETAIN_DAYS" -delete 2>/dev/null || true
echo "[$(date +%F\ %T)] kept $(ls -1 "$BACKUP_DIR"/timekeeping-*.db.gz 2>/dev/null | wc -l | tr -d ' ') snapshot(s); pruned older than ${RETAIN_DAYS}d"

# TIP: copy the newest snapshot off-box (OneDrive/SharePoint) so a lost VPS is recoverable:
#   rclone copy "$BACKUP_DIR" humiley-onedrive:Backups/Portal --max-age 25h
#
# --- RESTORE a snapshot later ----------------------------------------------------
#   gunzip -k /root/humiley-backups/timekeeping-YYYY-MM-DD_HHMMSS.db.gz
#   docker cp timekeeping-YYYY-MM-DD_HHMMSS.db humiley_portal:/data/timekeeping.db
#   docker restart humiley_portal
# ---------------------------------------------------------------------------------
