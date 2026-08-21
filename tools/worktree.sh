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
  #
  # Count against local AND its remote, taking the larger. Counting only the local ref would let a
  # stale local (behind a remote that still carries unlanded commits) read as 0 and auto-delete the
  # branch — the same staleness that made the verdict below wrong, but here it deletes rather than
  # merely misreports.
  # `set -o pipefail` is on: a git that fails inside $( ... | wc -l ) fails the whole substitution
  # and `set -e` then kills the script mid-run, printing nothing. An unpushed branch has no
  # origin/<branch> to ask about, so that is the ordinary case, not an edge one. Check the ref
  # exists first, and use `if` rather than `test && assign` — a false test is the last command in
  # the chain, so `&&` would exit the script too.
  local unmerged=0 unmerged_remote=0
  git -C "$MAIN_REPO" fetch -q origin 2>/dev/null || true
  if git -C "$MAIN_REPO" rev-parse --verify --quiet "$branch" >/dev/null 2>&1; then
    unmerged=$(git -C "$MAIN_REPO" log --oneline "origin/main..$branch" 2>/dev/null | wc -l | tr -d ' ' || true)
  fi
  if git -C "$MAIN_REPO" rev-parse --verify --quiet "origin/$branch" >/dev/null 2>&1; then
    unmerged_remote=$(git -C "$MAIN_REPO" log --oneline "origin/main..origin/$branch" 2>/dev/null | wc -l | tr -d ' ' || true)
  fi
  if [ "${unmerged_remote:-0}" -gt "${unmerged:-0}" ]; then unmerged=$unmerged_remote; fi
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
    #
    # Answering it by comparing FILES against main was wrong twice over, and said "this work has
    # NOT landed" about work that had:
    #   1. it judged the LOCAL ref, which goes stale the moment the branch moves anywhere else —
    #      `gh pr update-branch`, or a push from another machine, updates the remote and never
    #      touches your local ref;
    #   2. even on the right ref, "is this file byte-identical to main?" is not the question. If
    #      another PR also touched that file, it never will be, however completely this branch's
    #      own change landed.
    #
    # The question that survives both: would merging this branch into main change main at all? If
    # the merge is a no-op, everything the branch carries is already there — whatever the commit
    # graph looks like and whoever else edited the same files. The branch is still never
    # auto-deleted here; being wrong loses work. Say which case it is and let a human act.
    git -C "$MAIN_REPO" fetch -q origin 2>/dev/null || true

    # Pick the ref that actually holds the work. Behind its remote -> the remote is the truth.
    # Diverged -> do not guess; each side has commits the other lacks.
    local tip="$branch" remote="origin/$branch" stale=""
    if git -C "$MAIN_REPO" rev-parse --verify --quiet "$remote" >/dev/null 2>&1; then
      if git -C "$MAIN_REPO" merge-base --is-ancestor "$branch" "$remote" 2>/dev/null; then
        [ "$(git -C "$MAIN_REPO" rev-parse "$branch")" = "$(git -C "$MAIN_REPO" rev-parse "$remote")" ] \
          || stale=yes
        tip="$remote"
      elif ! git -C "$MAIN_REPO" merge-base --is-ancestor "$remote" "$branch" 2>/dev/null; then
        tip=""
      fi
    fi

    # TWO DIFFERENT QUESTIONS, and they had been answered as one:
    #
    #   would merging this change main?   -> is it safe to MERGE
    #   did this branch's work land?      -> is it safe to DELETE
    #
    # A branch can be unsafe to merge and safe to delete at the same time, and here that is the
    # NORMAL case rather than an edge one. Every deployable PR bumps static/sw.js, so the moment
    # one more PR lands, a merged branch's sw.js conflicts with main's and the merge stops being a
    # no-op. The branch is stale, not unlanded — but the merge test cannot tell those apart and
    # said "this work has not landed. Push it before deleting anything" about work that shipped
    # hours earlier. Reproduced on claude/services-costing, merged as #68.
    #
    # No content test settles it either, and each fails differently: patch-id cannot match a squash
    # merge, a tree comparison cannot see past staleness, and reverse-applying the branch's own
    # diff fails as soon as somebody edits the same lines afterwards (which #71 did to #68's).
    #
    # So ask the forge, which simply knows. A squash merge is recorded against the branch name, and
    # that record is not affected by anything that happens to main afterwards. `gh` is already this
    # repo's tool of record for PRs; with no network the answer is unknown, and unknown falls back
    # to keeping the branch, which is the safe direction to be wrong in.
    local landed=no merged_tree main_tree merge_conflicts="" MERGED_PR="" AFTER_MERGE=0 REUSED_PR="" PR_HEAD=""
    if [ -z "$tip" ]; then
      landed=diverged
    elif git -C "$MAIN_REPO" merge-base --is-ancestor "$tip" origin/main 2>/dev/null; then
      landed=yes
    else
      # git >= 2.38. On anything older this yields nothing and we fall through, which is safe.
      # NOTE: on a CONFLICT merge-tree still writes a tree — one full of conflict markers — and
      # exits non-zero. `|| true` used to swallow that, so a conflict was reported as "would change
      # main" with no hint that the two sides disagree rather than that work is missing.
      if merged_tree=$(git -C "$MAIN_REPO" merge-tree --write-tree origin/main "$tip" 2>/dev/null); then
        main_tree=$(git -C "$MAIN_REPO" rev-parse 'origin/main^{tree}' 2>/dev/null || true)
        [ -n "$merged_tree" ] && [ "$merged_tree" = "$main_tree" ] && landed=yes
      else
        merge_conflicts=yes
      fi
      if [ "$landed" != yes ] && command -v gh >/dev/null 2>&1; then
        local merged_pr pr_head
        merged_pr=$(gh pr list --state merged --head "$branch" --json number,headRefOid \
                      --jq '.[0] | "\(.number) \(.headRefOid)"' --limit 1 2>/dev/null || true)
        pr_head=${merged_pr#* }; merged_pr=${merged_pr%% *}
        # The lookup answers about a NAME, and the name is the one thing here that gets reused —
        # worktree names are short and descriptive. Reuse one whose old PR merged and the forge
        # cheerfully returns that old PR for entirely new work: "its work LANDED, delete it", for a
        # commit that exists nowhere else. That is the losing-work direction, the one direction
        # this tool is not allowed to be wrong in.
        #
        # So do not believe the number until the COMMIT agrees. The PR records the head it merged,
        # and GitHub keeps that after the remote branch is deleted — which is exactly when the hole
        # would otherwise open, because a live remote makes the divergence check fire first and
        # masks it. Ancestry rather than equality, because a branch can legitimately collect
        # commits after its merge (an sw.js bump pushed to an already-merged branch did just that);
        # those are worth naming, not worth calling the whole branch unlanded.
        if [ -n "$merged_pr" ] && [ "$merged_pr" != "null" ] && [ -n "$pr_head" ]; then
          if ! git -C "$MAIN_REPO" cat-file -e "$pr_head^{commit}" 2>/dev/null; then
            :   # cannot see the commit that PR merged — unverifiable, so keep the branch
          elif git -C "$MAIN_REPO" merge-base --is-ancestor "$pr_head" "$tip" 2>/dev/null; then
            landed=stale
            MERGED_PR="$merged_pr"
            AFTER_MERGE=$(git -C "$MAIN_REPO" rev-list --count "$pr_head..$tip" 2>/dev/null || echo 0)
            PR_HEAD="$pr_head"
          else
            REUSED_PR="$merged_pr"   # same name, different lineage
          fi
        fi
      fi
    fi

    if [ "$landed" = yes ]; then
      echo "kept branch $branch — its $unmerged commit(s) are not ancestors of origin/main, but"
      echo "  merging it into main would change nothing, so the work is already there."
      [ -n "$stale" ] && echo "  (judged $remote — your local $branch is behind it)"
      echo "  confirm:  git merge-tree --write-tree origin/main $tip   == $(git -C "$MAIN_REPO" rev-parse --short 'origin/main^{tree}' 2>/dev/null)"
      echo "  delete:   git branch -D $branch"
    elif [ "$landed" = diverged ]; then
      echo "kept branch $branch — it and $remote have DIVERGED: each has commits the other does not."
      echo "  Nothing here can tell which side you meant to keep, so nothing was deleted."
      echo "  yours only:  git log --oneline $remote..$branch"
      echo "  theirs only: git log --oneline $branch..$remote"
    elif [ "$landed" = stale ]; then
      echo "kept branch $branch — its work LANDED (merged as #$MERGED_PR), but the branch is stale:"
      echo "  merging it now WOULD change main, so do not merge it — delete it."
      if [ "${AFTER_MERGE:-0}" != "0" ]; then
        echo "  BUT $AFTER_MERGE commit(s) sit after the merge point and are on no PR — read them first:"
        echo "    git log --oneline $(git -C "$MAIN_REPO" rev-parse --short "$PR_HEAD" 2>/dev/null)..$tip"
      fi
      [ -n "$merge_conflicts" ] && echo "  (it also conflicts with main, which is what staleness looks like)"
      [ -n "$stale" ] && echo "  (judged $remote — your local $branch is behind it)"
      echo "  confirm:  gh pr view $MERGED_PR"
      echo "  delete:   git branch -D $branch"
    else
      if [ -n "$REUSED_PR" ]; then
        echo "kept branch $branch — a merged PR (#$REUSED_PR) has this NAME, but it merged a"
        echo "  different commit, so this branch is new work under a reused name. Not landed."
      else
        echo "kept branch $branch — no merged PR for it, and merging it into main WOULD change main,"
        echo "  so this work has not landed. Push it and get it merged before deleting anything."
      fi
      [ -n "$merge_conflicts" ] && echo "  (it conflicts with main — rebase before opening a PR)"
      command -v gh >/dev/null 2>&1 \
        || echo "  (gh is not installed, so whether a PR merged could not be checked)"
      echo "  see it:   git log --oneline origin/main..$tip"
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
