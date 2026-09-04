"""Appraisal cycles, end to end.

appraisal.py proves the rules. This proves what only the server can: that the participant list is
frozen at the moment a round opens, that closing a round with unfinished reviews takes a deliberate
confirmation because it changes what people are paid, and that the governing rating served to
payroll is the one from the closed round rather than whichever review record came last.
"""
import pytest

import appraisal as ap
import db


@pytest.fixture(autouse=True)
def _clean():
    before = {e["id"]: {"startDate": e.get("startDate"), "endDate": e.get("endDate"),
                        "status": e.get("status"), "salary": e.get("salary")}
              for e in db.list_employees()}
    conn = db.get_conn()
    conn.execute("DELETE FROM collections WHERE coll IN ('review_cycles','reviews')")
    conn.commit()
    conn.close()
    for e in db.list_employees():
        db.update_employee(e["id"], {"startDate": "2020-01-01", "endDate": None,
                                     "status": "Active", "salary": 20_000_000})
    yield
    conn = db.get_conn()
    conn.execute("DELETE FROM collections WHERE coll IN ('review_cycles','reviews')")
    conn.commit()
    conn.close()
    for eid, v in before.items():
        db.update_employee(eid, v)


def _open(api, tokens, name="Annual 2025", frm="2025-01-01", to="2025-12-31", **kw):
    st, b = api("POST", "/api/hr/appraisal/open", tokens["admin"],
                dict({"name": name, "periodFrom": frm, "periodTo": to}, **kw))
    assert st == 200, b
    return b["cycle"]


def _review(cycle_id, emp_id, status="Completed", rating=4):
    db.put_collection_item("reviews", {"id": "rev-%s-%s" % (cycle_id, emp_id), "cycleId": cycle_id,
                                       "empId": emp_id, "status": status, "rating": rating})


# ── opening ──────────────────────────────────────────────────────────────────────────────────────

def test_opening_a_round_freezes_who_is_in_it(api, tokens):
    """Recomputing eligibility on every read means a leaver drops out of the denominator and
    completion climbs to 100% without anybody finishing anything."""
    cyc = _open(api, tokens)
    frozen = {p["empId"] for p in cyc["participants"]}
    assert frozen
    db.update_employee("HML-STF", {"status": "Inactive", "endDate": "2026-01-31"})
    _, b = api("GET", "/api/hr/appraisal/cycles?cycle=" + cyc["id"], tokens["admin"])
    assert b["state"]["participants"] == len(frozen), "the denominator must not shrink"
    assert "HML-STF" in [r["empId"] for r in b["state"]["rows"]]


def test_who_was_left_out_and_why_is_recorded_on_the_round(api, tokens):
    db.update_employee("HML-OTH", {"startDate": "2025-12-01"})
    cyc = _open(api, tokens)
    exc = {x["empId"]: x["why"] for x in cyc["excluded"]}
    assert "HML-OTH" in exc and "minimum" in exc["HML-OTH"]


def test_a_round_with_nobody_eligible_is_refused_rather_than_opened_empty(api, tokens):
    st, b = api("POST", "/api/hr/appraisal/open", tokens["admin"],
                {"name": "Impossible", "periodFrom": "1990-01-01", "periodTo": "1990-12-31"})
    assert st == 400 and "Nobody is eligible" in (b.get("error") or "")


def test_a_backwards_period_is_refused(api, tokens):
    st, b = api("POST", "/api/hr/appraisal/open", tokens["admin"],
                {"name": "X", "periodFrom": "2025-12-31", "periodTo": "2025-01-01"})
    assert st == 400 and "ends before it starts" in (b.get("error") or "")


def test_opening_is_written_to_the_audit_chain(api, tokens):
    _open(api, tokens, name="Annual 2025")
    trail = [a for a in db.list_collection("audit") if a.get("action") == "Review round opened"]
    assert any("Annual 2025" in a["detail"] for a in trail)


# ── closing ──────────────────────────────────────────────────────────────────────────────────────

def test_closing_with_unfinished_reviews_needs_a_deliberate_confirmation(api, tokens):
    """Closing means those people are paid on the neutral rating instead of on an appraisal, so it
    is not something to do by accident."""
    cyc = _open(api, tokens)
    st, b = api("POST", "/api/hr/appraisal/close/" + cyc["id"], tokens["admin"], {})
    assert st == 409
    assert b["needsConfirm"] is True and "neutral rating" in (b.get("error") or "")
    assert db.get_collection_item("review_cycles", cyc["id"])["status"] == ap.OPEN


def test_a_confirmed_close_goes_through_and_records_what_was_unfinished(api, tokens):
    cyc = _open(api, tokens)
    st, b = api("POST", "/api/hr/appraisal/close/" + cyc["id"], tokens["admin"], {"confirm": True})
    assert st == 200 and b["cycle"]["status"] == ap.CLOSED
    trail = [a for a in db.list_collection("audit") if a.get("action") == "Review round closed"]
    assert any("unfinished" in a["detail"] for a in trail)


def test_a_fully_complete_round_closes_without_a_prompt(api, tokens):
    cyc = _open(api, tokens)
    for p in cyc["participants"]:
        _review(cyc["id"], p["empId"])
    st, b = api("POST", "/api/hr/appraisal/close/" + cyc["id"], tokens["admin"], {})
    assert st == 200 and b["state"]["pct"] == 100.0


def test_a_round_cannot_be_closed_twice(api, tokens):
    cyc = _open(api, tokens)
    api("POST", "/api/hr/appraisal/close/" + cyc["id"], tokens["admin"], {"confirm": True})
    st, b = api("POST", "/api/hr/appraisal/close/" + cyc["id"], tokens["admin"], {"confirm": True})
    assert st == 400 and "already closed" in (b.get("error") or "")


# ── the governing rating: the defect this exists to fix ─────────────────────────────────────────

def test_payroll_is_served_the_rating_from_the_closed_round_not_the_last_record(api, tokens):
    """The old build was `ratingBy[empId] = rating` over every review in list order, so the last one
    won whatever cycle it came from. Here a stale 5 from an OPEN round must not outrank the 2 from
    the closed one."""
    closed = _open(api, tokens, name="Annual 2025", frm="2025-01-01", to="2025-12-31")
    _review(closed["id"], "HML-STF", rating=2)
    api("POST", "/api/hr/appraisal/close/" + closed["id"], tokens["admin"], {"confirm": True})
    live = _open(api, tokens, name="Annual 2026", frm="2026-01-01", to="2026-12-31")
    _review(live["id"], "HML-STF", status="Self-assessment", rating=5)

    _, b = api("GET", "/api/hr/appraisal/ratings?period=2026-06", tokens["admin"])
    assert b["ratings"]["HML-STF"]["rating"] == 2
    assert "Annual 2025" in b["ratings"]["HML-STF"]["basis"]
    assert b["governingCycle"] == "Annual 2025"


def test_with_no_closed_round_everybody_is_neutral_and_it_says_why(api, tokens):
    cyc = _open(api, tokens, name="Annual 2026", frm="2026-01-01", to="2026-12-31")
    _review(cyc["id"], "HML-STF", rating=5)
    _, b = api("GET", "/api/hr/appraisal/ratings?period=2026-06", tokens["admin"])
    assert b["ratings"]["HML-STF"]["rating"] == ap.NEUTRAL_RATING
    assert "No closed appraisal cycle" in b["ratings"]["HML-STF"]["basis"]
    assert b["governingCycle"] == ""


def test_every_rating_comes_back_with_a_reason(api, tokens):
    _, b = api("GET", "/api/hr/appraisal/ratings?period=2026-06", tokens["admin"])
    assert b["ratings"]
    assert all(v["basis"] for v in b["ratings"].values())


def test_a_month_that_is_not_a_month_is_refused(api, tokens):
    assert api("GET", "/api/hr/appraisal/ratings", tokens["admin"])[0] == 400
    assert api("GET", "/api/hr/appraisal/ratings?period=banana", tokens["admin"])[0] == 400


# ── salary proposals ─────────────────────────────────────────────────────────────────────────────

def test_proposals_come_from_the_round_and_change_nothing(api, tokens):
    cyc = _open(api, tokens)
    _review(cyc["id"], "HML-STF", rating=5)
    api("POST", "/api/hr/appraisal/close/" + cyc["id"], tokens["admin"], {"confirm": True})
    st, b = api("GET", "/api/hr/appraisal/proposals?cycle=" + cyc["id"], tokens["admin"])
    assert st == 200
    row = [r for r in b["rows"] if r["empId"] == "HML-STF"][0]
    assert row["increase"] == 2_000_000
    assert db.get_employee("HML-STF")["salary"] == 20_000_000, "nothing is applied"


def test_a_budget_caps_the_whole_round_evenly(api, tokens):
    cyc = _open(api, tokens)
    for p in cyc["participants"]:
        _review(cyc["id"], p["empId"], rating=5)
    api("POST", "/api/hr/appraisal/close/" + cyc["id"], tokens["admin"], {"confirm": True})
    _, b = api("GET", "/api/hr/appraisal/proposals?cycle=%s&budget=3" % cyc["id"], tokens["admin"])
    assert b["capped"] is True and b["increasePct"] <= 3.01


def test_the_rating_spread_is_reported_with_the_proposals(api, tokens):
    """Turning ratings into money is exactly the moment to say the spread is not credible."""
    cyc = _open(api, tokens)
    for p in cyc["participants"]:
        _review(cyc["id"], p["empId"], rating=5)
    api("POST", "/api/hr/appraisal/close/" + cyc["id"], tokens["admin"], {"confirm": True})
    _, b = api("GET", "/api/hr/appraisal/proposals?cycle=" + cyc["id"], tokens["admin"])
    assert b["distribution"]["flags"]


# ── who may do what ──────────────────────────────────────────────────────────────────────────────

def test_a_manager_can_see_progress_but_not_open_close_or_price_a_round(api, tokens):
    cyc = _open(api, tokens)
    assert api("GET", "/api/hr/appraisal/cycles", tokens["mgr"])[0] == 200
    assert api("POST", "/api/hr/appraisal/open", tokens["mgr"],
               {"name": "X", "periodFrom": "2025-01-01", "periodTo": "2025-12-31"})[0] == 403
    assert api("POST", "/api/hr/appraisal/close/" + cyc["id"], tokens["mgr"], {})[0] == 403
    assert api("GET", "/api/hr/appraisal/proposals?cycle=" + cyc["id"], tokens["mgr"])[0] == 403
    assert api("GET", "/api/hr/appraisal/ratings?period=2026-06", tokens["mgr"])[0] == 403


def test_staff_cannot_read_the_round_at_all(api, tokens):
    assert api("GET", "/api/hr/appraisal/cycles", tokens["staff"])[0] == 403
