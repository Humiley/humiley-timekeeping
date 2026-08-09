"""The contract — advance recovery, retention, and the tax question that must refuse.

These are the two mechanisms this company loses money through quietly. An advance treated as a
payment makes the early claims look settled and the final account short; retention netted off as a
discount shrinks the contract by 5% and nobody notices until the release is due and there is no
record of what is owed.

The last group is the important one: the module must REFUSE to state a VAT figure, by name, rather
than choose a Vietnamese tax treatment it is not entitled to choose.
"""
import pytest

import sales_contract as C


def _c(**kw):
    return dict({"value": 1_000_000_000, "advancePct": 30, "retentionPct": 5,
                 "warrantyMonths": 12, "releaseRule": C.REL_WARRANTY_END,
                 "recoveryRule": C.REC_PRORATA}, **kw)


# ── the terms ────────────────────────────────────────────────────────────────────────────────────

def test_the_advance_is_a_share_of_the_contract():
    assert C.advance_amount(_c()) == 300_000_000


def test_retention_is_capped_so_an_overrunning_job_stops_withholding():
    """Without the ceiling, a contract that certifies past its value keeps withholding past what was
    agreed."""
    assert C.retention_cap(_c()) == 50_000_000


def test_a_contract_with_no_advance_and_no_retention_is_a_real_shape():
    t = C.terms({"value": 100})
    assert t["advancePct"] == 0 and t["retentionPct"] == 0


def test_a_missing_rule_is_never_defaulted():
    """How the advance winds down and when retention comes back are the contract's to state."""
    t = C.terms({"value": 100, "advancePct": 30})
    assert t["recoveryRule"] is None and t["releaseRule"] is None


# ── one claim ────────────────────────────────────────────────────────────────────────────────────

def test_a_first_claim_deducts_recovery_and_retention():
    r = C.application(_c(), 200_000_000)
    assert r["ok"] is True
    assert r["advanceRecovered"] == 60_000_000      # 30% of the claim
    assert r["retentionThis"] == 10_000_000         # 5% of the claim
    assert r["netPayable"] == 130_000_000


def test_the_balances_carry_forward():
    a = C.application(_c(), 200_000_000)
    b = C.application(_c(), 300_000_000, {"certifiedToDate": a["certifiedToDate"],
                                          "advanceOutstanding": a["advanceOutstanding"],
                                          "retentionHeld": a["retentionHeld"]})
    assert b["certifiedToDate"] == 500_000_000
    assert b["advanceOutstanding"] == 300_000_000 - 60_000_000 - 90_000_000
    assert b["retentionHeld"] == 25_000_000


def test_the_advance_clears_exactly_when_the_job_does_on_a_prorata_rule():
    """The point of pro-rata: the advance winds down at the same pace as the work."""
    st = {}
    for _ in range(4):
        r = C.application(_c(), 250_000_000, st)
        assert r["ok"] is True, r
        st = {"certifiedToDate": r["certifiedToDate"], "advanceOutstanding": r["advanceOutstanding"],
              "retentionHeld": r["retentionHeld"]}
    assert st["advanceOutstanding"] == 0
    assert st["retentionHeld"] == 50_000_000


def test_recovery_never_exceeds_what_is_still_outstanding():
    r = C.application(_c(), 200_000_000, {"advanceOutstanding": 10_000_000})
    assert r["advanceRecovered"] == 10_000_000
    assert r["advanceOutstanding"] == 0


def test_retention_stops_at_the_cap():
    r = C.application(_c(), 200_000_000, {"retentionHeld": 45_000_000})
    assert r["retentionThis"] == 5_000_000, "only the 5m of headroom left under the 50m cap"
    assert r["retentionHeld"] == 50_000_000


def test_a_deferred_recovery_rule_holds_off_until_the_job_is_far_enough_along():
    c = _c(recoveryRule=C.REC_FROM_PCT, recoveryFromPct=50)
    early = C.application(c, 200_000_000)
    assert early["advanceRecovered"] == 0, "20% complete — mobilisation cash left alone"
    later = C.application(c, 400_000_000, {"certifiedToDate": 200_000_000,
                                           "advanceOutstanding": 300_000_000})
    assert later["advanceRecovered"] > 0


def test_certifying_past_the_contract_value_is_refused_and_says_so():
    """A variation raises the value. Silently certifying past it is how a contract quietly grows."""
    r = C.application(_c(), 1_200_000_000)
    assert r["ok"] is False and "Raise a variation" in r["why"]


def test_a_negative_certification_is_refused_for_the_RIGHT_reason():
    """Without its own guard a negative still gets refused — by the deductions-exceed-the-claim
    branch, which tells the user to "reduce the recovery on this claim" when the real problem is
    that they typed a minus sign. A refusal that names the wrong cause sends somebody to fix the
    wrong thing."""
    r = C.application(_c(), -1)
    assert r["ok"] is False
    assert "credit note" in r["why"], r["why"]


def test_a_claim_whose_deductions_exceed_it_refuses_rather_than_paying_a_negative():
    c = _c(recoveryRule=C.REC_MANUAL)
    r = C.application(c, 10_000_000, {"recoverNow": 50_000_000})
    assert r["ok"] is False and "exceed" in r["why"]


def test_a_manual_recovery_still_cannot_exceed_the_outstanding_balance():
    c = _c(recoveryRule=C.REC_MANUAL)
    r = C.application(c, 200_000_000, {"recoverNow": 999_000_000, "advanceOutstanding": 40_000_000})
    assert r["advanceRecovered"] == 40_000_000


def test_the_statement_reads_like_the_claim_a_person_signs():
    r = C.application(_c(), 200_000_000)
    assert "certified" in r["statement"] and "advance recovery" in r["statement"]
    assert "retention" in r["statement"] and "payable" in r["statement"]


# ── the rules that may not be invented ───────────────────────────────────────────────────────────

def test_an_advance_with_no_recovery_rule_refuses_to_compute():
    r = C.application(_c(recoveryRule=None), 100_000_000)
    assert r["ok"] is False and "recovery rule" in r["why"]


def test_retention_with_no_release_rule_refuses_to_compute():
    r = C.application(_c(releaseRule=None), 100_000_000)
    assert r["ok"] is False and "when it comes back" in r["why"]


def test_a_contract_with_neither_computes_happily():
    """Not every job has an advance or retention; those are real shapes, not missing data."""
    r = C.application({"value": 100_000_000}, 50_000_000)
    assert r["ok"] is True and r["netPayable"] == 50_000_000


# ── the final account ────────────────────────────────────────────────────────────────────────────

def test_the_final_account_names_the_retention_still_held():
    f = C.final_settlement(_c(), {"certifiedToDate": 1_000_000_000, "advanceOutstanding": 0,
                                  "retentionHeld": 50_000_000})
    assert f["retentionToRelease"] == 50_000_000 and f["clean"] is True


def test_an_advance_that_never_cleared_is_reported_not_written_off():
    """It is money already paid for work. Invisible is how it gets written off by accident."""
    f = C.final_settlement(_c(), {"certifiedToDate": 1_000_000_000, "advanceOutstanding": 20_000_000,
                                  "retentionHeld": 50_000_000})
    assert f["clean"] is False
    assert any("never recovered" in i for i in f["issues"])


def test_certifying_less_than_the_contract_is_flagged_at_closeout():
    f = C.final_settlement(_c(), {"certifiedToDate": 900_000_000, "advanceOutstanding": 0,
                                  "retentionHeld": 45_000_000})
    assert any("against a contract value" in i for i in f["issues"])


# ── the tax treatment this module refuses to choose ──────────────────────────────────────────────

def test_no_vat_figure_can_be_stated_until_the_tax_points_are_recorded():
    """Guessing produces a confident wrong number on a document that goes to a customer AND into a
    tax return."""
    v = C.vat_ready(_c())
    assert v["ready"] is False
    assert {m["key"] for m in v["missing"]} == {"retentionTaxPoint", "advanceTaxPoint"}
    assert "must not choose" in v["why"]


def test_recording_the_answers_at_company_level_unblocks_every_contract():
    v = C.vat_ready(_c(), {"retentionTaxPoint": "at_acceptance", "advanceTaxPoint": "on_receipt"})
    assert v["ready"] is True


def test_a_contract_may_override_the_company_answer():
    v = C.vat_ready(_c(retentionTaxPoint="at_release", advanceTaxPoint="on_certification"))
    assert v["ready"] is True


def test_a_half_answered_setting_is_still_a_refusal():
    v = C.vat_ready(_c(), {"advanceTaxPoint": "on_receipt"})
    assert v["ready"] is False and [m["key"] for m in v["missing"]] == ["retentionTaxPoint"]


def test_it_says_who_decides_rather_than_leaving_somebody_to_guess():
    assert "accountant" in C.vat_ready(_c())["whoDecides"]


def test_every_claim_states_that_it_is_ex_vat():
    """The commercial arithmetic is certain; the tax on it is not, and the document must not blur
    the two."""
    assert "exclusive of VAT" in C.application(_c(), 100_000_000)["taxNote"]


def test_the_open_questions_travel_with_the_module():
    assert {u["topic"] for u in C.UNRESOLVED} >= {"The retention tax point", "VAT on an advance"}
