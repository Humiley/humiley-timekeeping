# -*- coding: utf-8 -*-
"""A code request that sends nothing still leaves a trace — for the owner, not the caller.

`/api/dr/site/code` answers with the same sentence whether or not the address is authorised, which
is right: a different answer would turn the form into a way of discovering who is on a contractor's
list. But the same silence covers two completely different situations —

    the address IS listed  -> a mail was attempted, and "no code arrived" is a delivery question
    the address is NOT     -> nothing was ever emailed, and delivery is beside the point

— and until these were recorded, nobody could tell which had happened. It cost a round of chasing
Gmail deliverability for a code that had never been sent. The caller still learns nothing; the audit
log now says which.
"""
import json
import urllib.error
import urllib.request

import pytest

import db
import dr_access

PID = "P-AUD"
TOKEN = "tok" + "A" * 30
LISTED = "site@taikisha.example"
CONTRACTOR = {"id": "C-AUD", "name": "Taikisha", "projectId": PID, "token": TOKEN,
              "emails": LISTED, "mgmtRoles": [], "workerTrades": [], "categories": []}


@pytest.fixture(autouse=True)
def _seed(base_url):
    db.put_collection_item("pm_projects", {"id": PID, "name": "Mega", "manager": "Dept Manager"})
    db.put_collection_item("dr_contractors", dict(CONTRACTOR))
    for row in list(db.list_collection("audit")):
        if "Daily report code" in str(row.get("action") or ""):
            db.delete_collection_item("audit", row.get("id"))
    yield
    db.delete_collection_item("dr_contractors", "C-AUD")
    db.delete_collection_item("pm_projects", PID)


def _ask(base_url, email, token=TOKEN):
    req = urllib.request.Request(base_url + "/api/dr/site/code",
                                 data=json.dumps({"token": token, "email": email}).encode(),
                                 method="POST")
    req.add_header("Content-Type", "application/json")
    try:
        with urllib.request.urlopen(req, timeout=10) as r:
            return r.status, json.loads(r.read().decode() or "{}")
    except urllib.error.HTTPError as e:
        return e.code, json.loads(e.read().decode() or "{}")


def _notes():
    return [r for r in db.list_collection("audit")
            if str(r.get("action") or "") == "Daily report code not sent"]


def test_an_unlisted_address_is_recorded_as_not_sent(base_url):
    st, b = _ask(base_url, "someone.else@gmail.com")
    assert st == 200 and b["message"] == dr_access.SENT_MESSAGE, \
        "the caller was told something different — that is an oracle"
    rows = _notes()
    assert rows, "nothing was recorded, so nobody can tell this from a delivery failure"
    detail = rows[-1]["detail"]
    assert "not on this contractor's list" in detail
    assert LISTED in detail, "the note does not say who IS on the list, which is the next question"


def test_an_unlisted_address_never_learns_the_mail_system_is_broken(base_url):
    """The ordinary answer is shared. Two states deliberately are not — the throttle and a failed
    send both answer honestly, and neither can be reached by an address that is not on the list.
    That trade is documented on the endpoint. What must stay true is the direction of it: an
    UNLISTED address only ever sees the generic sentence, whatever state the mail system is in.
    Here the test server has no M365 at all, so every real send fails — which makes this the exact
    condition under which a leak would show."""
    _st, unlisted = _ask(base_url, "nobody@example.com")
    assert unlisted["message"] == dr_access.SENT_MESSAGE, \
        "an unlisted address was told something about the mail system: %r" % unlisted["message"]
    assert not unlisted.get("throttled")

    _st, listed = _ask(base_url, LISTED)
    assert listed["message"] != dr_access.SENT_MESSAGE, \
        ("a listed address whose mail FAILED was told it was on its way — the false green the "
         "synchronous sender exists to prevent")


def test_an_unknown_link_is_recorded_too(base_url):
    st, b = _ask(base_url, LISTED, token="tok" + "Z" * 30)
    assert st == 200 and b["message"] == dr_access.SENT_MESSAGE
    rows = _notes()
    assert rows and "No contractor matches this link" in rows[-1]["detail"]


def test_the_note_does_not_carry_the_whole_token(base_url):
    """It is written to a log an admin reads and exports. A permanent sign-in link in plain text
    there is a credential sitting somewhere it was never meant to be."""
    _ask(base_url, LISTED, token="tok" + "Z" * 30)
    rows = _notes()
    assert rows
    assert TOKEN not in json.dumps(rows[-1]), "a full token reached the audit log"
    assert ("tok" + "Z" * 30) not in json.dumps(rows[-1])
