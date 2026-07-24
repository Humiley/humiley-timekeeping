#!/usr/bin/env bash
# Humiley Portal — one-shot VPS installer (Ubuntu).
# Installs Docker, fetches the app, and starts it behind Caddy (automatic HTTPS).
# Safe to re-run (it just updates + restarts). Override defaults with env vars:
#   PORTAL_DOMAIN, TK_ADMIN_EMAIL, TK_ADMIN_NAME, REPO_URL
set -euo pipefail

DOMAIN="${PORTAL_DOMAIN:-portal.humiley.com}"
ADMIN_EMAIL="${TK_ADMIN_EMAIL:-tony.nguyen@humiley.com}"
ADMIN_NAME="${TK_ADMIN_NAME:-Tony Nguyen}"
REPO="${REPO_URL:-https://github.com/Humiley/humiley-timekeeping.git}"
export DEBIAN_FRONTEND=noninteractive

echo "==> [1/4] Base packages (git, curl)..."
apt-get update -y >/dev/null && apt-get install -y git curl >/dev/null

echo "==> [2/4] Docker..."
if ! command -v docker >/dev/null 2>&1; then curl -fsSL https://get.docker.com | sh; fi

echo "==> [3/4] Fetch + configure the app..."
mkdir -p /opt && cd /opt
if [ -d humiley-timekeeping/.git ]; then
  cd humiley-timekeeping && git pull
else
  git clone "$REPO" humiley-timekeeping && cd humiley-timekeeping
fi
# Write the 3 site-config vars WITHOUT clobbering the secrets update.sh generates into the SAME
# .env (TK_ESIGN_PEPPER, TK_SSO_SECRET, AUTH_SECRET, POSTGRES_PASSWORD). A `> .env` truncation
# here would wipe those — breaking e-sign PINs and locking Procurement out of its own database
# (the postgres volume keeps the old password). So set-or-update each key in place instead.
touch .env
set_cfg(){ if grep -q "^$1=" .env; then sed -i "s|^$1=.*|$1=$2|" .env; else printf '%s=%s\n' "$1" "$2" >> .env; fi; }
set_cfg PORTAL_DOMAIN  "$DOMAIN"
set_cfg TK_ADMIN_EMAIL "$ADMIN_EMAIL"
set_cfg TK_ADMIN_NAME  "$ADMIN_NAME"

echo "==> [4/4] Generating secrets, migrating, seeding reference data + starting (via update.sh)..."
# update.sh owns secret generation + Procurement clone/migrate/bootstrap + build + health checks.
bash update.sh --bootstrap

echo ""
echo "==================================================================="
echo " DONE. Running containers:"
docker compose ps
echo ""
echo " When DNS for ${DOMAIN} points to this server's IP, open:"
echo "   https://${DOMAIN}"
echo "==================================================================="
