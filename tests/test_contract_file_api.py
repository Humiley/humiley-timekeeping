"""The labour contract as a DOCUMENT, end to end.

Before this, issuing a contract drew a PDF in the browser and called p.save(): the register held a
row saying a contract existed while the only copy of it sat in whoever pressed the button's Downloads
folder. Art. 14(1) wants the thing in writing with a copy for each party, so these tests are about the
file — that it is stored, that it comes back, that it reaches only the people entitled to it, and that
the ordinary edit path cannot quietly destroy it.

The two kinds are deliberately NOT one field:
    issued — the original this portal generated, stored automatically at issue.
    signed — the countersigned scan HR uploads when it comes back.
`hasFile` means SIGNED, because that is what the register's "no signed copy attached" warning asks
about. Folding the generated PDF into it would make that warning disappear the moment a contract was
issued — i.e. report an unsigned draft as a signed contract.
"""
import base64

import pytest

import db


PDF = "data:application/pdf;base64," + base64.b64encode(b"%PDF-1.4 issued original").decode()
SCAN = "data:application/pdf;base64," + base64.b64encode(b"%PDF-1.4 countersigned scan").decode()


@pytest.fixture(autouse=True)
def _clean():
    def _wipe():
        conn = db.get_conn()
        conn.execute("DELETE FROM collections WHERE coll = 'contracts'")
        conn.commit()
        conn.close()
    _wipe()
    yield
    _wipe()


@pytest.fixture
def contract():
    """A contract for HML-STF, seeded through the store.

    Creation goes through /api/hr/contract so the Art. 20/21 checks run; these tests are about the
    document attached to a row, not about the writer, so they seed the row directly.
    """
    rec = {"id": "hd-file-1", "empId": "HML-STF", "empName": "Staff One",
           "no": "HD-2026-001", "type": "definite",
           "startDate": "2026-01-01", "endDate": "2026-12-31"}
    db.put_collection_item("contracts", rec)
    return rec


# ── storing it ───────────────────────────────────────────────────────────────────────────────────

def test_the_issued_original_is_stored_and_comes_back(api, tokens, contract):
    st, b = api("POST", "/api/hr/contract/file", tokens["admin"],
                {"contractId": contract["id"], "kind": "issued", "file": PDF,
                 "fileName": "HD-2026-001.pdf"})
    assert st == 200, b
    assert b["hasIssuedFile"] is True
    # The signed copy is a DIFFERENT document and has not arrived, so the register must still say so.
    assert b["hasFile"] is False

    st, b = api("GET", "/api/hr/contract/%s/file/issued" % contract["id"], tokens["admin"])
    assert st == 200
    assert b["file"] == PDF
    assert b["fileName"] == "HD-2026-001.pdf"


def test_the_signed_copy_does_not_displace_the_original(api, tokens, contract):
    api("POST", "/api/hr/contract/file", tokens["admin"],
        {"contractId": contract["id"], "kind": "issued", "file": PDF})
    st, b = api("POST", "/api/hr/contract/file", tokens["admin"],
                {"contractId": contract["id"], "kind": "signed", "file": SCAN})
    assert st == 200
    assert b["hasFile"] is True and b["hasIssuedFile"] is True

    # Both retrievable, each its own bytes. One field for both would have lost the original here.
    _, iss = api("GET", "/api/hr/contract/%s/file/issued" % contract["id"], tokens["admin"])
    _, sig = api("GET", "/api/hr/contract/%s/file/signed" % contract["id"], tokens["admin"])
    assert iss["file"] == PDF
    assert sig["file"] == SCAN


def test_a_kind_this_portal_does_not_know_is_refused_not_defaulted(api, tokens, contract):
    """Defaulting an unrecognised kind would file a signed contract as the generated draft, or the
    reverse — silently, and exactly where the distinction carries the legal weight."""
    st, b = api("POST", "/api/hr/contract/file", tokens["admin"],
                {"contractId": contract["id"], "kind": "final", "file": PDF})
    assert st == 400
    assert "issued original" in b.get("error", "")
    row = db.get_collection_item("contracts", contract["id"])
    assert not row.get("file") and not row.get("issuedFile")


@pytest.mark.parametrize("payload,why", [
    ("", "no document at all"),
    ("HD-2026-001.pdf", "a filename rather than bytes"),
    ("data:application/pdf;base64,", "a data URI carrying nothing"),
])
def test_it_refuses_anything_that_is_not_a_document(api, tokens, contract, payload, why):
    st, _ = api("POST", "/api/hr/contract/file", tokens["admin"],
                {"contractId": contract["id"], "kind": "signed", "file": payload})
    assert st == 400, why


def test_it_refuses_a_document_over_the_size_cap(api, tokens, contract):
    import app
    big = "data:application/pdf;base64," + base64.b64encode(b"x" * (app._INVTRACK_FILE_MAX + 1)).decode()
    st, _ = api("POST", "/api/hr/contract/file", tokens["admin"],
                {"contractId": contract["id"], "kind": "signed", "file": big})
    assert st == 400


def test_attaching_to_a_contract_that_does_not_exist_is_a_404(api, tokens):
    st, _ = api("POST", "/api/hr/contract/file", tokens["admin"],
                {"contractId": "hd-nope", "kind": "signed", "file": PDF})
    assert st == 404


# ── who may see it ───────────────────────────────────────────────────────────────────────────────

def test_a_person_may_read_their_own_contract(api, tokens, contract):
    """Art. 14(1) gives each party a copy of equal effect. An employee unable to retrieve their own
    contract is the defect, not the protection."""
    api("POST", "/api/hr/contract/file", tokens["admin"],
        {"contractId": contract["id"], "kind": "signed", "file": SCAN})
    st, b = api("GET", "/api/hr/contract/%s/file/signed" % contract["id"], tokens["staff"])
    assert st == 200
    assert b["file"] == SCAN


def test_another_employee_may_not(api, tokens, contract):
    """A labour contract states a wage."""
    api("POST", "/api/hr/contract/file", tokens["admin"],
        {"contractId": contract["id"], "kind": "signed", "file": SCAN})
    st, b = api("GET", "/api/hr/contract/%s/file/signed" % contract["id"], tokens["other"])
    assert st == 403
    assert SCAN not in str(b)


def test_a_contract_with_no_employee_is_nobody_s_own(api, tokens):
    """The self-check compares rec.empId with the caller's id. A row whose empId is missing must not
    match a caller whose id is missing — "" == "" would hand a stranger's contract to anyone."""
    db.put_collection_item("contracts", {"id": "hd-orphan", "empId": "", "file": SCAN,
                                         "fileName": "x.pdf"})
    st, _ = api("GET", "/api/hr/contract/hd-orphan/file/signed", tokens["staff"])
    assert st == 403


def test_staff_cannot_attach_a_contract_document(api, tokens, contract):
    st, _ = api("POST", "/api/hr/contract/file", tokens["staff"],
                {"contractId": contract["id"], "kind": "signed", "file": SCAN})
    assert st == 403
    assert not db.get_collection_item("contracts", contract["id"]).get("file")


def test_a_manager_is_not_senior_enough_to_attach(api, tokens, contract):
    """Same bar as issuing one — management and above."""
    st, _ = api("POST", "/api/hr/contract/file", tokens["mgr"],
                {"contractId": contract["id"], "kind": "signed", "file": SCAN})
    assert st == 403


def test_asking_for_a_kind_that_was_never_attached_is_a_404_not_an_empty_success(api, tokens, contract):
    api("POST", "/api/hr/contract/file", tokens["admin"],
        {"contractId": contract["id"], "kind": "issued", "file": PDF})
    st, _ = api("GET", "/api/hr/contract/%s/file/signed" % contract["id"], tokens["admin"])
    assert st == 404


# ── the list must not carry the bytes ────────────────────────────────────────────────────────────

def test_the_register_list_ships_metadata_not_megabytes(api, tokens, contract):
    """One render of the register would otherwise ship every employee's contract — each stating their
    wage — to whoever loaded the page."""
    api("POST", "/api/hr/contract/file", tokens["admin"],
        {"contractId": contract["id"], "kind": "issued", "file": PDF})
    api("POST", "/api/hr/contract/file", tokens["admin"],
        {"contractId": contract["id"], "kind": "signed", "file": SCAN})

    st, b = api("GET", "/api/coll/contracts", tokens["admin"])
    assert st == 200
    row = next(r for r in b["items"] if r["id"] == contract["id"])
    assert row["file"] == "" and row["issuedFile"] == ""
    assert row["hasFile"] is True and row["hasIssuedFile"] is True
    assert PDF not in str(b) and SCAN not in str(b)


def test_the_review_endpoint_reports_both_kinds_without_the_bytes(api, tokens, contract):
    api("POST", "/api/hr/contract/file", tokens["admin"],
        {"contractId": contract["id"], "kind": "issued", "file": PDF})
    st, b = api("GET", "/api/hr/contracts/review", tokens["admin"])
    assert st == 200
    row = next(r for r in b["rows"] if r["empId"] == "HML-STF")
    assert row["hasIssuedFile"] is True
    assert row["hasFile"] is False        # no signed copy yet — the warning must still stand
    assert PDF not in str(b)


# ── the edit path must not destroy it ────────────────────────────────────────────────────────────

def _round_trip(api, tokens, cid):
    """The row exactly as a browser holds it: fetched from the list, so document bytes are blanked
    and the derived flags are present. This is the shape every real edit is made from."""
    _, listed = api("GET", "/api/coll/contracts", tokens["admin"])
    return next(r for r in listed["items"] if r["id"] == cid)


def test_a_permitted_edit_survives_the_round_trip_without_erasing_the_document(api, tokens, contract):
    """The list blanks the byte fields and adds hasFile/hasIssuedFile, so a row that merely made the
    trip browser→server differs from the stored row in three keys nobody edited. ISSUED_ONLY compares
    body against record, so before this was reconciled it read those as an attempt to rewrite an
    issued contract and refused EVERY edit with 400 — including the ones the allow-list exists to
    permit. And a blind whole-document replace would have written the blanks back."""
    api("POST", "/api/hr/contract/file", tokens["admin"],
        {"contractId": contract["id"], "kind": "issued", "file": PDF})
    api("POST", "/api/hr/contract/file", tokens["admin"],
        {"contractId": contract["id"], "kind": "signed", "file": SCAN})

    row = _round_trip(api, tokens, contract["id"])
    assert row["issuedFile"] == "" and row["hasIssuedFile"] is True      # the shape that used to 400
    row["status"] = "Active"                                             # an edit the allow-list permits
    row["signedAt"] = "2026-01-05"
    st, _ = api("PATCH", "/api/coll/contracts/" + contract["id"], tokens["admin"], row)
    assert st == 200

    stored = db.get_collection_item("contracts", contract["id"])
    assert stored["status"] == "Active" and stored["signedAt"] == "2026-01-05"
    assert stored["issuedFile"] == PDF                                   # the document is still there
    assert stored["file"] == SCAN


def test_what_was_agreed_still_cannot_be_rewritten(api, tokens, contract):
    """Reconciling the round trip must not have loosened the lock: the wage, the term and the
    contract number are what was AGREED. Changing one is an annex or a new contract, not an edit."""
    api("POST", "/api/hr/contract/file", tokens["admin"],
        {"contractId": contract["id"], "kind": "issued", "file": PDF})
    row = _round_trip(api, tokens, contract["id"])
    row["no"] = "HD-2026-001-REV2"
    st, b = api("PATCH", "/api/coll/contracts/" + contract["id"], tokens["admin"], row)
    assert st == 400
    assert "no" in b.get("error", "")
    assert db.get_collection_item("contracts", contract["id"])["no"] == "HD-2026-001"


def test_an_edit_cannot_reassign_who_issued_the_contract(api, tokens, contract):
    """Who issued it and when is a fact about the past; an editor recording the signing date is not
    the issuer, and must not become one by the body simply omitting those keys."""
    rec = db.get_collection_item("contracts", contract["id"])
    rec.update({"issuedBy": "Admin User", "issuedById": "HML-ADM", "issuedAt": "2026-01-01T00:00:00Z"})
    db.put_collection_item("contracts", rec)

    row = _round_trip(api, tokens, contract["id"])
    for k in ("issuedBy", "issuedById", "issuedAt"):
        row.pop(k, None)                                 # the browser drops what it does not show
    row["status"] = "Active"
    st, _ = api("PATCH", "/api/coll/contracts/" + contract["id"], tokens["management"], row)
    assert st == 200
    stored = db.get_collection_item("contracts", contract["id"])
    assert stored["issuedBy"] == "Admin User"
    assert stored["issuedById"] == "HML-ADM"
    assert stored["issuedAt"] == "2026-01-01T00:00:00Z"


def test_the_derived_flags_are_never_written_back(api, tokens, contract):
    """hasFile / hasIssuedFile are computed on read. Persisting them would let a row claim a document
    it does not have, and the register would offer to open nothing."""
    api("POST", "/api/hr/contract/file", tokens["admin"],
        {"contractId": contract["id"], "kind": "signed", "file": SCAN})
    row = _round_trip(api, tokens, contract["id"])
    assert row["hasFile"] is True                        # present in what the browser sends back
    st, _ = api("PATCH", "/api/coll/contracts/" + contract["id"], tokens["admin"], row)
    assert st == 200
    stored = db.get_collection_item("contracts", contract["id"])
    assert "hasFile" not in stored and "hasIssuedFile" not in stored


# ── it is written down ───────────────────────────────────────────────────────────────────────────

def test_attaching_a_signed_contract_is_audited(api, tokens, contract):
    api("POST", "/api/hr/contract/file", tokens["admin"],
        {"contractId": contract["id"], "kind": "signed", "file": SCAN})
    entries = [a for a in db.list_collection("audit")
               if a.get("target") == "contracts/" + contract["id"]]
    assert any("Signed labour contract attached" in (a.get("action") or "") for a in entries)


def test_sharepoint_being_unavailable_does_not_lose_the_contract(api, tokens, contract):
    """SharePoint is where the rest of the person's file lives, but it is not the store of record.
    In this harness M365 is not configured, so _hrsp_put raises — and the contract must still be
    attached, with the response saying which part did not happen rather than reporting success."""
    st, b = api("POST", "/api/hr/contract/file", tokens["admin"],
                {"contractId": contract["id"], "kind": "signed", "file": SCAN})
    assert st == 200
    assert b["filed"] is False
    assert b["error"]                                    # says why, rather than silently claiming success
    assert db.get_collection_item("contracts", contract["id"])["file"] == SCAN
