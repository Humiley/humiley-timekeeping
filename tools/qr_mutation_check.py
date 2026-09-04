"""Reintroduce each of the three QR bugs and confirm the tests catch them.

A passing test suite over a QR encoder proves very little on its own: the bugs that matter here all
produce a well-formed, good-looking symbol. So each one is put back, one at a time, and the suite is
run. A bug that survives means the test for it is decorative.
"""
import os
import re
import shutil
import subprocess
import sys

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
QR = os.path.join(ROOT, "qr.py")
BACKUP = QR + ".mutate-backup"

MUTATIONS = [
    ("reversed Reed-Solomon generator",
     "            g2[j] ^= c                      # the x * g(x) term\n"
     "            g2[j + 1] ^= _mul(c, _EXP[i])   # the alpha^i * g(x) term",
     "            g2[j] ^= _mul(c, _EXP[i])\n"
     "            g2[j + 1] ^= c"),
    ("format information written LSB first",
     "        b = bool((bits >> (14 - i)) & 1)",
     "        b = bool((bits >> i) & 1)"),
    ("alignment patterns skipped where a module is already set",
     "            in_finder = ((r < 8 and c < 8) or (r < 8 and c >= size - 8)\n"
     "                         or (r >= size - 8 and c < 8))\n"
     "            if in_finder:\n"
     "                continue",
     "            if m[r][c] is not None:\n"
     "                continue"),
]

original = open(QR).read()
shutil.copy(QR, BACKUP)
failures = []
try:
    for name, good, bad in MUTATIONS:
        if original.count(good) != 1:
            print("SKIP  %s — anchor not found (the code moved)" % name)
            failures.append(name)
            continue
        open(QR, "w").write(original.replace(good, bad))
        r = subprocess.run([sys.executable, "-m", "pytest", os.path.join(ROOT, "tests/test_qr.py"),
                            "-q", "-p", "no:cacheprovider", "--tb=no"],
                           capture_output=True, text=True, cwd=ROOT)
        caught = r.returncode != 0
        n = len(re.findall(r"^FAILED", r.stdout, re.M)) or r.stdout.count("F")
        print("%-4s %s%s" % ("OK" if caught else "MISS", name,
                             ("  (%d test(s) failed)" % n) if caught else
                             "  — THE SUITE DID NOT NOTICE"))
        if not caught:
            failures.append(name)
finally:
    shutil.copy(BACKUP, QR)
    os.remove(BACKUP)

print("\nrestored qr.py")
sys.exit(1 if failures else 0)
