"""A gate that says everything is done while the register says otherwise.

Gate criteria were sentences somebody ticked. Every register added since can answer some of them as
fact — open holds, departures nobody agreed, residual risks passed on with nobody told — and a
clean PASS asserts those facts are true.

So an unqualified pass is refused while the registers contradict it, and "Passed with actions" is
left open, because that status exists precisely for a gate that goes through carrying known work.
Refusing the gate outright would be worked around by not recording the gate, which is worse than a
gate with actions against it.
"""
import pytest

import app


@pytest.fixture(autouse=True)
def _demo_esign(monkeypatch):
    monkeypatch.setattr(app, "DEMO_MODE", True)


def _mk(api, token, coll, body):
    st, b = api("POST", "/api/coll/" + coll, token, body)
    assert st == 200, b
    return b["item"]


def _sign(api, token, coll, iid, status, meaning="test"):
    return api("POST", "/api/esign", token,
               {"coll": coll, "id": iid, "meaning": meaning, "setStatus": status})


@pytest.fixture
def commission(api, tokens):
    return _mk(api, tokens["admin"], "eng_projects", {
        "name": "Gate commission", "code": "GTE26", "client": "A Client",
        "designManager": "Dept Manager", "leadEngineer": "Staff One",
        "status": "Active", "currentStage": "Detail", "members": "Staff One"})


def _gate(api, tokens, commission):
    return _mk(api, tokens["staff"], "eng_stages", {
        "projectId": commission["id"], "stage": "Detail", "status": "At gate"})


def test_a_clean_commission_passes_its_gate(api, tokens, commission):
    g = _gate(api, tokens, commission)
    st, b = _sign(api, tokens["staff"], "eng_stages", g["id"], "Passed")
    assert st == 200, b
    assert b["item"]["gateSignedBy"] == "Staff One"
    assert b["item"]["gateDecision"] == "Passed"


def test_an_open_hold_stops_a_clean_pass(api, tokens, commission):
    _mk(api, tokens["staff"], "eng_holds", {
        "projectId": commission["id"], "kind": "hold", "ref": "H-021",
        "title": "Incoming supply unconfirmed", "status": "open"})
    g = _gate(api, tokens, commission)
    st, b = _sign(api, tokens["staff"], "eng_stages", g["id"], "Passed")
    assert st != 200, "gate passed clean over an open hold"
    assert "H-021" in str(b), "the refusal should name what is in the way"


def test_an_unagreed_departure_stops_a_clean_pass(api, tokens, commission):
    _mk(api, tokens["staff"], "eng_deviations", {
        "projectId": commission["id"], "ref": "DEV-021",
        "title": "Corridor width", "status": "Submitted"})
    g = _gate(api, tokens, commission)
    st, b = _sign(api, tokens["staff"], "eng_stages", g["id"], "Passed")
    assert st != 200
    assert "DEV-021" in str(b)


def test_an_uninformed_residual_risk_stops_a_clean_pass(api, tokens, commission):
    _mk(api, tokens["staff"], "eng_risks", {
        "projectId": commission["id"], "ref": "RSK-021", "hazard": "Roof plant access",
        "status": "Transferred", "action": "cannot be designed out", "informedBy": ""})
    g = _gate(api, tokens, commission)
    st, b = _sign(api, tokens["staff"], "eng_stages", g["id"], "Passed")
    assert st != 200
    assert "RSK-021" in str(b)


def test_passed_with_actions_is_always_available(api, tokens, commission):
    """The exit that keeps the gate honest. Without it people stop recording gates."""
    _mk(api, tokens["staff"], "eng_holds", {
        "projectId": commission["id"], "kind": "hold", "ref": "H-022",
        "title": "Still open", "status": "open"})
    g = _gate(api, tokens, commission)
    st, b = _sign(api, tokens["staff"], "eng_stages", g["id"], "Passed with actions")
    assert st == 200, b
    assert b["item"]["gateDecision"] == "Passed with actions"


def test_holding_or_failing_a_gate_is_never_blocked(api, tokens, commission):
    _mk(api, tokens["staff"], "eng_holds", {
        "projectId": commission["id"], "kind": "hold", "ref": "H-023", "status": "open"})
    g = _gate(api, tokens, commission)
    st, b = _sign(api, tokens["staff"], "eng_stages", g["id"], "Held")
    assert st == 200, b


def test_an_assumption_does_not_stop_a_gate(api, tokens, commission):
    """Assumptions are carried by design. Only holds stop things."""
    _mk(api, tokens["staff"], "eng_holds", {
        "projectId": commission["id"], "kind": "assumption", "ref": "A-021",
        "title": "35 C ambient", "status": "open"})
    g = _gate(api, tokens, commission)
    st, b = _sign(api, tokens["staff"], "eng_stages", g["id"], "Passed")
    assert st == 200, b


def test_a_closed_hold_does_not_stop_a_gate(api, tokens, commission):
    _mk(api, tokens["staff"], "eng_holds", {
        "projectId": commission["id"], "kind": "hold", "ref": "H-024",
        "title": "Answered", "status": "closed"})
    g = _gate(api, tokens, commission)
    st, b = _sign(api, tokens["staff"], "eng_stages", g["id"], "Passed")
    assert st == 200, b


def test_another_commissions_holds_do_not_stop_this_gate(api, tokens, commission):
    """Scoping matters: registers are per commission and a blocker must be this one's."""
    other = _mk(api, tokens["admin"], "eng_projects", {
        "name": "Somebody else", "code": "OTH26", "designManager": "Dept Manager",
        "leadEngineer": "Staff One", "status": "Active", "members": "Staff One"})
    _mk(api, tokens["staff"], "eng_holds", {
        "projectId": other["id"], "kind": "hold", "ref": "H-999",
        "title": "Not ours", "status": "open"})
    g = _gate(api, tokens, commission)
    st, b = _sign(api, tokens["staff"], "eng_stages", g["id"], "Passed")
    assert st == 200, b
    assert "H-999" not in str(b)
