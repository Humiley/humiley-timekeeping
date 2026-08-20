"""The estimating module through the API: who may see a margin, and what a won tender does to a budget.

The arithmetic is tested in `test_estimating`. What matters here is the boundary around it. An
estimate is the most commercially sensitive record the company holds — it says what a job costs us
and what we are taking on top — so the interesting cases are the refusals, and the one write that
is deliberately not repeatable.
"""
import db


def _seed(est_id="EST-T1", status="Approved", markups=None):
    """A two-line bill with a real build-up, priced and ready to adopt."""
    for coll, rows in (
        ("est_projects", [dict({"id": est_id, "estNo": "EST-2026-001", "title": "Cleanroom AHU",
                                "client": "Acme Pharma", "status": status,
                                "siteOverhead": 200_000, "overheadPct": 10, "riskPct": 5,
                                "profitPct": 15, "profitBasis": "markup"}, **(markups or {}))]),
        ("est_items", [
            {"id": est_id + "-s", "estId": est_id, "kind": "section", "seq": "1", "desc": "Ductwork"},
            {"id": est_id + "-a", "estId": est_id, "kind": "item", "seq": "1.1",
             "desc": "GI duct", "unit": "m2", "qty": 100},
            {"id": est_id + "-b", "estId": est_id, "kind": "item", "seq": "1.10",
             "desc": "Insulation", "unit": "m2", "qty": 50},
        ]),
        ("est_resources", [
            {"id": est_id + "-r1", "estId": est_id, "itemId": est_id + "-a", "kind": "material",
             "code": "GI-1.0", "desc": "GI sheet", "unit": "kg", "qtyPer": 8,
             "unitCost": 25_000, "wastePct": 10, "rateId": "RATE-GI"},
            {"id": est_id + "-r2", "estId": est_id, "itemId": est_id + "-a", "kind": "labour",
             "desc": "Sheet metal worker", "unit": "hour", "qtyPer": 0.5, "unitCost": 60_000},
            {"id": est_id + "-r3", "estId": est_id, "itemId": est_id + "-b", "kind": "material",
             "code": "INS-25", "desc": "Rockwool", "unit": "m2", "qtyPer": 1.05, "unitCost": 90_000},
        ]),
        ("est_rates", [{"id": "RATE-GI", "code": "GI-1.0", "desc": "GI sheet", "unit": "kg",
                        "kind": "material", "unitCost": 25_000, "effectiveFrom": "2026-01-01"}]),
    ):
        for r in rows:
            db.put_collection_item(coll, r)
    return est_id


# ── who may look at a margin ─────────────────────────────────────────────────────────────────────

def test_staff_cannot_read_an_estimate_summary(api, tokens):
    _seed("EST-ACL")
    st, r = api("GET", "/api/est/summary?id=EST-ACL", tokens["staff"])
    assert st == 403
    assert "manager" in (r.get("error") or "").lower()


def test_staff_cannot_reach_the_bill_through_the_generic_collection_route_either(api, tokens):
    """The summary endpoint is not the only door. The collections it reads must be shut too."""
    _seed("EST-ACL2")
    for coll in ("est_projects", "est_items", "est_resources", "est_rates"):
        st, _ = api("GET", "/api/coll/" + coll, tokens["staff"])
        assert st == 403, coll


def test_a_manager_can_read_it(api, tokens):
    _seed("EST-OK")
    st, r = api("GET", "/api/est/summary?id=EST-OK", tokens["mgr"])
    assert st == 200
    assert r["summary"]["lineCount"] == 2


def test_a_missing_estimate_is_a_404_not_an_empty_summary(api, tokens):
    st, _ = api("GET", "/api/est/summary?id=nope", tokens["admin"])
    assert st == 404


# ── the numbers the API serves ───────────────────────────────────────────────────────────────────

def test_the_summary_carries_cost_price_and_the_margin_actually_achieved(api, tokens):
    _seed("EST-NUM")
    st, r = api("GET", "/api/est/summary?id=EST-NUM", tokens["admin"])
    s = r["summary"]
    assert st == 200
    # 100 x 250,000 + 50 x 94,500 = 29,725,000 direct
    assert s["directCost"] == 29_725_000
    assert s["price"] > s["costBase"] > s["directCost"]
    # 15% mark-up is a 13.04% margin, and the API says so rather than echoing 15.
    assert abs(s["achievedMarginPct"] - 13.04) < 0.01
    assert s["profitPct"] == 15


def test_the_priced_lines_come_back_and_reconcile_to_the_total(api, tokens):
    _seed("EST-REC")
    st, r = api("GET", "/api/est/summary?id=EST-REC", tokens["admin"])
    assert sum(l["amount"] for l in r["lines"].values()) == r["summary"]["price"]


def test_the_bill_is_ordered_as_a_document_not_as_text(api, tokens):
    """1.10 comes after 1.1, not between 1.1 and 1.2 — a bill reordered by string sort is a
    different document from the one the customer was sent."""
    _seed("EST-SEQ")
    st, r = api("GET", "/api/est/summary?id=EST-SEQ", tokens["admin"])
    assert st == 200
    # The build-up-bearing line (1.1) must price before the 1.10 line.
    ids = list(r["lines"].keys())
    assert ids.index("EST-SEQ-a") < ids.index("EST-SEQ-b")


def test_the_take_offs_come_back_ready_for_procurement_and_payroll_to_check(api, tokens):
    _seed("EST-TO")
    st, r = api("GET", "/api/est/summary?id=EST-TO", tokens["admin"])
    mats = {m["code"]: m for m in r["takeOff"]}
    assert mats["GI-1.0"]["qty"] == 880          # 100 x 8 x 1.10 waste
    assert r["labour"][0]["trade"] == "Sheet metal worker"
    assert r["labour"][0]["hours"] == 50


def test_a_library_rate_that_has_moved_is_reported_as_drift_not_silently_repriced(api, tokens):
    _seed("EST-DRIFT")
    st, r = api("GET", "/api/est/summary?id=EST-DRIFT", tokens["admin"])
    assert r["rateDrift"] == []
    db.put_collection_item("est_rates", {"id": "RATE-GI", "code": "GI-1.0", "desc": "GI sheet",
                                         "unit": "kg", "kind": "material", "unitCost": 31_000,
                                         "effectiveFrom": "2026-06-01"})
    st, r = api("GET", "/api/est/summary?id=EST-DRIFT", tokens["admin"])
    # The estimate still prices at what it was priced at ...
    assert r["summary"]["directCost"] == 29_725_000
    # ... and the move is surfaced so re-pricing is a decision somebody makes.
    assert len(r["rateDrift"]) == 1
    assert r["rateDrift"][0]["libraryNow"] == 31_000
    db.put_collection_item("est_rates", {"id": "RATE-GI", "code": "GI-1.0", "desc": "GI sheet",
                                         "unit": "kg", "kind": "material", "unitCost": 25_000,
                                         "effectiveFrom": "2026-01-01"})


def test_an_impossible_margin_is_a_400_on_the_field_not_a_500(api, tokens):
    """100% margin has no finite price. The user can fix the field; they cannot fix a stack trace."""
    _seed("EST-BAD", markups={"profitPct": 100, "profitBasis": "margin"})
    st, r = api("GET", "/api/est/summary?id=EST-BAD", tokens["admin"])
    assert st == 400
    assert "mark-up" in (r.get("error") or "")


# ── adopting a won estimate as a project budget ──────────────────────────────────────────────────

def _project(pid="PRJ-EST"):
    db.put_collection_item("pm_projects", {"id": pid, "name": "Cleanroom Fit-out", "status": "Active"})
    return pid


def _budget_rows(pid):
    return [c for c in db.list_collection("pm_costs") if c.get("projectId") == pid]


def test_a_manager_below_management_cannot_set_a_project_budget(api, tokens):
    est_id, pid = _seed("EST-ADOPT-ACL"), _project("PRJ-ACL")
    st, _ = api("POST", "/api/est/adopt", tokens["mgr"], {"estId": est_id, "projectId": pid})
    assert st == 403
    assert _budget_rows(pid) == []


def test_a_draft_estimate_cannot_become_a_baseline(api, tokens):
    est_id, pid = _seed("EST-DRAFT", status="Draft"), _project("PRJ-DRAFT")
    st, r = api("POST", "/api/est/adopt", tokens["admin"], {"estId": est_id, "projectId": pid})
    assert st == 400
    assert "approved" in (r.get("error") or "").lower()
    assert _budget_rows(pid) == []


def test_an_approved_estimate_becomes_the_project_budget(api, tokens):
    est_id, pid = _seed("EST-ADOPT"), _project("PRJ-ADOPT")
    st, r = api("POST", "/api/est/adopt", tokens["admin"], {"estId": est_id, "projectId": pid})
    assert st == 200
    rows = _budget_rows(pid)
    assert rows and sum(int(c["budget"]) for c in rows) == r["total"]
    # Every line says where it came from, on the row itself.
    assert all(c.get("estimateNo") == "EST-2026-001" for c in rows)
    assert all("Adopted from estimate" in (c.get("note") or "") for c in rows)
    # And the categories are the ones the project module already uses.
    assert {c["category"] for c in rows} <= {"Labor", "Material", "Subcontract", "Equipment",
                                             "Overhead", "Other"}


def test_the_budget_is_the_cost_base_and_the_profit_is_deliberately_left_out(api, tokens):
    est_id, pid = _seed("EST-PROFIT"), _project("PRJ-PROFIT")
    st, r = api("POST", "/api/est/adopt", tokens["admin"], {"estId": est_id, "projectId": pid})
    _, s = api("GET", "/api/est/summary?id=" + est_id, tokens["admin"])
    assert r["total"] == s["summary"]["costBase"]
    assert r["excludesProfit"] == s["summary"]["profit"] > 0


def test_adopting_twice_is_refused_so_a_live_baseline_cannot_be_silently_rewritten(api, tokens):
    est_id, pid = _seed("EST-TWICE"), _project("PRJ-TWICE")
    st, _ = api("POST", "/api/est/adopt", tokens["admin"], {"estId": est_id, "projectId": pid})
    assert st == 200
    before = len(_budget_rows(pid))
    st2, r2 = api("POST", "/api/est/adopt", tokens["admin"], {"estId": est_id, "projectId": pid})
    assert st2 == 409
    assert "already adopted" in (r2.get("error") or "").lower()
    assert len(_budget_rows(pid)) == before      # and nothing was written the second time


def test_adopting_leaves_an_audit_entry_naming_both_documents(api, tokens):
    est_id, pid = _seed("EST-AUDIT"), _project("PRJ-AUDIT")
    api("POST", "/api/est/adopt", tokens["admin"], {"estId": est_id, "projectId": pid})
    hits = [a for a in db.list_collection("audit")
            if a.get("action") == "Estimate adopted as project budget" and a.get("target") == "EST-2026-001"]
    assert hits
    assert "Cleanroom Fit-out" in hits[-1]["detail"]


def test_an_unknown_project_is_refused_before_anything_is_written(api, tokens):
    est_id = _seed("EST-NOPROJ")
    st, _ = api("POST", "/api/est/adopt", tokens["admin"], {"estId": est_id, "projectId": "ghost"})
    assert st == 404
    assert not db.list_collection("est_projects") or not next(
        (e for e in db.list_collection("est_projects") if e.get("id") == est_id), {}
    ).get("adoptedProjectId")
