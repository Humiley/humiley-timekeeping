#!/usr/bin/env bash
#
# Set static/sw.js to a service-worker version nothing else has claimed.
#
#   tools/swbump.sh          bump to (highest anywhere) + 1
#   tools/swbump.sh --check  print what it would do, change nothing
#
# WHY THIS EXISTS. The version is picked by hand, and the number that is safe depends on every
# other branch in flight — not just on main. Two branches picked v294 independently once and both
# merged, so production answered v294 before AND after a deploy: the version could not tell two
# builds apart, and a deploy check that polled /api/build went green ~20s after a merge that had
# not deployed yet.
#
# Picking main + 1 is the obvious move and it is wrong whenever somebody else is mid-PR. The
# correct number is one above the highest claimed ANYWHERE, which is a question about eleven remote
# branches that nobody answers by hand at 6pm.
#
# WHY NOT DERIVE IT FROM THE COMMIT, which is the tidier idea. Three things read this literal: the
# CI deploy gate greps the file, /api/build serves it as the deployed build's identity, and every
# installed PWA caches under it as a cache NAME. Moving to a commit-derived value means changing
# all three together, and getting it wrong strands users on a stale shell — the exact failure the
# stale-shell work was written to fix. That change is worth making; it is not worth making
# casually, and this script removes the daily friction without touching the deploy path at all.
set -euo pipefail

cd "$(dirname "$0")/.."
SW=static/sw.js
[ -f "$SW" ] || { echo "no $SW here" >&2; exit 1; }

git fetch -q origin 2>/dev/null || echo "(could not fetch — reading the refs already present)" >&2

cur=$(grep -oE 'hml-pwa-v[0-9]+' "$SW" | head -1 | sed 's/hml-pwa-v//')
[ -n "$cur" ] || { echo "no hml-pwa-vNNN found in $SW" >&2; exit 1; }

best=$cur
holder="this working tree"
for ref in $(git for-each-ref --format='%(refname:short)' refs/remotes/origin); do
  v=$(git show "$ref:$SW" 2>/dev/null </dev/null | grep -oE 'hml-pwa-v[0-9]+' | head -1 | sed 's/hml-pwa-v//') || true
  [ -n "${v:-}" ] || continue
  if [ "$v" -gt "$best" ]; then best=$v; holder=$ref; fi
done

next=$((best + 1))
echo "highest claimed anywhere : v$best  ($holder)"
echo "this working tree        : v$cur"

if [ "${1:-}" = "--check" ]; then
  echo "would set               : v$next"
  exit 0
fi

# Only the CACHE constant. A blanket sed would also rewrite the version quoted in the comment block
# above it, which is documentation of a past incident and not a value.
python3 - "$SW" "$next" <<'PY'
import io, re, sys
p, n = sys.argv[1], sys.argv[2]
s = io.open(p, encoding='utf-8').read()
new, count = re.subn(r"(const CACHE = 'hml-pwa-v)\d+(';)", r"\g<1>%s\g<2>" % n, s, count=1)
if count != 1:
    sys.exit("expected exactly one `const CACHE = 'hml-pwa-vNNN';` line, found %d" % count)
io.open(p, 'w', encoding='utf-8').write(new)
PY

node --check "$SW" 2>/dev/null || { echo "sw.js no longer parses — reverting" >&2; git checkout -- "$SW"; exit 1; }
echo "set                     : v$next"
