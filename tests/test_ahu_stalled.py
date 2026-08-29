"""A unit that has stopped moving is invisible on every screen the factory has.

The three existing alerts fire on things that went WRONG — a step failed, a gate was held, a
non-conformance aged. None fires on work that simply stopped. A unit stuck at 40% looks identical on
the board this Monday and last Monday, so the commonest shop-floor failure is the one nothing
reports.

These tests are mostly about the THREE REFUSALS, because the arithmetic is trivial and the refusals
are where this would go wrong:

  * never started is not "stalled for N days" — different problem, different owner
  * a signature nobody can date is not "0 days" — that would rank the worst record as the healthiest
  * a future-stamped signature is refused rather than reported as negative days
"""
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

import ahu_capacity as C   # noqa: E402


def _step(code, ts=None, **kw):
    s = {"code": code, "kind": "op", "seq": 1}
    if ts:
        s["signatures"] = [{"ts": ts, "name": "Somebody"}]
    s.update(kw)
    return s


TODAY = "2026-08-29"


# ── the ordinary answer ─────────────────────────────────────────────────────────────────────────

def test_a_unit_signed_today_is_moving():
    st = C.stall_state([_step("WS-01", "2026-08-29T08:00:00")], TODAY, 7)
    assert st["status"] == C.MOVING and st["days"] == 0


def test_a_unit_untouched_past_the_threshold_is_stalled():
    st = C.stall_state([_step("WS-02", "2026-08-10T08:00:00")], TODAY, 7)
    assert st["status"] == C.STALLED and st["days"] == 19


def test_the_threshold_is_inclusive():
    """Exactly at the threshold counts as stalled — otherwise the alert fires a day late, every
    time, and the one number an operator tunes would not mean what it says."""
    assert C.stall_state([_step("WS-01", "2026-08-22T08:00:00")], TODAY, 7)["status"] == C.STALLED
    assert C.stall_state([_step("WS-01", "2026-08-23T08:00:00")], TODAY, 7)["status"] == C.MOVING


def test_the_clock_runs_from_the_LATEST_signature_not_the_first():
    st = C.stall_state([_step("WS-01", "2026-07-01T08:00:00"),
                        _step("WS-02", "2026-08-28T08:00:00")], TODAY, 7)
    assert st["status"] == C.MOVING and st["lastCode"] == "WS-02"


# ── the three refusals ──────────────────────────────────────────────────────────────────────────

def test_a_unit_with_nothing_signed_is_never_started_not_stalled():
    """Planning's problem, not the floor's. Folding it into the stalled list sends the wrong person
    to look, and there is no signature to count days from anyway."""
    st = C.stall_state([_step("WS-01"), _step("WS-02")], TODAY, 7)
    assert st["status"] == C.NEVER_STARTED
    assert st["days"] is None, "never-started must carry no day count"


def test_a_signature_with_no_readable_instant_is_undateable_not_zero_days():
    """THE refusal. Zero would rank the unit with the worst record as the healthiest on the board."""
    st = C.stall_state([_step("WS-01", "sometime last week")], TODAY, 7)
    assert st["status"] == C.UNDATEABLE
    assert st["days"] is None


def test_a_signed_by_with_no_signature_chain_is_undateable_not_never_started():
    """Somebody DID sign it — the record just cannot be dated. Reporting that as never-started would
    say the work had not begun, which is a different and wrong claim."""
    st = C.stall_state([_step("WS-01", signedBy="Tran Van Long", signedOn="2026-08-01")], TODAY, 7)
    assert st["status"] == C.UNDATEABLE


def test_a_signature_stamped_in_the_future_is_refused_not_reported_as_negative():
    st = C.stall_state([_step("WS-01", "2026-09-15T08:00:00")], TODAY, 7)
    assert st["status"] == C.UNDATEABLE and st["days"] is None


def test_an_unreadable_today_cannot_age_anything():
    st = C.stall_state([_step("WS-01", "2026-08-01T08:00:00")], "not a date", 7)
    assert st["status"] == C.UNDATEABLE


# ── the sweep ───────────────────────────────────────────────────────────────────────────────────

def _row(uid, pin, steps):
    return {"unit": {"id": uid, "pin": pin, "tag": "T", "orderId": "o1"}, "steps": steps}


def test_the_sweep_separates_the_three_kinds_rather_than_dropping_any():
    rows = [
        _row("u1", "PIN-1", [_step("WS-01", "2026-08-01T08:00:00")]),       # stalled
        _row("u2", "PIN-2", [_step("WS-01", "2026-08-29T08:00:00")]),       # moving
        _row("u3", "PIN-3", [_step("WS-01")]),                              # never started
        _row("u4", "PIN-4", [_step("WS-01", "who knows")]),                 # undateable
    ]
    out = C.stalled_units(rows, TODAY, 7)
    assert [r["pin"] for r in out["stalled"]] == ["PIN-1"]
    assert [r["pin"] for r in out["neverStarted"]] == ["PIN-3"]
    assert [r["pin"] for r in out["undateable"]] == ["PIN-4"]


def test_the_worst_offender_comes_first():
    rows = [_row("u1", "PIN-NEW", [_step("WS-01", "2026-08-15T08:00:00")]),
            _row("u2", "PIN-OLD", [_step("WS-01", "2026-06-01T08:00:00")])]
    out = C.stalled_units(rows, TODAY, 7)
    assert [r["pin"] for r in out["stalled"]] == ["PIN-OLD", "PIN-NEW"]


def test_an_undateable_unit_is_never_silently_dropped():
    """A unit nobody can age is the one most worth looking at. An alert that got quieter as the data
    got worse would be exactly backwards.

    The signature has to be present but unreadable — an EMPTY ts adds no signature at all and makes
    the unit never-started, which is a different row in a different list and would have let this
    test pass while proving nothing about undateable.
    """
    out = C.stalled_units([_row("u1", "PIN-X", [_step("WS-01", "13/08/2026")])], TODAY, 7)
    assert out["stalled"] == [] and out["neverStarted"] == []
    assert [r["pin"] for r in out["undateable"]] == ["PIN-X"]


def test_nothing_here_raises_on_empty_input():
    assert C.stalled_units(None, TODAY, 7)["stalled"] == []
    assert C.stall_state(None, TODAY, 7)["status"] == C.NEVER_STARTED
