"""The quotation as the Excel letterhead the company already uses.

There are two ways to produce a branded workbook and only one of them stays correct. Drawing the
letterhead in code means the two-tone header bar, the logo, the footer strip, the fonts and the
column widths are re-derived every release and drift from the file the sales team actually sends.
So this does the other thing: it opens `static/brand/HML-QT-Quotation-Letterhead.xlsx` — the real
template, with its real chrome — and writes values into it. Styles, header and footer images,
page setup, the unit drop-down and the "How to use" sheet are never touched.

What IS regenerated is the sheet's data and its merged ranges, because a quotation does not have
eight lines just because the template has eight rows. Regenerating both together, from one row
map, is what keeps the totals block, the merges and the SUM range agreeing when the line count
changes — the alternative, surgically inserting rows and shifting every reference below them, has
four places to get wrong and no way to notice.

The formulas are written too, not just the values. The template is a working document: somebody
will open it, add a line, change a quantity, and expect the totals to move. A workbook of frozen
numbers would look identical and be dead.
"""

import io
import os
import re
import zipfile

TEMPLATE = os.path.join(os.path.dirname(os.path.abspath(__file__)),
                        "static", "brand", "HML-QT-Quotation-Letterhead.xlsx")

SHEET = "xl/worksheets/sheet1.xml"

# Style indices, read off the template. Each is a cell format already carrying the right font,
# colour, border and alignment — which is why nothing here sets any of those.
S_COMPANY, S_ADDR, S_DATE, S_REF = 1, 2, 3, 4
S_NAME, S_BODY, S_RE, S_PARA = 5, 6, 7, 8
S_THEAD, S_CELL, S_ITEM, S_DESC, S_MONEY = 9, 10, 11, 12, 13
S_TOT_LBL, S_TOT_VAL, S_PCT, S_GT_LBL, S_GT_VAL = 14, 15, 16, 17, 18
S_RULE, S_TITLE = 19, 20

MIN_LINE_ROWS = 8          # the template's own capacity; fewer would change how the letter sits

# Heights the template uses, by role rather than by row number, so they survive a longer bill.
H = {"company": 20, "addr": 14, "gap_s": 6, "gap_m": 10, "gap_xs": 4, "date": 13, "to": 14,
     "re": 18, "intro": 46, "thead": 22, "line": 16, "tot": 17, "gt": 21, "terms": 70,
     "closing": 30, "sig": 14}


def _esc(v):
    return (str("" if v is None else v).replace("&", "&amp;").replace("<", "&lt;")
            .replace(">", "&gt;"))


def _num(v):
    try:
        return float(v or 0)
    except (TypeError, ValueError):
        return 0.0


def _cell(ref, style, value=None, formula=None, text=None):
    """One <c>. Text goes inline rather than through sharedStrings — the shared table belongs to
    the template and appending to it would mean rewriting its count, its uniqueCount and every
    index below the insertion."""
    a = ' s="%d"' % style if style is not None else ""
    if text is not None:
        return '<c r="%s"%s t="inlineStr"><is><t xml:space="preserve">%s</t></is></c>' % (ref, a, _esc(text))
    body = ""
    if formula:
        body += "<f>%s</f>" % _esc(formula)
    if value is not None:
        body += "<v>%s</v>" % (("%d" % value) if float(value).is_integer() else repr(float(value)))
    return '<c r="%s"%s>%s</c>' % (ref, a, body)


def _row(n, height, cells):
    h = ' ht="%s" customHeight="1"' % height if height else ""
    return '<row r="%d" spans="1:7"%s>%s</row>' % (n, h, "".join(cells))


def _span(row, style, cols="ABCDEFG", text=None):
    """A merged banner line: the text sits in the first column and the rest carry the same style,
    which is what makes the fill and the border run the full width."""
    out = [_cell(cols[0] + str(row), style, text=text if text is not None else "")]
    out += [_cell(c + str(row), style, text="") for c in cols[1:]]
    return out


def desc_height(text):
    """A description of four lines needs a row four lines tall. The template proves the rate:
    its four-line AHU row is 56pt, its one-line rows are 16."""
    n = max(1, str(text or "").count("\n") + 1)
    return max(H["line"], 14 * n)


def build(doc, lines=None):
    """Fill the template from a `tender.document()` and return the .xlsx bytes.

    `doc["lines"]` is the customer's copy — no cost, no mark-up — so nothing this writes could
    disclose either even if the sheet were unhidden and every formula traced.
    """
    lines = list(lines if lines is not None else (doc.get("lines") or []))
    n = max(len(lines), MIN_LINE_ROWS)
    first = 18
    last = first + n - 1                    # last line row
    r_sub, r_disc, r_vat, r_gt = last + 1, last + 2, last + 3, last + 4
    r_terms, r_closing = r_gt + 2, r_gt + 4
    r_contact, r_yours = r_gt + 6, r_gt + 7
    r_rule, r_signer, r_title, r_sig3 = r_gt + 10, r_gt + 11, r_gt + 12, r_gt + 13
    r_encl = r_gt + 15

    co = doc.get("company") or {}
    client = doc.get("client") or {}
    sig = (doc.get("signatures") or [{}])[0]
    rows = []

    # ── letterhead block ──
    rows.append(_row(1, H["company"], _span(1, S_COMPANY, "ABCD", co.get("name") or "HUMILEY ENGINEERING & SOLUTIONS")))
    rows.append(_row(2, H["addr"], _span(2, S_ADDR, "ABCD", co.get("address") or "")))
    rows.append(_row(3, H["addr"], _span(3, S_ADDR, "ABCD", co.get("contact") or "")))
    rows.append(_row(5, H["gap_m"], _span(5, S_DATE, "DEFG", doc.get("placeDate") or "")))
    rows.append(_row(6, H["date"], _span(6, S_REF, "DEFG", "Ref: " + (doc.get("quoteNo") or ""))))
    rows.append(_row(8, H["to"], _span(8, S_NAME, "ABC", doc.get("salutationTo") or "Sir / Madam")))
    rows.append(_row(9, H["date"], _span(9, S_BODY, "ABC", client.get("name") or "")))
    rows.append(_row(10, H["date"], _span(10, S_BODY, "ABC", client.get("address") or "")))
    rows.append(_row(12, H["re"], _span(12, S_RE, text="RE:   " + (doc.get("subject") or ""))))
    rows.append(_row(14, H["to"], _span(14, S_BODY, text=doc.get("salutation") or "Dear Sir / Madam,")))
    rows.append(_row(15, H["intro"], _span(15, S_PARA, text=doc.get("intro") or "")))

    # ── the priced table ──
    # From the document, not from here — see tender.columns(). Three renderers each holding their
    # own copy of these seven strings is how a letter and the file attached to it drift apart.
    heads = [c["label"] for c in (doc.get("columns") or [])] or [
        "#", "Item", "Description", "Qty", "Unit", "Unit Price (VND)", "Amount (VND)"]
    cols = (doc.get("columns") or [])
    keys = [c.get("key") for c in cols] or ["idx", "itemCode", "desc", "qty", "unit", "unitSell", "net"]
    money = [bool(c.get("money")) for c in cols] or [False, False, False, False, False, True, True]
    rows.append(_row(17, H["thead"], [_cell("ABCDEFG"[i] + "17", S_THEAD, text=h) for i, h in enumerate(heads)]))
    for i in range(n):
        r = first + i
        ln = lines[i] if i < len(lines) else None
        desc = (ln or {}).get("desc") or ""
        # The row number and the amount stay FORMULAS: somebody will open this and add a line.
        cs = [_cell("A%d" % r, S_CELL, value=(i + 1) if ln else None,
                    formula='IF($B%d="","",COUNTA($B$%d:$B%d))' % (r, first, r)),
              _cell("B%d" % r, S_ITEM, text=(ln or {}).get("itemCode") or ""),
              _cell("C%d" % r, S_DESC, text=desc),
              _cell("D%d" % r, S_CELL, value=_num((ln or {}).get(keys[3])) if ln else None),
              # Column E is a unit ("lot", "package") for goods and a MONEY figure for services,
              # so its style follows the column rather than the position. Writing a professional
              # fee with the text style would left-align it under a right-aligned header and drop
              # its thousands separators — the file would be readable and wrong.
              (_cell("E%d" % r, S_MONEY, value=_num((ln or {}).get(keys[4])) if ln else None)
               if money[4] else
               _cell("E%d" % r, S_CELL, text=(ln or {}).get(keys[4]) or "")),
              _cell("F%d" % r, S_MONEY, value=_num((ln or {}).get(keys[5])) if ln else None),
              # The amount stays a FORMULA for a goods quotation, because somebody will open this
              # and add a line: qty x rate is arithmetic Excel should keep doing. For services the
              # total is fee PLUS expenses — two independent figures, not a product — so the
              # formula follows the columns instead of multiplying whatever lands in D and F.
              _cell("G%d" % r, S_MONEY, value=_num((ln or {}).get(keys[6])) if ln else None,
                    formula=('IF($B%d="","",$E%d+$F%d)' % (r, r, r)) if money[4]
                            else ('IF($B%d="","",$D%d*$F%d)' % (r, r, r)))]
        rows.append(_row(r, desc_height(desc) if ln else H["line"], cs))

    tot = doc.get("totals") or {}
    disc = _num(doc.get("discountPct")) / 100.0
    vat_pct = _num(doc.get("vatPct")) / 100.0
    sub = _num(tot.get("subtotal", tot.get("net")))
    rows.append(_row(r_sub, H["tot"], [_cell(c + str(r_sub), S_TOT_LBL, text="SUBTOTAL" if c == "C" else "")
                                       for c in "CDEF"] +
                    [_cell("G%d" % r_sub, S_TOT_VAL, value=sub, formula="SUM(G%d:G%d)" % (first, last))]))
    rows.append(_row(r_disc, H["tot"], [_cell(c + str(r_disc), S_TOT_LBL, text="Project Discount" if c == "C" else "")
                                        for c in "CDE"] +
                    [_cell("F%d" % r_disc, S_PCT, value=disc),
                     _cell("G%d" % r_disc, S_MONEY, value=round(sub * disc),
                           formula="G%d*F%d" % (r_sub, r_disc))]))
    rows.append(_row(r_vat, H["tot"], [_cell(c + str(r_vat), S_TOT_LBL, text="Tax / VAT (if applicable)" if c == "C" else "")
                                       for c in "CDE"] +
                    [_cell("F%d" % r_vat, S_PCT, value=vat_pct),
                     _cell("G%d" % r_vat, S_MONEY, value=_num(tot.get("vat")),
                           formula="(G%d-G%d)*F%d" % (r_sub, r_disc, r_vat))]))
    rows.append(_row(r_gt, H["gt"], [_cell(c + str(r_gt), S_GT_LBL, text="GRAND TOTAL" if c == "C" else "")
                                     for c in "CDEF"] +
                    [_cell("G%d" % r_gt, S_GT_VAL, value=_num(tot.get("gross")),
                           formula="G%d-G%d+G%d" % (r_sub, r_disc, r_vat))]))

    # ── the letter's closing ──
    rows.append(_row(r_terms, H["terms"], _span(r_terms, S_PARA, text=doc.get("termsParagraph") or "")))
    rows.append(_row(r_closing, H["closing"], _span(r_closing, S_PARA, text=doc.get("closing") or "")))
    rows.append(_row(r_contact, H["to"], _span(r_contact, S_BODY, text=doc.get("contactLine") or "")))
    rows.append(_row(r_yours, H["sig"], [_cell("A%d" % r_yours, S_BODY, text="Yours sincerely,")]))
    rows.append(_row(r_rule, H["gap_xs"], [_cell(c + str(r_rule), S_RULE, text="") for c in "ABCDE"]))
    rows.append(_row(r_signer, None, [_cell("A%d" % r_signer, S_NAME, text=(sig.get("name") or "").upper())]))
    rows.append(_row(r_title, H["sig"], [_cell("A%d" % r_title, S_TITLE, text=sig.get("title") or "")]))
    rows.append(_row(r_sig3, None, [_cell("A%d" % r_sig3, S_BODY, text=doc.get("signerContact") or "")]))
    rows.append(_row(r_encl, H["sig"], [_cell("A%d" % r_encl, S_BODY,
                                              text="Encl.   " + (doc.get("encl") or ""))]))

    merges = ["A1:D1", "A2:D2", "A3:D3", "D5:G5", "D6:G6", "A8:C8", "A9:C9", "A10:C10",
              "A12:G12", "A14:G14", "A15:G15",
              "C%d:F%d" % (r_sub, r_sub), "C%d:E%d" % (r_disc, r_disc),
              "C%d:E%d" % (r_vat, r_vat), "C%d:F%d" % (r_gt, r_gt),
              "A%d:G%d" % (r_terms, r_terms), "A%d:G%d" % (r_closing, r_closing),
              "A%d:G%d" % (r_contact, r_contact)]

    sheet = zipfile.ZipFile(TEMPLATE).read(SHEET).decode("utf-8")
    sheet = re.sub(r"<sheetData>.*?</sheetData>", "<sheetData>" + "".join(rows) + "</sheetData>",
                   sheet, flags=re.S)
    sheet = re.sub(r"<mergeCells[^>]*>.*?</mergeCells>",
                   '<mergeCells count="%d">%s</mergeCells>'
                   % (len(merges), "".join('<mergeCell ref="%s"/>' % m for m in merges)),
                   sheet, flags=re.S)
    # The unit drop-down covers the line rows, so it has to grow with them.
    sheet = re.sub(r'sqref="E18:E\d+"', 'sqref="E%d:E%d"' % (first, last), sheet)

    src = zipfile.ZipFile(TEMPLATE)
    buf = io.BytesIO()
    out = zipfile.ZipFile(buf, "w", zipfile.ZIP_DEFLATED)
    for item in src.infolist():
        data = src.read(item.filename)
        out.writestr(item, sheet.encode("utf-8") if item.filename == SHEET else data)
    out.close()
    return buf.getvalue()


def filename(doc):
    ref = re.sub(r"[^A-Za-z0-9._-]+", "-", str(doc.get("quoteNo") or "HML-QT")).strip("-")
    who = re.sub(r"[^A-Za-z0-9]+", "-", str((doc.get("client") or {}).get("name") or "")).strip("-")
    return (ref + ("-" + who if who else "") + ".xlsx")[:120]
