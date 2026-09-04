"""The QR encoder, checked against things it did not produce.

A wrong QR code is the most confident-looking failure in this repository. It renders as a crisp,
plausible symbol with correct finder patterns and a correct quiet zone; it looks right in a review,
looks right on a printed card, and reads as nothing at all under a camera. Three separate bugs in
the first draft of qr.py had exactly that shape:

  * the Reed-Solomon generator polynomial came out reversed,
  * the format information was written least-significant bit first instead of most,
  * and alignment patterns whose centre lands on the timing row were silently dropped, which is
    invisible below version 7 because no such centre exists there.

None of the three changes how the symbol looks. So the tests here are built on external references
rather than on the encoder's own output: published test vectors for the arithmetic, the published
format-information table, and — in tools/_qrcmp.py, run by hand because it needs Swift — a
module-for-module comparison against CoreImage. A test that only asks "did we produce a matrix"
would have passed on all three bugs.
"""
import pytest

import qr


# ── arithmetic, against published vectors ────────────────────────────────────────────────────────

def test_the_generator_polynomial_matches_the_published_one():
    """Reversed coefficients still produce a well-formed polynomial and a well-formed symbol."""
    assert qr._rs_generator(10) == [1, 216, 194, 159, 111, 199, 94, 95, 113, 157, 193]


def test_error_correction_matches_the_reference_codewords():
    data = [32, 91, 11, 120, 209, 114, 220, 77, 67, 64, 236, 17, 236, 17, 236, 17]
    assert qr._rs_encode(data, 10) == [196, 35, 39, 119, 235, 215, 231, 226, 93, 23]


def test_every_format_word_matches_the_published_table():
    """The eight level-M format strings, as printed in the standard."""
    published = ["101010000010010", "101000100100101", "101111001111100", "101101101001011",
                 "100010111111001", "100000011001110", "100111110010111", "100101010100000"]
    for mask, want in enumerate(published):
        assert format(qr._format_bits(mask), "015b") == want


def test_the_version_information_block_matches_the_published_value():
    assert format(qr._version_bits(7), "018b") == "000111110010010100"


# ── the symbol ───────────────────────────────────────────────────────────────────────────────────

def _decode_own(text):
    """Read a symbol back the way the standard says to, without consulting the encoder's state.

    The mask is taken from the symbol's own format information rather than being remembered, so a
    format written the wrong way round fails here instead of cancelling out.
    """
    m = qr.matrix(text)
    size = len(m)
    version = (size - 17) // 4

    bits = 0
    pos = [(8, 0), (8, 1), (8, 2), (8, 3), (8, 4), (8, 5), (8, 7), (8, 8),
           (7, 8), (5, 8), (4, 8), (3, 8), (2, 8), (1, 8), (0, 8)]
    for i, (r, c) in enumerate(pos):
        bits |= (1 if m[r][c] else 0) << (14 - i)
    raw = (bits ^ 0b101010000010010) >> 10
    mask, ec = raw & 7, (raw >> 3) & 3
    assert ec == 0, "the symbol must declare error-correction level M"

    fn = qr._new_matrix(size)
    qr._place_function_patterns(fn, version)
    out, up, col = [], True, size - 1
    while col > 0:
        if col == 6:
            col -= 1
        for row in (range(size - 1, -1, -1) if up else range(size)):
            for c in (col, col - 1):
                if fn[row][c] is None:
                    out.append(1 if (bool(m[row][c]) ^ qr._MASKS[mask](row, c)) else 0)
        up = not up
        col -= 2
    cw = [int("".join(str(b) for b in out[i:i + 8]), 2) for i in range(0, len(out), 8)]

    _, _, groups = qr._M[version]
    blocks = []
    for count, words in groups:
        for _ in range(count):
            blocks.append([0] * words)
    idx = 0
    for i in range(max(len(b) for b in blocks)):
        for b in blocks:
            if i < len(b):
                b[i] = cw[idx]
                idx += 1
    data = "".join(format(x, "08b") for x in (y for b in blocks for y in b))
    assert data[:4] == "0100", "byte mode"
    lb = 8 if version < 10 else 16
    n = int(data[4:4 + lb], 2)
    body = data[4 + lb:4 + lb + n * 8]
    return bytes(int(body[i:i + 8], 2) for i in range(0, len(body), 8)).decode("utf-8")


@pytest.mark.parametrize("text", [
    "x",
    "hello there",
    "https://portal.humiley.com/?ahu=ahu-abc123&step=IPQC-2",
    "https://portal.humiley.com/?ahu=" + "u" * 40 + "&step=WS-09",
    "PIN-2026-0417-01 / G4 — kiểm tra chất lượng",           # UTF-8, multi-byte
    "x" * 120,                                                # version 7: version info appears
    "x" * 150,                                                # version 8: two block groups
    "x" * 180,                                                # version 9
])
def test_a_symbol_reads_back_as_what_went_in(text):
    assert _decode_own(text) == text


def test_versions_seven_and_up_carry_their_alignment_patterns():
    """The bug this pins: an alignment centre on the timing row was skipped because that module was
    already set. Below version 7 no such centre exists, so nothing showed it."""
    size = 45                                     # version 7
    m = qr._new_matrix(size)
    qr._place_function_patterns(m, 7)
    for centre in [(6, 22), (22, 6), (22, 22), (22, 38), (38, 22), (38, 38)]:
        r, c = centre
        assert m[r][c] is True, "no alignment pattern at %s" % (centre,)
        assert m[r - 1][c - 1] is False, "alignment ring missing at %s" % (centre,)
    # And no pattern was drawn at the three centres that would sit on a finder. That cannot be
    # asserted module-by-module — an alignment ring laid over a finder happens to agree with the
    # finder almost everywhere, which is why it is such a quiet mistake. What it CANNOT do is leave
    # the count of data modules unchanged, so that is the check: see
    # test_the_number_of_data_modules_matches_the_codeword_count, which covers every version.
    free = sum(1 for row in m for v in row if v is None)
    assert free == qr._M[7][0] * 8, "version 7 has the wrong number of data modules"


def test_the_number_of_data_modules_matches_the_codeword_count():
    """If the function-pattern map reserves the wrong cells, every symbol is wrong by a shift."""
    for version, (total, _, _) in qr._M.items():
        size = version * 4 + 17
        m = qr._new_matrix(size)
        qr._place_function_patterns(m, version)
        free = sum(1 for row in m for v in row if v is None)
        # Remainder bits: 0 for version 1, 7 for versions 2-6, 0 for version 7+ up to 10.
        remainder = {1: 0, 2: 7, 3: 7, 4: 7, 5: 7, 6: 7, 7: 0, 8: 0, 9: 0, 10: 0}[version]
        assert free == total * 8 + remainder, "version %d" % version


def test_a_payload_too_large_is_refused_rather_than_truncated():
    """A truncated payload still scans. It opens the wrong page, which is worse than not scanning."""
    with pytest.raises(ValueError):
        qr.matrix("x" * 400)


# ── the SVG ──────────────────────────────────────────────────────────────────────────────────────

def test_the_svg_draws_its_quiet_zone():
    """A QR with no margin is unreadable to most scanners, and looks perfect on screen."""
    s = qr.svg("hello", module=4, quiet=4)
    n = len(qr.matrix("hello"))
    assert 'width="%d"' % ((n + 8) * 4) in s


def test_the_svg_is_self_contained_and_has_no_script():
    s = qr.svg("hello")
    assert s.startswith("<svg") and s.endswith("</svg>")
    assert "<script" not in s and "href" not in s
