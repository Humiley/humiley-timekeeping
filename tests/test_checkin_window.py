# -*- coding: utf-8 -*-
"""The Check-In Window on a work schedule has to decide something.

The Work Schedules form has had a "Check-In Window" field since the register was written.
`saveSchedule` persists it as `inwin`, the register prints it in its own column, and the seeded
patterns ship real values — 07:30 – 08:30, 05:45 – 06:15. Nothing read it. `_late_threshold` parsed
a time out of the schedule's NAME instead.

So a pattern named without a time in it — "Factory Shift A", with 05:45 – 06:15 typed on the form
right beside it — was judged against a hardcoded 08:00. Somebody arriving at 06:40, forty minutes
into a shift that began at 06:00, was recorded as on time.

Exactly the shape of the grace-period bug, and the opposite direction: too LENIENT rather than too
harsh, which is why nobody ever complained about it. The register kept under Decree 145/2020 was
wrong either way.

The END of the window, not the start: 07:30 – 08:30 brackets an 08:00 shift. On every seeded pattern
that can be late, the end already equals shift start + grace, so this changes no existing verdict.
That is asserted below, because "changes nothing today" is a claim, not a hope.
"""
import app
import db


def _sched(name, **kw):
    row = {"name": name}
    row.update(kw)
    return db.put_collection_item("schedules", row)


def _clear(name):
    for r in db.list_collection("schedules"):
        if str(r.get("name") or "") == name:
            try:
                db.delete_collection_item("schedules", r["id"])
            except Exception:
                pass


# ── the defect ──────────────────────────────────────────────────────────────────────────────────
def test_a_pattern_named_without_a_time_uses_its_window(base_url):
    """The whole finding. Before this, the answer was 08:15 — two hours after the shift began."""
    name = "ZZ Factory Shift A"
    _clear(name)
    _sched(name, inwin="05:45 – 06:15", grace=15)
    try:
        assert app.Handler._late_threshold(name) == "06:15", \
            "a shift starting at 05:45 was judged against a hardcoded 08:00"
    finally:
        _clear(name)


def test_the_window_outranks_a_time_in_the_name(base_url):
    """An administrator typing a window is making an explicit statement about this shift. A time
    that happens to be in the pattern's name is an inference from a label."""
    name = "ZZ Night 22:00 - 06:00"
    _clear(name)
    _sched(name, inwin="21:30 – 22:20", grace=30)
    try:
        assert app.Handler._late_threshold(name) == "22:20", \
            "the name+grace answer (22:30) won over the window the administrator typed"
    finally:
        _clear(name)


# ── and it does not move anything that already worked ───────────────────────────────────────────
def test_the_seeded_patterns_keep_the_verdict_they_had(base_url):
    """On every shipped pattern the window's end already equals shift start + grace. If that were
    not so, this change would silently re-judge live attendance."""
    for name, inwin, grace, want in (
            ("ZZ Standard 08:00 - 17:00", "07:30 – 08:30", 30, "08:30"),
            ("ZZ Morning Shift 06:00 - 14:00", "05:45 – 06:15", 15, "06:15"),
            ("ZZ Evening Shift 14:00 - 22:00", "13:45 – 14:15", 15, "14:15")):
        _clear(name)
        _sched(name, inwin=inwin, grace=grace)
        try:
            got = app.Handler._late_threshold(name)
            assert got == want, "%s gave %s, expected %s" % (name, got, want)
        finally:
            _clear(name)


def test_a_schedule_with_no_window_still_reads_its_name_and_grace(base_url):
    name = "ZZ No Window 07:30 - 16:30"
    _clear(name)
    _sched(name, grace=20)
    try:
        assert app.Handler._late_threshold(name) == "07:50"
    finally:
        _clear(name)


def test_no_schedule_at_all_is_unchanged(base_url):
    assert app.Handler._late_threshold("") == "08:15"
    assert app.Handler._late_threshold(None) == "08:15"


# ── flexible staff are never late, whatever their window says ───────────────────────────────────
def test_flexible_and_wfh_stay_never_late_even_with_a_window(base_url):
    """Their window says when the door is open. For these patterns lateness is not a concept, and a
    window must not quietly reintroduce it."""
    for name, inwin in (("ZZ Flexible (Field Services)", "07:00 – 09:00"),
                        ("ZZ WFH Schedule", "08:00 – 09:00")):
        _clear(name)
        _sched(name, inwin=inwin, grace=30)
        try:
            assert app.Handler._late_threshold(name) is None, "%s became late-able" % name
        finally:
            _clear(name)


# ── nonsense in the box is an input error, not a policy ─────────────────────────────────────────
def test_a_window_with_one_time_is_refused(base_url):
    """One time is not a window. Guessing which end it is would be inventing a rule."""
    name = "ZZ Half Window 09:00 - 18:00"
    _clear(name)
    _sched(name, inwin="08:45", grace=15)
    try:
        assert app.Handler._late_threshold(name) == "09:15", "it used a half-typed window"
    finally:
        _clear(name)


def test_an_unparseable_window_falls_back(base_url):
    name = "ZZ Junk Window 09:00 - 18:00"
    for junk in ("", "   ", "morning-ish", "25:99 – 26:00"):
        _clear(name)
        _sched(name, inwin=junk, grace=15)
        try:
            assert app.Handler._late_threshold(name) == "09:15", \
                "%r was accepted as a check-in window" % junk
        finally:
            _clear(name)


def test_the_window_is_read_from_the_end_not_the_start(base_url):
    """If it took the START, a 07:30 - 08:30 window would make everybody on the standard pattern
    late an hour early.

    The first version of this test used a pattern named "08:00 - 17:00" with grace 30 and asserted
    08:30 — which is ALSO what name+grace gives, so it passed with _checkin_window_end reverted to
    `return None`. A direction test whose expected value both branches produce measures nothing.
    The name and the grace are now chosen so that all three candidate answers differ:
        window end  = 08:30      <- correct
        window start= 07:30      <- the direction error
        name+grace  = 09:05      <- the feature reverted
    """
    name = "ZZ Direction 09:00 - 18:00"
    _clear(name)
    _sched(name, inwin="07:30 - 08:30", grace=5)
    try:
        got = app.Handler._late_threshold(name)
        assert got != "07:30", "it read the window's START"
        assert got != "09:05", "it ignored the window entirely and used name + grace"
        assert got == "08:30", "got %s" % got
    finally:
        _clear(name)
