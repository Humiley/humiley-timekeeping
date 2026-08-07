"""Correcting an attendance record — and the fact that it was corrected.

Two things changed at once. There was never a way to correct one of these rows, while check-out told
an employee whose check-out was missed to "ask HR to correct your attendance record" — a facility
that did not exist. And attendance now feeds payroll, because approved overtime reaches the payslip,
so an edit here moves money and has to behave like one.
"""
import pytest

import db


def _att(emp_id="HML-STF", date="2026-08-03", cin="08:00", cout="19:00", hours=2,
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
    for _ in range(2):
        conn = db.get_conn()
        conn.execute("DELETE FROM attendance")
        conn.execute("DELETE FROM collections WHERE coll = 'payruns'")
        conn.commit()
        conn.close()
        yield
        return


def _amend(api, token, aid, **body):
    return api("POST", "/api/attendance/%d/amend" % aid, token, body)


# ── the correction itself ────────────────────────────────────────────────────────────────────────

def test_a_missed_check_out_can_finally_be_corrected(api, tokens):
    """The case the check-out guard has been pointing at: a shift that would read as 19 hours is
    refused and the employee is told to ask HR. This is what HR does about it."""
    aid = _att(cout="—", hours=0, status="")
    st, b = _amend(api, tokens["mgr"], aid, clock_out="18:30",
                   reason="Forgot to check out; site sign-out sheet shows 18:30")
    assert st == 200, b
    rec = db.get_attendance(aid)
    assert rec["clock_out"] == "18:30"
    assert rec["hrs"] == "10h 30m", "the worked span is recomputed, never left disagreeing with the clock"


def test_the_correction_says_who_when_and_why(api, tokens):
    aid = _att()
    _amend(api, tokens["mgr"], aid, clock_out="18:00", reason="Client site sign-out sheet")
    rec = db.get_attendance(aid)
    assert rec["amended_by"] == "Dept Manager"
    assert rec["amend_reason"] == "Client site sign-out sheet"
    assert rec["amended_at"] and rec["amend_count"] == 1


def test_a_second_correction_is_counted(api, tokens):
    aid = _att()
    _amend(api, tokens["mgr"], aid, clock_out="18:00", reason="first correction")
    _amend(api, tokens["mgr"], aid, clock_out="18:45", reason="second correction")
    assert db.get_attendance(aid)["amend_count"] == 2


def test_the_before_and_after_land_in_the_audit_chain(api, tokens):
    """A correction nobody can see is indistinguishable from a falsification."""
    aid = _att(cout="19:00")
    _amend(api, tokens["mgr"], aid, clock_out="17:30", reason="Left early for a client meeting")
    trail = [a for a in db.list_collection("audit")
             if a.get("target") == "attendance/%d" % aid and a.get("action") == "Attendance corrected"]
    assert trail
    d = trail[-1]["detail"]
    assert "19:00" in d and "17:30" in d and "client meeting" in d


def test_a_correction_without_a_reason_is_refused(api, tokens):
    aid = _att()
    st, b = _amend(api, tokens["mgr"], aid, clock_out="18:00", reason="")
    assert st == 400
    assert "reason" in (b.get("error") or "").lower()


def test_changing_nothing_changes_nothing(api, tokens):
    aid = _att(cout="19:00")
    st, b = _amend(api, tokens["mgr"], aid, clock_out="19:00", reason="no actual change")
    assert st == 200 and b.get("unchanged") is True
    assert db.get_attendance(aid)["amend_count"] in (None, 0)


def test_a_time_that_is_not_a_time_is_refused(api, tokens):
    aid = _att()
    st, _ = _amend(api, tokens["mgr"], aid, clock_out="half past six", reason="a valid reason")
    assert st == 400


def test_overtime_hours_outside_the_possible_range_are_refused(api, tokens):
    aid = _att()
    st, _ = _amend(api, tokens["mgr"], aid, ot_hours=30, reason="a valid reason")
    assert st == 400


# ── the overtime decision no longer describes what happened ──────────────────────────────────────

def test_moving_the_times_reopens_an_approved_overtime_decision(api, tokens):
    """The manager approved a particular stretch of work. Move it and they have not approved what is
    now there — and since the overtime window decides the night premium, the money moved too."""
    aid = _att(cout="19:00", hours=2, status="approved")
    st, b = _amend(api, tokens["mgr"], aid, clock_out="23:00",
                   reason="Corrected from the site log — the shift ran to 23:00")
    assert st == 200 and b["otReopened"] is True
    assert db.get_attendance(aid)["ot_status"] == "pending"


def test_correcting_the_overtime_hours_reopens_it_too(api, tokens):
    aid = _att(hours=8, status="approved")
    _, b = _amend(api, tokens["mgr"], aid, ot_hours=3, reason="Typed 8 instead of 3")
    assert b["otReopened"] is True
    assert db.get_attendance(aid)["ot_status"] == "pending"


def test_correcting_the_hours_to_zero_leaves_no_overtime_to_decide(api, tokens):
    aid = _att(hours=2, status="approved")
    _amend(api, tokens["mgr"], aid, ot_hours=0, reason="No overtime was worked that day")
    assert db.get_attendance(aid)["ot_status"] in ("", None)


def test_a_correction_that_touches_no_times_leaves_the_approval_alone(api, tokens):
    aid = _att(hours=2, status="approved")
    _, b = _amend(api, tokens["mgr"], aid, ot_reason="Client shutdown, per PO 4411",
                  reason="Recording the reason the manager gave verbally")
    assert b["otReopened"] is False
    assert db.get_attendance(aid)["ot_status"] == "approved"


# ── a signed month is closed ─────────────────────────────────────────────────────────────────────

def test_attendance_in_a_finalised_month_cannot_be_corrected(api, tokens):
    """The figures built on it are signed. Changing their basis afterwards, with nothing to show for
    it, is the thing dual control exists to prevent."""
    db.update_employee("HML-STF", {"salary": 20_000_000})
    _, run = api("POST", "/api/coll/payruns", tokens["admin"], {
        "period": "August 2026", "scope": "company",
        "lines": [{"empId": "HML-STF", "name": "Staff One", "contractGross": 20_000_000}]})
    db.put_collection_item("payruns", dict(run["item"], status="Finalised"))
    aid = _att(date="2026-08-03")
    st, b = _amend(api, tokens["mgr"], aid, clock_out="20:00", reason="a valid reason")
    assert st == 403
    assert "finalised" in (b.get("error") or "").lower()
    assert db.get_attendance(aid)["clock_out"] == "19:00", "the record is untouched"


def test_an_open_month_is_still_correctable_when_another_month_is_closed(api, tokens):
    db.update_employee("HML-STF", {"salary": 20_000_000})
    _, run = api("POST", "/api/coll/payruns", tokens["admin"], {
        "period": "July 2026", "scope": "company",
        "lines": [{"empId": "HML-STF", "name": "Staff One", "contractGross": 20_000_000}]})
    db.put_collection_item("payruns", dict(run["item"], status="Finalised"))
    aid = _att(date="2026-08-03")
    st, _ = _amend(api, tokens["mgr"], aid, clock_out="20:00", reason="a valid reason")
    assert st == 200


# ── who may correct one ──────────────────────────────────────────────────────────────────────────

def test_a_staff_member_cannot_correct_their_own_attendance(api, tokens):
    aid = _att()
    st, _ = _amend(api, tokens["staff"], aid, clock_out="23:00", reason="I definitely worked late")
    assert st == 403


def test_a_manager_who_is_not_theirs_cannot_correct_it(api, tokens):
    aid = _att(emp_id="HML-OTH")
    st, _ = _amend(api, tokens["mgr"], aid, clock_out="20:00", reason="a valid reason")
    assert st == 403


def test_management_can_correct_anybody_s(api, tokens):
    aid = _att(emp_id="HML-OTH")
    st, _ = _amend(api, tokens["management"], aid, clock_out="20:00", reason="a valid reason")
    assert st == 200


def test_a_record_that_does_not_exist_is_a_404_not_a_500(api, tokens):
    st, _ = _amend(api, tokens["admin"], 99_999, clock_out="20:00", reason="a valid reason")
    assert st == 404


# ── what may NOT be changed ──────────────────────────────────────────────────────────────────────

def test_the_date_cannot_be_moved(api, tokens):
    """Moving a shift to another day moves it between months and therefore between pay runs."""
    aid = _att(date="2026-08-03")
    _amend(api, tokens["mgr"], aid, date="2026-07-31", clock_out="18:00", reason="a valid reason")
    assert db.get_attendance(aid)["date"] == "2026-08-03"


def test_the_record_cannot_be_reassigned_to_another_employee(api, tokens):
    aid = _att(emp_id="HML-STF")
    _amend(api, tokens["mgr"], aid, emp_id="HML-OTH", clock_out="18:00", reason="a valid reason")
    assert db.get_attendance(aid)["emp_id"] == "HML-STF"


def test_correcting_your_own_record_is_allowed_but_named(api, tokens):
    """At this size the Managing Director is the top of the chain, so a rule nobody can satisfy would
    mean their record could never be fixed. It is named in the trail instead."""
    aid = _att(emp_id="HML-ADM")
    st, _ = _amend(api, tokens["admin"], aid, clock_out="20:00",
                   reason="Site visit ran late; corrected from the visitor log")
    assert st == 200
    trail = [a for a in db.list_collection("audit")
             if a.get("target") == "attendance/%d" % aid]
    assert "SELF-CORRECTION" in trail[-1]["detail"]


def test_the_storage_layer_refuses_to_move_a_shift_even_if_asked_directly(api, tokens):
    """Defence in depth behind the endpoint's field filter: whatever a caller passes, only the times,
    the overtime figure and the status are writable. A date change would move the shift between pay
    runs; an emp_id change would make it somebody else's."""
    aid = _att(date="2026-08-03", emp_id="HML-STF")
    db.amend_attendance(aid, {"date": "2026-01-01", "emp_id": "HML-OTH", "clock_out": "18:00"},
                        actor="Test", reason="direct call")
    rec = db.get_attendance(aid)
    assert rec["date"] == "2026-08-03" and rec["emp_id"] == "HML-STF"
    assert rec["clock_out"] == "18:00", "the fields that ARE allowed still land"
