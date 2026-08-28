"""Who is held competent to check what.

The register has recorded "checked by" since the module shipped and never once said whether that
person was held competent to check it. That is the question an auditor asks immediately after
"who checked this?" — and the one that undermines every signature already collected, because a
signature from somebody the office never said could check that discipline is a signature about
nothing.

Two rules, and one deliberate non-rule.

Competence is granted, never claimed: somebody else records what you may check, which is the whole
content of the word.

And it is the Design Manager or Lead Engineer who grants it — the same authority that decides a
gate, not a portal access level.

The non-rule matters as much. An issue checked by somebody with no competence record is NOT
refused. Competence records lag reality in a small office, and stopping real work over an
administrative gap is how a register earns the reputation that gets it ignored.

What the register DOES: when a checker is authorised, but not for the discipline of the drawing
they checked, the mismatch is noted in the refusal log. Noted, not refused — see above.

Every test here uses a DISTINCT person. The database is shared across tests in this file, so a
name authorised by an earlier test is still authorised in a later one; that is how the first
version of the mismatch test failed, and why I briefly deleted a working feature over it.
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
        "name": "Competence commission", "code": "CMP26", "client": "A Client",
        "designManager": "Dept Manager", "leadEngineer": "Staff One",
        "status": "Active", "currentStage": "Detail", "members": "Staff One"})


def _rec(api, tokens, commission, **kw):
    body = {"projectId": commission["id"], "person": "Carol Checker",
            "scope": "Electrical", "basis": "8 years LV distribution design",
            "status": "Proposed"}
    body.update(kw)
    return _mk(api, tokens["staff"], "eng_competence", body)


def test_competence_is_granted_by_the_design_authority(api, tokens, commission):
    c = _rec(api, tokens, commission)
    st, b = _sign(api, tokens["staff"], "eng_competence", c["id"], "Authorised")
    assert st == 200, b
    assert b["item"]["authorisedBy"] == "Staff One"
    assert b["item"]["authorisedOn"]


def test_nobody_authorises_themselves(api, tokens, commission):
    """The whole content of the word is that somebody else says it."""
    c = _rec(api, tokens, commission, person="Staff One")
    st, b = _sign(api, tokens["staff"], "eng_competence", c["id"], "Authorised")
    assert st != 200, "authorised their own competence"
    assert "yourself" in str(b).lower()


def test_a_post_cannot_forge_an_authorisation(api, tokens, commission):
    c = _rec(api, tokens, commission, status="Authorised",
             authorisedBy="Nobody At All", authorisedOn="2020-01-01")
    assert not c.get("authorisedBy"), "a browser must not be able to grant competence"


def test_an_unrecorded_checker_does_not_stop_the_issue(api, tokens, commission):
    """The deliberate non-rule. An administrative gap must not stop real work."""
    d = _mk(api, tokens["staff"], "eng_deliverables", {
        "projectId": commission["id"], "docNo": "CMP26-EL-DWG-001", "title": "SLD",
        "docType": "Drawing", "discipline": "Electrical", "stage": "Detail",
        "preparedBy": "Alice Engineer", "approver": "Staff One"})
    rev = _mk(api, tokens["staff"], "eng_revisions", {
        "projectId": commission["id"], "deliverableId": d["id"], "rev": "C01",
        "issueStatus": "IFC", "reasonForIssue": "issue", "preparedBy": "Alice Engineer",
        "checkedBy": "Somebody With No Record", "status": "Draft"})
    st, b = _sign(api, tokens["staff"], "eng_revisions", rev["id"], "Issued")
    assert st == 200, b


def test_a_checker_authorised_for_another_discipline_is_noted(api, tokens, commission):
    """Not refused — counted. The gap becomes visible instead of invisible."""
    c = _rec(api, tokens, commission, person="Mechanical Mike", scope="Mechanical")
    st, _ = _sign(api, tokens["staff"], "eng_competence", c["id"], "Authorised")
    assert st == 200

    d = _mk(api, tokens["staff"], "eng_deliverables", {
        "projectId": commission["id"], "docNo": "CMP26-EL-DWG-002", "title": "SLD",
        "docType": "Drawing", "discipline": "Electrical", "stage": "Detail",
        "preparedBy": "Alice Engineer", "approver": "Staff One"})
    rev = _mk(api, tokens["staff"], "eng_revisions", {
        "projectId": commission["id"], "deliverableId": d["id"], "rev": "C01",
        "issueStatus": "IFC", "reasonForIssue": "issue", "preparedBy": "Alice Engineer",
        "checkedBy": "Mechanical Mike", "status": "Draft"})
    st, b = _sign(api, tokens["staff"], "eng_revisions", rev["id"], "Issued")
    assert st == 200, "a competence gap must never block an issue"

    st2, log = api("GET", "/api/coll/eng_refusals", tokens["admin"])
    assert st2 == 200
    noted = [x for x in log["items"] if x.get("recordId") == rev["id"]
             and x.get("source") == "advisory"]
    assert noted, "the mismatch should be countable, not silent"
    assert "Mechanical Mike" in noted[0]["message"]


def test_a_checker_authorised_for_the_discipline_raises_nothing(api, tokens, commission):
    c = _rec(api, tokens, commission, person="Electrical Ellen", scope="Electrical")
    st, _ = _sign(api, tokens["staff"], "eng_competence", c["id"], "Authorised")
    assert st == 200

    d = _mk(api, tokens["staff"], "eng_deliverables", {
        "projectId": commission["id"], "docNo": "CMP26-EL-DWG-003", "title": "SLD",
        "docType": "Drawing", "discipline": "Electrical", "stage": "Detail",
        "preparedBy": "Alice Engineer", "approver": "Staff One"})
    rev = _mk(api, tokens["staff"], "eng_revisions", {
        "projectId": commission["id"], "deliverableId": d["id"], "rev": "C01",
        "issueStatus": "IFC", "reasonForIssue": "issue", "preparedBy": "Alice Engineer",
        "checkedBy": "Electrical Ellen", "status": "Draft"})
    st, b = _sign(api, tokens["staff"], "eng_revisions", rev["id"], "Issued")
    assert st == 200, b

    st2, log = api("GET", "/api/coll/eng_refusals", tokens["admin"])
    noted = [x for x in log["items"] if x.get("recordId") == rev["id"]
             and x.get("source") == "advisory"]
    assert not noted, "a properly authorised checker should raise nothing"
