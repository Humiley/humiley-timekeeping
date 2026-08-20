"""Regression tests for five defects found reviewing the AHU module after it shipped.

Each one had a reproduction. They are written here as the reproduction rather than as a paraphrase,
so if any of them comes back it fails here rather than in a factory.
"""
import uuid

import pytest

import ahu
import ahu_route
import app
import db


@pytest.fixture(autouse=True)
def _signable(monkeypatch):
    monkeypatch.setattr(app, "DEMO_MODE", True)


def _mk(api, token, coll, body):
    st, r = api("POST", "/api/coll/" + coll, token, body)
    assert st == 200, (coll, st, r)
    return r.get("id") or (r.get("item") or {}).get("id")


@pytest.fixture
def unit(api, tokens):
    oid = _mk(api, tokens["admin"], "ahu_orders", {
        "poNumber": "PO-" + uuid.uuid4().hex[:6], "contractReviewSigned": True,
        "scheduleBaselined": "Yes", "productionLead": "Staff One", "qcInspector": "Other Staff"})
    uid = _mk(api, tokens["admin"], "ahu_units", {
        "orderId": oid, "pin": "PIN-" + uuid.uuid4().hex[:6], "family": "modular",
        "productionLead": "Staff One", "qcInspector": "Other Staff"})
    api("POST", "/api/ahu/unit/%s/route" % uid, tokens["admin"])
    return uid


def _steps(api, token, uid):
    st, r = api("GET", "/api/ahu/unit/" + uid, token)
    assert st == 200, r
    return {s["code"]: s for s in r["steps"]}


# ── 1 & 2. A signed step must not be deletable ───────────────────────────────────────────────────

def _sign_g1(api, tokens, uid):
    s = _steps(api, tokens["admin"], uid)["G1"]
    st, r = api("POST", "/api/esign", tokens["admin"],
                {"coll": "ahu_steps", "id": s["id"], "meaning": "Gate G1", "setStatus": "Passed"})
    assert st == 200, r
    return s["id"]


def test_a_signed_step_cannot_be_deleted_by_anyone(api, tokens, unit):
    """It records what was measured when somebody put their name to it. Deleting it is strictly
    worse than editing it, which is already refused."""
    sid = _sign_g1(api, tokens, unit)
    for who in ("staff", "mgr", "admin"):
        st, r = api("DELETE", "/api/coll/ahu_steps/" + sid, tokens[who])
        assert st == 403, (who, st, r)
        assert "signed" in r.get("error", "").lower()
    assert db.get_collection_item("ahu_steps", sid) is not None


def test_an_unsigned_step_is_still_deletable_by_someone_with_standing(api, tokens, unit):
    """The guard must bite on the signature, not on the collection."""
    sid = _steps(api, tokens["admin"], unit)["WS-01"]["id"]
    st, _ = api("DELETE", "/api/coll/ahu_steps/" + sid, tokens["admin"])
    assert st == 200


def test_a_stranger_cannot_delete_a_production_record(api, tokens, unit):
    """ahu_ was missing from the delete-ownership guard that already covered crm_, pm_ and eng_,
    and ahu_steps is staff-writable, so nothing stopped an unrelated staff account."""
    sid = _steps(api, tokens["admin"], unit)["WS-02"]["id"]
    st, r = api("DELETE", "/api/coll/ahu_steps/" + sid, tokens["other"])
    assert st == 403, r
    assert "your own records" in r.get("error", "")
    assert db.get_collection_item("ahu_steps", sid) is not None


def test_a_closed_non_conformance_cannot_be_deleted(api, tokens, unit):
    nid = _mk(api, tokens["admin"], "ahu_ncr", {
        "unitId": unit, "ncrNo": "NCR-1", "title": "Gasket gap", "disposition": "Rework",
        "raisedBy": "Other Staff"})
    st, r = api("POST", "/api/esign", tokens["admin"],
                {"coll": "ahu_ncr", "id": nid, "meaning": "NCR closed", "setStatus": "Closed"})
    assert st == 200, r
    st, r = api("DELETE", "/api/coll/ahu_ncr/" + nid, tokens["admin"])
    assert st == 403, r


# ── 3. One mistyped family must not take the board down ──────────────────────────────────────────

def test_a_family_that_cannot_be_built_is_refused_on_the_way_in(api, tokens):
    st, r = api("POST", "/api/coll/ahu_units", tokens["admin"],
                {"pin": "PIN-BAD", "family": "kappa"})
    assert st == 400
    assert "not an AHU product family" in r["error"]
    assert "modular" in r["error"]


def test_a_bad_family_is_refused_on_update_too(api, tokens, unit):
    st, r = api("GET", "/api/ahu/unit/" + unit, tokens["admin"])
    u = dict(r["unit"], family="kappa")
    st, r = api("PATCH", "/api/coll/ahu_units/" + unit, tokens["admin"], u)
    assert st == 400, r


def test_a_blank_family_is_still_allowed(api, tokens):
    """A unit can exist before somebody has decided what it is."""
    st, _ = api("POST", "/api/coll/ahu_units", tokens["admin"], {"pin": "PIN-TBD"})
    assert st == 200


def test_the_board_survives_a_unit_whose_route_cannot_be_built(api, tokens, unit):
    """The board is the screen people leave open on a wall. One malformed record used to return
    500 to EVERY user, because the board builds every unit's route."""
    bad = db.get_collection_item("ahu_units", unit)
    bad["family"] = "kappa"                      # straight past the API, as a bad migration would
    db.put_collection_item("ahu_units", bad)
    st, r = api("GET", "/api/ahu/board", tokens["admin"])
    assert st == 200, r
    row = next(x for x in r["units"] if x["unitId"] == unit)
    assert row["routeError"]
    assert "kappa" in row["routeError"]


def test_safe_build_reports_the_problem_instead_of_raising():
    steps, err = ahu.safe_build_for({"id": "U", "family": "kappa"})
    assert steps == [] and "kappa" in err
    steps, err = ahu.safe_build_for({"id": "U", "family": "modular"})
    assert steps and err is None


# ── 4. AHU must be controllable under Access & Permissions ───────────────────────────────────────

def test_the_permissions_screen_can_switch_ahu_off():
    """_ahu_gate honours appsDenied, but nothing could put 'ahu' into it — the gate worked and was
    unreachable."""
    html = open("templates/index.html", encoding="utf-8").read()
    assert "ahu: denied.indexOf('ahu') < 0" in html
    assert "'crm','pm','eng','est','ahu','hr','finance','procurement'" in html
    assert "_appChk(ahuOn, 'ahu', 'AHU Production')" in html


def test_denying_the_app_actually_closes_the_endpoints(api, tokens, unit):
    emp = db.get_employee("HML-STF")
    before = emp.get("appsDenied")
    db.update_employee("HML-STF", {"appsDenied": "ahu"})
    try:
        st, r = api("GET", "/api/ahu/board", tokens["staff"])
        assert st == 403
        assert "not enabled" in r["error"]
    finally:
        db.update_employee("HML-STF", {"appsDenied": before or ""})


# ── 5. A failed step still carries a signature ───────────────────────────────────────────────────

def test_a_failed_step_is_not_treated_as_passed():
    """The distinction that matters most: a gate must not count a failure as done."""
    assert ahu.is_passed({"status": "Failed", "signedBy": "QC Lead"}) is False
    assert ahu.is_passed({"status": "Passed"}) is True


def test_a_failed_step_that_leaves_the_route_is_kept_and_flagged():
    """It is the record you would most want to still see."""
    failed = {"code": "WS-07", "kind": "op", "stage": 5, "seq": 1,
              "status": "Failed", "signedBy": "Production Lead"}
    out = ahu.instantiate({"id": "U", "family": "packaged"}, existing=[failed])
    ws07 = next((r for r in out if r["code"] == "WS-07"), None)
    assert ws07 is not None, "a failed, signed step was silently discarded"
    assert ws07["orphan"] is True


def test_a_failed_step_does_not_let_the_gate_pass(api, tokens, unit):
    """The regression this pair of functions exists to prevent."""
    steps = _steps(api, tokens["admin"], unit)
    st, r = api("POST", "/api/esign", tokens["admin"],
                {"coll": "ahu_steps", "id": steps["G1"]["id"], "meaning": "G1",
                 "setStatus": "Failed"})
    assert st == 200, r
    st, r = api("GET", "/api/ahu/unit/" + unit, tokens["admin"])
    g1 = next(s for s in r["steps"] if s["code"] == "G1")
    assert g1["signedBy"], "a failure is signed too — who decided it is what an investigation needs"
    # ...and G2 still waits on G1, because a failed G1 is not a passed G1.
    g2 = next(s for s in r["steps"] if s["code"] == "G2")
    assert "G1" in g2["blockedBy"]
