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
# FAIL-CLOSED: with no key file this script now ABORTS instead of writing a plaintext snapshot. The
# backup directory is meant to be copied off-box (see the rclone TIP at the bottom), so a silent
# plaintext fallback would ship unencrypted payroll/PII/GPS to consumer cloud. Set
# BACKUP_ALLOW_PLAINTEXT=1 to deliberately opt out (dev/testing only — never in production).
#
# Env (all optional):
#   TK_CONTAINER    app container name      (default: humiley_portal)
#   BACKUP_DIR      where snapshots go      (default: /root/humiley-backups)
#   RETAIN_DAYS     delete older than N     (default: 14)
#   BACKUP_KEYFILE  AES-256 passphrase file (default: $BACKUP_DIR/.backup-key; absent => ABORT)
#   BACKUP_ALLOW_PLAINTEXT=1  allow an UNENCRYPTED snapshot (dev only; prints a loud warning)
set -euo pipefail

CONTAINER="${TK_CONTAINER:-humiley_portal}"
BACKUP_DIR="${BACKUP_DIR:-/root/humiley-backups}"
RETAIN_DAYS="${RETAIN_DAYS:-14}"
KEYFILE="${BACKUP_KEYFILE:-$BACKUP_DIR/.backup-key}"
STAMP="$(date +%Y-%m-%d_%H%M%S)"
OUT="$BACKUP_DIR/timekeeping-$STAMP.db"

mkdir -p "$BACKUP_DIR"

# 0) FAIL-CLOSED KEY CHECK — before any data leaves the container. This directory gets copied off-box,
#    so a missing key must abort the run, not silently produce a plaintext dump of payroll/PII/GPS.
if [ ! -f "$KEYFILE" ]; then
  if [ "${BACKUP_ALLOW_PLAINTEXT:-0}" = "1" ]; then
    echo "[$(date +%F\ %T)] ⚠️  BACKUP_ALLOW_PLAINTEXT=1 — writing an UNENCRYPTED snapshot. Never do this in production." >&2
  else
    echo "[$(date +%F\ %T)] ✖ ABORT: no encryption key at $KEYFILE — refusing to write a plaintext backup of HR/finance data." >&2
    echo "    Create it once (and store a copy OFF this server, in a password manager):" >&2
    echo "      openssl rand -base64 48 > $KEYFILE && chmod 600 $KEYFILE" >&2
    echo "    Or set BACKUP_ALLOW_PLAINTEXT=1 to override (dev/testing only)." >&2
    exit 1
  fi
fi

# 1) Consistent online snapshot inside the container (uses the app's own Python; no host sqlite3 needed).
docker exec "$CONTAINER" python3 -c "import sqlite3,os; \
src=sqlite3.connect(os.environ.get('TK_DB_PATH','/data/timekeeping.db')); \
dst=sqlite3.connect('/data/_backup.db'); src.backup(dst); dst.close(); src.close()"

# 1b) VERIFY AT CREATION — a backup is only real if it's readable. Check SQLite integrity and assert the
#     snapshot actually holds rows, so corruption/truncation is caught NOW rather than during a restore
#     in an emergency. Any failure aborts (and clears the temp copy) so a bad snapshot is never kept.
if ! docker exec "$CONTAINER" python3 -c "
import sqlite3, sys
c = sqlite3.connect('/data/_backup.db')
ok = c.execute('PRAGMA integrity_check').fetchone()[0]
if ok != 'ok':
    print('integrity_check failed: %s' % ok); sys.exit(1)
n = c.execute('SELECT COUNT(*) FROM employees').fetchone()[0]
if n < 1:
    print('sanity check failed: employees table is empty'); sys.exit(1)
print('verified: integrity ok, %d employee row(s)' % n)
"; then
  echo "[$(date +%F\ %T)] ✖ ABORT: snapshot failed verification — not keeping it." >&2
  docker exec "$CONTAINER" rm -f /data/_backup.db 2>/dev/null || true
  exit 1
fi

# 2) Copy out to the host, compress, remove the temp copy from the volume.
docker cp "$CONTAINER:/data/_backup.db" "$OUT"
gzip -f "$OUT"
docker exec "$CONTAINER" rm -f /data/_backup.db 2>/dev/null || true

# 3) Encrypt at rest (AES-256-CBC + PBKDF2). The key was already required in step 0, so reaching the
#    plaintext branch means BACKUP_ALLOW_PLAINTEXT=1 was set deliberately.
FINAL="$OUT.gz"
if [ -f "$KEYFILE" ]; then
  openssl enc -aes-256-cbc -pbkdf2 -iter 200000 -salt -in "$OUT.gz" -out "$OUT.gz.enc" -pass "file:$KEYFILE"
  # Verify the ciphertext actually decrypts with this key before discarding the plaintext — an
  # unreadable "backup" is worse than none, and this catches a truncated write or a bad key file.
  if ! openssl enc -d -aes-256-cbc -pbkdf2 -iter 200000 -in "$OUT.gz.enc" -pass "file:$KEYFILE" 2>/dev/null | gzip -t; then
    echo "[$(date +%F\ %T)] ✖ ABORT: the encrypted snapshot did not decrypt/verify — keeping nothing." >&2
    rm -f "$OUT.gz.enc" "$OUT.gz"
    exit 1
  fi
  rm -f "$OUT.gz"
  FINAL="$OUT.gz.enc"
  echo "[$(date +%F\ %T)] backup OK (encrypted, decrypt-verified) -> $FINAL ($(du -h "$FINAL" | cut -f1))"
else
  echo "[$(date +%F\ %T)] backup OK (⚠️ UNENCRYPTED — BACKUP_ALLOW_PLAINTEXT=1) -> $FINAL ($(du -h "$FINAL" | cut -f1))" >&2
fi

# ── 4) PROCUREMENT: Postgres + the uploads volume ────────────────────────────────────────────────
# The portal SQLite above is only half the company's data. `procdb` holds every PO, GRN, the approval
# matrix and Procurement's own Part-11 e-signature chain; `proc_storage` holds the uploaded invoices
# and bills. Both were previously backed up by NOTHING — a lost host lost them outright.
#
# Best-effort by design: a portal-only install has no procdb, and the portal snapshot above (already
# written and verified) must not be thrown away because Procurement isn't deployed. A real FAILURE of
# a procdb that IS running is loud and sets a non-zero exit at the end.
PROC_DB_CONTAINER="${PROC_DB_CONTAINER:-humiley_proc_db}"
PROC_APP_CONTAINER="${PROC_APP_CONTAINER:-humiley_proc_app}"
PROC_RC=0

if docker ps --format '{{.Names}}' | grep -qx "$PROC_DB_CONTAINER"; then
  PGOUT="$BACKUP_DIR/procurement-$STAMP.sql.gz"
  # Run pg_dump INSIDE the container using the container's OWN env, so credentials are never parsed
  # out of .env on the host and never appear in the host process list.
  if docker exec "$PROC_DB_CONTAINER" sh -c \
        'pg_dump --clean --if-exists -U "$POSTGRES_USER" "$POSTGRES_DB"' 2>/dev/null | gzip -c > "$PGOUT"; then
    # A pg_dump that "succeeds" but emits a stub is the failure mode that matters — it restores
    # cleanly and silently loses everything. Require the schema to actually be in there.
    if gzip -t "$PGOUT" 2>/dev/null && [ "$(gzip -dc "$PGOUT" | grep -c 'CREATE TABLE')" -ge 1 ]; then
      echo "[$(date +%F\ %T)] procurement pg_dump OK ($(gzip -dc "$PGOUT" | grep -c 'CREATE TABLE') tables, $(du -h "$PGOUT" | cut -f1))"
    else
      echo "[$(date +%F\ %T)] ✖ procurement pg_dump produced no tables — discarding it." >&2
      rm -f "$PGOUT"; PROC_RC=1
    fi
  else
    echo "[$(date +%F\ %T)] ✖ procurement pg_dump FAILED." >&2
    rm -f "$PGOUT"; PROC_RC=1
  fi

  # Uploaded invoices/bills. Resolve the volume from the RUNNING container rather than hardcoding a
  # name — compose prefixes volumes with the project directory, which differs per install.
  STOR_VOL="$(docker inspect "$PROC_APP_CONTAINER" \
      --format '{{range .Mounts}}{{if eq .Destination "/app/storage"}}{{.Name}}{{end}}{{end}}' 2>/dev/null || true)"
  if [ -n "$STOR_VOL" ]; then
    STOROUT="$BACKUP_DIR/proc-storage-$STAMP.tgz"
    if docker run --rm -v "$STOR_VOL":/data:ro -v "$BACKUP_DIR":/out alpine \
         tar czf "/out/$(basename "$STOROUT")" -C /data . 2>/dev/null && tar tzf "$STOROUT" >/dev/null 2>&1; then
      echo "[$(date +%F\ %T)] procurement uploads OK ($(du -h "$STOROUT" | cut -f1), volume $STOR_VOL)"
    else
      echo "[$(date +%F\ %T)] ✖ procurement uploads archive FAILED or is unreadable." >&2
      rm -f "$STOROUT"; PROC_RC=1
    fi
  else
    echo "[$(date +%F\ %T)] ⚠️  could not resolve the proc_storage volume — uploads NOT backed up." >&2
    PROC_RC=1
  fi

  # Encrypt both with the SAME key, and decrypt-verify before discarding the plaintext. Procurement
  # invoices and vendor bank details are exactly as sensitive as the portal's payroll data.
  if [ -f "$KEYFILE" ]; then
    for f in "$BACKUP_DIR/procurement-$STAMP.sql.gz" "$BACKUP_DIR/proc-storage-$STAMP.tgz"; do
      [ -f "$f" ] || continue
      if openssl enc -aes-256-cbc -pbkdf2 -iter 200000 -salt -in "$f" -out "$f.enc" -pass "file:$KEYFILE" 2>/dev/null \
         && openssl enc -d -aes-256-cbc -pbkdf2 -iter 200000 -in "$f.enc" -pass "file:$KEYFILE" 2>/dev/null | gzip -t 2>/dev/null; then
        rm -f "$f"
        echo "[$(date +%F\ %T)] encrypted + decrypt-verified -> $f.enc"
      else
        echo "[$(date +%F\ %T)] ✖ could not encrypt/verify $f — keeping nothing for it." >&2
        rm -f "$f.enc" "$f"; PROC_RC=1
      fi
    done
  fi
else
  echo "[$(date +%F\ %T)] procurement: container '$PROC_DB_CONTAINER' not running — skipping (portal-only install?)"
fi

# ── 5) Retention: prune old snapshots (encrypted + plaintext, portal + procurement) ───────────────
# The parentheses are REQUIRED. Without them find parses this as
#   ( -name A ) OR ( -name B AND -type f AND -mtime +N AND -delete )
# because the implicit AND binds tighter than -o — so -delete applied to only the LAST name pattern
# and plaintext snapshots were never pruned at all. Verified with a real find before/after.
find "$BACKUP_DIR" -type f \
     \( -name 'timekeeping-*.db.gz'    -o -name 'timekeeping-*.db.gz.enc' \
     -o -name 'procurement-*.sql.gz'   -o -name 'procurement-*.sql.gz.enc' \
     -o -name 'proc-storage-*.tgz'     -o -name 'proc-storage-*.tgz.enc' \) \
     -mtime +"$RETAIN_DAYS" -delete 2>/dev/null || true
echo "[$(date +%F\ %T)] kept $(find "$BACKUP_DIR" -maxdepth 1 -type f \( -name 'timekeeping-*' -o -name 'procurement-*' -o -name 'proc-storage-*' \) | wc -l | tr -d ' ') file(s); pruned older than ${RETAIN_DAYS}d"

# ── 6) Off-box copy ───────────────────────────────────────────────────────────────────────────────
# Everything above still lives on the same disk as the data it protects — it survives a bad deploy or
# a dropped table and nothing else. offsite.sh ships the ENCRYPTED snapshots to an rclone remote.
# Opt-in: it does nothing until OFFSITE_REMOTE is configured, so an install without rclone is unaffected.
OFFSITE_RC=0
# SharePoint / OneDrive via Microsoft Graph. Preferred over rclone here because the portal ALREADY
# holds an app-only Graph secret (that is how invoices reach the Finance folder), so there is no
# browser sign-in to complete on a headless box — which is exactly where the rclone route stalled.
if [ -n "$(grep -Es '^(BACKUP_SP_URL|BACKUP_SP_USER)=.' "$(dirname "$0")/.env" 2>/dev/null)" ]; then
  if python3 "$(dirname "$0")/backup_sharepoint.py"; then :; else
    OFFSITE_RC=$?
    echo "[$(date +%F\ %T)] ✖ SharePoint off-box copy FAILED — snapshots are still only on this server." >&2
  fi
fi
if [ -x "$(dirname "$0")/offsite.sh" ]; then
  if "$(dirname "$0")/offsite.sh"; then :; else
    OFFSITE_RC=$?
    # Only complain when it was actually configured. Exit 1 with no OFFSITE_REMOTE just means
    # "off-box copying isn't set up yet", which is not a backup failure.
    if grep -qs '^OFFSITE_REMOTE=' "$(dirname "$0")/.env" || [ -n "${OFFSITE_REMOTE:-}" ]; then
      echo "[$(date +%F\ %T)] ✖ off-box copy FAILED — the snapshots are still only on this server." >&2
    else
      OFFSITE_RC=0   # not configured; stay quiet
    fi
  fi
fi

# Failures are reported AFTER the portal snapshot is safely written, and exit non-zero so
# cron/healthchecks.io sees a red run instead of a silent half-backup.
if [ "$PROC_RC" -ne 0 ]; then
  echo "[$(date +%F\ %T)] ✖ PORTAL backup succeeded but PROCUREMENT did not — see errors above." >&2
  exit "$PROC_RC"
fi
if [ "$OFFSITE_RC" -ne 0 ]; then
  echo "[$(date +%F\ %T)] ✖ Both databases were backed up, but the OFF-BOX copy failed." >&2
  exit "$OFFSITE_RC"
fi

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
