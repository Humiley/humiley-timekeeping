"""Design risk and safety in design — what the design did, and who was told what it could not fix.

A designer's duty runs in an order: eliminate the hazard, then reduce it, then control it, and only
then inform the people who will inherit what is left. The register is worth having only if it
records which of those actually happened.

Two rules carry it.

"Controlled" with an empty action column is an opinion, not a control. That register is the one
produced after an accident, and it proves nothing.

And a residual risk passed to a contractor or an operator who was never told stays ours. If the
design could not remove it, the duty that remains is to inform — so a drawing about to be built
from will not issue while it carries an uninformed residual risk.
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
        "name": "Risk commission", "code": "RSK26", "client": "A Client",
        "designManager": "Dept Manager", "leadEngineer": "Staff One",
        "status": "Active", "currentStage": "Detail", "members": "Staff One"})


@pytest.fixture
def deliverable(api, tokens, commission):
    return _mk(api, tokens["staff"], "eng_deliverables", {
        "projectId": commission["id"], "title": "Plant room layout", "docNo": "RSK26-ME-DWG-001",
        "docType": "Drawing", "discipline": "Mechanical", "stage": "Detail",
        "preparedBy": "Alice Engineer", "approver": "Staff One"})


def _risk(api, tokens, commission, deliverable, **kw):
    body = {"projectId": commission["id"], "deliverableId": deliverable["id"], "ref": "RSK-001",
            "hazard": "AHU filter change at 4.2 m with no permanent access",
            "phase": "Maintenance", "likelihood": 3, "severity": 4, "status": "Open"}
    body.update(kw)
    return _mk(api, tokens["staff"], "eng_risks", body)


def test_controlled_needs_to_say_what_the_design_did(api, tokens, commission, deliverable):
    r = _risk(api, tokens, commission, deliverable)
    st, b = _sign(api, tokens["staff"], "eng_risks", r["id"], "Controlled")
    assert st != 200, "a risk was signed off as controlled with an empty action"
    assert "action" in str(b).lower() or "opinion" in str(b).lower()


def test_controlled_lands_when_the_design_actually_did_something(api, tokens, commission, deliverable):
    r = _risk(api, tokens, commission, deliverable,
              action="Filter bank relocated to the walkway side; access from the maintenance "
                     "gantry, no ladder required")
    st, b = _sign(api, tokens["staff"], "eng_risks", r["id"], "Controlled")
    assert st == 200, b
    assert b["item"]["signedOffBy"] == "Staff One"
    assert b["item"]["signedOffOn"]


def test_a_transferred_risk_needs_a_record_of_who_was_told(api, tokens, commission, deliverable):
    r = _risk(api, tokens, commission, deliverable,
              action="Cannot be designed out — plant is on the roof by client instruction")
    st, b = _sign(api, tokens["staff"], "eng_risks", r["id"], "Transferred")
    assert st != 200, "a residual risk was transferred with nobody informed"
    assert "told" in str(b).lower() or "inform" in str(b).lower()


def test_a_transferred_risk_lands_once_the_telling_is_recorded(api, tokens, commission, deliverable):
    r = _risk(api, tokens, commission, deliverable,
              action="Cannot be designed out — plant is on the roof by client instruction",
              informedBy="Drawing note 4 + residual risk schedule RRS-02 issued with TRN-014")
    st, b = _sign(api, tokens["staff"], "eng_risks", r["id"], "Transferred")
    assert st == 200, b


def test_an_uninformed_residual_risk_blocks_the_construction_issue(api, tokens, commission, deliverable):
    _risk(api, tokens, commission, deliverable, ref="RSK-009", status="Transferred",
          action="Cannot be designed out", informedBy="")
    rev = _mk(api, tokens["staff"], "eng_revisions", {
        "projectId": commission["id"], "deliverableId": deliverable["id"], "rev": "C01",
        "issueStatus": "IFC", "reasonForIssue": "for construction",
        "preparedBy": "Alice Engineer", "checkedBy": "Carol Checker", "status": "Draft"})
    st, b = _sign(api, tokens["staff"], "eng_revisions", rev["id"], "Issued")
    assert st != 200, "a drawing carrying an uninformed residual risk was issued for construction"
    assert "RSK-009" in str(b), "the refusal should name the risk"


def test_the_issue_proceeds_once_they_have_been_told(api, tokens, commission, deliverable):
    _risk(api, tokens, commission, deliverable, ref="RSK-010", status="Transferred",
          action="Cannot be designed out",
          informedBy="Drawing note 4; residual risk schedule issued with the IFC transmittal")
    rev = _mk(api, tokens["staff"], "eng_revisions", {
        "projectId": commission["id"], "deliverableId": deliverable["id"], "rev": "C01",
        "issueStatus": "IFC", "reasonForIssue": "for construction",
        "preparedBy": "Alice Engineer", "checkedBy": "Carol Checker", "status": "Draft"})
    st, b = _sign(api, tokens["staff"], "eng_revisions", rev["id"], "Issued")
    assert st == 200, b


def test_an_open_risk_does_not_block_anything(api, tokens, commission, deliverable):
    """Only a risk being PASSED ON needs the telling. An open one is still being worked."""
    _risk(api, tokens, commission, deliverable, ref="RSK-011", status="Open")
    rev = _mk(api, tokens["staff"], "eng_revisions", {
        "projectId": commission["id"], "deliverableId": deliverable["id"], "rev": "C01",
        "issueStatus": "IFC", "reasonForIssue": "for construction",
        "preparedBy": "Alice Engineer", "checkedBy": "Carol Checker", "status": "Draft"})
    st, b = _sign(api, tokens["staff"], "eng_revisions", rev["id"], "Issued")
    assert st == 200, b


def test_a_post_cannot_forge_the_sign_off(api, tokens, commission, deliverable):
    r = _risk(api, tokens, commission, deliverable,
              signedOffBy="Nobody At All", signedOffOn="2020-01-01")
    assert not r.get("signedOffBy"), "a browser must not be able to name who signed off a risk"
