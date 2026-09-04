"""The defects an adversarial review of Wave 1 + emp_events found in live code.

Fourteen findings survived triple independent refutation; deduplicated they are the nine fixed here.
Each test states the failure it prevents, because the value of a regression test is that somebody
reading it later knows what it is standing guard over.
"""
import pytest

import app
import db


# ── a manager could no longer see their own pay ──────────────────────────────────────────────────

def test_a_manager_still_sees_their_own_salary_on_their_own_record(api, tokens):
    """Splitting the roster branches dropped the "own record is always full" rule for managers, so a
    department head's own salary and grade were stripped from their own row. Their payslip then
    priced them at the grade band mid-point, printed a complete invented PIT and net, and badged
    none of it — while an ordinary staff member on the same screen saw the correct figure."""
    db.update_employee("HML-MGR", {"salary": 22_000_000, "grade": "G6", "taxId": "8899001122"})
    st, b = api("GET", "/api/employees", tokens["mgr"])
    assert st == 200
    mine = next(e for e in b["employees"] if e["id"] == "HML-MGR")
    assert mine.get("salary") == 22_000_000
    assert mine.get("grade") == "G6"
    assert mine.get("taxId") == "8899001122"


def test_a_manager_still_cannot_see_a_report_s_salary(api, tokens):
    """The fix must not swing back the other way."""
    db.update_employee("HML-STF", {"salary": 19_000_000})
    _, b = api("GET", "/api/employees", tokens["mgr"])
    other = next(e for e in b["employees"] if e["id"] == "HML-STF")
    assert "salary" not in other and "grade" not in other


def test_staff_still_see_their_own_record_in_full(api, tokens):
    db.update_employee("HML-STF", {"salary": 19_000_000, "personalId": "0790001112"})
    _, b = api("GET", "/api/employees", tokens["staff"])
    mine = next(e for e in b["employees"] if e["id"] == "HML-STF")
    assert mine.get("salary") == 19_000_000 and mine.get("personalId") == "0790001112"


# ── deleting an employee erased their employment history ─────────────────────────────────────────

def test_an_employee_with_recorded_history_cannot_simply_be_deleted(api, tokens):
    """emp_events carried ON DELETE CASCADE and employee_references did not count it, so a DELETE
    erased the effective-dated record and then wrote an audit row saying "no history on record" —
    the one document a settlement dispute and Decree 145/2020 Art. 3 are answered from."""
    db.create_employee({"id": "HML-DEL", "name": "Duplicate Row", "email": "dup@humiley.com",
                        "role": "staff", "level": "staff"})
    db.add_emp_event("HML-DEL", "salary", None, 25_000_000, effective="2026-08-01")
    try:
        refs = db.employee_references("HML-DEL")
        assert "employment-history record" in refs
        st, b = api("DELETE", "/api/employees/HML-DEL", tokens["admin"])
        assert st != 200, b
        assert len(db.list_emp_events(emp_id="HML-DEL")) == 1
    finally:
        conn = db.get_conn()
        conn.execute("DELETE FROM emp_events WHERE emp_id = 'HML-DEL'")
        conn.commit()
        conn.close()
        db.delete_employee("HML-DEL")


def test_the_history_table_no_longer_cascades_with_the_employee(api, tokens):
    """Defence in depth behind the reference guard: an append-only legal record must outlive the row
    it describes. An orphan is recoverable; an erasure is not."""
    conn = db.get_conn()
    fks = conn.execute("PRAGMA foreign_key_list(emp_events)").fetchall()
    conn.close()
    assert fks == [], "emp_events must not be deleted along with the employee row"


# ── a pay run priced from a guess ────────────────────────────────────────────────────────────────

def test_a_pay_run_containing_someone_with_no_salary_is_refused(api, tokens):
    """`_payComputed` prices an employee with no salary at their grade's MID-POINT — a full gross,
    PIT and statutory footprint invented for a figure nobody agreed. The browser guard covered one
    of the three buttons that create a run; this is the boundary that covers all of them."""
    db.create_employee({"id": "HML-NOS", "name": "No Salary Yet", "email": "nos@humiley.com",
                        "role": "staff", "level": "staff", "title": "Engineer"})
    try:
        st, b = api("POST", "/api/coll/payruns", tokens["admin"], {
            "period": "August 2026",
            "lines": [{"empId": "HML-NOS", "name": "No Salary Yet", "gross": 22_000_000}]})
        assert st == 400, b
        assert "No Salary Yet" in (b.get("error") or "")
    finally:
        db.delete_employee("HML-NOS")


def test_a_pay_run_for_people_who_do_have_salaries_still_goes_through(api, tokens):
    db.update_employee("HML-STF", {"salary": 20_000_000})
    st, b = api("POST", "/api/coll/payruns", tokens["admin"], {
        "period": "August 2026",
        "lines": [{"empId": "HML-STF", "name": "Staff One", "gross": 18_530_000,
                   "contractGross": 20_000_000}]})
    assert st == 200, b
    assert b["item"]["status"] == "Pending Approval"


# ── an employee's own payslip could never reach the signed record ────────────────────────────────

def test_an_employee_can_read_their_own_finalised_payslip_line(api, tokens):
    """Pay runs are management-only, which is right for the register and the company totals — but it
    also meant an employee's own payslip never reached the frozen, Director-signed line, so their
    My Payslip screen recomputed the month live and showed today's salary under an old heading."""
    db.update_employee("HML-STF", {"salary": 20_000_000})
    db.update_employee("HML-OTH", {"salary": 30_000_000})
    _, b = api("POST", "/api/coll/payruns", tokens["admin"], {
        "period": "July 2026", "scope": "company",
        "lines": [{"empId": "HML-STF", "name": "Staff One", "contractGross": 20_000_000,
                   "net": 17_000_000, "calc": {"net": 17_000_000}},
                  {"empId": "HML-OTH", "name": "Other Staff", "contractGross": 30_000_000,
                   "net": 25_000_000}]})
    db.put_collection_item("payruns", dict(b["item"], status="Finalised"))
    st, got = api("GET", "/api/coll/payruns", tokens["staff"])
    assert st == 200, got
    lines = [l for it in got["items"] for l in it["lines"]]
    assert [l["empId"] for l in lines] == ["HML-STF"], "only their own line, nobody else's"
    assert lines[0]["net"] == 17_000_000


def test_an_employee_never_sees_an_unsigned_draft_of_their_own_payslip(api, tokens):
    """A run is created Pending Approval and only a Director's e-signature makes it a payslip."""
    api("POST", "/api/coll/payruns", tokens["admin"], {
        "period": "November 2026", "scope": "company",
        "lines": [{"empId": "HML-STF", "name": "Staff One", "contractGross": 20_000_000}]})
    _, got = api("GET", "/api/coll/payruns", tokens["staff"])
    assert not any(it["period"] == "November 2026" for it in got["items"])


def test_the_company_totals_never_reach_an_employee(api, tokens):
    """The self-scoped read must hand back a line, not the payroll register."""
    _, b = api("POST", "/api/coll/payruns", tokens["admin"], {
        "period": "October 2026", "scope": "company", "gross": 500_000_000, "net": 420_000_000,
        "count": 30, "erCost": 610_000_000,
        "lines": [{"empId": "HML-STF", "name": "Staff One", "contractGross": 20_000_000}]})
    db.put_collection_item("payruns", dict(b["item"], status="Finalised"))
    _, got = api("GET", "/api/coll/payruns", tokens["staff"])
    row = next(it for it in got["items"] if it["period"] == "October 2026")
    for k in ("gross", "net", "count", "erCost", "preparedBy"):
        assert k not in row, "%s is a company figure, not this employee's" % k


# ── the leave working-day bound was dead whenever holidays existed ────────────────────────────────

def test_the_working_day_bound_survives_a_configured_holiday_register(api, tokens):
    """`db.get_setting` already json-decodes, so json.loads on its result raised TypeError on every
    deployment that had actually saved a holiday register — swallowed by a bare except, leaving the
    bound at the raw calendar span. The check ran only when there were no holidays to apply it to."""
    db.set_setting("portal_holidays", [{"date": "2026-09-02", "name": "National Day"}])
    try:
        # Mon 31 Aug – Fri 4 Sep: 5 calendar days, 2 Sep is a public holiday → 4 working days.
        st, b = api("POST", "/api/leave", tokens["staff"], {
            "type": "Annual", "startDate": "2026-08-31", "endDate": "2026-09-04",
            "days": 5, "reason": "t"})
        assert st == 400, b
        st, b = api("POST", "/api/leave", tokens["staff"], {
            "type": "Annual", "startDate": "2026-08-31", "endDate": "2026-09-04",
            "days": 4, "reason": "t"})
        assert st == 200, b
    finally:
        db.set_setting("portal_holidays", [])


def test_a_range_that_is_all_holiday_consumes_no_leave_at_all(api, tokens):
    """Tết. Nine calendar days of which none are working days: the old fallback let all nine be
    booked and deducted from a twelve-day entitlement."""
    db.set_setting("portal_holidays", [{"date": "2026-02-%02d" % d} for d in range(16, 21)])
    try:
        st, b = api("POST", "/api/leave", tokens["staff"], {
            "type": "Annual", "startDate": "2026-02-14", "endDate": "2026-02-22",
            "days": 9, "reason": "t"})
        assert st == 400, b
        assert "no leave" in (b.get("error") or "").lower()
    finally:
        db.set_setting("portal_holidays", [])


def test_a_factory_saturday_is_a_working_day_for_leave_too(api, tokens):
    """Rest days come from the requester's own schedule, the same rule the browser applies."""
    _, sch = api("POST", "/api/coll/schedules", tokens["admin"],
                 {"name": "Factory Shift B", "days": "Mon – Sat", "dept": "Factory"})
    db.update_employee("HML-STF", {"schedule": "Factory Shift B"})
    try:
        # Fri 4 Sep – Sat 5 Sep: two working days on Mon–Sat, one on Mon–Fri.
        st, b = api("POST", "/api/leave", tokens["staff"], {
            "type": "Annual", "startDate": "2026-09-04", "endDate": "2026-09-05",
            "days": 2, "reason": "t"})
        assert st == 200, b
    finally:
        db.update_employee("HML-STF", {"schedule": ""})
        api("DELETE", "/api/coll/schedules/" + sch["item"]["id"], tokens["admin"])
