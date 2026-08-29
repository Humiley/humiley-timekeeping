"""/api/est/reprice — preview and apply, through the real boundary.

The rule this file exists for is the one a pure test cannot check: the preview and the write must be
the same computation. A preview costed by different code from the change is a preview that can lie,
and it is the thing somebody decides whether to re-price a live bid on.
"""
import db


def _tender(tid="TND-RP", **kw):
    row = {"id": tid, "estNo": "EST-2026-700", "quoteNo": "QT-2026-700", "title": "Ducting",
           "costingType": "boq", "status": "Draft", "client": "Acme",
           "clientTaxCode": "0123456789", "exclusions": "Crane hire",
           "overheadPct": 10, "riskPct": 0, "profitPct": 20, "profitBasis": "markup"}
    row.update(kw)
    db.put_collection_item("est_projects", row)
    return tid


def _rate(rid, cost, code="LAB-01"):
    db.put_collection_item("est_rates", {
        "id": rid, "code": code, "desc": "Fitter", "kind": "labour", "unit": "hour",
        "unitCost": cost, "effectiveFrom": "2026-08-01", "source": "2026 rate card"})
    return rid


def _bill(tid, rate_id, snapped, hand=None):
    """One line, one library-priced build-up, optionally one hand-priced one."""
    db.put_collection_item("est_items", {
        "id": tid + "-it", "estId": tid, "seq": "1", "kind": "item",
        "desc": "Ductwork", "unit": "m2", "qty": 10})
    db.put_collection_item("est_resources", {
        "id": tid + "-rs", "estId": tid, "itemId": tid + "-it", "kind": "labour",
        "desc": "Fitter", "qtyPer": 1, "unitCost": snapped, "rateId": rate_id})
    if hand is not None:
        db.put_collection_item("est_resources", {
            "id": tid + "-hand", "estId": tid, "itemId": tid + "-it", "kind": "material",
            "desc": "Crane hire, quoted", "qtyPer": 1, "unitCost": hand})


# ── the boundary ─────────────────────────────────────────────────────────────────────────────────

def test_staff_cannot_reprice_a_tender(api, tokens):
    tid = _tender("TND-RP-ACL")
    st, r = api("POST", "/api/est/reprice", tokens["staff"], {"estId": tid})
    assert st == 403


def test_a_missing_tender_is_a_404(api, tokens):
    st, _ = api("POST", "/api/est/reprice", tokens["admin"], {"estId": "ghost"})
    assert st == 404


# ── preview ──────────────────────────────────────────────────────────────────────────────────────

def test_a_preview_reports_the_move_and_changes_nothing(api, tokens):
    tid = _tender("TND-RP-1")
    _rate("rt-rp1", 120000)
    _bill(tid, "rt-rp1", 100000)
    st, r = api("POST", "/api/est/reprice", tokens["admin"], {"estId": tid})
    assert st == 200, r
    assert r["applied"] is False
    assert r["counts"]["changed"] == 1
    assert r["changes"][0]["was"] == 100000 and r["changes"][0]["now"] == 120000
    # nothing was written
    assert db.get_collection_item("est_resources", tid + "-rs")["unitCost"] == 100000


def test_the_preview_states_what_it_does_to_the_margin(api, tokens):
    """'The cost went up 4%' is only actionable next to what it does to the number somebody is
    defending."""
    tid = _tender("TND-RP-2")
    _rate("rt-rp2", 200000)
    _bill(tid, "rt-rp2", 100000)
    _, r = api("POST", "/api/est/reprice", tokens["admin"], {"estId": tid})
    assert r["after"]["directCost"] > r["before"]["directCost"]
    assert "achievedMarginPct" in r["before"] and "achievedMarginPct" in r["after"]


def test_a_tender_whose_rates_have_not_moved_reports_no_change(api, tokens):
    """'Nothing changed' is a real and useful answer, not an empty screen."""
    tid = _tender("TND-RP-3")
    _rate("rt-rp3", 120000)
    _bill(tid, "rt-rp3", 120000)
    _, r = api("POST", "/api/est/reprice", tokens["admin"], {"estId": tid})
    assert r["counts"]["changed"] == 0 and r["changes"] == []
    assert r["before"]["directCost"] == r["after"]["directCost"]


# ── apply ────────────────────────────────────────────────────────────────────────────────────────

def test_applying_writes_the_rows_the_preview_was_costed_from(api, tokens):
    """THE rule. Preview then apply must agree, because the preview is what the decision was made
    on — so the applied result is compared against the preview's own numbers."""
    tid = _tender("TND-RP-4")
    _rate("rt-rp4", 150000)
    _bill(tid, "rt-rp4", 100000)
    _, prev = api("POST", "/api/est/reprice", tokens["admin"], {"estId": tid})
    _, done = api("POST", "/api/est/reprice", tokens["admin"], {"estId": tid, "apply": True})
    assert done["applied"] is True
    assert done["after"]["directCost"] == prev["after"]["directCost"]
    assert done["after"]["achievedMarginPct"] == prev["after"]["achievedMarginPct"]
    assert db.get_collection_item("est_resources", tid + "-rs")["unitCost"] == 150000


def test_the_summary_afterwards_matches_what_the_preview_promised(api, tokens):
    """The independent check: price the tender through its own endpoint after applying."""
    tid = _tender("TND-RP-5")
    _rate("rt-rp5", 150000)
    _bill(tid, "rt-rp5", 100000)
    _, prev = api("POST", "/api/est/reprice", tokens["admin"], {"estId": tid})
    api("POST", "/api/est/reprice", tokens["admin"], {"estId": tid, "apply": True})
    st, s = api("GET", "/api/est/summary?id=" + tid, tokens["admin"])
    assert st == 200
    assert s["summary"]["directCost"] == prev["after"]["directCost"]


def test_a_hand_priced_build_up_is_untouched_by_the_write(api, tokens):
    """Not just absent from the plan — still carrying its number in the database afterwards."""
    tid = _tender("TND-RP-6")
    _rate("rt-rp6", 150000)
    _bill(tid, "rt-rp6", 100000, hand=777000)
    _, r = api("POST", "/api/est/reprice", tokens["admin"], {"estId": tid, "apply": True})
    assert r["counts"]["handPriced"] == 1
    assert db.get_collection_item("est_resources", tid + "-hand")["unitCost"] == 777000


def test_re_applying_a_second_time_changes_nothing_further(api, tokens):
    """Idempotent: the rates now match the library, so the second run has nothing to do."""
    tid = _tender("TND-RP-7")
    _rate("rt-rp7", 150000)
    _bill(tid, "rt-rp7", 100000)
    api("POST", "/api/est/reprice", tokens["admin"], {"estId": tid, "apply": True})
    _, again = api("POST", "/api/est/reprice", tokens["admin"], {"estId": tid, "apply": True})
    assert again["counts"]["changed"] == 0
    assert again["applied"] is False


def test_the_drift_panel_goes_quiet_after_a_reprice(api, tokens):
    """The point of the whole feature. If the summary still reports drift, nothing was fixed."""
    tid = _tender("TND-RP-8")
    _rate("rt-rp8", 150000)
    _bill(tid, "rt-rp8", 100000)
    _, before = api("GET", "/api/est/summary?id=" + tid, tokens["admin"])
    assert before["rateDrift"], "the fixture should start with drift to report"
    api("POST", "/api/est/reprice", tokens["admin"], {"estId": tid, "apply": True})
    _, after = api("GET", "/api/est/summary?id=" + tid, tokens["admin"])
    assert after["rateDrift"] == []


def test_a_tender_that_is_a_live_projects_budget_cannot_be_repriced(api, tokens):
    """Re-pricing it would move the baseline under a running job."""
    tid = _tender("TND-RP-9", adoptedProjectId="pm-1", status="Won")
    _rate("rt-rp9", 150000)
    _bill(tid, "rt-rp9", 100000)
    st, r = api("POST", "/api/est/reprice", tokens["admin"], {"estId": tid, "apply": True})
    assert st == 409
    assert db.get_collection_item("est_resources", tid + "-rs")["unitCost"] == 100000


def test_but_a_frozen_tender_may_still_be_PREVIEWED(api, tokens):
    """Seeing what today's rates would do to a won job is exactly the question somebody asks when
    the market moves. Looking is not changing."""
    tid = _tender("TND-RP-10", adoptedProjectId="pm-1", status="Won")
    _rate("rt-rp10", 150000)
    _bill(tid, "rt-rp10", 100000)
    st, r = api("POST", "/api/est/reprice", tokens["admin"], {"estId": tid})
    assert st == 200
    assert r["counts"]["changed"] == 1 and r["frozen"] is True
    assert db.get_collection_item("est_resources", tid + "-rs")["unitCost"] == 100000


def test_applying_is_written_to_the_audit_log(api, tokens):
    tid = _tender("TND-RP-11")
    _rate("rt-rp11", 150000)
    _bill(tid, "rt-rp11", 100000)
    api("POST", "/api/est/reprice", tokens["admin"], {"estId": tid, "apply": True})
    hits = [a for a in db.list_collection("audit")
            if a.get("action") == "Tender re-priced against the rate library"
            and a.get("target") == "EST-2026-700"]
    assert hits, "a tender's cost base changed and nothing recorded it"


def test_a_preview_is_not_audited_as_a_change(api, tokens):
    """An audit log that records looking is one nobody can read."""
    before = len([a for a in db.list_collection("audit")
                  if a.get("action") == "Tender re-priced against the rate library"])
    tid = _tender("TND-RP-12")
    _rate("rt-rp12", 150000)
    _bill(tid, "rt-rp12", 100000)
    api("POST", "/api/est/reprice", tokens["admin"], {"estId": tid})
    after = len([a for a in db.list_collection("audit")
                 if a.get("action") == "Tender re-priced against the rate library"])
    assert after == before
