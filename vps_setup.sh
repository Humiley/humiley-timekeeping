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
printf 'PORTAL_DOMAIN=%s\nTK_ADMIN_EMAIL=%s\nTK_ADMIN_NAME=%s\n' "$DOMAIN" "$ADMIN_EMAIL" "$ADMIN_NAME" > .env

echo "==> [4/4] Build + start (takes a few minutes the first time)..."
docker compose up -d --build

echo ""
echo "==================================================================="
echo " DONE. Running containers:"
docker compose ps
echo ""
echo " When DNS for ${DOMAIN} points to this server's IP, open:"
echo "   https://${DOMAIN}"
echo "==================================================================="
