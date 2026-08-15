#!/usr/bin/env bash
# Humiley — build STAGING from any branch, on a COPY of the live database.
#
#   ./staging.sh                       # staging from the current checkout
#   ./staging.sh fix/some-branch       # staging from a branch (fetched into a temp worktree)
#   ./staging.sh --fresh               # rebuild the staging DB from production again
#   ./staging.sh --down                # stop staging (its data volume is kept)
#
# SAFETY, which is the whole point of this file:
#   · Production's volume is only ever mounted READ-ONLY (:ro). This script cannot write to it,
#     cannot migrate it and cannot delete it — the copy runs one way, prod -> staging, always.
#   · Staging runs under its own compose project (humiley_staging), so its containers, network and
#     volume are namespaced away from production's.
#   · Staging's outbound integrations are blank in docker-compose.staging.yml: no mail, no webhook.
#     A staging copy holds real people's records; it must never be able to email them.
#   · Nothing here touches the live containers. `docker compose -p humiley_staging` only ever
#     addresses the staging project.
set -euo pipefail
cd "$(dirname "$0")"

PROJ=humiley_staging
FILE=docker-compose.staging.yml
PROD_VOL=${PROD_VOL:-humiley-timekeeping_humiley_data}     # production's SQLite volume
STAGE_VOL=${PROJ}_humiley_data
PORT=8100
say(){ printf '\n\033[1;36m==>\033[0m %s\n' "$*"; }

case "${1:-}" in
  --down)
    say "Stopping staging (data volume kept — use 'docker volume rm $STAGE_VOL' to discard it)"
    docker compose -p "$PROJ" -f "$FILE" down
    exit 0 ;;
esac

FRESH=0; BRANCH=""
for a in "$@"; do
  case "$a" in
    --fresh) FRESH=1 ;;
    -*) echo "unknown flag: $a" >&2; exit 2 ;;
    *) BRANCH="$a" ;;
  esac
done

# ── the code under test ──────────────────────────────────────────────────────────────────────────
if [ -n "$BRANCH" ]; then
  say "Fetching $BRANCH"
  git fetch --quiet origin "$BRANCH"
  WT=".staging-worktree"
  git worktree remove --force "$WT" 2>/dev/null || true
  git worktree add --quiet --detach "$WT" "origin/$BRANCH"
  BUILD_DIR="$WT"
else
  BUILD_DIR="."
  say "Building staging from the current checkout ($(git rev-parse --short HEAD))"
fi

# ── the data: a COPY, taken read-only ────────────────────────────────────────────────────────────
if ! docker volume inspect "$STAGE_VOL" >/dev/null 2>&1 || [ "$FRESH" = "1" ]; then
  if ! docker volume inspect "$PROD_VOL" >/dev/null 2>&1; then
    echo "Production volume '$PROD_VOL' not found. Set PROD_VOL=… (docker volume ls) and retry." >&2
    exit 1
  fi
  say "Copying the live database into staging (production mounted READ-ONLY)"
  docker volume create "$STAGE_VOL" >/dev/null
  # -ro on the source is the guarantee: even a wrong command inside this container cannot alter
  # production. The WAL and shm files come too — copying only the .db can lose committed rows that
  # are still in the write-ahead log.
  docker run --rm \
    -v "$PROD_VOL":/from:ro \
    -v "$STAGE_VOL":/to \
    alpine:3 sh -c 'rm -rf /to/* 2>/dev/null; cp -a /from/. /to/ && ls -la /to'
  say "Copied. Staging now holds a snapshot of production as of $(date '+%F %T')."
  echo "    ⚠️  It contains REAL salary, bank and personal data. Treat it like production:"
  echo "        do not expose the port publicly, and delete the volume when you are done."
fi

# ── run ──────────────────────────────────────────────────────────────────────────────────────────
# Staging joins production's network so the existing Caddy can serve it on a subdomain. Joining a
# network is not sharing data — the volumes stay separate, and Caddy only routes to staging if a
# file in caddy.d/ says so. Compose's own error for a missing external network names no remedy, so
# check it here.
if ! docker network inspect humiley_net >/dev/null 2>&1; then
  echo "Network 'humiley_net' not found — production does not appear to be up." >&2
  echo "Start it first (./update.sh, or docker compose up -d), then re-run this." >&2
  exit 1
fi

say "Building and starting staging"
( cd "$BUILD_DIR" && docker compose -p "$PROJ" -f "$OLDPWD/$FILE" up -d --build )

say "Waiting for it to answer"
for i in $(seq 1 30); do
  if curl -fsS "http://127.0.0.1:$PORT/api/health" >/dev/null 2>&1; then
    echo "    healthy after ${i}s"
    echo
    echo "    Staging build: $(curl -fsS http://127.0.0.1:$PORT/api/build 2>/dev/null || echo '?')"
    echo "    Production   : $(curl -fsS https://portal.humiley.com/api/build 2>/dev/null || echo '?')"
    echo
    if [ -f caddy.d/staging.caddy ]; then
      echo "    caddy.d/staging.caddy exists — staging is published over HTTPS."
      echo "    Browse the domain named in that file. If you just edited it:"
      echo "        docker exec humiley_caddy caddy reload --config /etc/caddy/Caddyfile"
    else
      echo "    It is running, but only this server can reach it (127.0.0.1:$PORT)."
      echo "    From HERE you can check it:  curl -s http://127.0.0.1:$PORT/api/health"
      echo
      echo "    To open it in a BROWSER, publish it through Caddy — see docs/STAGING.md."
      echo "    (An SSH tunnel also works, but only on a network that allows outbound port 22,"
      echo "     and it must be run on your own computer, never in this console.)"
    fi
    exit 0
  fi
  sleep 1
done
echo "Staging did not become healthy in 30s — check: docker compose -p $PROJ -f $FILE logs --tail 50" >&2
exit 1
