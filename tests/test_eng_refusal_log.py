"""Counting the rules, so they can be judged on real work rather than on the tests that wrote them.

Nine rules went into this module in a fortnight, verified against tests I wrote and never against
an engineer trying to issue a drawing on a Friday. That asymmetry is the risk: a control that stops
the wrong thing does not get fixed, it gets routed around — people stop recording the gate, leave
the hold out of the register, mark everything commission-wide — and then the register looks
populated while meaning nothing.

So every refusal is recorded: which rule, on what, attempted by whom. Two properties matter more
than the count.

The log must be SERVER-WRITTEN. It is evidence about people, and a browser that could write it
could delete the record of having been stopped.

And it must never change the outcome. A refusal that fails to log is still a refusal; a refusal
that succeeds because logging threw would be the worst bug this module could have.
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


def _log(api, token):
    st, b = api("GET", "/api/coll/eng_refusals", token)
    assert st == 200, b
    return b["items"]


@pytest.fixture
def commission(api, tokens):
    return _mk(api, tokens["admin"], "eng_projects", {
        "name": "Refusal log commission", "code": "LOG26", "client": "A Client",
        "designManager": "Dept Manager", "leadEngineer": "Staff One",
        "status": "Active", "currentStage": "Detail", "members": "Staff One"})


def test_a_refused_signature_is_recorded(api, tokens, commission):
    before = len(_log(api, tokens["admin"]))
    _mk(api, tokens["staff"], "eng_holds", {
        "projectId": commission["id"], "kind": "hold", "ref": "H-301",
        "title": "Open", "status": "open"})
    g = _mk(api, tokens["staff"], "eng_stages", {
        "projectId": commission["id"], "stage": "Detail", "status": "At gate"})
    st, _ = _sign(api, tokens["staff"], "eng_stages", g["id"], "Passed")
    assert st != 200

    rows = _log(api, tokens["admin"])
    assert len(rows) == before + 1, "the refusal was not recorded"
    # Select the row by what it is about, not by position: the collection is shared across tests
    # and "the last one" is only mine by luck.
    r = [x for x in rows if x.get("recordId") == g["id"]][0]
    assert r["coll"] == "eng_stages"
    assert r["attempted"] == "Passed"
    assert r["who"] == "Staff One", "the log names who was stopped"
    assert r["rule"], "the rule is identified"
    assert "H-301" in r["message"], "the message that was shown is kept"


def test_a_successful_signature_is_not_recorded(api, tokens, commission):
    """Only refusals. A log of everything is a log nobody reads."""
    before = len(_log(api, tokens["admin"]))
    g = _mk(api, tokens["staff"], "eng_stages", {
        "projectId": commission["id"], "stage": "Detail", "status": "At gate"})
    st, _ = _sign(api, tokens["staff"], "eng_stages", g["id"], "Passed")
    assert st == 200
    assert len(_log(api, tokens["admin"])) == before


def test_the_write_path_refusals_are_recorded_too(api, tokens, commission):
    """Two of the nine live on the write path. Missing them would make the tally quietly partial —
    and they are the two most likely to be argued with."""
    before = len(_log(api, tokens["admin"]))
    std = _mk(api, tokens["staff"], "eng_standards", {
        "projectId": commission["id"], "code": "TCVN 5687", "edition": "2010",
        "obligation": "Statutory", "status": "Adopted"})
    std["edition"] = "2024"
    st, _ = api("PATCH", "/api/coll/eng_standards/" + std["id"], tokens["staff"], std)
    assert st != 200

    rows = _log(api, tokens["admin"])
    assert len(rows) == before + 1
    r = [x for x in rows if x.get("recordId") == std["id"]][0]
    assert r["coll"] == "eng_standards"
    assert r["source"] == "write", "the write path is distinguishable from the sign path"


def test_the_log_cannot_be_written_from_a_browser(api, tokens, commission):
    """It is evidence about people. A browser that could add to it could also add noise to bury
    the entry about itself."""
    st, b = api("POST", "/api/coll/eng_refusals", tokens["staff"],
                {"projectId": commission["id"], "rule": "invented", "who": "Somebody Else"})
    assert st != 200, "a staff account wrote to the refusal log"


def test_a_logging_failure_never_turns_a_refusal_into_a_pass(api, tokens, commission, monkeypatch):
    """The worst bug this module could have. The refusal stands even if nothing records it."""
    def _boom(*a, **k):
        raise RuntimeError("the log is on fire")
    monkeypatch.setattr(app.Handler, "_eng_log_refusal", _boom, raising=True)

    _mk(api, tokens["staff"], "eng_holds", {
        "projectId": commission["id"], "kind": "hold", "ref": "H-302",
        "title": "Open", "status": "open"})
    g = _mk(api, tokens["staff"], "eng_stages", {
        "projectId": commission["id"], "stage": "Detail", "status": "At gate"})
    st, b = _sign(api, tokens["staff"], "eng_stages", g["id"], "Passed")
    assert st != 200, "the gate passed because the logger threw"
    assert "H-302" in str(b), "and it still says why"


def test_the_log_says_which_record_was_stopped(api, tokens, commission):
    d = _mk(api, tokens["staff"], "eng_deliverables", {
        "projectId": commission["id"], "docNo": "LOG26-EL-DWG-001", "title": "A drawing",
        "docType": "Drawing", "discipline": "Electrical", "stage": "Detail",
        "preparedBy": "Alice Engineer", "approver": "Staff One"})
    rev = _mk(api, tokens["staff"], "eng_revisions", {
        "projectId": commission["id"], "deliverableId": d["id"], "rev": "C01",
        "issueStatus": "IFC", "reasonForIssue": "issue", "preparedBy": "Alice Engineer",
        "status": "Draft"})
    st, _ = _sign(api, tokens["staff"], "eng_revisions", rev["id"], "Issued")
    assert st != 200                      # no checker recorded

    r = [x for x in _log(api, tokens["admin"]) if x.get("recordId") == rev["id"]][0]
    assert r["recordId"] == rev["id"]
    assert r["recordRef"] == "C01", "so a reader can find the thing that was stopped"
    assert r["projectId"] == commission["id"], "and which commission it belongs to"
