"""Adopting a TENDER-priced job as a project budget, through the real endpoint.

The unit tests in test_tender_budget.py prove the lines reconcile. These prove the endpoint that
writes them behaves — because that is where the refusals live, and a budget that can be set by the
wrong person, from a draft, or twice over a live job is worse than none: it looks like a baseline.

Before this, `/api/est/adopt` only understood the BoQ path. A trading, EPC or services tender that
was WON hit `_est_rows`, found no BoQ items, and was told it had "nothing to budget yet" — a
correct-sounding refusal about an estimate that was fully priced.
"""
import db
import tender


def _project(pid):
    db.put_collection_item("pm_projects", {"id": pid, "name": "Test project", "status": "Active"})
    return pid


def _rows(pid):
    return [c for c in db.list_collection("pm_costs") if c.get("projectId") == pid]


def _epc_tender(tid, status="Approved"):
    db.put_collection_item("est_projects", {
        "id": tid, "estNo": tid, "title": "Turnkey plant", "costingType": "epc",
        "status": status, "vatPct": 10})
    for i, (centre, usd) in enumerate((("CIV", 400000), ("MEP", 300000), ("CON", 40000))):
        db.put_collection_item("est_bom", {"id": "%s-B%d" % (tid, i), "estId": tid,
                                           "costCentre": centre, "qty": 1, "unitCostUsd": usd})
    return tid


def _services_tender(tid):
    db.put_collection_item("est_projects", {
        "id": tid, "estNo": tid, "title": "EU-GMP readiness", "costingType": "services",
        "status": "Approved", "vatPct": 10})
    db.put_collection_item("est_wbs", {"id": tid + "-W1", "estId": tid, "code": "WP-01",
                                       "name": "Assessment", "durationMonths": 2,
                                       "daysSME": 12, "daysENG": 18,
                                       "travelPeople": 2, "travelTrips": 2, "travelNights": 4})
    return tid


def _trading_tender(tid):
    db.put_collection_item("est_projects", {
        "id": tid, "estNo": tid, "title": "Pump package", "costingType": "trading",
        "status": "Approved", "vatPct": 10})
    db.put_collection_item("est_landed", {"id": tid + "-L1", "estId": tid, "desc": "Pump",
                                          "qty": 1, "exwUnit": 100000, "currency": "USD",
                                          "mfnDutyPct": 10})
    return tid


def test_an_epc_tender_becomes_a_budget_with_a_line_per_cost_centre(api, tokens):
    tid, pid = _epc_tender("TND-EPC-ADOPT"), _project("PRJ-EPC-ADOPT")
    st, r = api("POST", "/api/est/adopt", tokens["admin"], {"estId": tid, "projectId": pid})
    assert st == 200, r
    rows = _rows(pid)
    assert rows, "nothing was budgeted"
    assert sum(int(c["budget"]) for c in rows) == r["total"]
    notes = " ".join(c["note"] + " " + c["item"] for c in rows)
    assert "CIV" in notes and "MEP" in notes


def test_a_services_tender_becomes_a_budget_of_work_packages(api, tokens):
    tid, pid = _services_tender("TND-SVC-ADOPT"), _project("PRJ-SVC-ADOPT")
    st, r = api("POST", "/api/est/adopt", tokens["admin"], {"estId": tid, "projectId": pid})
    assert st == 200, r
    rows = _rows(pid)
    assert any("WP-01" in c["item"] for c in rows)
    assert any(c["category"] == "Labor" for c in rows)
    assert sum(int(c["budget"]) for c in rows) == r["total"]


def test_a_trading_tender_budgets_the_customs_chain_not_one_landed_line(api, tokens):
    """Goods to the supplier, freight to the forwarder, duty to customs — each separately
    committed, so each separately controllable."""
    tid, pid = _trading_tender("TND-TRD-ADOPT"), _project("PRJ-TRD-ADOPT")
    st, r = api("POST", "/api/est/adopt", tokens["admin"], {"estId": tid, "projectId": pid})
    assert st == 200, r
    items = " | ".join(c["item"] for c in _rows(pid))
    assert "EXW" in items and "duty" in items.lower()
    assert len(_rows(pid)) > 1, "the whole customs chain landed as a single line"


def test_a_draft_tender_cannot_become_a_baseline(api, tokens):
    tid, pid = _epc_tender("TND-EPC-DRAFT", status="Draft"), _project("PRJ-EPC-DRAFT")
    st, r = api("POST", "/api/est/adopt", tokens["admin"], {"estId": tid, "projectId": pid})
    assert st == 400
    assert "approved" in (r.get("error") or "").lower()
    assert _rows(pid) == []


def test_a_manager_below_management_cannot_baseline_a_tender(api, tokens):
    tid, pid = _epc_tender("TND-EPC-ACL"), _project("PRJ-EPC-ACL")
    st, _ = api("POST", "/api/est/adopt", tokens["mgr"], {"estId": tid, "projectId": pid})
    assert st == 403
    assert _rows(pid) == []


def test_a_tender_cannot_be_adopted_twice(api, tokens):
    """A baseline that can be silently rewritten is not a baseline."""
    tid, pid = _epc_tender("TND-EPC-TWICE"), _project("PRJ-EPC-TWICE")
    assert api("POST", "/api/est/adopt", tokens["admin"], {"estId": tid, "projectId": pid})[0] == 200
    before = len(_rows(pid))
    st, r = api("POST", "/api/est/adopt", tokens["admin"], {"estId": tid, "projectId": pid})
    assert st == 409
    assert "already adopted" in (r.get("error") or "").lower()
    assert len(_rows(pid)) == before, "the second attempt wrote budget lines anyway"


def test_the_budget_says_where_each_line_came_from(api, tokens):
    """A budget line whose origin is only in an audit log is one nobody reading the budget sees."""
    tid, pid = _epc_tender("TND-EPC-PROV"), _project("PRJ-EPC-PROV")
    api("POST", "/api/est/adopt", tokens["admin"], {"estId": tid, "projectId": pid})
    for c in _rows(pid):
        assert c.get("estimateId") == tid
        assert "Adopted from estimate" in (c.get("note") or "")


def test_the_budget_is_rebuilt_from_the_rows_not_from_a_stale_summary(api, tokens):
    """Adopting off a cached figure is how a project gets funded for a price nobody quotes."""
    tid, pid = _epc_tender("TND-EPC-FRESH"), _project("PRJ-EPC-FRESH")
    db.put_collection_item("est_bom", {"id": tid + "-B9", "estId": tid, "costCentre": "CLR",
                                       "qty": 1, "unitCostUsd": 250000})
    st, r = api("POST", "/api/est/adopt", tokens["admin"], {"estId": tid, "projectId": pid})
    assert st == 200
    assert any("CLR" in c["item"] for c in _rows(pid)), "the line added last was not budgeted"
