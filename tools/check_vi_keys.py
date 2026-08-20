#!/usr/bin/env python3
"""Find keys claimed twice with DIFFERENT meanings in the `_VI` translation dictionary.

`_VI` is one flat object shared by every module in the portal, so a key is a claim on a word across
the whole product and a later definition silently wins. That is how the PMC "Issue" register came to
read *Phát hành* ("a controlled release") in Vietnamese after the design module claimed the same
word for its own meaning — a live regression nobody saw, because the obvious check does not work.

The obvious check does not work because the older `_VI` entries pack several keys onto one line, so
a line-leading regex never sees them. This walks the object from `const _VI = {` to its matching
brace and compares values per key, and reports only the collisions where the values DIFFER —
same-value duplicates are untidy but harmless and would drown the signal.

Usage:  python3 tools/check_vi_keys.py [path-to-html]
Exit 1 if any differing-value duplicate exists.
"""
import os
import re
import sys
from collections import defaultdict

SRC = sys.argv[1] if len(sys.argv) > 1 else os.path.join(
    os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "templates", "index.html")

# 'key': 'value' or "key": "value", with either quote style and escaped quotes inside.
PAIR = re.compile(r"""(?P<q>['"])(?P<key>(?:\\.|(?!(?P=q)).)*)(?P=q)\s*:\s*"""
                  r"""(?P<vq>['"])(?P<val>(?:\\.|(?!(?P=vq)).)*)(?P=vq)""")


def find_block(html):
    """The text between `const _VI = {` and its matching close brace.

    Braces are counted only outside string literals, so a `}` inside a translated phrase does not
    end the object early.
    """
    m = re.search(r"const\s+_VI\s*=\s*\{", html)
    if not m:
        raise SystemExit("could not find `const _VI = {` in %s" % SRC)
    i = m.end()
    depth, quote, esc, start = 1, None, False, i
    while i < len(html) and depth:
        c = html[i]
        if esc:
            esc = False
        elif c == "\\":
            esc = True
        elif quote:
            if c == quote:
                quote = None
        elif c in "'\"":
            quote = c
        elif c == "{":
            depth += 1
        elif c == "}":
            depth -= 1
        i += 1
    if depth:
        raise SystemExit("`_VI` object is not closed — the file may be mid-splice")
    return html[start:i - 1], html.count("\n", 0, start) + 1


def main():
    html = open(SRC, encoding="utf-8").read()
    block, first_line = find_block(html)
    seen = defaultdict(list)
    for m in PAIR.finditer(block):
        line = first_line + block.count("\n", 0, m.start())
        seen[m.group("key")].append((m.group("val"), line))

    clashes = {k: v for k, v in seen.items() if len({val for val, _ in v}) > 1}
    same = sum(1 for k, v in seen.items() if len(v) > 1 and len({val for val, _ in v}) == 1)

    for key in sorted(clashes):
        print("CLASH  %r — the LAST definition wins portal-wide:" % key)
        for val, line in clashes[key]:
            print("         line %-6d %s" % (line, val))
        print()

    print("%d key(s) in _VI · %d differing-value duplicate(s) · %d harmless same-value duplicate(s)"
          % (len(seen), len(clashes), same))
    if clashes:
        print("\nA key is a claim on a word across the WHOLE portal. Qualify yours "
              "('Production stage', not 'Stage') rather than claiming the bare word.")
    return 1 if clashes else 0


if __name__ == "__main__":
    sys.exit(main())
