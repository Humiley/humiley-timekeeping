"""The generated PDFs must be set in the brand typeface, and must be able to draw Vietnamese.

Two requirements that used to pull against each other. The brand documents set their Normal style
to Calibri (humiley-brand/assets/document/HML_Document_EN.docx), so a quotation sent in anything
else is off-brand. But jsPDF's standard-14 fonts are WinAnsi and turn Vietnamese into mojibake,
which is why this slot originally held Be Vietnam Pro instead. Carlito satisfies both: it is the
metric-compatible open substitute for Calibri, and it covers the Vietnamese blocks completely.

The coverage assertions matter more than they look. A font that lacks a codepoint does not raise —
jsPDF draws nothing at all — so a missing glyph reaches the customer as a silent gap in a sentence.
The name on a contract is exactly where that gets noticed.
"""
import base64
import io
import os
import re
import struct

import pytest

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
ASSET = os.path.join(ROOT, "static", "vendor", "tk-font-brand.js")
LICENCE = os.path.join(ROOT, "static", "vendor", "tk-font-brand.OFL.txt")
HTML = os.path.join(ROOT, "templates", "index.html")

# Every Vietnamese-specific letter: the precomposed tone/vowel block, plus the four base letters
# Vietnamese adds to Latin (Đ, Ơ, Ư, Ă) and the ones it shares (Ĩ, Ũ).
VIETNAMESE = list(range(0x1EA0, 0x1EFA)) + [
    0x0110, 0x0111,   # Đ đ
    0x01A0, 0x01A1,   # Ơ ơ
    0x01AF, 0x01B0,   # Ư ư
    0x0102, 0x0103,   # Ă ă
    0x0128, 0x0129,   # Ĩ ĩ
    0x0168, 0x0169,   # Ũ ũ
]
DONG = 0x20AB          # ₫ — _pdfSafe used to rewrite this as "VND " because it could not be drawn


def _weights():
    """The two base64 TTFs the page hands to jsPDF, decoded straight out of the shipped asset."""
    src = io.open(ASSET, encoding="utf-8").read()
    out = {}
    for name in ("regular", "bold"):
        m = re.search(r'%s:\s*"([A-Za-z0-9+/=]+)"' % name, src)
        assert m, "%s weight missing from %s" % (name, ASSET)
        out[name] = base64.b64decode(m.group(1))
    return out


def _cmap(raw):
    """Codepoints the font can actually draw. Parsed from the real cmap, not from a claim."""
    num_tables = struct.unpack(">H", raw[4:6])[0]
    cmap_off = None
    for i in range(num_tables):
        rec = 12 + i * 16
        if raw[rec:rec + 4] == b"cmap":
            cmap_off = struct.unpack(">I", raw[rec + 8:rec + 12])[0]
    assert cmap_off, "no cmap table"
    n = struct.unpack(">H", raw[cmap_off + 2:cmap_off + 4])[0]
    sub = None
    for i in range(n):
        p = cmap_off + 4 + i * 8
        pid, eid, off = struct.unpack(">HHI", raw[p:p + 8])
        if (pid, eid) in ((3, 1), (3, 10), (0, 3), (0, 4)):
            sub = cmap_off + off
    assert sub, "no unicode cmap subtable"
    fmt = struct.unpack(">H", raw[sub:sub + 2])[0]
    assert fmt == 4, "unexpected cmap format %d" % fmt
    seg_x2 = struct.unpack(">H", raw[sub + 6:sub + 8])[0]
    seg = seg_x2 // 2
    ends = [struct.unpack(">H", raw[sub + 14 + j * 2:sub + 16 + j * 2])[0] for j in range(seg)]
    starts = [struct.unpack(">H", raw[sub + 16 + seg_x2 + j * 2:sub + 18 + seg_x2 + j * 2])[0]
              for j in range(seg)]
    cps = set()
    for s, e in zip(starts, ends):
        if e == 0xFFFF:
            continue
        cps.update(range(s, e + 1))
    return cps


@pytest.mark.parametrize("weight", ["regular", "bold"])
def test_the_font_can_draw_every_vietnamese_letter(weight):
    cps = _cmap(_weights()[weight])
    missing = [c for c in VIETNAMESE if c not in cps]
    assert not missing, (
        "%s weight cannot draw %d Vietnamese codepoint(s): %s — jsPDF draws nothing for these, so "
        "they reach the reader as gaps, not as errors"
        % (weight, len(missing), " ".join("U+%04X" % c for c in missing[:12])))


@pytest.mark.parametrize("weight", ["regular", "bold"])
def test_the_font_can_draw_the_dong_sign(weight):
    assert DONG in _cmap(_weights()[weight]), \
        "no ₫ in the %s weight — money would have to be written 'VND ' again" % weight


@pytest.mark.parametrize("weight", ["regular", "bold"])
def test_the_font_is_calibri_metric(weight):
    """Carlito is metric-compatible with Calibri; 2048 units/em is part of that contract. A face
    with different metrics would reflow every document that was laid out against the brand template."""
    raw = _weights()[weight]
    num_tables = struct.unpack(">H", raw[4:6])[0]
    head = None
    for i in range(num_tables):
        rec = 12 + i * 16
        if raw[rec:rec + 4] == b"head":
            head = struct.unpack(">I", raw[rec + 8:rec + 12])[0]
    assert head, "no head table"
    assert struct.unpack(">H", raw[head + 18:head + 20])[0] == 2048


def test_the_page_asks_for_the_brand_face():
    """The choke point every PDF setFont goes through must name the brand family, and must load the
    asset that provides it."""
    src = io.open(HTML, encoding="utf-8").read()
    assert "const TK_BRAND_FONT_NAME = 'Carlito';" in src
    assert "'/static/vendor/tk-font-brand.js'" in src
    assert "TK_VN_FONT" not in src, "a reference to the superseded font asset survives"


def test_the_licence_ships_with_the_font():
    """The OFL permits redistribution only with the licence attached, and a subset is still a copy.
    The repository is public, so this is the condition under which the font may be here at all."""
    assert os.path.exists(LICENCE), "the OFL text is missing"
    txt = io.open(LICENCE, encoding="utf-8").read()
    assert "SIL OPEN FONT LICENSE Version 1.1" in txt
    assert "Carlito" in txt, "the licence does not name the font it covers"
    assert "Be Vietnam Pro" not in txt, "stale licence text left from the previous font"


def test_the_generated_asset_declares_its_provenance():
    """A checked-in binary blob with no stated origin is one nobody can rebuild or verify."""
    head = io.open(ASSET, encoding="utf-8").read(900)
    assert "tools/make_pdf_font.py" in head, "the asset does not say how to regenerate it"
    assert "SIL Open Font License" in head


# --- the brand type scale -------------------------------------------------------------------
# Sizes read out of the official template: body 11, secondary 9, captions 7, headings 13 and 14,
# title 26. Nothing else is a brand size.
BRAND_SIZES = {7, 9, 11, 13, 14, 26}


def test_every_pdf_font_size_is_on_the_brand_scale():
    """The PDF code had drifted to twenty-two sizes across 144 call sites — 6.5, 7.3, 7.4, 7.6,
    7.8, 8.2, 8.6, 8.8 and 10.5 among them. Sizes that fine apart are not a decision anybody made;
    they accumulate one document at a time, and the result is that two documents from the same
    company do not look like each other. This is what stops the next one landing."""
    src = io.open(HTML, encoding="utf-8").read()
    calls = re.findall(r"\b[A-Za-z_][A-Za-z0-9_]*\.setFontSize\(([0-9]+(?:\.[0-9]+)?)\)", src)
    assert calls, "no setFontSize calls found at all — this check would be examining nothing"
    off = sorted({float(c) for c in calls} - {float(b) for b in BRAND_SIZES})
    assert not off, (
        "%d PDF font size(s) are off the brand scale %s: %s"
        % (len(off), sorted(BRAND_SIZES), ", ".join(str(o) for o in off)))


def test_the_scale_is_declared_once_and_matches_the_brand():
    """A scale that exists only as scattered literals is one nobody can look up."""
    src = io.open(HTML, encoding="utf-8").read()
    m = re.search(r"const _LH_TYPE = \{([^}]*)\};", src)
    assert m, "_LH_TYPE is missing — the scale has no single declaration"
    declared = {int(v) for v in re.findall(r":\s*([0-9]+)", m.group(1))}
    assert declared == BRAND_SIZES, \
        "_LH_TYPE declares %s but the brand scale is %s" % (sorted(declared), sorted(BRAND_SIZES))


def test_caller_supplied_sizes_are_snapped_too():
    """Two exporters take the size as an argument. Without snapping at that choke point a caller
    can reintroduce an off-scale size that the literal check above cannot see."""
    src = io.open(HTML, encoding="utf-8").read()
    assert "function _brandSize(" in src
    assert not re.search(r"setFontSize\(size \|\| [0-9]", src), \
        "a parameterised exporter still passes an unsnapped caller size straight to setFontSize"
