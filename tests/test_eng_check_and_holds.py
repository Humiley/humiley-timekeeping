"""The design controls that were claimed but not enforced.

`checkedBy` was a stamped field and nothing more: a drawing could reach IFC with it blank, or
naming the person who drew it, provided one other name appeared as the approver. Checking and
approving are separate acts — the checker confirms the content, the approver authorises the
release — and ISO 9001 8.3.4 asks for the verification, not only the authorisation.

A HOLD is an open question the design is waiting on. Nothing stopped one leaving the office inside
an IFC document, which is the assumption-that-shipped: the classic way a consultancy inherits a
liability it never priced. An ASSUMPTION is different in kind — declared, listed and carried on the
face of the document — so it must NOT block, or engineers will stop recording them.

Every test here was written to fail on the code as it was.
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
        "name": "Check and hold commission", "code": "CHK26", "client": "A Client",
        "designManager": "Dept Manager", "leadEngineer": "Staff One",
        "status": "Active", "currentStage": "Detail", "members": "Staff One"})


def _deliv(api, tokens, commission, no, **kw):
    body = {"projectId": commission["id"], "title": "Drawing " + no, "docNo": no,
            "docType": "Drawing", "discipline": "Electrical", "stage": "Detail",
            "approver": "Staff One"}
    body.update(kw)
    return _mk(api, tokens["staff"], "eng_deliverables", body)


def _rev(api, tokens, commission, d, **kw):
    body = {"projectId": commission["id"], "deliverableId": d["id"], "rev": "C01",
            "issueStatus": "IFC", "reasonForIssue": "for construction",
            "preparedBy": "Alice Engineer", "status": "Draft"}
    body.update(kw)
    return _mk(api, tokens["staff"], "eng_revisions", body)


# ── the check has to exist, and has to be somebody else ─────────────────────────

def test_external_issue_refused_with_no_checker(api, tokens, commission):
    d = _deliv(api, tokens, commission, "CHK26-EL-DWG-001")
    rev = _rev(api, tokens, commission, d)
    st, b = _sign(api, tokens["staff"], "eng_revisions", rev["id"], "Issued")
    assert st != 200, "IFC was issued with no checker recorded"
    assert "check" in str(b).lower()


def test_the_preparer_cannot_be_the_checker(api, tokens, commission):
    d = _deliv(api, tokens, commission, "CHK26-EL-DWG-002")
    rev = _rev(api, tokens, commission, d,
               preparedBy="Alice Engineer", checkedBy="alice engineer")
    st, b = _sign(api, tokens["staff"], "eng_revisions", rev["id"], "Issued")
    assert st != 200, "the preparer was accepted as her own checker"
    assert "checker" in str(b).lower()


def test_a_properly_checked_document_issues(api, tokens, commission):
    d = _deliv(api, tokens, commission, "CHK26-EL-DWG-003")
    rev = _rev(api, tokens, commission, d, checkedBy="Carol Checker")
    st, b = _sign(api, tokens["staff"], "eng_revisions", rev["id"], "Issued")
    assert st == 200, b
    assert b["item"]["issuedBy"] == "Staff One"


def test_internal_review_copy_still_needs_no_checker(api, tokens, commission):
    """A one-engineer discipline must still be able to circulate a check print."""
    d = _deliv(api, tokens, commission, "CHK26-EL-DWG-004")
    rev = _rev(api, tokens, commission, d, rev="P01", issueStatus="IFR", preparedBy="Staff One")
    st, b = _sign(api, tokens["staff"], "eng_revisions", rev["id"], "Issued")
    assert st == 200, b


# ── a hold must not leave the office ────────────────────────────────────────────

def test_open_hold_blocks_issue_and_names_itself(api, tokens, commission):
    d = _deliv(api, tokens, commission, "CHK26-EL-DWG-005")
    _mk(api, tokens["staff"], "eng_holds", {
        "projectId": commission["id"], "deliverableId": d["id"], "kind": "hold",
        "ref": "H-014", "title": "Incoming supply capacity unconfirmed",
        "raisedBy": "Alice Engineer", "status": "open"})
    rev = _rev(api, tokens, commission, d, checkedBy="Carol Checker")
    st, b = _sign(api, tokens["staff"], "eng_revisions", rev["id"], "Issued")
    assert st != 200, "a document carrying an open HOLD was issued for construction"
    assert "hold" in str(b).lower()
    assert "H-014" in str(b), "the refusal should name the hold that is blocking"


def test_an_assumption_is_carried_not_blocked(api, tokens, commission):
    d = _deliv(api, tokens, commission, "CHK26-EL-DWG-006")
    _mk(api, tokens["staff"], "eng_holds", {
        "projectId": commission["id"], "deliverableId": d["id"], "kind": "assumption",
        "ref": "A-002", "title": "Ambient design condition taken as 35 C",
        "raisedBy": "Alice Engineer", "status": "open"})
    rev = _rev(api, tokens, commission, d, checkedBy="Carol Checker")
    st, b = _sign(api, tokens["staff"], "eng_revisions", rev["id"], "Issued")
    assert st == 200, b


def test_closing_the_hold_releases_the_document(api, tokens, commission):
    d = _deliv(api, tokens, commission, "CHK26-EL-DWG-007")
    h = _mk(api, tokens["staff"], "eng_holds", {
        "projectId": commission["id"], "deliverableId": d["id"], "kind": "hold",
        "ref": "H-015", "title": "Duct route through the fire wall",
        "raisedBy": "Alice Engineer", "status": "open"})
    h["status"] = "closed"
    st, _ = api("PATCH", "/api/coll/eng_holds/" + h["id"], tokens["staff"], h)
    assert st == 200
    rev = _rev(api, tokens, commission, d, checkedBy="Carol Checker")
    st, b = _sign(api, tokens["staff"], "eng_revisions", rev["id"], "Issued")
    assert st == 200, b


def test_the_raiser_does_not_close_their_own_hold(api, tokens, commission):
    d = _deliv(api, tokens, commission, "CHK26-EL-DWG-008")
    h = _mk(api, tokens["staff"], "eng_holds", {
        "projectId": commission["id"], "deliverableId": d["id"], "kind": "hold",
        "ref": "H-016", "title": "Client to confirm transformer rating",
        "raisedBy": "Staff One", "status": "open"})
    st, b = _sign(api, tokens["staff"], "eng_holds", h["id"], "Closed")
    assert st != 200, "the engineer who raised the hold closed it alone"


# ── the interdisciplinary check is a record, not a sentence ─────────────────────

def test_idc_cannot_be_signed_by_the_preparer(api, tokens, commission):
    d = _deliv(api, tokens, commission, "CHK26-EL-DWG-009", preparedBy="Staff One")
    entry = _mk(api, tokens["staff"], "eng_idc", {
        "projectId": commission["id"], "deliverableId": d["id"],
        "discipline": "Mechanical", "status": "Draft"})
    st, b = _sign(api, tokens["staff"], "eng_idc", entry["id"], "Clear")
    assert st != 200, "the preparer signed the interdisciplinary check on her own drawing"


def test_idc_by_another_discipline_is_accepted_and_stamped(api, tokens, commission):
    d = _deliv(api, tokens, commission, "CHK26-EL-DWG-010", preparedBy="Alice Engineer")
    entry = _mk(api, tokens["staff"], "eng_idc", {
        "projectId": commission["id"], "deliverableId": d["id"],
        "discipline": "Mechanical", "status": "Draft"})
    st, b = _sign(api, tokens["staff"], "eng_idc", entry["id"], "Clear")
    assert st == 200, b
    assert b["item"]["checkedBy"] == "Staff One", "the server stamps the signer"
    assert b["item"]["checkedOn"]


def test_an_idc_signature_cannot_be_forged_by_a_post(api, tokens, commission):
    d = _deliv(api, tokens, commission, "CHK26-EL-DWG-011")
    entry = _mk(api, tokens["admin"], "eng_idc", {
        "projectId": commission["id"], "deliverableId": d["id"], "discipline": "Civil",
        "status": "Clear", "checkedBy": "Someone Who Never Looked",
        "checkedOn": "2020-01-01", "signatures": [{"name": "Forged"}]})
    assert not entry.get("checkedBy"), "a browser must not be able to name the checker"
    assert not entry.get("signatures")


def test_the_mdr_hold_flag_now_blocks_too(api, tokens, commission):
    """The deliverable carried an `hold = Yes` flag that displayed a chip and blocked nothing.

    Two places to record the same fact, one of which silently offered no protection, is worse than
    either alone: whichever an engineer reaches for, they believe they are covered.
    """
    d = _deliv(api, tokens, commission, "CHK26-EL-DWG-012",
               hold="Yes", holdReason="Awaiting client decision on the riser route")
    rev = _rev(api, tokens, commission, d, checkedBy="Carol Checker")
    st, b = _sign(api, tokens["staff"], "eng_revisions", rev["id"], "Issued")
    assert st != 200, "a deliverable flagged On hold in the MDR was issued for construction"
    assert "hold" in str(b).lower()
    assert "riser route" in str(b), "the refusal should carry the reason already recorded"
