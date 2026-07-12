#!/usr/bin/env bash
# Humiley — ONE-COMMAND deploy/update for the whole stack (Portal + Procurement + Postgres + Caddy).
# Backs up data → pulls both repos → generates any missing secrets ONCE → builds → migrates the
# Procurement DB → restarts everything. Your data volumes are never dropped.
#
# On the VPS:
#   cd /opt/humiley-timekeeping && ./update.sh              # normal update (everything)
#   ./update.sh --bootstrap                                 # FIRST run: also seed Procurement admin
#   ./update.sh --no-backup                                 # skip the portal DB snapshot
set -euo pipefail
cd "$(dirname "$0")"

DO_BOOTSTRAP=0; SKIP_BACKUP=0
for a in "$@"; do case "$a" in
  --bootstrap) DO_BOOTSTRAP=1 ;;
  --no-backup) SKIP_BACKUP=1 ;;
  *) echo "unknown flag: $a" >&2; exit 2 ;;
esac; done

APP="${TK_CONTAINER:-humiley_portal}"
BACKUP_DIR="${BACKUP_DIR:-/root/humiley-backups}"
PROC_DIR="humiley-procurement"
PROC_REPO="${PROC_REPO:-https://github.com/Humiley/humiley-procurement.git}"
DOMAIN="$(grep -E '^PORTAL_DOMAIN=' .env 2>/dev/null | cut -d= -f2- || true)"; DOMAIN="${DOMAIN:-portal.humiley.com}"
say(){ printf '\n\033[1;34m==>\033[0m %s\n' "$*"; }

# Ensure a secret exists in .env exactly once (generated, then reused forever).
gen_secret(){ # $1 = var name, $2 = human note
  touch .env
  if grep -qE "^$1=.." .env; then say "$1 already set — leaving it unchanged."; return; fi
  say "Generating $1 (first run)…"
  local v; v="$(openssl rand -hex 32 2>/dev/null || head -c 32 /dev/urandom | od -An -tx1 | tr -d ' \n')"
  sed -i.bak "/^$1=/d" .env && rm -f .env.bak
  printf '%s=%s\n' "$1" "$v" >> .env
  echo "    saved to .env — back up this file.${2:+ $2}"
}

# 1) Back up the portal SQLite DB (skip on first boot / --no-backup)
if [ "$SKIP_BACKUP" -eq 0 ] && docker ps --format '{{.Names}}' | grep -q "^$APP$"; then
  say "Backing up the portal database…"
  mkdir -p "$BACKUP_DIR"; OUT="$BACKUP_DIR/portal-$(date +%F-%H%M%S).db"
  if docker exec "$APP" python3 -c "import sqlite3,os;s=sqlite3.connect(os.environ.get('TK_DB_PATH','/data/timekeeping.db'));d=sqlite3.connect('/data/_backup.db');s.backup(d);d.close();s.close()"; then
    docker cp "$APP:/data/_backup.db" "$OUT"; docker exec "$APP" rm -f /data/_backup.db 2>/dev/null || true
    gzip -f "$OUT"; echo "    saved: $OUT.gz"
    ls -1t "$BACKUP_DIR"/portal-*.db.gz 2>/dev/null | tail -n +15 | xargs -r rm -f
  else echo "    WARNING: portal backup failed — aborting (use --no-backup to override)." >&2; exit 1; fi
fi

# 2) Latest code — this repo + the Procurement repo cloned INTO ./humiley-procurement
say "Pulling latest Portal code…"; git pull
if [ -d "$PROC_DIR/.git" ]; then say "Pulling latest Procurement code…"; git -C "$PROC_DIR" pull
else say "Cloning Procurement into ./$PROC_DIR…"; git clone "$PROC_REPO" "$PROC_DIR"; fi

# 3) Secrets — all generated ONCE into the single shared .env
gen_secret TK_ESIGN_PEPPER "Do NOT change it or enrolled e-sign PINs stop working."
gen_secret TK_SSO_SECRET   "Procurement reads this SAME value as PORTAL_SSO_SECRET."
gen_secret AUTH_SECRET     "Auth.js session secret for Procurement."
gen_secret POSTGRES_PASSWORD "Procurement database password."

# 4) Build everything
say "Building images (Portal + Procurement)…"; docker compose build

# 5) Bring up the Procurement database, then apply its migrations
say "Starting the Procurement database…"; docker compose up -d procdb
say "Applying Procurement migrations…"; docker compose --profile setup run --rm proc-migrate
# proc-bootstrap is fully idempotent — the approval matrix is left untouched if present, the HS
# 2022 codes + C/O forms + FX reference data are upserted (so the HS Code Explorer is never empty
# or stale), and the admin is created only on first run. Safe to run every update.
say "Seeding Procurement reference data (+ admin on first run)…"; docker compose --profile setup run --rm proc-bootstrap

# 6) Start / restart the whole stack (data volumes persist)
say "Starting the whole stack…"; docker compose up -d --build

# 7) Health checks
say "Containers:"; docker compose ps
sleep 3
say "Checking https://$DOMAIN …"
P="$(curl -s -o /dev/null -w '%{http_code}' "https://$DOMAIN" || echo 000)"
Q="$(curl -s -o /dev/null -w '%{http_code}' "https://$DOMAIN/procurement/login" || echo 000)"
[ "$P" = "200" ] && printf '\033[1;32m    Portal OK (HTTP %s)\033[0m\n' "$P" || printf '\033[1;33m    Portal HTTP %s — docker compose logs --tail=50 app\033[0m\n' "$P"
[ "$Q" = "200" ] && printf '\033[1;32m    Procurement OK (HTTP %s at /procurement)\033[0m\n' "$Q" || printf '\033[1;33m    Procurement HTTP %s — docker compose logs --tail=50 procurement\033[0m\n' "$Q"
say "Done. One stack: Portal + Procurement + DB + Caddy."
