"""Signed design records are kept for ten years after the COMMISSION closes.

Construction liability in Vietnam runs long past handover, and the document that answers "who
checked this, against which edition, and what did they know at the time" is the signed record in
these registers. Nothing stopped one being deleted — not by a mistake, but by somebody tidying up
years later who no longer remembers why it was kept.

The clock runs from the commission's close date, not from the signature on the individual record.
A drawing signed in year one of a four-year job would otherwise fall out of retention while the
project it belongs to is still being argued about — and these records only answer the question as a
set: the drawing, the check, the deviation that permitted it, the gate that accepted it.

A commission with no close date recorded protects its records with no end in sight. That is right —
the work is live — and it gives somebody a reason to record the close date, because until they do
the clock never starts.

The rule is deliberately narrow. Only a SIGNED record is protected: a commission set up wrong, a
duplicate, a test row — none of those carry a signature, and refusing to delete them would train
people to route around the guard on the records that matter. The signature is what turns a row into
evidence, so the signature is what starts the clock.

There is no admin exemption, and that is the point rather than an oversight. An admin is exactly
who gets asked to "just remove it". Everywhere else in this codebase an admin steps over a freeze,
because a freeze stops accidents; this one stops a decision.
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
        "name": "Retention commission", "code": "RET26", "client": "A Client",
        "designManager": "Dept Manager", "leadEngineer": "Staff One",
        "status": "Active", "currentStage": "Detail", "members": "Staff One"})


def _signed_gate(api, tokens, commission):
    g = _mk(api, tokens["staff"], "eng_stages", {
        "projectId": commission["id"], "stage": "Detail", "status": "At gate"})
    st, b = _sign(api, tokens["staff"], "eng_stages", g["id"], "Passed")
    assert st == 200, b
    return b["item"]


def test_an_unsigned_record_deletes_freely(api, tokens, commission):
    """Mistakes, duplicates and test rows must still clear, or the guard gets routed around."""
    g = _mk(api, tokens["staff"], "eng_stages", {
        "projectId": commission["id"], "stage": "Concept", "status": "Open"})
    st, b = api("DELETE", "/api/coll/eng_stages/" + g["id"], tokens["admin"])
    assert st == 200, b


def test_a_signed_record_is_kept(api, tokens, commission):
    g = _signed_gate(api, tokens, commission)
    st, b = api("DELETE", "/api/coll/eng_stages/" + g["id"], tokens["staff"])
    assert st != 200, "a signed gate was deleted"
    assert "10 years" in str(b) or "ten years" in str(b).lower()


def test_an_admin_cannot_delete_it_either(api, tokens, commission):
    """An admin is exactly who gets asked to 'just remove it'."""
    g = _signed_gate(api, tokens, commission)
    st, b = api("DELETE", "/api/coll/eng_stages/" + g["id"], tokens["admin"])
    assert st != 200, "an admin deleted a signed design record"


def test_the_refusal_says_what_to_do_instead(api, tokens, commission):
    """A guard with no way forward is a guard people learn to hate."""
    g = _signed_gate(api, tokens, commission)
    st, b = api("DELETE", "/api/coll/eng_stages/" + g["id"], tokens["admin"])
    assert "supersede" in str(b).lower() or "void" in str(b).lower()


def test_a_signed_revision_is_kept(api, tokens, commission):
    d = _mk(api, tokens["staff"], "eng_deliverables", {
        "projectId": commission["id"], "docNo": "RET26-EL-DWG-001", "title": "SLD",
        "docType": "Drawing", "discipline": "Electrical", "stage": "Detail",
        "preparedBy": "Alice Engineer", "approver": "Staff One"})
    rev = _mk(api, tokens["staff"], "eng_revisions", {
        "projectId": commission["id"], "deliverableId": d["id"], "rev": "C01",
        "issueStatus": "IFC", "reasonForIssue": "issue", "preparedBy": "Alice Engineer",
        "checkedBy": "Carol Checker", "status": "Draft"})
    st, _ = _sign(api, tokens["staff"], "eng_revisions", rev["id"], "Issued")
    assert st == 200
    st, b = api("DELETE", "/api/coll/eng_revisions/" + rev["id"], tokens["admin"])
    assert st != 200, "an issued drawing revision was deleted"


def test_a_commission_closed_long_ago_releases_its_records(api, tokens, commission):
    """The clock does run out. Ten years after close, the record can be cleared."""
    g = _signed_gate(api, tokens, commission)
    commission["closedOn"] = "2005-01-01"
    st, _ = api("PATCH", "/api/coll/eng_projects/" + commission["id"], tokens["admin"], commission)
    assert st == 200
    st, b = api("DELETE", "/api/coll/eng_stages/" + g["id"], tokens["admin"])
    assert st == 200, b


def test_an_open_commission_protects_everything_it_holds(api, tokens, commission):
    """No close date means the clock has not started, and the refusal says so."""
    g = _signed_gate(api, tokens, commission)
    st, b = api("DELETE", "/api/coll/eng_stages/" + g["id"], tokens["admin"])
    assert st != 200
    assert "close date" in str(b).lower() or "closes" in str(b).lower()


def test_the_commission_can_set_its_own_period(api, tokens, commission):
    """Ten years is the default, not a law of nature — a contract may require longer."""
    commission["retentionYears"] = "20"
    commission["closedOn"] = "2020-06-30"
    st, _ = api("PATCH", "/api/coll/eng_projects/" + commission["id"], tokens["admin"], commission)
    assert st == 200
    g = _signed_gate(api, tokens, commission)
    st, b = api("DELETE", "/api/coll/eng_stages/" + g["id"], tokens["admin"])
    assert st != 200
    assert "20 years" in str(b), "the refusal should quote the period actually in force"


def test_a_record_in_another_collection_is_untouched(api, tokens, commission):
    """The guard is about eng_ design records, not about everything anybody signed."""
    st, b = api("GET", "/api/coll/eng_projects", tokens["admin"])
    assert st == 200


# ── the clock has to start by itself ────────────────────────────────────────────

def test_closing_a_commission_stamps_the_date(api, tokens, commission):
    """Nothing started the clock before this. A date somebody has to remember to type is a
    retention policy that protects finished work for ever — the same state as work that closed
    yesterday, which is an absence of a policy wearing the right words."""
    assert not commission.get("closedOn")
    commission["status"] = "Completed"
    st, b = api("PATCH", "/api/coll/eng_projects/" + commission["id"], tokens["admin"], commission)
    assert st == 200, b
    assert b["item"]["closedOn"], "closing the commission did not start the clock"


def test_a_hand_entered_close_date_is_not_overwritten(api, tokens, commission):
    """A commission closed in the past and recorded later. The typed date is the true one."""
    commission["status"] = "Closed"
    commission["closedOn"] = "2024-03-15"
    st, b = api("PATCH", "/api/coll/eng_projects/" + commission["id"], tokens["admin"], commission)
    assert st == 200, b
    assert b["item"]["closedOn"] == "2024-03-15"


def test_a_later_edit_does_not_move_the_expiry(api, tokens, commission):
    """Re-stamping on every save would quietly push the expiry out each time somebody edited a
    commission that had been closed for years."""
    commission["status"] = "Closed"
    commission["closedOn"] = "2015-01-01"
    st, b = api("PATCH", "/api/coll/eng_projects/" + commission["id"], tokens["admin"], commission)
    assert st == 200
    item = b["item"]
    item["client"] = "A Client, renamed"
    st, b2 = api("PATCH", "/api/coll/eng_projects/" + commission["id"], tokens["admin"], item)
    assert st == 200
    assert b2["item"]["closedOn"] == "2015-01-01", "an ordinary edit moved the retention expiry"


def test_reopening_and_closing_again_keeps_the_first_date(api, tokens, commission):
    """A commission closed, reopened for a snag, and closed again. The retention clock belongs to
    the first close — the records were complete then."""
    commission["status"] = "Closed"
    st, b = api("PATCH", "/api/coll/eng_projects/" + commission["id"], tokens["admin"], commission)
    assert st == 200
    first = b["item"]["closedOn"]
    assert first
    item = b["item"]; item["status"] = "Active"
    st, b2 = api("PATCH", "/api/coll/eng_projects/" + commission["id"], tokens["admin"], item)
    assert st == 200
    item = b2["item"]; item["status"] = "Closed"
    st, b3 = api("PATCH", "/api/coll/eng_projects/" + commission["id"], tokens["admin"], item)
    assert st == 200
    assert b3["item"]["closedOn"] == first
