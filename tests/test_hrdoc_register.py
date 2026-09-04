"""Managing a published company document.

The feature shipped able to publish a document and unable to touch it afterwards. Six policies were
migrated with no file attached, so every employee was shown "Read & sign" with nothing to read and no
route existed to ever upload the PDF. These tests pin the parts of that fix that live on the server:
what may be signed, what may be deleted, who may publish, what a reader is allowed to see, and the
facts the record has to carry so a deadline means something.
"""
import app
import db


def _doc(api, tokens, **kw):
    body = {"title": "Employee Handbook", "code": "HML-HR-001", "version": "1.0",
            "category": "Handbook", "audience": "All",
            "file": "data:application/pdf;base64,JVBERi0xLjQK", "fileName": "handbook.pdf"}
    body.update(kw)
    st, b = api("POST", "/api/coll/hrdocs", tokens["admin"], body)
    assert st == 200, b
    return b["item"]


# ── nothing to read means nothing to sign ────────────────────────────────────────────────────────

def test_a_document_with_no_file_cannot_be_signed(api, tokens):
    """The acknowledgement says "I have received and read this document". With no file behind it that
    is a false statement on a controlled form — and the matrix would then report the person green."""
    d = _doc(api, tokens, file="", fileName="")
    st, b = api("POST", "/api/coll/hrdoc_acks", tokens["staff"],
                {"docId": d["id"], "signature": "data:image/png;base64,AAA"})
    assert st == 409, b
    assert "no file" in (b.get("error") or "").lower()
    assert not [a for a in db.list_collection("hrdoc_acks") if a.get("docId") == d["id"]]


def test_attaching_the_file_makes_it_signable(api, tokens):
    d = _doc(api, tokens, file="", fileName="")
    api("PATCH", "/api/coll/hrdocs/" + d["id"], tokens["admin"],
        dict(d, file="data:application/pdf;base64,JVBERi0xLjQK", fileName="handbook.pdf"))
    st, b = api("POST", "/api/coll/hrdoc_acks", tokens["staff"],
                {"docId": d["id"], "signature": "data:image/png;base64,AAA"})
    assert st == 200, b


def test_a_file_less_document_is_not_chased(api, tokens):
    """The daily sweep must not email somebody about a document they cannot open."""
    d = _doc(api, tokens, file="", fileName="", dueDays=1)
    assert not [o for o in app._hrdoc_outstanding() if o["doc"]["id"] == d["id"]]


def test_a_file_less_document_shows_as_nofile_not_overdue(api, tokens):
    """HR's problem, not the employee's — it must not put a red mark against a person."""
    d = _doc(api, tokens, file="", fileName="", dueDays=1, effectiveFrom="2020-01-01")
    st, b = api("GET", "/api/hr/compliance", tokens["admin"])
    assert st == 200, b
    mine = [r for r in b["rows"] if r["docId"] == d["id"]]
    assert mine, "the document should still appear for HR"
    assert {r["state"] for r in mine} == {"nofile"}
    assert [x for x in b["docs"] if x["id"] == d["id"]][0]["hasFile"] is False


# ── a signature is permanent ─────────────────────────────────────────────────────────────────────

def test_an_employee_cannot_delete_their_own_signature(api, tokens):
    """hrdoc_acks is staff-writable and self-owned, so the signer used to be able to simply remove
    their own signature and go back to Outstanding with nothing recording it had ever existed."""
    d = _doc(api, tokens)
    st, b = api("POST", "/api/coll/hrdoc_acks", tokens["staff"],
                {"docId": d["id"], "signature": "data:image/png;base64,AAA"})
    ack = b["item"]
    st, b = api("DELETE", "/api/coll/hrdoc_acks/" + ack["id"], tokens["staff"])
    assert st == 403, b
    assert db.get_collection_item("hrdoc_acks", ack["id"])


def test_not_even_an_admin_can_delete_a_signature(api, tokens):
    d = _doc(api, tokens)
    _, b = api("POST", "/api/coll/hrdoc_acks", tokens["staff"],
               {"docId": d["id"], "signature": "data:image/png;base64,AAA"})
    st, _ = api("DELETE", "/api/coll/hrdoc_acks/" + b["item"]["id"], tokens["admin"])
    assert st == 403


def test_a_signed_document_cannot_be_deleted_out_from_under_its_signatures(api, tokens):
    """Deleting the document leaves the acks unreachable: both the matrix and the sweep walk
    documents and look acks up by (docId, empId, version)."""
    d = _doc(api, tokens)
    api("POST", "/api/coll/hrdoc_acks", tokens["staff"],
        {"docId": d["id"], "signature": "data:image/png;base64,AAA"})
    st, b = api("DELETE", "/api/coll/hrdocs/" + d["id"], tokens["admin"])
    assert st == 409, b
    assert "archive" in (b.get("error") or "").lower()
    assert db.get_collection_item("hrdocs", d["id"])


def test_an_unsigned_document_can_still_be_deleted(api, tokens):
    d = _doc(api, tokens)
    st, _ = api("DELETE", "/api/coll/hrdocs/" + d["id"], tokens["admin"])
    assert st == 200
    assert not db.get_collection_item("hrdocs", d["id"])


# ── archiving is the way to withdraw one ─────────────────────────────────────────────────────────

def test_archiving_withdraws_a_document_without_destroying_its_signatures(api, tokens):
    d = _doc(api, tokens)
    api("POST", "/api/coll/hrdoc_acks", tokens["staff"],
        {"docId": d["id"], "signature": "data:image/png;base64,AAA"})
    st, b = api("PATCH", "/api/coll/hrdocs/" + d["id"], tokens["admin"], dict(d, archived=True))
    assert st == 200, b
    assert not [o for o in app._hrdoc_outstanding() if o["doc"]["id"] == d["id"]]
    _, comp = api("GET", "/api/hr/compliance", tokens["admin"])
    assert not [r for r in comp["rows"] if r["docId"] == d["id"]]
    assert [a for a in db.list_collection("hrdoc_acks") if a.get("docId") == d["id"]]


# ── editing must not quietly destroy the document ────────────────────────────────────────────────

def test_editing_without_re_uploading_keeps_the_file(api, tokens):
    """List reads no longer carry the bytes, so the edit form cannot send them back. A blind
    overwrite would delete the attachment on any edit that did not re-upload it."""
    d = _doc(api, tokens)
    st, b = api("PATCH", "/api/coll/hrdocs/" + d["id"], tokens["admin"],
                {"id": d["id"], "title": "Employee Handbook", "code": "HML-HR-001",
                 "version": "1.0", "audience": "All", "owner": "Tran Doan"})
    assert st == 200, b
    assert b["item"]["file"].startswith("data:application/pdf")
    assert b["item"]["fileName"] == "handbook.pdf"
    assert b["item"]["owner"] == "Tran Doan"


def test_removing_the_file_takes_an_explicit_flag(api, tokens):
    d = _doc(api, tokens)
    _, b = api("PATCH", "/api/coll/hrdocs/" + d["id"], tokens["admin"], dict(d, removeFile=True))
    assert b["item"]["file"] == "" and b["item"]["fileName"] == ""
    assert "removeFile" not in b["item"]


def test_publication_facts_survive_an_edit(api, tokens):
    d = _doc(api, tokens)
    assert d.get("ts") and d.get("publishedBy")
    _, b = api("PATCH", "/api/coll/hrdocs/" + d["id"], tokens["admin"],
               {"id": d["id"], "title": "Employee Handbook", "ts": "1999-01-01T00:00:00Z",
                "publishedBy": "Somebody Else"})
    assert b["item"]["ts"] == d["ts"]
    assert b["item"]["publishedBy"] == d["publishedBy"]
    assert b["item"]["updatedBy"]


# ── a deadline has to be measured from something ─────────────────────────────────────────────────

def test_a_document_with_no_publication_date_is_never_overdue(api, tokens):
    """Falling through to the join date invented a deadline out of nothing and then chased it daily,
    making every existing employee overdue the moment the document appeared."""
    emp = {"id": "E1", "name": "A", "joinDate": "2020-01-01", "status": "Active"}
    assert app._hrdoc_due({"dueDays": 7}, emp) == ""
    assert app._hrdoc_due({"dueDays": 7, "effectiveFrom": "2026-01-01"}, emp) == "2026-01-08"


def test_publishing_is_recorded_in_the_audit_trail(api, tokens):
    """Deletion was logged and publication was not — the asymmetry that matters most in an argument
    about who changed a policy after people had signed it."""
    d = _doc(api, tokens)
    acts = [a for a in db.list_collection("audit") if a.get("target") == "hrdocs/" + d["id"]]
    assert any(a["action"] == "Published document" for a in acts)
    api("PATCH", "/api/coll/hrdocs/" + d["id"], tokens["admin"], dict(d, version="2.0"))
    acts = [a for a in db.list_collection("audit") if a.get("target") == "hrdocs/" + d["id"]]
    assert any("Re-issued" in a["action"] for a in acts)


# ── who may publish, and who may read ────────────────────────────────────────────────────────────

def test_staff_cannot_publish_a_company_document(api, tokens):
    st, _ = api("POST", "/api/coll/hrdocs", tokens["staff"], {"title": "Fake policy", "code": "X"})
    assert st == 403


def test_a_document_is_only_readable_by_the_people_it_is_addressed_to(api, tokens):
    """The audience rule lived only in the browser, so any account could pull a document aimed at
    three named people."""
    mine = _doc(api, tokens, code="HML-ALL", audience="All")
    theirs = _doc(api, tokens, code="HML-SEL", title="Director contracts",
                  audience="Selected", empIds="NOBODY-1,NOBODY-2")
    st, b = api("GET", "/api/coll/hrdocs", tokens["staff"])
    assert st == 200, b
    ids = {x["id"] for x in b["items"]}
    assert mine["id"] in ids, "an audience=All document must reach everybody"
    assert theirs["id"] not in ids, "a Selected-audience document must not reach a non-addressee"


def test_an_archived_document_is_not_served_to_staff(api, tokens):
    d = _doc(api, tokens)
    api("PATCH", "/api/coll/hrdocs/" + d["id"], tokens["admin"], dict(d, archived=True))
    _, b = api("GET", "/api/coll/hrdocs", tokens["staff"])
    assert d["id"] not in {x["id"] for x in b["items"]}


def test_the_list_does_not_ship_the_file_bytes(api, tokens):
    """Six real policy PDFs inline is tens of megabytes on every Onboarding render, on a phone."""
    d = _doc(api, tokens)
    _, b = api("GET", "/api/coll/hrdocs", tokens["staff"])
    row = [x for x in b["items"] if x["id"] == d["id"]][0]
    assert row["file"] == "" and row["hasFile"] is True and row["fileName"] == "handbook.pdf"
    assert all(x.get("file") == "" for x in b["items"]), "no row may carry inline bytes"


def test_the_file_endpoint_serves_the_bytes_to_an_addressee(api, tokens):
    d = _doc(api, tokens)
    st, b = api("GET", "/api/hr/doc/" + d["id"] + "/file", tokens["staff"])
    assert st == 200, b
    assert b["file"].startswith("data:application/pdf") and b["fileName"] == "handbook.pdf"


def test_the_file_endpoint_refuses_a_document_addressed_to_somebody_else(api, tokens):
    d = _doc(api, tokens, audience="Selected", empIds="NOBODY-1")
    st, b = api("GET", "/api/hr/doc/" + d["id"] + "/file", tokens["staff"])
    assert st == 403, b
    assert not b.get("file")
