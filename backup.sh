#!/usr/bin/env bash
# Humiley People & Workplace Portal — nightly SQLite backup (Docker deployment).
# Makes a CONSISTENT online backup of the live DB INSIDE the running container
# (Python's sqlite3 .backup is safe while the app is serving), copies it to the
# host, gzip-compresses it, and prunes copies older than RETAIN_DAYS.
#
# Run daily from cron, e.g.:
#   0 2 * * *  /opt/humiley-timekeeping/backup.sh >> /var/log/humiley-backup.log 2>&1
#
# The DB holds sensitive HR/finance data (GPS, payroll, leave, e-sign records). If a key file is
# present the snapshot is ENCRYPTED at rest with AES-256 before it ever leaves this box — so the
# off-box copy on OneDrive/SharePoint is ciphertext. Create the key ONCE (keep it OFF the server too,
# in a password manager — losing it means losing every encrypted backup):
#   openssl rand -base64 48 > /root/humiley-backups/.backup-key && chmod 600 /root/humiley-backups/.backup-key
# With no key file, it falls back to plain gzip (a warning is logged) so the cron never silently fails.
#
# Env (all optional):
#   TK_CONTAINER    app container name      (default: humiley_portal)
#   BACKUP_DIR      where snapshots go      (default: /root/humiley-backups)
#   RETAIN_DAYS     delete older than N     (default: 14)
#   BACKUP_KEYFILE  AES-256 passphrase file (default: $BACKUP_DIR/.backup-key; absent => plaintext)
set -euo pipefail

CONTAINER="${TK_CONTAINER:-humiley_portal}"
BACKUP_DIR="${BACKUP_DIR:-/root/humiley-backups}"
RETAIN_DAYS="${RETAIN_DAYS:-14}"
KEYFILE="${BACKUP_KEYFILE:-$BACKUP_DIR/.backup-key}"
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

# 3) Encrypt at rest (AES-256-CBC + PBKDF2) if a key file exists; otherwise keep plaintext + warn.
FINAL="$OUT.gz"
if [ -f "$KEYFILE" ]; then
  openssl enc -aes-256-cbc -pbkdf2 -iter 200000 -salt -in "$OUT.gz" -out "$OUT.gz.enc" -pass "file:$KEYFILE"
  rm -f "$OUT.gz"
  FINAL="$OUT.gz.enc"
  echo "[$(date +%F\ %T)] backup OK (encrypted) -> $FINAL ($(du -h "$FINAL" | cut -f1))"
else
  echo "[$(date +%F\ %T)] backup OK (PLAINTEXT — no key at $KEYFILE) -> $FINAL ($(du -h "$FINAL" | cut -f1))" >&2
fi

# 4) Retention: prune old snapshots (both encrypted + plaintext forms).
find "$BACKUP_DIR" -name 'timekeeping-*.db.gz' -o -name 'timekeeping-*.db.gz.enc' -type f -mtime +"$RETAIN_DAYS" -delete 2>/dev/null || true
echo "[$(date +%F\ %T)] kept $(ls -1 "$BACKUP_DIR"/timekeeping-*.db.gz* 2>/dev/null | wc -l | tr -d ' ') snapshot(s); pruned older than ${RETAIN_DAYS}d"

# TIP: copy the newest snapshot off-box (OneDrive/SharePoint) so a lost VPS is recoverable:
#   rclone copy "$BACKUP_DIR" humiley-onedrive:Backups/Portal --max-age 25h
#
# RESTORE later with ./restore.sh (it auto-decrypts .enc + decompresses .gz):
#   ./restore.sh /root/humiley-backups/timekeeping-YYYY-MM-DD_HHMMSS.db.gz.enc
# RESTORE DRILL (do quarterly): restore the newest snapshot into a THROWAWAY path and check it opens —
#   TK_DB_PATH=/tmp/drill.db ./restore.sh <newest.enc> && \
#   docker run --rm -v /tmp/drill.db:/data/timekeeping.db humiley_portal python3 -c \
#     "import sqlite3; print(sqlite3.connect('/data/timekeeping.db').execute('select count(*) from employees').fetchone())"
# A restore path that is never rehearsed is not a backup.
