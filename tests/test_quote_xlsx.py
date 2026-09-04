"""The quotation workbook: the real letterhead, filled — not a letterhead redrawn in code.

Two things are worth testing hard. The template's chrome must survive untouched, because the whole
point of filling a template rather than generating one is that the header bar, the logo, the fonts
and the page setup stay the file the sales team already sends. And the sheet must stay CONSISTENT
when the bill is longer than the template's eight rows — the totals block, the merged ranges, the
SUM range and the unit drop-down all move together or the workbook is quietly wrong.
"""
import io
import re
import zipfile

import quote_xlsx as qx


def _doc(n_lines=5):
    return {
        "quoteNo": "HML-QT-2026-0001",
        "placeDate": "Ho Chi Minh City, 21 August 2026",
        "company": {"name": "HUMILEY ENGINEERING & SOLUTIONS", "address": "2nd Floor, 68 Nguyen Hue",
                    "contact": "www.humiley.com"},
        "client": {"name": "Quoc Viet Co., Ltd", "address": "Ho Chi Minh City, Vietnam"},
        "subject": "Sales Quotation No. HML-QT-2026-0001 — Air Handling Unit System",
        "intro": "Thank you for your enquiry.",
        "lines": [{"itemCode": "IT-%d" % (i + 1), "desc": "Line %d" % (i + 1), "qty": i + 1,
                   "unit": "unit", "unitSell": 1000000, "net": 1000000 * (i + 1)}
                  for i in range(n_lines)],
        "totals": {"subtotal": 15000000, "vat": 1500000, "gross": 16500000},
        "discountPct": 0, "vatPct": 10,
        "termsParagraph": "Valid 30 days.", "closing": "We look forward to it.",
        "contactLine": "Contact me directly.",
        "signatures": [{"name": "Anh Giang Nguyen", "title": "Sales Manager"}],
        "signerContact": "E  sales@humiley.com", "encl": "Detailed quotation (Excel / PDF)",
    }


def _sheet(doc):
    z = zipfile.ZipFile(io.BytesIO(qx.build(doc)))
    return z, z.read(qx.SHEET).decode("utf-8")


def _cells(xml):
    out = {}
    for m in re.finditer(r'<c r="([A-G]\d+)"[^>]*>(?:<f>([^<]*)</f>)?'
                         r'(?:<v>([^<]*)</v>|<is><t[^>]*>([^<]*)</t></is>)?</c>', xml):
        out[m.group(1)] = {"f": m.group(2) or "", "v": m.group(3) or "", "t": m.group(4) or ""}
    return out


# ── the template's own chrome must come through untouched ────────────────────────────────────────

def test_every_part_of_the_template_survives():
    """The header bar, the footer strip, the logo and the how-to sheet are the reason this fills a
    template instead of drawing one."""
    src = zipfile.ZipFile(qx.TEMPLATE)
    out = zipfile.ZipFile(io.BytesIO(qx.build(_doc())))
    assert set(out.namelist()) == set(src.namelist())
    for part in ("xl/styles.xml", "xl/theme/theme1.xml", "xl/media/image1.png",
                 "xl/media/image3.png", "xl/drawings/drawing1.xml", "xl/worksheets/sheet2.xml"):
        assert out.read(part) == src.read(part), part


def test_only_the_data_and_the_merges_are_rewritten():
    src = zipfile.ZipFile(qx.TEMPLATE).read(qx.SHEET).decode("utf-8")
    _z, out = _sheet(_doc())
    for keep in ("<pageSetup", "<headerFooter", "<pageMargins", 'showGridLines="0"', "<cols>"):
        assert keep in out, keep
    # page setup identical, header/footer identical — only sheetData and mergeCells differ
    assert re.search(r"<pageSetup[^>]*/>", src).group(0) == re.search(r"<pageSetup[^>]*/>", out).group(0)
    assert re.search(r"<headerFooter.*?</headerFooter>", src, re.S).group(0) == \
           re.search(r"<headerFooter.*?</headerFooter>", out, re.S).group(0)


def test_a_five_line_quotation_lands_on_exactly_the_rows_the_template_uses():
    """Same layout as the file the sales team already knows — the totals do not creep upward just
    because this quotation is shorter than the example."""
    _z, xml = _sheet(_doc(5))
    c = _cells(xml)
    assert c["A17"]["t"] == "#" and c["G17"]["t"] == "Amount (VND)"
    assert c["C26"]["t"] == "SUBTOTAL"
    assert c["C29"]["t"] == "GRAND TOTAL"
    assert c["G26"]["f"] == "SUM(G18:G25)"
    assert re.findall(r'<mergeCell ref="([^"]+)"', xml) == [
        "A1:D1", "A2:D2", "A3:D3", "D5:G5", "D6:G6", "A8:C8", "A9:C9", "A10:C10", "A12:G12",
        "A14:G14", "A15:G15", "C26:F26", "C27:E27", "C28:E28", "C29:F29", "A31:G31", "A33:G33",
        "A35:G35"]


# ── a bill longer than the template ──────────────────────────────────────────────────────────────

def test_a_longer_bill_moves_the_totals_the_merges_the_sum_and_the_dropdown_together():
    """Fourteen lines, so everything below the table shifts by six. If any one of these four moved
    without the others the workbook would still open and would still be wrong."""
    _z, xml = _sheet(_doc(14))
    c = _cells(xml)
    assert c["C32"]["t"] == "SUBTOTAL"                 # 26 + 6
    assert c["G32"]["f"] == "SUM(G18:G31)"             # covers all fourteen lines
    assert c["C35"]["t"] == "GRAND TOTAL"
    assert c["G35"]["f"] == "G32-G33+G34"
    merges = re.findall(r'<mergeCell ref="([^"]+)"', xml)
    assert "C32:F32" in merges and "C35:F35" in merges
    assert "A37:G37" in merges                          # the terms paragraph moved too
    assert re.search(r'sqref="(E\d+:E\d+)"', xml).group(1) == "E18:E31"


def test_a_short_bill_still_fills_the_template_to_its_eight_rows():
    _z, xml = _sheet(_doc(2))
    c = _cells(xml)
    assert c["B19"]["t"] == "IT-2"
    assert c["B25"]["t"] == ""                          # the spare rows stay, blank
    assert c["C26"]["t"] == "SUBTOTAL"


# ── it stays a working document ──────────────────────────────────────────────────────────────────

def test_the_numbering_and_the_amounts_are_formulas_not_frozen_numbers():
    """Somebody will open this and add a line. A workbook of frozen numbers looks identical and is
    dead."""
    _z, xml = _sheet(_doc())
    c = _cells(xml)
    assert c["A18"]["f"] == 'IF($B18="","",COUNTA($B$18:$B18))'
    assert c["G18"]["f"] == 'IF($B18="","",$D18*$F18)'
    assert c["G27"]["f"] == "G26*F27"
    assert c["G28"]["f"] == "(G26-G27)*F28"
    assert c["G29"]["f"] == "G26-G27+G28"


def test_the_percentages_are_written_as_fractions_because_the_cell_is_formatted_as_a_percent():
    _z, xml = _sheet(_doc())
    c = _cells(xml)
    assert c["F28"]["v"] == "0.1"                       # renders as 10%
    assert c["F27"]["v"] == "0"


def test_a_multi_line_description_gets_a_row_tall_enough_to_show_it():
    d = _doc(1)
    d["lines"][0]["desc"] = "one\ntwo\nthree\nfour"
    _z, xml = _sheet(d)
    # \b matters: without it the pattern also matches the "ht" inside customHeight="1".
    ht = re.search(r'<row r="18"[^>]*\sht="(\d+)"', xml).group(1)
    assert int(ht) >= 56
    assert qx.desc_height("a") == 16 and qx.desc_height("a\nb\nc\nd") == 56


# ── what must never reach the customer, and what must ────────────────────────────────────────────

def test_no_cost_or_markup_can_appear_anywhere_in_the_workbook():
    """The customer opens this file and can see every cell and every formula."""
    d = _doc()
    for ln in d["lines"]:
        ln["unitCost"] = 999999          # as if a caller passed the internal row by mistake
    _z, xml = _sheet(d)
    assert "999999" not in xml
    for banned in ("unitCost", "markup", "cogs", "Mark-up", "Cost"):
        assert banned not in xml, banned


def test_text_is_escaped_so_an_ampersand_in_a_customer_name_cannot_break_the_file():
    d = _doc()
    d["client"]["name"] = "Smith & Sons <Vietnam> Co."
    z, xml = _sheet(d)
    assert "Smith &amp; Sons &lt;Vietnam&gt; Co." in xml
    assert zipfile.ZipFile(io.BytesIO(qx.build(d))).testzip() is None


def test_the_filename_names_the_quotation_and_the_customer():
    assert qx.filename(_doc()) == "HML-QT-2026-0001-Quoc-Viet-Co-Ltd.xlsx"
    assert qx.filename({"quoteNo": "", "client": {}}).endswith(".xlsx")
