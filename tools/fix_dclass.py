#!/usr/bin/env python3
"""Correct the EN 1886 D-class thresholds across the AHU controlled document set.

The set states 4 mm/m as the D2 limit. EN 1886 places 4 mm/m at D1 and 10 mm/m at D2 — the same
table AeroSelect classifies against (packages/calculations/src/standards.ts) and the one the portal
now judges test T2 by. The Design Standards carry a second error in the same sentence: D1 = 2.5 mm/m.

WHAT THIS DELIBERATELY DOES NOT DO: change anybody's acceptance level. The SOP's KPI table targets
"D2 or better", and simply substituting "D2 = 10 mm/m" would loosen the accepted deflection from
4 mm/m to 10 mm/m — a real relaxation of a quality criterion, which is not a typo fix and not mine
to make. The corrected wording states the standard's thresholds and leaves the target class where
it already lives, so the acceptance follows from whichever class a unit is sold as.

Originals are copied to *.pre-dclass-fix.bak beside each file before anything is written.

Usage:  python3 tools/fix_dclass.py [--apply]      (default: dry run)
"""
import glob
import os
import re
import shutil
import sys
import zipfile

ROOT = "/Users/huynguyen/Library/CloudStorage/OneDrive-Humiley(2)/Claude Projects/AHU Production"
APPLY = "--apply" in sys.argv

# (what it says now, what it should say). Both sides appear verbatim in the XML — verified with
# tools/_probe_runs.py, because Word routinely splits a phrase across runs and a replace that
# silently matches nothing is worse than an error.
EDITS = [
    # SOP / training: the acceptance cell for test T2.
    ("D2: ≤ 4 mm/m", "D1: ≤ 4 mm/m, D2: ≤ 10 mm/m"),
    # Design Standards: both figures in one sentence were wrong.
    ("D2 = 4 mm/m, D1 = 2.5 mm/m", "D1 = 4 mm/m, D2 = 10 mm/m"),
    ("D2 = 4 mm/m", "D1 = 4 mm/m, D2 = 10 mm/m"),
]

TARGETS = [
    "AHU_Master_Production_Procedure_EN-VN.docx",
    "AHU_Master_Production_Procedure_EN-VN_BG.docx",
    "00_Master_Documents/HML-AHU-SOP-MASTER-001_Production_Procedure_EN-VN.docx",
    "00_Master_Documents/HML-AHU-SOP-MASTER-001_Production_Procedure_EN-VN_BG.docx",
    "00_Master_Documents/HML-AHU-DS-COMP-001_Design_Standards.docx",
    "00_Master_Documents/HML-AHU-DS-COMP-001_Design_Standards_BG.docx",
    "00_Master_Documents/HML-AHU-TRN-001_Production_Training.pptx",
]


def parts_of(path):
    """The XML parts that carry visible text, for docx and pptx alike."""
    with zipfile.ZipFile(path) as z:
        return [n for n in z.namelist()
                if n.endswith("document.xml") or re.match(r"ppt/slides/slide\d+\.xml$", n)]


def rewrite(path, apply):
    changed = {}
    with zipfile.ZipFile(path) as z:
        names = z.namelist()
        blobs = {n: z.read(n) for n in names}
    for n in parts_of(path):
        xml = blobs[n].decode("utf-8")
        before = xml
        for old, new in EDITS:
            if old in xml:
                cnt = xml.count(old)
                xml = xml.replace(old, new)
                changed.setdefault(n, []).append((old, new, cnt))
        if xml != before:
            blobs[n] = xml.encode("utf-8")
    if not changed:
        return None
    if apply:
        bak = path + ".pre-dclass-fix.bak"
        if not os.path.exists(bak):
            shutil.copy2(path, bak)
        tmp = path + ".tmp"
        # Preserve order and compression so the package stays a valid Office file.
        with zipfile.ZipFile(path) as src, zipfile.ZipFile(tmp, "w", zipfile.ZIP_DEFLATED) as out:
            for info in src.infolist():
                out.writestr(info, blobs[info.filename])
        os.replace(tmp, path)
    return changed


total = 0
for rel in TARGETS:
    path = os.path.join(ROOT, rel)
    if not os.path.exists(path):
        print("MISSING  %s" % rel)
        continue
    res = rewrite(path, APPLY)
    if not res:
        print("no match %s" % rel)
        continue
    for part, edits in res.items():
        for old, new, cnt in edits:
            print("%s  %s [%s]\n      %r\n   -> %r  (x%d)"
                  % ("WROTE   " if APPLY else "would fix", rel, part.rsplit("/", 1)[-1],
                     old, new, cnt))
            total += cnt

print("\n%d replacement(s) %s" % (total, "written" if APPLY else "pending — rerun with --apply"))
