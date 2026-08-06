"""Effective-dated employee history — giving the portal a memory.

The system knew what was true; it did not know what WAS true. Every employee edit was an in-place
UPDATE keeping no prior value, so "what were we paying him in March", "when did Engineering go from
6 to 9" and the labour management book Decree 145/2020 Art. 3 requires were all unanswerable — and
worse, a March payslip reprinted in September silently answered with September's salary.

This is the table that fixes it, and the access rules that keep salary history from becoming a second
compensation database.
"""
import pytest

import app
import db


@pytest.fixture(autouse=True)
def _clean_history():
    """History is append-only by design, so tests clear it directly rather than through the API."""
    conn = db.get_conn()
    conn.execute("DELETE FROM emp_events")
    conn.commit()
    conn.close()
    yield
    db.update_employee("HML-OTH", {"managerEmail": "admin@humiley.com"})


# ── the question that could not be answered ──────────────────────────────────────────────────────

def test_what_were_we_paying_him_in_march(api, tokens):
    """The headline. Three raises, and the portal must give the right answer for each date."""
    for eff, amount in (("2026-01-01", 20_000_000), ("2026-04-01", 24_000_000), ("2026-07-01", 30_000_000)):
        api("PATCH", "/api/employees/HML-STF", tokens["admin"],
            {"salary": amount, "_effective": eff, "_reason": "annual review"})
    assert db.emp_value_asof("HML-STF", "salary", "2026-03-31") == "20000000"
    assert db.emp_value_asof("HML-STF", "salary", "2026-05-15") == "24000000"
    assert db.emp_value_asof("HML-STF", "salary", "2026-12-31") == "30000000"
    # …and honestly nothing at all before recording began, which is not the same as "it was zero".
    assert db.emp_value_asof("HML-STF", "salary", "2025-06-01") is None


def test_a_promotion_and_a_transfer_are_dated_too(api, tokens):
    api("PATCH", "/api/employees/HML-STF", tokens["admin"],
        {"title": "Senior Engineer", "dept": "Engineering", "_effective": "2026-05-01"})
    assert db.emp_value_asof("HML-STF", "title", "2026-06-01") == "Senior Engineer"
    assert db.emp_value_asof("HML-STF", "title", "2026-04-01") is None


def test_the_effective_date_is_the_business_date_not_the_typing_date(api, tokens):
    """A rise agreed today may take force next month. Recording when it was typed would make every
    retrospective or forward-dated change wrong."""
    api("PATCH", "/api/employees/HML-STF", tokens["admin"],
        {"salary": 41_000_000, "_effective": "2026-11-01"})
    ev = db.list_emp_events(emp_id="HML-STF", field="salary")[0]
    assert ev["effective"] == "2026-11-01"
    assert ev["ts"][:4] != "2026-11", "ts records when it was entered, effective when it applies"


def test_a_change_with_no_effective_date_takes_today(api, tokens):
    api("PATCH", "/api/employees/HML-STF", tokens["admin"], {"grade": "G6"})
    ev = db.list_emp_events(emp_id="HML-STF", field="grade")[0]
    assert ev["effective"] == db.now_iso()[:10]


def test_the_reason_is_kept(api, tokens):
    api("PATCH", "/api/employees/HML-STF", tokens["admin"],
        {"salary": 26_000_000, "_reason": "promotion to Senior"})
    assert db.list_emp_events(emp_id="HML-STF", field="salary")[0]["reason"] == "promotion to Senior"


def test_control_fields_never_reach_the_employee_record(api, tokens):
    api("PATCH", "/api/employees/HML-STF", tokens["admin"],
        {"salary": 27_000_000, "_effective": "2026-03-01", "_reason": "x"})
    row = db.get_employee("HML-STF")
    assert "_effective" not in row and "_reason" not in row


def test_only_the_six_history_fields_are_tracked(api, tokens):
    """Tracking everything turns the table into a slow copy of the record. These six move money,
    route approvals or decide reporting; the rest are in the audit log."""
    api("PATCH", "/api/employees/HML-STF", tokens["admin"], {"phone": "0900000000", "note": "hello"})
    assert db.list_emp_events(emp_id="HML-STF") == []
    assert set(db.EMP_HISTORY_FIELDS) == {"salary", "grade", "title", "dept", "managerEmail", "status"}


def test_re_saving_the_same_SALARY_writes_no_event(api, tokens):
    """The text-comparison trap. `salary` is a SQLite REAL, so the stored value returns as 30000000.0
    while the browser sends the integer 30000000 — compared as text those differ, and every re-save of
    an unchanged salary invented a raise in both the audit trail and the history. A history that
    fabricates events is worse than none. Found by driving the real UI, not by this suite."""
    api("PATCH", "/api/employees/HML-STF", tokens["admin"], {"salary": 30_000_000})
    n = len(db.list_emp_events(emp_id="HML-STF", field="salary"))
    assert n == 1
    api("PATCH", "/api/employees/HML-STF", tokens["admin"], {"salary": 30_000_000})
    api("PATCH", "/api/employees/HML-STF", tokens["admin"], {"salary": 30_000_000.0})
    assert len(db.list_emp_events(emp_id="HML-STF", field="salary")) == n, \
        "an unchanged salary must never appear as a change"


def test_a_real_salary_change_is_still_recorded_after_that_fix(api, tokens):
    """The guard must not swing the other way and swallow genuine raises."""
    db.update_employee("HML-STF", {"salary": 19_000_000})    # baseline, writes no event
    api("PATCH", "/api/employees/HML-STF", tokens["admin"], {"salary": 30_000_000})
    api("PATCH", "/api/employees/HML-STF", tokens["admin"], {"salary": 30_000_001})
    vals = [e["new_value"] for e in db.list_emp_events(emp_id="HML-STF", field="salary")]
    assert len(vals) == 2, "two genuine raises must both be recorded"
    assert "30000001" in vals[0] and "30000000" in vals[1]


def test_an_unchanged_value_writes_no_event(api, tokens):
    api("PATCH", "/api/employees/HML-STF", tokens["admin"], {"title": "Steady"})
    n = len(db.list_emp_events(emp_id="HML-STF"))
    api("PATCH", "/api/employees/HML-STF", tokens["admin"], {"title": "Steady"})
    assert len(db.list_emp_events(emp_id="HML-STF")) == n


# ── who may read a salary history ────────────────────────────────────────────────────────────────

def _hist(api, token, eid="HML-STF"):
    return api("GET", "/api/employees/%s/history" % eid, token)


def test_management_sees_the_whole_history(api, tokens):
    api("PATCH", "/api/employees/HML-STF", tokens["admin"], {"salary": 33_000_000})
    st, b = _hist(api, tokens["management"])
    assert st == 200, b
    assert any(e["field"] == "salary" for e in b["events"])
    assert b["payHidden"] is False


def test_you_always_see_your_own_pay_history(api, tokens):
    """It is your pay. Being able to check what you were paid, and from when, is the point."""
    api("PATCH", "/api/employees/HML-STF", tokens["admin"], {"salary": 34_000_000})
    st, b = _hist(api, tokens["staff"])
    assert st == 200, b
    assert any(e["field"] == "salary" and e["new_value"] == "34000000" for e in b["events"])


def test_a_manager_sees_their_report_without_the_pay_fields(api, tokens):
    db.update_employee("HML-OTH", {"managerEmail": "mgr@humiley.com"})
    api("PATCH", "/api/employees/HML-OTH", tokens["admin"], {"salary": 35_000_000, "title": "Engineer II"})
    st, b = _hist(api, tokens["mgr"], "HML-OTH")
    assert st == 200, b
    assert b["payHidden"] is True
    assert not any(e["field"] in ("salary", "grade") for e in b["events"]), \
        "the history endpoint must not become a way around the roster's pay scoping"
    assert any(e["field"] == "title" for e in b["events"]), "…but the rest of the trail is theirs to see"


def test_a_stranger_gets_nothing(api, tokens):
    db.update_employee("HML-OTH", {"managerEmail": "admin@humiley.com"})
    st, _ = _hist(api, tokens["other"], "HML-STF")
    assert st == 403


# ── backfill from the pay runs ───────────────────────────────────────────────────────────────────

def test_backfill_reconstructs_history_from_finalised_pay_runs(api, tokens):
    """Every finalised run froze dept, title, grade and gross per employee — the history for those
    months already existed, it was just never queryable."""
    for period, gross, title in (("January 2026", 20_000_000, "Engineer"),
                                 ("February 2026", 20_000_000, "Engineer"),
                                 ("March 2026", 25_000_000, "Senior Engineer")):
        api("POST", "/api/coll/payruns", tokens["admin"], {
            "scope": "company", "period": period, "status": "Finalised",
            "lines": [{"empId": "HML-STF", "name": "Staff One", "dept": "Engineering",
                       "title": title, "grade": "G3", "gross": gross}]})
    st, b = api("POST", "/api/hr/history-backfill", tokens["admin"], {})
    assert st == 200, b
    assert b["events"] > 0
    # January set it, February did not change it, March raised it.
    assert db.emp_value_asof("HML-STF", "salary", "2026-02-15") == "20000000"
    assert db.emp_value_asof("HML-STF", "salary", "2026-03-15") == "25000000"
    assert db.emp_value_asof("HML-STF", "title", "2026-03-15") == "Senior Engineer"
    months = {e["effective"] for e in db.list_emp_events(emp_id="HML-STF", field="salary")}
    assert "2026-02-01" not in months, "an unchanged month must not create a fake change"


def test_backfill_is_idempotent(api, tokens):
    api("POST", "/api/coll/payruns", tokens["admin"], {
        "scope": "company", "period": "April 2026", "status": "Finalised",
        "lines": [{"empId": "HML-STF", "dept": "Engineering", "title": "Engineer",
                   "grade": "G3", "gross": 21_000_000}]})
    api("POST", "/api/hr/history-backfill", tokens["admin"], {})
    n = db.emp_events_count()
    st, b = api("POST", "/api/hr/history-backfill", tokens["admin"], {})
    assert st == 200 and b["events"] == 0
    assert db.emp_events_count() == n


def test_a_backfilled_row_says_it_was_inferred(api, tokens):
    """An inferred row must never be mistaken for one somebody recorded at the time."""
    api("POST", "/api/coll/payruns", tokens["admin"], {
        "scope": "company", "period": "May 2026", "status": "Finalised",
        "lines": [{"empId": "HML-STF", "dept": "Engineering", "title": "Engineer",
                   "grade": "G3", "gross": 22_000_000}]})
    api("POST", "/api/hr/history-backfill", tokens["admin"], {})
    assert all(e["source"] == "backfill" for e in db.list_emp_events(emp_id="HML-STF"))


def test_only_an_admin_may_backfill(api, tokens):
    st, _ = api("POST", "/api/hr/history-backfill", tokens["mgr"], {})
    assert st == 403
