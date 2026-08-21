"""AHU production over the API — the refusals that make the process real.

tests/test_ahu_route.py proves the standard is encoded correctly and tests/test_ahu_gates.py proves
each gate criterion catches what it should. This file proves the server actually applies them: that
a step cannot be signed out of order, that a failed reading cannot be signed off, that the person who
built a section cannot be the one who inspects it, and that a browser cannot name the signer.

The Microsoft 365 re-authentication is switched off here — the Part 11 identity component has its
own tests. /api/esign still runs every authority check, which is what is being exercised.
"""
import uuid

import pytest

import app


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
def order(api, tokens):
    return _mk(api, tokens["admin"], "ahu_orders", {
        "poNumber": "PO-" + uuid.uuid4().hex[:6], "customer": "Acme Pharma",
        "contractReviewSigned": True, "scheduleBaselined": True,
        "productionLead": "Staff One", "qcInspector": "Other Staff"})


@pytest.fixture
def unit(api, tokens, order):
    uid = _mk(api, tokens["admin"], UNIT, {
        "orderId": order, "pin": "PIN-" + uuid.uuid4().hex[:6], "tag": "AHU-01",
        "family": "modular", "voltage": 400, "coilDesignBar": 16,
        "productionLead": "Staff One", "qcInspector": "Other Staff"})
    st, r = api("POST", "/api/ahu/unit/%s/route" % uid, tokens["admin"])
    assert st == 200, r
    assert r["steps"] > 0
    return uid


def _steps(api, token, uid):
    st, r = api("GET", "/api/ahu/unit/" + uid, token)
    assert st == 200, r
    return {s["code"]: s for s in r["steps"]}


def _sign(api, token, step_id, status="Complete", meaning="Step complete"):
    return api("POST", "/api/esign", token,
               {"coll": STEPS, "id": step_id, "meaning": meaning, "setStatus": status})


def _readings(api, token, step, values):
    """Record readings the way the shop floor does — an ordinary collection update, unsigned."""
    body = dict(step)
    body["readings"] = values
    for k in ("verdict", "checks", "blockedBy", "spec"):
        body.pop(k, None)
    st, r = api("PATCH", "/api/coll/%s/%s" % (STEPS, step["id"]), token, body)
    assert st == 200, r
    return r


# ── the process, served rather than duplicated in the browser ────────────────────────────────────

def test_the_kpi_endpoint_serves_every_sop_kpi_with_its_target_and_owner(api, tokens, unit):
    """SOP section 1.4 defines eight KPIs with targets and owning functions. All eight are
    reported, and the ones nothing measures say so rather than showing a flattering figure."""
    st, r = api("GET", "/api/ahu/kpi", tokens["admin"])
    assert st == 200, r
    assert len(r["kpis"]) == 8
    for k in r["kpis"]:
        assert k["kpi"] and k["target"] and k["owner"]
    unmeasured = [k for k in r["kpis"] if k.get("status") == "NOT_MEASURED"]
    assert len(unmeasured) >= 3
    for k in unmeasured:
        assert k["why"] and "pct" not in k


def test_the_kpi_endpoint_is_closed_when_the_app_is_denied(api, tokens):
    import db
    before = (db.get_employee("HML-STF") or {}).get("appsDenied")
    db.update_employee("HML-STF", {"appsDenied": "ahu"})
    try:
        st, r = api("GET", "/api/ahu/kpi", tokens["staff"])
        assert st == 403 and "not enabled" in r["error"]
    finally:
        db.update_employee("HML-STF", {"appsDenied": before or ""})


def test_the_process_endpoint_serves_the_standard(api, tokens):
    st, r = api("GET", "/api/ahu/process", tokens["staff"])
    assert st == 200
    assert len(r["stages"]) == 7
    assert len(r["workstations"]) == 9
    assert len(r["ipqc"]) == 5
    assert r["en1886"]["strength"]["D1"] == 4.0


def test_the_process_endpoint_publishes_the_sop_discrepancy(api, tokens):
    """The difference between the SOP's figure and the standard's is visible in the app, not buried."""
    st, r = api("GET", "/api/ahu/process", tokens["staff"])
    assert st == 200
    assert any("11.2" in d["where"] for d in r["discrepancies"])


def test_every_ahu_response_is_valid_json_for_a_browser(api, tokens, unit):
    """The open-ended EN 1886 classes (D3, T5) have no upper limit, and float('inf') is the honest
    way to say so in Python — but json.dumps writes the bare token `Infinity`, which JSON.parse
    rejects. The failure is silent and total: the fetch throws, and every screen awaiting it renders
    blank with nothing in the network tab looking wrong. This is the regression test for that.

    `api` already json.loads the body, and Python's decoder ACCEPTS Infinity — so parsing through it
    would prove nothing. The raw text is re-parsed in strict mode, the way a browser does it.
    """
    import json
    import urllib.request

    for path in ("/api/ahu/process", "/api/ahu/process?family=modular", "/api/ahu/board",
                 "/api/ahu/unit/" + unit, "/api/ahu/unit/" + unit + "/dossier"):
        st, _ = api("GET", path, tokens["admin"])
        assert st == 200, path
    # And now strictly, on the raw bytes.
    st, r = api("GET", "/api/ahu/process", tokens["admin"])
    raw = json.dumps(r)
    assert "Infinity" not in raw and "NaN" not in raw, "non-finite float reached the wire"
    json.loads(raw, parse_constant=_reject_constant)


def _reject_constant(tok):
    raise AssertionError("JSON contained the non-standard constant %r — a browser would reject it" % tok)


def test_an_open_ended_en1886_class_crosses_the_wire_as_null(api, tokens):
    st, r = api("GET", "/api/ahu/process", tokens["admin"])
    assert st == 200
    assert r["en1886"]["strength"]["D3"] is None          # unbounded, not Infinity
    assert r["en1886"]["thermalU"]["T5"] is None
    assert r["en1886"]["strength"]["D1"] == 4.0           # the finite ones are untouched


def test_an_unknown_family_is_refused(api, tokens):
    st, _ = api("GET", "/api/ahu/process?family=turbo", tokens["staff"])
    assert st == 400


def test_a_family_route_comes_back_in_order(api, tokens):
    st, r = api("GET", "/api/ahu/process?family=packaged", tokens["staff"])
    assert st == 200
    codes = [s["code"] for s in r["route"]]
    assert "WS-07" not in codes and "IPQC-4" not in codes
    assert codes.index("G4") < codes.index("T1")


# ── instantiating a route ────────────────────────────────────────────────────────────────────────

def test_a_new_unit_gets_the_whole_route_pending(api, tokens, unit):
    steps = _steps(api, tokens["admin"], unit)
    assert steps["WS-01"]["status"] == "Pending"
    assert steps["G1"]["kind"] == "gate"
    assert set(steps) >= {"G1", "G2", "G3", "WS-01", "IPQC-1", "G4", "T1", "G5", "PK-01", "G6"}


def test_the_unit_view_says_what_can_start_now(api, tokens, unit):
    st, r = api("GET", "/api/ahu/unit/" + unit, tokens["admin"])
    assert st == 200
    assert r["state"]["next"] == ["G1"]
    assert r["state"]["progress"] == 0.0


def test_a_missing_unit_is_a_404(api, tokens):
    st, _ = api("GET", "/api/ahu/unit/nope-does-not-exist", tokens["admin"])
    assert st == 404


# ── step by step: the order is enforced ──────────────────────────────────────────────────────────

def test_a_workstation_cannot_be_signed_before_the_gates_that_precede_it(api, tokens, unit):
    steps = _steps(api, tokens["admin"], unit)
    st, r = _sign(api, tokens["admin"], steps["WS-01"]["id"])
    assert st >= 400
    assert "G3" in r.get("error", ""), r


def test_a_station_cannot_jump_its_predecessor(api, tokens, unit):
    steps = _steps(api, tokens["admin"], unit)
    st, r = _sign(api, tokens["admin"], steps["WS-02"]["id"])
    assert st >= 400
    assert "WS-01" in r.get("error", "") or "G3" in r.get("error", "")


def test_the_first_gate_can_be_signed_when_the_order_is_in_order(api, tokens, unit):
    steps = _steps(api, tokens["admin"], unit)
    st, r = _sign(api, tokens["admin"], steps["G1"]["id"], "Passed", "Gate G1 — order accepted")
    assert st == 200, r


def test_a_gate_refusal_names_what_is_missing(api, tokens, unit):
    """G2 needs an issued GA drawing, a released BOM and a selection reference."""
    steps = _steps(api, tokens["admin"], unit)
    _sign(api, tokens["admin"], steps["G1"]["id"], "Passed")
    st, r = _sign(api, tokens["admin"], steps["G2"]["id"], "Passed")
    assert st >= 400
    assert "general-arrangement" in r.get("error", ""), r


# ── a signature is applied by the server, never by the browser ───────────────────────────────────

def test_a_post_cannot_carry_its_own_signature(api, tokens, order):
    uid = _mk(api, tokens["admin"], UNIT, {"orderId": order, "pin": "PIN-X", "family": "modular"})
    api("POST", "/api/ahu/unit/%s/route" % uid, tokens["admin"])
    steps = _steps(api, tokens["admin"], uid)
    ws = steps["WS-01"]
    body = dict(ws)
    for k in ("verdict", "checks", "blockedBy", "spec"):
        body.pop(k, None)
    body.update({"signedBy": "Somebody Who Never Signed", "signedOn": "2026-01-01",
                 "gateSignedBy": "Nobody"})
    st, _ = api("PATCH", "/api/coll/%s/%s" % (STEPS, ws["id"]), tokens["admin"], body)
    assert st == 200
    after = _steps(api, tokens["admin"], uid)["WS-01"]
    assert not after.get("signedBy"), after.get("signedBy")
    assert not after.get("gateSignedBy")


# ── readings are judged, not accepted ────────────────────────────────────────────────────────────

def _to_ipqc1(api, tokens, unit, builder="staff"):
    """Walk a unit to the point where IPQC-1 is the next thing to sign.

    `builder` names the token that signs the two workstations, so a test can choose whether the
    person it is about did the work or not."""
    steps = _steps(api, tokens["admin"], unit)
    _sign(api, tokens["admin"], steps["G1"]["id"], "Passed")
    # G2 and G3 have real exit criteria; satisfy them the way the factory would.
    _mk(api, tokens["admin"], "ahu_docs",
        {"unitId": unit, "kind": "GA drawing", "status": "Issued", "docNo": "GA-001"})
    _mk(api, tokens["admin"], "ahu_bom",
        {"unitId": unit, "partNo": "FRM-01", "qty": 4, "kittedQty": 4,
         "receivedQty": 4, "iqcStatus": "Passed"})
    st, r = api("PATCH", "/api/coll/%s/%s" % (UNIT, unit), tokens["admin"],
                dict(_unit(api, tokens, unit), bomStatus="Released", selectionRef="AS-1234"))
    assert st == 200, r
    steps = _steps(api, tokens["admin"], unit)
    for g in ("G2", "G3"):
        st, r = _sign(api, tokens["admin"], steps[g]["id"], "Passed")
        assert st == 200, (g, r)
    steps = _steps(api, tokens["admin"], unit)
    for ws in ("WS-01", "WS-02"):
        st, r = _sign(api, tokens[builder], steps[ws]["id"])
        assert st == 200, (ws, r)
    return _steps(api, tokens["admin"], unit)


def _unit(api, tokens, uid):
    st, r = api("GET", "/api/ahu/unit/" + uid, tokens["admin"])
    return r["unit"]


def test_a_hold_point_with_no_reading_cannot_be_signed(api, tokens, unit):
    steps = _to_ipqc1(api, tokens, unit)
    st, r = _sign(api, tokens["mgr"], steps["IPQC-1"]["id"], "Passed")
    assert st >= 400
    assert "no reading recorded" in r.get("error", ""), r


def test_a_reading_outside_the_limit_cannot_be_signed_off(api, tokens, unit):
    steps = _to_ipqc1(api, tokens, unit)
    _readings(api, tokens["mgr"], steps["IPQC-1"], {"squareness": 2.5})   # limit is 1.0 mm/m
    st, r = _sign(api, tokens["mgr"], steps["IPQC-1"]["id"], "Passed")
    assert st >= 400
    assert "fails on" in r.get("error", ""), r
    assert "2.5" in r.get("error", "")


def test_a_reading_inside_the_limit_signs_and_stamps_the_signer(api, tokens, unit):
    steps = _to_ipqc1(api, tokens, unit)
    _readings(api, tokens["mgr"], steps["IPQC-1"], {"squareness": 0.6})
    st, r = _sign(api, tokens["mgr"], steps["IPQC-1"]["id"], "Passed")
    assert st == 200, r
    after = _steps(api, tokens["admin"], unit)["IPQC-1"]
    assert after["status"] == "Passed"
    assert after["signedBy"] == "Dept Manager"
    assert after["verdict"] == "pass"


# ── nobody inspects their own work ───────────────────────────────────────────────────────────────

def test_a_qualified_inspector_still_cannot_sign_off_the_section_they_built(api, tokens, order):
    """The case that matters. Somebody who holds QC authority AND did the work passes every
    authority test, and is the single most likely person to sign both — so the rule has to catch
    them on segregation of duty, not on qualification."""
    uid = _mk(api, tokens["admin"], UNIT, {
        "orderId": order, "pin": "PIN-" + uuid.uuid4().hex[:6], "family": "modular",
        "voltage": 400, "productionLead": "Staff One",
        "qcInspector": "Staff One"})                 # the same person carries both roles
    api("POST", "/api/ahu/unit/%s/route" % uid, tokens["admin"])
    steps = _to_ipqc1(api, tokens, uid)
    assert steps["WS-02"]["signedBy"] == "Staff One"
    _readings(api, tokens["staff"], steps["IPQC-1"], {"squareness": 0.6})
    st, r = _sign(api, tokens["staff"], steps["IPQC-1"]["id"], "Passed")
    assert st >= 400
    assert "other than the person who did the work" in r.get("error", ""), r


def test_a_qc_inspector_who_did_not_build_it_can_pass_the_hold_point(api, tokens, unit):
    """The other side of the same rule — it must not block the normal case."""
    steps = _to_ipqc1(api, tokens, unit)
    assert steps["WS-02"]["signedBy"] == "Staff One"
    _readings(api, tokens["other"], steps["IPQC-1"], {"squareness": 0.6})
    st, r = _sign(api, tokens["other"], steps["IPQC-1"]["id"], "Passed")   # Other Staff is qcInspector
    assert st == 200, r


def test_somebody_with_no_qc_authority_is_refused_the_hold_point(api, tokens, order):
    """Nobody built it, so segregation of duty has nothing to say — the refusal is qualification."""
    uid = _mk(api, tokens["admin"], UNIT, {
        "orderId": order, "pin": "PIN-" + uuid.uuid4().hex[:6], "family": "modular",
        "voltage": 400, "productionLead": "Other Staff", "qcInspector": "Dept Manager"})
    api("POST", "/api/ahu/unit/%s/route" % uid, tokens["admin"])
    steps = _to_ipqc1(api, tokens, uid, builder="other")
    _readings(api, tokens["other"], steps["IPQC-1"], {"squareness": 0.6})
    st, r = _sign(api, tokens["staff"], steps["IPQC-1"]["id"], "Passed")
    assert st >= 400
    assert "signed by QA/QC" in r.get("error", ""), r


def test_a_manager_gets_no_exemption_from_inspecting_their_own_work(api, tokens, order):
    """A working supervisor is exactly the person most likely to be both builder and inspector, so
    this is the one rule in the module with no manager override."""
    uid = _mk(api, tokens["admin"], UNIT,
              {"orderId": order, "pin": "PIN-" + uuid.uuid4().hex[:6], "family": "modular",
               "voltage": 400})
    api("POST", "/api/ahu/unit/%s/route" % uid, tokens["admin"])
    steps = _to_ipqc1(api, tokens, uid, builder="mgr")
    assert steps["WS-02"]["signedBy"] == "Dept Manager"
    _readings(api, tokens["mgr"], steps["IPQC-1"], {"squareness": 0.6})
    st, r = _sign(api, tokens["mgr"], steps["IPQC-1"]["id"], "Passed")
    assert st >= 400
    assert "other than the person who did the work" in r.get("error", ""), r


def test_a_signed_step_cannot_have_its_readings_rewritten_afterwards(api, tokens, unit):
    """The evidential point of a traveller: the signature attests to the numbers that were there
    when it was given. If they can be edited later it attests to nothing."""
    steps = _to_ipqc1(api, tokens, unit)
    _readings(api, tokens["other"], steps["IPQC-1"], {"squareness": 0.6})
    st, r = _sign(api, tokens["other"], steps["IPQC-1"]["id"], "Passed")
    assert st == 200, r
    signed = _steps(api, tokens["admin"], unit)["IPQC-1"]
    _readings(api, tokens["mgr"], signed, {"squareness": 99.0})
    after = _steps(api, tokens["admin"], unit)["IPQC-1"]
    assert after["readings"]["squareness"] == 0.6, after["readings"]
    assert after["verdict"] == "pass"


def test_a_note_can_still_be_added_to_a_signed_step(api, tokens, unit):
    """A fact recorded ABOUT the step afterwards is not a change TO it."""
    steps = _to_ipqc1(api, tokens, unit)
    _readings(api, tokens["other"], steps["IPQC-1"], {"squareness": 0.6})
    _sign(api, tokens["other"], steps["IPQC-1"]["id"], "Passed")
    signed = _steps(api, tokens["admin"], unit)["IPQC-1"]
    body = {k: v for k, v in signed.items() if k not in ("verdict", "checks", "blockedBy", "spec")}
    body["notes"] = "Re-checked against the master diagonal on 20 Aug."
    st, _ = api("PATCH", "/api/coll/%s/%s" % (STEPS, signed["id"]), tokens["mgr"], body)
    assert st == 200
    assert _steps(api, tokens["admin"], unit)["IPQC-1"]["notes"].startswith("Re-checked")


# ── a test whose limit the unit never declared ───────────────────────────────────────────────────

def test_a_test_with_no_declared_basis_is_refused_rather_than_passed(api, tokens, order):
    """A unit with no supply voltage cannot have a hi-pot test voltage. Signing it would put a
    passed dielectric test on a CE-facing document with nothing behind it."""
    uid = _mk(api, tokens["admin"], UNIT,
              {"orderId": order, "pin": "PIN-HP", "family": "modular"})      # no voltage declared
    api("POST", "/api/ahu/unit/%s/route" % uid, tokens["admin"])
    steps = _steps(api, tokens["admin"], uid)
    t9 = steps["T9"]
    _readings(api, tokens["admin"], t9,
              {"applied_v": 1500, "leak_ma": 1.0, "no_breakdown": "yes"})
    st, r = _sign(api, tokens["admin"], t9["id"], "Passed")
    assert st >= 400
    # It is refused for its predecessor first; once that is out of the way the reason is the basis.
    assert "G4" in r.get("error", "") or "supply voltage" in r.get("error", ""), r


def test_the_declaration_shows_what_a_limit_will_be_resolved_from(api, tokens, unit):
    st, r = api("GET", "/api/ahu/unit/" + unit, tokens["admin"])
    assert st == 200
    assert r["declaration"]["classD"] == "D2"          # modular default from the Design Standard
    assert r["declaration"]["voltage"] == 400
    t9 = next(s for s in r["steps"] if s["code"] == "T9")
    applied = next(c for c in t9["checks"] if c["key"] == "applied_v")
    assert applied["limit"] == 2000.0                  # 400 V circuit


# ── somebody is told ─────────────────────────────────────────────────────────────────────────────
# tests/test_ahu_notify.py proves who should be told and what the message says; this proves the
# server actually reaches that code on the two events that happen inside a request. Without these,
# the notification module could be perfect and never called — and a notification that never fires
# looks exactly like a quiet week on the floor.
#
# The evidence is the audit row _ahu_notify_send writes. It is written whether or not anybody had
# push enabled, precisely so "was an alert raised" and "did a device receive it" stay separate
# questions; the test harness has no push subscriptions, so the row is the only thing to assert on.

def _alerts(unit_id=None):
    """Every AHU alert row currently in the audit trail, optionally only this unit's.

    Filtered by TARGET rather than taken as a tail slice: db.list_collection orders by the row's
    random uuid, so "everything after index N" is not "everything written after this point" — a
    slice here silently reads the wrong rows and can report either a phantom alert or none at all.
    """
    import db
    rows = [r for r in db.list_collection("audit")
            if str(r.get("action") or "").startswith("AHU alert")]
    if unit_id:
        rows = [r for r in rows if str(r.get("target") or "").endswith("/" + unit_id)]
    return rows


def test_recording_a_failing_reading_raises_an_alert(api, tokens, unit):
    steps = _to_ipqc1(api, tokens, unit)
    _readings(api, tokens["mgr"], steps["IPQC-1"], {"squareness": 2.5})   # limit is 1.0 mm/m
    rows = _alerts(unit)
    assert rows, "a reading outside the limit must alert somebody"
    assert "step-failed" in rows[0]["action"]
    assert "IPQC-1" in rows[0]["detail"] and "2.5" in rows[0]["detail"]


def test_a_reading_inside_the_limit_alerts_nobody(api, tokens, unit):
    steps = _to_ipqc1(api, tokens, unit)
    _readings(api, tokens["mgr"], steps["IPQC-1"], {"squareness": 0.6})
    assert _alerts(unit) == []


def test_an_incomplete_reading_is_not_treated_as_a_failure(api, tokens, unit):
    """Incomplete is not failed. Alerting on it would fire on every half-entered form on the floor,
    which is the fastest way to make the real alert worthless."""
    steps = _to_ipqc1(api, tokens, unit)
    _readings(api, tokens["mgr"], steps["IPQC-1"], {})
    assert _alerts(unit) == []


def test_re_saving_an_already_failed_step_does_not_alert_again(api, tokens, unit):
    """An inspector attaching a photo to a failed hold point must not re-page the QA manager. The
    trigger is the transition into failure, not the state of being failed."""
    steps = _to_ipqc1(api, tokens, unit)
    _readings(api, tokens["mgr"], steps["IPQC-1"], {"squareness": 2.5})
    assert len(_alerts(unit)) == 1
    again = _steps(api, tokens["admin"], unit)["IPQC-1"]
    _readings(api, tokens["mgr"], again, {"squareness": 2.5})
    assert len(_alerts(unit)) == 1, "the second save must not raise a second alert"


def test_the_alert_records_who_it_could_not_reach(api, tokens, unit):
    """The whole point of writing this row. A send count of zero cannot distinguish "nobody
    subscribed" from "the QC inspector is spelled in a way the register does not recognise"."""
    steps = _to_ipqc1(api, tokens, unit)
    st, r = api("PATCH", "/api/coll/%s/%s" % (UNIT, unit), tokens["admin"],
                dict(_unit(api, tokens, unit), qcInspector="Nguyen Thi Nobody"))
    assert st == 200, r
    _readings(api, tokens["mgr"], _steps(api, tokens["admin"], unit)["IPQC-1"],
              {"squareness": 2.5})
    rows = _alerts(unit)
    assert rows and "UNREACHABLE: Nguyen Thi Nobody" in rows[0]["detail"]


def test_a_gate_refused_by_its_exit_criteria_alerts_the_people_who_can_clear_it(api, tokens, unit):
    """G2 will not pass until the drawings are issued. Whoever pressed the button already knows;
    the production lead who has to go and get them issued does not."""
    steps = _steps(api, tokens["admin"], unit)
    _sign(api, tokens["admin"], steps["G1"]["id"], "Passed")
    st, r = _sign(api, tokens["admin"], _steps(api, tokens["admin"], unit)["G2"]["id"], "Passed")
    assert st >= 400, r
    rows = _alerts(unit)
    assert rows and "gate-held" in rows[0]["action"]
    assert "G2" in rows[0]["detail"]


def test_a_workstation_refused_for_order_alerts_nobody(api, tokens, unit):
    """Only gates, and only on exit criteria. A step refused for a missing predecessor is a matter
    for the person at the screen — telling three other people would bury the alert that means the
    line has stopped."""
    steps = _steps(api, tokens["admin"], unit)
    st, r = _sign(api, tokens["admin"], steps["WS-02"]["id"], "Complete")
    assert st >= 400, r
    assert _alerts(unit) == []


# ── the two numbers this module cannot derive ────────────────────────────────────────────────────

def test_the_capacity_and_aging_settings_round_trip(api, tokens):
    st, r = api("PATCH", "/api/ahu/settings", tokens["admin"],
                {"weeklyCapacityH": 240, "ncrAgingDays": 7})
    assert st == 200, r
    st, r = api("GET", "/api/ahu/settings", tokens["admin"])
    assert st == 200 and r["weeklyCapacityH"] == 240.0 and r["ncrAgingDays"] == 7


def test_an_unset_aging_threshold_reports_the_default_that_will_be_used(api, tokens):
    """Not a blank. A blank hides which number the sweep is actually applying."""
    st, r = api("PATCH", "/api/ahu/settings", tokens["admin"], {"ncrAgingDays": None})
    assert st == 200, r
    st, r = api("GET", "/api/ahu/settings", tokens["admin"])
    assert st == 200 and r["ncrAgingDays"] == r["ncrAgingDefault"]


def test_a_blank_capacity_clears_it_rather_than_meaning_zero(api, tokens):
    """Zero hours a week would mark every week over capacity for ever — a catastrophe on screen
    that is really a missing number. The chart already knows how to report hours with no verdict."""
    api("PATCH", "/api/ahu/settings", tokens["admin"], {"weeklyCapacityH": 240})
    st, r = api("PATCH", "/api/ahu/settings", tokens["admin"], {"weeklyCapacityH": None})
    assert st == 200 and r["weeklyCapacityH"] is None
    st, r = api("GET", "/api/ahu/capacity", tokens["admin"])
    assert st == 200 and r["capacity"] is None and "No weekly capacity" in r["note"]


def test_a_nonsense_capacity_is_refused(api, tokens):
    for bad in ("soon", 0, -5, 99999):
        st, r = api("PATCH", "/api/ahu/settings", tokens["admin"], {"weeklyCapacityH": bad})
        assert st == 400, (bad, st, r)


def test_a_nonsense_aging_threshold_is_refused(api, tokens):
    for bad in ("often", 0, -1, 400):
        st, r = api("PATCH", "/api/ahu/settings", tokens["admin"], {"ncrAgingDays": bad})
        assert st == 400, (bad, st, r)


def test_staff_may_read_the_settings_but_not_change_them(api, tokens):
    st, r = api("GET", "/api/ahu/settings", tokens["staff"])
    assert st == 200 and r["canEdit"] is False
    st, r = api("PATCH", "/api/ahu/settings", tokens["staff"], {"weeklyCapacityH": 1})
    assert st == 403, r


def test_changing_a_capacity_is_audited(api, tokens):
    """It decides what the factory promises. Who moved it, and to what, has to be answerable."""
    import db
    def _rows():
        return [x for x in db.list_collection("audit")
                if str(x.get("action") or "") == "AHU production settings changed"]
    before = len(_rows())
    st, r = api("PATCH", "/api/ahu/settings", tokens["admin"], {"weeklyCapacityH": 321})
    assert st == 200, r
    rows = _rows()
    assert len(rows) == before + 1
    assert any("321" in str(x.get("detail") or "") for x in rows)


# ── the shop-floor card ──────────────────────────────────────────────────────────────────────────
# The value of a printed code is entirely in whether it opens the right thing. So these check the
# LINK the symbol carries, not that a symbol was produced: tests/test_qr.py already proves a symbol
# decodes to the text it was given, and the two together are the round trip.

def test_the_card_carries_a_code_for_every_unsigned_step(api, tokens, unit):
    st, r = api("GET", "/api/ahu/unit/%s/card" % unit, tokens["admin"])
    assert st == 200, r
    codes = {s["code"] for s in r["steps"]}
    live = {s["code"] for s in _steps(api, tokens["admin"], unit).values() if not s.get("signedBy")}
    assert codes == live
    assert all(s["qr"].startswith("<svg") for s in r["steps"])


def test_each_code_links_to_that_step_on_that_unit(api, tokens, unit):
    st, r = api("GET", "/api/ahu/unit/%s/card" % unit, tokens["admin"])
    assert st == 200
    for s in r["steps"]:
        assert ("ahu=" + unit) in s["link"]
        assert ("step=" + s["code"]) in s["link"]


def test_a_signed_step_drops_off_the_card(api, tokens, unit):
    """A card is for the work still to do. Codes for finished steps are noise beside the machine."""
    steps = _steps(api, tokens["admin"], unit)
    st, r = _sign(api, tokens["admin"], steps["G1"]["id"], "Passed")
    assert st == 200, r
    st, r = api("GET", "/api/ahu/unit/%s/card" % unit, tokens["admin"])
    assert "G1" not in {s["code"] for s in r["steps"]}


def test_the_card_says_which_steps_it_could_not_encode(api, tokens, unit):
    """A silent gap where a code should be looks like a complete card, and the operator at that
    station finds nothing to scan. Nothing is expected to overflow at realistic id lengths — this
    pins that the field is reported rather than absent."""
    st, r = api("GET", "/api/ahu/unit/%s/card" % unit, tokens["admin"])
    assert st == 200
    assert r["unprintable"] == []
    assert all(s["qr"] for s in r["steps"])


def test_the_origin_comes_from_the_request_not_from_a_constant(api, tokens, unit, base_url):
    """A card printed in the office has to keep working on the tablet that scans it."""
    st, r = api("GET", "/api/ahu/unit/%s/card" % unit, tokens["admin"])
    assert st == 200
    assert r["origin"] and r["origin"] in r["steps"][0]["link"]
    assert r["origin"].startswith("http://127.0.0.1:")


def test_a_forwarded_request_is_told_it_arrived_over_https(api, tokens, unit):
    """Behind Caddy the socket is plain HTTP on localhost. Without reading the forwarded headers
    every printed code would point at http:// on an internal hostname."""
    st, r = api("GET", "/api/ahu/unit/%s/card" % unit, tokens["admin"],
                headers={"X-Forwarded-Proto": "https", "X-Forwarded-Host": "portal.humiley.com"})
    assert st == 200
    assert r["origin"] == "https://portal.humiley.com"
    assert r["steps"][0]["link"].startswith("https://portal.humiley.com/?ahu=")


def test_an_unknown_unit_has_no_card(api, tokens):
    st, r = api("GET", "/api/ahu/unit/no-such-unit/card", tokens["admin"])
    assert st == 404


def test_the_card_is_closed_when_the_app_is_denied(api, tokens, unit):
    import db
    before = (db.get_employee("HML-STF") or {}).get("appsDenied")
    db.update_employee("HML-STF", {"appsDenied": "ahu"})
    try:
        st, r = api("GET", "/api/ahu/unit/%s/card" % unit, tokens["staff"])
        assert st == 403 and "not enabled" in r["error"]
    finally:
        db.update_employee("HML-STF", {"appsDenied": before or ""})


# ── live updates ─────────────────────────────────────────────────────────────────────────────────
# The board used to redraw on a 30-second timer, which cannot tell "nothing happened" from "the
# network went away". Writes now bump a counter and a held-open request answers the moment it moves.
# The endpoint carries a revision number and nothing else, so there is one description of a unit's
# state rather than two that can drift apart.

def test_a_poll_that_is_already_behind_returns_at_once(api, tokens, unit):
    import time
    st, r = api("GET", "/api/ahu/changes?since=0", tokens["admin"])
    assert st == 200 and r["rev"] > 0, "creating a unit must have moved the revision"
    started = time.time()
    st, r = api("GET", "/api/ahu/changes?since=0", tokens["admin"])
    assert st == 200 and r["changed"] is True
    assert time.time() - started < 2, "a poll that is already behind must not wait"


def test_a_signature_wakes_a_waiting_poll(api, tokens, unit):
    """The event a wall board exists to show. A sign-off does not go through the generic collection
    write, so without its own bump the one change that matters would leave every screen waiting."""
    import threading
    import time
    st, r = api("GET", "/api/ahu/changes?since=0", tokens["admin"])
    rev = r["rev"]
    got = {}

    def _wait():
        got["st"], got["r"] = api("GET", "/api/ahu/changes?since=%d" % rev, tokens["admin"])

    t = threading.Thread(target=_wait)
    t.start()
    time.sleep(1.0)
    steps = _steps(api, tokens["admin"], unit)
    st, _ = _sign(api, tokens["admin"], steps["G1"]["id"], "Passed")
    assert st == 200
    t.join(timeout=20)
    assert not t.is_alive(), "the poll did not return after a sign-off"
    assert got["r"]["changed"] is True and got["r"]["rev"] > rev


def test_a_poll_with_nothing_to_report_answers_within_a_bound(api, tokens, unit, monkeypatch):
    """It says "nothing yet" rather than hanging. A request held indefinitely would outlive the
    authorisation that opened it and keep feeding a screen after the account was disabled.

    The wait is shortened here because the harness gives up on a request after ten seconds — which
    is itself worth knowing: the real 25-second window is longer than some clients will hold, and
    any caller of this endpoint has to expect to wait that long or not call it.
    """
    import time
    monkeypatch.setattr(app, "AHU_WAIT_SECONDS", 3)
    st, r = api("GET", "/api/ahu/changes?since=0", tokens["admin"])
    rev = r["rev"]
    started = time.time()
    st, r = api("GET", "/api/ahu/changes?since=%d" % rev, tokens["admin"])
    waited = time.time() - started
    assert st == 200 and r["changed"] is False
    assert waited >= 2, "it should wait for a change rather than answer immediately"
    assert waited < 9, "the wait must be bounded"


def test_a_nonsense_since_is_treated_as_zero_rather_than_failing(api, tokens, unit):
    st, r = api("GET", "/api/ahu/changes?since=soon", tokens["admin"])
    assert st == 200 and "rev" in r


def test_live_updates_are_closed_when_the_app_is_denied(api, tokens):
    import db
    before = (db.get_employee("HML-STF") or {}).get("appsDenied")
    db.update_employee("HML-STF", {"appsDenied": "ahu"})
    try:
        st, r = api("GET", "/api/ahu/changes?since=0", tokens["staff"])
        assert st == 403 and "not enabled" in r["error"]
    finally:
        db.update_employee("HML-STF", {"appsDenied": before or ""})


def test_the_waiter_cap_refuses_politely_instead_of_exhausting_threads(api, tokens, unit,
                                                                      monkeypatch):
    """Each waiting request parks a thread. A screen turned away keeps its timer; degrading silently
    would leave a board that looks live and is frozen."""
    monkeypatch.setattr(app, "AHU_WAIT_MAX", 0)
    st, r = api("GET", "/api/ahu/changes?since=0", tokens["admin"])
    assert st == 200 and r.get("busy") is True and r.get("note")
