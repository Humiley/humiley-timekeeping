"""An approver must be able to SEE the leave they are being asked to approve.

The bug, exactly as it reached the Managing Director's mailbox: a reminder arrived saying "this leave
request from Son Nguyen has been waiting 39 days for your review", and the Approval Inbox was empty.
The system asked for an action and then gave nowhere to take it.

The two halves disagreed. `_appr_reminders` scans EVERY pending leave company-wide and mails the
requester's manager. `_leave_list` returned only your own leave plus your DIRECT REPORTS' — for
everyone, admins included. So anyone who can approve but is not that person's line manager got the
nudge and an empty screen. The frontend was never the problem: `_aprCanSee` already says "anyone who
can approve must be able to SEE what to approve" — the rows simply never arrived.

Claims, travel and payments never had this: `_coll_list` scopes to own records only at STAFF level
and shows the whole company to every manager. Leave was the odd one out.

The fix is deliberately narrow. An approver gets the QUEUE — rows awaiting a decision — not everyone's
leave history. Leave reasons are personal, and an approver needs what is actionable, not the archive.
"""
import app
import db


def _leave(api, tokens, who, start, end, days=1, ltype="Annual Leave"):
    st, b = api("POST", "/api/leave", tokens[who],
                {"type": ltype, "startDate": start, "endDate": end, "days": days, "reason": "test"})
    assert st == 200, b
    return b["id"]


def _ids(api, token, status=None):
    st, b = api("GET", "/api/leave" + ("?status=" + status if status else ""), token)
    assert st == 200, b
    return [r["id"] for r in b["leave"]]


# ── the bug ───────────────────────────────────────────────────────────────────────────────────────

def test_an_approver_sees_leave_from_someone_who_is_not_their_report(api, tokens):
    """'other' reports to admin, not to the Finance Approver — who could nonetheless approve it, and
       so was being reminded about a request they could not see."""
    lid = _leave(api, tokens, "other", "2026-06-29", "2026-06-30")
    assert lid in _ids(api, tokens["management"]), \
        "the approver was told to review this and given an empty inbox"


def test_the_admin_sees_it_too(api, tokens):
    lid = _leave(api, tokens, "staff", "2026-07-06", "2026-07-07")
    assert lid in _ids(api, tokens["admin"])


def test_what_the_reminder_scans_and_what_the_approver_sees_now_agree(api, tokens):
    """THE load-bearing test: the mismatch that produced the empty inbox must not come back. Whatever
       the sweep would nag an approver about, that approver must be able to open."""
    _leave(api, tokens, "other", "2026-08-10", "2026-08-11")
    _leave(api, tokens, "staff", "2026-08-12", "2026-08-13")
    nagged = {r["id"] for st in ("pending", "reviewed")
              for r in (db.list_leave(status=st) or [])}
    visible = set(_ids(api, tokens["management"]))
    assert nagged and nagged <= visible, "reminded about leave that is not in the inbox: %s" % (nagged - visible)


# ── what must NOT have widened ────────────────────────────────────────────────────────────────────

def test_a_plain_manager_still_only_sees_their_own_reports(api, tokens):
    """The three-level flow is deliberate: a Contributor reviews their direct reports, not the company.
       'other' reports to admin, so the dept manager must not see their leave."""
    lid = _leave(api, tokens, "other", "2026-09-01", "2026-09-02")
    assert lid not in _ids(api, tokens["mgr"]), "review scope widened beyond direct reports"


def test_staff_still_only_see_their_own(api, tokens):
    lid = _leave(api, tokens, "other", "2026-09-08", "2026-09-09")
    assert lid not in _ids(api, tokens["staff"])


def test_an_approver_does_not_get_everyones_leave_history(api, tokens, monkeypatch):
    """Only the queue. A decided request from somebody who is not their report stays private — the
       approver has no action left to take on it, and leave reasons are personal."""
    monkeypatch.setattr(app, "DEMO_MODE", True)
    lid = _leave(api, tokens, "other", "2026-10-05", "2026-10-06")
    st, b = api("POST", "/api/esign", tokens["admin"],
                {"coll": "leave", "id": lid, "meaning": "Approve", "setStatus": "approved"})
    assert st == 200, b
    assert lid not in _ids(api, tokens["management"]), \
        "a decided request from a non-report leaked into the approver's list"


def test_the_approval_token_is_never_in_a_list_response(api, tokens):
    """The widened query must strip the one-click token exactly as the original did — otherwise this
       fix would hand every approver a self-approval link for every pending request."""
    _leave(api, tokens, "other", "2026-11-02", "2026-11-03")
    st, b = api("GET", "/api/leave", tokens["management"])
    assert st == 200, b
    assert b["leave"], "fixture produced nothing to check"
    assert all("token" not in r for r in b["leave"]), "an approval token leaked into the list"


def test_no_row_is_returned_twice(api, tokens):
    """Your own reports appear in both halves of the query — they must not be duplicated."""
    lid = _leave(api, tokens, "staff", "2026-12-01", "2026-12-02")   # staff reports to mgr
    ids = _ids(api, tokens["admin"])
    assert ids.count(lid) == 1, "the same request came back more than once"


def test_a_status_filter_is_still_honoured(api, tokens):
    _leave(api, tokens, "other", "2027-01-05", "2027-01-06")
    st, b = api("GET", "/api/leave?status=pending", tokens["management"])
    assert st == 200, b
    assert b["leave"] and all(r["status"] == "pending" for r in b["leave"])
