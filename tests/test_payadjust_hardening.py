"""Manual payroll adjustments (payadjust) are money-affecting. They must (a) be written to the
tamper-evident audit trail on every add/edit, and (b) be locked once the month is finalised (a
Director-e-signed company pay run for that period) — no adding, editing, or deleting a closed month's
adjustment behind a signed payroll's back.
"""
import app
import db


def _adj(api, tok, period, empId="HML-STF", net=5_000_000):
    return api("POST", "/api/coll/payadjust", tok, {"empId": empId, "period": period, "net": net})


def _finalise_company_run(api, tokens, monkeypatch, period):
    monkeypatch.setattr(app, "DEMO_MODE", True)
    _, b = api("POST", "/api/coll/payruns", tokens["editor"],
               {"scope": "company", "period": period, "count": 1, "gross": 10_000_000, "net": 9_000_000,
                "ee": 500_000, "er": 1_000_000, "pit": 500_000, "erCost": 11_000_000})
    pid = b["item"]["id"]
    st, r = api("POST", "/api/esign", tokens["management"],
                {"coll": "payruns", "id": pid, "meaning": "Finalise", "setStatus": "Finalised"})
    assert st == 200, r
    return pid


def _adj_audits():
    return [r for r in db.list_collection("audit") if "adjustment" in str(r.get("action", "")).lower()]


def test_payadjust_add_and_edit_are_audited(api, tokens):
    st, b = _adj(api, tokens["editor"], "Audit-Test 2026")
    assert st == 200, b
    aid = b["item"]["id"]
    api("PATCH", "/api/coll/payadjust/" + aid, tokens["editor"], dict(db.get_collection_item("payadjust", aid), net=6_000_000))
    acts = [str(r.get("action", "")).lower() for r in _adj_audits() if aid in str(r.get("target", ""))]
    assert any("added" in a for a in acts), acts
    assert any("edited" in a for a in acts), acts


def test_finalised_period_locks_add_edit_delete(api, tokens, monkeypatch):
    period = "Lock-Test 2026"
    _, b = _adj(api, tokens["editor"], period)              # created BEFORE finalising — allowed
    aid = b["item"]["id"]
    _finalise_company_run(api, tokens, monkeypatch, period)
    # ADD to a finalised month → blocked
    st_c, _ = _adj(api, tokens["editor"], period, empId="HML-OTH")
    assert st_c == 403
    # EDIT an existing adjustment in a finalised month → blocked, and the stored value is unchanged
    st_u, _ = api("PATCH", "/api/coll/payadjust/" + aid, tokens["editor"],
                  dict(db.get_collection_item("payadjust", aid), net=7_000_000))
    assert st_u == 403
    assert db.get_collection_item("payadjust", aid)["net"] == 5_000_000
    # DELETE from a finalised month → blocked, still present
    st_d, _ = api("DELETE", "/api/coll/payadjust/" + aid, tokens["editor"])
    assert st_d == 403
    assert db.get_collection_item("payadjust", aid) is not None


def test_open_period_still_allows_edit_and_delete(api, tokens):
    _, b = _adj(api, tokens["editor"], "Open-Period 2026")
    aid = b["item"]["id"]
    st_u, _ = api("PATCH", "/api/coll/payadjust/" + aid, tokens["editor"],
                  dict(db.get_collection_item("payadjust", aid), net=8_000_000))
    assert st_u == 200 and db.get_collection_item("payadjust", aid)["net"] == 8_000_000
    st_d, _ = api("DELETE", "/api/coll/payadjust/" + aid, tokens["editor"])
    assert st_d == 200 and db.get_collection_item("payadjust", aid) is None
