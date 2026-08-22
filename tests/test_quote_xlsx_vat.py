"""The workbook must not recalculate its way to a different tax than the letter shows.

A PDF is read; an Excel file is CHECKED — somebody puts a cursor in the cell and Excel recomputes
the formula on open. So a cached value that disagrees with the formula beside it is the worst
outcome available: the file is right until the customer opens it, and wrong in front of them.

The VAT row used to carry the server's per-line total as its value and "(subtotal − discount) ×
one header rate" as its formula. Identical while every line is rated the same. On a tender mixing
a 10%-rated domestic sale with a zero-rated export, opening the file overstated the tax by the
whole of the exempt line.
"""
import io
import re
import zipfile

import pytest

import quote_xlsx
import tender


A = tender.assumptions()
L = dict(qty=1, exwUnit=100000, currency="USD", mfnDutyPct=10)
T = {"costingType": tender.TRADING, "vatPct": 10, "assump": {}, "id": "T1", "quoteNo": "QT-1"}


def _doc(overrides=None, **tkw):
    master = tender.cost_master([dict(L, id="L1", desc="Domestic sale"),
                                 dict(L, id="L2", desc="Export")], [], A)
    t = dict(T, **tkw)
    quote = tender.quotation(t, master=master, overrides=overrides)
    return tender.document(t, quote), quote


def _vat_row(doc):
    """(label, percent cell, formula, cached value) off the real generated file."""
    z = zipfile.ZipFile(io.BytesIO(quote_xlsx.build(doc)))
    name = [n for n in z.namelist() if n.startswith("xl/worksheets/sheet")][0]
    xml = z.read(name).decode("utf-8")
    row = next(m.group(1) for m in re.finditer(r'<row r="\d+".*?>(.*?)</row>', xml, re.S)
               if "Tax / VAT" in m.group(1))
    label = formula = value = pct = None
    for c in re.finditer(r'<c r="([A-Z]+)(\d+)"[^>]*>(.*?)</c>', row, re.S):
        col, body = c.group(1), c.group(3)
        f = re.search(r"<f>(.*?)</f>", body, re.S)
        v = re.search(r"<v>(.*?)</v>", body, re.S)
        t = re.search(r"<is><t[^>]*>(.*?)</t></is>", body, re.S)
        if col == "C" and t:
            label = t.group(1)
        if col == "F":
            pct = (v.group(1) if v else None) or (t.group(1) if t else None)
        if col == "G":
            formula = f.group(1) if f else None
            value = float(v.group(1)) if v else None
    return label, pct, formula, value


def test_one_rate_keeps_a_formula_excel_can_recompute():
    """The common case must not regress into a dead number: a quotation whose totals recompute is
    the reason the workbook is sent alongside the PDF at all."""
    doc, quote = _doc()
    label, pct, formula, value = _vat_row(doc)
    assert formula, "the single-rate sheet lost its formula"
    assert value == float(quote["vat"])
    assert float(pct) == pytest.approx(0.10)
    assert label == "Tax / VAT (if applicable)"

    # And the formula, evaluated by hand exactly as Excel would, gives the same answer.
    tot = doc["totals"]
    assert round((tot["subtotal"] - tot["discount"]) * doc["vatPct"] / 100.0) == round(quote["vat"])


def test_mixed_rates_carry_no_formula_that_could_disagree():
    doc, quote = _doc(overrides=[{"srcId": "L2", "vatPct": 0}])
    label, pct, formula, value = _vat_row(doc)
    assert formula is None, \
        "a single-rate formula was written for a tender whose lines are not at one rate"
    assert value == float(quote["vat"])
    assert label == "Tax / VAT (rates vary by line)", label
    assert pct == "per line"


def test_the_fixture_really_is_a_disagreement_and_not_a_coincidence():
    """Without this, both tests above would pass on a fixture where the two calculations happen to
    match — which is exactly how the defect survived: every existing test used one rate."""
    doc, quote = _doc(overrides=[{"srcId": "L2", "vatPct": 0}])
    tot = doc["totals"]
    single_rate = (tot["subtotal"] - tot["discount"]) * doc["vatPct"] / 100.0
    assert round(single_rate) != round(quote["vat"])
    assert round(single_rate) == round(quote["vat"]) * 2, "the exempt line is half the tender"


def test_the_grand_total_still_reconciles_in_both_cases():
    """Whatever the VAT cell is, the grand total the customer reads has to be net + VAT."""
    for overrides in (None, [{"srcId": "L2", "vatPct": 0}]):
        doc, quote = _doc(overrides=overrides)
        tot = doc["totals"]
        assert tot["gross"] == tot["net"] + tot["vat"]
        assert tot["net"] == tot["subtotal"] - tot["discount"]


def test_a_discounted_mixed_rate_tender_is_still_consistent():
    doc, quote = _doc(overrides=[{"srcId": "L2", "vatPct": 0}], discountPct=7)
    label, pct, formula, value = _vat_row(doc)
    assert formula is None
    assert value == float(quote["vat"])
    # VAT is charged on the discounted base, per line, and the lines still add up to the header.
    assert sum(l["vat"] for l in quote["lines"]) == quote["vat"]
