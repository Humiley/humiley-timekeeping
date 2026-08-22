"""How long the client took, recorded while it is happening.

A design programme slips because approvals arrive late far more often than because drawings do, and
the evidence for that is contemporaneous or it is nothing. A year later it is an inbox archaeology
exercise; at the time it is one line.

So the register refuses two things. A transmittal marked Responded with no date cannot say how long
it took. And one closed over a response that never came deletes the single fact an extension-of-time
claim rests on — that we asked, on a date, and waited.

Chases are e-signed for the same reason: "we chased them three times" is worth what its record is
worth.
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
        "name": "Response clock commission", "code": "RSP26", "client": "A Client",
        "designManager": "Dept Manager", "leadEngineer": "Staff One",
        "status": "Active", "currentStage": "Detail", "members": "Staff One"})


def _trn(api, tokens, commission, **kw):
    body = {"projectId": commission["id"], "trnNo": "RSP26-TRN-001",
            "subject": "IFA package for approval", "toOrg": "A Client",
            "issueDate": "2026-07-01", "responseRequired": "Yes — approval",
            "responseDue": "2026-07-15", "status": "Issued"}
    body.update(kw)
    return _mk(api, tokens["staff"], "eng_transmittals", body)


def test_responded_without_a_date_is_refused(api, tokens, commission):
    t = _trn(api, tokens, commission)
    st, b = _sign(api, tokens["staff"], "eng_transmittals", t["id"], "Responded")
    assert st != 200, "marked Responded with no date"
    assert "date" in str(b).lower()


def test_responded_with_a_date_lands(api, tokens, commission):
    t = _trn(api, tokens, commission, responseDate="2026-08-04")
    st, b = _sign(api, tokens["staff"], "eng_transmittals", t["id"], "Responded")
    assert st == 200, b


def test_closing_over_a_missing_response_is_refused(api, tokens, commission):
    """The one that matters: silence must not be closed away."""
    t = _trn(api, tokens, commission)
    st, b = _sign(api, tokens["staff"], "eng_transmittals", t["id"], "Closed")
    assert st != 200, "closed over a response that never came, with nothing recorded"
    assert "never came" in str(b).lower() or "what happened" in str(b).lower()


def test_closing_is_allowed_once_somebody_says_what_happened(api, tokens, commission):
    t = _trn(api, tokens, commission,
             closureNote="Superseded by the C01 issue on 2026-08-10; approval no longer needed")
    st, b = _sign(api, tokens["staff"], "eng_transmittals", t["id"], "Closed")
    assert st == 200, b


def test_closing_is_allowed_when_the_response_did_arrive(api, tokens, commission):
    t = _trn(api, tokens, commission, responseDate="2026-08-04")
    st, b = _sign(api, tokens["staff"], "eng_transmittals", t["id"], "Closed")
    assert st == 200, b


def test_a_transmittal_that_asked_for_nothing_closes_freely(api, tokens, commission):
    """Most transmittals are for information. Do not make those a fight."""
    t = _trn(api, tokens, commission, responseRequired="No", responseDue="")
    st, b = _sign(api, tokens["staff"], "eng_transmittals", t["id"], "Closed")
    assert st == 200, b


def test_a_chase_is_signed_and_the_server_names_the_chaser(api, tokens, commission):
    t = _trn(api, tokens, commission)
    c = _mk(api, tokens["staff"], "eng_chases", {
        "projectId": commission["id"], "transmittalId": t["id"], "method": "Email",
        "to": "Client PM", "note": "Second reminder, approval now 3 weeks late"})
    st, b = _sign(api, tokens["staff"], "eng_chases", c["id"], "Sent")
    assert st == 200, b
    assert b["item"]["chasedBy"] == "Staff One"
    assert b["item"]["chasedOn"]


def test_a_post_cannot_forge_a_chase(api, tokens, commission):
    t = _trn(api, tokens, commission)
    c = _mk(api, tokens["staff"], "eng_chases", {
        "projectId": commission["id"], "transmittalId": t["id"],
        "chasedBy": "Somebody Who Never Chased", "chasedOn": "2020-01-01"})
    assert not c.get("chasedBy"), "a browser must not be able to claim a chase happened"


def test_issuing_a_transmittal_still_works(api, tokens, commission):
    """The new rules sit in front of the existing issue path — do not break it."""
    t = _trn(api, tokens, commission, status="Draft")
    st, b = _sign(api, tokens["staff"], "eng_transmittals", t["id"], "Issued")
    assert st == 200, b
    assert b["item"]["issuedBy"] == "Staff One"
