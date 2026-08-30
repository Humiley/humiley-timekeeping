"""Quantity surveying — the five ways a valuation quietly tells you the wrong number.

Every test here is one of the module's stated rules, exercised at the point where the OBVIOUS
implementation gets it wrong and nothing looks broken:

  * an unpriced bill line valued at nil totals correctly and undercharges the client
  * over-measure clamped to the billed quantity hides a take-off error AND a legitimate remeasure
  * an instructed-but-unagreed variation put in the claim is money the client disputes
  * a pump claimed as material on site in March and measured in April is claimed twice
  * a submitted valuation recomputed from today's registers rewrites what was claimed

The last group checks the boundary: this module must NOT compute retention or advance recovery.
sales_contract does, and a second implementation is a second answer.
"""
import pytest

import qsurvey as qs
import sales_contract


# ── the bill ─────────────────────────────────────────────────────────────────────────────────────

def _bill():
    return [
        {"id": "h1", "kind": qs.HEADING, "section": "A", "desc": "Substructure"},
        {"id": "b1", "itemNo": "A.1", "desc": "Excavation", "unit": "m3",
         "billedQty": 100, "rate": 250_000},
        {"id": "b2", "itemNo": "A.2", "desc": "Concrete", "unit": "m3",
         "billedQty": 40, "rate": 1_800_000},
        {"id": "p1", "itemNo": "A.9", "desc": "Provisional sum — drainage",
         "kind": qs.PROVISIONAL, "rate": 200_000_000},
    ]


def test_a_heading_never_reaches_a_total():
    """A bill is not a flat list of priced rows. A heading with a stray rate on it must still be
    worth nothing, or every section title inflates the contract."""
    line = qs.boq_line({"id": "h", "kind": qs.HEADING, "rate": 999_999})
    assert line["value"] == 0.0
    assert qs.bill_total([{"id": "h", "kind": qs.HEADING, "rate": 999_999}])["total"] == 0.0


def test_an_unpriced_line_is_not_a_nil_line():
    """RULE 1. `_num` would make a blank rate 0.0 and the bill would total correctly while a real
    line quietly charged nothing. The line must come back unpriced and be NAMED."""
    t = qs.bill_total([{"id": "b1", "itemNo": "A.1", "desc": "Excavation", "billedQty": 100}])
    assert t["total"] == 0.0
    assert t["unpriced"] == [{"id": "b1", "itemNo": "A.1", "desc": "Excavation"}]


def test_the_bill_totals_measured_items_and_sums_separately():
    t = qs.bill_total(_bill())
    assert t["measuredTotal"] == 100 * 250_000 + 40 * 1_800_000
    assert t["sumsTotal"] == 200_000_000
    assert t["total"] == t["measuredTotal"] + t["sumsTotal"]
    assert t["unpriced"] == []


def test_a_provisional_sum_carried_in_the_rate_column_is_not_valued_at_nil():
    """The normal shape of a provisional sum is the amount in the rate column and a blank quantity.
    Multiplying by an implied zero would silently drop it out of the contract sum."""
    assert qs.boq_line({"id": "p", "kind": qs.PROVISIONAL, "rate": 200_000_000})["value"] \
        == 200_000_000


# ── measurement ──────────────────────────────────────────────────────────────────────────────────

def test_measured_to_date_is_the_sum_of_dated_records_not_a_stored_total():
    m = [{"id": "m1", "boqItemId": "b1", "qty": 30, "date": "2026-03-10"},
         {"id": "m2", "boqItemId": "b1", "qty": 25, "date": "2026-03-28"},
         {"id": "m3", "boqItemId": "b1", "qty": 40, "date": "2026-04-05"}]
    assert qs.measured_to_date(_bill(), m, "2026-03-31")["qty"]["b1"] == 55
    assert qs.measured_to_date(_bill(), m, "2026-04-30")["qty"]["b1"] == 95


def test_a_measurement_after_the_cutoff_belongs_to_the_next_valuation():
    """RULE 6. Recorded on the 3rd against a cut-off of the 31st, it is next month's."""
    m = [{"id": "m1", "boqItemId": "b1", "qty": 30, "date": "2026-04-03"}]
    assert qs.measured_value(_bill(), m, "2026-03-31")["total"] == 0


def test_an_undated_measurement_is_excluded_and_reported_not_silently_included():
    """A record with no date cannot be shown to fall before the cut-off. Including it on the
    strength of having no date is how work gets claimed in the wrong month."""
    r = qs.measured_value(_bill(), [{"id": "m1", "boqItemId": "b1", "qty": 30}], "2026-03-31")
    assert r["total"] == 0
    assert r["undatedExcluded"] == 1


def test_over_measure_is_reported_with_the_excess_and_still_counted():
    """RULE 2. Clamping to the billed quantity makes a take-off error invisible AND under-values a
    genuine remeasure. Both are wrong; the register says which lines and by how much."""
    m = [{"id": "m1", "boqItemId": "b1", "qty": 120, "date": "2026-03-10"}]
    r = qs.measured_value(_bill(), m, "2026-03-31")
    assert r["total"] == 120 * 250_000                       # counted, not clamped to 100
    assert len(r["overMeasured"]) == 1
    assert r["overMeasured"][0]["excessQty"] == 20
    assert r["overMeasured"][0]["excessValue"] == 20 * 250_000


def test_measured_work_against_an_unpriced_line_is_named_not_dropped_in_silence():
    """The worst case of rule 1: work is genuinely built, and there is no rate, so it is worth
    nothing on the certificate. That has to be loud."""
    bill = [{"id": "b9", "itemNo": "Z.1", "desc": "Ductwork", "billedQty": 50}]
    r = qs.measured_value(bill, [{"id": "m", "boqItemId": "b9", "qty": 20, "date": "2026-03-01"}],
                          "2026-03-31")
    assert r["total"] == 0
    assert r["measuredButUnpriced"][0]["itemNo"] == "Z.1"


def test_a_measurement_pointing_at_a_line_that_is_not_in_the_bill_is_reported():
    r = qs.measured_value(_bill(), [{"id": "m", "boqItemId": "gone", "qty": 5,
                                     "date": "2026-03-01"}], "2026-03-31")
    assert r["orphanMeasureIds"] == ["m"]


# ── variations ───────────────────────────────────────────────────────────────────────────────────

def test_only_an_agreed_variation_is_valued():
    """RULE 3. Instructed work with no agreed price is exposure, not a claim."""
    vs = [{"id": "v1", "voNo": "VO-001", "status": qs.V_INSTRUCTED, "estimatedValue": 90_000_000},
          {"id": "v2", "voNo": "VO-002", "status": qs.V_AGREED, "agreedValue": 50_000_000,
           "agreedOn": "2026-03-15"}]
    r = qs.variations_value(vs, "2026-03-31")
    assert r["total"] == 50_000_000
    assert r["exposure"] == 90_000_000
    assert [v["voNo"] for v in r["pending"]] == ["VO-001"]


def test_an_omission_reduces_the_valuation():
    vs = [{"id": "v", "status": qs.V_AGREED, "basis": qs.VB_OMISSION,
           "agreedValue": 20_000_000, "agreedOn": "2026-03-01"}]
    assert qs.variations_value(vs, "2026-03-31")["total"] == -20_000_000


def test_an_agreed_variation_with_no_agreed_value_is_a_gap_not_a_zero():
    vs = [{"id": "v", "voNo": "VO-007", "status": qs.V_AGREED, "agreedOn": "2026-03-01"}]
    r = qs.variations_value(vs, "2026-03-31")
    assert r["total"] == 0
    assert r["agreedButUnpriced"][0]["voNo"] == "VO-007"


def test_a_variation_agreed_after_the_cutoff_waits_for_the_next_valuation():
    vs = [{"id": "v", "status": qs.V_AGREED, "agreedValue": 10_000_000, "agreedOn": "2026-04-02"}]
    assert qs.variations_value(vs, "2026-03-31")["total"] == 0


def test_a_part_complete_variation_is_valued_pro_rata():
    vs = [{"id": "v", "status": qs.V_AGREED, "agreedValue": 100_000_000,
           "agreedOn": "2026-03-01", "pctComplete": 40}]
    assert qs.variations_value(vs, "2026-03-31")["total"] == 40_000_000


def test_the_variation_flow_has_no_dead_end_that_should_be_reachable():
    """A status machine written down is one that can be checked. Every open status must be able to
    reach agreement or withdrawal, or a variation can get stuck with no way out."""
    for st in qs.VARIATION_OPEN:
        seen, stack = set(), [st]
        while stack:
            cur = stack.pop()
            if cur in seen:
                continue
            seen.add(cur)
            stack.extend(qs.VARIATION_FLOW.get(cur, ()))
        assert seen & set(qs.VARIATION_TERMINAL), "%s cannot reach a terminal status" % st


# ── daywork and materials ────────────────────────────────────────────────────────────────────────

def test_only_approved_daywork_is_valued_and_signed_daywork_is_exposure():
    sheets = [{"id": "d1", "status": qs.DW_SIGNED, "value": 5_000_000, "date": "2026-03-02"},
              {"id": "d2", "status": qs.DW_APPROVED, "value": 8_000_000, "date": "2026-03-04"}]
    r = qs.daywork_value(sheets, "2026-03-31")
    assert r["total"] == 8_000_000
    assert r["exposure"] == 5_000_000


def test_material_built_into_the_works_leaves_the_valuation():
    """RULE 4, and the commonest double-count in the trade: a pump claimed as material on site in
    March and measured as installed work in April is claimed twice unless it drops out here."""
    mats = [{"id": "m", "desc": "AHU-01", "value": 300_000_000,
             "onSiteDate": "2026-03-05", "incorporatedDate": "2026-04-10"}]
    assert qs.materials_value(mats, "2026-03-31")["total"] == 300_000_000    # March: on site
    april = qs.materials_value(mats, "2026-04-30")
    assert april["total"] == 0                                               # April: built in
    assert april["droppedAsIncorporated"][0]["id"] == "m"


def test_materials_are_claimed_at_the_agreed_percentage_of_invoice_value():
    mats = [{"id": "m", "value": 100_000_000, "onSiteDate": "2026-03-01", "claimPct": 80}]
    assert qs.materials_value(mats, "2026-03-31")["total"] == 80_000_000


def test_a_material_percentage_above_a_hundred_cannot_over_claim():
    """An unclamped user percentage is one of this codebase's standing traps — 150% here would
    claim half as much again as the invoice."""
    mats = [{"id": "m", "value": 100_000_000, "onSiteDate": "2026-03-01", "claimPct": 150}]
    assert qs.materials_value(mats, "2026-03-31")["total"] == 100_000_000


# ── the valuation ────────────────────────────────────────────────────────────────────────────────

def _ctx(**kw):
    return dict({
        "boq": _bill(),
        "measures": [{"id": "m1", "boqItemId": "b1", "qty": 60, "date": "2026-03-10"},
                     {"id": "m2", "boqItemId": "b2", "qty": 20, "date": "2026-03-20"}],
        "variations": [{"id": "v", "status": qs.V_AGREED, "agreedValue": 50_000_000,
                        "agreedOn": "2026-03-15"}],
        "daywork": [{"id": "d", "status": qs.DW_APPROVED, "value": 8_000_000,
                     "date": "2026-03-04"}],
        "materials": [{"id": "mo", "value": 30_000_000, "onSiteDate": "2026-03-05"}],
        "cutoff": "2026-03-31",
        "previous": 0,
        "contractSum": 1_000_000_000,
    }, **kw)


def test_the_valuation_is_the_sum_of_its_four_parts():
    v = qs.valuation(_ctx())
    measured = 60 * 250_000 + 20 * 1_800_000
    assert v["grossToDate"] == measured + 50_000_000 + 8_000_000 + 30_000_000
    assert [b["amount"] for b in v["build"]] == [measured, 50_000_000, 8_000_000, 30_000_000]


def test_this_period_is_the_difference_from_the_previous_cutoff():
    v = qs.valuation(_ctx(previous=40_000_000))
    assert v["valuedThisPeriod"] == v["grossToDate"] - 40_000_000


def test_percent_complete_measures_against_the_REVISED_contract_sum():
    """Measuring against the original sum on a job carrying agreed variations reports a completion
    the site has not reached."""
    v = qs.valuation(_ctx())
    assert v["revisedContractSum"] == 1_050_000_000
    assert v["pctComplete"] == round(v["grossToDate"] / 1_050_000_000 * 100, 2)


def test_a_period_that_values_less_than_the_last_one_says_so():
    v = qs.valuation(_ctx(previous=500_000_000))
    assert v["valuedThisPeriod"] < 0
    assert any(w["code"] == "negative_period" for w in v["warnings"])


def test_valuing_past_the_revised_contract_sum_is_a_warning_not_a_clamp():
    v = qs.valuation(_ctx(contractSum=10_000_000))
    assert v["grossToDate"] > 10_000_000        # not clamped
    assert any(w["code"] == "over_contract" for w in v["warnings"])


def test_a_valuation_with_no_cutoff_says_it_is_including_everything():
    assert any(w["code"] == "no_cutoff" for w in qs.valuation(_ctx(cutoff=""))["warnings"])


def test_every_data_problem_reaches_the_warnings_list():
    """The valuation never refuses — a QS needs the figure AND the problems, not one instead of the
    other. So each problem has to actually arrive."""
    v = qs.valuation(_ctx(
        boq=_bill() + [{"id": "x", "itemNo": "X.1", "desc": "Unpriced", "billedQty": 10}],
        measures=[{"id": "m1", "boqItemId": "b1", "qty": 120, "date": "2026-03-01"},
                  {"id": "m2", "boqItemId": "x", "qty": 5, "date": "2026-03-01"},
                  {"id": "m3", "boqItemId": "ghost", "qty": 5, "date": "2026-03-01"},
                  {"id": "m4", "boqItemId": "b2", "qty": 5}],
        variations=[{"id": "v1", "voNo": "VO-1", "status": qs.V_AGREED},
                    {"id": "v2", "status": qs.V_INSTRUCTED, "estimatedValue": 1_000_000}],
        daywork=[{"id": "d", "status": qs.DW_SIGNED, "value": 1_000_000, "date": "2026-03-01"}]))
    codes = {w["code"] for w in v["warnings"]}
    assert {"unpriced_bill_lines", "measured_but_unpriced", "over_measured", "orphan_measurements",
            "undated_measurements", "agreed_variation_unpriced", "variation_exposure",
            "daywork_exposure"} <= codes


def test_the_valuation_never_states_retention_or_advance_recovery():
    """The boundary, asserted rather than described. Retention and advance recovery have exactly one
    implementation in this codebase and it is sales_contract.application(). A key appearing here
    would be a second answer to a question that must have one."""
    v = qs.valuation(_ctx())
    flat = repr(sorted(v.keys())).lower()
    assert "retention" not in flat
    assert "advance" not in flat
    assert "netpayable" not in flat


def test_the_valuation_hands_its_gross_figure_to_sales_contract_unchanged():
    """The join, exercised end to end: what QS values is what the contract module certifies."""
    v = qs.valuation(_ctx())
    c = {"value": 1_050_000_000, "advancePct": 30, "retentionPct": 5, "warrantyMonths": 12,
         "releaseRule": sales_contract.REL_WARRANTY_END,
         "recoveryRule": sales_contract.REC_PRORATA}
    app = sales_contract.application(c, v["valuedThisPeriod"],
                                     {"certifiedToDate": 0,
                                      "advanceOutstanding": 315_000_000, "retentionHeld": 0})
    assert app["ok"] is True
    assert app["certifiedThis"] == v["valuedThisPeriod"]
    assert app["retentionThis"] == round(v["valuedThisPeriod"] * 0.05, 2)


# ── cost value reconciliation ────────────────────────────────────────────────────────────────────

def test_margin_is_value_less_cost_accruals_and_provisions():
    r = qs.cvr({"valueToDate": 1_000_000_000, "costToDate": 700_000_000,
                "accruals": 50_000_000, "provisions": 30_000_000})
    assert r["trueCostToDate"] == 780_000_000
    assert r["margin"] == 220_000_000
    assert r["marginPct"] == 22.0


def test_a_loss_making_job_says_so():
    r = qs.cvr({"valueToDate": 100_000_000, "costToDate": 140_000_000})
    assert r["margin"] == -40_000_000
    assert any(w["code"] == "loss_making" for w in r["warnings"])


def test_eroding_margin_is_caught_against_the_previous_period():
    """A job rarely fails in one month. It gives up two points a month for five months and the
    first person to notice is the auditor."""
    r = qs.cvr({"valueToDate": 1_000_000_000, "costToDate": 900_000_000, "previousMargin": 18})
    assert r["marginDrift"] == -8.0
    assert any(w["code"] == "margin_eroding" for w in r["warnings"])


def test_cost_booked_with_nothing_valued_is_a_warning():
    r = qs.cvr({"valueToDate": 0, "costToDate": 200_000_000})
    assert any(w["code"] == "cost_without_value" for w in r["warnings"])


def test_a_forecast_loss_is_raised_before_the_final_account_finds_it():
    r = qs.cvr({"valueToDate": 500_000_000, "costToDate": 400_000_000,
                "forecastValue": 1_000_000_000, "forecastCost": 1_100_000_000})
    assert r["forecastMargin"] == -100_000_000
    assert any(w["code"] == "forecast_loss" for w in r["warnings"])


def test_a_missing_forecast_is_named_rather_than_reported_as_break_even():
    r = qs.cvr({"valueToDate": 500_000_000, "costToDate": 400_000_000})
    assert r["forecastMargin"] is None
    assert any(w["code"] == "no_forecast" for w in r["warnings"])


# ── the final account ────────────────────────────────────────────────────────────────────────────

def test_the_final_account_adds_up_and_states_the_balance_due():
    r = qs.final_account({
        "contractSum": 1_000_000_000,
        "variations": [{"id": "v", "status": qs.V_AGREED, "agreedValue": 80_000_000,
                        "agreedOn": "2026-06-01"}],
        "daywork": [{"id": "d", "status": qs.DW_APPROVED, "value": 12_000_000,
                     "date": "2026-05-01"}],
        "provisionalAdjustment": -20_000_000,
        "agreedClaims": 30_000_000,
        "certifiedToDate": 900_000_000})
    assert r["finalAccountSum"] == 1_102_000_000
    assert r["balanceDue"] == 202_000_000
    assert r["agreed"] is True


def test_an_unagreed_variation_stops_it_being_a_final_account():
    """A final account containing an unagreed figure is a claim. It may still be printed as a
    draft — but it must not call itself agreed."""
    r = qs.final_account({
        "contractSum": 1_000_000_000,
        "variations": [{"id": "v", "voNo": "VO-9", "status": qs.V_SUBMITTED,
                        "estimatedValue": 40_000_000}]})
    assert r["agreed"] is False
    assert any("VO-9" in b for b in r["blockedBy"])


def test_what_blocks_a_final_account_never_names_a_row_id():
    """This list is what a QS works through to close a job. "Variation pm_-778acacb is instructed"
    is not something anybody can act on — and the row id was exactly what it printed when a record
    had no number, which is the normal case for anything not typed into the form."""
    r = qs.final_account({
        "contractSum": 1_000_000_000,
        "variations": [{"id": "pm_-778acacb", "title": "Relocate chilled water risers",
                        "status": qs.V_INSTRUCTED, "estimatedValue": 96_000_000},
                       {"id": "pm_-0badc0de", "status": qs.V_PRICED}],
        "daywork": [{"id": "pm_-315639b6", "status": qs.DW_SIGNED, "value": 7_200_000,
                     "date": "2026-03-19", "desc": "Standing time, power outage"}]})
    joined = " ".join(r["blockedBy"])
    for rid in ("pm_-778acacb", "pm_-0badc0de", "pm_-315639b6"):
        assert rid not in joined, "the blocker list printed a row id: %s" % joined
    assert "Relocate chilled water risers" in joined
    assert "Standing time" in joined
    assert "an unnumbered variation" in joined


def test_the_final_account_does_not_net_off_retention():
    """Retention is held, not deducted. Netting it off here would shrink the agreed final sum by
    5% and leave nothing saying what is still owed."""
    r = qs.final_account({"contractSum": 1_000_000_000, "certifiedToDate": 0})
    assert r["finalAccountSum"] == 1_000_000_000
    assert "retention" in r["retentionNote"].lower()


def test_a_missing_contract_sum_blocks_rather_than_totalling_from_zero():
    r = qs.final_account({"variations": [], "certifiedToDate": 500_000_000})
    assert r["finalAccountSum"] is None
    assert r["agreed"] is False


# ── the refusals ─────────────────────────────────────────────────────────────────────────────────

def test_the_module_names_what_it_will_not_decide():
    joined = " ".join(qs.UNRESOLVED).lower()
    assert "fluctuation" in joined
    assert "liquidated damages" in joined
    assert len(qs.UNRESOLVED) >= 3
