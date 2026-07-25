#!/usr/bin/env bash
# Humiley — poll-based AUTO-DEPLOY.  Runs on the VPS from a systemd timer (or cron); when the
# GitHub repo(s) move, it runs the normal one-click deploy (./deploy.sh) exactly once.  It only
# makes OUTBOUND calls (git fetch/pull) — no inbound ports and no SSH — so it works behind the
# office's blocked port 22.  You just `git push` and the server updates itself.
#
#   Trigger:  git push origin main   ->  (within the poll interval)  ->  ./deploy.sh on the VPS
#   Install:  see docs/AUTO-DEPLOY.md  (one paste in the Vietnix console, once)
#   Watch:    tail -f /root/humiley-backups/autodeploy.log     (use `cat -v` / less — it holds raw
#             git+docker output, which can contain terminal-escape sequences from commit messages)
set -uo pipefail
cd "$(dirname "$0")"
export GIT_TERMINAL_PROMPT=0                    # never block a timer tick on a credential prompt

BRANCH="${DEPLOY_BRANCH:-main}"
STATE_DIR="${AUTODEPLOY_STATE:-/root/humiley-backups}"
LOG="$STATE_DIR/autodeploy.log"
MARK="$STATE_DIR/autodeploy-last"              # "portalHEAD:procHEAD" ACTUALLY built by the last success
FAIL="$STATE_DIR/autodeploy-fail"              # "TARGET COUNT LASTEPOCH" for the currently-failing target
ALERT="$STATE_DIR/autodeploy-ALERT"            # present => auto-deploy is stuck; monitoring can watch for it
PROC_DIR="humiley-procurement"
DEPLOY_TIMEOUT="${AUTODEPLOY_TIMEOUT:-1200}"   # kill a wedged deploy after 20 min so the lock frees
FETCH_TIMEOUT="${AUTODEPLOY_FETCH_TIMEOUT:-120}"
MAX_TRIES="${AUTODEPLOY_MAX_TRIES:-5}"         # stop hammering a broken commit after N tries (until next push)
mkdir -p "$STATE_DIR"
say(){ printf '%s  %s\n' "$(date '+%F %T')" "$*" >>"$LOG"; }

# Never let two ticks overlap a long docker build.  -n = do not wait, just skip this tick.
exec 9>"$STATE_DIR/autodeploy.lock"
if ! flock -n 9; then say "busy - a deploy is already running, skip"; exit 0; fi

# What GitHub has now for the Portal repo (bounded so a stalled TCP fetch can't wedge the tick).
if ! timeout "$FETCH_TIMEOUT" git fetch --quiet origin "$BRANCH" 2>>"$LOG"; then
  say "git fetch (portal) failed/timed out - skip"; exit 0; fi
REMOTE="$(git rev-parse "origin/$BRANCH" 2>/dev/null || true)"
if [ -z "$REMOTE" ]; then say "cannot resolve origin/$BRANCH - skip"; exit 0; fi

# Also watch the Procurement repo (deploy.sh -> update.sh pulls it too) so a procurement-only push
# still deploys.  Best-effort: if it can't be read, we simply don't trigger on it.
PROC_REMOTE=""
if [ -d "$PROC_DIR/.git" ]; then
  timeout "$FETCH_TIMEOUT" git -C "$PROC_DIR" fetch --quiet 2>>"$LOG" || true
  PROC_REMOTE="$(git -C "$PROC_DIR" rev-parse '@{u}' 2>/dev/null || true)"
fi
TARGET="$REMOTE:$PROC_REMOTE"

# Up to date?  (MARK holds the HEADs actually built last time, so a fresh proc clone or a
# fetch-vs-pull race does NOT cause a redundant rebuild next tick.)
LAST="$(cat "$MARK" 2>/dev/null || true)"
if [ "$TARGET" = "$LAST" ]; then exit 0; fi

# Back-off / give-up guard: a PERSISTENTLY broken commit (bad build, dirty tree that blocks
# git pull --ff-only, OOM) must not re-run a full deploy every 2 min forever.  Retry the SAME
# failing TARGET with exponential backoff, then stop until a NEW push arrives.
FT=""; FC=0; FE=0
if [ -f "$FAIL" ]; then read -r FT FC FE < "$FAIL" || true; fi
[ -z "${FC:-}" ] && FC=0; [ -z "${FE:-}" ] && FE=0
if [ "$TARGET" = "$FT" ]; then
  if [ "$FC" -ge "$MAX_TRIES" ]; then exit 0; fi          # gave up; a new push (below) resets it
  NOW="$(date +%s)"; WAIT=$(( 60 * (1 << FC) )); [ "$WAIT" -gt 3600 ] && WAIT=3600
  if [ $(( NOW - FE )) -lt "$WAIT" ]; then exit 0; fi      # still backing off — skip quietly
else
  FC=0                                                     # different (newer) target -> fresh start
fi

say "change detected (portal=$REMOTE proc=${PROC_REMOTE:-none}) - deploying (try $((FC+1))/$MAX_TRIES)"
if timeout "$DEPLOY_TIMEOUT" ./deploy.sh >>"$LOG" 2>&1; then
  # Record what we ACTUALLY built (post-pull/clone HEADs), not the pre-build remote refs.
  NEW="$(git rev-parse HEAD 2>/dev/null || echo "$REMOTE"):"
  [ -d "$PROC_DIR/.git" ] && NEW="$NEW$(git -C "$PROC_DIR" rev-parse HEAD 2>/dev/null || echo "$PROC_REMOTE")"
  printf '%s' "$NEW" > "$MARK"
  rm -f "$FAIL" "$ALERT"
  say "deploy OK  (built portal=$(git rev-parse --short HEAD 2>/dev/null || echo '?'))"
else
  rc=$?
  FC=$((FC + 1))
  printf '%s %s %s' "$TARGET" "$FC" "$(date +%s)" > "$FAIL"
  if [ "$rc" -eq 124 ]; then say "deploy TIMED OUT after ${DEPLOY_TIMEOUT}s (try $FC/$MAX_TRIES)"
  else say "deploy FAILED rc=$rc (try $FC/$MAX_TRIES) - see log above"; fi
  if [ "$FC" -ge "$MAX_TRIES" ]; then
    printf '%s  AUTO-DEPLOY STUCK on %s after %s tries — fix the build/tree on the VPS, then push again\n' \
      "$(date '+%F %T')" "$TARGET" "$FC" > "$ALERT"
    say "GIVING UP on $TARGET after $MAX_TRIES tries — wrote $ALERT; will retry only after a NEW push"
  fi
fi

# Keep the log bounded.
if tail -n 2000 "$LOG" > "$LOG.tmp" 2>/dev/null; then mv "$LOG.tmp" "$LOG"; else rm -f "$LOG.tmp"; fi
