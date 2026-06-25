#!/usr/bin/env bash
# Humiley Portal — one-command SAFE update for the Vietnix VPS.
# Does: back up the database → pull latest code → rebuild → health-check.
# Your data (the humiley_data volume) is NEVER touched by the rebuild.
#
# Usage on the server:
#   cd /opt/humiley-timekeeping && ./update.sh
#   ./update.sh --no-backup        # skip the DB snapshot (not recommended)
set -euo pipefail
cd "$(dirname "$0")"

APP="${TK_CONTAINER:-humiley_portal}"
BACKUP_DIR="${BACKUP_DIR:-/root/humiley-backups}"
DOMAIN="$(grep -E '^PORTAL_DOMAIN=' .env 2>/dev/null | cut -d= -f2- || true)"
DOMAIN="${DOMAIN:-portal.humiley.com}"
SKIP_BACKUP=0
[ "${1:-}" = "--no-backup" ] && SKIP_BACKUP=1

say(){ printf '\n\033[1;34m==>\033[0m %s\n' "$*"; }

# 1) Back up the live DB (consistent online snapshot) unless skipped
if [ "$SKIP_BACKUP" -eq 0 ]; then
  say "Backing up the database…"
  mkdir -p "$BACKUP_DIR"
  OUT="$BACKUP_DIR/portal-$(date +%F-%H%M%S).db"
  if docker exec "$APP" python3 -c "import sqlite3,os; s=sqlite3.connect(os.environ.get('TK_DB_PATH','/data/timekeeping.db')); d=sqlite3.connect('/data/_backup.db'); s.backup(d); d.close(); s.close()"; then
    docker cp "$APP:/data/_backup.db" "$OUT"
    docker exec "$APP" rm -f /data/_backup.db 2>/dev/null || true
    gzip -f "$OUT"
    echo "    saved: $OUT.gz"
    # keep only the 14 newest snapshots
    ls -1t "$BACKUP_DIR"/portal-*.db.gz 2>/dev/null | tail -n +15 | xargs -r rm -f
  else
    echo "    WARNING: backup failed (is the '$APP' container running?). Aborting." >&2
    echo "    If you really want to update without a backup, run: ./update.sh --no-backup" >&2
    exit 1
  fi
else
  say "Skipping backup (--no-backup)."
fi

# 2) Pull the latest code from GitHub main
say "Pulling latest code…"
git pull

# 3) Rebuild + restart — the humiley_data volume (your DB) is left untouched
say "Rebuilding and restarting…"
docker compose up -d --build

# 4) Health check
say "Containers:"
docker compose ps
say "Checking https://$DOMAIN …"
sleep 3
CODE="$(curl -s -o /dev/null -w '%{http_code}' "https://$DOMAIN" || echo 000)"
if [ "$CODE" = "200" ]; then
  printf '\033[1;32m    OK — HTTP %s. Update complete. Now hard-refresh your browser (Cmd/Ctrl+Shift+R).\033[0m\n' "$CODE"
else
  printf '\033[1;33m    Got HTTP %s — check logs:  docker compose logs --tail=50 app\033[0m\n' "$CODE"
fi
