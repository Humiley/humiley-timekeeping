#!/usr/bin/env python3
"""Syntax-check every inline <script> block in templates/index.html.

The file is a single 2.8 MB page whose JavaScript lives in a couple of dozen inline blocks. A bad
splice there does not fail a Python test and does not fail a browser load loudly — it kills one
script block, and every function defined below the break silently stops existing. This runs
`node --check` over each block so a syntax error is caught at edit time instead of by a user
clicking a button that no longer has a handler.

Two things this deliberately refuses to do quietly:
  · pass when it found NO blocks to check. If the regex ever stops matching — the file gets
    restructured, someone switches to a build step — "checked 0 blocks, 0 failed" is a green tick
    that means nothing was examined. That is the same shape as a size assertion that passed while
    six functions were being deleted from this very file. Zero blocks is a failure.
  · crash with a traceback when node is missing. Then it is not obvious whether the code is fine or
    the checker never ran.

Written by the AHU-production session; adopted here with those two guards added.

Usage:  python3 tools/check_index_js.py [path-to-html]
"""
import os
import re
import subprocess
import sys
import tempfile

SRC = sys.argv[1] if len(sys.argv) > 1 else os.path.join(
    os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "templates", "index.html")

# Only inline blocks. A <script src=...> has no body to check, and type="application/json" or a
# template type is data, not code.
BLOCK = re.compile(r"<script\b([^>]*)>(.*?)</script>", re.S | re.I)


def main():
    try:
        subprocess.run(["node", "--version"], capture_output=True, check=True)
    except (OSError, subprocess.CalledProcessError):
        print("FAIL  node is not available — the JavaScript in index.html was NOT checked.")
        return 1
    html = open(SRC, encoding="utf-8").read()
    blocks, bad = 0, 0
    for m in BLOCK.finditer(html):
        attrs, body = m.group(1), m.group(2)
        if re.search(r'\bsrc\s*=', attrs, re.I):
            continue
        t = re.search(r'\btype\s*=\s*["\']?([^"\'\s>]+)', attrs, re.I)
        if t and t.group(1).lower() not in ("text/javascript", "application/javascript", "module"):
            continue
        blocks += 1
        line = html.count("\n", 0, m.start(2)) + 1
        with tempfile.NamedTemporaryFile("w", suffix=".js", delete=False, encoding="utf-8") as fh:
            fh.write(body)
            tmp = fh.name
        try:
            r = subprocess.run(["node", "--check", tmp], capture_output=True, text=True)
            if r.returncode != 0:
                bad += 1
                # node reports a line number within the block; translate it back to the file.
                err = r.stderr.strip().replace(tmp, "%s:<block starting line %d>" % (SRC, line))
                print("FAIL  block at line %d\n%s\n" % (line, err))
        finally:
            os.unlink(tmp)
    if not blocks:
        print("FAIL  found no inline script blocks in %s — nothing was checked.\n"
              "      Either the file changed shape or this pattern stopped matching; either way\n"
              "      a pass here would be meaningless." % SRC)
        return 1
    print("checked %d inline script block(s), %d failed" % (blocks, bad))
    return 1 if bad else 0


if __name__ == "__main__":
    sys.exit(main())
