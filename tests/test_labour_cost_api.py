"""Labour cost per project, end to end.

labour_cost.py proves the apportionment. This proves the parts only the server can answer: that the
cost comes from the SIGNED pay run when one exists and says so when it does not, that a day recorded
at check-in reaches the right project, and that nobody below Approver can read what people cost.
"""
import pytest

import db
import payroll_calc as pc


@pytest.fixture(autouse=True)
def _clean():
    before = {e["id"]: {"salary": e.get("salary"), "status": e.get("status")}
              for e in db.list_employees()}
    conn = db.get_conn()
    conn.execute("DELETE FROM attendance")
    conn.execute("DELETE FROM collections WHERE coll IN ('payruns','pm_projects','pm_resources')")
    conn.commit()
    conn.close()
    yield
    conn = db.get_conn()
    conn.execute("DELETE FROM attendance")
    conn.execute("DELETE FROM collections WHERE coll IN ('payruns','pm_projects','pm_resources')")
    conn.commit()
    conn.close()
    for eid, v in before.items():
        db.update_employee(eid, v)


def _day(emp_id="HML-STF", date="2026-08-03", project=None):
    conn = db.get_conn()
    cur = conn.execute(
        "INSERT INTO attendance (emp_id,name,dept,date,clock_in,clock_out,status,project) "
        "VALUES (?,?,?,?,?,?,?,?)",
        (emp_id, "Staff One", "Engineering", date, "08:00", "17:00", "on-time", project))
    conn.commit()
    rid = cur.lastrowid
    conn.close()
    return rid


def _project(pid, name):
    db.put_collection_item("pm_projects", {"id": pid, "name": name})


def _signed_run(api, tokens, emp_ids=("HML-STF",), gross=20_000_000, period="August 2026"):
    lines = []
    for e in emp_ids:
        c = pc.compute(gross=gross, working_days=22)
        db.update_employee(e, {"salary": gross})
        lines.append({"empId": e, "name": e, "dept": "Engineering", "contractGross": gross,
                      "gross": c["grossPay"], "net": c["net"], "pit": c["pit"], "calc": c})
    st, b = api("POST", "/api/coll/payruns", tokens["admin"],
                {"period": period, "scope": "company", "lines": lines})
    assert st == 200, b
    db.put_collection_item("payruns", dict(b["item"], status="Finalised"))
    return b["item"]["id"]


def _only(emp_ids):
    """Cost exactly these people this month. The report covers every active employee with a salary,
    so a test about proportions has to say who is in the denominator instead of inheriting it."""
    keep = set(emp_ids)
    for e in db.list_employees():
        if e["id"] not in keep:
            db.update_employee(e["id"], {"salary": 0})


def _get(api, tokens, period="2026-08", who="admin"):
    return api("GET", "/api/hr/labour-cost?period=" + period, tokens[who])


# ── what a person cost ───────────────────────────────────────────────────────────────────────────

def test_a_signed_month_is_costed_from_the_run_and_says_so(api, tokens):
    """The signed run is frozen, e-signed and already carries employer contributions and overtime.
    Anything else is a stand-in."""
    _signed_run(api, tokens)
    _project("P1", "Cleanroom Phase 2")
    _day(project="P1")
    st, b = _get(api, tokens)
    assert st == 200, b
    assert b["signed"] is True and b["provisional"] is False
    assert b["costBasis"] == "signed pay run"
    assert b["projects"][0]["cost"] > 20_000_000, "employer cost exceeds gross"


def test_an_unsigned_month_is_marked_provisional_rather_than_quietly_estimated(api, tokens):
    """Pricing a tender off an unsigned month is fine. Doing it without knowing it is unsigned is
    the failure this flag exists for."""
    db.update_employee("HML-STF", {"salary": 20_000_000})
    st, b = _get(api, tokens, period="2026-09")
    assert st == 200
    assert b["signed"] is False and b["provisional"] is True
    assert "not been signed" in b["costBasis"]


# ── which job ────────────────────────────────────────────────────────────────────────────────────

def test_a_day_recorded_at_check_in_reaches_the_right_project(api, tokens):
    _project("P1", "Cleanroom Phase 2")
    _signed_run(api, tokens)
    for d in ("2026-08-03", "2026-08-04"):
        _day(date=d, project="P1")
    _, b = _get(api, tokens)
    row = [p for p in b["projects"] if p["projectId"] == "P1"][0]
    assert row["name"] == "Cleanroom Phase 2"
    assert row["basis"] == "recorded"


def test_check_in_can_record_the_project_and_is_never_blocked_by_it(api, tokens, monkeypatch):
    """Somebody at a site gate at 06:00 must always be able to clock in — an unknown project leaves
    the day unattributed, it does not refuse them.

    The company clock is frozen because the punch time was hardcoded at 08:00: between midnight and
    08:00 Vietnam time the server correctly refused it as a future punch, and this test failed for
    reasons that had nothing to do with projects."""
    import app
    from datetime import datetime as _dt, timedelta as _td
    fixed = _dt(2026, 7, 18, 9, 5)
    monkeypatch.setattr(app.Handler, "_vn_now", staticmethod(lambda: fixed))
    monkeypatch.setattr(app.Handler, "_vn_day",
                        staticmethod(lambda offset_days=0:
                                     (fixed + _td(days=offset_days)).strftime("%Y-%m-%d")))
    st, b = api("POST", "/api/attendance/checkin", tokens["staff"],
                {"time": "08:00", "project": "NO-SUCH-PROJECT"})
    assert st == 200, b
    rows = [a for a in db.list_attendance(emp_id="HML-STF") if a.get("project")]
    assert rows and rows[0]["project"] == "NO-SUCH-PROJECT"


def test_days_nobody_attributed_show_up_as_unattributed_not_spread_over_the_rest(api, tokens):
    _project("P1", "Cleanroom")
    _signed_run(api, tokens)
    _day(date="2026-08-03", project="P1")
    for d in ("2026-08-04", "2026-08-05", "2026-08-06"):
        _day(date=d)
    _, b = _get(api, tokens)
    by = {p["projectId"]: p for p in b["projects"]}
    assert "unassigned" in by
    assert by["unassigned"]["name"] == "Not attributed to a project"
    assert by["P1"]["cost"] < by["unassigned"]["cost"], "1 day of 4, not the whole month"


def test_the_project_register_fills_in_for_somebody_with_no_recorded_days(api, tokens):
    _project("P1", "Cleanroom")
    _signed_run(api, tokens)
    db.put_collection_item("pm_resources",
                           {"id": "r1", "name": "Staff One", "projectId": "P1", "allocationPct": 100})
    _, b = _get(api, tokens)
    row = [p for p in b["projects"] if p["projectId"] == "P1"][0]
    assert row["basis"] == "allocated", "an estimate must not be presented as a timesheet"


def test_the_report_says_how_much_of_it_rests_on_recorded_fact(api, tokens):
    """The share is over EVERYBODY costed that month, so the scenario has to be pinned: the first
    version asserted 100% and passed alone but failed in a full run, because other suites leave
    other employees carrying a salary and they arrive as unattributed cost. A share that silently
    depends on what ran before it is not measuring what it claims to."""
    _only(["HML-STF"])
    _project("P1", "Cleanroom")
    _signed_run(api, tokens)
    _day(project="P1")
    _, b = _get(api, tokens)
    assert b["peopleCounted"] == 1
    assert b["recordedShare"] == 100.0


def test_the_recorded_share_falls_when_somebody_records_nothing(api, tokens):
    """The other half of the same claim — the number has to move."""
    _only(["HML-STF", "HML-OTH"])
    _project("P1", "Cleanroom")
    _signed_run(api, tokens, emp_ids=("HML-STF", "HML-OTH"))
    _day(emp_id="HML-STF", project="P1")
    _, b = _get(api, tokens)
    assert b["peopleCounted"] == 2
    assert b["recordedShare"] == 50.0


# ── the money has to add up ──────────────────────────────────────────────────────────────────────

def test_every_dong_lands_on_exactly_one_project_line(api, tokens):
    _project("P1", "A")
    _project("P2", "B")
    _signed_run(api, tokens, emp_ids=("HML-STF", "HML-OTH"), gross=19_999_999)
    _day(emp_id="HML-STF", date="2026-08-03", project="P1")
    _day(emp_id="HML-STF", date="2026-08-04", project="P2")
    _day(emp_id="HML-OTH", date="2026-08-03", project="P1")
    _, b = _get(api, tokens)
    assert b["reconciles"] is True
    assert b["booked"] == b["total"] == sum(p["cost"] for p in b["projects"])


def test_a_month_with_nothing_in_it_reports_zero_rather_than_failing(api, tokens):
    st, b = _get(api, tokens, period="2019-01")
    assert st == 200 and b["reconciles"] is True


# ── who may read it ──────────────────────────────────────────────────────────────────────────────

def test_a_line_manager_cannot_read_what_people_cost(api, tokens):
    assert _get(api, tokens, who="mgr")[0] == 403
    assert _get(api, tokens, who="staff")[0] == 403


def test_a_month_that_is_not_a_month_is_refused_rather_than_guessed(api, tokens):
    assert api("GET", "/api/hr/labour-cost", tokens["admin"])[0] == 400
    assert api("GET", "/api/hr/labour-cost?period=banana", tokens["admin"])[0] == 400


def test_a_written_out_month_name_is_understood_too(api, tokens):
    """The pay run stores 'August 2026'; a caller should not have to know that."""
    _signed_run(api, tokens)
    st, b = api("GET", "/api/hr/labour-cost?period=August%202026", tokens["admin"])
    assert st == 200 and b["ym"] == "2026-08" and b["signed"] is True
