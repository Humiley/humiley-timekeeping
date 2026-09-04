"""The scheduled quantity is a baseline, not a free-text field.

Percent complete is site quantity over scheduled quantity. Once somebody has measured against a
denominator, moving it silently rewrites every percentage already reported — the roll-up, the master
activity, the S-curve, the client's progress report — and nothing on screen says why. Lowering it
flatters the job; raising it buries a delay.

The rule: free while nothing is measured, then a manager's decision with a stated reason.
"""
import pytest

import db


PID = "PRJ-GUARD"


@pytest.fixture
def item(api, tokens):
    st, b = api("POST", "/api/coll/pm_detail", tokens["mgr"],
                {"projectId": PID, "category": "Plumbing", "name": "Underground pipe — Zone 9",
                 "start": "2026-08-01", "finish": "2026-08-31", "unit": "m", "qtyPlan": 500})
    assert st == 200, b
    row = b.get("item") or b
    yield row["id"]
    try:
        conn = db.get_conn()
        conn.execute("DELETE FROM collections WHERE coll='pm_detail' AND id=?", (row["id"],))
        conn.commit(); conn.close()
    except Exception:
        pass


def _measure(api, tokens, iid, qty, pct):
    row = db.get_collection_item("pm_detail", iid)
    row["log"] = [{"d": "2026-08-15", "qty": qty, "pct": pct, "by": "Site"}]
    st, b = api("PATCH", "/api/coll/pm_detail/" + iid, tokens["mgr"], row)
    assert st == 200, b


# ── before anything is measured, it is just data entry ───────────────────────────────────────────

def test_setting_the_baseline_is_free_until_something_is_measured(api, tokens, item):
    row = db.get_collection_item("pm_detail", item)
    row["qtyPlan"] = 620
    st, _ = api("PATCH", "/api/coll/pm_detail/" + item, tokens["mgr"], row)
    assert st == 200
    assert db.get_collection_item("pm_detail", item)["qtyPlan"] == 620
    assert not db.get_collection_item("pm_detail", item).get("qtyPlanLog"), \
        "no history for a baseline nobody had measured against"


def test_a_reading_with_only_a_percentage_does_not_lock_it(api, tokens, item):
    """A judged percentage was never computed off the denominator, so moving it changes nothing that
    was reported. Locking there would be ceremony."""
    row = db.get_collection_item("pm_detail", item)
    row["log"] = [{"d": "2026-08-15", "pct": 40, "by": "Site"}]
    assert api("PATCH", "/api/coll/pm_detail/" + item, tokens["mgr"], row)[0] == 200
    row = db.get_collection_item("pm_detail", item)
    row["qtyPlan"] = 700
    assert api("PATCH", "/api/coll/pm_detail/" + item, tokens["mgr"], row)[0] == 200


# ── once measured, it is a decision ──────────────────────────────────────────────────────────────

def test_staff_cannot_move_a_measured_baseline(api, tokens, item):
    _measure(api, tokens, item, 350, 70)
    row = db.get_collection_item("pm_detail", item)
    row["qtyPlan"] = 400
    st, b = api("PATCH", "/api/coll/pm_detail/" + item, tokens["staff"], row)
    assert st == 403
    assert "manager" in b.get("error", "").lower()
    assert db.get_collection_item("pm_detail", item)["qtyPlan"] == 500, "and it did not move"


def test_a_manager_must_say_why(api, tokens, item):
    _measure(api, tokens, item, 350, 70)
    row = db.get_collection_item("pm_detail", item)
    row["qtyPlan"] = 400
    st, b = api("PATCH", "/api/coll/pm_detail/" + item, tokens["mgr"], row)
    assert st == 400
    assert "why" in b.get("error", "").lower()
    assert db.get_collection_item("pm_detail", item)["qtyPlan"] == 500


def test_a_reasoned_change_goes_through_and_is_kept(api, tokens, item):
    _measure(api, tokens, item, 350, 70)
    row = db.get_collection_item("pm_detail", item)
    row["qtyPlan"] = 400
    row["qtyPlanReason"] = "Variation VO-014 reduced the Zone 9 run"
    st, _ = api("PATCH", "/api/coll/pm_detail/" + item, tokens["mgr"], row)
    assert st == 200
    saved = db.get_collection_item("pm_detail", item)
    assert saved["qtyPlan"] == 400
    hist = saved.get("qtyPlanLog") or []
    assert len(hist) == 1
    assert hist[0]["from"] == 500 and hist[0]["to"] == 400
    assert "VO-014" in hist[0]["reason"]
    assert hist[0]["by"] and hist[0]["at"], "who and when, or it is not a record"
    assert "qtyPlanReason" not in saved, "the justification is history, not a column"


def test_the_change_reaches_the_audit_chain(api, tokens, item):
    _measure(api, tokens, item, 350, 70)
    row = db.get_collection_item("pm_detail", item)
    row["qtyPlan"] = 400
    row["qtyPlanReason"] = "Re-measured against the issued-for-construction drawing"
    assert api("PATCH", "/api/coll/pm_detail/" + item, tokens["mgr"], row)[0] == 200
    rows = db.list_collection("audit") or []
    assert any(r.get("action") == "Scheduled quantity changed" and item in str(r.get("target") or "")
               for r in rows), "moving a reported denominator must leave a trace"


def test_history_survives_an_unrelated_edit(api, tokens, item):
    """The round-trip PATCH must not drop the history — the same class of loss the CV reconciliation
    was written for."""
    _measure(api, tokens, item, 350, 70)
    row = db.get_collection_item("pm_detail", item)
    row["qtyPlan"] = 400; row["qtyPlanReason"] = "Variation VO-014"
    assert api("PATCH", "/api/coll/pm_detail/" + item, tokens["mgr"], row)[0] == 200
    row = db.get_collection_item("pm_detail", item)
    row.pop("qtyPlanLog", None)                      # a client that never knew about it
    row["note"] = "changed something else entirely"
    assert api("PATCH", "/api/coll/pm_detail/" + item, tokens["mgr"], row)[0] == 200
    saved = db.get_collection_item("pm_detail", item)
    assert len(saved.get("qtyPlanLog") or []) == 1, "history was dropped by an unrelated edit"
    assert saved["note"] == "changed something else entirely"


def test_clearing_the_baseline_is_also_a_change(api, tokens, item):
    """Setting it to zero turns every measured line back into a judged one. That is not a tidy-up."""
    _measure(api, tokens, item, 350, 70)
    row = db.get_collection_item("pm_detail", item)
    row["qtyPlan"] = 0
    assert api("PATCH", "/api/coll/pm_detail/" + item, tokens["staff"], row)[0] == 403
    assert db.get_collection_item("pm_detail", item)["qtyPlan"] == 500
