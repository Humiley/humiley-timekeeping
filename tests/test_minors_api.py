"""Young workers, end to end.

minors.py proves the law. This proves the parts only the server can: that the Art. 144 register is
built from the records the company already keeps, that it is not readable by everybody, and — the
one that would actually stop something happening — that the overtime approval path REFUSES a minor
rather than offering the approver an override.
"""
import pytest

import db
import minors as m


@pytest.fixture(autouse=True)
def _clean():
    # The WHOLE row, not the handful of fields this file means to touch. Restoring a subset is how
    # a fixture in this suite has broken unrelated tests before: _setup below rewrites name, dob,
    # address and more, and every later suite then sees a different employee than it seeded.
    before = {e["id"]: dict(e) for e in db.list_employees()}

    def wipe():
        conn = db.get_conn()
        conn.execute("DELETE FROM collections WHERE coll = 'certificates'")
        conn.execute("DELETE FROM attendance")
        conn.commit()
        conn.close()
    wipe()
    yield
    wipe()
    for eid, v in before.items():
        db.update_employee(eid, v)


def _age(n):
    """A date of birth making somebody n years old in 2026."""
    return "%d-01-01" % (2026 - n)


def _health(emp_id, issued="2026-02-01", result="Fit for work"):
    db.put_collection_item("certificates", {
        "id": "cert-" + emp_id, "empId": emp_id, "kind": "health_check",
        "issued": issued, "expires": "2027-02-01", "result": result})


# ── who may read it ──────────────────────────────────────────────────────────────────────────────

def test_it_lists_dates_of_birth_and_health_results_so_it_is_management_and_above(api, tokens):
    assert api("GET", "/api/hr/minors", tokens["staff"])[0] == 403
    assert api("GET", "/api/hr/minors", tokens["mgr"])[0] == 403
    assert api("GET", "/api/hr/minors", tokens["management"])[0] == 200


def test_it_needs_a_session(api, tokens):
    assert api("GET", "/api/hr/minors", None)[0] == 401


# ── the register itself ──────────────────────────────────────────────────────────────────────────

def test_a_workforce_of_adults_produces_the_sentence_an_auditor_wants(api, tokens):
    for e in db.list_employees():
        db.update_employee(e["id"], {"dob": _age(35)})
    code, r = api("GET", "/api/hr/minors?asOf=2026-08-08", tokens["management"])
    assert code == 200, r
    assert r["minors"] == 0 and r["unknownDob"] == 0
    assert "requires no monitoring book" in r["statement"]
    assert r["headcount"] > 0, "it says how many people that covers"


def test_a_minor_appears_with_the_four_columns_article_144_names(api, tokens):
    for e in db.list_employees():
        db.update_employee(e["id"], {"dob": _age(35)})
    db.update_employee("HML-STF", {"dob": _age(16), "title": "Phụ việc cơ khí"})
    _health("HML-STF")
    _, r = api("GET", "/api/hr/minors?asOf=2026-08-08", tokens["management"])
    assert r["minors"] == 1
    row = [x for x in r["rows"] if x["empId"] == "HML-STF"][0]
    assert row["dob"] == _age(16)
    assert row["work"] == "Phụ việc cơ khí"
    assert row["healthChecks"] and row["healthChecks"][0]["result"] == "Fit for work"
    assert row["limits"]["maxDaily"] == 8


def test_a_minor_with_no_health_examination_on_file_is_a_gap(api, tokens):
    for e in db.list_employees():
        db.update_employee(e["id"], {"dob": _age(35)})
    db.update_employee("HML-STF", {"dob": _age(16)})
    _, r = api("GET", "/api/hr/minors?asOf=2026-08-08", tokens["management"])
    row = [x for x in r["rows"] if x["empId"] == "HML-STF"][0]
    assert any("health examination" in i for i in row["issues"])
    assert r["gaps"] >= 1


def test_somebody_with_no_date_of_birth_is_listed_separately_from_a_minor(api, tokens):
    for e in db.list_employees():
        db.update_employee(e["id"], {"dob": _age(35)})
    db.update_employee("HML-STF", {"dob": ""})
    db.update_employee("HML-OTH", {"dob": _age(17)})
    _, r = api("GET", "/api/hr/minors?asOf=2026-08-08", tokens["management"])
    assert r["unknownDob"] == 1 and r["minors"] == 1
    assert "cannot be shown either way" in r["statement"]


def test_an_inactive_employee_is_not_in_the_book(api, tokens):
    """The book records who the company employs, not who it once did."""
    for e in db.list_employees():
        db.update_employee(e["id"], {"dob": _age(35)})
    db.update_employee("HML-STF", {"dob": _age(16), "status": "Inactive"})
    try:
        _, r = api("GET", "/api/hr/minors?asOf=2026-08-08", tokens["management"])
        assert not [x for x in r["rows"] if x["empId"] == "HML-STF"]
    finally:
        db.update_employee("HML-STF", {"status": "Active"})


def test_the_register_cites_article_144_in_both_languages(api, tokens):
    _, r = api("GET", "/api/hr/minors", tokens["management"])
    assert "Art. 144" in r["basis"] and "Điều 144" in r["basisVn"]


# ── the refusal that stops something happening ───────────────────────────────────────────────────

def _pending_ot(emp_id="HML-STF", hours=2.0, date="2026-08-03"):
    conn = db.get_conn()
    cur = conn.execute(
        "INSERT INTO attendance (emp_id,name,dept,date,clock_in,clock_out,status,ot_hours,ot_status) "
        "VALUES (?,?,?,?,?,?,?,?,?)",
        (emp_id, "Staff One", "Engineering", date, "08:00", "19:00", "on-time", hours, "pending"))
    conn.commit()
    rid = cur.lastrowid
    conn.close()
    return rid


def test_overtime_for_an_employee_under_fifteen_is_refused_not_offered_as_an_override(api, tokens):
    """Art. 107's ceilings come back as a 422 the approver may override by saying why. Art. 146(1)
    admits no exception, so this must not be one of those — and the portal, which already had the
    date of birth loaded, never looked at it."""
    db.update_employee("HML-STF", {"dob": _age(14), "managerEmail": "mgr@humiley.com"})
    aid = _pending_ot()
    code, b = api("POST", "/api/attendance/%d/ot" % aid, tokens["management"],
                  {"decision": "approve"})
    assert code == 422, b
    assert b.get("ageRefusal") is True
    assert "146(1)" in b["basis"]
    assert "prohibition" in b["error"]


def test_the_refusal_cannot_be_overridden_the_way_an_art_107_breach_can(api, tokens):
    db.update_employee("HML-STF", {"dob": _age(14), "managerEmail": "mgr@humiley.com"})
    aid = _pending_ot()
    code, b = api("POST", "/api/attendance/%d/ot" % aid, tokens["management"],
                  {"decision": "approve", "override": "Urgent client shutdown"})
    assert code == 422, "an override must not buy past Art. 146"
    assert b.get("ageRefusal") is True


def test_a_fifteen_to_eighteen_year_old_is_refused_too_on_this_companys_work(api, tokens):
    db.update_employee("HML-STF", {"dob": _age(16), "managerEmail": "mgr@humiley.com"})
    aid = _pending_ot()
    code, b = api("POST", "/api/attendance/%d/ot" % aid, tokens["management"],
                  {"decision": "approve"})
    assert code == 422 and "146(2)" in b["basis"]


def test_an_employee_with_no_date_of_birth_is_refused_rather_than_assumed_adult(api, tokens):
    db.update_employee("HML-STF", {"dob": "", "managerEmail": "mgr@humiley.com"})
    aid = _pending_ot()
    code, b = api("POST", "/api/attendance/%d/ot" % aid, tokens["management"],
                  {"decision": "approve"})
    assert code == 422 and b.get("ageRefusal") is True
    assert b["overridable"] is True, "a gap in the record, not a prohibition"
    assert "Record the date of birth" in b["error"]


def test_the_approver_may_attest_an_unknown_age_and_it_lands_in_the_audit_chain(api, tokens):
    """Refusing outright would stop the company approving ANY overtime until every date of birth
    was typed in — which is how a correct check gets switched off. The attestation is named."""
    db.update_employee("HML-STF", {"dob": "", "managerEmail": "mgr@humiley.com"})
    aid = _pending_ot()
    code, b = api("POST", "/api/attendance/%d/ot" % aid, tokens["management"],
                  {"decision": "approve", "override": "I know this employee is 34."})
    assert code == 200, b
    rows = [a for a in db.list_collection("audit")
            if str(a.get("target") or "") == "attendance/" + str(aid)]
    assert rows, "the approval is audited"


def test_no_attestation_can_buy_past_a_real_minor(api, tokens):
    """The override is only ever available for the unknown case."""
    db.update_employee("HML-STF", {"dob": _age(16), "managerEmail": "mgr@humiley.com"})
    aid = _pending_ot()
    code, b = api("POST", "/api/attendance/%d/ot" % aid, tokens["management"],
                  {"decision": "approve", "override": "I know this employee is 34."})
    assert code == 422 and b["overridable"] is False


def test_an_adults_overtime_still_approves_normally(api, tokens):
    db.update_employee("HML-STF", {"dob": _age(30), "managerEmail": "mgr@humiley.com"})
    aid = _pending_ot()
    code, b = api("POST", "/api/attendance/%d/ot" % aid, tokens["management"],
                  {"decision": "approve"})
    assert code == 200, b


def test_rejecting_a_minors_overtime_is_never_blocked(api, tokens):
    """Refusing to record the refusal would be absurd — and would leave the request pending."""
    db.update_employee("HML-STF", {"dob": _age(14), "managerEmail": "mgr@humiley.com"})
    aid = _pending_ot()
    code, b = api("POST", "/api/attendance/%d/ot" % aid, tokens["management"],
                  {"decision": "reject"})
    assert code == 200, b


def test_the_refusal_is_readable_in_vietnamese(api, tokens):
    db.update_employee("HML-STF", {"dob": _age(14), "managerEmail": "mgr@humiley.com"})
    aid = _pending_ot()
    _, b = api("POST", "/api/attendance/%d/ot" % aid, tokens["management"],
               {"decision": "approve"})
    assert b["errorVn"] and any(ord(c) > 127 for c in b["errorVn"])


# ── the Art. 146 ceiling on ORDINARY hours, not just overtime ────────────────────────────────────

def _freeze(monkeypatch, when="2026-08-03 17:00"):
    """The checkout endpoint finds the open row by the COMPANY's today/yesterday, so the clock has
    to agree with the date under test."""
    import app as _app
    from datetime import datetime as _dt, timedelta as _td
    fixed = _dt.strptime(when, "%Y-%m-%d %H:%M")
    monkeypatch.setattr(_app.Handler, "_vn_now", staticmethod(lambda: fixed))
    monkeypatch.setattr(_app.Handler, "_vn_day",
                        staticmethod(lambda offset_days=0:
                                     (fixed + _td(days=offset_days)).strftime("%Y-%m-%d")))


def _breaches():
    return [a for a in db.list_collection("audit")
            if "Art. 146 daily limit" in str(a.get("action") or "")]


def _clear_att():
    conn = db.get_conn(); conn.execute("DELETE FROM attendance"); conn.commit(); conn.close()


def test_a_minor_worked_over_the_daily_ceiling_is_recorded_as_a_breach(api, tokens, monkeypatch):
    """minors.daily_hours_ok existed and NOTHING called it — the overtime refusal only covers hours
    somebody asked to be paid extra for, so a ten-hour ordinary day for a 16-year-old passed
    unremarked. It RECORDS rather than refuses: the hours were worked, and refusing to close the day
    would move them off the books, which is the opposite of what Art. 146 is for."""
    _freeze(monkeypatch)
    db.update_employee("HML-MGT", {"dob": _age(16)})
    _clear_att()
    before = len(_breaches())
    db.clock_in("HML-MGT", "2026-08-03", "06:00")
    code, b = api("POST", "/api/attendance/checkout", tokens["management"], {"time": "16:00"})
    assert code == 200, b                       # the day is still recorded
    after = _breaches()
    assert len(after) == before + 1, "the breach is named in the audit chain"
    assert "8h ceiling" in after[-1]["detail"]
    assert "146" in after[-1]["detail"]


def test_an_adult_working_the_same_day_raises_nothing(api, tokens, monkeypatch):
    _freeze(monkeypatch)
    db.update_employee("HML-MGT", {"dob": _age(35)})
    _clear_att()
    before = len(_breaches())
    db.clock_in("HML-MGT", "2026-08-03", "06:00")
    assert api("POST", "/api/attendance/checkout", tokens["management"], {"time": "16:00"})[0] == 200
    assert len(_breaches()) == before


def test_a_minor_inside_the_ceiling_raises_nothing(api, tokens, monkeypatch):
    _freeze(monkeypatch, "2026-08-03 16:30")
    db.update_employee("HML-MGT", {"dob": _age(16)})
    _clear_att()
    before = len(_breaches())
    db.clock_in("HML-MGT", "2026-08-03", "08:00")
    assert api("POST", "/api/attendance/checkout", tokens["management"], {"time": "16:00"})[0] == 200
    assert len(_breaches()) == before, "eight hours is exactly the ceiling for a 15-to-18-year-old"


def test_an_unknown_date_of_birth_raises_nothing_rather_than_guessing(api, tokens, monkeypatch):
    """It cannot be a breach of a ceiling nobody can establish. The gap is the young-worker
    register's finding, not the attendance log's."""
    _freeze(monkeypatch)
    db.update_employee("HML-MGT", {"dob": ""})
    _clear_att()
    before = len(_breaches())
    db.clock_in("HML-MGT", "2026-08-03", "06:00")
    assert api("POST", "/api/attendance/checkout", tokens["management"], {"time": "16:00"})[0] == 200
    assert len(_breaches()) == before
