"""Final settlement, end to end: computed from the law, and raised as a real payable.

settlement.py proves the arithmetic. This proves the parts only the server can answer — that the
wage comes from the dated salary history rather than today's figure, that the untaken-leave days are
the PRORATED entitlement a leaver actually earned, and that somebody's final pay cannot be raised
twice.
"""
import pytest

import db


@pytest.fixture(autouse=True)
def _clean():
    before = {e["id"]: {"startDate": e.get("startDate"), "salary": e.get("salary"),
                        "annualUsed": e.get("annualUsed"), "annualTotal": e.get("annualTotal"),
                        "endDate": e.get("endDate")}
              for e in db.list_employees()}
    conn = db.get_conn()
    for c in ("exits", "payments"):
        conn.execute("DELETE FROM collections WHERE coll = ?", (c,))
    conn.execute("DELETE FROM emp_events")
    conn.commit()
    conn.close()
    yield
    conn = db.get_conn()
    for c in ("exits", "payments"):
        conn.execute("DELETE FROM collections WHERE coll = ?", (c,))
    conn.execute("DELETE FROM emp_events")
    conn.commit()
    conn.close()
    for eid, v in before.items():
        db.update_employee(eid, v)


def _exit(api, tokens, emp_id="HML-STF", last_day="2026-07-31", type_="Resignation", **kw):
    st, b = api("POST", "/api/coll/exits", tokens["admin"],
                dict({"empId": emp_id, "name": "Staff One", "lastDay": last_day,
                      "type": type_, "status": "Initiated"}, **kw))
    assert st == 200, b
    return b["item"]["id"]


# ── what it computes ─────────────────────────────────────────────────────────────────────────────

def test_the_settlement_is_itemised_with_the_article_behind_each_line(api, tokens):
    db.update_employee("HML-STF", {"startDate": "2005-01-01", "salary": 20_000_000,
                                   "annualUsed": 0, "annualTotal": 12})
    xid = _exit(api, tokens)
    st, b = api("GET", "/api/hr/exit/%s/settlement" % xid, tokens["admin"])
    assert st == 200, b
    bases = " ".join(l["basis"] for l in b["lines"])
    assert "Art. 113(4)" in bases and "Art. 46" in bases
    assert b["total"] > 0


def test_the_untaken_leave_is_what_a_leaver_actually_earned_not_the_annual_headline(api, tokens):
    """Somebody who leaves on 31 July earned seven months of a twelve-day entitlement, not twelve.
    Paying the headline would overpay every leaver by the unearned part of the year."""
    db.update_employee("HML-STF", {"startDate": "2023-01-01", "salary": 20_000_000,
                                   "annualUsed": 0, "annualTotal": 12})
    xid = _exit(api, tokens, last_day="2026-07-31")
    _, b = api("GET", "/api/hr/exit/%s/settlement" % xid, tokens["admin"])
    assert b["leaveEarned"] == 7, "7 of 12 months worked"
    assert b["leaveUntaken"] == 7


def test_leave_already_taken_comes_off(api, tokens):
    db.update_employee("HML-STF", {"startDate": "2023-01-01", "salary": 20_000_000,
                                   "annualUsed": 5, "annualTotal": 12})
    xid = _exit(api, tokens, last_day="2026-07-31")
    _, b = api("GET", "/api/hr/exit/%s/settlement" % xid, tokens["admin"])
    assert b["leaveUntaken"] == 2


def test_taking_more_leave_than_was_earned_never_produces_a_negative_payout(api, tokens):
    db.update_employee("HML-STF", {"startDate": "2023-01-01", "salary": 20_000_000,
                                   "annualUsed": 12, "annualTotal": 12})
    xid = _exit(api, tokens, last_day="2026-03-31")
    _, b = api("GET", "/api/hr/exit/%s/settlement" % xid, tokens["admin"])
    assert b["leaveUntaken"] == 0 and b["leavePay"] == 0


def test_a_modern_hire_gets_no_severance_and_the_reason_is_on_the_record(api, tokens):
    """Art. 46(2). The answer surprises people, so it has to explain itself."""
    db.update_employee("HML-STF", {"startDate": "2018-01-01", "salary": 20_000_000, "annualUsed": 0})
    xid = _exit(api, tokens)
    _, b = api("GET", "/api/hr/exit/%s/settlement" % xid, tokens["admin"])
    assert b["severance"]["amount"] == 0
    assert "unemployment insurance" in b["severance"]["reason"]


def test_a_redundancy_is_a_job_loss_allowance_instead(api, tokens):
    db.update_employee("HML-STF", {"startDate": "2018-01-01", "salary": 20_000_000, "annualUsed": 0})
    xid = _exit(api, tokens, type_="Redundancy")
    _, b = api("GET", "/api/hr/exit/%s/settlement" % xid, tokens["admin"])
    assert b["severance"]["kind"] == "jobloss" and b["severance"]["amount"] > 0


def test_the_wage_comes_from_the_dated_history_not_from_todays_salary(api, tokens):
    """Decree 145/2020 Art. 8(2) averages the six months before termination. Using the current figure
    would price a leaver on a raise they held for one month."""
    db.update_employee("HML-STF", {"startDate": "2000-01-01", "salary": 60_000_000, "annualUsed": 0})
    for eff, amt in (("2020-01-01", 20_000_000), ("2026-07-01", 60_000_000)):
        db.add_emp_event("HML-STF", "salary", None, amt, effective=eff)
    xid = _exit(api, tokens, last_day="2026-07-31")
    _, b = api("GET", "/api/hr/exit/%s/settlement" % xid, tokens["admin"])
    assert b["wage"] < 60_000_000, "the six-month average, not the last month's figure"


def test_the_deadline_is_fourteen_working_days_and_says_so(api, tokens):
    db.update_employee("HML-STF", {"startDate": "2020-01-01", "salary": 20_000_000, "annualUsed": 0})
    xid = _exit(api, tokens, last_day="2026-07-31")
    _, b = api("GET", "/api/hr/exit/%s/settlement" % xid, tokens["admin"])
    assert b["deadline"] == "2026-08-20"
    assert "Art. 48(1)" in b["deadlineBasis"]


def test_an_exit_with_no_last_working_day_is_refused_rather_than_dated_from_nothing(api, tokens):
    xid = _exit(api, tokens, last_day="")
    st, b = api("GET", "/api/hr/exit/%s/settlement" % xid, tokens["admin"])
    assert st == 400 and "last working day" in (b.get("error") or "")


# ── raising it as a payable ──────────────────────────────────────────────────────────────────────

def test_raising_it_creates_a_real_payment_request(api, tokens):
    """The point of the change: the amount stops being a number on an HR record and enters the
    approval and disbursement path every other payment goes through."""
    db.update_employee("HML-STF", {"startDate": "2005-01-01", "salary": 20_000_000, "annualUsed": 0})
    xid = _exit(api, tokens)
    st, b = api("POST", "/api/hr/exit/%s/settlement" % xid, tokens["admin"], {})
    assert st == 200, b
    pay = b["payment"]
    assert pay["payee"] == "Staff One"
    assert pay["amount"] == round(b["total"])
    assert pay["status"] == "Pending Approval"
    assert pay["dueDate"] == b["deadline"]
    assert "Art. 48(1)" in pay["note"]


def test_the_payable_carries_the_itemisation_so_an_approver_can_see_what_they_are_signing(api, tokens):
    db.update_employee("HML-STF", {"startDate": "2005-01-01", "salary": 20_000_000, "annualUsed": 0})
    xid = _exit(api, tokens)
    _, b = api("POST", "/api/hr/exit/%s/settlement" % xid, tokens["admin"], {})
    assert len(b["payment"]["settlementLines"]) == len(b["lines"])
    assert "Untaken annual leave" in b["payment"]["note"]


def test_somebody_s_final_pay_can_never_be_raised_twice(api, tokens):
    """Not a recoverable clerical error."""
    db.update_employee("HML-STF", {"startDate": "2005-01-01", "salary": 20_000_000, "annualUsed": 0})
    xid = _exit(api, tokens)
    _, first = api("POST", "/api/hr/exit/%s/settlement" % xid, tokens["admin"], {})
    _, again = api("POST", "/api/hr/exit/%s/settlement" % xid, tokens["admin"], {})
    assert again.get("alreadyRaised") is True
    assert again["paymentId"] == first["payment"]["id"]
    assert len([p for p in db.list_collection("payments") if p.get("settlementFor") == xid]) == 1


def test_the_exit_record_remembers_which_payment_settles_it(api, tokens):
    db.update_employee("HML-STF", {"startDate": "2005-01-01", "salary": 20_000_000, "annualUsed": 0})
    xid = _exit(api, tokens)
    _, b = api("POST", "/api/hr/exit/%s/settlement" % xid, tokens["admin"], {})
    rec = db.get_collection_item("exits", xid)
    assert rec["settlementPaymentId"] == b["payment"]["id"]
    assert rec["settlementDeadline"] == b["deadline"]


def test_raising_it_is_written_to_the_audit_chain(api, tokens):
    db.update_employee("HML-STF", {"startDate": "2005-01-01", "salary": 20_000_000, "annualUsed": 0})
    xid = _exit(api, tokens)
    api("POST", "/api/hr/exit/%s/settlement" % xid, tokens["admin"], {})
    trail = [a for a in db.list_collection("audit")
             if a.get("action") == "Final settlement raised as a payment"]
    assert trail and "Art. 48(1)" in trail[-1]["detail"]


def test_nothing_owed_raises_nothing(api, tokens):
    db.update_employee("HML-STF", {"startDate": "2026-06-01", "salary": 20_000_000,
                                   "annualUsed": 99})
    xid = _exit(api, tokens, last_day="2026-07-31")
    st, b = api("POST", "/api/hr/exit/%s/settlement" % xid, tokens["admin"], {})
    assert st == 400 and "nothing" in (b.get("error") or "").lower()


# ── who may do it ────────────────────────────────────────────────────────────────────────────────

def test_a_manager_cannot_see_or_raise_a_settlement(api, tokens):
    db.update_employee("HML-STF", {"startDate": "2005-01-01", "salary": 20_000_000})
    xid = _exit(api, tokens)
    st, _ = api("GET", "/api/hr/exit/%s/settlement" % xid, tokens["mgr"])
    assert st == 403
    st, _ = api("POST", "/api/hr/exit/%s/settlement" % xid, tokens["mgr"], {})
    assert st == 403


def test_an_exit_that_does_not_exist_is_a_404(api, tokens):
    st, _ = api("GET", "/api/hr/exit/nope/settlement", tokens["admin"])
    assert st == 404
