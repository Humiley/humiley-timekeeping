"""The start stamp and the labour analysis, over the API.

tests/test_ahu_labour.py proves the arithmetic. This proves the server reaches it, and pins the two
properties the stamp is worthless without: it comes from the SERVER, and pressing Start twice does
not move it.
"""
import uuid

import pytest

import app
import db


UNIT = "ahu_units"
STEPS = "ahu_steps"


@pytest.fixture(autouse=True)
def _signable(monkeypatch):
    monkeypatch.setattr(app, "DEMO_MODE", True)


def _mk(api, token, coll, body):
    st, r = api("POST", "/api/coll/" + coll, token, body)
    assert st == 200, (coll, st, r)
    return r.get("id") or (r.get("item") or {}).get("id")


@pytest.fixture
def unit(api, tokens):
    order = _mk(api, tokens["admin"], "ahu_orders", {
        "poNumber": "PO-" + uuid.uuid4().hex[:6], "customer": "Acme Pharma",
        "contractReviewSigned": True, "scheduleBaselined": True,
        "productionLead": "Staff One", "qcInspector": "Other Staff"})
    uid = _mk(api, tokens["admin"], UNIT, {
        "orderId": order, "pin": "PIN-" + uuid.uuid4().hex[:6], "tag": "AHU-01",
        "family": "modular", "voltage": 400, "coilDesignBar": 16, "sectionCount": 4,
        "productionLead": "Staff One", "qcInspector": "Other Staff"})
    st, r = api("POST", "/api/ahu/unit/%s/route" % uid, tokens["admin"])
    assert st == 200, r
    return uid


def _steps(api, token, uid):
    st, r = api("GET", "/api/ahu/unit/" + uid, token)
    assert st == 200, r
    return {s["code"]: s for s in r["steps"]}


# ── the start stamp ──────────────────────────────────────────────────────────────────────────────

def test_starting_a_step_records_a_server_side_instant(api, tokens, unit):
    steps = _steps(api, tokens["admin"], unit)
    st, r = api("PATCH", "/api/ahu/step/%s/start" % steps["WS-01"]["id"], tokens["mgr"])
    assert st == 200, r
    assert r["startedAt"].endswith("Z") and r["startedAt"].startswith("20")


def test_starting_twice_keeps_the_first_stamp(api, tokens, unit):
    """The second press is somebody coming back to a job. Moving the start forward would quietly
    shorten the very measurement this exists to take."""
    steps = _steps(api, tokens["admin"], unit)
    sid = steps["WS-01"]["id"]
    first = api("PATCH", "/api/ahu/step/%s/start" % sid, tokens["mgr"])[1]["startedAt"]
    second = api("PATCH", "/api/ahu/step/%s/start" % sid, tokens["mgr"])[1]
    assert second["startedAt"] == first and second["already"] is True


def test_the_start_is_not_taken_from_the_caller(api, tokens, unit):
    """A browser-supplied start could be backdated, and the whole value of the field is that the gap
    to the signature is real. The endpoint accepts no body at all."""
    steps = _steps(api, tokens["admin"], unit)
    sid = steps["WS-01"]["id"]
    st, r = api("PATCH", "/api/ahu/step/%s/start" % sid, tokens["mgr"],
                {"startedAt": "2020-01-01T00:00:00Z"})
    assert st == 200
    assert not r["startedAt"].startswith("2020")


def test_a_signed_step_cannot_be_started(api, tokens, unit):
    """Starting it again would rewrite a signed record."""
    steps = _steps(api, tokens["admin"], unit)
    st, _ = api("POST", "/api/esign", tokens["admin"],
                {"coll": STEPS, "id": steps["G1"]["id"], "meaning": "G1", "setStatus": "Passed"})
    assert st == 200
    st, r = api("PATCH", "/api/ahu/step/%s/start" % steps["G1"]["id"], tokens["admin"])
    assert st == 409 and "already signed" in r["error"]


def test_starting_an_unknown_step_is_refused(api, tokens):
    st, r = api("PATCH", "/api/ahu/step/no-such-step/start", tokens["admin"])
    assert st == 404


def test_the_start_is_closed_when_the_app_is_denied(api, tokens, unit):
    steps = _steps(api, tokens["admin"], unit)
    before = (db.get_employee("HML-STF") or {}).get("appsDenied")
    db.update_employee("HML-STF", {"appsDenied": "ahu"})
    try:
        st, r = api("PATCH", "/api/ahu/step/%s/start" % steps["WS-01"]["id"], tokens["staff"])
        assert st == 403 and "not enabled" in r["error"]
    finally:
        db.update_employee("HML-STF", {"appsDenied": before or ""})


# ── the analysis ─────────────────────────────────────────────────────────────────────────────────

def test_the_analysis_reports_the_route_as_strictly_serial(api, tokens):
    st, r = api("GET", "/api/ahu/labour?sections=4&family=modular", tokens["admin"])
    assert st == 200, r
    assert r["criticalPath"]["serialShare"] == 100
    assert r["criticalPath"]["criticalPathH"] == r["criticalPath"]["totalWorkH"]


def test_the_analysis_prices_the_spread_from_the_sops_own_bands(api, tokens):
    st, r = api("GET", "/api/ahu/labour?sections=4", tokens["admin"])
    assert r["spread"]["worstH"] > r["spread"]["bestH"]
    assert r["spread"]["stations"][0]["code"] == "WS-04"


def test_fixed_labour_does_not_move_with_the_section_count(api, tokens):
    a = api("GET", "/api/ahu/labour?sections=1", tokens["admin"])[1]["cost"]
    b = api("GET", "/api/ahu/labour?sections=8", tokens["admin"])[1]["cost"]
    assert a["fixedH"] == b["fixedH"]
    assert a["fixedPct"] > b["fixedPct"], "a small unit carries more of the fixed hours"


def test_the_parallel_options_are_priced_with_their_caveat(api, tokens):
    st, r = api("GET", "/api/ahu/labour", tokens["admin"])
    assert r["parallelOptions"]
    for p in r["parallelOptions"]:
        assert "question for the production lead" in p["caveat"]


def test_an_unknown_family_is_refused_rather_than_defaulted(api, tokens):
    st, r = api("GET", "/api/ahu/labour?family=kappa", tokens["admin"])
    assert st == 400


def test_a_started_and_signed_step_is_measured_as_touch_time(api, tokens, unit):
    """The whole point of the stamp: a run measured hands-on rather than as a gap between
    sign-offs, and labelled so the two are never averaged together."""
    steps = _steps(api, tokens["admin"], unit)
    api("POST", "/api/esign", tokens["admin"],
        {"coll": STEPS, "id": steps["G1"]["id"], "meaning": "G1", "setStatus": "Passed"})
    _mk(api, tokens["admin"], "ahu_docs",
        {"unitId": unit, "kind": "GA drawing", "status": "Issued", "docNo": "GA-1"})
    _mk(api, tokens["admin"], "ahu_bom",
        {"unitId": unit, "partNo": "P", "qty": 1, "kittedQty": 1, "receivedQty": 1,
         "iqcStatus": "Passed"})
    st, r = api("GET", "/api/ahu/unit/" + unit, tokens["admin"])
    api("PATCH", "/api/coll/%s/%s" % (UNIT, unit), tokens["admin"],
        dict(r["unit"], bomStatus="Released", selectionRef="AS-1"))
    steps = _steps(api, tokens["admin"], unit)
    for g in ("G2", "G3"):
        api("POST", "/api/esign", tokens["admin"],
            {"coll": STEPS, "id": steps[g]["id"], "meaning": g, "setStatus": "Passed"})
    steps = _steps(api, tokens["admin"], unit)
    api("PATCH", "/api/ahu/step/%s/start" % steps["WS-01"]["id"], tokens["admin"])
    st, _ = api("POST", "/api/esign", tokens["admin"],
                {"coll": STEPS, "id": steps["WS-01"]["id"], "meaning": "WS-01",
                 "setStatus": "Complete"})
    assert st == 200

    st, r = api("GET", "/api/ahu/labour", tokens["admin"])
    assert r["touchRuns"] >= 1, "a started-then-signed step must be measured as touch time"
    ws1 = next((g for g in r["stations"] if g["code"] == "WS-01"), None)
    assert ws1 and "touch" in ws1["sources"]
