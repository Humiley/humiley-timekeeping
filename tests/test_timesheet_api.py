"""The timesheet, end to end — and the first absence figure this portal can actually produce.

attendance_days.py proves the classification. This proves the parts only the server can: that the
rest days come from the employee's OWN schedule, that the holiday register and approved leave reach
the calculation, and that the sheet is scoped so a staff member sees their own and not the company's.
"""
import pytest

import db


@pytest.fixture(autouse=True)
def _clean():
    before = {e["id"]: dict(e) for e in db.list_employees()}

    def wipe():
        conn = db.get_conn()
        conn.execute("DELETE FROM attendance")
        conn.execute("DELETE FROM leave")
        conn.execute("DELETE FROM collections WHERE coll = 'schedules'")
        conn.commit()
        conn.close()
    wipe()
    db.set_setting("portal_holidays", [])
    yield
    wipe()
    db.set_setting("portal_holidays", [])
    for eid, v in before.items():
        db.update_employee(eid, v)


# A week that has already happened — 2026-07-27 Mon … 2026-08-02 Sun. It has to be in the past:
# the server truncates the record at today, because a day that has not arrived is not an absence.
MON, TUE, WED, THU, FRI, SAT, SUN = ("2026-07-27", "2026-07-28", "2026-07-29", "2026-07-30",
                                     "2026-07-31", "2026-08-01", "2026-08-02")


def _sheet_for(r, emp_id):
    return [s for s in r["sheets"] if s["empId"] == emp_id][0]


def _get(api, token, **qs):
    q = "&".join("%s=%s" % (k, v) for k, v in qs.items())
    return api("GET", "/api/hr/timesheet" + ("?" + q if q else ""), token)


# ── who sees what ────────────────────────────────────────────────────────────────────────────────

def test_a_staff_member_sees_their_own_and_not_the_company(api, tokens):
    code, r = _get(api, tokens["staff"], **{"from": MON, "to": FRI})
    assert code == 200, r
    assert [s["empId"] for s in r["sheets"]] == ["HML-STF"]


def test_management_sees_everybody(api, tokens):
    _, r = _get(api, tokens["management"], **{"from": MON, "to": FRI})
    assert len(r["sheets"]) > 1


def test_it_needs_a_session(api, tokens):
    assert _get(api, None, **{"from": MON, "to": FRI})[0] == 401


# ── the absence figure ───────────────────────────────────────────────────────────────────────────

def test_a_working_week_with_no_records_is_five_absences_not_zero(api, tokens):
    """The old counter read a status nothing writes, so it was always zero. This is the number the
    company has never been able to see."""
    _, r = _get(api, tokens["staff"], **{"from": MON, "to": SUN})
    s = _sheet_for(r, "HML-STF")
    assert s["counts"]["absent"] == 5, "Mon-Fri"
    assert s["counts"]["rest"] == 2, "Sat and Sun, the default office pattern"


def test_a_day_worked_is_not_an_absence(api, tokens):
    db.clock_in("HML-STF", MON, "08:00")
    _, r = _get(api, tokens["staff"], **{"from": MON, "to": MON})
    s = _sheet_for(r, "HML-STF")
    assert s["counts"]["absent"] == 0 and s["worked"] == 1


def test_a_public_holiday_from_the_company_register_is_not_an_absence(api, tokens):
    db.set_setting("portal_holidays", [{"date": MON, "name": "Test holiday"}])
    _, r = _get(api, tokens["staff"], **{"from": MON, "to": MON})
    s = _sheet_for(r, "HML-STF")
    assert s["counts"]["holiday"] == 1 and s["counts"]["absent"] == 0


def _leave(start, end, status):
    conn = db.get_conn()
    conn.execute('INSERT INTO leave (emp_id,type,"startDate","endDate",days,reason,status) '
                 "VALUES (?,?,?,?,?,?,?)",
                 ("HML-STF", "annual", start, end, 1, "family", status))
    conn.commit(); conn.close()


def test_approved_leave_reaches_the_calculation(api, tokens):
    _leave(MON, TUE, "approved")
    _, r = _get(api, tokens["staff"], **{"from": MON, "to": TUE})
    s = _sheet_for(r, "HML-STF")
    assert s["counts"]["leave"] == 2 and s["counts"]["absent"] == 0


def test_a_pending_leave_request_does_not_excuse_the_day(api, tokens):
    _leave(MON, MON, "pending")
    _, r = _get(api, tokens["staff"], **{"from": MON, "to": MON})
    assert _sheet_for(r, "HML-STF")["counts"]["absent"] == 1


# ── the rest days come from the employee's OWN schedule ──────────────────────────────────────────

def test_a_mon_to_sat_worker_is_not_absent_on_saturday_and_IS_expected_on_it(api, tokens):
    """The default is the office Mon-Fri pattern. Applying it to the factory would have reported a
    Saturday shift as an absence for everybody who works one."""
    db.put_collection_item("schedules", {"id": "s1", "name": "Factory Shift A", "days": "Mon - Sat"})
    db.update_employee("HML-STF", {"schedule": "Factory Shift A"})
    _, r = _get(api, tokens["staff"], **{"from": SAT, "to": SUN})
    s = _sheet_for(r, "HML-STF")
    assert s["counts"]["rest"] == 1, "only Sunday"
    assert s["counts"]["absent"] == 1, "Saturday was a working day they did not attend"


def test_the_default_office_pattern_rests_at_the_weekend(api, tokens):
    db.update_employee("HML-STF", {"schedule": ""})
    _, r = _get(api, tokens["staff"], **{"from": SAT, "to": SUN})
    assert _sheet_for(r, "HML-STF")["counts"]["rest"] == 2


# ── the Decree 145 record ────────────────────────────────────────────────────────────────────────

def test_the_sheet_carries_the_times_and_the_place_for_every_day(api, tokens):
    db.clock_in("HML-STF", MON, "08:00", loc="Cleanroom Phase 2")
    db.clock_out(db.open_attendance("HML-STF", MON)["id"], "17:00")
    _, r = _get(api, tokens["staff"], **{"from": MON, "to": MON})
    d = _sheet_for(r, "HML-STF")["days"][0]
    assert (d["clockIn"], d["clockOut"]) == ("08:00", "17:00")
    assert d["hrs"] == "9h 00m"
    assert d["location"] == "Cleanroom Phase 2"


def test_a_forgotten_check_out_shows_as_an_open_row_rather_than_a_worked_day(api, tokens):
    db.clock_in("HML-STF", MON, "08:00")
    _, r = _get(api, tokens["staff"], **{"from": MON, "to": MON})
    s = _sheet_for(r, "HML-STF")
    assert s["openRows"] == 1
    assert s["days"][0]["open"] is True


def test_the_review_names_who_was_absent_and_for_how_many_days(api, tokens):
    _, r = _get(api, tokens["management"], **{"from": MON, "to": FRI})
    assert r["absentDays"] > 0
    assert r["absentPeople"] and r["absentPeople"][0]["days"] > 0
    assert "derived from the register" in r["basis"]


def test_one_employee_can_be_asked_for_by_id(api, tokens):
    _, r = _get(api, tokens["management"], **{"from": MON, "to": MON, "emp": "HML-STF"})
    assert [s["empId"] for s in r["sheets"]] == ["HML-STF"]


def test_a_missing_or_nonsense_window_falls_back_to_this_month(api, tokens):
    code, r = _get(api, tokens["staff"])
    assert code == 200
    assert r["from"].endswith("-01") and len(r["to"]) == 10


def test_a_window_running_past_today_does_not_accuse_anybody_of_the_future(api, tokens):
    """Picking "this month" in the first week used to report the rest of it as absence. The server
    holds the company clock, so the truncation belongs here."""
    code, r = _get(api, tokens["staff"], **{"from": "2000-01-01", "to": "2099-12-31"})
    assert code == 200
    s = _sheet_for(r, "HML-STF")
    assert r["truncated"] is True
    assert max(d["date"] for d in s["days"]) <= r["today"]


def test_a_window_that_has_already_passed_is_not_marked_truncated(api, tokens):
    _, r = _get(api, tokens["staff"], **{"from": MON, "to": FRI})
    assert r["truncated"] is False


def test_an_inactive_employee_is_not_reported_as_absent_every_day(api, tokens):
    """They left. Counting their absence would be the largest number on the screen."""
    db.update_employee("HML-STF", {"status": "Inactive"})
    try:
        _, r = _get(api, tokens["management"], **{"from": MON, "to": FRI})
        assert not [s for s in r["sheets"] if s["empId"] == "HML-STF"]
    finally:
        db.update_employee("HML-STF", {"status": "Active"})
