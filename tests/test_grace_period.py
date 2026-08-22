# -*- coding: utf-8 -*-
"""The grace period on a work schedule has to be the one that decides lateness.

The Work Schedules form has a "Late Grace Period (min)" field. saveSchedule persists it as `grace`
on the schedule record, the register prints it in its own column, and the seeded office pattern
ships 30. Nothing read it — _late_threshold added a hardcoded 15.

That is the worst shape a dead control can take. Every other inert toggle fails to RECORD something;
this one wrote a wrong fact about a named person — status='late' — into the attendance register kept
under Decree 145/2020, which Manager → Late Arrivals disciplines from. An administrator who set 30
minutes' grace still had somebody arriving 08:16 marked late, and nothing on any screen explained why.
"""
import app
import db


def _sched(name, grace, days="Mon-Fri"):
    # NOTE: every test below takes `base_url`. That session fixture boots the app, which is what
    # CREATES the schema — without it db.list_collection raises "no such table: collections" and the
    # test errors in setup rather than passing. An erroring test is not a passing one.
    return db.put_collection_item("schedules", {"name": name, "grace": grace, "days": days})


def _clear(name):
    for r in db.list_collection("schedules"):
        if str(r.get("name") or "") == name:
            try:
                db.delete_collection_item("schedules", r["id"])
            except Exception:
                pass


# ── the thing that was broken ───────────────────────────────────────────────────────────────────
def test_the_schedules_own_grace_decides_lateness(base_url):
    name = "ZZ Office 08:00 - 17:00"
    _clear(name)
    _sched(name, 30)
    try:
        assert app.Handler._late_threshold(name) == "08:30", \
            "the schedule says 30 minutes and the threshold ignored it"
    finally:
        _clear(name)


def test_a_different_grace_gives_a_different_threshold(base_url):
    """If both values produced the same answer the test above could pass on a hardcoded constant."""
    name = "ZZ Shift 06:00 - 14:00"
    for grace, want in ((0, "06:00"), (5, "06:05"), (45, "06:45"), (75, "07:15")):
        _clear(name)
        _sched(name, grace)
        try:
            got = app.Handler._late_threshold(name)
            assert got == want, "grace %s gave %s, expected %s" % (grace, got, want)
        finally:
            _clear(name)


# ── the fallback must not move ──────────────────────────────────────────────────────────────────
def test_no_schedule_still_means_eight_fifteen(base_url):
    """Every record already in the register was judged by 08:15. Moving the fallback silently would
    change what those rows MEAN, retrospectively."""
    assert app.Handler._late_threshold("") == "08:15"
    assert app.Handler._late_threshold(None) == "08:15"


def test_an_unknown_schedule_name_falls_back_rather_than_guessing(base_url):
    assert app.Handler._late_threshold("ZZ Never Created 09:00 - 18:00") == "09:15"


def test_a_schedule_with_no_grace_value_falls_back(base_url):
    name = "ZZ No Grace 07:30 - 16:30"
    _clear(name)
    db.put_collection_item("schedules", {"name": name, "days": "Mon-Fri"})   # no grace key at all
    try:
        assert app.Handler._late_threshold(name) == "07:45"
    finally:
        _clear(name)


# ── nonsense in the box is an input error, not a policy ─────────────────────────────────────────
def test_absurd_grace_is_refused(base_url):
    name = "ZZ Absurd 08:00 - 17:00"
    for bad in (-30, 1440, "abc"):
        _clear(name)
        _sched(name, bad)
        try:
            assert app.Handler._late_threshold(name) == "08:15", \
                "%r was accepted as a grace period" % bad
        finally:
            _clear(name)


# ── flexible staff are still never late ─────────────────────────────────────────────────────────
def test_flexible_and_wfh_are_untouched(base_url):
    assert app.Handler._late_threshold("Flexible (Field Services)") is None
    assert app.Handler._late_threshold("WFH Schedule") is None
