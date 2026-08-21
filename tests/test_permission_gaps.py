"""Three gates that were open, and one that could not fire.

Every test here fails if its fix is reverted — that is the only property that makes a permission
test worth having. A gate is asserted in BOTH directions: refusing the wrong caller proves nothing
if it also refuses the right one, and a check nobody can trip is the shape this codebase keeps
producing (see tests/test_api.py::test_hr_app_grant_is_what_opens_hr for the last one).
"""
import db


# ─── the subcontract register is project money ──────────────────────────────────────────────────
def test_a_staff_account_cannot_read_the_subcontract_register(api, tokens):
    """pm_procurement carries the vendor name and the committed contract value of every subcontract.

    READ_MIN raised pm_costs and pm_procurement_payments to manager so project financials would stop
    being world-readable, and left pm_procurement out — so the payment CERTIFICATE was protected and
    the contract it certifies against was served in full to every staff account with the Projects
    app, which is on by default.
    """
    st, _ = api("GET", "/api/coll/pm_procurement", tokens["staff"])
    assert st == 403, "the subcontract register must not be readable by every staff account"


def test_a_manager_still_runs_the_subcontract_register(api, tokens):
    st, r = api("GET", "/api/coll/pm_procurement", tokens["mgr"])
    assert st == 200, "manager-and-above is who awards packages — the gate must not shut them out"
    assert isinstance(r.get("items"), list)


def test_the_gate_matches_the_one_on_payments_against_it(api, tokens):
    """The package and the certificates drawn against it are the same commercial fact; they must not
    sit at two different access levels, or the lower one is the real one."""
    a, _ = api("GET", "/api/coll/pm_procurement", tokens["staff"])
    b, _ = api("GET", "/api/coll/pm_procurement_payments", tokens["staff"])
    assert a == b == 403


# ─── a signature is written once ────────────────────────────────────────────────────────────────
def _an_ack(api, tokens):
    """A real signature: a published document that HAS a file, signed by the staff fixture through
    the same route the browser uses. Identity, time and version are stamped by the server."""
    db.put_collection_item("hrdocs", {
        "id": "DOC-PERM-1", "title": "Code of Conduct", "code": "HML-POL-001",
        "version": "1.0", "audience": "All", "file": "data:application/pdf;base64,JVBERi0="})
    st, r = api("POST", "/api/coll/hrdoc_acks", tokens["staff"],
                {"docId": "DOC-PERM-1", "grade": "standard"})
    assert st == 200, r
    return r["item"]["id"]


def test_a_signed_acknowledgement_cannot_be_rewritten(api, tokens):
    """DELETE already refused, on the reasoning that this row is the artefact an inspector asks for.
    PATCH did not — and PATCH on this route REPLACES the whole document, so any account whose
    employee role is "manager" could rewrite the signer's name, the version acknowledged and the
    time it was signed, with no owner check and no audit row."""
    aid = _an_ack(api, tokens)
    st, _ = api("PATCH", "/api/coll/hrdoc_acks/" + aid, tokens["mgr"],
                {"docId": "DOC-PERM-1", "empId": "HML-OTH", "name": "Other Staff",
                 "version": "9.9", "signedAt": "1999-01-01T00:00:00Z"})
    assert st == 403, "a signature that a third party can rewrite is not evidence of anything"

    row = db.get_collection_item("hrdoc_acks", aid)
    assert row["empId"] == "HML-STF", "the stored signature must be untouched, not merely refused"
    assert row["name"] == "Staff One"
    assert row["docVersion"] == "1.0"


def test_not_even_an_admin_edits_a_signature(api, tokens):
    """Level is not the question. A signed acknowledgement is append-only for everyone; re-issuing
    the document at a new version is the way to ask for it again."""
    aid = _an_ack(api, tokens)
    st, _ = api("PATCH", "/api/coll/hrdoc_acks/" + aid, tokens["admin"], {"docVersion": "9.9"})
    assert st == 403
    assert db.get_collection_item("hrdoc_acks", aid)["docVersion"] == "1.0"


def test_signing_still_works(api, tokens):
    """The refusal must be on the EDIT, not on the feature. If this fails the guard is too wide and
    nobody can sign anything."""
    aid = _an_ack(api, tokens)
    assert db.get_collection_item("hrdoc_acks", aid) is not None
    st, r = api("GET", "/api/coll/hrdoc_acks", tokens["staff"])
    assert st == 200 and any(a["id"] == aid for a in r["items"]), \
        "the signer must still be able to see their own signature"


# ─── an opt-in app you were never given still leaves your own records reachable ─────────────────
def test_your_own_contract_survives_the_hr_gate(api, tokens):
    """Art. 13(1) entitles the employee to a copy of their own labour contract. The HR app gate runs
    before READ_MIN, so closing it naively would have taken their own contract away from them along
    with everybody else's — a portal that holds your contract and will not show it to you is worse
    than one that never held it."""
    db.put_collection_item("contracts", {
        "id": "CT-PERM-1", "empId": "HML-STF", "type": "definite",
        "startDate": "2026-01-01", "endDate": "2026-12-31", "wage": 20000000})
    db.put_collection_item("contracts", {
        "id": "CT-PERM-2", "empId": "HML-OTH", "type": "definite",
        "startDate": "2026-01-01", "endDate": "2026-12-31", "wage": 99000000})
    try:
        st, r = api("GET", "/api/coll/contracts", tokens["staff"])
        assert st == 200, "your own contract must still reach you"
        ids = {c["id"] for c in r["items"]}
        assert "CT-PERM-1" in ids, "your own contract must be in what comes back"
        assert "CT-PERM-2" not in ids, \
            "somebody else's contract states their wage and must not be in it"
        # Stated as a property of every row rather than an exact id set: other tests in the suite
        # also leave contracts behind, and an exact set would fail on their leftovers instead of on
        # the thing under test.
        assert all(c.get("empId") == "HML-STF" for c in r["items"]), \
            "the self-scoped branch must return the caller's rows and nobody else's"
    finally:
        db.delete_collection_item("contracts", "CT-PERM-1")
        db.delete_collection_item("contracts", "CT-PERM-2")
