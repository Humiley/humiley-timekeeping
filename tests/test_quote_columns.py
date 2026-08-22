"""What the priced table's seven columns mean, decided once.

The letterhead template gives seven columns and no more, so this is not a choice about how many but
about what they carry. Goods are sold by quantity at a rate; a consultancy engagement is not.
"Qty 1, Unit: package" is a column pair saying nothing, printed beside a fee whose two halves —
professional time and travel — the client's own tender form asks for separately.

The seven headers were previously written out in THREE renderers (PDF, on-screen preview, Excel).
That is the same arrangement that let the discount be applied differently by each of four surfaces:
the moment they disagree, the letter a customer holds and the file they open stop being the same
document.
"""
import io
import re
import zipfile
from xml.sax.saxutils import unescape

import pytest

import quote_xlsx
import tender


A = tender.assumptions()
IMP = {"qty": 2, "exwUnit": 100000, "currency": "USD", "mfnDutyPct": 10}
PKGS = [{"id": "1", "code": "WP-00", "ursRef": "General", "name": "PM & kick-off",
         "durationMonths": 12, "daysDIR": 10, "daysADM": 24,
         "travelPeople": 1, "travelTrips": 4, "travelNights": 2},
        {"id": "2", "code": "WP-01", "ursRef": "URS-01", "name": "Facility assessment",
         "durationMonths": 2, "daysSME": 12, "daysENG": 18,
         "travelPeople": 2, "travelTrips": 2, "travelNights": 4}]

GOODS_HEADS = ["#", "Item", "Description", "Qty", "Unit", "Unit Price (VND)", "Amount (VND)"]


def _doc(ctype, **kw):
    t = dict({"costingType": ctype, "vatPct": 10, "assump": {}, "quoteNo": "Q1",
              "client": "X", "clientTaxCode": "1", "issueDate": "2026-01-01",
              "validUntil": "2026-02-01"}, **kw)
    if ctype == tender.SERVICES:
        r = tender.services_rollup(PKGS, A)
        return t, tender.document(t, tender.quotation(t, rollup=r))
    t["imports"] = [dict(IMP, id="L1", desc="AHU"), dict(IMP, id="L2", desc="Valve", exwUnit=4000)]
    t["locals"] = []
    m = tender.cost_master(t["imports"], [], A)
    return t, tender.document(t, tender.quotation(t, master=m))


# --- the goods path must not have moved ---------------------------------------------------------

def test_a_goods_quotation_keeps_the_columns_it_always_had():
    """A change here is a regression, not a feature."""
    _t, doc = _doc(tender.TRADING)
    assert [c["label"] for c in doc["columns"]] == GOODS_HEADS


def test_epc_is_a_goods_quotation_too():
    """A plant is quoted as lots of works, not as consultant days."""
    t = {"costingType": tender.EPC}
    assert [c["label"] for c in tender.columns(t)] == GOODS_HEADS


def test_an_unknown_costing_type_falls_back_to_goods():
    assert [c["label"] for c in tender.columns({"costingType": "something-new"})] == GOODS_HEADS
    assert [c["label"] for c in tender.columns({})] == GOODS_HEADS


# --- services --------------------------------------------------------------------------------------

def test_a_services_quotation_carries_the_columns_the_clients_form_asks_for():
    _t, doc = _doc(tender.SERVICES)
    assert [c["label"] for c in doc["columns"]] == [
        "#", "URS Ref.", "Scope of Services", "Days",
        "Professional Fee (VND)", "Travel & Expenses (VND)", "Total Price (VND)"]


def test_both_column_sets_are_seven_wide():
    """The letterhead template gives seven and no more. An eighth would not be a wider table; it
    would be a table that no longer fits the stationery it is printed on."""
    assert len(tender.COLUMNS_DEFAULT) == 7
    assert len(tender.COLUMNS_SERVICES) == 7


def test_fee_plus_expenses_equals_the_line_total():
    """Two columns that do not add up to the third would be worse than one column."""
    _t, doc = _doc(tender.SERVICES)
    for l in doc["lines"]:
        assert l["professionalFee"] + l["expenses"] == l["net"]


def test_every_services_column_key_exists_on_the_lines():
    """A column whose key is not on the line renders blank — a silent empty cell in a customer's
    quotation, with nothing anywhere reporting a fault."""
    _t, doc = _doc(tender.SERVICES)
    for c in doc["columns"]:
        if c["key"] == "idx":
            continue
        for l in doc["lines"]:
            assert c["key"] in l, "column %r has no value on the line" % c["key"]


def test_every_goods_column_key_exists_on_the_lines():
    _t, doc = _doc(tender.TRADING)
    for c in doc["columns"]:
        if c["key"] == "idx":
            continue
        for l in doc["lines"]:
            assert c["key"] in l, "column %r has no value on the line" % c["key"]


# --- the Excel export follows the columns, not fixed positions ----------------------------------------

def _sheet(doc):
    z = zipfile.ZipFile(io.BytesIO(quote_xlsx.build(doc)))
    return z.read("xl/worksheets/sheet1.xml").decode("utf-8", "replace")


def test_the_workbook_header_row_matches_the_document():
    """Read from row 17 of the sheet, where the exporter writes them as inline strings — not from
    sharedStrings, which holds the letterhead template's own text and would have passed on the
    template rather than on anything this code produced."""
    _t, doc = _doc(tender.SERVICES)
    xml = _sheet(doc)
    row = xml[xml.index('r="17"'):]
    # Unescaped before comparing: "Travel & Expenses" is stored as "Travel &amp; Expenses", which
    # is the exporter escaping correctly. Comparing raw would fail on a file that is right.
    row = unescape(row[:row.index("</row>")])
    for c in doc["columns"]:
        assert c["label"] in row, "%r missing from the workbook header row" % c["label"]


def test_a_services_total_is_fee_plus_expenses_not_days_times_expenses():
    """The goods formula is qty x rate. Carrying it over would multiply consultant days by a
    travel budget and produce a confident, enormous, wrong number that Excel would recompute on
    every open."""
    _t, doc = _doc(tender.SERVICES)
    xml = _sheet(doc)
    assert "$E18+$F18" in xml, "the services total is not fee + expenses"
    assert "$D18*$F18" not in xml, "the goods qty x rate formula leaked into a services quotation"


def test_a_goods_total_is_still_qty_times_rate():
    _t, doc = _doc(tender.TRADING)
    xml = _sheet(doc)
    assert "$D18*$F18" in xml
    assert "$E18+$F18" not in xml


def test_a_services_fee_column_is_written_as_money_not_text():
    """Column E is a unit ("lot") for goods and a money figure for services. Writing a fee with the
    text style would left-align it under a right-aligned header and drop its thousands
    separators — readable, and wrong."""
    _t, doc = _doc(tender.SERVICES)
    xml = _sheet(doc)
    m = re.search(r'<c r="E18"[^>]*s="(\d+)"', xml)
    assert m, "E18 not found"
    assert int(m.group(1)) == quote_xlsx.S_MONEY


def test_the_exporter_still_works_if_a_document_carries_no_columns():
    """Older stored documents predate the field. They must render as goods rather than as a
    quotation with no header row at all."""
    _t, doc = _doc(tender.TRADING)
    doc.pop("columns", None)
    xml = _sheet(doc)
    row = xml[xml.index('r="17"'):]
    row = unescape(row[:row.index("</row>")])
    for label in GOODS_HEADS:
        assert label in row
