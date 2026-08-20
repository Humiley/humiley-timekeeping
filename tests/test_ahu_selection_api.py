"""Importing an AeroSelect selection onto a production unit, over the API.

tests/test_ahu_selection.py proves the document is read correctly. This proves the server does the
right things with it: stamps the unit, files the selection report gate G2 asks for, and — the one
that matters — refuses to quietly re-specify a unit that is already being built.
"""
import base64
import json
import uuid

import pytest

import app
import ahu_selection as S

SECRET = "shared-with-aeroselect-0123456789"


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
        "poNumber": "PO-" + uuid.uuid4().hex[:6], "customer": "Pharma Co",
        "contractReviewSigned": True, "scheduleBaselined": "Yes",
        "productionLead": "Staff One", "qcInspector": "Other Staff"})
    uid = _mk(api, tokens["admin"], "ahu_units", {
        "orderId": oid, "pin": "PIN-" + uuid.uuid4().hex[:6], "family": "modular",
        "productionLead": "Staff One", "qcInspector": "Other Staff"})
    api("POST", "/api/ahu/unit/%s/route" % uid, tokens["admin"])
    return uid


def payload(**over):
    p = {
        "project": {"number": "P-2026-014", "name": "Cleanroom Block B"},
        "unit": {"tag": "AHU-B-01", "model": "AeroSmart AS-24", "family": "hygienic",
                 "airflow_m3h": 12000, "esp_pa": 450, "voltage_v": 400,
                 "coilDesignBar": 16, "cleanroom": "ISO 7"},
        "classes": {"D": "D1", "L": "L1", "F": "F9", "T": "T1", "TB": "TB1"},
        "performance": {"erp": {"verdict": "PASS", "sfpIntWm3s": 810.0}, "euroventClass": "A+"},
        "sections": [{"type": "filter_hepa"}],
    }
    p.update(over)
    return p


def doc(secret=None, ref="AS-2026-0410", **over):
    p = payload(**over)
    env = {"document": "selection", "specVersion": S.SPEC_VERSION, "selectionRef": ref,
           "engine": "AeroSelect", "engineVersion": "2.0.0",
           "generatedOn": "2026-08-20T09:14:00Z", "contentHash": S.content_hash(p)}
    if secret:
        env["signature"] = S.sign(p, secret)
    return {"aeroselect": env, "payload": p}


def _import(api, token, uid, document, **extra):
    body = {"document": document}
    body.update(extra)
    return api("POST", "/api/ahu/unit/%s/selection" % uid, token, body)


def _unit(api, token, uid):
    st, r = api("GET", "/api/ahu/unit/" + uid, token)
    assert st == 200, r
    return r["unit"]


# ── the happy path ───────────────────────────────────────────────────────────────────────────────

def test_a_selection_stamps_the_unit_with_the_numbers_it_was_sold_on(api, tokens, unit):
    st, r = _import(api, tokens["admin"], unit, doc())
    assert st == 200, r
    u = _unit(api, tokens["admin"], unit)
    assert u["airflow"] == 12000 and u["esp"] == 450
    assert u["voltage"] == 400 and u["coilDesignBar"] == 16
    assert u["cleanroom"] == "ISO7" and u["family"] == "hygienic"
    assert u["selectionRef"] == "AS-2026-0410"
    assert u["model"] == "AeroSmart AS-24"


def test_the_import_files_the_selection_report_gate_g2_asks_for(api, tokens, unit):
    st, _ = api("GET", "/api/ahu/unit/" + unit, tokens["admin"])
    _import(api, tokens["admin"], unit, doc())
    st, r = api("GET", "/api/ahu/unit/" + unit, tokens["admin"])
    docs = [d for d in r["docs"] if d.get("kind") == "Selection report"]
    assert len(docs) == 1
    assert docs[0]["docNo"] == "AS-2026-0410"
    assert docs[0]["status"] == "Issued"


def test_g2_stops_complaining_about_a_missing_selection_once_one_is_imported(api, tokens, unit):
    st, r = api("GET", "/api/ahu/unit/" + unit, tokens["admin"])
    g2 = next(g for g in r["gates"] if g["code"] == "G2")
    assert any("selection report" in b for b in g2["blockers"])
    _import(api, tokens["admin"], unit, doc())
    st, r = api("GET", "/api/ahu/unit/" + unit, tokens["admin"])
    g2 = next(g for g in r["gates"] if g["code"] == "G2")
    assert not any("selection report" in b for b in g2["blockers"])


def test_the_declared_leakage_class_becomes_the_limit_test_t3_is_judged_against(api, tokens, unit):
    """The point of the whole integration: AeroSelect declares L1, and the factory proves it."""
    _import(api, tokens["admin"], unit, doc())
    st, r = api("GET", "/api/ahu/unit/" + unit, tokens["admin"])
    t3 = next(s for s in r["steps"] if s["code"] == "T3")
    leak = next(c for c in t3["checks"] if c["key"] == "leak_neg400")
    assert leak["limit"] == 0.15                       # EN 1886 L1 at -400 Pa
    assert "L1" in (leak["limitNote"] or "")


def test_the_response_names_the_classes_the_factory_still_has_to_prove(api, tokens, unit):
    st, r = _import(api, tokens["admin"], unit, doc())
    assert r["targetsToProve"] == {"L": "T3", "F": "T4"}


def test_importing_a_different_family_reports_the_route_as_stale(api, tokens, unit):
    """A modular unit re-specified as hygienic needs a different route — different tests apply."""
    st, r = _import(api, tokens["admin"], unit, doc())
    assert r["routeStale"] is True


# ── trust, reported honestly ─────────────────────────────────────────────────────────────────────

def test_with_no_shared_secret_the_import_says_it_is_unverified(api, tokens, unit):
    st, r = _import(api, tokens["admin"], unit, doc())
    assert st == 200
    assert r["verified"] is False and r["secretConfigured"] is False
    assert _unit(api, tokens["admin"], unit)["selectionVerified"] is False


def test_with_a_shared_secret_a_signed_document_verifies(api, tokens, unit, monkeypatch):
    monkeypatch.setenv(app.Handler.AHU_SELECTION_SECRET_ENV, SECRET)
    st, r = _import(api, tokens["admin"], unit, doc(secret=SECRET))
    assert st == 200, r
    assert r["verified"] is True and r["secretConfigured"] is True
    assert _unit(api, tokens["admin"], unit)["selectionVerified"] is True


def test_with_a_shared_secret_an_unsigned_document_is_refused(api, tokens, unit, monkeypatch):
    monkeypatch.setenv(app.Handler.AHU_SELECTION_SECRET_ENV, SECRET)
    st, r = _import(api, tokens["admin"], unit, doc())
    assert st == 400
    assert "unsigned" in r["error"]


def test_a_document_edited_after_export_is_refused(api, tokens, unit):
    d = doc()
    d["payload"]["unit"]["airflow_m3h"] = 99000
    st, r = _import(api, tokens["admin"], unit, d)
    assert st == 400
    assert "altered" in r["error"]
    assert not _unit(api, tokens["admin"], unit).get("airflow")


def test_a_file_upload_arrives_as_a_data_uri(api, tokens, unit):
    b64 = base64.b64encode(json.dumps(doc()).encode()).decode()
    st, r = _import(api, tokens["admin"], unit, "data:application/json;base64," + b64)
    assert st == 200, r
    assert _unit(api, tokens["admin"], unit)["airflow"] == 12000


def test_nothing_attached_says_what_to_attach(api, tokens, unit):
    st, r = _import(api, tokens["admin"], unit, "")
    assert st == 400 and "exported from AeroSelect" in r["error"]


# ── a family nobody can determine ────────────────────────────────────────────────────────────────

def test_a_selection_with_no_recognisable_family_is_refused_on_a_unit_that_has_none(
        api, tokens, order_less_unit):
    u = dict(payload()["unit"], family="something new")
    st, r = _import(api, tokens["admin"], order_less_unit, doc(unit=u))
    assert st == 400
    assert "which product family" in r["error"]


@pytest.fixture
def order_less_unit(api, tokens):
    """A unit with no family set, to corner the case where the document cannot supply one."""
    return _mk(api, tokens["admin"], "ahu_units",
               {"pin": "PIN-" + uuid.uuid4().hex[:6]})


def test_a_selection_with_no_recognisable_family_is_allowed_when_the_unit_already_has_one(
        api, tokens, unit):
    u = dict(payload()["unit"], family="something new")
    st, r = _import(api, tokens["admin"], unit, doc(unit=u))
    assert st == 200, r
    assert _unit(api, tokens["admin"], unit)["family"] == "modular"   # unchanged, not blanked


# ── re-importing onto a unit already being built ─────────────────────────────────────────────────

def _release_to_g2(api, tokens, uid):
    """Get a unit past G2 the way the factory would."""
    _import(api, tokens["admin"], uid, doc())
    _mk(api, tokens["admin"], "ahu_docs",
        {"unitId": uid, "kind": "GA drawing", "status": "Issued", "docNo": "GA-1"})
    _mk(api, tokens["admin"], "ahu_bom",
        {"unitId": uid, "partNo": "P1", "qty": 1, "kittedQty": 1, "receivedQty": 1,
         "iqcStatus": "Passed"})
    u = _unit(api, tokens["admin"], uid)
    st, r = api("PATCH", "/api/coll/ahu_units/" + uid, tokens["admin"],
                dict(u, bomStatus="Released"))
    assert st == 200, r
    st, r = api("GET", "/api/ahu/unit/" + uid, tokens["admin"])
    steps = {s["code"]: s for s in r["steps"]}
    for g in ("G1", "G2"):
        st, r = api("POST", "/api/esign", tokens["admin"],
                    {"coll": "ahu_steps", "id": steps[g]["id"], "meaning": "Gate " + g,
                     "setStatus": "Passed"})
        assert st == 200, (g, r)


def test_reimporting_the_same_selection_after_release_is_fine(api, tokens, unit):
    """Idempotent — re-importing what the unit was already built to changes nothing."""
    _release_to_g2(api, tokens, unit)
    st, r = _import(api, tokens["admin"], unit, doc())
    assert st == 200, r


def test_a_different_selection_after_release_is_refused_as_an_engineering_change(
        api, tokens, unit):
    """The design moved under a unit somebody is already building. That is an ECN decision."""
    _release_to_g2(api, tokens, unit)
    u = dict(payload()["unit"], airflow_m3h=14000)
    st, r = _import(api, tokens["admin"], unit, doc(unit=u, ref="AS-2026-0411"))
    assert st == 409
    assert "engineering change" in r["error"]
    assert "airflow" in r["error"]
    assert _unit(api, tokens["admin"], unit)["airflow"] == 12000     # untouched


def test_a_superseding_import_is_allowed_when_the_decision_is_recorded(api, tokens, unit):
    _release_to_g2(api, tokens, unit)
    u = dict(payload()["unit"], airflow_m3h=14000)
    st, r = _import(api, tokens["admin"], unit, doc(unit=u, ref="AS-2026-0411"),
                    supersede=True)
    assert st == 200, r
    assert _unit(api, tokens["admin"], unit)["airflow"] == 14000


def test_superseding_a_released_unit_is_not_a_staff_decision(api, tokens, unit):
    _release_to_g2(api, tokens, unit)
    u = dict(payload()["unit"], airflow_m3h=14000)
    st, r = _import(api, tokens["staff"], unit, doc(unit=u, ref="AS-2026-0411"),
                    supersede=True)
    assert st == 403


def test_before_release_a_different_selection_simply_applies(api, tokens, unit):
    """Nothing has been built yet, so re-selecting is ordinary engineering work."""
    _import(api, tokens["admin"], unit, doc())
    u = dict(payload()["unit"], airflow_m3h=14000)
    st, r = _import(api, tokens["admin"], unit, doc(unit=u, ref="AS-2026-0411"))
    assert st == 200, r
    assert _unit(api, tokens["admin"], unit)["airflow"] == 14000


# ── authority ────────────────────────────────────────────────────────────────────────────────────

def test_somebody_with_no_part_in_the_unit_cannot_import_a_selection(api, tokens, unit):
    st, r = _import(api, tokens["other"], unit, doc())
    assert st == 403
    assert "engineering or production" in r["error"]


def test_the_named_production_lead_can_import(api, tokens, unit):
    st, r = _import(api, tokens["staff"], unit, doc())
    assert st == 200, r
