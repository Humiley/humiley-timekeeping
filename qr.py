"""A QR encoder, because a traveller card needs something a phone camera can read.

Scan-to-step only works if the code on the printed card actually scans. There is no QR library
available here and nothing in the portal generated one, so this is a byte-mode encoder to
ISO/IEC 18004: versions 1–10 at error-correction level M, which covers any portal URL up to 216
bytes with 15% of the symbol recoverable — enough to survive a card that has been handled on a
factory floor.

Pure: takes a string, returns a matrix of booleans or an SVG string. No I/O, no clock, no database.

── Why level M and not L ────────────────────────────────────────────────────────────────────────

L recovers 7% and would let a shorter URL use a smaller symbol. A traveller card lives in a
workshop: it gets folded, smudged with sealant and photographed at an angle under a work light. The
extra modules cost nothing on paper and are the difference between one scan and four.

── What this does not do ────────────────────────────────────────────────────────────────────────

No numeric or alphanumeric mode. They pack tighter, but a URL contains lowercase letters and so
falls into byte mode anyway; supporting three encodings to compress the one case that never occurs
would be three code paths where one is exercised.
"""

# ── GF(256) for Reed–Solomon, primitive polynomial 0x11d ────────────────────────────────────────
_EXP = [0] * 512
_LOG = [0] * 256


def _init_tables():
    x = 1
    for i in range(255):
        _EXP[i] = x
        _LOG[x] = i
        x <<= 1
        if x & 0x100:
            x ^= 0x11d
    for i in range(255, 512):
        _EXP[i] = _EXP[i - 255]


_init_tables()


def _mul(a, b):
    if a == 0 or b == 0:
        return 0
    return _EXP[_LOG[a] + _LOG[b]]


def _rs_generator(n):
    """The generator polynomial for n error-correction codewords, highest power first.

    Coefficient ORDER is the whole trap here. Multiplying the running product by (x + alpha^i) means
    the shifted copy keeps its coefficient and the scaled copy moves down one — get those two the
    wrong way round and every generator comes out reversed. The result still looks like a plausible
    polynomial and still produces a symbol that renders perfectly; it simply does not decode.
    """
    g = [1]
    for i in range(n):
        g2 = [0] * (len(g) + 1)
        for j, c in enumerate(g):
            g2[j] ^= c                      # the x * g(x) term
            g2[j + 1] ^= _mul(c, _EXP[i])   # the alpha^i * g(x) term
        g = g2
    return g


def _rs_encode(data, n):
    """The n error-correction codewords for one block of data codewords."""
    gen = _rs_generator(n)
    rem = [0] * n
    for byte in data:
        factor = byte ^ rem[0]
        rem = rem[1:] + [0]
        for i, g in enumerate(gen[1:]):
            rem[i] ^= _mul(g, factor)
    return rem


# ── Version tables, level M only ────────────────────────────────────────────────────────────────
# (total codewords, ec codewords per block, [(block count, data codewords per block), ...])
_M = {
    1:  (26,  10, [(1, 16)]),
    2:  (44,  16, [(1, 28)]),
    3:  (70,  26, [(1, 44)]),
    4:  (100, 18, [(2, 32)]),
    5:  (134, 24, [(2, 43)]),
    6:  (172, 16, [(4, 27)]),
    7:  (196, 18, [(4, 31)]),
    8:  (242, 22, [(2, 38), (2, 39)]),
    9:  (292, 22, [(3, 36), (2, 37)]),
    10: (346, 26, [(4, 43), (1, 44)]),
}

_ALIGN = {
    1: [], 2: [6, 18], 3: [6, 22], 4: [6, 26], 5: [6, 30], 6: [6, 34],
    7: [6, 22, 38], 8: [6, 24, 42], 9: [6, 26, 46], 10: [6, 28, 50],
}

_EC_LEVEL_BITS = 0b00          # level M
_MAX_VERSION = 10


def _capacity(version):
    """Data codewords available at this version, level M."""
    return sum(count * words for count, words in _M[version][2])


def _pick_version(nbytes):
    """The smallest version that fits. Raises rather than silently truncating.

    A truncated payload still produces a scannable code — one that opens the wrong URL. Refusing is
    the only outcome that cannot be mistaken for success.
    """
    for v in range(1, _MAX_VERSION + 1):
        # 4 bits mode + 8 or 16 bits length + the data itself, in whole codewords.
        header = 4 + (8 if v < 10 else 16)
        if (header + nbytes * 8 + 7) // 8 <= _capacity(v):
            return v
    raise ValueError("%d bytes will not fit in a version-%d QR symbol at level M (max %d)"
                     % (nbytes, _MAX_VERSION, _capacity(_MAX_VERSION) - 3))


def _bitstream(data, version):
    """Mode indicator, length, payload, terminator and padding — as a list of bits."""
    bits = []

    def put(value, length):
        for i in range(length - 1, -1, -1):
            bits.append((value >> i) & 1)

    put(0b0100, 4)                                   # byte mode
    put(len(data), 8 if version < 10 else 16)
    for byte in data:
        put(byte, 8)
    cap_bits = _capacity(version) * 8
    put(0, min(4, cap_bits - len(bits)))             # terminator, truncated if it will not fit
    while len(bits) % 8:
        bits.append(0)
    pad = [0xEC, 0x11]
    i = 0
    while len(bits) < cap_bits:
        put(pad[i % 2], 8)
        i += 1
    return bits


def _codewords(bits):
    return [int("".join(str(b) for b in bits[i:i + 8]), 2) for i in range(0, len(bits), 8)]


def _interleave(data_cw, version):
    """Split into blocks, add error correction, and interleave as the standard requires."""
    _, ec_per_block, groups = _M[version]
    blocks, pos = [], 0
    for count, words in groups:
        for _ in range(count):
            blocks.append(data_cw[pos:pos + words])
            pos += words
    ec_blocks = [_rs_encode(b, ec_per_block) for b in blocks]

    out = []
    for i in range(max(len(b) for b in blocks)):
        for b in blocks:
            if i < len(b):
                out.append(b[i])
    for i in range(ec_per_block):
        for b in ec_blocks:
            out.append(b[i])
    return out


# ── The symbol ──────────────────────────────────────────────────────────────────────────────────

def _new_matrix(size):
    return [[None] * size for _ in range(size)]


def _place_function_patterns(m, version):
    size = len(m)

    def finder(r, c):
        for dr in range(-1, 8):
            for dc in range(-1, 8):
                rr, cc = r + dr, c + dc
                if not (0 <= rr < size and 0 <= cc < size):
                    continue
                on = (0 <= dr <= 6 and dc in (0, 6)) or (0 <= dc <= 6 and dr in (0, 6)) \
                    or (2 <= dr <= 4 and 2 <= dc <= 4)
                m[rr][cc] = on

    finder(0, 0)
    finder(0, size - 7)
    finder(size - 7, 0)

    for i in range(size):                                    # timing
        if m[6][i] is None:
            m[6][i] = (i % 2 == 0)
        if m[i][6] is None:
            m[i][6] = (i % 2 == 0)

    # Alignment patterns sit at every combination of the version's centre coordinates EXCEPT the
    # three that would land on a finder. The exclusion has to be stated geometrically: testing
    # "is this module already set" instead silently drops the patterns centred on the timing row or
    # column — legitimate patterns at, for example, (6,22) on version 7 — and from version 7 up
    # that shifts nothing visually while making the symbol undecodable. Versions 2 to 6 have no such
    # centre, which is exactly why the bug hid until a long payload needed a bigger symbol.
    centres = _ALIGN[version]
    for r in centres:
        for c in centres:
            in_finder = ((r < 8 and c < 8) or (r < 8 and c >= size - 8)
                         or (r >= size - 8 and c < 8))
            if in_finder:
                continue
            for dr in range(-2, 3):
                for dc in range(-2, 3):
                    m[r + dr][c + dc] = (max(abs(dr), abs(dc)) != 1)

    m[size - 8][8] = True                                    # the dark module

    for i in range(9):                                       # reserve the format areas
        if m[8][i] is None:
            m[8][i] = False
        if m[i][8] is None:
            m[i][8] = False
    for i in range(8):
        if m[8][size - 1 - i] is None:
            m[8][size - 1 - i] = False
        if m[size - 1 - i][8] is None:
            m[size - 1 - i][8] = False

    if version >= 7:                                         # version information
        bits = _version_bits(version)
        for i in range(18):
            b = bool((bits >> i) & 1)
            m[i // 3][size - 11 + i % 3] = b
            m[size - 11 + i % 3][i // 3] = b


def _version_bits(version):
    """The 18-bit version information block: 6 version bits and a (18,6) Golay check."""
    rem = version << 12
    for i in range(17, 11, -1):
        if rem & (1 << i):
            rem ^= 0x1F25 << (i - 12)
    return (version << 12) | rem


def _format_bits(mask):
    data = (_EC_LEVEL_BITS << 3) | mask
    rem = data << 10
    for i in range(14, 9, -1):
        if rem & (1 << i):
            rem ^= 0b10100110111 << (i - 10)
    return ((data << 10) | rem) ^ 0b101010000010010


# The fifteen format-information modules, in the order the standard assigns bits 14 down to 0.
# Written out rather than computed: every off-by-one in this list produces a symbol that renders
# perfectly and decodes to nothing, and a table can be checked against the figure by eye.
_FORMAT_POS_1 = [(8, 0), (8, 1), (8, 2), (8, 3), (8, 4), (8, 5), (8, 7), (8, 8),
                 (7, 8), (5, 8), (4, 8), (3, 8), (2, 8), (1, 8), (0, 8)]


def _format_pos_2(size):
    return ([(size - 1 - i, 8) for i in range(7)] +
            [(8, size - 8 + i) for i in range(8)])


def _place_format(m, mask):
    """Both copies of the format information.

    The MOST significant bit goes at (8,0). Getting this backwards is not a cosmetic difference: the
    symbol still draws, the finder patterns still find, and no scanner on earth reads it — which is
    exactly how it survives every check short of decoding one.
    """
    size = len(m)
    bits = _format_bits(mask)
    pos2 = _format_pos_2(size)
    for i in range(15):
        b = bool((bits >> (14 - i)) & 1)
        m[_FORMAT_POS_1[i][0]][_FORMAT_POS_1[i][1]] = b
        m[pos2[i][0]][pos2[i][1]] = b
    m[size - 8][8] = True                      # the dark module, restated so it can never be lost


_MASKS = [
    lambda i, j: (i + j) % 2 == 0,
    lambda i, j: i % 2 == 0,
    lambda i, j: j % 3 == 0,
    lambda i, j: (i + j) % 3 == 0,
    lambda i, j: (i // 2 + j // 3) % 2 == 0,
    lambda i, j: (i * j) % 2 + (i * j) % 3 == 0,
    lambda i, j: ((i * j) % 2 + (i * j) % 3) % 2 == 0,
    lambda i, j: ((i + j) % 2 + (i * j) % 3) % 2 == 0,
]


def _place_data(m, codewords, mask):
    """Zigzag the data in from the bottom-right, applying the mask as each module is written."""
    size = len(m)
    bits = []
    for cw in codewords:
        for i in range(7, -1, -1):
            bits.append((cw >> i) & 1)
    idx = 0
    up = True
    col = size - 1
    while col > 0:
        if col == 6:                       # the vertical timing column is not a data column
            col -= 1
        rows = range(size - 1, -1, -1) if up else range(size)
        for row in rows:
            for c in (col, col - 1):
                if m[row][c] is not None:
                    continue
                bit = bits[idx] if idx < len(bits) else 0
                idx += 1
                m[row][c] = bool(bit) ^ _MASKS[mask](row, c)
        up = not up
        col -= 2


def _penalty(m):
    size = len(m)
    score = 0
    # Rule 1: runs of five or more of the same colour.
    for line in list(m) + [[m[r][c] for r in range(size)] for c in range(size)]:
        run, prev = 1, line[0]
        for v in line[1:]:
            if v == prev:
                run += 1
            else:
                if run >= 5:
                    score += 3 + (run - 5)
                run, prev = 1, v
        if run >= 5:
            score += 3 + (run - 5)
    # Rule 2: 2x2 blocks of one colour.
    for r in range(size - 1):
        for c in range(size - 1):
            if m[r][c] == m[r][c + 1] == m[r + 1][c] == m[r + 1][c + 1]:
                score += 3
    # Rule 3: the finder-like 1:1:3:1:1 pattern with four light modules beside it.
    pat_a = [True, False, True, True, True, False, True, False, False, False, False]
    pat_b = list(reversed(pat_a))
    for line in list(m) + [[m[r][c] for r in range(size)] for c in range(size)]:
        for i in range(size - 10):
            window = line[i:i + 11]
            if window == pat_a or window == pat_b:
                score += 40
    # Rule 4: imbalance between dark and light.
    dark = sum(1 for row in m for v in row if v)
    pct = dark * 100 // (size * size)
    score += 10 * (abs(pct - 50) // 5)
    return score


def matrix(text):
    """The QR modules for `text` as a list of rows of booleans (True = dark).

    Every mask is tried and the least-penalised chosen, as the standard requires — picking a fixed
    mask produces symbols that scan on a desk and fail on a shop floor, which is the worst possible
    place for the difference to show up.
    """
    data = text.encode("utf-8")
    version = _pick_version(len(data))
    cw = _interleave(_codewords(_bitstream(data, version)), version)
    size = version * 4 + 17

    best, best_score = None, None
    for mask in range(8):
        m = _new_matrix(size)
        _place_function_patterns(m, version)
        _place_data(m, cw, mask)
        _place_format(m, mask)
        s = _penalty(m)
        if best_score is None or s < best_score:
            best, best_score = m, s
    return best


def svg(text, module=4, quiet=4, dark="#0B1F3A", light="#FFFFFF"):
    """The symbol as an SVG string, ready to drop into a page or a printed card.

    The quiet zone is drawn, not assumed. A QR with no margin around it is unreadable by most
    scanners, and "it worked on my screen" is exactly how that ships.
    """
    m = matrix(text)
    n = len(m)
    dim = (n + quiet * 2) * module
    parts = ['<svg xmlns="http://www.w3.org/2000/svg" width="%d" height="%d" viewBox="0 0 %d %d" '
             'shape-rendering="crispEdges" role="img">' % (dim, dim, dim, dim),
             '<rect width="%d" height="%d" fill="%s"/>' % (dim, dim, light)]
    for r in range(n):
        c = 0
        while c < n:
            if not m[r][c]:
                c += 1
                continue
            run = 1
            while c + run < n and m[r][c + run]:
                run += 1
            parts.append('<rect x="%d" y="%d" width="%d" height="%d" fill="%s"/>'
                         % ((c + quiet) * module, (r + quiet) * module,
                            run * module, module, dark))
            c += run
    parts.append("</svg>")
    return "".join(parts)
