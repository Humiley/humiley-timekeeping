"""Compare qr.py against macOS CoreImage, module for module.

    python3 tools/qr_check_against_coreimage.py

Run by hand — it needs Swift, so it is not part of the pytest suite. It exists because the QR bugs
that matter all produce a perfectly plausible-looking symbol, and the only way to know a symbol is
right is to check it against one this repository did not generate.

A whole-symbol diff is only meaningful when both encoders picked the same version and mask, so the
mask is read out of the reference and qr.py is re-rendered with it. Two caveats it prints rather
than hides: where the versions differ the symbols are not comparable, and where the payload contains
digits or capitals CoreImage may split it into mixed numeric/alphanumeric segments — a different,
equally legal encoding of the same text, which shows up as a large difference and is not a fault.
Payloads of pure lowercase bytes are the ones that must match exactly.
"""
import os
import subprocess
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
import qr    # noqa: E402

HERE = os.path.dirname(os.path.abspath(__file__))
SWIFT = sys.argv[1] if len(sys.argv) > 1 else os.path.join(HERE, "qr_reference.swift")


def reference(text):
    raw = subprocess.run(["swift", SWIFT, text], capture_output=True, text=True).stdout
    rows = [l.strip() for l in raw.splitlines() if l.strip()][1:]
    return [r[1:-1] for r in rows[1:-1]]


def read_mask(rows):
    bits = 0
    pos = [(8, 0), (8, 1), (8, 2), (8, 3), (8, 4), (8, 5), (8, 7), (8, 8),
           (7, 8), (5, 8), (4, 8), (3, 8), (2, 8), (1, 8), (0, 8)]
    for i, (r, c) in enumerate(pos):
        bits |= (1 if rows[r][c] == "1" else 0) << (14 - i)
    # The five data bits are the TOP of the 15-bit word: (ec << 3 | mask) << 10, then BCH,
    # then the XOR. Reading the bottom five gives a plausible small number every time — which
    # is how this misread survived several rounds of looking straight at it.
    raw = (bits ^ 0b101010000010010) >> 10
    return raw & 7, (raw >> 3) & 3


def ref_single_byte_segment(rows, version, mask, nbytes):
    """Did the reference encode the WHOLE payload as one byte segment?

    Checking only the mode indicator is not enough: CoreImage happily starts with a byte segment and
    then switches to alphanumeric part-way through a URL, which is legal, produces a different
    symbol, and reads back as mode 0100 at the front. So the first segment's declared length has to
    account for every byte, or the two symbols are encoding the same text differently and a
    module diff means nothing.
    """
    size = len(rows)
    fn = qr._new_matrix(size)
    qr._place_function_patterns(fn, version)
    need = 4 + (8 if version < 10 else 16)
    bits, up, col = [], True, size - 1
    while col > 0 and len(bits) < need:
        if col == 6:
            col -= 1
        for row in (range(size - 1, -1, -1) if up else range(size)):
            for c in (col, col - 1):
                if fn[row][c] is None and len(bits) < need:
                    bits.append(1 if ((rows[row][c] == "1") ^ qr._MASKS[mask](row, c)) else 0)
        up = not up
        col -= 2
    s = "".join(str(b) for b in bits)
    if s[:4] != "0100":
        return False
    return int(s[4:], 2) == nbytes


cases = ["hello there",
         "https://portal.humiley.com/?ahu=ahu-abc123&step=IPQC-2",
         "x" * 30, "x" * 60, "x" * 90, "x" * 120, "x" * 150, "x" * 160, "x" * 180,
         "PIN-2026-0417-01 / G4 — kiểm tra"]

for text in cases:
    ref = reference(text)
    rv = (len(ref) - 17) // 4
    mv = qr._pick_version(len(text.encode()))
    label = "%-14s %3d bytes" % (repr(text[:10]), len(text.encode()))
    if rv != mv:
        print("%s  ref v%-2d  mine v%-2d  (different version — not comparable)" % (label, rv, mv))
        continue
    mask, ec = read_mask(ref)
    if ec != 0:
        print("%s  ref v%-2d level %s — CoreImage upgraded the correction level, not comparable"
              % (label, rv, {0: "M", 1: "L", 2: "Q", 3: "H"}[ec]))
        continue
    cw = qr._interleave(qr._codewords(qr._bitstream(text.encode(), mv)), mv)
    m = qr._new_matrix(mv * 4 + 17)
    qr._place_function_patterns(m, mv)
    qr._place_data(m, cw, mask)
    qr._place_format(m, mask)
    mine = ["".join("1" if v else "0" for v in row) for row in m]
    diff = sum(1 for a, b in zip("".join(mine), "".join(ref)) if a != b)
    if diff and not ref_single_byte_segment(ref, rv, mask, len(text.encode())):
        print("%s  v%-2d mask %d  CoreImage split this into mixed segments — not comparable"
              % (label, rv, mask))
        continue
    print("%s  v%-2d mask %d  differing modules: %d%s"
          % (label, rv, mask, diff, "" if diff == 0 else "   <-- MISMATCH"))
