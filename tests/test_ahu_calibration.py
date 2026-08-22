"""Calibration: whether the thing that measured the number was fit to.

The defect this module exists to prevent is not a wrong verdict — it is a CLEAN verdict on an
instrument nobody has looked after. So the load-bearing tests here are the ones about absence: an
instrument with no due date must never read as valid, and a step naming an instrument that does not
exist must never pass silently.
"""
from datetime import date

import ahu_calibration as C


INST = {"id": "M-04", "name": "Digital manometer", "type": "Manometer", "serial": "DM-99181",
        "calDue": "2026-09-30", "calDate": "2025-09-30", "certNo": "VN-CAL-2025-4417"}


# ── status ───────────────────────────────────────────────────────────────────────────────────────

def test_an_instrument_inside_its_interval_is_valid():
    s = C.status(INST, "2026-08-21")
    assert s["status"] == C.VALID and s["daysLeft"] == 40


def test_an_instrument_past_its_due_date_is_expired_and_says_by_how_long():
    s = C.status(INST, "2026-10-15")
    assert s["status"] == C.EXPIRED
    assert s["daysLeft"] == -15
    assert "15 day(s) before this" in s["why"]


def test_the_last_day_of_the_interval_is_still_valid():
    """An off-by-one here condemns a day's testing or lets a day's testing through."""
    assert C.status(INST, "2026-09-30")["status"] == C.DUE_SOON
    assert C.status(INST, "2026-10-01")["status"] == C.EXPIRED


def test_an_instrument_approaching_its_due_date_is_flagged_before_it_bites():
    assert C.status(INST, "2026-09-15")["status"] == C.DUE_SOON


def test_an_instrument_with_no_due_date_is_unknown_and_never_valid():
    """THE test. "We have no record" and "it is in calibration" are opposite claims, and defaulting
    the first to the second puts a clean status on exactly the instruments nobody is maintaining."""
    for bad in ("", None, "soon", "30/09/2026", "2026-13-01"):
        s = C.status(dict(INST, calDue=bad), "2026-08-21")
        assert s["status"] == C.UNKNOWN, bad
        assert "not the same as being in calibration" in s["why"]
    # And an instrument record with no calDue KEY at all — `dict(INST, **{})` would have left the
    # real due date in place and quietly tested nothing.
    bare = {k: v for k, v in INST.items() if k != "calDue"}
    assert "calDue" not in bare
    assert C.status(bare, "2026-08-21")["status"] == C.UNKNOWN


def test_an_instrument_that_does_not_exist_is_not_found_rather_than_unknown():
    """Different problems: one is a records gap, the other is a broken reference."""
    assert C.status(None, "2026-08-21")["status"] == C.NOT_FOUND


# ── the check at sign time ───────────────────────────────────────────────────────────────────────

def _idx():
    return C.index([INST])


def test_signing_a_test_on_an_expired_instrument_is_refused():
    err = C.check_step({"instrumentId": "M-04"}, _idx(), "2026-10-15")
    assert err and "out of calibration" in err and "M-04" in err


def test_signing_a_test_on_an_instrument_in_calibration_is_allowed():
    assert C.check_step({"instrumentId": "M-04"}, _idx(), "2026-08-21") is None


def test_an_instrument_reference_matching_nothing_is_refused():
    """A free-typed id that matches nothing is indistinguishable from a typo, and a typo here
    silently detaches a measurement from its provenance."""
    err = C.check_step({"instrumentId": "M-99"}, _idx(), "2026-08-21")
    assert err and "not in the calibration register" in err


def test_a_step_naming_no_instrument_passes_until_the_rule_is_switched_on():
    """Off by default so a factory can populate the register before the rule is enforced. The gap is
    reported either way — see untraced_tests."""
    assert C.check_step({}, _idx(), "2026-08-21") is None
    err = C.check_step({}, _idx(), "2026-08-21", require_named=True)
    assert err and "does not say which instrument" in err


def test_an_unknown_or_due_soon_instrument_does_not_stop_the_line():
    """A missing due date is a records problem to chase, not a reason to halt a test mid-way. It is
    reported by register_gaps instead."""
    idx = C.index([dict(INST, calDue="")])
    assert C.check_step({"instrumentId": "M-04"}, idx, "2026-08-21") is None
    assert C.check_step({"instrumentId": "M-04"}, _idx(), "2026-09-15") is None


# ── the question a failed calibration asks ───────────────────────────────────────────────────────

STEPS = [
    {"id": "s1", "unitId": "u1", "code": "T3", "instrumentId": "M-04", "signedOn": "2026-08-01",
     "signedBy": "Mai"},
    {"id": "s2", "unitId": "u2", "code": "T3", "instrumentId": "M-04", "signedOn": "2026-11-02",
     "signedBy": "Mai"},
    {"id": "s3", "unitId": "u3", "code": "T3", "instrumentId": "OTHER", "signedOn": "2026-11-02",
     "signedBy": "Mai"},
    {"id": "s4", "unitId": "u4", "code": "T3", "instrumentId": "M-04", "signedOn": "",
     "signedBy": ""},
]


def test_every_measurement_taken_after_the_due_date_is_listed_as_suspect():
    rows = C.affected_steps(INST, STEPS)
    by_id = {r["stepId"]: r for r in rows}
    assert by_id["s1"]["suspect"] is False
    assert by_id["s2"]["suspect"] is True and "33 day(s) after" in by_id["s2"]["why"]


def test_another_instruments_measurements_are_not_swept_in():
    """A recall list that over-reaches gets ignored as fast as one that under-reports."""
    assert "s3" not in {r["stepId"] for r in C.affected_steps(INST, STEPS)}


def test_an_unsigned_step_is_left_out_rather_than_judged():
    assert "s4" not in {r["stepId"] for r in C.affected_steps(INST, STEPS)}


def test_the_signature_timestamp_is_used_when_there_is_no_signed_on_date():
    steps = [{"id": "s9", "unitId": "u9", "code": "T3", "instrumentId": "M-04",
              "signatures": [{"name": "Mai", "ts": "2026-11-02T09:00:00Z"}]}]
    r = C.affected_steps(INST, steps)[0]
    assert r["signedOn"] == "2026-11-02" and r["suspect"] is True


def test_an_instrument_with_no_due_date_reports_its_steps_as_unjudgeable_not_clean():
    r = C.affected_steps(dict(INST, calDue=""), STEPS)
    assert all(x["suspect"] is False for x in r)
    assert all("cannot be judged" in x["why"] for x in r)


def test_an_instrument_with_no_id_matches_nothing():
    """Otherwise a blank id would match every step whose instrumentId is also blank, and report the
    whole factory as affected."""
    assert C.affected_steps({"calDue": "2026-09-30"}, STEPS) == []


# ── the register's own gaps ──────────────────────────────────────────────────────────────────────

def test_the_register_report_separates_expired_due_soon_and_no_date():
    reg = [INST,
           dict(INST, id="M-05", calDue="2026-01-01"),
           dict(INST, id="M-06", calDue=""),
           dict(INST, id="M-07", calDue="2028-01-01")]
    g = C.register_gaps(reg, "2026-08-21")
    assert [r["id"] for r in g[C.EXPIRED]] == ["M-05"]
    assert [r["id"] for r in g[C.UNKNOWN]] == ["M-06"]
    assert "M-07" not in str(g)          # in calibration and not near due — not a gap


def test_an_instrument_with_no_due_date_appears_in_the_gaps_at_all():
    """It would be invisible in any list sorted by due date, which is exactly the instrument nobody
    is maintaining."""
    g = C.register_gaps([dict(INST, id="X", calDue="")], "2026-08-21")
    assert len(g[C.UNKNOWN]) == 1


def test_expired_instruments_are_ordered_worst_first():
    reg = [dict(INST, id="A", calDue="2026-08-01"), dict(INST, id="B", calDue="2026-01-01")]
    assert [r["id"] for r in C.register_gaps(reg, "2026-08-21")[C.EXPIRED]] == ["B", "A"]


def test_untraced_signed_tests_are_named_not_counted():
    steps = [{"id": "a", "unitId": "u1", "code": "T3", "signedBy": "Mai"},
             {"id": "b", "unitId": "u1", "code": "T4", "signedBy": "Mai", "instrumentId": "M-04"},
             {"id": "c", "unitId": "u1", "code": "T5"}]          # unsigned — not yet a gap
    out = C.untraced_tests(steps)
    assert [r["stepId"] for r in out] == ["a"]


def test_the_calibration_diary_lists_what_falls_due_soonest_first():
    reg = [dict(INST, id="A", calDue="2026-10-01"), dict(INST, id="B", calDue="2026-09-01"),
           dict(INST, id="C", calDue="2027-06-01")]
    out = C.next_due(reg, "2026-08-21", within_days=90)
    assert [r["id"] for r in out] == ["B", "A"]           # C is beyond the horizon


def test_nothing_here_raises_on_empty_input():
    assert C.register_gaps(None, "2026-08-21")[C.EXPIRED] == []
    assert C.untraced_tests(None) == []
    assert C.next_due(None, "2026-08-21") == []
    assert C.affected_steps(None, None) == []
