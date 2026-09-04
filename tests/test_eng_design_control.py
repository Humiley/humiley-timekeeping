"""Engineering design control — the guards that make the register evidence rather than a list.

A design office's product is documents, and the questions asked about a document a year later are
always the same: which revision was issued, for what purpose, who checked it, who approved it, and
under whose authority did it change. The register answers those only if five things hold, and each
one is tested here:

  * a signature can be applied by /api/esign and by nothing else — not by a POST that arrives with
    `issuedBy` already filled in;
  * an issued revision freezes, because ASME Y14.35 changes a released drawing by issuing a new
    revision, never by editing the released one;
  * nobody approves their own work out of the door (ISO 9001 8.3.4 verification), while an internal
    review copy stays self-serviceable — a one-engineer discipline must still be able to circulate
    a check print;
  * a design engineer on an ordinary STAFF account can work the registers, because that is who
    fills them in;
  * a review comment cannot be closed with nothing written against it, which is how a client's
    objection goes missing.
"""
import pytest

import app
import db


@pytest.fixture(autouse=True)
def _demo_esign(monkeypatch):
    """e-signing in tests skips the M365 re-auth, exactly as the demo build does."""
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
    """A commission whose Lead Engineer is the STAFF account — the normal shape in a design office,
    where design authority and portal access level are unrelated."""
    return _mk(api, tokens["admin"], "eng_projects", {
        "name": "Test design commission", "code": "TST26", "client": "A Client",
        "designManager": "Dept Manager", "leadEngineer": "Staff One",
        "status": "Active", "currentStage": "Basic", "members": "Staff One"})


def _deliv(api, tokens, commission, no, **kw):
    body = {"projectId": commission["id"], "title": "A drawing " + no, "docNo": no,
            "docType": "Drawing", "discipline": "Structural", "stage": "Detail"}
    body.update(kw)
    return _mk(api, tokens["staff"], "eng_deliverables", body)


# ── a signature comes from /api/esign and from nowhere else ───────────────────────────────────────

def test_a_post_cannot_create_an_already_signed_record(api, tokens, commission):
    d = _deliv(api, tokens, commission, "TST26-ST-DWG-001")
    rev = _mk(api, tokens["admin"], "eng_revisions", {
        "projectId": commission["id"], "deliverableId": d["id"], "rev": "C01",
        "issueStatus": "IFC", "reasonForIssue": "forged", "status": "Issued",
        "issuedBy": "Somebody Who Never Signed", "issuedOn": "2020-01-01",
        "signatures": [{"name": "Forged", "meaning": "issued"}]})
    assert not rev.get("issuedBy"), "a browser must not be able to name the signer"
    assert not rev.get("signatures")

    st = _mk(api, tokens["admin"], "eng_stages", {
        "projectId": commission["id"], "stage": "Basic", "status": "At gate",
        "gateSignedBy": "Nobody", "gateDecision": "Passed"})
    assert not st.get("gateSignedBy") and not st.get("gateDecision")

    ecn = _mk(api, tokens["admin"], "eng_changes", {
        "projectId": commission["id"], "title": "A change",
        "decidedBy": "Nobody", "decision": "Approved"})
    assert not ecn.get("decidedBy")


def test_the_server_stamps_the_signer_from_the_session(api, tokens, commission):
    d = _deliv(api, tokens, commission, "TST26-ST-DWG-002")
    rev = _mk(api, tokens["staff"], "eng_revisions", {
        "projectId": commission["id"], "deliverableId": d["id"], "rev": "P01",
        "issueStatus": "IFR", "reasonForIssue": "first issue",
        "preparedBy": "Somebody Else", "status": "Draft"})
    st, b = _sign(api, tokens["staff"], "eng_revisions", rev["id"], "Issued")
    assert st == 200, b
    assert b["item"]["issuedBy"] == "Staff One"
    assert b["item"]["issuedOn"]
    assert b["item"]["signatures"][-1]["setStatus"] == "Issued"


# ── nobody approves their own work out of the door ────────────────────────────────────────────────

def test_the_preparer_cannot_approve_their_own_external_issue(api, tokens, commission):
    d = _deliv(api, tokens, commission, "TST26-ST-DWG-003", approver="Staff One")
    rev = _mk(api, tokens["staff"], "eng_revisions", {
        "projectId": commission["id"], "deliverableId": d["id"], "rev": "C01",
        "issueStatus": "IFC", "reasonForIssue": "issued for construction",
        "preparedBy": "Staff One", "status": "Draft"})
    st, b = _sign(api, tokens["staff"], "eng_revisions", rev["id"], "Issued")
    assert st == 403
    assert "prepared" in str(b).lower()


def test_an_admin_gets_no_exemption_from_that(api, tokens, commission):
    """An exemption would aim itself at the one person most likely to be both the only preparer and
    the only approver — the owner of a small design office — which is the case the rule exists for."""
    d = _deliv(api, tokens, commission, "TST26-ST-DWG-004", approver="Admin User")
    rev = _mk(api, tokens["admin"], "eng_revisions", {
        "projectId": commission["id"], "deliverableId": d["id"], "rev": "C01",
        "issueStatus": "IFA", "reasonForIssue": "issued for approval",
        "preparedBy": "Admin User", "status": "Draft"})
    st, b = _sign(api, tokens["admin"], "eng_revisions", rev["id"], "Issued")
    assert st == 403, b


def test_an_internal_review_issue_stays_self_serviceable(api, tokens, commission):
    """IFR does not leave the office. Requiring a second signature to circulate a check print would
    stop a one-engineer discipline working at all."""
    d = _deliv(api, tokens, commission, "TST26-ST-DWG-005", approver="Staff One")
    rev = _mk(api, tokens["staff"], "eng_revisions", {
        "projectId": commission["id"], "deliverableId": d["id"], "rev": "P01",
        "issueStatus": "IFR", "reasonForIssue": "for internal review",
        "preparedBy": "Staff One", "status": "Draft"})
    st, b = _sign(api, tokens["staff"], "eng_revisions", rev["id"], "Issued")
    assert st == 200, b
    assert b["item"]["issuedBy"] == "Staff One"


def test_the_originator_of_a_change_does_not_authorise_it(api, tokens, commission):
    ecn = _mk(api, tokens["staff"], "eng_changes", {
        "projectId": commission["id"], "title": "Resize the dryer",
        "originator": "Staff One", "impactHours": 180, "decision": "Pending"})
    st, b = _sign(api, tokens["staff"], "eng_changes", ecn["id"], "Approved")
    assert st == 403
    assert "raised it" in str(b).lower()

    st2, b2 = _sign(api, tokens["mgr"], "eng_changes", ecn["id"], "Approved")
    assert st2 == 200, b2
    assert b2["item"]["decidedBy"] == "Dept Manager"
    assert b2["item"]["decision"] == "Approved"


# ── an issued revision is frozen ──────────────────────────────────────────────────────────────────

def test_an_issued_revision_is_frozen_but_can_still_be_marked_superseded(api, tokens, commission):
    d = _deliv(api, tokens, commission, "TST26-ST-DWG-006", approver="Staff One")
    rev = _mk(api, tokens["staff"], "eng_revisions", {
        "projectId": commission["id"], "deliverableId": d["id"], "rev": "P01",
        "issueStatus": "IFR", "reasonForIssue": "first issue",
        "preparedBy": "Somebody Else", "status": "Draft"})
    st, b = _sign(api, tokens["staff"], "eng_revisions", rev["id"], "Issued")
    assert st == 200, b
    signed = b["item"]

    st2, _ = api("PATCH", "/api/coll/eng_revisions/" + rev["id"], tokens["staff"],
                 dict(signed, reasonForIssue="rewritten after the fact"))
    assert st2 == 403, "what was issued must not be editable afterwards"

    # Issuing the next revision is what makes this one superseded. Recording that is not rewriting
    # the record — it is the register staying true.
    st3, b3 = api("PATCH", "/api/coll/eng_revisions/" + rev["id"], tokens["staff"],
                  dict(signed, status="Superseded", supersededBy="P02", supersededOn="2026-08-20",
                       reasonForIssue="rewritten after the fact"))
    assert st3 == 200, b3
    assert b3["item"]["status"] == "Superseded"
    assert b3["item"]["supersededBy"] == "P02"
    assert b3["item"]["reasonForIssue"] == "first issue", "superseding is not a licence to rewrite"


def test_a_signed_gate_decision_is_frozen(api, tokens, commission):
    st_row = _mk(api, tokens["staff"], "eng_stages", {
        "projectId": commission["id"], "stage": "Basic", "status": "At gate",
        "gateNotes": "ready", "criteriaDone": "0,1,2"})
    st, b = _sign(api, tokens["staff"], "eng_stages", st_row["id"], "Passed")
    assert st == 200, b
    assert b["item"]["gateSignedBy"] == "Staff One"
    assert b["item"]["gateDecision"] == "Passed"
    st2, _ = api("PATCH", "/api/coll/eng_stages/" + st_row["id"], tokens["staff"],
                 dict(b["item"], gateNotes="changed my mind", criteriaDone="0,1,2,3,4,5"))
    assert st2 == 403


# ── a comment closed with no answer is how an objection goes missing ──────────────────────────────

def test_a_comment_cannot_be_closed_with_no_response(api, tokens, commission):
    c = _mk(api, tokens["staff"], "eng_comments", {
        "projectId": commission["id"], "comment": "The fire road is too narrow",
        "commentNo": "C-001", "raisedBy": "The Client", "status": "Open",
        "responsible": "Staff One"})
    st, b = _sign(api, tokens["staff"], "eng_comments", c["id"], "Closed")
    assert st == 403
    assert "response" in str(b).lower()

    api("PATCH", "/api/coll/eng_comments/" + c["id"], tokens["staff"],
        dict(c, response="Road widened to 6 m at Rev C01."))
    st2, b2 = _sign(api, tokens["staff"], "eng_comments", c["id"], "Closed")
    assert st2 == 200, b2
    assert b2["item"]["closedBy"] == "Staff One"


# ── the people who actually use it ────────────────────────────────────────────────────────────────

def test_a_staff_engineer_can_work_the_registers(api, tokens, commission):
    d = _deliv(api, tokens, commission, "TST26-PR-DWG-009", discipline="Process")
    st, b = api("PATCH", "/api/coll/eng_deliverables/" + d["id"], tokens["staff"],
                dict(d, creditStatus="Checked"))
    assert st == 200, b
    assert b["item"]["creditStatus"] == "Checked"


def test_but_a_commission_itself_is_manager_level(api, tokens):
    st, _ = api("POST", "/api/coll/eng_projects", tokens["staff"],
                {"name": "Staff commission", "code": "NOPE"})
    assert st == 403


def test_the_app_can_be_switched_off_per_user(api, tokens):
    """Engineering Design is opt-out like CRM and Projects — an admin can disable it per account."""
    db.update_employee("HML-STF", {"appsDenied": "eng"})
    try:
        st, _ = api("GET", "/api/coll/eng_deliverables", tokens["staff"])
        assert st == 403
    finally:
        db.update_employee("HML-STF", {"appsDenied": ""})
