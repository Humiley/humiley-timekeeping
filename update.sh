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

DO_BOOTSTRAP=0; SKIP_BACKUP=0; PORTAL_ONLY=0
for a in "$@"; do case "$a" in
  --bootstrap) DO_BOOTSTRAP=1 ;;
  --no-backup) SKIP_BACKUP=1 ;;
  # Only portal files changed (app.py / templates / static / …). Skip the entire Procurement half:
  # its repo pull, its image build, its migrations and its reference-data seed. Those cost MINUTES
  # on every deploy and cannot possibly be affected by a change to the portal's HTML. autodeploy.sh
  # passes this automatically when the commit range touches nothing outside the portal.
  --portal-only) PORTAL_ONLY=1 ;;
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
    gzip -f "$OUT"
    # Encrypt at rest when a key exists — these pre-deploy snapshots hold the same payroll/PII/GPS as
    # the nightly ones and land in the same directory (which gets copied off-box). Unlike backup.sh this
    # does NOT fail closed: a deploy must never be blocked by a missing backup key (you may be shipping
    # an urgent fix), so it warns loudly and keeps going.
    KEYFILE="${BACKUP_KEYFILE:-$BACKUP_DIR/.backup-key}"
    if [ -f "$KEYFILE" ]; then
      openssl enc -aes-256-cbc -pbkdf2 -iter 200000 -salt -in "$OUT.gz" -out "$OUT.gz.enc" -pass "file:$KEYFILE" \
        && rm -f "$OUT.gz" && echo "    saved (encrypted): $OUT.gz.enc"
    else
      echo "    saved: $OUT.gz"
      echo "    ⚠️  UNENCRYPTED — no key at $KEYFILE. Create one so snapshots aren't plaintext HR/finance data:" >&2
      echo "        openssl rand -base64 48 > $KEYFILE && chmod 600 $KEYFILE" >&2
    fi
    # Keep the 14 newest snapshots. `|| true` is REQUIRED: an unmatched glob is passed to ls literally,
    # ls then exits 1, and under `set -euo pipefail` that would abort the whole deploy. That is exactly
    # what happened once the .enc glob was added while no key (and so no .enc file) existed yet.
    ls -1t "$BACKUP_DIR"/portal-*.db.gz "$BACKUP_DIR"/portal-*.db.gz.enc 2>/dev/null | tail -n +15 | xargs -r rm -f || true
  else echo "    WARNING: portal backup failed — aborting (use --no-backup to override)." >&2; exit 1; fi
fi

# 2) Latest code — this repo + the Procurement repo cloned INTO ./humiley-procurement
say "Pulling latest Portal code…"; git pull
if [ "$PORTAL_ONLY" -eq 1 ]; then say "Portal-only update — leaving Procurement untouched."
elif [ -d "$PROC_DIR/.git" ]; then say "Pulling latest Procurement code…"; git -C "$PROC_DIR" pull
else say "Cloning Procurement into ./$PROC_DIR…"; git clone "$PROC_REPO" "$PROC_DIR"; fi

# 3) Secrets — all generated ONCE into the single shared .env
gen_secret TK_ESIGN_PEPPER "Do NOT change it or enrolled e-sign PINs stop working."
gen_secret TK_SSO_SECRET   "Procurement reads this SAME value as PORTAL_SSO_SECRET."
gen_secret AUTH_SECRET     "Auth.js session secret for Procurement."
gen_secret ESIGN_SIGNING_SECRET "Procurement e-signature chain HMAC key. Do NOT change it or existing signatures fail verification."
gen_secret POSTGRES_PASSWORD "Procurement database password."

# 4) Build everything
if [ "$PORTAL_ONLY" -eq 1 ]; then
  say "Building the Portal image…"; docker compose build app
else
  say "Building images (Portal + Procurement)…"; docker compose build
fi

# 5) Bring up the Procurement database, then apply its migrations
if [ "$PORTAL_ONLY" -eq 0 ]; then
say "Starting the Procurement database…"; docker compose up -d procdb
say "Applying Procurement migrations…"; docker compose --profile setup run --rm proc-migrate
# proc-bootstrap is fully idempotent — the approval matrix is left untouched if present, the HS
# 2022 codes + C/O forms + FX reference data are upserted (so the HS Code Explorer is never empty
# or stale), and the admin is created only on first run. Safe to run every update.
# The first Procurement ADMIN defaults to the Portal admin (same person signs in via SSO), so a
# FRESH install is never left with no admin. bootstrap.ts leaves an existing admin untouched.
export BOOTSTRAP_ADMIN_EMAIL="${BOOTSTRAP_ADMIN_EMAIL:-$(grep -E '^TK_ADMIN_EMAIL=' .env 2>/dev/null | cut -d= -f2- || true)}"
export BOOTSTRAP_ADMIN_EMAIL="${BOOTSTRAP_ADMIN_EMAIL:-tony.nguyen@humiley.com}"
export BOOTSTRAP_ADMIN_NAME="${BOOTSTRAP_ADMIN_NAME:-$(grep -E '^TK_ADMIN_NAME=' .env 2>/dev/null | cut -d= -f2- || true)}"
export BOOTSTRAP_ADMIN_NAME="${BOOTSTRAP_ADMIN_NAME:-Tony Nguyen}"
say "Seeding Procurement reference data (+ admin ${BOOTSTRAP_ADMIN_EMAIL} on first run)…"; docker compose --profile setup run --rm proc-bootstrap
fi

# 5.5) VALIDATE THE EDGE CONFIG BEFORE TOUCHING THE EDGE.
#
# Caddy is a single process serving portal.humiley.com AND /procurement, and its config is a
# bind-mounted file plus everything imported from caddy.d/. A config Caddy cannot load makes the
# container exit; `restart: unless-stopped` then loops it, 80/443 never bind, and the whole company
# is offline. Nothing below used to check for that: `up -d --build` does not fail when a container
# starts and immediately dies, and the reload step's old fallback was `|| docker compose restart
# caddy || true` — which threw away a WORKING config in favour of one that had just been refused,
# and then swallowed the exit code so auto-deploy recorded "deploy OK" over a dead site.
#
# caddy.d/staging.caddy is hand-edited on the server and gitignored, so CI can never see it. This is
# the only place it can be checked. Validate with the RUNNING container's own binary where possible
# — that is the exact version that will parse it — and fall back to the image only on first boot.
say "Validating the Caddy config…"
if docker compose ps --status running caddy 2>/dev/null | grep -q caddy; then
  _cv() { docker compose exec -T caddy caddy validate --config /etc/caddy/Caddyfile --adapter caddyfile; }
else
  _cv() { docker run --rm -e PORTAL_DOMAIN="$DOMAIN" \
            -v "$PWD/Caddyfile:/etc/caddy/Caddyfile:ro" -v "$PWD/caddy.d:/etc/caddy/conf.d:ro" \
            caddy:2 caddy validate --config /etc/caddy/Caddyfile --adapter caddyfile; }
fi
if ! _cv; then
  printf '\033[1;31m\n  Caddy config is INVALID — refusing to restart the edge.\033[0m\n' >&2
  printf '  The site is still up on the old config. Nothing has been changed.\n' >&2
  printf '  Almost always a hand-edited caddy.d/*.caddy file. To get back to a known-good edge:\n' >&2
  printf '      mv caddy.d/staging.caddy /tmp/  &&  ./update.sh\n' >&2
  exit 1
fi

# 6) Start / restart the whole stack (data volumes persist)
if [ "$PORTAL_ONLY" -eq 1 ]; then
  # No --build: step 4 already built it. The old `up -d --build` here meant EVERY deploy built the
  # images twice over.
  say "Restarting the Portal…"; docker compose up -d --no-deps app
else
  say "Starting the whole stack…"; docker compose up -d --build
fi

# The Caddyfile is bind-mounted, so `compose up` does NOT reload it (compose only sees image/config
# changes). Gracefully reload Caddy so edits (gzip/zstd compression, framing headers) take effect on
# an update — otherwise they stay dormant until the next full Caddy restart.
#
# There is deliberately NO restart fallback. Caddy rolls the old config back into place if a reload
# fails, so a refused reload leaves the site UP on the last known-good config — which is the safe
# state and exactly what you want to preserve. Restarting at that moment discards the good config
# and re-reads the bad one; Caddy's own docs say a failed startup should not be automatically
# retried. The error is no longer swallowed either: it is reported, and the deploy is marked failed
# so auto-deploy raises its alert instead of logging "deploy OK".
say "Reloading Caddy config…"
if ! docker compose exec -T caddy caddy reload --config /etc/caddy/Caddyfile --adapter caddyfile; then
  printf '\033[1;31m    Caddy REFUSED the reload — it is still serving the previous config.\033[0m\n' >&2
  printf '    The site is up. Fix the config, then re-run ./update.sh.\n' >&2
  CADDY_RELOAD_FAILED=1
fi

# 7) Health checks
say "Containers:"; docker compose ps
sleep 3
say "Checking https://$DOMAIN …"
P="$(curl -s -o /dev/null -w '%{http_code}' "https://$DOMAIN" || echo 000)"
Q="$(curl -s -o /dev/null -w '%{http_code}' "https://$DOMAIN/procurement/login" || echo 000)"
[ "$P" = "200" ] && printf '\033[1;32m    Portal OK (HTTP %s)\033[0m\n' "$P" || printf '\033[1;33m    Portal HTTP %s — docker compose logs --tail=50 app\033[0m\n' "$P"
[ "$Q" = "200" ] && printf '\033[1;32m    Procurement OK (HTTP %s at /procurement)\033[0m\n' "$Q" || printf '\033[1;33m    Procurement HTTP %s — docker compose logs --tail=50 procurement\033[0m\n' "$Q"
say "Done. One stack: Portal + Procurement + DB + Caddy."

# A refused reload means the edge is running something OLDER than what is checked out. That is safe,
# but it is not success — exit non-zero so autodeploy.sh counts the failure and raises its alert
# rather than clearing it.
if [ "${CADDY_RELOAD_FAILED:-0}" = "1" ]; then
  printf '\033[1;31mDeploy incomplete: Caddy is serving an older config than this checkout.\033[0m\n' >&2
  exit 1
fi
