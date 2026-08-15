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
    echo "    ┌─────────────────────────────────────────────────────────────────────────┐"
    echo "    │  Staging is running HERE on the server, on 127.0.0.1:$PORT.               │"
    echo "    │                                                                         │"
    echo "    │  To see it, open Terminal ON YOUR OWN COMPUTER — not this window —       │"
    echo "    │  and run:                                                               │"
    echo "    │                                                                         │"
    echo "    │      ssh -L $PORT:127.0.0.1:$PORT root@portal.humiley.com                │"
    echo "    │                                                                         │"
    echo "    │  Leave it open, then browse to  http://127.0.0.1:$PORT                   │"
    echo "    │                                                                         │"
    echo "    │  (Running that command in THIS window just logs the server into itself   │"
    echo "    │   and fails with \"Address already in use\" — staging already has the port.)│"
    echo "    └─────────────────────────────────────────────────────────────────────────┘"
    exit 0
  fi
  sleep 1
done
echo "Staging did not become healthy in 30s — check: docker compose -p $PROJ -f $FILE logs --tail 50" >&2
exit 1
