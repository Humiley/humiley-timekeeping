"""Overtime, end to end: who may see it, what it is worth, and where the law stops it.

overtime.py proves the arithmetic. This proves the parts only the server can answer — that the hours
came from an APPROVED record, that a rest day is read from the employee's own schedule rather than
assumed, that nobody sees overtime they could not see on the roster, and that approving hours over
the Art. 107 ceiling requires somebody to put their name to it.
"""
import pytest

import app
import db
import overtime


def _att(emp_id, date, cin, cout, hours, status="approved", name=None, dept="Engineering"):
    """Insert an attendance row directly — the check-in/check-out API is exercised elsewhere and
    would not let a test place a shift on an arbitrary past date."""
    conn = db.get_conn()
    cur = conn.execute(
        "INSERT INTO attendance (emp_id,name,dept,date,clock_in,clock_out,status,ot_status,ot_hours) "
        "VALUES (?,?,?,?,?,?,?,?,?)",
        (emp_id, name or emp_id, dept, date, cin, cout, "on-time", status, hours))
    conn.commit()
    rid = cur.lastrowid
    conn.close()
    return rid


@pytest.fixture(autouse=True)
def _clean():
    conn = db.get_conn()
    conn.execute("DELETE FROM attendance")
    conn.commit()
    conn.close()
    db.set_setting("portal_holidays", [])
    db.set_setting("portal_otAnnualCap", "")
    # These tests are about the ART. 107 ceilings, which only ever apply to an adult. Without a date
    # of birth the approval path now refuses on Art. 146 first and never reaches them — correctly,
    # but it makes the test about the wrong article. Say out loud that this employee is an adult.
    db.update_employee("HML-STF", {"dob": "1990-05-20"})
    yield
    conn = db.get_conn()
    conn.execute("DELETE FROM attendance")
    conn.commit()
    conn.close()
    db.update_employee("HML-STF", {"schedule": ""})


def _rows(b):
    return {r["empId"]: r for r in b.get("rows", [])}


# ── the hours that count ─────────────────────────────────────────────────────────────────────────

def test_approved_overtime_reaches_the_summary(api, tokens):
    _att("HML-STF", "2026-06-10", "08:00", "19:00", 2)
    st, b = api("GET", "/api/hr/overtime?period=2026-06", tokens["admin"])
    assert st == 200, b
    r = _rows(b)["HML-STF"]
    assert r["hours"] == 2
    assert r["units"] == 3.0            # 2h × 150%, in multiples of the hourly wage


def test_a_pending_request_is_not_overtime(api, tokens):
    """It is a question the manager has not answered. Paying it would pay for a decision nobody made."""
    _att("HML-STF", "2026-06-10", "08:00", "19:00", 2, status="pending")
    _, b = api("GET", "/api/hr/overtime?period=2026-06", tokens["admin"])
    assert "HML-STF" not in _rows(b)


def test_a_rejected_request_is_not_overtime(api, tokens):
    _att("HML-STF", "2026-06-10", "08:00", "19:00", 2, status="rejected")
    _, b = api("GET", "/api/hr/overtime?period=2026-06", tokens["admin"])
    assert "HML-STF" not in _rows(b)


def test_another_month_is_another_month(api, tokens):
    _att("HML-STF", "2026-05-10", "08:00", "19:00", 2)
    _, b = api("GET", "/api/hr/overtime?period=2026-06", tokens["admin"])
    assert "HML-STF" not in _rows(b)
    _, b = api("GET", "/api/hr/overtime?period=2026-05", tokens["admin"])
    assert _rows(b)["HML-STF"]["hours"] == 2


# ── the rate follows the day, and the day follows the employee's own schedule ────────────────────

def test_sunday_overtime_is_paid_at_the_rest_day_rate(api, tokens):
    _att("HML-STF", "2026-06-14", "08:00", "12:00", 4)          # Sunday
    _, b = api("GET", "/api/hr/overtime?period=2026-06", tokens["admin"])
    assert _rows(b)["HML-STF"]["units"] == 8.0                  # 4h × 200%


def test_a_public_holiday_is_paid_at_treble(api, tokens):
    db.set_setting("portal_holidays", [{"date": "2026-06-10", "name": "Test holiday"}])
    _att("HML-STF", "2026-06-10", "08:00", "12:00", 2)
    _, b = api("GET", "/api/hr/overtime?period=2026-06", tokens["admin"])
    assert _rows(b)["HML-STF"]["units"] == 6.0                  # 2h × 300%


def test_the_factory_saturday_is_a_working_day_not_a_rest_day(api, tokens):
    """`employee.schedule` holds the NAME of a pattern, so the rest days have to be read from the
    schedule that name points at. Reading the name itself treats the whole factory as a Mon–Fri
    office and pays its Saturday overtime at 200% instead of 150%."""
    _, sch = api("POST", "/api/coll/schedules", tokens["admin"],
                 {"name": "Factory Shift A", "days": "Mon – Sat", "dept": "Factory"})
    db.update_employee("HML-STF", {"schedule": "Factory Shift A"})
    _att("HML-STF", "2026-06-13", "08:00", "19:00", 2)          # Saturday
    _, b = api("GET", "/api/hr/overtime?period=2026-06", tokens["admin"])
    assert _rows(b)["HML-STF"]["units"] == 3.0                  # 150%, a normal working day
    api("DELETE", "/api/coll/schedules/" + sch["item"]["id"], tokens["admin"])


def test_night_overtime_carries_the_night_premium(api, tokens):
    """22:00 → 01:00, so the checkout is before the check-in and all three hours are night hours:
    150% + 30% + 20%."""
    _att("HML-STF", "2026-06-10", "08:00", "01:00", 3)
    _, b = api("GET", "/api/hr/overtime?period=2026-06", tokens["admin"])
    r = _rows(b)["HML-STF"]
    assert r["nightHours"] == 3
    assert r["units"] == pytest.approx(6.0)


def test_the_taxable_part_is_only_the_ordinary_rate(api, tokens):
    """Circular 111/2013: the premium above the normal rate is exempt from PIT. Four hours of
    overtime are four hours of taxable wage however many multiples they were paid at."""
    _att("HML-STF", "2026-06-14", "08:00", "12:00", 4)          # Sunday, 200%
    _, b = api("GET", "/api/hr/overtime?period=2026-06", tokens["admin"])
    r = _rows(b)["HML-STF"]
    assert r["taxableUnits"] == 4.0 and r["units"] == 8.0


# ── who may see it ───────────────────────────────────────────────────────────────────────────────

def test_you_see_your_own_overtime(api, tokens):
    _att("HML-STF", "2026-06-10", "08:00", "19:00", 2)
    st, b = api("GET", "/api/hr/overtime?period=2026-06", tokens["staff"])
    assert st == 200
    assert set(_rows(b)) == {"HML-STF"}


def test_a_manager_sees_their_own_reports_and_no_one_else(api, tokens):
    _att("HML-STF", "2026-06-10", "08:00", "19:00", 2)          # reports to mgr@
    _att("HML-OTH", "2026-06-10", "08:00", "19:00", 2)          # reports to admin@
    _, b = api("GET", "/api/hr/overtime?period=2026-06", tokens["mgr"])
    assert set(_rows(b)) == {"HML-STF"}


def test_management_sees_the_whole_company(api, tokens):
    _att("HML-STF", "2026-06-10", "08:00", "19:00", 2)
    _att("HML-OTH", "2026-06-10", "08:00", "19:00", 2)
    _, b = api("GET", "/api/hr/overtime?period=2026-06", tokens["management"])
    assert set(_rows(b)) == {"HML-STF", "HML-OTH"}


def test_a_colleague_never_appears_in_your_own_view(api, tokens):
    _att("HML-OTH", "2026-06-10", "08:00", "19:00", 2)
    _, b = api("GET", "/api/hr/overtime?period=2026-06", tokens["staff"])
    assert "HML-OTH" not in _rows(b)


def test_a_junk_period_falls_back_rather_than_erroring(api, tokens):
    st, b = api("GET", "/api/hr/overtime?period=not-a-month", tokens["admin"])
    assert st == 200 and len(b["period"]) == 7


# ── the caps (Art. 107) ──────────────────────────────────────────────────────────────────────────

def _decide(api, token, aid, **body):
    return api("POST", "/api/attendance/%d/ot" % aid, token, dict({"decision": "approve"}, **body))


def test_a_lawful_approval_goes_straight_through(api, tokens):
    aid = _att("HML-STF", "2026-06-10", "08:00", "20:00", 3, status="pending")
    st, b = _decide(api, tokens["mgr"], aid)
    assert st == 200 and b["otStatus"] == "approved" and b["overCap"] == []


def test_five_hours_in_one_day_is_refused_until_somebody_says_why(api, tokens):
    """Art. 107(2)(b) caps a day's overtime at half the normal hours. The approval is blocked, but
    the record is untouched — hours worked were worked, and deleting them just moves the liability
    off the books."""
    aid = _att("HML-STF", "2026-06-10", "08:00", "22:00", 5, status="pending")
    st, b = _decide(api, tokens["mgr"], aid)
    assert st == 422, b
    assert b["capBreach"] is True and [x["cap"] for x in b["breaches"]] == ["day"]
    assert db.get_attendance(aid)["ot_status"] == "pending"
    assert db.get_attendance(aid)["ot_hours"] == 5, "the hours themselves must survive the refusal"


def test_the_monthly_cap_counts_what_is_already_approved(api, tokens):
    for d in range(1, 11):                                       # 10 days × 4h = 40h, exactly lawful
        _att("HML-STF", "2026-06-%02d" % d, "08:00", "21:00", 4)
    aid = _att("HML-STF", "2026-06-20", "08:00", "21:00", 1, status="pending")
    st, b = _decide(api, tokens["mgr"], aid)
    assert st == 422
    assert "month" in [x["cap"] for x in b["breaches"]]
    assert b["monthHours"] == 41


def test_exactly_forty_hours_is_still_lawful(api, tokens):
    for d in range(1, 10):                                       # 9 × 4 = 36
        _att("HML-STF", "2026-06-%02d" % d, "08:00", "21:00", 4)
    aid = _att("HML-STF", "2026-06-20", "08:00", "21:00", 4, status="pending")   # → exactly 40
    st, b = _decide(api, tokens["mgr"], aid)
    assert st == 200, b


def test_an_over_cap_approval_needs_a_reason_and_is_named_in_the_audit(api, tokens):
    aid = _att("HML-STF", "2026-06-10", "08:00", "22:00", 5, status="pending")
    st, b = _decide(api, tokens["mgr"], aid, override="Emergency chiller shutdown at the client site")
    assert st == 200, b
    assert b["overCap"] == ["day"]
    assert db.get_attendance(aid)["ot_status"] == "approved"
    trail = [a for a in db.list_collection("audit") if a.get("target") == "attendance/%d" % aid]
    assert any("OVER THE STATUTORY CAP" in a["detail"] and "chiller" in a["detail"]
               for a in trail)


def test_the_annual_cap_is_two_hundred_unless_the_company_has_elected_three(api, tokens):
    for d in range(1, 13):                                       # 12 months × ~17h ≈ 204h
        _att("HML-STF", "2026-%02d-05" % d, "08:00", "21:00", 4)
        _att("HML-STF", "2026-%02d-06" % d, "08:00", "21:00", 4)
        _att("HML-STF", "2026-%02d-07" % d, "08:00", "21:00", 4)
        _att("HML-STF", "2026-%02d-08" % d, "08:00", "21:00", 4)
        _att("HML-STF", "2026-%02d-09" % d, "08:00", "21:00", 4)   # 20h a month = 240h a year
    aid = _att("HML-STF", "2026-06-25", "08:00", "21:00", 1, status="pending")
    st, b = _decide(api, tokens["mgr"], aid)
    assert st == 422 and "year" in [x["cap"] for x in b["breaches"]]
    db.set_setting("portal_otAnnualCap", "300")
    st, b = _decide(api, tokens["mgr"], aid)
    assert "year" not in [x["cap"] for x in b.get("breaches", [])]


def test_rejecting_overtime_is_never_blocked_by_a_cap(api, tokens):
    """The cap is a reason to say no, so it must never be a reason you cannot say no."""
    for d in range(1, 11):
        _att("HML-STF", "2026-06-%02d" % d, "08:00", "21:00", 4)
    aid = _att("HML-STF", "2026-06-20", "08:00", "21:00", 6, status="pending")
    st, b = api("POST", "/api/attendance/%d/ot" % aid, tokens["mgr"], {"decision": "reject"})
    assert st == 200 and b["otStatus"] == "rejected"


def test_you_still_cannot_approve_your_own_overtime_over_the_cap(api, tokens):
    aid = _att("HML-MGR", "2026-06-10", "08:00", "22:00", 5, status="pending")
    st, _ = _decide(api, tokens["mgr"], aid, override="because I want to")
    assert st == 403


# ── the annual-cap setting ───────────────────────────────────────────────────────────────────────

def test_the_annual_cap_defaults_to_the_ordinary_two_hundred():
    db.set_setting("portal_otAnnualCap", "")
    assert app._ot_annual_cap() == overtime.CAP_YEAR_HOURS


def test_the_three_hundred_hour_election_is_a_recorded_decision():
    db.set_setting("portal_otAnnualCap", "300")
    assert app._ot_annual_cap() == 300
    db.set_setting("portal_otAnnualCap", "")


# ── the summary must agree with the approval path about what a lawful day is ─────────────────────

def test_lawful_sunday_shutdown_work_is_not_reported_as_a_statutory_breach(api, tokens):
    """The approval path passes day_kind, so 8h of Sunday work is correctly allowed under Decree
    145/2020 Art. 60. The SUMMARY did not — it took max(byDate) and let cap_check default to a
    normal day's 4-hour ceiling — so the same lawful hours came back as a breach and were printed
    into the audit pack that goes to the client."""
    db.update_employee("HML-STF", {"schedule": "", "managerEmail": "mgr@humiley.com"})
    _att("HML-STF", "2026-08-02", "08:00", "16:00", 8)                 # 2026-08-02 is a Sunday
    _, r = api("GET", "/api/hr/overtime?period=2026-08", tokens["admin"])
    row = [x for x in r["rows"] if x["empId"] == "HML-STF"]
    assert row, r
    day = [b for b in row[0]["breaches"] if b["cap"] == "day"]
    assert not day, "a rest day is capped at 12 total hours, not 4 of overtime: %s" % day


def test_the_same_eight_hours_on_a_weekday_IS_a_breach(api, tokens):
    """…and the guard must not simply stop reporting. Monday still caps at 4."""
    db.update_employee("HML-STF", {"schedule": "", "managerEmail": "mgr@humiley.com"})
    _att("HML-STF", "2026-08-03", "08:00", "16:00", 8)         # Monday
    _, r = api("GET", "/api/hr/overtime?period=2026-08", tokens["admin"])
    row = [x for x in r["rows"] if x["empId"] == "HML-STF"][0]
    day = [b for b in row["breaches"] if b["cap"] == "day"]
    assert day, "eight hours of overtime on a working day exceeds Art. 107"
    assert day[0]["date"] == "2026-08-03", "and it names WHICH day"


def test_the_breach_names_the_day_and_its_kind(api, tokens):
    db.update_employee("HML-STF", {"schedule": "", "managerEmail": "mgr@humiley.com"})
    _att("HML-STF", "2026-08-03", "08:00", "16:00", 8)
    _, r = api("GET", "/api/hr/overtime?period=2026-08", tokens["admin"])
    b = [x for x in [y for y in r["rows"] if y["empId"] == "HML-STF"][0]["breaches"]
         if x["cap"] == "day"][0]
    assert b["dayKind"] == "normal"
    assert "Art. 107" in b["message"]
