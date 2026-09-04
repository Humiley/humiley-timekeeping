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
    """History is append-only by design, so tests clear it directly rather than through the API.

    Pay runs go too: the backfill reads every run in the collection, so a run left behind by an
    earlier test silently becomes an input to the next one's history — which is how a test asserting
    "no salary was recorded for July" passed on March's figure instead.
    """
    conn = db.get_conn()
    conn.execute("DELETE FROM emp_events")
    conn.execute("DELETE FROM collections WHERE coll = 'payruns'")
    conn.commit()
    conn.close()
    yield
    db.update_employee("HML-OTH", {"managerEmail": "admin@humiley.com"})


# ── the question that could not be answered ──────────────────────────────────────────────────────

def test_what_were_we_paying_him_in_march(api, tokens):
    """The headline. Three raises, and the portal must give the right answer for each date."""
    # A baseline none of the three amounts below, set directly so it writes no event: otherwise a
    # test in another file that happens to leave the salary at 20,000,000 turns the first PATCH into
    # a no-op, no event is recorded, and this fails for a reason unrelated to what it is testing.
    db.update_employee("HML-STF", {"salary": 1_000_000})
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

def _run(api, tokens, period, salary=None, title="Engineer", grade="G3", status="Finalised",
         gross=99_000_000):
    """A finalised pay run with one line. `gross` is deliberately a number that is NOT the salary —
    on a real line it is P1+P2+P3+welfare — so any test that passes because the backfill read `gross`
    as somebody's pay will fail loudly."""
    line = {"empId": "HML-STF", "name": "Staff One", "dept": "Engineering",
            "title": title, "grade": grade, "gross": gross}
    if salary is not None:
        line["contractGross"] = salary
    st, b = api("POST", "/api/coll/payruns", tokens["admin"],
                {"scope": "company", "period": period, "lines": [line]})
    # _coll_add forces every new run to "Pending Approval" whatever the client asks for — a run only
    # becomes Finalised when a Director e-signs it. Set the status the way that signature would,
    # rather than pretending the create call can.
    db.put_collection_item("payruns", dict(b["item"], status=status))
    return st, b


def test_backfill_reconstructs_history_from_finalised_pay_runs(api, tokens):
    """Every finalised run froze dept, title, grade and the contractual salary per employee — the
    history for those months already existed, it was just never queryable."""
    _run(api, tokens, "January 2026", salary=20_000_000)
    _run(api, tokens, "February 2026", salary=20_000_000)
    _run(api, tokens, "March 2026", salary=25_000_000, title="Senior Engineer")
    st, b = api("POST", "/api/hr/history-backfill", tokens["admin"], {})
    assert st == 200, b
    assert b["events"] > 0
    # January set it, February did not change it, March raised it.
    assert db.emp_value_asof("HML-STF", "salary", "2026-02-15") == "20000000"
    assert db.emp_value_asof("HML-STF", "salary", "2026-03-15") == "25000000"
    assert db.emp_value_asof("HML-STF", "title", "2026-03-15") == "Senior Engineer"
    months = {e["effective"] for e in db.list_emp_events(emp_id="HML-STF", field="salary")}
    assert "2026-02-01" not in months, "an unchanged month must not create a fake change"


def test_the_backfill_reads_the_contractual_salary_and_never_the_payslip_total(api, tokens):
    """The blocker this replaced. A line's `gross` is P1+P2+P3+welfare — it carries the KPI factor,
    ₫1,530,000 of fixed welfare and any one-off bonus. Recorded as salary it understates every
    ordinary month, and a Tết bonus becomes a raise followed by an identical pay cut, permanently,
    in a table with no delete."""
    _run(api, tokens, "June 2026", salary=20_000_000, gross=41_530_000)   # gross inflated by a bonus
    api("POST", "/api/hr/history-backfill", tokens["admin"], {})
    assert db.emp_value_asof("HML-STF", "salary", "2026-06-15") == "20000000"
    assert not any(e["new_value"] == "41530000"
                   for e in db.list_emp_events(emp_id="HML-STF", field="salary"))


def test_a_run_with_no_contractual_salary_contributes_no_salary_row(api, tokens):
    """Runs finalised before the salary was recorded on the line. A gap in the history is honest; a
    figure derived from the payslip total is not. The job fields still backfill, and the response
    says how many lines it could not price."""
    _run(api, tokens, "July 2026", salary=None, title="Foreman")
    st, b = api("POST", "/api/hr/history-backfill", tokens["admin"], {})
    assert b["salaryUnavailable"] == 1
    assert db.emp_value_asof("HML-STF", "salary", "2026-07-15") is None
    assert db.emp_value_asof("HML-STF", "title", "2026-07-15") == "Foreman"


def test_a_run_the_director_refused_to_sign_is_not_history(api, tokens):
    """Every run is created as Pending Approval and only a Director's e-signature makes it Finalised.
    An unsigned draft is a proposal, and seeding the permanent record from one writes a figure nobody
    approved into a table with no delete."""
    _run(api, tokens, "August 2026", salary=99_000_000, status="Pending Approval")
    st, b = api("POST", "/api/hr/history-backfill", tokens["admin"], {})
    assert st == 200, b
    assert b["runs"] == 0, "an unsigned run is not an input to the history"
    assert db.list_emp_events(emp_id="HML-STF", field="salary") == []


def test_the_signed_run_wins_over_the_draft_that_preceded_it(api, tokens):
    """The realistic shape: HR prepares a run with a mistyped figure, the Director refuses it, HR
    prepares a corrected one. Both sit in the collection under the same period."""
    _run(api, tokens, "August 2026", salary=99_000_000, status="Pending Approval")
    _run(api, tokens, "August 2026", salary=26_000_000, status="Finalised")
    api("POST", "/api/hr/history-backfill", tokens["admin"], {})
    vals = [e["new_value"] for e in db.list_emp_events(emp_id="HML-STF", field="salary")]
    assert vals == ["26000000"], "the refused figure must not appear at all"


def test_two_finalised_runs_in_one_month_cannot_both_write_the_same_dated_row(api, tokens):
    """A company run and a later individual correction share a period. Without adding each written
    row to the seen-set inside the pass, the second one writes a duplicate same-day event and the
    as-of query resolves it by insertion order."""
    _run(api, tokens, "September 2026", salary=27_000_000)
    _run(api, tokens, "September 2026", salary=28_000_000)
    api("POST", "/api/hr/history-backfill", tokens["admin"], {})
    sept = [e for e in db.list_emp_events(emp_id="HML-STF", field="salary")
            if e["effective"] == "2026-09-01"]
    assert len(sept) == 1


def test_backfill_is_idempotent(api, tokens):
    _run(api, tokens, "April 2026", salary=21_000_000)
    api("POST", "/api/hr/history-backfill", tokens["admin"], {})
    n = db.emp_events_count()
    st, b = api("POST", "/api/hr/history-backfill", tokens["admin"], {})
    assert st == 200 and b["events"] == 0
    assert db.emp_events_count() == n


def test_a_backfilled_row_says_it_was_inferred(api, tokens):
    """An inferred row must never be mistaken for one somebody recorded at the time."""
    _run(api, tokens, "May 2026", salary=22_000_000)
    api("POST", "/api/hr/history-backfill", tokens["admin"], {})
    assert all(e["source"] == "backfill" for e in db.list_emp_events(emp_id="HML-STF"))


def test_only_an_admin_may_backfill(api, tokens):
    st, _ = api("POST", "/api/hr/history-backfill", tokens["mgr"], {})
    assert st == 403


# ── repairing the rows the first, wrong backfill wrote ───────────────────────────────────────────

def _bad_backfill_row(emp_id, field, value, effective):
    """A row exactly as the defective backfill left it: inferred, and asserting a payslip TOTAL as
    somebody's salary."""
    db.add_emp_event(emp_id, field, None, value, effective=effective,
                     reason="Backfilled from the March 2026 pay run", source="backfill")


def test_the_repair_removes_the_wrong_inferred_rows_and_rebuilds_them(api, tokens):
    """The production scenario: an earlier backfill already wrote 18,530,000 — the payslip total —
    as this employee's March salary. The corrected pay-run line says 20,000,000."""
    _bad_backfill_row("HML-STF", "salary", 18_530_000, "2026-03-01")
    assert db.emp_value_asof("HML-STF", "salary", "2026-03-15") == "18530000"
    _run(api, tokens, "March 2026", salary=20_000_000, gross=18_530_000)
    st, b = api("POST", "/api/hr/history-repair", tokens["admin"], {})
    assert st == 200, b
    assert b["removed"] == 1
    assert db.emp_value_asof("HML-STF", "salary", "2026-03-15") == "20000000"


def test_the_repair_never_touches_a_row_somebody_recorded(api, tokens):
    """source='edit' rows are evidence of a decision. Only the reconstruction is rebuilt."""
    api("PATCH", "/api/employees/HML-STF", tokens["admin"],
        {"salary": 31_000_000, "_effective": "2026-05-01", "_reason": "annual review"})
    _bad_backfill_row("HML-STF", "salary", 18_530_000, "2026-03-01")
    api("POST", "/api/hr/history-repair", tokens["admin"], {})
    kept = db.list_emp_events(emp_id="HML-STF", field="salary")
    assert [e["new_value"] for e in kept] == ["31000000"]
    assert kept[0]["source"] == "edit"


def test_the_removal_is_itself_written_into_the_audit_chain(api, tokens):
    """Somebody will ask why a figure on their profile changed. The answer has to exist."""
    _bad_backfill_row("HML-STF", "salary", 18_530_000, "2026-03-01")
    api("POST", "/api/hr/history-repair", tokens["admin"], {})
    trail = [a for a in db.list_collection("audit")
             if a.get("action") == "Employment history rebuilt"]
    assert trail, "the rebuild must leave a record"
    assert any("18530000" in a["detail"] and "HML-STF" in a["detail"] for a in trail)


def test_the_repair_is_safe_when_the_bad_backfill_was_never_run(api, tokens):
    """Most likely case for this install. It must remove nothing and still rebuild cleanly."""
    _run(api, tokens, "March 2026", salary=20_000_000)
    st, b = api("POST", "/api/hr/history-repair", tokens["admin"], {})
    assert st == 200 and b["removed"] == 0
    assert db.emp_value_asof("HML-STF", "salary", "2026-03-15") == "20000000"


def test_the_repair_is_idempotent(api, tokens):
    _bad_backfill_row("HML-STF", "salary", 18_530_000, "2026-03-01")
    _run(api, tokens, "March 2026", salary=20_000_000)
    api("POST", "/api/hr/history-repair", tokens["admin"], {})
    n = db.emp_events_count()
    st, b = api("POST", "/api/hr/history-repair", tokens["admin"], {})
    assert st == 200
    assert db.emp_events_count() == n


def test_only_an_admin_may_repair(api, tokens):
    st, _ = api("POST", "/api/hr/history-repair", tokens["mgr"], {})
    assert st == 403
