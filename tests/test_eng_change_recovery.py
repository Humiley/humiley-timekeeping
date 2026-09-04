"""A chargeable change that was built and never billed.

This is the quietest way a design office funds a client's change out of its own fee, and it does
not look like anything at the time: the ECN is approved, the drawings are revised, the work is
recorded as done, and the variation that was going to recover it is still a conversation somebody
meant to have.

Two rules, at the two moments where it can still be caught.

Who pays is part of the approval, not something to settle afterwards. "To be agreed" settles itself
once the hours are spent, and it settles against us.

And a change agreed as chargeable cannot be recorded as done with nothing to bill it against. The
variation does not have to exist when the change is approved — it usually cannot, the scope is
still being argued — but by the time the work is done, the thing that recovers it has to be pointed
at. Absorbing the cost stays available; it just has to be a decision somebody is seen to make.
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
        "name": "Recovery commission", "code": "REC26", "client": "A Client",
        "designManager": "Dept Manager", "leadEngineer": "Staff One",
        "status": "Active", "currentStage": "Detail", "members": "Staff One"})


def _ecn(api, tokens, commission, **kw):
    body = {"projectId": commission["id"], "ecnNo": "REC26-ECN-001",
            "title": "Client moved the plant room two grids east",
            "originator": "Alice Engineer", "impactHours": 120,
            "clientChargeable": "Yes — variation", "status": "Raised"}
    body.update(kw)
    return _mk(api, tokens["staff"], "eng_changes", body)


# ── who pays is part of the approval ────────────────────────────────────────────

def test_approving_with_chargeability_undecided_is_refused(api, tokens, commission):
    e = _ecn(api, tokens, commission, clientChargeable="To be agreed")
    st, b = _sign(api, tokens["staff"], "eng_changes", e["id"], "Approved")
    assert st != 200, "approved with who-pays still open"
    assert "who pays" in str(b).lower() or "agreed" in str(b).lower()


def test_approving_with_the_field_blank_is_allowed(api, tokens, commission):
    """A blank field is a record made before anybody asked the question, and older changes are
    full of them. Refusing those would break approvals that were legitimate when raised — and the
    money is caught for certain at implementation, where the work is actually done."""
    e = _ecn(api, tokens, commission, clientChargeable="")
    st, b = _sign(api, tokens["mgr"], "eng_changes", e["id"], "Approved")
    assert st == 200, b


def test_approving_a_chargeable_change_is_fine(api, tokens, commission):
    e = _ecn(api, tokens, commission)
    st, b = _sign(api, tokens["staff"], "eng_changes", e["id"], "Approved")
    assert st == 200, b
    assert b["item"]["decidedBy"] == "Staff One"


def test_approving_a_change_we_choose_to_absorb_is_fine(api, tokens, commission):
    """Absorbing stays available. It just has to be chosen, by somebody, on the record."""
    e = _ecn(api, tokens, commission, clientChargeable="No — at our cost")
    st, b = _sign(api, tokens["staff"], "eng_changes", e["id"], "Approved")
    assert st == 200, b


# ── done, with nothing to bill it against ───────────────────────────────────────

def test_implementing_a_chargeable_change_with_no_variation_is_refused(api, tokens, commission):
    e = _ecn(api, tokens, commission)
    st, _ = _sign(api, tokens["staff"], "eng_changes", e["id"], "Approved")
    assert st == 200
    e["status"] = "Implemented"
    st, b = api("PATCH", "/api/coll/eng_changes/" + e["id"], tokens["staff"], e)
    assert st != 200, "recorded as done with nothing to recover it"
    assert "variation" in str(b).lower()


def test_implementing_lands_once_the_variation_is_linked(api, tokens, commission):
    e = _ecn(api, tokens, commission)
    st, _ = _sign(api, tokens["staff"], "eng_changes", e["id"], "Approved")
    assert st == 200
    e["status"] = "Implemented"
    e["variationRef"] = "VO-014"
    st, b = api("PATCH", "/api/coll/eng_changes/" + e["id"], tokens["staff"], e)
    assert st == 200, b


def test_implementing_an_absorbed_change_needs_no_variation(api, tokens, commission):
    e = _ecn(api, tokens, commission, clientChargeable="No — at our cost")
    st, _ = _sign(api, tokens["staff"], "eng_changes", e["id"], "Approved")
    assert st == 200
    e["status"] = "Implemented"
    st, b = api("PATCH", "/api/coll/eng_changes/" + e["id"], tokens["staff"], e)
    assert st == 200, b


def test_switching_to_absorb_is_a_way_through(api, tokens, commission):
    """The refusal offers two exits and both have to work, or people route around it."""
    e = _ecn(api, tokens, commission)
    st, _ = _sign(api, tokens["staff"], "eng_changes", e["id"], "Approved")
    assert st == 200
    e["status"] = "Implemented"
    e["clientChargeable"] = "No — at our cost"
    st, b = api("PATCH", "/api/coll/eng_changes/" + e["id"], tokens["staff"], e)
    assert st == 200, b


def test_an_ordinary_edit_before_it_is_done_is_untouched(api, tokens, commission):
    """The rule fires on the transition to done, not on every save."""
    e = _ecn(api, tokens, commission)
    e["description"] = "Two grids east, confirmed on the site walk"
    st, b = api("PATCH", "/api/coll/eng_changes/" + e["id"], tokens["staff"], e)
    assert st == 200, b
