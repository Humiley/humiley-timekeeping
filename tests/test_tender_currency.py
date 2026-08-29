"""A quotation presented in another currency, through `document()` — the one funnel.

`test_fx_quote` proves the arithmetic. This proves the DOCUMENT is internally consistent, because
that is what a customer receives: a letter whose total is in dollars and whose lines are in dong is
worse than one that was never converted, since it looks finished.

Everything the on-screen letter, the PDF and the Excel workbook print comes from `document()`, so a
document that agrees with itself here agrees on all three surfaces.
"""
import pytest

import fx_quote
import tender


def Q(lines=None):
    lines = lines if lines is not None else [
        {"srcId": "1", "itemCode": "A-1", "desc": "AHU", "unit": "set", "qty": 2,
         "unitCost": 100, "cogs": 200, "markupPct": 20,
         "unitSell": 300000000, "net": 600000000, "netAfterDiscount": 600000000,
         "discount": 0, "vatPct": 10, "vat": 60000000, "gross": 660000000},
        {"srcId": "2", "itemCode": "A-2", "desc": "Ductwork", "unit": "lot", "qty": 1,
         "unitCost": 50, "cogs": 100, "markupPct": 20,
         "unitSell": 400000000, "net": 400000000, "netAfterDiscount": 400000000,
         "discount": 0, "vatPct": 10, "vat": 40000000, "gross": 440000000}]
    sub = sum(l["net"] for l in lines)
    vat = sum(l["vat"] for l in lines)
    cogs = sum(l["cogs"] for l in lines)
    return {"lines": lines, "subtotal": sub, "discount": 0, "discountPct": 0,
            "net": sub, "vat": vat, "gross": sub + vat, "lineCount": len(lines),
            "cogs": cogs,
            # issue_check reads this; a fixture without it fails on the margin rule, not the one
            # under test.
            "grossMarginPct": ((sub - cogs) / sub * 100) if sub else 0}


def T(**kw):
    t = {"quoteNo": "QT-1", "client": "Acme", "clientTaxCode": "0123456789",
         "issueDate": "2026-01-05", "validUntil": "2026-02-05", "exclusions": "Crane hire",
         "amountInWords": "One billion sixty million dong"}
    t.update(kw)
    return t


USD = {"presentCurrency": "USD", "presentFx": 25500, "presentFxOn": "2026-08-29",
       "presentFxSource": "Vietcombank selling"}


# ── the default is unchanged ─────────────────────────────────────────────────────────────────────

def test_a_quotation_with_no_currency_set_is_exactly_as_it_was():
    """Every existing tender must be untouched by this."""
    d = tender.document(T(), Q())
    assert d["currency"] == "VND"
    assert d["money"] == {"code": "VND", "symbol": "₫", "places": 0}
    assert d["totals"]["gross"] == 1100000000
    assert "fx" not in d
    assert d["amountInWords"] == "One billion sixty million dong"


def test_choosing_VND_explicitly_is_also_a_no_op():
    d = tender.document(T(presentCurrency="VND", presentFx=1), Q())
    assert d["currency"] == "VND" and "fx" not in d


# ── the whole document moves together ────────────────────────────────────────────────────────────

def test_the_totals_the_lines_and_the_label_all_change_together():
    """THE rule. Any one of them left behind produces a document that contradicts itself."""
    d = tender.document(T(**USD), Q())
    assert d["currency"] == "USD"
    assert d["money"]["places"] == 2 and d["money"]["symbol"] == "$"
    assert d["totals"]["gross"] == pytest.approx(1100000000 / 25500, abs=0.01)
    assert all(l["net"] < 100000 for l in d["lines"])     # dollars, not dong


def test_the_lines_still_add_up_to_the_total_on_the_document():
    """What the customer's finance team actually checks."""
    d = tender.document(T(**USD), Q())
    assert sum(l["minor"]["gross"] for l in d["lines"]) == round(d["totals"]["gross"] * 100)


def test_the_column_headings_name_the_currency_that_is_printed_under_them():
    """Otherwise the workbook prints a dollar figure under 'Amount (VND)'."""
    cols = tender.columns(T(**USD))
    labels = [c["label"] for c in cols]
    assert "Unit Price (USD)" in labels and "Amount (USD)" in labels
    assert not any("(VND)" in x for x in labels)


def test_the_column_headings_are_untouched_for_an_ordinary_quotation():
    labels = [c["label"] for c in tender.columns(T())]
    assert "Amount (VND)" in labels


def test_the_module_level_column_list_is_not_mutated():
    """A dict mutated in place would leak the last tender's currency into the next request."""
    tender.columns(T(**USD))
    assert tender.COLUMNS_DEFAULT[5]["label"] == "Unit Price (VND)"


def test_the_conditions_paragraph_stops_saying_vietnamese_dong():
    """It is printed on the same page as the table. Left alone the letter contradicts itself."""
    d = tender.document(T(**USD), Q())
    cur = [t for t in d["terms"] if t["label"] == "Currency"][0]["text"]
    assert "USD" in cur and "25,500" in cur and "2026-08-29" in cur
    assert "Vietnamese Dong" not in cur


def test_a_tender_with_its_own_terms_keeps_them():
    """Somebody chose those words. Silently rewriting them is worse than a sentence that can be
    seen and fixed."""
    own = [{"label": "Currency", "text": "Prices are as agreed in the framework agreement."}]
    d = tender.document(T(terms=own, **USD), Q())
    assert d["terms"][0]["text"] == "Prices are as agreed in the framework agreement."


def test_the_amount_in_words_is_dropped_rather_than_left_saying_dong():
    """It was written against a DONG total. A sentence reading 'one billion dong' under a dollar
    grand total is the kind of contradiction a contract is argued over."""
    d = tender.document(T(**USD), Q())
    assert d["amountInWords"] == ""


# ── the rate is on the document ──────────────────────────────────────────────────────────────────

def test_the_rate_its_date_and_its_source_are_on_the_document():
    d = tender.document(T(**USD), Q())
    assert d["fx"]["rate"] == 25500
    assert d["fx"]["on"] == "2026-08-29"
    assert d["fx"]["source"] == "Vietcombank selling"


def test_the_dong_figures_stay_on_the_document():
    """So the record can always be traced back to what the company actually priced."""
    d = tender.document(T(**USD), Q())
    assert d["fx"]["vnd"]["gross"] == 1100000000


# ── a currency with no rate ──────────────────────────────────────────────────────────────────────

def test_building_the_document_refuses_rather_than_defaulting_the_rate():
    """A rate of 1 would print ₫1,100,000,000 as '1,100,000,000' under a USD heading."""
    with pytest.raises(fx_quote.FxError):
        tender.document(T(presentCurrency="USD"), Q())


def test_the_refusal_is_a_ValueError_so_the_endpoints_turn_it_into_a_400():
    """They already catch ValueError and return its message. A 500 would tell the estimator
    nothing they can act on."""
    assert issubclass(fx_quote.FxError, ValueError)


def test_issue_check_says_so_before_anything_is_pressed():
    """A refusal thrown while building the letter reads as a crash. This is the one place a tender
    already lists what is missing."""
    chk = tender.issue_check(T(presentCurrency="USD"), Q())
    assert chk["canIssue"] is False
    assert any("exchange rate" in m for m in chk["missing"]), chk["missing"]


def test_with_a_rate_the_quotation_can_be_issued():
    assert tender.issue_check(T(**USD), Q())["canIssue"] is True


def test_an_ordinary_vnd_quotation_is_not_asked_for_a_rate():
    assert tender.issue_check(T(), Q())["canIssue"] is True


# ── a currency with no minor unit ────────────────────────────────────────────────────────────────

def test_a_yen_quotation_prints_whole_yen():
    d = tender.document(T(presentCurrency="JPY", presentFx=170), Q())
    assert d["money"]["places"] == 0
    assert float(d["totals"]["gross"]).is_integer()
    assert all(float(l["gross"]).is_integer() for l in d["lines"])


def test_the_yen_lines_still_add_up():
    d = tender.document(T(presentCurrency="JPY", presentFx=170), Q())
    assert sum(l["minor"]["gross"] for l in d["lines"]) == round(d["totals"]["gross"])


# ── the customer's copy still carries no cost ────────────────────────────────────────────────────

def test_the_converted_lines_still_hide_cost_and_mark_up():
    """The oldest rule in this module, and a conversion that rebuilt the lines could undo it."""
    d = tender.document(T(**USD), Q())
    for l in d["lines"]:
        assert "unitCost" not in l and "cogs" not in l and "markupPct" not in l
