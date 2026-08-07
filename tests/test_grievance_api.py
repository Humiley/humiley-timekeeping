"""The speak-up channel, end to end.

grievance.py proves the routing and the clock. This proves the part only the server can: that the
confidentiality boundary actually holds against a real request — including against an administrator,
who is deliberately not a way in, and including through the generic /api/coll route that would
otherwise hand every concern to exactly the people the channel exists to be independent of.
"""
import pytest

import db
import grievance as g


@pytest.fixture(autouse=True)
def _clean():
    conn = db.get_conn()
    conn.execute("DELETE FROM collections WHERE coll = 'concerns'")
    conn.commit()
    conn.close()
    db.set_setting("portal_speakupHandlers", None)
    yield
    conn = db.get_conn()
    conn.execute("DELETE FROM collections WHERE coll = 'concerns'")
    conn.commit()
    conn.close()
    db.set_setting("portal_speakupHandlers", None)


DETAIL = "On 3 August the site supervisor told me to work through my rest day without recording it."


def _handlers(*ids):
    db.set_setting("portal_speakupHandlers", ",".join(ids))


def _raise(api, tokens, who="staff", **kw):
    body = dict({"category": "pay", "detail": DETAIL}, **kw)
    return api("POST", "/api/hr/speakup", tokens[who], body)


# ── raising ──────────────────────────────────────────────────────────────────────────────────────

def test_any_employee_can_raise_a_concern(api, tokens):
    """A channel only managers can use is not a speak-up channel."""
    _handlers("HML-MGT")
    code, b = _raise(api, tokens, "staff")
    assert code == 200, b
    assert b["ref"].startswith("SPK-") and b["routedCount"] == 1


def test_the_reference_is_returned_with_an_instruction_to_keep_it(api, tokens):
    _handlers("HML-MGT")
    _, b = _raise(api, tokens, "staff")
    assert "ONLY way" in b["keepThis"]


def test_a_thin_concern_is_refused_with_the_reason(api, tokens):
    _handlers("HML-MGT")
    code, b = _raise(api, tokens, "staff", detail="unfair")
    assert code == 400 and "cannot be investigated" in b["error"]


def test_with_no_handler_designated_at_all_it_says_so(api, tokens):
    """It must not swallow the concern and report success."""
    db.set_setting("portal_hrAdmins", None)
    code, b = _raise(api, tokens, "staff")
    if code == 400:
        assert "No speak-up handler" in b["error"]
        assert db.list_collection("concerns") == []


# ── anonymity: what is and is not written down ───────────────────────────────────────────────────

def test_an_anonymous_concern_does_not_record_who_raised_it(api, tokens):
    """Not masked on the way out — genuinely absent from the record."""
    _handlers("HML-MGT")
    _, b = _raise(api, tokens, "staff", anonymous=True)
    rec = [c for c in db.list_collection("concerns") if c["ref"] == b["ref"]][0]
    assert rec["anonymous"] is True
    assert not rec.get("raisedById") and not rec.get("raisedByName")


def test_a_named_concern_does_record_it(api, tokens):
    _handlers("HML-MGT")
    _, b = _raise(api, tokens, "staff")
    rec = [c for c in db.list_collection("concerns") if c["ref"] == b["ref"]][0]
    assert rec["raisedById"] == "HML-STF"


def test_the_audit_row_carries_neither_the_reporter_nor_the_detail(api, tokens):
    """Every administrator can read the audit log. Putting either in it would undo the channel from
    the other end."""
    _handlers("HML-MGT")
    _, b = _raise(api, tokens, "staff")
    # Matched on the reference, not [-1]: the audit table is not cleared between tests, so the
    # last row belongs to whichever test ran most recently.
    row = [a for a in db.list_collection("audit")
           if a.get("action") == "Concern raised" and b["ref"] in str(a.get("target") or "")]
    assert len(row) == 1
    row = row[0]
    assert row["actorId"] == "" and row["actor"] == "Speak-up channel"
    assert DETAIL not in row["detail"] and "HML-STF" not in row["detail"]


# ── who can read it ──────────────────────────────────────────────────────────────────────────────

def test_the_routed_handler_sees_it(api, tokens):
    _handlers("HML-MGT")
    _raise(api, tokens, "staff")
    code, b = api("GET", "/api/hr/speakup", tokens["management"])
    assert code == 200 and len(b["concerns"]) == 1


def test_an_administrator_who_is_not_a_handler_sees_nothing(api, tokens):
    """The single most important assertion in this file. Being an admin is not a way in."""
    _handlers("HML-MGT")
    _raise(api, tokens, "staff")
    code, b = api("GET", "/api/hr/speakup", tokens["admin"])
    assert code == 200 and b["concerns"] == []


def test_a_manager_who_is_not_a_handler_sees_nothing(api, tokens):
    _handlers("HML-MGT")
    _raise(api, tokens, "staff")
    _, b = api("GET", "/api/hr/speakup", tokens["mgr"])
    assert b["concerns"] == []


def test_the_reporter_sees_their_own_named_concern(api, tokens):
    _handlers("HML-MGT")
    _raise(api, tokens, "staff")
    _, b = api("GET", "/api/hr/speakup", tokens["staff"])
    assert len(b["concerns"]) == 1


def test_the_reporter_does_not_see_their_own_ANONYMOUS_concern(api, tokens):
    """It cannot be shown to them — the record does not know who they are. That is the cost of
    anonymity, and the reference is what replaces it."""
    _handlers("HML-MGT")
    _raise(api, tokens, "staff", anonymous=True)
    _, b = api("GET", "/api/hr/speakup", tokens["staff"])
    assert b["concerns"] == []


def test_the_handler_never_receives_the_reporters_identity_on_an_anonymous_concern(api, tokens):
    _handlers("HML-MGT")
    _raise(api, tokens, "staff", anonymous=True)
    _, b = api("GET", "/api/hr/speakup", tokens["management"])
    c = b["concerns"][0]
    assert "raisedById" not in c and "raisedByName" not in c
    assert "HML-STF" not in repr(c)


# ── the generic collection route must not be a way round it ──────────────────────────────────────

def test_the_concerns_collection_is_not_served_by_the_generic_route_to_anyone(api, tokens):
    """Listing it would hand every concern to exactly the people the channel is independent of."""
    _handlers("HML-MGT")
    _raise(api, tokens, "staff")
    for who in ("admin", "editor", "management", "mgr", "staff"):
        code, _ = api("GET", "/api/coll/concerns", tokens[who])
        assert code == 404, who


def test_it_cannot_be_written_edited_or_deleted_through_the_generic_route(api, tokens):
    _handlers("HML-MGT")
    _, b = _raise(api, tokens, "staff")
    rec = [c for c in db.list_collection("concerns") if c["ref"] == b["ref"]][0]
    assert api("POST", "/api/coll/concerns", tokens["admin"], {"detail": "x"})[0] == 404
    assert api("PATCH", "/api/coll/concerns/" + rec["id"], tokens["admin"], dict(rec, status="Closed"))[0] == 404
    assert api("DELETE", "/api/coll/concerns/" + rec["id"], tokens["admin"])[0] == 404
    assert db.get_collection_item("concerns", rec["id"])["status"] == g.OPEN


# ── tracking by reference ────────────────────────────────────────────────────────────────────────

def test_the_reference_returns_the_status_without_any_identity(api, tokens):
    _handlers("HML-MGT")
    _, b = _raise(api, tokens, "staff", anonymous=True)
    code, t = api("GET", "/api/hr/speakup/track?ref=" + b["ref"], tokens["staff"])
    assert code == 200
    assert t["concern"]["status"] == g.OPEN and t["concern"]["ref"] == b["ref"]


def test_the_reference_view_carries_no_detail_no_handler_and_no_notes(api, tokens):
    """A lucky guess at a reference must not expose somebody's account of events."""
    _handlers("HML-MGT")
    _, b = _raise(api, tokens, "staff")
    _, t = api("GET", "/api/hr/speakup/track?ref=" + b["ref"], tokens["mgr"])
    blob = repr(t)
    assert DETAIL not in blob and "HML-MGT" not in blob and "HML-STF" not in blob


def test_an_unknown_reference_says_the_same_thing_as_a_wrong_one(api, tokens):
    """A distinguishable error turns this into an oracle for guessing references."""
    code, b = api("GET", "/api/hr/speakup/track?ref=SPK-000000", tokens["staff"])
    assert code == 404 and "No concern matches that reference" in (b.get("error") or "")


# ── handling it ──────────────────────────────────────────────────────────────────────────────────

def _one(api, tokens):
    _handlers("HML-MGT")
    _, b = _raise(api, tokens, "staff")
    return [c for c in db.list_collection("concerns") if c["ref"] == b["ref"]][0]


def test_the_routed_handler_can_acknowledge_it(api, tokens):
    rec = _one(api, tokens)
    code, b = api("POST", "/api/hr/speakup/" + rec["id"], tokens["management"],
                  {"status": g.ACKNOWLEDGED, "note": "Read it, meeting arranged."})
    assert code == 200 and b["concern"]["status"] == g.ACKNOWLEDGED
    assert b["concern"]["acknowledgedOn"] and b["concern"]["due"]["acknowledged"] is True


def test_somebody_it_was_not_routed_to_cannot_act_on_it(api, tokens):
    rec = _one(api, tokens)
    for who in ("admin", "editor", "mgr", "staff"):
        assert api("POST", "/api/hr/speakup/" + rec["id"], tokens[who],
                   {"status": g.ACKNOWLEDGED})[0] in (403, 404), who
    assert db.get_collection_item("concerns", rec["id"])["status"] == g.OPEN


def test_closing_needs_an_outcome(api, tokens):
    """It is the one thing the person who raised it is entitled to be told."""
    rec = _one(api, tokens)
    code, b = api("POST", "/api/hr/speakup/" + rec["id"], tokens["management"],
                  {"status": g.CLOSED})
    assert code == 400 and "needs an outcome" in b["error"]
    code, b = api("POST", "/api/hr/speakup/" + rec["id"], tokens["management"],
                  {"status": g.CLOSED, "outcome": "Upheld. The rest day was reinstated and paid."})
    assert code == 200 and b["concern"]["closedOn"]


def test_the_outcome_reaches_the_reporter_through_the_reference(api, tokens):
    rec = _one(api, tokens)
    api("POST", "/api/hr/speakup/" + rec["id"], tokens["management"],
        {"status": g.CLOSED, "outcome": "Upheld. The rest day was reinstated and paid."})
    _, t = api("GET", "/api/hr/speakup/track?ref=" + rec["ref"], tokens["staff"])
    assert t["concern"]["outcome"].startswith("Upheld")


def test_a_state_that_is_not_a_state_is_refused(api, tokens):
    rec = _one(api, tokens)
    assert api("POST", "/api/hr/speakup/" + rec["id"], tokens["management"],
               {"status": "Ignored"})[0] == 400


def test_every_action_is_added_to_the_timeline(api, tokens):
    rec = _one(api, tokens)
    api("POST", "/api/hr/speakup/" + rec["id"], tokens["management"], {"status": g.ACKNOWLEDGED})
    api("POST", "/api/hr/speakup/" + rec["id"], tokens["management"], {"note": "Spoke to the crew."})
    tl = db.get_collection_item("concerns", rec["id"])["timeline"]
    assert [t["what"] for t in tl] == ["Raised", g.ACKNOWLEDGED, "Note added"]


# ── routing away from the subject, over HTTP ─────────────────────────────────────────────────────

def test_a_concern_about_the_only_handler_is_refused_rather_than_sent_to_them(api, tokens):
    """The whole point. Over HTTP, not just in the module."""
    _handlers("HML-MGT")
    code, b = api("POST", "/api/hr/speakup", tokens["staff"],
                  {"category": "management", "detail": DETAIL, "about": ["HML-MGT"]})
    assert code == 400 and "named in it" in b["error"]
    assert db.list_collection("concerns") == []


def test_with_a_second_handler_it_routes_to_the_one_not_named(api, tokens):
    _handlers("HML-MGT", "HML-EDT")
    _, b = api("POST", "/api/hr/speakup", tokens["staff"],
               {"category": "management", "detail": DETAIL, "about": ["HML-MGT"]})
    rec = [c for c in db.list_collection("concerns") if c["ref"] == b["ref"]][0]
    assert rec["routedTo"] == ["HML-EDT"]
    assert api("GET", "/api/hr/speakup", tokens["management"])[1]["concerns"] == []


# ── the number an auditor asks for ───────────────────────────────────────────────────────────────

def test_the_handler_screen_carries_the_summary_and_both_notices(api, tokens):
    _handlers("HML-MGT")
    _raise(api, tokens, "staff")
    _, b = api("GET", "/api/hr/speakup", tokens["management"])
    assert b["summary"]["total"] == 1 and "1 concern(s) raised" in b["summary"]["statement"]
    assert "cannot promise" in b["notice"] and b["noticeVn"]
    assert "Retaliation" in b["noRetaliation"] and b["noRetaliationVn"]
