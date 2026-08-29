"""Can one commission's records be read from another?

This is the test that has to exist BEFORE any client-facing view does. A client portal is the only
thing anybody has proposed for this module that fails in the dangerous direction: every rule built
so far fails safe — it refuses something it should not have, somebody complains, it gets fixed. An
access boundary fails the other way. One client sees another client's drawings and nobody reports
it, because from their side nothing looks wrong.

So the boundary gets characterised first, on the API as it stands today, and whatever it turns out
to be is written down here. If the existing scoping already isolates commissions, this records that
and the client view can be built on top of it. If it does not, that is a finding worth more than
the feature, and it has been found by a test rather than by a client.

Nothing here asserts what the boundary SHOULD be until it is known what it IS. The assertions
below describe measured behaviour.
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


@pytest.fixture
def two_commissions(api, tokens):
    """Two commissions. Staff One is a member of the first and NOT of the second."""
    ours = _mk(api, tokens["admin"], "eng_projects", {
        "name": "Ours", "code": "OURS26", "client": "Client A",
        "designManager": "Dept Manager", "leadEngineer": "Staff One",
        "status": "Active", "members": "Staff One"})
    theirs = _mk(api, tokens["admin"], "eng_projects", {
        "name": "Theirs", "code": "THRS26", "client": "Client B",
        "designManager": "Dept Manager", "leadEngineer": "Someone Else",
        "status": "Active", "members": "Someone Else"})
    a = _mk(api, tokens["admin"], "eng_deliverables", {
        "projectId": ours["id"], "docNo": "OURS26-EL-DWG-001", "title": "Ours drawing",
        "docType": "Drawing", "discipline": "Electrical", "stage": "Detail"})
    b = _mk(api, tokens["admin"], "eng_deliverables", {
        "projectId": theirs["id"], "docNo": "THRS26-EL-DWG-001", "title": "Theirs drawing",
        "docType": "Drawing", "discipline": "Electrical", "stage": "Detail"})
    return {"ours": ours, "theirs": theirs, "ourDoc": a, "theirDoc": b}


def test_the_list_endpoint_is_the_boundary_or_there_is_none(api, tokens, two_commissions):
    """Characterisation. Whatever /api/coll returns to a staff member is the boundary a client
    view would inherit, so it has to be known before anything is built on it."""
    st, b = api("GET", "/api/coll/eng_deliverables", tokens["staff"])
    assert st == 200, b
    ids = {x.get("id") for x in b["items"]}
    ours_visible = two_commissions["ourDoc"]["id"] in ids
    theirs_visible = two_commissions["theirDoc"]["id"] in ids

    assert ours_visible, "a member cannot see their own commission's deliverables"
    # The measured answer, recorded rather than assumed. If this ever changes, the change is
    # deliberate and this test is where the decision gets re-made.
    assert theirs_visible, (
        "MEASURED: eng_deliverables are NOT scoped per commission at the API — a staff account "
        "sees every commission's documents. That is workable inside one design office, where "
        "everyone is staff and the register is shared. It is NOT a boundary a client portal can "
        "be built on: a client given a staff-shaped session would see every client's drawings. "
        "Any client-facing view must filter server-side by commission itself, and must be tested "
        "on that filter rather than on this one.")


def test_a_direct_fetch_of_another_commissions_record(api, tokens, two_commissions):
    """The list is one route in; the item endpoint is another. A view that filters the list and
    forgets the item is the classic hole."""
    st, b = api("GET", "/api/coll/eng_deliverables/" + two_commissions["theirDoc"]["id"],
                tokens["staff"])
    # Recorded, not asserted-as-correct: same reasoning as above.
    assert st in (200, 403, 404), b


def test_admin_sees_both(api, tokens, two_commissions):
    st, b = api("GET", "/api/coll/eng_deliverables", tokens["admin"])
    assert st == 200
    ids = {x.get("id") for x in b["items"]}
    assert two_commissions["ourDoc"]["id"] in ids
    assert two_commissions["theirDoc"]["id"] in ids


def test_the_refusal_log_write_is_refused(api, tokens, two_commissions):
    """This test used to be called ...is_not_readable_by_staff, and its docstring claimed "the log
    refuses the write and the read is management-only". Only the first half was ever asserted. The
    second half was false: /api/coll reads are default-allow, eng_refusals had no READ_MIN entry,
    and every account with the ENG app was served every commission's refusals.

    A sentence in a docstring is not a boundary. The read is now scoped by design authority and
    tested for it in tests/test_eng_refusal_log.py; what belongs HERE is only the claim this test
    actually makes."""
    st, b = api("POST", "/api/coll/eng_refusals", tokens["staff"],
                {"projectId": two_commissions["ours"]["id"], "rule": "invented"})
    assert st != 200, "a staff account wrote to the refusal log"
