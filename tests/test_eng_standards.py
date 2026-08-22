"""Which edition of a code governs is a design input, not a note.

A consultancy is audited on this: show me the codes this design was produced to, at which edition,
and show me that the drawings were checked against that text. The register had no answer — the
codes lived in the design-basis narrative, so "which edition?" was a question about a paragraph.

The rule that matters is not that the edition is recorded. It is that it cannot drift. Once an
edition is adopted, every deliverable has been designed and checked against THAT text; moving the
register to a newer one silently re-bases the whole design and leaves drawings claiming compliance
with something nobody verified. Codes really are reissued mid-project, so the edition may still
move — carrying the change reference that says who looked at what it broke.
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
        "name": "Standards commission", "code": "STD26", "client": "A Client",
        "designManager": "Dept Manager", "leadEngineer": "Staff One",
        "status": "Active", "currentStage": "Detail", "members": "Staff One"})


def _std(api, tokens, commission, **kw):
    body = {"projectId": commission["id"], "code": "TCVN 5687", "title": "Ventilation and air conditioning",
            "issuer": "TCVN", "edition": "2010", "discipline": "Mechanical",
            "obligation": "Statutory", "status": "Draft"}
    body.update(kw)
    return _mk(api, tokens["staff"], "eng_standards", body)


def test_the_register_holds_a_governing_edition(api, tokens, commission):
    s = _std(api, tokens, commission)
    assert s["edition"] == "2010"
    st, b = api("GET", "/api/coll/eng_standards", tokens["staff"])
    assert any(x["id"] == s["id"] for x in b["items"])


def test_adoption_is_a_signed_act_of_the_design_authority(api, tokens, commission):
    s = _std(api, tokens, commission)
    st, b = _sign(api, tokens["staff"], "eng_standards", s["id"], "Adopted")
    assert st == 200, b
    assert b["item"]["adoptedBy"] == "Staff One", "the server stamps the signer"
    assert b["item"]["adoptedOn"]


def test_a_post_cannot_forge_the_adoption(api, tokens, commission):
    s = _std(api, tokens, commission, status="Adopted",
             adoptedBy="Somebody Who Never Signed", adoptedOn="2020-01-01")
    assert not s.get("adoptedBy"), "a browser must not be able to name who adopted an edition"
    assert not s.get("adoptedOn")


def test_the_edition_cannot_drift_once_adopted(api, tokens, commission):
    """The whole point. 2010 -> 2024 with no change reference is refused."""
    s = _std(api, tokens, commission, status="Adopted")
    s["edition"] = "2024"
    st, b = api("PATCH", "/api/coll/eng_standards/" + s["id"], tokens["staff"], s)
    assert st != 200, "the governing edition was moved with nothing recorded"
    assert "2024" in str(b) and "2010" in str(b), "the refusal should name both editions"
    assert "change" in str(b).lower()


def test_a_new_edition_lands_when_a_change_authorises_it(api, tokens, commission):
    s = _std(api, tokens, commission, status="Adopted")
    ecn = _mk(api, tokens["staff"], "eng_changes", {
        "projectId": commission["id"], "title": "TCVN 5687 reissued as 2024",
        "originator": "Staff One", "status": "Raised"})
    s["edition"] = "2024"
    s["changeRef"] = ecn.get("ecnNo") or ecn["id"]
    st, b = api("PATCH", "/api/coll/eng_standards/" + s["id"], tokens["staff"], s)
    assert st == 200, b
    assert b["item"]["edition"] == "2024"


def test_an_edition_still_being_drafted_moves_freely(api, tokens, commission):
    """Before adoption the register is being assembled. Do not make that a fight."""
    s = _std(api, tokens, commission, status="Draft")
    s["edition"] = "2024"
    st, b = api("PATCH", "/api/coll/eng_standards/" + s["id"], tokens["staff"], s)
    assert st == 200, b
    assert b["item"]["edition"] == "2024"


def test_everything_else_on_an_adopted_standard_stays_editable(api, tokens, commission):
    """The guard is about the edition, not about locking the record."""
    s = _std(api, tokens, commission, status="Adopted")
    s["note"] = "Clause 5.3 governs the fresh-air rate for the cleanroom"
    st, b = api("PATCH", "/api/coll/eng_standards/" + s["id"], tokens["staff"], s)
    assert st == 200, b
    assert "5.3" in b["item"]["note"]
