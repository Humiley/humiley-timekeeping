"""Figures that are wrong without being errors.

Everything here used to travel the whole way to a customer's PDF in silence. That is the expensive
kind of defect in a pricing tool: nothing raises, nothing is red, and the estimator sees a total
that looks exactly like a total. The fixes do not block a quotation — a tender that will not open
cannot be corrected — they make the silence audible.

The division of labour matters and is pinned here: quotation() carries the FACTS (what was asked
for versus what was applied, which lines have a quantity and no money, how many days cost nothing)
and issue_check() turns them into the sentences a person reads. Two modules each composing their
own warning list is how two surfaces come to say different things about one tender.
"""
import pytest

import tender


A = tender.assumptions()
IMP = {"qty": 1, "exwUnit": 100000, "currency": "USD", "mfnDutyPct": 10}


def _says_capped(quote):
    return any("share of the price" in w for w in tender.issue_check({}, quote)["warnings"])


def _trading(**kw):
    t = dict({"costingType": tender.TRADING, "vatPct": 10, "assump": {}, "id": "T1"}, **kw)
    imports = [dict(IMP, id="L1", desc="Pump")]
    return tender.quotation(t, master=tender.cost_master(imports, [], A))


# --- a discount that is not a share of the price ------------------------------------------------

def test_a_discount_over_100_percent_does_not_invert_the_invoice():
    """150 is one keystroke from 15, and it used to produce a negative net, a negative VAT and a
    grand total the company owed the customer — with the P&L and the cash flow following it down."""
    q = _trading(discountPct=150)
    assert q["net"] >= 0 and q["gross"] >= 0 and q["vat"] >= 0
    assert q["discountPct"] == 100.0
    assert q["discountPctAsked"] == 150.0
    assert q["discountCapped"] is True


def test_a_negative_discount_does_not_quietly_put_the_price_up():
    q = _trading(discountPct=-20)
    assert q["discountPct"] == 0.0
    assert q["discount"] == 0
    assert q["net"] == q["subtotal"], "a negative discount added money to the price"
    assert q["discountCapped"] is True


def test_a_capped_discount_says_so_rather_than_just_being_capped():
    """Silently clamping is the same class of defect as silently inverting: the estimator sees a
    number that is not the one they typed, with nothing to say why."""
    q = _trading(discountPct=150)
    w = tender.issue_check({"discountPct": 150}, q)["warnings"]
    assert any("150" in x and "100" in x for x in w), w


def test_a_real_discount_is_left_exactly_alone():
    q = _trading(discountPct=15)
    assert q["discountPct"] == 15.0 and q["discountCapped"] is False
    assert not _says_capped(q)


def test_a_full_discount_is_a_real_discount_not_a_capped_one():
    """100% is the edge of the range, not outside it — a free-of-charge supply is a thing people
    quote. It must not be reported as a mistake."""
    q = _trading(discountPct=100)
    assert q["net"] == 0 and q["discountCapped"] is False
    assert not _says_capped(q), "a legitimate 100% discount was flagged as a mistake"


# --- effort that costs nothing --------------------------------------------------------------------

def _services(effort):
    pkgs = [{"id": "1", "code": "WP-1", "name": "Package", "effort": effort}]
    roll = tender.services_rollup(pkgs, A)
    quote = tender.quotation({"costingType": tender.SERVICES, "vatPct": 10, "assump": {}},
                             rollup=roll)
    return roll, quote


def test_an_unrecognised_grade_no_longer_costs_nothing_in_silence():
    """`GRADE_RATE.get(grade, 0)` hands out a zero rate for any grade it does not know — a typo, a
    rate card whose codes differ, a grade retired from GRADES while packages still reference it.
    Ten days of a director's time then priced at zero and read on screen as though it were costed."""
    roll, quote = _services([{"grade": "NOPE", "days": 10}])
    assert roll["unpricedDays"] == 10.0
    assert roll["unknownGrades"] == ["NOPE"]
    assert quote["unpricedDays"] == 10.0, "the fact did not reach the quotation"
    w = tender.issue_check({}, quote)["warnings"]
    assert any("NOPE" in x for x in w), w


def test_free_days_are_found_even_inside_a_package_that_totals_healthily():
    """This is the case a line-level check misses: the package sells for 40 million, so nothing
    about its total looks wrong, and ten of its days are still being given away."""
    roll, quote = _services([{"grade": "NOPE", "days": 10}, {"grade": "CON", "days": 5}])
    assert quote["lines"][0]["net"] > 0, "the fixture must LOOK healthy or it proves nothing"
    assert roll["unpricedDays"] == 10.0
    assert tender.issue_check({}, quote)["warnings"], \
        "a package with ten free days inside it reported nothing"


def test_a_grade_the_system_knows_can_never_be_quoted_free():
    """Zeroing a rate in the assumptions does NOT hand the days out for nothing — the rate falls
    through to the card. Pinned because the obvious reading of that `or` chain is that a zero
    assumption wins, and somebody reasoning about the warning above will want to know why a known
    grade can never trigger it. Every rate on the card is non-zero, so the only route to unpriced
    days is a grade nothing recognises."""
    zero = dict(A, rateCon=0)
    roll = tender.services_rollup([{"id": "1", "code": "W", "name": "P",
                                    "effort": [{"grade": "CON", "days": 4}]}], zero)
    assert roll["unpricedDays"] == 0
    assert roll["packages"][0]["effort"][0]["rate"] == tender.GRADE_RATE["CON"]
    assert all(tender.GRADE_RATE[g] > 0 for g in tender.GRADE_RATE), \
        "a zero on the card would reopen the silent route this test rules out"


def test_days_priced_normally_raise_nothing():
    roll, quote = _services([{"grade": "CON", "days": 5}])
    assert roll["unpricedDays"] == 0
    assert roll["unknownGrades"] == []
    assert quote["unpricedLines"] == []


# --- a line with a quantity and no money -----------------------------------------------------------

def test_a_line_carrying_a_quantity_but_no_money_is_named():
    imports = [dict(IMP, id="L1", desc="Pump"), dict(IMP, id="L2", desc="Freebie", exwUnit=0)]
    q = tender.quotation({"costingType": tender.TRADING, "vatPct": 10, "assump": {}},
                         master=tender.cost_master(imports, [], A))
    assert q["unpricedLines"] == ["Freebie"]
    w = tender.issue_check({}, q)["warnings"]
    assert any("Freebie" in x for x in w), w


def test_a_hundred_percent_discount_does_not_make_every_line_look_unpriced():
    """The lines are checked on what they are worth, not on what is left after the document-level
    discount — otherwise a legitimate free-of-charge quotation would name every line it has."""
    q = _trading(discountPct=100)
    assert q["unpricedLines"] == []


# --- the facts are always present, on every engine ---------------------------------------------------

def test_every_engine_reports_these_facts_even_when_there_is_nothing_to_report():
    """A caller that has to check whether the key exists will eventually forget to, and the check
    it forgets is the one that would have caught the zero."""
    roll = tender.bom_rollup([{"costCentre": "CIV", "qty": 1, "unitCostUsd": 400000}], A)
    for quote in (_trading(),
                  tender.quotation({"costingType": tender.EPC, "vatPct": 10, "assump": {}},
                                   rollup=roll),
                  _services([{"grade": "CON", "days": 5}])[1]):
        assert isinstance(quote["unpricedLines"], list)
        assert isinstance(quote["unknownGrades"], list)
        assert quote["unpricedDays"] == 0
        assert quote["discountCapped"] is False
