"""The deposit is a term of the PO and the contract, not a house rule.

Three shapes turn up on real jobs — a percentage, a stated sum straight off the purchase order, and
staged tranches — and all three have to survive the same recovery arithmetic downstream. The one
that used to be impossible is the stated sum: encoding a deposit as a percentage only would force
somebody to convert ₫200,000,000 into "20.3%" by hand, and the recovery would then be wrong by
whatever the rounding lost, for ever, because the balance never reaches zero.
"""
import pytest

import sales_contract as C


def _c(**kw):
    return dict({"value": 1_000_000_000, "retentionPct": 5, "warrantyMonths": 12,
                 "releaseRule": C.REL_WARRANTY_END, "recoveryRule": C.REC_PRORATA}, **kw)


# ── the three shapes ─────────────────────────────────────────────────────────────────────────────

def test_a_percentage_still_works_exactly_as_before():
    """Every contract already in the database has this shape. A migration that reinterpreted them
    would rewrite live balances."""
    s = C.advance_schedule(_c(advancePct=30))
    assert s["ok"] and s["total"] == 300_000_000
    assert [x["basis"] for x in s["tranches"]] == [C.ADV_PCT]
    assert C.advance_amount(_c(advancePct=30)) == 300_000_000


def test_a_stated_amount_off_the_purchase_order():
    s = C.advance_schedule(_c(advanceSchedule=[{"basis": C.ADV_FIXED, "value": 200_000_000,
                                                "label": "On signing"}]))
    assert s["ok"] and s["total"] == 200_000_000


def test_staged_tranches_add_up():
    s = C.advance_schedule(_c(advanceSchedule=[
        {"basis": C.ADV_PCT, "value": 20, "trigger": "On signing"},
        {"basis": C.ADV_PCT, "value": 10, "trigger": "On delivery of materials to site"}]))
    assert s["total"] == 300_000_000 and len(s["tranches"]) == 2


def test_a_percentage_and_a_stated_sum_can_be_mixed():
    """A PO that says "20% on signing plus ₫50,000,000 for the imported fan section" is a real PO."""
    s = C.advance_schedule(_c(advanceSchedule=[
        {"basis": C.ADV_PCT, "value": 20}, {"basis": C.ADV_FIXED, "value": 50_000_000}]))
    assert s["total"] == 250_000_000


def test_a_schedule_overrides_the_old_percentage_rather_than_adding_to_it():
    s = C.advance_schedule(_c(advancePct=30, advanceSchedule=[{"basis": C.ADV_FIXED, "value": 1_000}]))
    assert s["total"] == 1_000


def test_no_deposit_is_a_real_shape():
    s = C.advance_schedule(_c())
    assert s["ok"] and s["total"] == 0 and s["tranches"] == []
    assert "No deposit" in s["why"]


def test_an_empty_schedule_falls_back_to_the_percentage():
    """A saved-then-emptied list must not silently delete a deposit the contract still states."""
    assert C.advance_schedule(_c(advancePct=30, advanceSchedule=[]))["total"] == 300_000_000


# ── the share it recovers against ────────────────────────────────────────────────────────────────

def test_a_stated_sum_recovers_at_its_real_share_not_a_rounded_one():
    """₫200,000,000 on a ₫986,000,000 job is 20.28…%. Asking a person to round that into the
    contract is asking for a balance that never reaches zero."""
    c = _c(value=986_000_000, advanceSchedule=[{"basis": C.ADV_FIXED, "value": 200_000_000}])
    assert C.advance_pct_effective(c) == pytest.approx(20.2840, abs=0.0001)


def test_a_fixed_deposit_clears_exactly_when_the_job_does():
    """The whole point of pro-rata, and the thing a hand-rounded percentage breaks."""
    c = _c(value=986_000_000, advanceSchedule=[{"basis": C.ADV_FIXED, "value": 200_000_000}])
    st = {"advanceOutstanding": 200_000_000}
    for _ in range(4):
        r = C.application(c, 246_500_000, st)
        assert r["ok"] is True, r
        st = {"certifiedToDate": r["certifiedToDate"], "advanceOutstanding": r["advanceOutstanding"],
              "retentionHeld": r["retentionHeld"]}
    assert st["advanceOutstanding"] == 0


def test_a_staged_deposit_recovers_against_the_whole_of_it():
    c = _c(advanceSchedule=[{"basis": C.ADV_PCT, "value": 20}, {"basis": C.ADV_PCT, "value": 10}])
    r = C.application(c, 200_000_000, {"advanceOutstanding": 300_000_000})
    assert r["advanceRecovered"] == 60_000_000, "30% of the claim, not 20%"


# ── what it refuses ──────────────────────────────────────────────────────────────────────────────

def test_a_deposit_larger_than_the_job_is_refused():
    """Always a typo, and left alone it makes every claim recover more than it certifies."""
    s = C.advance_schedule(_c(advanceSchedule=[{"basis": C.ADV_FIXED, "value": 2_000_000_000}]))
    assert s["ok"] is False and "larger than the job" in s["why"]


def test_a_claim_against_an_impossible_deposit_refuses_rather_than_computing():
    r = C.application(_c(advanceSchedule=[{"basis": C.ADV_FIXED, "value": 2_000_000_000}]), 1_000)
    assert r["ok"] is False and "larger than the job" in r["why"]


def test_a_negative_tranche_is_refused():
    s = C.advance_schedule(_c(advanceSchedule=[{"basis": C.ADV_FIXED, "value": -1}]))
    assert s["ok"] is False and "pays the customer" in s["why"]


def test_an_unknown_basis_is_named_rather_than_assumed():
    s = C.advance_schedule(_c(advanceSchedule=[{"basis": "vibes", "value": 10}]))
    assert s["ok"] is False and "unknown basis" in s["why"]


def test_a_deposit_with_no_recovery_rule_still_refuses_and_now_says_the_amount():
    r = C.application(_c(recoveryRule=None, advanceSchedule=[{"basis": C.ADV_FIXED, "value": 200_000_000}]),
                      100_000_000)
    assert r["ok"] is False
    assert "₫200,000,000 deposit" in r["why"] and "recovery rule" in r["why"]


def test_the_refusals_are_written_in_dong():
    r = C.application(_c(advancePct=30), 1_200_000_000)
    assert "₫" in r["why"] and ".00" not in r["why"]
