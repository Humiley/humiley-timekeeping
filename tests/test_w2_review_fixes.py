"""What the adversarial review of the Wave 2 work found in live code.

Forty findings, sixteen survived triple refutation, twelve distinct defects — most of them mine from
the same day. Each test below names the failure it stands guard over, because a regression test whose
purpose has to be reconstructed is only half a test.
"""
import pytest

import app
import contracts
import datespan
import db
import overtime
import settlement


def _att(emp_id="HML-STF", date="2026-08-03", cin="08:00", cout="21:00", hours=4,
         status="approved"):
    conn = db.get_conn()
    cur = conn.execute(
        "INSERT INTO attendance (emp_id,name,dept,date,clock_in,clock_out,status,ot_status,ot_hours) "
        "VALUES (?,?,?,?,?,?,?,?,?)",
        (emp_id, "Staff One", "Engineering", date, cin, cout, "on-time", status, hours))
    conn.commit()
    rid = cur.lastrowid
    conn.close()
    return rid


@pytest.fixture(autouse=True)
def _clean():
    conn = db.get_conn()
    conn.execute("DELETE FROM attendance")
    conn.execute("DELETE FROM collections WHERE coll IN ('payruns','certificates','contracts')")
    conn.commit()
    conn.close()
    db.set_setting("portal_holidays", [])
    yield
    conn = db.get_conn()
    conn.execute("DELETE FROM attendance")
    conn.execute("DELETE FROM collections WHERE coll IN ('payruns','certificates','contracts')")
    conn.commit()
    conn.close()


# ── overtime that was never worked ───────────────────────────────────────────────────────────────

def test_overtime_can_never_exceed_the_hours_somebody_was_checked_in_for(api, tokens):
    """Check-out enforced this; the correction path did not. Overtime is the TAIL of the shift, so 4
    hours against an 08:00–09:00 shift starts the window at 05:00 and buys an hour of night premium
    nobody worked — and at the extreme rolls hours onto the previous day at its holiday rate."""
    aid = _att(cout="21:00", hours=4)
    st, b = api("POST", "/api/attendance/%d/amend" % aid, tokens["mgr"],
                {"clock_out": "09:00", "reason": "Badge error — they left at 09:00"})
    assert st == 400, b
    assert "cannot exceed" in (b.get("error") or "")
    assert db.get_attendance(aid)["clock_out"] == "21:00", "the record is untouched"


def test_the_overtime_window_itself_refuses_to_start_before_the_check_in():
    """Belt and braces behind the endpoint: a row written before the validation existed, or written
    directly, must still not be payable for a window nobody was present for."""
    r = overtime.record_pay({"date": "2026-08-10", "clock_in": "08:00", "clock_out": "09:00",
                             "ot_hours": 4}, 1.0)
    assert r["hours"] == 1.0 and r["nightHours"] == 0.0
    assert r["pay"] == 1.5, "one real hour at 150%, not four with an invented night premium"


def test_a_genuine_night_stint_is_still_paid_in_full():
    """The clamp must not swing the other way: 22:00 → 01:00 is three night hours."""
    r = overtime.record_pay({"date": "2026-08-10", "clock_in": "08:00", "clock_out": "01:00",
                             "ot_hours": 3}, 1.0)
    assert r["nightHours"] == 3.0


def test_correcting_a_record_to_ADD_overtime_leaves_it_awaiting_approval(api, tokens):
    """The reopen rule keyed on "was approved", so adding overtime to a record that had none left it
    in no state at all — hours no approval queue ever showed and payroll never paid, because only
    approved overtime counts."""
    aid = _att(cout="21:00", hours=0, status="")
    st, b = api("POST", "/api/attendance/%d/amend" % aid, tokens["mgr"],
                {"ot_hours": 3, "reason": "They worked the shutdown; it was never recorded"})
    assert st == 200, b
    assert db.get_attendance(aid)["ot_status"] == "pending"


# ── the daily cap on a rest day ──────────────────────────────────────────────────────────────────

def test_eight_hours_of_overtime_on_a_sunday_is_lawful(api, tokens):
    """Art. 107(2)(b) caps overtime at half the normal hours of a working DAY. A rest day has no
    normal hours to halve — Decree 145/2020 Art. 60's 12-hour total is what binds. Applying the
    4-hour figure refused lawful shutdown work and recorded the manager as overriding the law."""
    aid = _att(date="2026-08-09", cin="08:00", cout="17:00", hours=8, status="pending")  # Sunday
    st, b = api("POST", "/api/attendance/%d/ot" % aid, tokens["mgr"], {"decision": "approve"})
    assert st == 200, b
    assert b["overCap"] == []


def test_eight_hours_on_a_weekday_still_breaches_the_daily_cap(api, tokens):
    aid = _att(date="2026-08-10", cin="08:00", cout="22:00", hours=8, status="pending")  # Monday
    st, b = api("POST", "/api/attendance/%d/ot" % aid, tokens["mgr"], {"decision": "approve"})
    assert st == 422
    assert "day" in [x["cap"] for x in b["breaches"]]


def test_thirteen_hours_on_a_rest_day_still_breaches_the_twelve_hour_ceiling():
    assert overtime.cap_check(day_hours=13, day_kind="rest")["ok"] is False
    assert overtime.cap_check(day_hours=12, day_kind="rest")["ok"] is True


# ── month arithmetic that three modules disagreed about ──────────────────────────────────────────

def test_a_lawful_thirty_six_month_contract_starting_mid_month_is_not_flagged():
    """The one I called safe and was wrong about. The day-of-month shortcut over-counted by one for
    any contract not starting on the 1st, which is roughly half of them."""
    assert contracts.term_months("2026-03-15", "2029-03-14") == 36
    assert contracts.exceeds_max_term("2026-03-15", "2029-03-14") is False


def test_a_term_of_thirty_six_months_and_one_day_does_exceed_the_ceiling():
    """Whole months cannot tell those apart, so the ceiling is compared as dates."""
    assert contracts.exceeds_max_term("2026-03-15", "2029-03-15") is True
    assert contracts.exceeds_max_term("2026-01-01", "2029-01-01") is True


def test_the_three_modules_now_share_one_month_count():
    """contracts, settlement and certificates each grew their own, and they disagreed."""
    assert contracts.term_months("2015-01-01", "2015-01-15") == 0
    assert settlement.months_between("2015-01-01", "2015-01-15") == 0
    assert datespan.whole_months("2015-01-01", "2015-01-15") == 0
    assert str(datespan.add_months("2026-01-31", 1)) == "2026-02-28"


# ── health records are not company-wide reading ──────────────────────────────────────────────────

def test_a_manager_listing_certificates_sees_only_their_own_crew(api, tokens):
    """READ_MIN let a manager reach the collection so they could check their crew before a site day.
    The raw list read was unscoped, so it handed them every employee's medical cadence instead —
    which made the review endpoint's crew scoping decorative."""
    api("POST", "/api/coll/certificates", tokens["admin"],
        {"empId": "HML-STF", "kind": "health_check", "issuedDate": "2026-05-01"})
    api("POST", "/api/coll/certificates", tokens["admin"],
        {"empId": "HML-OTH", "kind": "health_check", "issuedDate": "2026-05-01"})
    st, b = api("GET", "/api/coll/certificates", tokens["mgr"])
    assert st == 200
    assert {c["empId"] for c in b["items"]} == {"HML-STF"}, "HML-OTH does not report to this manager"


def test_a_manager_never_receives_the_scanned_certificate_itself(api, tokens):
    api("POST", "/api/coll/certificates", tokens["admin"],
        {"empId": "HML-STF", "kind": "health_check", "issuedDate": "2026-05-01",
         "file": "data:application/pdf;base64,AAAA"})
    _, b = api("GET", "/api/coll/certificates", tokens["mgr"])
    assert b["items"] and "file" not in b["items"][0]


def test_management_still_sees_the_whole_register(api, tokens):
    api("POST", "/api/coll/certificates", tokens["admin"],
        {"empId": "HML-OTH", "kind": "health_check", "issuedDate": "2026-05-01"})
    _, b = api("GET", "/api/coll/certificates", tokens["management"])
    assert any(c["empId"] == "HML-OTH" for c in b["items"])


# ── writing must need at least what reading needs ────────────────────────────────────────────────

def test_somebody_who_cannot_read_a_contract_cannot_rewrite_its_wage(api, tokens):
    """Both collections were gated on the raw `role` column, so a manager who is refused the register
    could still POST to it — and delete a contract without leaving a snapshot."""
    st, _ = api("POST", "/api/coll/contracts", tokens["mgr"],
                {"empId": "HML-STF", "type": "definite", "startDate": "2026-01-01",
                 "endDate": "2026-12-31", "salary": 1})
    assert st == 403


def test_management_can_still_write_a_contract(api, tokens):
    st, _ = api("POST", "/api/coll/contracts", tokens["management"],
                {"empId": "HML-STF", "type": "definite", "startDate": "2026-01-01",
                 "endDate": "2026-12-31"})
    assert st == 200


def test_deleting_a_contract_snapshots_it_into_the_audit_chain(api, tokens):
    _, b = api("POST", "/api/coll/contracts", tokens["admin"],
               {"empId": "HML-STF", "no": "HD-2026-777", "type": "definite",
                "startDate": "2026-01-01", "endDate": "2026-12-31"})
    api("DELETE", "/api/coll/contracts/" + b["item"]["id"], tokens["admin"])
    assert any("HD-2026-777" in str(a.get("detail") or "") for a in db.list_collection("audit"))


# ── a pay run priced from a guess, via the other door ────────────────────────────────────────────

def test_an_unsalaried_employee_cannot_be_PATCHed_into_a_pay_run(api, tokens):
    """The guard was on create only, which left the edit path as a way to add them and then have a
    Director sign it."""
    db.update_employee("HML-STF", {"salary": 20_000_000})
    db.create_employee({"id": "HML-NS2", "name": "No Salary", "email": "ns2@humiley.com",
                        "role": "staff", "level": "staff"})
    try:
        _, b = api("POST", "/api/coll/payruns", tokens["admin"], {
            "period": "August 2026",
            "lines": [{"empId": "HML-STF", "name": "Staff One", "contractGross": 20_000_000}]})
        st, b2 = api("PATCH", "/api/coll/payruns/" + b["item"]["id"], tokens["admin"],
                     dict(b["item"], lines=b["item"]["lines"] +
                          [{"empId": "HML-NS2", "name": "No Salary"}]))
        assert st == 400, b2
        assert "No Salary" in (b2.get("error") or "")
    finally:
        db.delete_employee("HML-NS2")


# ── a prorated year is not a permanent entitlement ───────────────────────────────────────────────

def test_applying_never_writes_a_prorated_figure_into_the_year_less_field(api, tokens):
    """`annualTotal` carries no year, so writing a mid-year joiner's 6 days into it would make six
    days look like their entitlement for every year afterwards."""
    db.update_employee("HML-STF", {"startDate": "2026-07-01", "annualTotal": 3})
    try:
        _, b = api("POST", "/api/hr/leave-entitlement/apply", tokens["admin"], {"year": 2026})
        assert not any(c["empId"] == "HML-STF" for c in b["changed"])
        assert db.get_employee("HML-STF")["annualTotal"] == 3
    finally:
        db.update_employee("HML-STF", {"startDate": "", "annualTotal": 12})


# ── the statutory classification fields ──────────────────────────────────────────────────────────

def test_a_line_manager_cannot_reclassify_somebody_s_working_conditions(api, tokens):
    """These four decide the annual-leave base, the health-check cadence, whether safety training is
    required and whether somebody may be kept on fixed terms indefinitely. They are legal
    classifications the company makes, not fields a line manager edits."""
    db.update_employee("HML-STF", {"workConditions": "heavy", "oshGroup": "3"})
    try:
        api("PATCH", "/api/employees/HML-STF", tokens["mgr"],
            {"workConditions": "normal", "oshGroup": "", "contractExempt": "foreign",
             "disabled": 1, "bankAcc": "999"})
        e = db.get_employee("HML-STF")
        assert e["workConditions"] == "heavy" and e["oshGroup"] == "3"
        assert not e.get("contractExempt") and not e.get("bankAcc")
    finally:
        db.update_employee("HML-STF", {"workConditions": "", "oshGroup": ""})


def test_changing_one_leaves_a_line_in_the_audit_trail(api, tokens):
    api("PATCH", "/api/employees/HML-STF", tokens["admin"], {"workConditions": "heavy"})
    try:
        assert any("workConditions" in str(a.get("detail") or "")
                   for a in db.list_collection("audit")
                   if a.get("target") == "employees/HML-STF")
    finally:
        db.update_employee("HML-STF", {"workConditions": ""})


def test_the_bank_account_number_is_masked_in_the_audit_trail(api, tokens):
    """The trail is admin-readable and must not quietly become a second copy of everyone's banking."""
    api("PATCH", "/api/employees/HML-STF", tokens["admin"], {"bankAcc": "19012345678901"})
    try:
        detail = " ".join(str(a.get("detail") or "") for a in db.list_collection("audit")
                          if a.get("target") == "employees/HML-STF")
        assert "19012345678901" not in detail
        assert "bankAcc changed" in detail
    finally:
        db.update_employee("HML-STF", {"bankAcc": ""})


def test_a_non_numeric_string_never_makes_somebody_a_person_with_disabilities(api, tokens):
    """`disabled` is read with bool(), so any non-empty string is truthy — which would silently put
    somebody on the 14-day annual-leave base and the six-month health-check cadence.

    SQLite's INTEGER affinity already converts "0" and "1", so those are not the risky inputs; a
    value it cannot convert is stored as TEXT and survives to be read as True. That is the case the
    coercion exists for, so it is the case tested — the first version of this used "0" and proved
    nothing, because the database was doing the work."""
    api("PATCH", "/api/employees/HML-STF", tokens["admin"], {"disabled": "false"})
    try:
        assert not db.get_employee("HML-STF")["disabled"], '"false" must not read as disabled'
        api("PATCH", "/api/employees/HML-STF", tokens["admin"], {"disabled": "yes"})
        assert db.get_employee("HML-STF")["disabled"] == 1
    finally:
        db.update_employee("HML-STF", {"disabled": 0})


# ── the hourly divisor and the rate must agree about the week ────────────────────────────────────

def test_the_overtime_endpoint_returns_the_employees_own_working_days(api, tokens):
    """The rate classification resolved the real schedule while the browser divided by a hardcoded
    Mon–Fri count, so a Mon–Sat employee's overtime came out about 24% too high — two halves of one
    calculation disagreeing about how many days a week somebody works."""
    _, sch = api("POST", "/api/coll/schedules", tokens["admin"],
                 {"name": "Factory Shift C", "days": "Mon – Sat", "dept": "Factory"})
    db.update_employee("HML-STF", {"schedule": "Factory Shift C"})
    _att(date="2026-08-03", cout="19:00", hours=2)
    try:
        _, b = api("GET", "/api/hr/overtime?period=2026-08", tokens["admin"])
        row = next(r for r in b["rows"] if r["empId"] == "HML-STF")
        assert row["restDays"] == [6], "Sunday only"
        assert row["workingDays"] == 26, "August 2026 has 26 Mon-Sat days"
    finally:
        db.update_employee("HML-STF", {"schedule": ""})
        api("DELETE", "/api/coll/schedules/" + sch["item"]["id"], tokens["admin"])


def test_an_office_employee_gets_the_mon_fri_count(api, tokens):
    _att(date="2026-08-03", cout="19:00", hours=2)
    _, b = api("GET", "/api/hr/overtime?period=2026-08", tokens["admin"])
    row = next(r for r in b["rows"] if r["empId"] == "HML-STF")
    assert row["restDays"] == [5, 6] and row["workingDays"] == 21


def test_a_public_holiday_is_not_a_working_day_in_the_divisor_either(api, tokens):
    db.set_setting("portal_holidays", [{"date": "2026-08-03", "name": "Test"}])
    _att(date="2026-08-04", cout="19:00", hours=2)
    _, b = api("GET", "/api/hr/overtime?period=2026-08", tokens["admin"])
    row = next(r for r in b["rows"] if r["empId"] == "HML-STF")
    assert row["workingDays"] == 20
