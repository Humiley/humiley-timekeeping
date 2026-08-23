# -*- coding: utf-8 -*-
"""Every night-shift worker was stamped late, every night.

`_checkin` decided lateness with a plain same-day string compare, `t <= thr`. A night pattern's
threshold has wrapped past midnight — "Night Shift 23:30 - 07:30" with 45 minutes' grace gives
00:15 — and `'23:35' <= '00:15'` is False. Somebody arriving five minutes into their shift was
written into the attendance register kept under Decree 145/2020 with status='late', and Manager →
Late Arrivals disciplines from that row.

A night pattern named without a time fell through to the 08:00 default and was stamped late on
arrival for the same reason.

Neither had anything to do with the check-in window; both predate it. Lateness is measured in
ELAPSED MINUTES from when the shift's door opens now, so a clock face that wraps stops mattering.

Two directions are guarded, because a modular subtraction gets both wrong on its own:
  · an EARLY arrival must never be late — 07:00 against an 08:30 threshold is not 22½ hours late
  · more than twelve hours after the door opened is a punch for a different shift
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


def _late(punch, schedule):
    """What _checkin computes: the threshold and the start, then the verdict."""
    thr = app.Handler._late_threshold(schedule)
    if thr is None:
        return False
    return app.Handler._is_late(punch, thr, app.Handler._shift_start_for(schedule))


# -- the live bug: a threshold that wrapped past midnight ----------------------------------------
def test_a_night_worker_arriving_on_time_is_not_late(base_url):
    name = "ZZ Night Shift 23:30 - 07:30"
    _clear(name)
    _sched(name, grace=45)                      # threshold 00:15 - wrapped
    try:
        assert app.Handler._late_threshold(name) == "00:15", "the fixture does not reproduce the wrap"
        assert not _late("23:35", name), "five minutes into the shift was stamped late"
        assert not _late("23:30", name), "arriving exactly on time was stamped late"
    finally:
        _clear(name)


def test_but_a_night_worker_who_is_actually_late_still_is(base_url):
    """The fix must not become 'nobody on nights is ever late', which is the other way to be wrong."""
    name = "ZZ Night Shift 23:30 - 07:30"
    _clear(name)
    _sched(name, grace=45)
    try:
        assert _late("00:20", name), "five minutes past a 00:15 threshold is late"
        assert _late("02:00", name)
    finally:
        _clear(name)


def test_a_night_pattern_named_without_a_time_uses_its_window(base_url):
    """The second pre-existing path to the same wrong answer: no time in the name, so the old code
    fell back to 08:00 and stamped a 22:00 arrival late."""
    name = "ZZ Factory Night Shift A"
    _clear(name)
    _sched(name, inwin="21:45 - 22:15", grace=15)
    try:
        assert app.Handler._late_threshold(name) == "22:15"
        assert not _late("22:00", name), "arriving before the window closed was stamped late"
        assert _late("22:30", name)
    finally:
        _clear(name)


# -- an early arrival is never late ---------------------------------------------------------------
def test_arriving_early_is_not_late(base_url):
    """`(punch - start) % 1440` alone makes 07:00 against an 08:00 start read as 23 hours elapsed."""
    name = "ZZ Standard 08:00 - 17:00"
    _clear(name)
    _sched(name, grace=30)
    try:
        assert not _late("07:00", name), "an hour early was counted as 23 hours late"
        assert not _late("06:00", name)
        assert not _late("08:00", name)
        assert not _late("08:30", name), "exactly on the threshold is not past it"
        assert _late("08:31", name)
    finally:
        _clear(name)


def test_early_for_a_night_shift_too(base_url):
    name = "ZZ Night Shift 22:00 - 06:00"
    _clear(name)
    _sched(name, grace=30)
    try:
        assert not _late("21:30", name), "half an hour early on nights"
        assert not _late("22:30", name)
        assert _late("22:31", name)
    finally:
        _clear(name)


# -- a punch for another shift is not a late arrival -----------------------------------------------
def test_a_punch_half_a_day_later_is_not_reported_as_lateness(base_url):
    name = "ZZ Standard 08:00 - 17:00"
    _clear(name)
    _sched(name, grace=30)
    try:
        assert _late("12:00", name), "four hours late is late"
        assert not _late("21:00", name), "thirteen hours after the door opened is another shift"
    finally:
        _clear(name)


# -- the day patterns must not move ---------------------------------------------------------------
def test_the_seeded_day_patterns_keep_their_verdicts(base_url):
    """If any of these moved, the change would be re-judging live attendance rather than fixing it."""
    cases = [
        ("ZZ Standard 08:00 - 17:00", "07:30 - 08:30", 30, [("08:00", False), ("08:30", False), ("08:31", True)]),
        ("ZZ Morning Shift 06:00 - 14:00", "05:45 - 06:15", 15, [("06:00", False), ("06:15", False), ("06:16", True)]),
        ("ZZ Evening Shift 14:00 - 22:00", "13:45 - 14:15", 15, [("14:00", False), ("14:15", False), ("14:20", True)]),
    ]
    for name, inwin, grace, punches in cases:
        _clear(name)
        _sched(name, inwin=inwin, grace=grace)
        try:
            for t, want in punches:
                assert _late(t, name) is want, "%s at %s: expected late=%s" % (name, t, want)
        finally:
            _clear(name)


def test_flexible_staff_are_still_never_late(base_url):
    name = "ZZ Flexible (Field Services)"
    _clear(name)
    _sched(name, inwin="07:00 - 09:00", grace=30)
    try:
        assert app.Handler._late_threshold(name) is None
        assert not _late("13:00", name)
    finally:
        _clear(name)


# -- the helper itself, so the boundary is pinned without a DB ------------------------------------
def test_is_late_boundaries():
    L = app.Handler._is_late
    assert not L("08:00", "08:30", "08:00")
    assert not L("08:30", "08:30", "08:00")      # on the threshold, not past it
    assert L("08:31", "08:30", "08:00")
    assert not L("07:59", "08:30", "08:00")      # one minute early
    assert L("20:00", "08:30", "08:00")          # exactly 12h - still this shift
    assert not L("20:01", "08:30", "08:00")      # past 12h - another shift
    # the wrap
    assert not L("23:35", "00:15", "23:30")
    assert L("00:20", "00:15", "23:30")


def test_is_late_never_raises_on_junk():
    """An unparseable time must not 500 a check-in, and must not be read as evidence of lateness."""
    L = app.Handler._is_late
    for bad in ("", "abc", None, "25:99", "8"):
        assert L(bad, "08:30", "08:00") is False
        assert L("08:31", bad, "08:00") is False
        assert L("08:31", "08:30", bad) is False
