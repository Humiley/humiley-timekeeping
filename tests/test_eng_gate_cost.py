"""Signing a gate must not get slower the more the commission has recorded.

`_eng_appr_check` filters eng_holds, eng_deviations and eng_risks to the commission before deciding
whether a gate can be passed clean. It did that with `self._eng_project_of(x) == proj` inside three
list comprehensions — and `_eng_project_of` does a full `list_collection("eng_projects")` scan on
every call. So the number of full table reads grew with the number of rows in those registers.

Measured before the fix, on one gate signature:

    eng_projects reads:   7  with 2 rows in each register
                         67  with 20

which is the same shape that took the AHU production board to four seconds at 87 units. A
commission carries hundreds of holds, deviations and risks by the time it reaches a gate, and the
gate is the moment somebody is waiting on a signature.

COUNTS READS, NOT SECONDS. A timing assertion passes on an idle runner while the quadratic is still
there — 67 tiny reads take no measurable time on a laptop with an empty database, which is exactly
why this went unnoticed. The number of reads is the thing that scales, so the number of reads is
what is asserted.
"""
import pytest

import app
import db


@pytest.fixture(autouse=True)
def _demo(monkeypatch):
    monkeypatch.setattr(app, "DEMO_MODE", True)


def _mk(api, token, coll, body):
    st, b = api("POST", "/api/coll/" + coll, token, body)
    assert st == 200, b
    return b["item"]


def _reads_signing_a_gate(api, tokens, n_rows, tag):
    """Sign one gate on a commission carrying n_rows in each of three registers; count the
    collection reads that happen while the signature is processed."""
    proj = _mk(api, tokens["admin"], "eng_projects", {
        "name": "Gate cost %s" % tag, "code": "GC%s" % tag, "client": "C",
        "designManager": "Dept Manager", "leadEngineer": "Staff One",
        "status": "Active", "currentStage": "Detail", "members": "Staff One"})
    for i in range(n_rows):
        _mk(api, tokens["staff"], "eng_holds", {
            "projectId": proj["id"], "kind": "hold", "ref": "H%d" % i,
            "title": "closed", "status": "Closed"})
        _mk(api, tokens["staff"], "eng_deviations", {
            "projectId": proj["id"], "ref": "D%d" % i, "title": "x"})
        _mk(api, tokens["staff"], "eng_risks", {
            "projectId": proj["id"], "ref": "R%d" % i, "hazard": "x", "status": "Controlled"})
    gate = _mk(api, tokens["staff"], "eng_stages", {
        "projectId": proj["id"], "stage": "Detail", "status": "At gate"})

    calls = {}
    real = db.list_collection

    def counted(name, *a, **k):
        calls[name] = calls.get(name, 0) + 1
        return real(name, *a, **k)

    # Restored by hand rather than with monkeypatch.undo(), which reverts EVERY patch on the
    # fixture — including the autouse DEMO_MODE one, after which the next signature fails with
    # "not a valid signed token" and the measurement looks like a permissions bug.
    db.list_collection = counted
    try:
        st, b = api("POST", "/api/esign", tokens["staff"], {
            "coll": "eng_stages", "id": gate["id"], "meaning": "gate cost", "setStatus": "Passed"})
    finally:
        db.list_collection = real
    # Passed or refused is immaterial — the filtering runs either way, and that is what is counted.
    assert st in (200, 403), b
    return calls


def test_the_gate_check_does_not_reread_the_commission_per_row(api, tokens):
    """The whole point. Twenty rows in each register must not cost thirty times what two do."""
    small = _reads_signing_a_gate(api, tokens, 2, "S")
    big = _reads_signing_a_gate(api, tokens, 20, "B")
    grew = big.get("eng_projects", 0) - small.get("eng_projects", 0)
    assert grew <= 2, (
        "eng_projects was read %d times for a commission with 2 rows in each register and %d times "
        "for one with 20 — the gate check is re-reading the commission per row. Filter by "
        "projectId; do not call _eng_project_of inside the comprehension."
        % (small.get("eng_projects", 0), big.get("eng_projects", 0)))


def test_the_whole_signature_stays_bounded(api, tokens):
    """Not just eng_projects. Any per-row read anywhere on this path shows up here."""
    small = sum(_reads_signing_a_gate(api, tokens, 2, "S2").values())
    big = sum(_reads_signing_a_gate(api, tokens, 20, "B2").values())
    assert big - small <= 4, (
        "signing one gate cost %d collection reads at 2 rows and %d at 20 — something on this path "
        "scales with the register size" % (small, big))


def test_the_rule_still_refuses_what_it_refused(api, tokens):
    """A faster check that stopped checking would be a much worse bug than a slow one. The three
    blockers are re-asserted here so the optimisation cannot quietly delete the rule."""
    proj = _mk(api, tokens["admin"], "eng_projects", {
        "name": "Gate cost rule", "code": "GCR26", "client": "C",
        "designManager": "Dept Manager", "leadEngineer": "Staff One",
        "status": "Active", "currentStage": "Detail", "members": "Staff One"})
    _mk(api, tokens["staff"], "eng_holds", {
        "projectId": proj["id"], "kind": "hold", "ref": "H-COST", "title": "open",
        "status": "open"})
    gate = _mk(api, tokens["staff"], "eng_stages", {
        "projectId": proj["id"], "stage": "Detail", "status": "At gate"})
    st, b = api("POST", "/api/esign", tokens["staff"], {
        "coll": "eng_stages", "id": gate["id"], "meaning": "x", "setStatus": "Passed"})
    assert st != 200, "the open hold no longer blocks a clean pass"
    assert "H-COST" in str(b), "and it still names what is in the way"


def test_another_commissions_rows_never_block_this_gate(api, tokens):
    """The scoping the id comparison replaced. Getting this wrong in the other direction — matching
    too much — would block a gate on somebody else's open hold, which is worse than slow."""
    mine = _mk(api, tokens["admin"], "eng_projects", {
        "name": "Mine", "code": "GCM26", "client": "C", "designManager": "Dept Manager",
        "leadEngineer": "Staff One", "status": "Active", "currentStage": "Detail",
        "members": "Staff One"})
    theirs = _mk(api, tokens["admin"], "eng_projects", {
        "name": "Theirs", "code": "GCT26", "client": "C2", "designManager": "Dept Manager",
        "leadEngineer": "Staff One", "status": "Active", "currentStage": "Detail",
        "members": "Staff One"})
    _mk(api, tokens["staff"], "eng_holds", {
        "projectId": theirs["id"], "kind": "hold", "ref": "H-THEIRS", "title": "open",
        "status": "open"})
    gate = _mk(api, tokens["staff"], "eng_stages", {
        "projectId": mine["id"], "stage": "Detail", "status": "At gate"})
    st, b = api("POST", "/api/esign", tokens["staff"], {
        "coll": "eng_stages", "id": gate["id"], "meaning": "x", "setStatus": "Passed"})
    assert st == 200, "another commission's open hold blocked this gate: %s" % (b,)


def test_a_row_with_no_commission_blocks_nothing(api, tokens):
    """An orphan row — imported, or left by a deleted commission — must not stop every gate in the
    office. The old dict comparison would have matched it against an empty project record."""
    _mk(api, tokens["staff"], "eng_holds", {
        "kind": "hold", "ref": "H-ORPHAN", "title": "open", "status": "open"})
    proj = _mk(api, tokens["admin"], "eng_projects", {
        "name": "Orphan probe", "code": "GCO26", "client": "C", "designManager": "Dept Manager",
        "leadEngineer": "Staff One", "status": "Active", "currentStage": "Detail",
        "members": "Staff One"})
    gate = _mk(api, tokens["staff"], "eng_stages", {
        "projectId": proj["id"], "stage": "Detail", "status": "At gate"})
    st, b = api("POST", "/api/esign", tokens["staff"], {
        "coll": "eng_stages", "id": gate["id"], "meaning": "x", "setStatus": "Passed"})
    assert st == 200, "a hold belonging to no commission blocked a gate: %s" % (b,)
