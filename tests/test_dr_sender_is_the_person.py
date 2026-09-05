# -*- coding: utf-8 -*-
"""The link comes from whoever sent it; the codes come from whoever set the site up.

A site handed a permanent sign-in link should see who handed it over and be able to reply to that
person — "procurement@" is a department, and the contractor's question is always for an individual.

The code email is the awkward half and worth stating: NOBODY IS SIGNED IN when a code is requested.
The site is anonymous, which is the entire point of the link, so "the current user" does not exist
at that moment. `issuedBy` — recorded when the link was emailed — is the nearest true answer and is
the person that site already corresponds with.

The consequence for operations is the reason `_mail_senders` had to change too: the set of mailboxes
the app sends as is now DATA. An Exchange application access policy scoped from a fixed list would
omit a colleague who issued a link after the policy was written, and the first code from them would
fail with nothing on any screen saying why.
"""
import app
import db
import dr_access

PID = "P-SND"
CON = {"id": "C-SND", "name": "Newtecons", "projectId": PID, "token": "tok" + "S" * 30,
       "emails": "site@newtecons.example", "mgmtRoles": [], "workerTrades": [], "categories": []}


def _seed(**extra):
    db.put_collection_item("dr_contractors", dict(CON, **extra))
    return db.get_collection_item("dr_contractors", "C-SND")


def test_a_contractor_nobody_has_issued_uses_the_department_mailbox(base_url):
    """Set up before this change, or the link handed over by hand. It must still be able to send."""
    con = _seed()
    got = app.Handler._dr_mail_sender(app.Handler, con)
    assert got == app._dr_sender(), got
    assert "@" in got
    db.delete_collection_item("dr_contractors", "C-SND")


def test_the_issuer_sends_the_codes(base_url):
    con = _seed(issuedBy="tony.nguyen@humiley.com")
    assert app.Handler._dr_mail_sender(app.Handler, con) == "tony.nguyen@humiley.com"
    db.delete_collection_item("dr_contractors", "C-SND")


def test_a_blank_issuer_falls_back_rather_than_sending_from_nowhere(base_url):
    """An empty string is not an address, and `or` on it must reach the default rather than hand
    Graph a blank From — which fails with an error about a mailbox named nothing."""
    for blank in ("", "   ", None):
        con = _seed(issuedBy=blank)
        got = app.Handler._dr_mail_sender(app.Handler, con)
        assert got == app._dr_sender(), "%r produced %r" % (blank, got)
    db.delete_collection_item("dr_contractors", "C-SND")


def test_the_issuer_is_normalised_so_case_cannot_split_one_mailbox_in_two(base_url):
    con = _seed(issuedBy="  Tony.Nguyen@Humiley.com  ")
    assert app.Handler._dr_mail_sender(app.Handler, con) == "tony.nguyen@humiley.com"
    db.delete_collection_item("dr_contractors", "C-SND")


def test_every_issuer_reaches_the_health_panel(base_url):
    """The check that protects the Exchange policy. A mailbox the app sends as and the panel does
    not list is a mailbox a scope group leaves out."""
    _seed(issuedBy="colleague@humiley.com")
    try:
        listed = {m["address"] for m in app._mail_senders()}
        assert "colleague@humiley.com" in listed, \
            "an issuing mailbox is invisible to the panel: %s" % sorted(listed)
        row = [m for m in app._mail_senders() if m["address"] == "colleague@humiley.com"][0]
        assert "Newtecons" in row["purpose"], \
            "the row does not say WHICH contractor, so nobody can tell why it is there"
    finally:
        db.delete_collection_item("dr_contractors", "C-SND")


def test_the_department_mailboxes_are_still_listed(base_url):
    """Adding the dynamic ones must not displace the fixed ones — approval mail still uses those."""
    _seed(issuedBy="colleague@humiley.com")
    try:
        listed = {m["address"] for m in app._mail_senders()}
        for coll in ("leave", "claims", "proc_x"):
            assert app._appr_email_sender(coll).lower() in listed, coll
        assert app.INVTRACK["mailbox"].lower() in listed
    finally:
        db.delete_collection_item("dr_contractors", "C-SND")


def test_the_send_link_signature_takes_the_caller(base_url):
    """The one live call site passes `u`, but the parameter has to stay OPTIONAL: a caller with no
    signed-in user (a scheduled resend, a repair script) must still be able to send rather than
    crash on a missing keyword, and it then falls back to the department mailbox."""
    import inspect
    sig = inspect.signature(app.Handler._dr_send_link)
    assert "u" in sig.parameters, sig
    assert sig.parameters["u"].default is None, "the caller must be optional"
