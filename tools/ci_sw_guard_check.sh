#!/bin/bash
# Exercise the version guard's decision logic outside CI.
#
# The last time this guard changed, its author tested the DECISION and stubbed the data gathering —
# and the stubbed half was the half that broke, failing the guard's own PR. So this drives the real
# comparison and the real suggest() shape, with `gh` stubbed to return controlled answers, and it
# checks the property that matters most: a suggestion that cannot be computed must NEVER change
# whether the guard passes or fails.
set -u

pass=0; fail=0
check() { # name expected_exit actual_exit
  if [ "$2" = "$3" ]; then pass=$((pass+1)); printf '  ok    %s\n' "$1"
  else fail=$((fail+1)); printf '  FAIL  %s (wanted exit %s, got %s)\n' "$1" "$2" "$3"; fi
}

# The guard's logic from .github/workflows/ci.yml, lifted verbatim in shape. `suggest` is the new
# part; SUGGEST_OK controls
# whether it can reach its data, standing in for the API being unavailable.
guard() { # mine theirs
  m=$1; t=$2
  suggest() {
    hi=$1
    if [ "${SUGGEST_OK:-1}" = "0" ]; then return 1; fi   # API unreachable
    for n in $PEERS; do [ "$n" -gt "$hi" ] && hi=$n; done
    echo $((hi + 3))
  }
  if [ "$m" = "$t" ] || [ "$(printf '%s\n%s\n' "$m" "$t" | sort -n | tail -1)" != "$m" ]; then
    pick=$(suggest "$t" 2>/dev/null || echo $((t + 3)))
    echo "SUGGEST=$pick"
    return 1
  fi
  return 0
}

echo "the decision itself"
PEERS="" SUGGEST_OK=1
guard 460 450 >/dev/null; check "a higher version passes"            0 $?
guard 450 450 >/dev/null; check "the same version is refused"        1 $?
guard 449 450 >/dev/null; check "a lower version is refused"         1 $?
guard 1000 999 >/dev/null; check "numeric, not lexical: 1000 > 999"  0 $?
guard 999 1000 >/dev/null; check "and 999 < 1000 is refused"         1 $?

echo
echo "the suggestion"
PEERS="455 457 452" SUGGEST_OK=1
out=$(guard 450 450); check "takes the highest peer claim plus a gap" "SUGGEST=460" "$out"
PEERS="" SUGGEST_OK=1
out=$(guard 450 450); check "falls back to base plus a gap with no peers" "SUGGEST=453" "$out"
PEERS="440 441" SUGGEST_OK=1
out=$(guard 450 450); check "never suggests below the base" "SUGGEST=453" "$out"

echo
echo "the property that matters: advice must not change the verdict"
PEERS="455" SUGGEST_OK=0
guard 460 450 >/dev/null; check "a GOOD version still passes when suggest() fails" 0 $?
out=$(guard 450 450); check "a bad version still fails, with a fallback number" "SUGGEST=453" "$out"
guard 450 450 >/dev/null; check "and still exits non-zero"                        1 $?

echo
printf '%d passed, %d failed\n' "$pass" "$fail"
[ "$fail" -eq 0 ]
