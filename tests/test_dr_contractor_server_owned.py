# -*- coding: utf-8 -*-
"""Three fields on a contractor row that decide access, and none of them may come from the client.

Report Setup saves a contractor by PATCHing the WHOLE row back — `Object.assign({}, cur, …)` — and
`/api/coll` PATCH is a blind full-document replace. So every field the browser happens to be holding
is re-asserted on every save, including the ones the server set for reasons the browser knows
nothing about:

    issuedBy      the mailbox the app SENDS AS for this contractor's link and codes
    token         the permanent link — the entire access boundary is that it cannot be guessed
    sessionEpoch  the generation number that "Sign everyone out" bumps

The third is the one that bites without anybody doing anything wrong: revoke bumps the epoch, the
browser's cached copy still holds the old one, and the next "Save setup" writes it back — signing
every revoked device back IN, from a screen that says nothing about sessions.
"""
import db
import dr_access
import pytest

PID = "ZZ-DRSO"


@pytest.fixture
def con(api, tokens):
    db.put_collection_item("pm_projects", {"id": PID, "name": "ZZ Server Owned",
                                           "manager": "Dept Manager"})
    st, b = api("POST", "/api/coll/dr_contractors", tokens["mgr"],
                {"name": "Newtecons", "projectId": PID, "lists": {},
                 "mgmtRoles": [], "workerTrades": [], "categories": []})
    assert st == 200, b
    row = [c for c in db.list_collection("dr_contractors") if c.get("projectId") == PID][0]
    yield row
    for c in db.list_collection("dr_contractors"):
        if c.get("projectId") == PID:
            db.delete_collection_item("dr_contractors", c["id"])
    db.delete_collection_item("pm_projects", PID)


# ── what you asked for: the person who sets it up is the person it sends as ──────────────────────
def test_creating_a_contractor_records_who_created_it(con):
    """Not on first send — at creation. Until this, `issuedBy` was written only by a SUCCESSFUL link
    email, so a contractor set up and configured over an afternoon had no sender at all, the health
    panel could not show its mailbox, and the Exchange policy could not be built from it."""
    assert dr_access.norm_email(con.get("issuedBy")) == "mgr@humiley.com", \
        "the creator is not recorded: %r" % (con.get("issuedBy"),)


def test_that_sender_is_what_the_codes_go_out_from(con):
    import app
    assert app.Handler._dr_mail_sender(app.Handler, con) == "mgr@humiley.com"


def test_a_client_cannot_choose_the_mailbox_it_sends_as(api, tokens, con):
    """`issuedBy` is a From address handed to Graph. Taken from the body, any colleague with write
    access on the project could make the portal send a sign-in code as somebody else."""
    body = dict(con, issuedBy="ceo@humiley.com")
    st, b = api("PATCH", "/api/coll/dr_contractors/" + con["id"], tokens["mgr"], body)
    assert st == 200, b
    after = db.get_collection_item("dr_contractors", con["id"])
    assert dr_access.norm_email(after.get("issuedBy")) == "mgr@humiley.com", \
        "the browser chose the sending mailbox: %r" % (after.get("issuedBy"),)


# ── the two that travel with it ──────────────────────────────────────────────────────────────────
def test_a_client_cannot_choose_the_link(api, tokens, con):
    """A client-chosen token is a client-chosen secret. `valid_token` accepts sixteen characters of
    anything, so "aaaaaaaaaaaaaaaa" passes — and the contractor's site is then guessable by somebody
    who was never given the link."""
    was = con.get("token")
    st, _b = api("PATCH", "/api/coll/dr_contractors/" + con["id"], tokens["mgr"],
                 dict(con, token="a" * 16))
    assert st == 200
    after = db.get_collection_item("dr_contractors", con["id"])
    assert after.get("token") == was, "the link was replaced with a guessable one"


def test_saving_setup_cannot_undo_a_revoke(api, tokens, con):
    """The live one. Sign everyone out, then save the setup screen from a browser that loaded the
    contractor before the revoke: the stale epoch goes back, and every device that was signed out is
    signed back in."""
    revoked = dict(con, sessionEpoch=dr_access.session_epoch(con) + 1)
    db.put_collection_item("dr_contractors", revoked)
    assert dr_access.session_epoch(db.get_collection_item("dr_contractors", con["id"])) == 1

    st, _b = api("PATCH", "/api/coll/dr_contractors/" + con["id"], tokens["mgr"], dict(con))
    assert st == 200
    after = db.get_collection_item("dr_contractors", con["id"])
    assert dr_access.session_epoch(after) == 1, \
        "a stale Save setup rolled the generation back to %d — every revoked device is live again" \
        % dr_access.session_epoch(after)


def test_an_older_contractor_adopts_a_sender_when_its_setup_is_saved(api, tokens, con):
    """The migration path, and the reason it matters today: every contractor already in production
    was created before the sender was recorded. Without this they would stay on the department
    mailbox — and invisible to the health panel — until somebody happened to re-send the link."""
    db.put_collection_item("dr_contractors", dict(con, issuedBy=""))
    st, _b = api("PATCH", "/api/coll/dr_contractors/" + con["id"], tokens["admin"], dict(con))
    assert st == 200
    after = db.get_collection_item("dr_contractors", con["id"])
    assert dr_access.norm_email(after.get("issuedBy")) == "admin@humiley.com", \
        "an older contractor did not adopt a sender: %r" % (after.get("issuedBy"),)


def test_adoption_does_not_overwrite_a_sender_that_is_already_there(api, tokens, con):
    """Otherwise the mailbox would change under the contractor every time a different colleague
    opened Report Setup and pressed Save — and the codes with it."""
    st, _b = api("PATCH", "/api/coll/dr_contractors/" + con["id"], tokens["admin"], dict(con))
    assert st == 200
    after = db.get_collection_item("dr_contractors", con["id"])
    assert dr_access.norm_email(after.get("issuedBy")) == "mgr@humiley.com", \
        "somebody else's save moved the sending mailbox: %r" % (after.get("issuedBy"),)
