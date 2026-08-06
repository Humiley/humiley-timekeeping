"""Signing for a company document.

HR publishes a policy once; everybody it applies to reads it and signs. The signature is the whole
point — in six months the question is never "was it announced", it is "show me what they signed and
which version it was". So the record has to say who, when, and against which VERSION, and none of
those may come from the browser: a client that could choose them could sign a policy in a colleague's
name, or backdate a signature to before the incident it is meant to cover.
"""
import app
import db


def _doc(api, tokens, **kw):
    body = {"title": "Employee Handbook", "code": "HML-HR-001", "version": "1.0",
            "category": "Handbook", "audience": "All"}
    body.update(kw)
    st, b = api("POST", "/api/coll/hrdocs", tokens["admin"], body)
    assert st == 200, b
    return b["item"]


def _sign(api, token, doc_id, **extra):
    body = {"docId": doc_id, "signature": "data:image/png;base64,AAA"}
    body.update(extra)
    return api("POST", "/api/coll/hrdoc_acks", token, body)


def test_an_employee_can_sign_for_a_document(api, tokens):
    d = _doc(api, tokens)
    st, b = _sign(api, tokens["staff"], d["id"])
    assert st == 200, b
    a = b["item"]
    assert a["empId"] == "HML-STF" and a["name"] == "Staff One"
    assert a["docTitle"] == "Employee Handbook" and a["docVersion"] == "1.0"


def test_you_cannot_sign_in_somebody_else_s_name(api, tokens):
    """The one that matters. A signature is worthless if the signer is a field the client fills in."""
    d = _doc(api, tokens, code="HML-HR-002")
    st, b = _sign(api, tokens["staff"], d["id"], empId="HML-ADM", name="Admin User")
    assert b["item"]["empId"] == "HML-STF", "a client signed as somebody else"
    assert b["item"]["name"] == "Staff One"


def test_a_signature_cannot_be_backdated(api, tokens):
    """Backdating would let somebody claim they had read a safety policy before an accident."""
    d = _doc(api, tokens, code="HML-HR-003")
    st, b = _sign(api, tokens["staff"], d["id"], ts="2020-01-01T00:00:00.000Z")
    assert not b["item"]["ts"].startswith("2020")


def test_the_version_signed_for_comes_from_the_published_record(api, tokens):
    """Otherwise a client could sign against v1 while reading v2 — or against a title it invented."""
    d = _doc(api, tokens, code="HML-HR-004", version="3.2", title="Code of Conduct")
    st, b = _sign(api, tokens["staff"], d["id"], docVersion="1.0", docTitle="Something harmless")
    assert b["item"]["docVersion"] == "3.2"
    assert b["item"]["docTitle"] == "Code of Conduct"


def test_you_cannot_sign_for_a_document_that_does_not_exist(api, tokens):
    st, b = _sign(api, tokens["staff"], "made-up-id")
    assert st == 404, (st, b)


def test_the_client_cannot_claim_where_the_signature_was_filed(api, tokens):
    """webUrl is the server's statement that the PDF reached SharePoint. A client that could set it
       would let an unfiled acknowledgement look filed."""
    d = _doc(api, tokens, code="HML-HR-005")
    st, b = _sign(api, tokens["staff"], d["id"], webUrl="https://example.invalid/not-really")
    assert not b["item"].get("webUrl")


def test_staff_see_only_their_own_acknowledgements(api, tokens):
    d = _doc(api, tokens, code="HML-HR-006")
    _sign(api, tokens["staff"], d["id"])
    _sign(api, tokens["other"], d["id"])
    st, b = api("GET", "/api/coll/hrdoc_acks", tokens["staff"])
    assert all(a["empId"] == "HML-STF" for a in b.get("items", []))


def test_everybody_can_read_the_published_documents(api, tokens):
    """A policy nobody can fetch is a policy nobody can sign."""
    _doc(api, tokens, code="HML-HR-007", title="HSE rules")
    st, b = api("GET", "/api/coll/hrdocs", tokens["staff"])
    assert st == 200
    assert "HSE rules" in [d.get("title") for d in b.get("items", [])]


def test_staff_cannot_publish_a_document(api, tokens):
    """Publishing decides what the whole company must sign — that is not a self-service action."""
    st, b = api("POST", "/api/coll/hrdocs", tokens["staff"],
                {"title": "My own policy", "audience": "All"})
    assert st == 403, (st, b)


def test_only_an_admin_can_create_the_employee_folders(api, tokens):
    st, b = api("POST", "/api/hr/employee-folders", tokens["mgr"], {})
    assert st == 403, (st, b)


def test_filing_somebody_else_s_acknowledgement_is_refused(api, tokens):
    d = _doc(api, tokens, code="HML-HR-008")
    ack = _sign(api, tokens["staff"], d["id"])[1]["item"]
    st, b = api("POST", "/api/hr/onboarding/file", tokens["other"],
                {"ackId": ack["id"], "data": "data:application/pdf;base64,JVBERi0="})
    assert st == 403, (st, b)
