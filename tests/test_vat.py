"""VAT: the rate and the base are FILLED IN, never chosen by this code.

The earlier behaviour — refuse to state any VAT figure at all — was only half right. It was right
that the portal must not CHOOSE a Vietnamese tax treatment; it was wrong that there was nowhere for
a person to choose one, which left a real question permanently unanswerable and a real number
permanently missing from every claim.

The tests below are mostly about the seam between those two halves: what is offered, what is
computed once somebody chooses, what is still refused, and how you find out a year later why a
particular claim was 8%.
"""
import pytest

import vat


def _claim(**kw):
    return dict(kw)


# ── what is offered, and what is never assumed ──────────────────────────────────────────────────

def test_the_rates_a_vietnamese_seller_actually_picks_from_are_all_offered():
    """8% has run alongside 10% under successive reduction resolutions, 5% applies to some
    supplies, and 0% is exports and export-processing zones."""
    assert set(vat.RATE_VALUES) == {0, 5, 8, 10}


def test_no_rate_is_a_default():
    r = vat.resolve()
    assert r["set"] is False and r["rate"] is None


def test_nothing_recorded_anywhere_says_so_and_says_where_to_fix_it():
    r = vat.resolve()
    assert "Company settings" in r["why"]


def test_a_rate_that_is_not_a_real_rate_is_refused_rather_than_clamped():
    """1.0 typed instead of 10 would otherwise produce a plausible, tiny, wrong tax line."""
    assert vat.rate_ok(10) and vat.rate_ok(8) and vat.rate_ok(0)
    assert not vat.rate_ok(1) and not vat.rate_ok(12) and not vat.rate_ok("ten")


def test_not_a_vat_supply_is_a_choice_not_a_blank():
    assert vat.rate_ok(vat.NOT_APPLICABLE)


# ── VAT on WHAT — the question a single rate box cannot ask ─────────────────────────────────────

def test_the_two_bases_differ_by_the_recovery_and_the_retention():
    """On a ₫200m claim with a 30% advance and 5% retention that is ₫7m of tax, every month."""
    s = {"vatRate": 10, "vatBase": vat.BASE_CERTIFIED}
    on_certified = vat.compute(200_000_000, 130_000_000, settings=s)
    s2 = dict(s, vatBase=vat.BASE_NET)
    on_net = vat.compute(200_000_000, 130_000_000, settings=s2)
    assert on_certified["vat"] == 20_000_000
    assert on_net["vat"] == 13_000_000
    assert on_certified["vat"] - on_net["vat"] == 7_000_000


def test_the_gross_is_always_the_net_payable_plus_the_tax():
    """Whatever the tax is computed ON, what the customer pays is the net plus it."""
    out = vat.compute(200_000_000, 130_000_000,
                      settings={"vatRate": 10, "vatBase": vat.BASE_CERTIFIED})
    assert out["gross"] == 150_000_000


def test_an_unknown_base_is_not_a_base():
    assert vat.resolve(settings={"vatRate": 10, "vatBase": "whatever"})["set"] is False


# ── where the answer came from ──────────────────────────────────────────────────────────────────

def test_the_claim_beats_the_contract_beats_the_company():
    out = vat.resolve(claim={"vatRate": 8}, contract={"vatRate": 10}, settings={"vatRate": 0,
                                                                               "vatBase": vat.BASE_NET})
    assert out["rate"] == 8 and out["rateFrom"] == "claim"
    assert out["base"] == vat.BASE_NET and out["baseFrom"] == "company"


def test_the_provenance_travels_with_the_answer():
    """"Why is this one 8%" is a question somebody asks a year later, and "that claim says so" and
    "the company default says so" are different answers with different fixes."""
    out = vat.resolve(contract={"vatRate": 8, "vatBase": vat.BASE_CERTIFIED})
    assert out["rateFrom"] == "contract" and "contract" in out["why"]


def test_a_split_source_is_stated_as_a_split():
    out = vat.resolve(claim={"vatRate": 8}, settings={"vatBase": vat.BASE_NET})
    assert "respectively" in out["why"]


def test_a_zero_rate_on_the_claim_is_not_treated_as_unset():
    """0% is a real answer — exports and EPZ customers — and falling through to the company default
    would silently tax an export."""
    out = vat.resolve(claim={"vatRate": 0}, settings={"vatRate": 10, "vatBase": vat.BASE_NET})
    assert out["rate"] == 0 and out["rateFrom"] == "claim"


# ── the arithmetic, once somebody has chosen ────────────────────────────────────────────────────

def test_it_computes_rather_than_refusing_once_a_rate_exists():
    out = vat.compute(200_000_000, 130_000_000,
                      settings={"vatRate": 8, "vatBase": vat.BASE_CERTIFIED})
    assert out["ok"] is True and out["vat"] == 16_000_000


def test_it_refuses_ONLY_because_nobody_stated_one():
    out = vat.compute(200_000_000, 130_000_000)
    assert out["ok"] is False and out["vat"] == 0
    assert out["gross"] == 130_000_000, "with no tax line the claim is still worth its net"


def test_an_unset_claim_carries_NO_STATEMENT_ABOUT_TAX():
    """The dangerous shape, and the one the numbers alone cannot catch: with no rate recorded the
    arithmetic still produces ₫0, so a claim would read "0% VAT on ₫130,000,000 = ₫0" — a confident
    statement that nothing is taxable, made on behalf of a company that has not said so."""
    out = vat.compute(200_000_000, 130_000_000)
    assert "statement" not in out
    assert "Nobody has recorded" in out["why"]


def test_not_a_vat_supply_charges_nothing_and_says_so():
    out = vat.compute(200_000_000, 130_000_000,
                      settings={"vatRate": vat.NOT_APPLICABLE, "vatBase": vat.BASE_NET})
    assert out["ok"] is True and out["vat"] == 0
    assert "Not a VAT supply" in out["statement"]


def test_the_statement_is_written_in_dong():
    out = vat.compute(200_000_000, 130_000_000,
                      settings={"vatRate": 10, "vatBase": vat.BASE_CERTIFIED})
    assert "₫20,000,000" in out["statement"] and ".00" not in out["statement"]


# ── the settings review ─────────────────────────────────────────────────────────────────────────

def test_an_empty_company_is_told_the_four_things_to_record():
    r = vat.settings_review({})
    assert r["complete"] is False
    assert {m["key"] for m in r["missing"]} == {"vatRate", "vatBase",
                                               "retentionTaxPoint", "advanceTaxPoint"}


def test_recording_all_four_completes_it():
    r = vat.settings_review({"vatRate": 10, "vatBase": vat.BASE_CERTIFIED,
                             "retentionTaxPoint": "at_acceptance",
                             "advanceTaxPoint": "on_receipt"})
    assert r["complete"] is True and "claims carry a VAT line" in r["why"]


def test_a_nonsense_default_rate_is_reported_as_missing_not_accepted():
    """Otherwise every contract in the company silently inherits a rate that is not a rate."""
    r = vat.settings_review({"vatRate": 1, "vatBase": vat.BASE_NET,
                             "retentionTaxPoint": "at_release", "advanceTaxPoint": "on_receipt"})
    assert r["complete"] is False and [m["key"] for m in r["missing"]] == ["vatRate"]


def test_an_incomplete_setting_stops_the_TAX_LINE_not_the_screen():
    """A blank here is a smaller and much more honest failure than a whole screen that will not
    load — which is what the old hard refusal amounted to."""
    r = vat.settings_review({"vatRate": 10})
    assert r["complete"] is False
    assert "Claims stay ex-VAT" in r["why"]


def test_it_says_who_decides():
    assert "accountant" in vat.settings_review({})["whoDecides"]


def test_both_tax_point_questions_offer_their_real_options():
    assert [o["code"] for o in vat.TAX_POINTS["retentionTaxPoint"]["options"]] == \
        ["at_acceptance", "at_release"]
    assert [o["code"] for o in vat.TAX_POINTS["advanceTaxPoint"]["options"]] == \
        ["on_receipt", "on_certification"]


def test_every_question_is_asked_in_vietnamese_too():
    """Including the line that explains WHY it matters — that was the last English leak on an
    otherwise Vietnamese screen, and it is the sentence that makes somebody answer."""
    for k, q in vat.TAX_POINTS.items():
        assert q["questionVn"] and q["questionVn"] != q["question"], k
        assert q["whyVn"] and q["whyVn"] != q["why"], k
        for o in q["options"]:
            assert o["labelVn"], (k, o["code"])


def test_the_module_still_refuses_to_issue_an_invoice_and_says_so():
    assert any("signed XML" in u["question"] for u in vat.UNRESOLVED)
