"""A departure from an adopted standard, agreed before it ships — or a non-compliance after it.

The codes register fixed which edition governs. This is the register for the times the design does
not follow it: a deviation asked for before the fact, or a concession recorded after, when what was
built does not match what was specified.

Two rules carry the weight.

A departure from something with the FORCE OF LAW is not ours to grant. Internal agreement records
that we find it acceptable; it cannot make a building lawful. Without the authority's or client's
written agreement on the record, a design office can self-certify its way past a building code —
which is exactly the paper trail an investigation looks for and does not find.

And an unagreed departure must not leave the office. A deviation nobody has accepted is a
non-compliance until somebody does; issuing the drawing externally publishes it as though it were
the design.
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
        "name": "Deviation commission", "code": "DEV26", "client": "A Client",
        "designManager": "Dept Manager", "leadEngineer": "Staff One",
        "status": "Active", "currentStage": "Detail", "members": "Staff One"})


@pytest.fixture
def deliverable(api, tokens, commission):
    return _mk(api, tokens["staff"], "eng_deliverables", {
        "projectId": commission["id"], "title": "Riser layout", "docNo": "DEV26-ME-DWG-001",
        "docType": "Drawing", "discipline": "Mechanical", "stage": "Detail",
        "preparedBy": "Alice Engineer", "approver": "Staff One"})


def _std(api, tokens, commission, obligation):
    return _mk(api, tokens["staff"], "eng_standards", {
        "projectId": commission["id"], "code": "QCVN 06", "title": "Fire safety",
        "issuer": "BXD (Bộ Xây dựng)", "edition": "2022", "obligation": obligation,
        "status": "Adopted"})


def _dev(api, tokens, commission, deliverable, **kw):
    body = {"projectId": commission["id"], "deliverableId": deliverable["id"],
            "ref": "DEV-001", "title": "Corridor width 1.4 m against 1.5 m required",
            "kind": "Deviation", "clause": "3.2.1", "requestedBy": "Alice Engineer",
            "justification": "Compensating measures: sprinklered throughout, travel distance halved",
            "status": "Submitted"}
    body.update(kw)
    return _mk(api, tokens["staff"], "eng_deviations", body)


def test_a_departure_is_agreed_by_somebody_other_than_the_asker(api, tokens, commission, deliverable):
    std = _std(api, tokens, commission, "Contractual")
    d = _dev(api, tokens, commission, deliverable, standardId=std["id"], requestedBy="Staff One")
    st, b = _sign(api, tokens["staff"], "eng_deviations", d["id"], "Approved")
    assert st != 200, "the engineer who asked for the deviation approved it"


def test_a_contractual_departure_can_be_agreed_in_the_office(api, tokens, commission, deliverable):
    std = _std(api, tokens, commission, "Contractual")
    d = _dev(api, tokens, commission, deliverable, standardId=std["id"])
    st, b = _sign(api, tokens["staff"], "eng_deviations", d["id"], "Approved")
    assert st == 200, b
    assert b["item"]["decidedBy"] == "Staff One"
    assert b["item"]["decision"] == "Approved"


def test_a_statutory_departure_cannot_be_self_certified(api, tokens, commission, deliverable):
    """The rule that matters. A design office cannot grant itself relief from a building code."""
    std = _std(api, tokens, commission, "Statutory")
    d = _dev(api, tokens, commission, deliverable, standardId=std["id"])
    st, b = _sign(api, tokens["staff"], "eng_deviations", d["id"], "Approved")
    assert st != 200, "a departure from a statutory code was approved inside the office"
    assert "statutory" in str(b).lower()
    assert "QCVN 06" in str(b), "the refusal should name the code"


def test_a_statutory_departure_lands_with_the_authority_on_the_record(api, tokens, commission, deliverable):
    std = _std(api, tokens, commission, "Statutory")
    d = _dev(api, tokens, commission, deliverable, standardId=std["id"],
             externalApprovalRef="Fire Police approval 1234/PCCC dated 2026-07-30")
    st, b = _sign(api, tokens["staff"], "eng_deviations", d["id"], "Approved")
    assert st == 200, b


def test_rejecting_a_statutory_departure_needs_no_external_paper(api, tokens, commission, deliverable):
    """Saying no is always ours to do."""
    std = _std(api, tokens, commission, "Statutory")
    d = _dev(api, tokens, commission, deliverable, standardId=std["id"])
    st, b = _sign(api, tokens["staff"], "eng_deviations", d["id"], "Rejected")
    assert st == 200, b


def test_an_unagreed_deviation_blocks_the_external_issue(api, tokens, commission, deliverable):
    std = _std(api, tokens, commission, "Contractual")
    _dev(api, tokens, commission, deliverable, standardId=std["id"], ref="DEV-007")
    rev = _mk(api, tokens["staff"], "eng_revisions", {
        "projectId": commission["id"], "deliverableId": deliverable["id"], "rev": "C01",
        "issueStatus": "IFC", "reasonForIssue": "for construction",
        "preparedBy": "Alice Engineer", "checkedBy": "Carol Checker", "status": "Draft"})
    st, b = _sign(api, tokens["staff"], "eng_revisions", rev["id"], "Issued")
    assert st != 200, "a drawing with an unagreed deviation was issued for construction"
    assert "DEV-007" in str(b), "the refusal should name the deviation"


def test_once_agreed_the_drawing_issues(api, tokens, commission, deliverable):
    std = _std(api, tokens, commission, "Contractual")
    d = _dev(api, tokens, commission, deliverable, standardId=std["id"])
    st, _ = _sign(api, tokens["staff"], "eng_deviations", d["id"], "Approved")
    assert st == 200
    rev = _mk(api, tokens["staff"], "eng_revisions", {
        "projectId": commission["id"], "deliverableId": deliverable["id"], "rev": "C01",
        "issueStatus": "IFC", "reasonForIssue": "for construction",
        "preparedBy": "Alice Engineer", "checkedBy": "Carol Checker", "status": "Draft"})
    st, b = _sign(api, tokens["staff"], "eng_revisions", rev["id"], "Issued")
    assert st == 200, b


def test_an_internal_issue_is_still_free(api, tokens, commission, deliverable):
    """The argument about a departure happens over check prints. Do not block those."""
    std = _std(api, tokens, commission, "Contractual")
    _dev(api, tokens, commission, deliverable, standardId=std["id"])
    rev = _mk(api, tokens["staff"], "eng_revisions", {
        "projectId": commission["id"], "deliverableId": deliverable["id"], "rev": "P01",
        "issueStatus": "IFR", "reasonForIssue": "review", "preparedBy": "Staff One",
        "status": "Draft"})
    st, b = _sign(api, tokens["staff"], "eng_revisions", rev["id"], "Issued")
    assert st == 200, b


def test_a_post_cannot_forge_the_decision(api, tokens, commission, deliverable):
    d = _dev(api, tokens, commission, deliverable, decision="Approved",
             decidedBy="Nobody At All", decidedOn="2020-01-01")
    assert not d.get("decidedBy"), "a browser must not be able to name who agreed a departure"
    assert not d.get("decision")
