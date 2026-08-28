#!/bin/bash
#
#   tools/sw_next_version.sh [base-version]
#
# Which hml-pwa version to put in static/sw.js. Run it before you edit the file.
#
# Reads every OPEN PR's head branch through the GitHub API and takes the highest claim plus a gap.
# The API rather than `git branch -r`, because local remote refs go stale between fetches and CI
# runs on a shallow clone where the scan sees almost nothing — both of which quietly recommend a
# number somebody already holds.
#
# A GAP, not +1: the scan is a snapshot of a moving thing, and the number is free when you read it
# and taken by the time CI runs. The gap costs nothing, since the version is opaque and only has to
# increase.
#
# This is the same suggest() body that ci.yml prints in its failure message, kept here so an author
# can get the answer BEFORE pushing rather than after a red tick — and so the API half of the guard
# is exercised by hand when the guard changes. tools/ci_sw_guard_check.sh covers the decision half.
set -u
REPO="Humiley/humiley-timekeeping"
BASE=${1:-0}

suggest() {
  hi=$1
  for br in $(gh api --paginate "repos/$REPO/pulls?state=open" \
                --jq '.[].head.ref' 2>/dev/null || true); do
    raw=$(gh api -H "Accept: application/vnd.github.raw" \
            "repos/$REPO/contents/static/sw.js?ref=$br" 2>/dev/null || true)
    v=$(printf '%s' "$raw" | grep -oE 'hml-pwa-v[0-9]+' | head -1 || true)
    [ -z "$v" ] && continue
    n=${v#hml-pwa-v}
    case "$n" in ''|*[!0-9]*) continue ;; esac
    echo "  saw $br -> v$n" >&2
    [ "$n" -gt "$hi" ] && hi=$n
  done
  echo $((hi + 3))
}

echo "claims on every open PR:" >&2
pick=$(suggest "$BASE")
echo "suggested: hml-pwa-v$pick"
