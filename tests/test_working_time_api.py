"""/api/hr/working-time — Arts. 105, 110 and 111 against the real register.

working_time.py proves the law. This proves the join: that the break comes off the employee's OWN
schedule, that a pattern with no declared break is reported as undeclared rather than as a breach,
and that the endpoint is scoped so a staff member sees their own hours and not the company's.
"""
import pytest

import db


@pytest.fixture(autouse=True)
def _clean():
    before = {e["id"]: dict(e) for e in db.list_employees()}

    def wipe():
        conn = db.get_conn()
        conn.execute("DELETE FROM attendance")
        conn.execute("DELETE FROM collections WHERE coll = 'schedules'")
        conn.commit()
        conn.close()
    wipe()
    yield
    wipe()
    for eid, v in before.items():
        db.update_employee(eid, v)


MON, TUE, WED, THU, FRI = ("2026-07-27", "2026-07-28", "2026-07-29", "2026-07-30", "2026-07-31")


def _shift(emp, date, cin, cout, **kw):
    db.clock_in(emp, date, cin, **kw)
    row = db.open_attendance(emp, date)
    db.clock_out(row["id"], cout, overnight=(cout <= cin))
    return row


def _sched(name, break_min, days="Mon - Fri"):
    db.put_collection_item("schedules", {"id": "s-" + name, "name": name, "days": days,
                                         "breakMin": break_min})
    db.update_employee("HML-STF", {"schedule": name})


def _get(api, token, **qs):
    q = "&".join("%s=%s" % (k, v) for k, v in qs.items())
    return api("GET", "/api/hr/working-time" + ("?" + q if q else ""), token)


def _me(r):
    return [p for p in r["people"] if p["empId"] == "HML-STF"][0]


# ── who sees what ────────────────────────────────────────────────────────────────────────────────

def test_a_staff_member_sees_only_their_own_hours(api, tokens):
    _shift("HML-STF", MON, "08:00", "17:00")
    _shift("HML-MGR", MON, "08:00", "17:00")
    code, r = _get(api, tokens["staff"], **{"from": MON, "to": FRI})
    assert code == 200, r
    assert [p["empId"] for p in r["people"]] == ["HML-STF"]


def test_it_needs_a_session(api, tokens):
    assert _get(api, None, **{"from": MON, "to": FRI})[0] == 401


def test_somebody_with_no_attendance_is_left_out_rather_than_reported_as_clean(api, tokens):
    """A person with no rows has not been shown to comply — there is simply nothing to check."""
    _, r = _get(api, tokens["management"], **{"from": MON, "to": FRI})
    assert r["people"] == [] and r["findings"] == []


# ── the break comes off the employee's own schedule ──────────────────────────────────────────────

def test_an_ordinary_office_day_is_not_a_breach_once_the_break_is_declared(api, tokens):
    """08:00–17:00 is nine hours on site and eight of work. Without the declared break the portal
    cannot tell those apart, and reporting the breach would flag every employee every day."""
    _sched("Standard 08:00 - 17:00", 60)
    _shift("HML-STF", MON, "08:00", "17:00")
    _, r = _get(api, tokens["staff"], **{"from": MON, "to": FRI})
    me = _me(r)
    assert me["breakMinutes"] == 60
    assert me["days"][0]["normalHours"] == 8.0
    assert not [f for f in r["findings"] if f["article"] == "Art. 105"]


def test_a_schedule_with_no_declared_break_is_reported_as_undeclared_not_as_a_breach(api, tokens):
    _sched("No break declared", None)
    _shift("HML-STF", MON, "08:00", "17:00")
    _, r = _get(api, tokens["staff"], **{"from": MON, "to": FRI})
    assert [u["empId"] for u in r["undeclaredBreak"]] == ["HML-STF"]
    assert _me(r)["indeterminate"] is True
    assert r["findings"] == []


def test_an_employee_with_no_schedule_at_all_is_undeclared_too(api, tokens):
    db.update_employee("HML-STF", {"schedule": ""})
    _shift("HML-STF", MON, "08:00", "17:00")
    _, r = _get(api, tokens["staff"], **{"from": MON, "to": FRI})
    assert _me(r)["breakMinutes"] is None


def test_a_break_of_zero_is_kept_distinct_from_one_that_was_never_set(api, tokens):
    """Zero asserts "works straight through" and makes the arithmetic exact. None says the figure is
    missing. Collapsing them would turn a blank field into a compliance claim."""
    _sched("Straight through", 0)
    _shift("HML-STF", MON, "08:00", "17:00")
    _, r = _get(api, tokens["staff"], **{"from": MON, "to": FRI})
    assert _me(r)["breakMinutes"] == 0
    assert r["undeclaredBreak"] == []
    assert [f["article"] for f in r["findings"]] == ["Art. 105"], "9 working hours, and now provable"


# ── the articles ─────────────────────────────────────────────────────────────────────────────────

def test_less_than_twelve_hours_between_shifts_is_found(api, tokens):
    """Art. 110. A late finish and an early start is the pattern this exists to catch, and nothing
    in the portal has ever looked at it."""
    _sched("Standard", 60)
    _shift("HML-STF", MON, "14:00", "22:00")
    _shift("HML-STF", TUE, "06:00", "14:00")
    _, r = _get(api, tokens["staff"], **{"from": MON, "to": FRI})
    art110 = [f for f in r["findings"] if f["article"] == "Art. 110"]
    assert art110 and art110[0]["actual"] == 8.0
    assert art110[0]["name"]


def test_a_week_with_no_twenty_four_hour_rest_is_found(api, tokens):
    _sched("Seven days", 60, days="Mon - Sun")
    for d in range(27, 32):
        _shift("HML-STF", "2026-07-%02d" % d, "08:00", "22:00")
    _shift("HML-STF", "2026-08-01", "08:00", "22:00")
    _shift("HML-STF", "2026-08-02", "08:00", "22:00")
    _, r = _get(api, tokens["staff"], **{"from": "2026-07-27", "to": "2026-08-02"})
    assert [f for f in r["findings"] if f["article"] == "Art. 111(1)"]


def test_a_normal_week_raises_nothing(api, tokens):
    _sched("Standard", 60)
    for d in (MON, TUE, WED, THU, FRI):
        _shift("HML-STF", d, "08:00", "17:00")
    _, r = _get(api, tokens["staff"], **{"from": MON, "to": FRI})
    assert r["findings"] == []
    assert "Nothing to answer" in r["statement"]


# ── the night premium nobody was paid ────────────────────────────────────────────────────────────

def test_a_rostered_night_shift_surfaces_its_night_hours(api, tokens):
    """Art. 98(2) is not conditional on overtime. The portal only ever priced night hours inside the
    overtime tail, so a crew on a 22:00–06:00 shutdown earned what a day crew earned."""
    _sched("Night", 30)
    _shift("HML-STF", MON, "22:00", "06:00")
    _, r = _get(api, tokens["staff"], **{"from": MON, "to": FRI})
    assert _me(r)["nightHours"] == 8.0
    assert r["nightHours"] == 8.0


def test_the_night_exposure_is_stated_as_unpaid_rather_than_quietly_applied(api, tokens):
    """A read-only screen must not move money. It says what is owed and leaves the decision with the
    people who sign payslips."""
    _sched("Night", 30)
    _shift("HML-STF", MON, "22:00", "06:00")
    _, r = _get(api, tokens["staff"], **{"from": MON, "to": FRI})
    assert "have not reached a payslip" in r["nightPay"]
    assert "changes no pay" in r["nightPay"]
    assert r["nightPayVn"] and any(ord(c) > 127 for c in r["nightPayVn"])


# ── the honesty of the pack ──────────────────────────────────────────────────────────────────────

def test_the_open_questions_travel_with_the_answer(api, tokens):
    _, r = _get(api, tokens["management"], **{"from": MON, "to": FRI})
    topics = {u["topic"] for u in r["unresolved"]}
    assert "Day type after midnight" in topics


def test_the_rejected_claims_travel_with_it_too(api, tokens):
    """So that an auditor or an outside HR consultant producing the 60-hour month or the 250% night
    rate meets the reason it was rejected, not a shrug."""
    _, r = _get(api, tokens["management"], **{"from": MON, "to": FRI})
    claims = {x["claim"] for x in r["rejected"]}
    assert "60 overtime hours a month" in claims


def test_the_limits_in_force_are_returned_so_the_screen_never_restates_them(api, tokens):
    _, r = _get(api, tokens["management"], **{"from": MON, "to": FRI})
    assert r["limits"]["weekHours"] == 48.0 and r["limits"]["shiftGapHours"] == 12.0
    assert r["limits"]["encouragedWeek"] == 40.0, "carried as encouragement, never applied as a cap"


def test_a_missing_window_falls_back_to_this_month(api, tokens):
    code, r = _get(api, tokens["staff"])
    assert code == 200 and r["from"].endswith("-01")
