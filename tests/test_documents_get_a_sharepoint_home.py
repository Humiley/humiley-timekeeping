# -*- coding: utf-8 -*-
"""Four families of document that had nowhere to live, and the ways giving them one goes wrong.

Onboarding files, labour contracts, job descriptions, claims, travel, payments and supplier invoices
all file themselves into SharePoint. Published policies, HR decisions, confirmation letters and
candidate CVs did not — every SharePoint write in app.py goes through _graph_put_bytes, and it had
four callers, none of them these.

Two of the four are worse than "stored in the wrong place". A decision and a confirmation letter are
drawn in the BROWSER at issue time and go straight to the issuer's Downloads folder: the row holds
the facts, not the paper, and a reprint re-renders from those facts against TODAY's employee record.
So the reprint of a salary decision changes when the salary changes, and the company holds no copy
of what it actually signed.

What must not break, and why each of these tests exists:

  · THE FIELD NAME. hrdocs is read by three separate call sites that each ask "is there a file?" by
    hand, and all three know only `file` and `fileUrl`. The two existing HR filers write `webUrl`.
    Copy that precedent and every filed policy silently drops out of the chase list, becomes
    unsignable with a 409, and 404s on its own file endpoint — while the register still lists it.
  · THE ISSUED-DOCUMENT ALLOW-LIST. decisions and hrletters are ISSUED_ONLY, enforced by a
    BOTH-DIRECTIONS diff: a key the body omits counts as a change. A field outside ISSUED_EDITABLE
    makes every later edit 400 — including the ones the allow-list exists to permit.
  · FILENAME COLLISIONS. _hrsp_put hands _sp_safe_leaf an empty id, which is exactly the branch that
    does NOT add a content hash, and Graph replaces on conflict. Two candidates who both upload
    "cv.pdf" would end as one file with two records pointing at it.
  · THE AUDITED READ PATH. Every CV read writes "CV opened" into the tamper-evident chain. A link
    into a shared library is read by whoever the library admits, unrecorded — so the CV filer files
    a COPY and leaves the portal's own path exactly as it was.

The harness gets the no-SharePoint half for free: TK_M365_CLIENT_SECRET is unset under pytest, so
_invtrack_app_ready() is false and _hrsp_put raises on its first line with no network call.
"""
import base64

import pytest

import app
import db

PDF = "data:application/pdf;base64," + base64.b64encode(b"%PDF-1.4 policy bytes").decode()
# What jsPDF really emits. The strict data: pattern used elsewhere in app.py refuses this.
JSPDF = "data:application/pdf;filename=generated.pdf;base64," + \
        base64.b64encode(b"%PDF-1.4 issued document").decode()


def _rm(coll, rid):
    try:
        db.delete_collection_item(coll, rid)
    except Exception:
        pass


# ══ 1. the two helpers ═════════════════════════════════════════════════════════════════════════

def test_two_files_called_cv_pdf_do_not_become_one_file():
    a = app._hrsp_name("c-111", "cv.pdf")
    b = app._hrsp_name("c-222", "cv.pdf")
    assert a != b, "both candidates would file as the same name, and Graph replaces on conflict"
    assert "c-111" in a and "cv.pdf" in a


def test_a_name_cannot_climb_out_of_its_folder():
    assert "/" not in app._hrsp_name("x", "../../secrets.pdf")
    assert "\\" not in app._hrsp_name("a/b:c", "..\\..\\x.pdf")
    assert app._hrsp_name("", "") == "document.pdf", "a blank name must still be a name"


def test_the_filer_reads_what_jspdf_actually_writes():
    """The ';filename=generated.pdf;' segment sits between the media type and ';base64,'.

    Getting this wrong does not look like a parse error. It looks like a document that filed
    successfully and then cannot be opened.
    """
    web, err = app._hrsp_file(["X"], "a.pdf", JSPDF)
    assert web == ""                       # no SharePoint configured under pytest
    assert "could not be read" not in err, \
        "the tolerant data: pattern rejected jsPDF's own output: %r" % err


def test_the_filer_never_raises():
    """Every caller has already written its record. A SharePoint outage costs the filing, nothing else."""
    for bad in (None, "", "notadatauri", "data:application/pdf;base64,!!!not base64!!!"):
        web, err = app._hrsp_file(["X"], "a.pdf", bad)
        assert web == "" and err, "expected a reported failure, not a raise, for %r" % bad


def test_an_oversized_file_is_refused_by_the_filer_not_by_graph():
    big = "data:application/pdf;base64," + base64.b64encode(b"A" * (9 * 1024 * 1024)).decode()
    web, err = app._hrsp_file(["X"], "a.pdf", big)
    assert web == "" and "too large" in err


# ══ 2. published policies ══════════════════════════════════════════════════════════════════════

@pytest.fixture
def doc(api, tokens):
    st, b = api("POST", "/api/coll/hrdocs", tokens["admin"],
                {"title": "Employee Handbook", "code": "HR-POL-01", "version": "1.0",
                 "audience": "All", "file": PDF, "fileName": "handbook.pdf"})
    assert st == 200, b
    rid = (b.get("item") or b).get("id")
    yield rid
    _rm("hrdocs", rid)


def test_a_published_policy_keeps_its_bytes_when_sharepoint_is_not_set_up(doc):
    """The JD filer deletes the bytes once filed. This one must not, even on success — but the
    case that matters here is the customer's: no HR folder configured yet."""
    row = db.get_collection_item("hrdocs", doc)
    assert row["file"] == PDF, "publishing lost the document"
    assert not row.get("fileUrl"), "there is no SharePoint to have filed it in"
    assert row.get("fileError"), "and the record should say why it was not filed"


def test_the_client_cannot_claim_where_a_policy_was_filed(api, tokens):
    """Same rule the acknowledgement PDF already enforces on webUrl. This link is offered to every
    employee the document is addressed to, so a client-settable value points them anywhere."""
    st, b = api("POST", "/api/coll/hrdocs", tokens["admin"],
                {"title": "Forged", "code": "X-1", "audience": "All", "file": PDF,
                 "fileName": "x.pdf", "fileUrl": "https://evil.example/steal"})
    rid = (b.get("item") or b).get("id")
    try:
        assert st == 200, b
        assert db.get_collection_item("hrdocs", rid).get("fileUrl") != "https://evil.example/steal"
    finally:
        _rm("hrdocs", rid)


def test_editing_a_policy_carries_the_file_and_its_link_forward(api, tokens, doc):
    """The register PATCHes the whole row it is holding, and that row came from a LIST read with the
    bytes blanked. Archive/restore does exactly this. Losing the link here would quietly un-file it."""
    row = dict(db.get_collection_item("hrdocs", doc))
    row["fileUrl"] = "https://contoso.sharepoint.com/x/handbook.pdf"     # as a successful filing left it
    db.put_collection_item("hrdocs", row)

    st, b = api("PATCH", "/api/coll/hrdocs/" + doc, tokens["admin"],
                {"id": doc, "title": "Employee Handbook", "code": "HR-POL-01",
                 "audience": "All", "archived": True, "file": "", "hasFile": True})
    assert st == 200, b
    after = db.get_collection_item("hrdocs", doc)
    assert after["file"] == PDF, "an edit that did not re-upload deleted the document"
    assert after["fileUrl"] == "https://contoso.sharepoint.com/x/handbook.pdf", \
        "the SharePoint link was dropped, so the filed copy became unreachable from the portal"
    assert after["fileName"] == "handbook.pdf"


def test_removing_the_file_removes_the_link_with_it(api, tokens, doc):
    row = dict(db.get_collection_item("hrdocs", doc))
    row["fileUrl"] = "https://contoso.sharepoint.com/x/handbook.pdf"
    db.put_collection_item("hrdocs", row)

    st, b = api("PATCH", "/api/coll/hrdocs/" + doc, tokens["admin"],
                {"id": doc, "title": "Employee Handbook", "audience": "All", "removeFile": True})
    assert st == 200, b
    after = db.get_collection_item("hrdocs", doc)
    assert not after.get("file") and not after.get("fileUrl") and not after.get("fileName"), \
        "a removed document still had somewhere to be read from: %r" % (
            {k: after.get(k) for k in ("file", "fileUrl", "fileName")})


def test_a_filed_policy_is_still_a_signable_policy(doc):
    """_hrdoc_has_file is what decides whether a document is chased and whether it can be signed.
    It reads `file` or `fileUrl` — never `webUrl`, which is what the two existing HR filers write."""
    assert app._hrdoc_has_file({"fileUrl": "https://x/y.pdf"}) is True
    assert app._hrdoc_has_file({"webUrl": "https://x/y.pdf"}) is False, \
        "if the wiring ever writes webUrl, this is the assertion that says why it broke"


# ══ 3. issued decisions and letters ════════════════════════════════════════════════════════════

@pytest.fixture
def decision():
    rid = "qd-testarch"
    db.put_collection_item("decisions", {
        "id": rid, "kind": "salary", "empId": "HML-STF", "empName": "Tran Thi C",
        "no": "12/2026/QD-HML", "subject": "Salary adjustment", "issuedAt": "2026-08-31"})
    yield rid
    _rm("decisions", rid)


def test_the_company_now_keeps_a_copy_of_what_it_issued(api, tokens, decision):
    """Before this, a quyet dinh existed only in the issuer's Downloads folder."""
    st, b = api("POST", "/api/hr/issued-file", tokens["admin"],
                {"kind": "decision", "id": decision, "file": JSPDF, "name": "12-2026.pdf"})
    assert st == 200, b
    assert b["filed"] is False, "no SharePoint is configured under pytest"
    assert b["error"], "and it must say why rather than reporting a silent success"
    row = db.get_collection_item("decisions", decision)
    assert row["file"] == JSPDF, "the copy was not kept either — the document is gone again"
    assert row["fileName"] == "12-2026.pdf"
    assert "fileError" not in row, \
        "fileError is outside ISSUED_EDITABLE; storing it makes every later edit of this " \
        "frozen document 400"


def test_a_document_is_archived_once(api, tokens, decision):
    """A second upload against one record is a different PDF wearing the same reference number."""
    api("POST", "/api/hr/issued-file", tokens["admin"],
        {"kind": "decision", "id": decision, "file": JSPDF, "name": "first.pdf"})
    other = "data:application/pdf;base64," + base64.b64encode(b"%PDF different").decode()
    st, b = api("POST", "/api/hr/issued-file", tokens["admin"],
                {"kind": "decision", "id": decision, "file": other, "name": "second.pdf"})
    assert st == 200 and b.get("already") is True
    assert db.get_collection_item("decisions", decision)["file"] == JSPDF, \
        "the archived document was overwritten by a later render"


def test_only_an_issued_letter_is_filed(api, tokens):
    rid = "xn-testarch"
    db.put_collection_item("hrletters", {"id": rid, "empId": "HML-STF", "empName": "Tran Thi C",
                                         "purpose": "bank", "status": "Requested"})
    try:
        st, b = api("POST", "/api/hr/issued-file", tokens["admin"],
                    {"kind": "letter", "id": rid, "file": PDF, "name": "x.pdf"})
        assert st == 400, "a request is not a document: %r" % (b,)
        assert not db.get_collection_item("hrletters", rid).get("file")
    finally:
        _rm("hrletters", rid)


def test_staff_cannot_file_a_document_against_somebody_elses_decision(api, tokens, decision):
    st, _ = api("POST", "/api/hr/issued-file", tokens["staff"],
                {"kind": "decision", "id": decision, "file": PDF, "name": "x.pdf"})
    assert st in (403, 404), "the archive must not be a way around the issue-level gate"
    assert not db.get_collection_item("decisions", decision).get("file")


def test_an_unknown_kind_and_a_missing_record_are_refused(api, tokens):
    st, _ = api("POST", "/api/hr/issued-file", tokens["admin"],
                {"kind": "payslip", "id": "x", "file": PDF})
    assert st == 400
    st, _ = api("POST", "/api/hr/issued-file", tokens["admin"],
                {"kind": "decision", "id": "qd-nope", "file": PDF})
    assert st == 404


def test_the_register_lists_decisions_without_shipping_them(api, tokens, decision):
    """The defect that made the project Quality tab time out at 30 seconds, one collection over."""
    api("POST", "/api/hr/issued-file", tokens["admin"],
        {"kind": "decision", "id": decision, "file": JSPDF, "name": "12-2026.pdf"})
    st, b = api("GET", "/api/coll/decisions", tokens["admin"])
    assert st == 200
    row = next((r for r in b["items"] if r["id"] == decision), None)
    assert row is not None
    assert not row.get("file"), "the register shipped the PDF to draw a table"
    assert row.get("hasFile") is True, "and now the table cannot tell there is a document at all"

    st, one = api("GET", "/api/coll/decisions/" + decision, tokens["admin"])
    assert st == 200 and one["item"]["file"] == JSPDF, \
        "the single-record route is where the bytes belong, and it stopped serving them"


def test_hasfile_does_not_make_an_issued_edit_illegal():
    """hasFile is derived on read. Left out of ISSUED_EDITABLE, a row read from the register and
    sent straight back reads as an illegal edit of a frozen document."""
    for coll in ("decisions", "hrletters"):
        assert "hasFile" in app.Handler.ISSUED_EDITABLE[coll], coll


# ══ 4. candidate CVs ═══════════════════════════════════════════════════════════════════════════

def test_a_cv_is_copied_not_moved(api, tokens):
    """Deliberately unlike the other three. Every CV read writes "CV opened" into the tamper-evident
    chain, and that control exists only while the portal is the way in — a library link is read by
    whoever the library admits, unrecorded. So the bytes stay, and the audited path is untouched."""
    st, b = api("POST", "/api/coll/candidates", tokens["mgr"],
                {"name": "Le Van D", "role": "QA Engineer", "stage": "Applied"})
    cid = (b.get("item") or b).get("id")
    try:
        st, b = api("POST", "/api/hr/cv", tokens["mgr"],
                    {"candidateId": cid, "file": PDF, "fileName": "cv.pdf"})
        assert st == 200, b
        assert b["filed"] is False and b["fileError"]
        assert db.get_collection_item("candidates", cid)["cvFile"] == PDF, \
            "filing a copy destroyed the original"

        st, one = api("GET", "/api/hr/cv/" + cid, tokens["mgr"])
        assert st == 200 and one["file"] == PDF, "the audited read path stopped working"
    finally:
        _rm("candidates", cid)


# ══ 5. the success path ════════════════════════════════════════════════════════════════════════
# Everything above runs with SharePoint unconfigured — the customer's situation today, and the half
# that must not lose a document. But it means nothing above ever observes a SUCCESSFUL filing, and
# "the link is written under the name the readers actually read" is the assertion this whole change
# turns on. The handler runs in this process, so a stand-in _hrsp_put makes the success path real
# without a network call, and records where each family asked to be filed.

@pytest.fixture
def filed(monkeypatch):
    seen = []

    def fake(sub_dirs, filename, raw, ctype):
        seen.append({"dirs": list(sub_dirs), "name": filename, "bytes": len(raw), "type": ctype})
        return "https://contoso.sharepoint.com/sites/HR/" + "/".join(list(sub_dirs) + [filename])

    monkeypatch.setattr(app, "_hrsp_put", fake)
    return seen


def test_a_filed_policy_records_the_link_where_the_three_readers_look(api, tokens, filed):
    st, b = api("POST", "/api/coll/hrdocs", tokens["admin"],
                {"title": "Safety Policy", "code": "HR-OSH-02", "audience": "All",
                 "effectiveFrom": "2024-03-01", "file": PDF, "fileName": "safety.pdf"})
    rid = (b.get("item") or b).get("id")
    try:
        assert st == 200, b
        row = db.get_collection_item("hrdocs", rid)
        assert row["fileUrl"].endswith("safety.pdf"), row
        assert "webUrl" not in row, \
            "webUrl is what the two OLDER HR filers write, and no hrdocs reader knows that name — " \
            "a policy filed under it drops out of the chase list, cannot be signed, and 404s"
        assert row["file"] == PDF, "a successful filing must not delete the audience-scoped copy"
        assert not row.get("fileError")
        assert filed[0]["dirs"] == ["Policies", "2024"], \
            "filed by the year it took effect, not the year it was typed in: %r" % (filed[0],)
        assert filed[0]["name"] == "HR-OSH-02 - safety.pdf"
    finally:
        _rm("hrdocs", rid)


def test_a_filed_decision_lands_in_the_employee_folder_beside_their_contract(api, tokens,
                                                                            decision, filed):
    st, b = api("POST", "/api/hr/issued-file", tokens["admin"],
                {"kind": "decision", "id": decision, "file": JSPDF, "name": "12-2026.pdf"})
    assert st == 200 and b["filed"] is True, b
    row = db.get_collection_item("decisions", decision)
    assert row["fileUrl"] == b["fileUrl"]
    assert not row.get("file"), \
        "once SharePoint holds it there is no reason to carry a second copy on the row"
    assert filed[0]["dirs"][0] == "Employees" and filed[0]["dirs"][-1] == "Decisions", filed[0]
    assert "HML-STF" in filed[0]["dirs"][1], \
        "the same three-segment shape onboarding files and contracts already use"
    assert filed[0]["type"] == "application/pdf", \
        "jsPDF's ';filename=' segment must not be mistaken for the media type"


def test_a_filed_letter_goes_to_Letters_not_Decisions(api, tokens, filed):
    rid = "xn-filedok"
    db.put_collection_item("hrletters", {"id": rid, "empId": "HML-STF", "empName": "Staff One",
                                         "purpose": "bank", "status": "Issued", "no": "7/2026/XN"})
    try:
        st, b = api("POST", "/api/hr/issued-file", tokens["admin"],
                    {"kind": "letter", "id": rid, "file": JSPDF, "name": "xn.pdf"})
        assert st == 200 and b["filed"] is True, b
        assert filed[0]["dirs"][-1] == "Letters", filed[0]
        assert filed[0]["name"].startswith("7_2026_XN"), \
            "the document number makes the name unique, and '/' is illegal in a SharePoint " \
            "leaf: %r" % (filed[0]["name"],)
    finally:
        _rm("hrletters", rid)


def test_a_filed_cv_keeps_both_copies_and_uses_the_field_hasCv_reads(api, tokens, filed):
    st, b = api("POST", "/api/coll/candidates", tokens["mgr"],
                {"name": "Pham Van E", "role": "Draughtsman", "stage": "Applied"})
    cid = (b.get("item") or b).get("id")
    try:
        st, b = api("POST", "/api/hr/cv", tokens["mgr"],
                    {"candidateId": cid, "file": PDF, "fileName": "cv.pdf"})
        assert st == 200 and b["filed"] is True, b
        row = db.get_collection_item("candidates", cid)
        assert row["cvUrl"] == b["cvUrl"]
        assert row["cvFile"] == PDF, \
            "the bytes stay: /api/hr/cv/<id> writes 'CV opened' into the tamper-evident chain on " \
            "every read, and a library link is read by whoever the library admits, unrecorded"
        assert filed[0]["dirs"][0] == "Recruitment"
        assert filed[0]["name"].startswith(cid), \
            "every applicant's laptop calls it cv.pdf, and Graph replaces on conflict: %r" % (
                filed[0]["name"],)
    finally:
        _rm("candidates", cid)
