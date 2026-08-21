"""The third costing model: a consultancy engagement, priced from effort.

Humiley's real EU-GMP tenders (the Bidiphar SVI and OSD commercial quotation forms) are a
work-package breakdown — work package, URS reference, scope, key deliverables, duration,
professional fee, travel & expenses — with a separate sheet of optional services. Neither existing
engine fits: TRADING costs a customs chain and a consultancy imports nothing; EPC costs a bill of
materials and a consultancy has no materials. What it sells is people's time.

So the cost base is DAYS x DAY RATE by grade, and the fee follows from it. A fee picked out of the
air cannot be defended when the client asks why, cannot be compared with what the work actually
cost, and leaves the business unable to tell a good engagement from one it lost money on.

TWO OF THE TESTS BELOW EXIST BECAUSE THE FIRST DRAFT FAILED THEM. `apply_profit(cost, pct, basis)`
and `achieved_margin(price, cost)` take their arguments in different orders, and both were called
the wrong way round. Neither raised: the first quietly applied a 0% mark-up so every package was
sold at cost, and the second reported a NEGATIVE margin on a profitable job. A fee equal to cost
and a minus sign in front of a margin are exactly the kind of wrong number that looks like a
pricing decision rather than a defect.
"""
import pytest

import tender


A = tender.assumptions()

PKGS = [
    {"id": "WP00", "code": "WP-00", "ursRef": "General", "name": "Project Management & Kick-off",
     "durationMonths": 12,
     "effort": [{"grade": "DIR", "days": 10}, {"grade": "ADM", "days": 24}],
     "travelPeople": 1, "travelTrips": 4, "travelNights": 2},
    {"id": "WP01", "code": "WP-01", "ursRef": "URS-01", "name": "Facility & Engineering Assessment",
     "durationMonths": 2,
     "effort": [{"grade": "SME", "days": 12}, {"grade": "ENG", "days": 18}],
     "travelPeople": 2, "travelTrips": 2, "travelNights": 4},
    {"id": "WP07", "code": "WP-07", "ursRef": "URS-07", "name": "Technology Transfer Readiness",
     "durationMonths": 4, "optional": True,
     "effort": [{"grade": "SME", "days": 20}, {"grade": "CON", "days": 15}],
     "travelPeople": 2, "travelTrips": 3, "travelNights": 3},
]


def _tender(**kw):
    t = {"costingType": tender.SERVICES, "vatPct": 10, "discountPct": 0, "durationMonths": 12,
         "assump": {}, "quoteNo": "Q-SVC-1", "client": "Client", "clientTaxCode": "1",
         "issueDate": "2026-01-01", "validUntil": "2026-03-01"}
    t.update(kw)
    return t


# --- the cost base is effort -----------------------------------------------------------------

def test_labour_is_days_times_the_grade_rate():
    p = tender.package_cost(PKGS[1], A)
    assert p["labour"] == 12 * tender.GRADE_RATE["SME"] + 18 * tender.GRADE_RATE["ENG"]
    assert p["days"] == 30


def test_a_per_package_rate_overrides_the_grade_default():
    """A named expert is not billed at the grade's standard rate."""
    pkg = dict(PKGS[1], effort=[{"grade": "SME", "days": 10, "rate": 20_000_000}])
    assert tender.package_cost(pkg, A)["labour"] == 200_000_000


def test_expenses_are_derived_from_the_trip_not_typed_as_a_lump():
    """"Two consultants, two visits, four nights each" is checkable; a number in a box is not."""
    p = tender.package_cost(PKGS[1], A)
    d = p["expenseDetail"]
    assert d["travel"] == 2 * 2 * A["travelTripCost"]
    assert d["hotel"] == 2 * 2 * 4 * A["hotelNight"]
    # A travel day is a day away from base: the nights plus the day of travel itself.
    assert d["perDiem"] == 2 * 2 * (4 + 1) * A["perDiemDay"]
    assert p["expenses"] == d["travel"] + d["hotel"] + d["perDiem"] + d["other"]


def test_cost_is_labour_plus_expenses_and_nothing_else():
    p = tender.package_cost(PKGS[1], A)
    assert p["cost"] == p["labour"] + p["expenses"]


# --- the two silent argument-order defects --------------------------------------------------

def test_the_markup_is_actually_applied():
    """First draft called apply_profit(cost, MARKUP, pct) — arguments transposed. It did not raise;
    it applied 0% and sold every package at cost."""
    p = tender.package_cost(dict(PKGS[1], markupPct=35), A)
    assert p["fee"] > p["cost"], "the fee equals the cost — the mark-up was not applied"
    assert p["fee"] == round(p["cost"] * 1.35)


def test_the_margin_is_positive_on_a_profitable_package():
    """First draft called achieved_margin(cost, fee) — arguments transposed. It reported -35% on a
    package earning +25.93%, which reads as a decision to sell at a loss."""
    p = tender.package_cost(dict(PKGS[1], markupPct=35), A)
    assert p["marginPct"] > 0, "a package priced above cost reported a negative margin"
    assert p["marginPct"] == pytest.approx(25.93, abs=0.01)


def test_markup_and_margin_are_not_confused():
    """35% mark-up is a 25.93% margin. Reporting the mark-up as the margin overstates what the
    business keeps by nine points."""
    p = tender.package_cost(dict(PKGS[1], markupPct=35), A)
    assert p["markupPct"] == 35
    assert p["marginPct"] != p["markupPct"]


def test_the_rollup_margin_agrees_with_the_quotation():
    """Two code paths compute this; if they disagree, one screen contradicts another."""
    r = tender.services_rollup(PKGS, A)
    q = tender.quotation(_tender(), rollup=r)
    assert r["marginPct"] == pytest.approx(q["grossMarginPct"], abs=0.01)


# --- optional packages ------------------------------------------------------------------------

def test_a_declined_optional_package_vanishes_rather_than_showing_as_zero():
    """A zero row in a tender reads as 'we forgot to price this'."""
    r = tender.services_rollup(PKGS, A, config={"WP-07": {"include": False}})
    assert r["packageCount"] == 2
    assert "WP-07" not in [p["code"] for p in r["packages"]]
    assert r["excludedPackages"] == ["WP-07"]
    q = tender.quotation(_tender(), rollup=r)
    assert all("WP-07" not in str(l["itemCode"]) for l in q["lines"])


def test_declining_a_package_reduces_the_fee():
    full = tender.services_rollup(PKGS, A)
    less = tender.services_rollup(PKGS, A, config={"WP-07": {"include": False}})
    assert less["fee"] < full["fee"]
    assert less["cost"] < full["cost"]


def test_a_non_optional_package_cannot_be_switched_off():
    """Only what the client may decline is declinable — the core scope is not a toggle."""
    r = tender.services_rollup(PKGS, A, config={"WP-01": {"include": False}})
    assert "WP-01" in [p["code"] for p in r["packages"]]


# --- the quotation ----------------------------------------------------------------------------

def test_one_line_per_work_package_carrying_the_urs_reference():
    """The evaluator cross-checks the URS reference against their requirement spec; a services
    quotation that cannot be traced back to the URS is marked down whatever the price says."""
    r = tender.services_rollup(PKGS, A)
    q = tender.quotation(_tender(), rollup=r)
    assert q["lineCount"] == 3
    assert [l["itemCode"] for l in q["lines"]] == ["General", "URS-01", "URS-07"]
    assert all(l["unit"] == "package" for l in q["lines"])


def test_the_fee_and_the_expenses_stay_separable():
    """The client's own form asks for professional fee and travel & expenses in two columns."""
    r = tender.services_rollup(PKGS, A)
    q = tender.quotation(_tender(), rollup=r)
    for l in q["lines"]:
        assert l["professionalFee"] + l["expenses"] == l["net"], \
            "fee + expenses does not reconcile to the line price"


def test_the_quotation_reconciles():
    r = tender.services_rollup(PKGS, A)
    q = tender.quotation(_tender(), rollup=r)
    assert q["subtotal"] == sum(l["net"] for l in q["lines"])
    assert q["subtotal"] == r["fee"]
    assert q["cogs"] == r["cost"]
    assert q["subtotal"] - q["discount"] + q["vat"] == q["gross"]


def test_a_discount_reaches_a_services_quotation_too():
    r = tender.services_rollup(PKGS, A)
    full = tender.quotation(_tender(discountPct=0), rollup=r)
    cut = tender.quotation(_tender(discountPct=15), rollup=r)
    assert cut["gross"] < full["gross"]
    assert cut["subtotal"] - cut["discount"] + cut["vat"] == cut["gross"]


# --- the numbers a services business lives on -------------------------------------------------

def test_the_effective_day_rate_is_reported():
    """A consultancy that cannot say what it is really selling a day for cannot tell whether it is
    winning work or buying it."""
    r = tender.services_rollup(PKGS, A)
    assert r["effectiveDayRate"] == round(r["fee"] / r["days"])
    assert r["effectiveDayRate"] > max(tender.GRADE_RATE.values()) * 0.5


def test_duration_is_the_longest_package_not_the_sum():
    """Work packages overlap. Summing them would forecast an engagement three times its length."""
    r = tender.services_rollup(PKGS, A)
    assert r["durationMonths"] == 12
    assert r["durationMonths"] < sum(p["durationMonths"] for p in PKGS)


# --- cash flow --------------------------------------------------------------------------------

def test_each_package_spends_across_its_own_duration():
    """A two-month gap analysis smeared over an eighteen-month programme understates the early
    cash need, which is when a services business is most exposed."""
    r = tender.services_rollup(PKGS, A)
    cf = tender.cash_flow(_tender(durationMonths=12), tender.quotation(_tender(), rollup=r), rollup=r)
    by = {row["label"]: row for row in cf["outflows"]}
    wp01 = by["Facility & Engineering Assessment"]
    assert sum(1 for c in wp01["months"] if c) == 2, \
        "a 2-month package did not spend across exactly 2 months"


def test_the_cash_flow_reconciles_to_the_cost():
    r = tender.services_rollup(PKGS, A)
    q = tender.quotation(_tender(), rollup=r)
    cf = tender.cash_flow(_tender(), q, rollup=r)
    assert sum(sum(row["months"]) for row in cf["outflows"]) == r["cost"]


def test_the_pnl_runs_on_a_services_quotation():
    r = tender.services_rollup(PKGS, A)
    q = tender.quotation(_tender(), rollup=r)
    p = tender.pnl(q, _tender())
    assert p["revenue"] == q["net"]
    assert p["netProfit"] < p["ebit"] or p["ebit"] <= 0
    assert p["grossMarginPct"] > 0


# --- edges -------------------------------------------------------------------------------------

def test_a_package_with_no_effort_costs_nothing_and_is_flagged_at_issue():
    r = tender.services_rollup([{"id": "X", "code": "WP-X", "name": "Empty", "effort": []}], A)
    assert r["cost"] == 0
    q = tender.quotation(_tender(), rollup=r)
    assert any("no cost behind it" in w for w in tender.issue_check(_tender(), q)["warnings"])


def test_an_unknown_grade_does_not_silently_cost_zero_days():
    """An unknown grade has no rate, so it contributes nothing — the days must still be counted so
    the effective day rate exposes it rather than hiding it."""
    p = tender.package_cost({"effort": [{"grade": "WIZARD", "days": 5}]}, A)
    assert p["days"] == 5
    assert p["labour"] == 0


def test_the_footer_band_names_the_document_not_the_stationery():
    """It printed "LETTERHEAD" on every letter Humiley sends — the name of the paper, not of the
    document. Two of them side by side could not be told apart by looking. Derived from the
    SUBJECT because that is the one field somebody edits per document, so the band cannot drift
    from the letter's own heading."""
    assert tender.doc_kind({"subject": "Sales Quotation No. QT-1"}) == "Quotation"
    assert tender.doc_kind({"subject": "Proposal for EU-GMP readiness"}) == "Proposal"
    assert tender.doc_kind({"subject": "Budgetary Estimate — Block B"}) == "Budgetary Estimate"


def test_a_longer_kind_wins_over_the_shorter_one_inside_it():
    """"Revised Quotation" contains "Quotation"; first-match-wins on an unordered list would call
    a revision an original, which is exactly the distinction a customer needs from the footer."""
    assert tender.doc_kind({"subject": "Revised Quotation No. QT-2"}) == "Revised Quotation"
    assert tender.doc_kind({"subject": "Pro Forma Invoice 88"}) == "Pro Forma Invoice"


def test_an_explicit_kind_overrides_the_subject():
    assert tender.doc_kind({"subject": "Sales Quotation No. X",
                            "docKind": "Letter of Award"}) == "Letter of Award"


def test_an_unrecognised_subject_still_gets_a_real_word():
    """Never back to "LETTERHEAD", and never blank — a footer band with nothing in it reads as a
    rendering fault on a document going to a customer."""
    kind = tender.doc_kind({"subject": "Something nobody anticipated"})
    assert kind and kind.upper() != "LETTERHEAD"


def test_the_document_carries_the_kind_so_the_footer_need_not_derive_it():
    t = _tender(subject="Proposal for EU-GMP readiness")
    r = tender.services_rollup(PKGS, A)
    doc = tender.document(t, tender.quotation(t, rollup=r))
    assert doc["docKind"] == "Proposal"


def test_services_is_a_registered_costing_type():
    assert tender.SERVICES in tender.COSTING_TYPES
    assert len(tender.COSTING_TYPES) == 3


# --- what the quick-add form actually stores ---------------------------------------------------

def test_effort_can_arrive_as_the_flat_fields_the_form_produces():
    """The form renderer has no repeating-row control, so effort is entered a grade at a time.
    Both shapes must price identically, or the screen and the engine disagree."""
    listy = tender.package_cost({"effort": [{"grade": "SME", "days": 12},
                                            {"grade": "ENG", "days": 18}]}, A)
    flat = tender.package_cost({"daysSME": 12, "daysENG": 18}, A)
    assert flat["labour"] == listy["labour"]
    assert flat["days"] == listy["days"] == 30
    assert [e["grade"] for e in flat["effort"]] == ["SME", "ENG"]


def test_optional_reads_the_forms_select_rather_than_its_truthiness():
    """The select stores the string "No", and bool("No") is True — which would make every package
    optional. The same defect as one that shows at zero, arriving from the other direction."""
    assert tender.package_cost({"optional": "No"}, A)["optional"] is False
    assert tender.package_cost({"optional": ""}, A)["optional"] is False
    assert tender.package_cost({"optional": "Yes"}, A)["optional"] is True
    assert tender.package_cost({"optional": True}, A)["optional"] is True


def test_a_package_marked_no_cannot_be_declined():
    pkgs = [{"id": "A", "code": "WP-A", "name": "Core", "optional": "No", "daysSME": 5},
            {"id": "B", "code": "WP-B", "name": "Extra", "optional": "Yes", "daysSME": 5}]
    r = tender.services_rollup(pkgs, A, config={"WP-A": {"include": False},
                                                "WP-B": {"include": False}})
    assert [p["code"] for p in r["packages"]] == ["WP-A"]
