#!/usr/bin/env bash
#
# One isolated git worktree per Claude Code session.
#
# Several sessions run against this checkout at once. In a shared tree a blanket `git add` stages
# whatever every other session happens to have in flight — that has now happened twice, most
# recently in 27eca4d, which swallowed a whole i18n pass into an unrelated tender commit and pushed
# it. A worktree gives each session its own working directory and its own branch, so `git add -A`
# can only ever stage that session's work.
#
#   tools/worktree.sh new <name> [base-ref]   create a worktree and print the path to enter
#   tools/worktree.sh list                    show every worktree and what it is on
#   tools/worktree.sh rm <name>               remove the worktree (refuses if work would be lost)
#
# Worktrees live OUTSIDE the OneDrive folder (default ~/humiley-worktrees, override with
# TK_WORKTREE_ROOT). Two reasons: OneDrive syncs every build artifact and .pyc it sees, and macOS
# can revoke directory-listing permission on the synced folder, which breaks git and pytest inside
# it while leaving plain file reads working — a failure that looks like a corrupt repo and is not.
# Not /private/tmp either: macOS deletes files there that go untouched for a few days, and a
# worktree holds uncommitted work.

set -euo pipefail

# Print the header comment block (everything after the shebang up to the first non-comment line).
usage() { awk 'NR>1{ if (/^#/) { sub(/^# ?/,""); print } else exit }' "$0"; exit "${1:-1}"; }

command -v git >/dev/null || { echo "git not found on PATH" >&2; exit 1; }
git rev-parse --git-dir >/dev/null 2>&1 || { echo "not inside a git repository" >&2; exit 1; }

# The main checkout, resolved from the shared .git dir, so this works from inside a worktree too.
COMMON_DIR=$(git rev-parse --path-format=absolute --git-common-dir)
MAIN_REPO=$(dirname "$COMMON_DIR")
ROOT=${TK_WORKTREE_ROOT:-$HOME/humiley-worktrees}

# Deterministic per-name port, so two worktrees do not both grab 8000 and so the same worktree keeps
# the same port across restarts. autoPort in launch.json still moves it if the port is taken.
port_for() { printf '%d' $(( 8100 + $(printf '%s' "$1" | cksum | cut -d' ' -f1) % 800 )); }

seed_launch_json() {   # $1 = worktree path, $2 = name
  local wt=$1 name=$2 port; port=$(port_for "$name")
  mkdir -p "$wt/.claude"
  # .claude/ is gitignored, so a fresh worktree has no preview config. Point it at the worktree's
  # OWN app.py — no scratchpad copy, so an edit to templates/index.html is live on next request
  # instead of needing a sync step.
  cat > "$wt/.claude/launch.json" <<JSON
{
  "version": "0.0.1",
  "configurations": [
    {
      "name": "tk-$name",
      "runtimeExecutable": "python3",
      "runtimeArgs": ["$wt/app.py"],
      "port": $port,
      "autoPort": true,
      "env": {
        "TK_DB_PATH": "$wt/timekeeping.db",
        "TK_PORT": "$port",
        "TK_BOOTSTRAP_ADMIN": "1",
        "TK_M365_CLIENT_ID": "",
        "TK_M365_TENANT_ID": "",
        "TK_SSO_SECRET": "dev-sso-secret-humiley-portal-2026-abcdef",
        "TK_AUDIT_PEPPER": "dev-audit-pepper-humiley-portal-2026-abcdef"
      }
    }
  ]
}
JSON
  echo "$port"
}

cmd_new() {
  local name=${1:-} base=${2:-}
  [ -n "$name" ] || usage 1
  case $name in *[!A-Za-z0-9._-]*) echo "name may use letters, digits, dot, underscore, dash" >&2; exit 1;; esac

  local wt="$ROOT/$name" branch="claude/$name"
  [ -e "$wt" ] && { echo "already exists: $wt" >&2; echo "  enter it, or: tools/worktree.sh rm $name" >&2; exit 1; }
  git -C "$MAIN_REPO" show-ref --verify --quiet "refs/heads/$branch" \
    && { echo "branch $branch already exists — pick another name" >&2; exit 1; }

  # Branch from the freshest shared base we can prove exists, so a new session does not inherit
  # another session's half-finished feature branch.
  if [ -z "$base" ]; then
    git -C "$MAIN_REPO" fetch --quiet origin 2>/dev/null || true
    for c in origin/main main; do
      git -C "$MAIN_REPO" rev-parse --verify --quiet "$c^{commit}" >/dev/null && { base=$c; break; }
    done
    base=${base:-HEAD}
  fi
  git -C "$MAIN_REPO" rev-parse --verify --quiet "$base^{commit}" >/dev/null \
    || { echo "base ref not found: $base" >&2; exit 1; }

  mkdir -p "$ROOT"
  git -C "$MAIN_REPO" worktree add -b "$branch" "$wt" "$base" >/dev/null
  local port; port=$(seed_launch_json "$wt" "$name")

  echo "worktree  $wt"
  echo "branch    $branch  (from $base @ $(git -C "$wt" rev-parse --short HEAD))"
  echo "preview   config 'tk-$name' on port $port — serves this worktree directly"
  echo
  echo "Enter it with the EnterWorktree tool:  { \"path\": \"$wt\" }"
}

cmd_list() {
  # Paths here contain spaces (the OneDrive checkout does), so take the rest of the line after the
  # keyword rather than a whitespace-split field.
  git -C "$MAIN_REPO" worktree list --porcelain | awk '
    /^worktree /   { p = substr($0, 10) }
    /^branch /     { b = substr($0, 8); sub("refs/heads/", "", b); printf "%s\n    %s\n", p, b }
    /^detached$/   { printf "%s\n    (detached)\n", p }'
}

cmd_rm() {
  local name=${1:-}; [ -n "$name" ] || usage 1
  local wt="$ROOT/$name" branch="claude/$name"
  [ -d "$wt" ] || { echo "no such worktree: $wt" >&2; exit 1; }
  # `git worktree remove` already refuses on uncommitted changes; commits that exist only on this
  # branch are the other way to lose work, so check that too before deleting the branch.
  local unmerged
  unmerged=$(git -C "$MAIN_REPO" log --oneline "origin/main..$branch" 2>/dev/null | wc -l | tr -d ' ')
  # `git worktree remove` refuses when the tree still holds work, which is right. But under `set -e`
  # this script would then die on git's bare "fatal: ... use --force to delete it", which says what
  # happened and nothing about what to do — and the move people reach for next is `rm -rf` on the
  # directory. That unregisters nothing and strands the branch, which is exactly how this tool came
  # to be reported as having a leftover-branch bug it does not have. Say what is in the way instead.
  if ! git -C "$MAIN_REPO" worktree remove "$wt" 2>/dev/null; then
    echo "$wt still has work in it — nothing was removed." >&2
    echo >&2
    git -C "$wt" status --short >&2 || true
    echo >&2
    echo "  keep it:     commit and push from $wt, then run this again" >&2
    echo "  discard it:  git -C \"$wt\" reset --hard && git -C \"$wt\" clean -fd" >&2
    echo "  force it:    git -C \"$MAIN_REPO\" worktree remove --force \"$wt\"" >&2
    echo "               (then delete the branch yourself: git branch -D $branch)" >&2
    echo >&2
    echo "Do not rm -rf the directory: git keeps the worktree registered and $branch is left behind." >&2
    exit 1
  fi
  if [ "$unmerged" != "0" ]; then
    # `origin/main..$branch` asks whether these COMMITS are ancestors of main. This repo squash-
    # merges, so a fully merged branch never satisfies that and its work is reported as unmerged —
    # the same "does it exist" / "did it ship" confusion that costs people an afternoon elsewhere.
    # Ask the question that actually matters instead: is every file this branch touched already
    # byte-identical on origin/main? If so the work landed, whatever the commit graph says. The
    # branch is still not auto-deleted — being wrong here loses work — but say which case it is.
    git -C "$MAIN_REPO" fetch -q origin main 2>/dev/null || true
    local base landed=no f
    base=$(git -C "$MAIN_REPO" merge-base origin/main "$branch" 2>/dev/null || true)
    if [ -n "$base" ]; then
      landed=yes
      # `</dev/null` on the inner git: without it, git reads the loop's remaining input and the
      # loop silently skips files — the classic way a check like this passes without looking.
      while IFS= read -r f; do
        [ -n "$f" ] || continue
        git -C "$MAIN_REPO" diff --quiet origin/main "$branch" -- "$f" </dev/null || { landed=no; break; }
      done <<EOF
$(git -C "$MAIN_REPO" diff --name-only "$base" "$branch")
EOF
    fi
    if [ "$landed" = yes ]; then
      echo "kept branch $branch — its $unmerged commit(s) are not ancestors of origin/main, but every"
      echo "  file it touched is already identical there. That is what a squash merge looks like."
      echo "  confirm:  git diff origin/main $branch   (expect no output)"
      echo "  delete:   git branch -D $branch"
    else
      echo "kept branch $branch — it has $unmerged commit(s) not on origin/main, and its files still"
      echo "  differ there, so this work has NOT landed. Push it before deleting anything."
      echo "  see it:   git log --oneline origin/main..$branch"
      echo "  delete when merged:  git branch -D $branch"
    fi
  else
    git -C "$MAIN_REPO" branch -D "$branch" >/dev/null 2>&1 || true
    echo "removed $wt and branch $branch"
  fi
}

case ${1:-} in
  new)  shift; cmd_new "$@" ;;
  list) cmd_list ;;
  rm)   shift; cmd_rm "$@" ;;
  -h|--help|"") usage 0 ;;
  *) echo "unknown command: $1" >&2; usage 1 ;;
esac
