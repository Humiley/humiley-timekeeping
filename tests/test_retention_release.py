"""Retention: the single most-forgotten receivable a contractor has.

It is withheld a slice at a time across a year of claims and then falls due once, quietly, twelve
months after everybody stopped thinking about the job. Nothing chases it, because nothing knows when
it is due — and 5% of every contract is not a rounding error for a company this size.

The two refusals are the point. Without a release rule nothing can be said. Without an ACCEPTANCE
date the clock has not started, and dating it off the contract signature or the last claim would put
a real receivable on a day nobody agreed to.
"""
import pytest

import sales_contract as C


def _c(**kw):
    return dict({"value": 1_000_000_000, "advancePct": 30, "retentionPct": 5, "warrantyMonths": 12,
                 "releaseRule": C.REL_WARRANTY_END, "recoveryRule": C.REC_PRORATA,
                 "acceptedOn": "2026-01-15", "retentionHeld": 50_000_000,
                 "retentionReleased": 0}, **kw)


# ── the clock ────────────────────────────────────────────────────────────────────────────────────

def test_the_whole_retention_falls_due_at_the_end_of_the_warranty():
    r = C.retention_release(_c(), None, "2026-08-09")
    assert [t["dueOn"] for t in r["tranches"]] == ["2027-01-15"]
    assert r["tranches"][0]["amount"] == 50_000_000
    assert r["dueNow"] == 0, "not due for another five months"


def test_the_half_rule_splits_it_into_two_dated_tranches():
    r = C.retention_release(_c(releaseRule=C.REL_HALF_AT_COMPLETION), None, "2026-08-09")
    assert [(t["dueOn"], t["amount"]) for t in r["tranches"]] == \
        [("2026-01-15", 25_000_000), ("2027-01-15", 25_000_000)]
    assert r["dueNow"] == 25_000_000


def test_a_tranche_past_its_date_is_flagged_overdue():
    r = C.retention_release(_c(), None, "2027-06-01")
    assert r["tranches"][0]["overdue"] is True
    assert r["dueNow"] == 50_000_000


def test_the_warranty_lands_on_a_real_date_when_the_month_is_shorter():
    """31 January + 12 months is fine; + 1 month is 28 February, not 3 March. A due date that does
    not exist has to land somewhere, and landing EARLY would make a release look due before it is."""
    r = C.retention_release(_c(acceptedOn="2026-01-31", warrantyMonths=1), None, "2026-01-01")
    assert r["tranches"][0]["dueOn"] == "2026-02-28"


def test_a_leap_february_is_not_shortened_to_the_28th():
    r = C.retention_release(_c(acceptedOn="2028-01-31", warrantyMonths=1), None, "2028-01-01")
    assert r["tranches"][0]["dueOn"] == "2028-02-29"


# ── what has already come back ──────────────────────────────────────────────────────────────────

def test_a_release_is_applied_to_the_earliest_tranche_first():
    """Spreading a part-release evenly would make the later tranche look partly settled before its
    own date, and hide the fact that the first one is short."""
    r = C.retention_release(_c(releaseRule=C.REL_HALF_AT_COMPLETION, retentionReleased=25_000_000),
                            None, "2026-08-09")
    assert r["tranches"][0]["outstanding"] == 0
    assert r["tranches"][1]["outstanding"] == 25_000_000
    assert r["dueNow"] == 0


def test_a_fully_released_retention_is_finished():
    r = C.retention_release(_c(retentionReleased=50_000_000), None, "2030-01-01")
    assert r["outstanding"] == 0 and r["dueNow"] == 0
    assert "No retention" in r["why"]


def test_a_contract_that_never_withheld_anything_is_a_real_shape():
    r = C.retention_release({"value": 100, "retentionHeld": 0}, None, "2026-08-09")
    assert r["status"] == "ok" and r["outstanding"] == 0


# ── the two refusals ────────────────────────────────────────────────────────────────────────────

def test_with_no_release_rule_nothing_can_be_said():
    r = C.retention_release(_c(releaseRule=None), None, "2026-08-09")
    assert r["status"] == C.INDETERMINATE
    assert "does not say when it comes back" in r["why"]
    assert r["tranches"] == []


def test_with_no_acceptance_date_the_clock_has_not_started():
    """The warranty runs from the works being ACCEPTED. Dating it off the contract or the last claim
    would put a real receivable on a day nobody agreed to."""
    r = C.retention_release(_c(acceptedOn=""), None, "2026-08-09")
    assert r["status"] == C.INDETERMINATE
    assert "acceptance" in r["why"].lower()
    assert r["dueNow"] == 0


def test_a_refusal_still_states_the_amount_at_stake():
    """"Something is wrong" gets ignored. "₫50,000,000 is being held" gets acted on."""
    for r in (C.retention_release(_c(releaseRule=None), None, "2026-08-09"),
              C.retention_release(_c(acceptedOn=""), None, "2026-08-09")):
        assert "₫50,000,000" in r["why"]


def test_a_garbled_acceptance_date_does_not_produce_a_garbled_due_date():
    r = C.retention_release(_c(acceptedOn="not-a-date"), None, "2026-08-09")
    assert r["tranches"][0]["dueOn"] == ""
    assert r["dueNow"] == 0, "an unknown due date is never 'due now'"


def test_the_figures_are_written_in_dong():
    assert ".00" not in C.retention_release(_c(), None, "2026-08-09")["why"]
