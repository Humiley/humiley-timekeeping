"""Calibration over the API — the half that has to actually refuse.

tests/test_ahu_calibration.py proves the arithmetic. This proves the server reaches it: that a test
signed against an out-of-calibration instrument is turned away, that the register reports its own
gaps, and that a failed calibration can name every measurement it touched.
"""
import uuid

import pytest

import app
import db


UNIT = "ahu_units"
STEPS = "ahu_steps"
INSTR = "ahu_instruments"


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
        "family": "modular", "voltage": 400, "coilDesignBar": 16,
        "productionLead": "Staff One", "qcInspector": "Other Staff"})
    st, r = api("POST", "/api/ahu/unit/%s/route" % uid, tokens["admin"])
    assert st == 200, r
    return uid


def _steps(api, token, uid):
    st, r = api("GET", "/api/ahu/unit/" + uid, token)
    assert st == 200, r
    return {s["code"]: s for s in r["steps"]}


def _to_ipqc1(api, tokens, uid):
    """Walk the unit to the point where IPQC-1 is the next thing to sign."""
    steps = _steps(api, tokens["admin"], uid)
    api("POST", "/api/esign", tokens["admin"],
        {"coll": STEPS, "id": steps["G1"]["id"], "meaning": "G1", "setStatus": "Passed"})
    _mk(api, tokens["admin"], "ahu_docs",
        {"unitId": uid, "kind": "GA drawing", "status": "Issued", "docNo": "GA-001"})
    _mk(api, tokens["admin"], "ahu_bom",
        {"unitId": uid, "partNo": "FRM-01", "qty": 4, "kittedQty": 4,
         "receivedQty": 4, "iqcStatus": "Passed"})
    st, r = api("GET", "/api/ahu/unit/" + uid, tokens["admin"])
    api("PATCH", "/api/coll/%s/%s" % (UNIT, uid), tokens["admin"],
        dict(r["unit"], bomStatus="Released", selectionRef="AS-1234"))
    steps = _steps(api, tokens["admin"], uid)
    for g in ("G2", "G3"):
        api("POST", "/api/esign", tokens["admin"],
            {"coll": STEPS, "id": steps[g]["id"], "meaning": g, "setStatus": "Passed"})
    steps = _steps(api, tokens["admin"], uid)
    for ws in ("WS-01", "WS-02"):
        api("POST", "/api/esign", tokens["admin"],
            {"coll": STEPS, "id": steps[ws]["id"], "meaning": ws, "setStatus": "Complete"})
    return _steps(api, tokens["admin"], uid)


def _set_step(api, token, step, **kw):
    body = dict(step)
    body.update(kw)
    for k in ("verdict", "checks", "blockedBy", "spec"):
        body.pop(k, None)
    st, r = api("PATCH", "/api/coll/%s/%s" % (STEPS, step["id"]), token, body)
    assert st == 200, r
    return r


def _sign(api, token, step_id, status="Passed"):
    return api("POST", "/api/esign", token,
               {"coll": STEPS, "id": step_id, "meaning": "hold point", "setStatus": status})


# ── the refusal ──────────────────────────────────────────────────────────────────────────────────

def test_a_hold_point_signed_on_an_expired_instrument_is_refused(api, tokens, unit):
    """The whole point. A Part 11 signature attesting to a number, produced by an instrument the
    company itself records as out of calibration, asserts something it cannot stand behind."""
    iid = _mk(api, tokens["admin"], INSTR, {"name": "Old manometer", "calDue": "2020-01-01"})
    steps = _to_ipqc1(api, tokens, unit)
    _set_step(api, tokens["mgr"], steps["IPQC-1"],
              readings={"squareness": 0.6}, instrumentId=iid)
    st, r = _sign(api, tokens["mgr"], steps["IPQC-1"]["id"])
    assert st >= 400, r
    assert "out of calibration" in r.get("error", "")
    assert iid in r.get("error", "")


def test_the_same_step_signs_once_the_instrument_is_in_calibration(api, tokens, unit):
    """Proves the refusal above is about calibration and not about something else on the step."""
    iid = _mk(api, tokens["admin"], INSTR, {"name": "Good manometer", "calDue": "2099-01-01"})
    steps = _to_ipqc1(api, tokens, unit)
    _set_step(api, tokens["mgr"], steps["IPQC-1"],
              readings={"squareness": 0.6}, instrumentId=iid)
    st, r = _sign(api, tokens["mgr"], steps["IPQC-1"]["id"])
    assert st == 200, r


def test_an_instrument_reference_matching_nothing_is_refused(api, tokens, unit):
    steps = _to_ipqc1(api, tokens, unit)
    _set_step(api, tokens["mgr"], steps["IPQC-1"],
              readings={"squareness": 0.6}, instrumentId="NOT-A-REAL-ID")
    st, r = _sign(api, tokens["mgr"], steps["IPQC-1"]["id"])
    assert st >= 400 and "not in the calibration register" in r.get("error", "")


def test_naming_no_instrument_is_allowed_until_the_rule_is_switched_on(api, tokens, unit):
    """Off by default so a factory can populate its register before the rule bites."""
    steps = _to_ipqc1(api, tokens, unit)
    _set_step(api, tokens["mgr"], steps["IPQC-1"], readings={"squareness": 0.6})
    st, r = _sign(api, tokens["mgr"], steps["IPQC-1"]["id"])
    assert st == 200, r


def test_switching_the_rule_on_makes_the_instrument_mandatory(api, tokens, unit):
    steps = _to_ipqc1(api, tokens, unit)
    _set_step(api, tokens["mgr"], steps["IPQC-1"], readings={"squareness": 0.6})
    db.set_setting("ahu_require_instrument", "1")
    try:
        st, r = _sign(api, tokens["mgr"], steps["IPQC-1"]["id"])
        assert st >= 400 and "which instrument" in r.get("error", "")
    finally:
        db.set_setting("ahu_require_instrument", "")


def test_a_stored_false_does_not_switch_the_rule_on(base_url):
    """get_setting decodes, so a stored `false` returns the boolean while a stored "0" returns a
    truthy non-empty string. `bool(get_setting(...))` would turn the rule ON for both."""
    try:
        for off in ("0", "false", "no", "", False):
            db.set_setting("ahu_require_instrument", off)
            assert app.Handler._flag("ahu_require_instrument") is False, off
        for on in ("1", "true", "yes", True):
            db.set_setting("ahu_require_instrument", on)
            assert app.Handler._flag("ahu_require_instrument") is True, on
    finally:
        db.set_setting("ahu_require_instrument", "")


def test_a_gate_never_needs_an_instrument(api, tokens, unit):
    """A gate decides that a stage is complete; it measures nothing. Demanding an instrument there
    would train people to pick anything to get past the field."""
    db.set_setting("ahu_require_instrument", "1")
    try:
        steps = _steps(api, tokens["admin"], unit)
        st, r = api("POST", "/api/esign", tokens["admin"],
                    {"coll": STEPS, "id": steps["G1"]["id"], "meaning": "G1",
                     "setStatus": "Passed"})
        assert st == 200, r
    finally:
        db.set_setting("ahu_require_instrument", "")


# ── the register and its gaps ────────────────────────────────────────────────────────────────────

def test_the_register_reports_expired_due_soon_and_no_due_date_separately(api, tokens):
    exp = _mk(api, tokens["admin"], INSTR, {"name": "gaps-expired", "calDue": "2020-01-01"})
    none_ = _mk(api, tokens["admin"], INSTR, {"name": "gaps-nodate"})
    ok = _mk(api, tokens["admin"], INSTR, {"name": "gaps-fine", "calDue": "2099-01-01"})
    st, r = api("GET", "/api/ahu/instruments?today=2026-08-21", tokens["admin"])
    assert st == 200, r
    assert exp in str(r["gaps"]["EXPIRED"])
    assert none_ in str(r["gaps"]["UNKNOWN"])
    assert ok not in str(r["gaps"])


def test_an_instrument_with_no_due_date_is_not_reported_as_valid(api, tokens):
    iid = _mk(api, tokens["admin"], INSTR, {"name": "unrecorded"})
    st, r = api("GET", "/api/ahu/instruments?today=2026-08-21", tokens["admin"])
    row = next(i for i in r["instruments"] if i["id"] == iid)
    assert row["calStatus"]["status"] == "UNKNOWN"


def test_untraced_signed_tests_are_named(api, tokens, unit):
    steps = _to_ipqc1(api, tokens, unit)
    _set_step(api, tokens["mgr"], steps["IPQC-1"], readings={"squareness": 0.6})
    assert _sign(api, tokens["mgr"], steps["IPQC-1"]["id"])[0] == 200
    st, r = api("GET", "/api/ahu/instruments", tokens["admin"])
    assert st == 200
    assert any(x["code"] == "IPQC-1" and x["unitId"] == unit for x in r["untraced"])


def test_the_register_is_closed_when_the_app_is_denied(api, tokens):
    before = (db.get_employee("HML-STF") or {}).get("appsDenied")
    db.update_employee("HML-STF", {"appsDenied": "ahu"})
    try:
        st, r = api("GET", "/api/ahu/instruments", tokens["staff"])
        assert st == 403 and "not enabled" in r["error"]
    finally:
        db.update_employee("HML-STF", {"appsDenied": before or ""})


# ── the question a failed calibration asks ───────────────────────────────────────────────────────

def test_a_failed_calibration_names_every_measurement_it_touched(api, tokens, unit):
    """Without this the only defensible answer to "this manometer was reading 4% high" is to
    re-test everything it might have touched."""
    iid = _mk(api, tokens["admin"], INSTR, {"name": "Manometer", "calDue": "2099-01-01"})
    steps = _to_ipqc1(api, tokens, unit)
    _set_step(api, tokens["mgr"], steps["IPQC-1"],
              readings={"squareness": 0.6}, instrumentId=iid)
    assert _sign(api, tokens["mgr"], steps["IPQC-1"]["id"])[0] == 200

    # The calibration check comes back bad: the instrument was actually due long ago.
    st, r = api("GET", "/api/ahu/instruments", tokens["admin"])
    inst = next(i for i in r["instruments"] if i["id"] == iid)
    inst.pop("calStatus", None)
    st, r = api("PATCH", "/api/coll/%s/%s" % (INSTR, iid), tokens["admin"],
                dict(inst, calDue="2020-01-01"))
    assert st == 200, r

    st, r = api("GET", "/api/ahu/instrument/%s/affected" % iid, tokens["admin"])
    assert st == 200, r
    assert any(x["code"] == "IPQC-1" for x in r["suspect"])
    assert r["unitsAffected"], "the affected units must be named, not just the steps"


def test_an_unknown_instrument_has_no_affected_list(api, tokens):
    st, r = api("GET", "/api/ahu/instrument/no-such-thing/affected", tokens["admin"])
    assert st == 404
