#!/usr/bin/env bash
# ─────────────────────────────────────────────────────────────────────────────
#  One-click update + deploy for the Humiley stack on the Vietnix VPS.
#
#  In the Vietnix browser console (Open Xterm.js Console), paste ONE line:
#
#       /opt/humiley-timekeeping/deploy.sh
#
#  It pulls the latest code FIRST (so any change to update.sh itself takes effect
#  this run — e.g. the Caddy reload), then rebuilds + migrates + seeds the whole
#  stack (portal + procurement + Postgres + Caddy) via update.sh --bootstrap.
#  --bootstrap is idempotent, so it is always safe to use.
# ─────────────────────────────────────────────────────────────────────────────
set -uo pipefail
REPO="/opt/humiley-timekeeping"

cd "$REPO" 2>/dev/null || { echo "✗ Repo not found at $REPO"; exit 1; }

echo "▶ [1/2] Pulling the latest code…"
if ! git pull --ff-only; then
  echo "✗ git pull failed. The VPS repo has local changes or has diverged."
  echo "  Inspect with:  git -C $REPO status   (then 'git stash' or resolve), and re-run."
  exit 1
fi
chmod +x update.sh vps_setup.sh 2>/dev/null || true

echo "▶ [2/2] Building + migrating + seeding + reloading Caddy…"
exec ./update.sh --bootstrap "$@"
