# -*- coding: utf-8 -*-
"""Two advance-recovery rules that could not do what they are named after.

The contract terms offer three ways to wind a deposit down. Two of them were unreachable — not
broken logic, but a rule whose input had no field anywhere in the portal:

  "Nothing until a set % complete"  reads terms["recoveryFromPct"]. There was no ct-recoveryFromPct
                                    input, so it was always 0, `pct_complete >= 0` was always true,
                                    and the rule recovered from claim #1 — behaving exactly like the
                                    prorata rule it exists to differ from. The customer is paid less
                                    than the contract says from the first certificate, on a document
                                    a director signs.

  "Decided per claim"               reads state["recoverNow"]. _contract_state() built a dict of
                                    three keys and that was not one of them, so `r2(None)` -> 0.0 on
                                    every claim, for the life of the job, while the contract screen
                                    said the advance balance must still reach zero. The first sign
                                    of trouble is the final account refusing to close, months later,
                                    when the cash is gone.

Both now REFUSE rather than quietly behave as a different rule. That is the same choice the module
already makes for an unrecognised rule, and for the reason its comment gives: a claim computed on an
invented recovery rule is a number somebody signs and the customer disputes.
"""
import sales_contract as C


def _contract(**kw):
    """An active contract with a 20% deposit, so there is always something to recover."""
    c = {"value": 1_000_000_000, "retentionPct": 0, "releaseRule": "",
         # `value`, not `pct` — the tranche shape is {basis, value}. Getting this wrong makes the
         # deposit ₫0, and a ₫0 deposit is exempt from the very guards under test: the fixture would
         # have quietly disarmed them while every assertion still ran.
         "advanceSchedule": [{"label": "On signing", "basis": "pct", "value": 20}],
         "recoveryRule": C.REC_PRORATA}
    c.update(kw)
    return c


def _state(**kw):
    st = {"certifiedToDate": 0, "advanceOutstanding": 200_000_000, "retentionHeld": 0}
    st.update(kw)
    return st


# ── "Nothing until a set % complete" ────────────────────────────────────────────────────────────
def test_from_pct_with_no_threshold_is_refused_not_treated_as_prorata():
    c = _contract(recoveryRule=C.REC_FROM_PCT)          # no recoveryFromPct at all — the old state
    r = C.application(c, 100_000_000, _state())
    assert not r["ok"], "it computed a claim on a threshold nobody set"
    assert "threshold" in r["why"].lower(), r["why"]


def test_a_zero_threshold_is_refused_too():
    """0 is not 'recover from the start' — that rule exists and is called prorata. It is the value a
    field that never existed leaves behind."""
    r = C.application(_contract(recoveryRule=C.REC_FROM_PCT, recoveryFromPct=0), 100_000_000, _state())
    assert not r["ok"]


def test_with_a_real_threshold_it_recovers_nothing_below_it():
    c = _contract(recoveryRule=C.REC_FROM_PCT, recoveryFromPct=50)
    r = C.application(c, 100_000_000, _state())          # 10% complete
    assert r["ok"], r.get("why")
    assert r["advanceRecovered"] == 0, "10%% complete is below the 50%% threshold"


def test_and_recovers_once_the_works_pass_it():
    c = _contract(recoveryRule=C.REC_FROM_PCT, recoveryFromPct=50)
    r = C.application(c, 600_000_000, _state())          # 60% complete
    assert r["ok"], r.get("why")
    assert r["advanceRecovered"] > 0, "past the threshold the deposit must start winding down"


def test_the_threshold_actually_changes_the_answer():
    """Two thresholds either side of the same claim. If both gave the same figure the tests above
    could pass on a constant."""
    st, this = _state(), 400_000_000                     # 40% complete
    below = C.application(_contract(recoveryRule=C.REC_FROM_PCT, recoveryFromPct=30), this, st)
    above = C.application(_contract(recoveryRule=C.REC_FROM_PCT, recoveryFromPct=70), this, st)
    assert below["ok"] and above["ok"]
    assert below["advanceRecovered"] > 0 and above["advanceRecovered"] == 0


# ── "Decided per claim" ─────────────────────────────────────────────────────────────────────────
def test_manual_with_nobody_naming_an_amount_is_refused():
    r = C.application(_contract(recoveryRule=C.REC_MANUAL), 100_000_000, _state())
    assert not r["ok"], "it recovered nothing and said nothing — the whole defect"
    assert "how much" in r["why"].lower() or "amount" in r["why"].lower(), r["why"]


def test_an_explicit_zero_is_a_real_answer_and_is_honoured():
    """'Recover nothing this time' is a legitimate decision on this rule. It must be distinguishable
    from silence, or the refusal above just becomes a nuisance people work around."""
    r = C.application(_contract(recoveryRule=C.REC_MANUAL), 100_000_000, _state(recoverNow=0))
    assert r["ok"], r.get("why")
    assert r["advanceRecovered"] == 0


def test_a_named_amount_is_recovered():
    r = C.application(_contract(recoveryRule=C.REC_MANUAL), 100_000_000, _state(recoverNow=30_000_000))
    assert r["ok"], r.get("why")
    assert r["advanceRecovered"] == 30_000_000
    assert r["advanceOutstanding"] == 170_000_000, "the balance must move by what was recovered"


def test_it_still_cannot_recover_more_than_is_outstanding():
    """The guard that already existed must survive the change — the caller says, and the balance
    still binds."""
    r = C.application(_contract(recoveryRule=C.REC_MANUAL), 500_000_000,
                      _state(recoverNow=999_000_000, advanceOutstanding=40_000_000))
    assert r["ok"], r.get("why")
    assert r["advanceRecovered"] == 40_000_000
    assert r["advanceOutstanding"] == 0


def test_a_contract_with_no_deposit_left_does_not_demand_an_amount():
    """Once the advance is fully recovered there is nothing to decide, so the refusal must lift —
    otherwise the last claims on every manual contract become unraisable."""
    r = C.application(_contract(recoveryRule=C.REC_MANUAL), 100_000_000, _state(advanceOutstanding=0))
    assert r["ok"], r.get("why")
    assert r["advanceRecovered"] == 0


# ── the rules stay distinguishable ──────────────────────────────────────────────────────────────
def test_prorata_is_untouched():
    """The one rule that always worked must give exactly what it gave before."""
    r = C.application(_contract(recoveryRule=C.REC_PRORATA), 100_000_000, _state())
    assert r["ok"] and r["advanceRecovered"] == 20_000_000     # 20% of the claim


def test_from_pct_past_its_threshold_matches_prorata():
    """Above the threshold the two rules agree — which is precisely why a 0 threshold hid the bug."""
    pro = C.application(_contract(recoveryRule=C.REC_PRORATA), 600_000_000, _state())
    frm = C.application(_contract(recoveryRule=C.REC_FROM_PCT, recoveryFromPct=50), 600_000_000, _state())
    assert pro["advanceRecovered"] == frm["advanceRecovered"]
