# -*- coding: utf-8 -*-
"""Report Setup can answer "why is no code arriving".

The form cannot: the same sentence goes back whether or not the address is listed, or the link
becomes a way of discovering who is on it. That left the person configuring the contractor guessing
on the one screen where the answer belongs — and the guess people reach for is "the email is slow",
which sent us after DKIM for a code that had never been sent.

`/api/dr/link` now returns the last few outcomes, refusals AND successes, so the two states are
distinguishable by looking.
"""
import json
import urllib.error
import urllib.request

import pytest

import app
import db
import dr_access

PID = "P-RC"
TOKEN = "tok" + "R" * 30
LISTED = "site@taikisha.example"
CON = {"id": "C-RC", "name": "Taikisha", "projectId": PID, "token": TOKEN, "emails": LISTED,
       "mgmtRoles": [], "workerTrades": [], "categories": [],
       "owner": "Dept Manager", "createdById": "HML-MGR"}


@pytest.fixture(autouse=True)
def _seed(base_url):
    db.put_collection_item("pm_projects", {"id": PID, "name": "Mega", "manager": "Dept Manager"})
    db.put_collection_item("dr_contractors", dict(CON))
    for row in list(db.list_collection("audit")):
        if "Daily report code" in str(row.get("action") or ""):
            db.delete_collection_item("audit", row.get("id"))
    yield
    db.delete_collection_item("dr_contractors", "C-RC")
    db.delete_collection_item("pm_projects", PID)


def _ask(base_url, email):
    req = urllib.request.Request(base_url + "/api/dr/site/code",
                                 data=json.dumps({"token": TOKEN, "email": email}).encode(),
                                 method="POST")
    req.add_header("Content-Type", "application/json")
    try:
        urllib.request.urlopen(req, timeout=10).read()
    except urllib.error.HTTPError as e:
        e.read()


def _link(api, tokens):
    st, b = api("POST", "/api/dr/link", tokens["mgr"], {"contractorId": "C-RC", "projectId": PID})
    assert st == 200, b
    return b


def test_a_refusal_is_visible_on_the_setup_screen(base_url, api, tokens):
    _ask(base_url, "not.listed@gmail.com")
    rows = _link(api, tokens)["codes"]
    assert rows, "the setup screen shows nothing about a request that was refused"
    assert rows[0]["action"] == "Daily report code not sent"
    assert "not.listed@gmail.com" in rows[0]["who"]
    assert "not on this contractor's list" in rows[0]["detail"], \
        "the row does not say WHY, which is the whole point"


def test_an_attempted_send_is_visible_too(base_url, api, tokens):
    """Without this, "no rows" would mean both "nobody ever asked" and "every request worked" —
    ambiguous in exactly the situation the panel exists to resolve. This server has no M365, so the
    send fails; either way an entry has to appear, or the screen is silent about a real attempt."""
    _ask(base_url, LISTED)
    rows = _link(api, tokens)["codes"]
    assert rows, "a request for a LISTED address left no trace at all"
    assert rows[0]["who"] == LISTED


def test_the_newest_attempt_is_first(base_url, api, tokens):
    _ask(base_url, "first@gmail.com")
    _ask(base_url, "second@gmail.com")
    rows = _link(api, tokens)["codes"]
    assert len(rows) >= 2
    assert rows[0]["who"] == "second@gmail.com", "the list is not newest-first: %r" % rows

def test_only_this_contractors_attempts_are_shown(base_url, api, tokens):
    """Two contractors on one project. One's sign-in attempts are not the other's business, and a
    mixed list would send somebody looking at the wrong address list."""
    other = dict(CON, id="C-RC2", name="Newtecons", token="tok" + "S" * 30,
                 emails="other@newtecons.example")
    db.put_collection_item("dr_contractors", other)
    try:
        _ask(base_url, "nope@gmail.com")           # against C-RC
        rows = _link(api, tokens)["codes"]
        assert all("C-RC2" not in json.dumps(r) for r in rows)
        assert rows and rows[0]["who"] == "nope@gmail.com"
    finally:
        db.delete_collection_item("dr_contractors", "C-RC2")


def test_no_code_and_no_token_ever_reaches_these_rows(base_url, api, tokens):
    """They are rendered into an admin screen and read by people. The six-digit code is the
    credential; the token is a permanent sign-in link."""
    _ask(base_url, LISTED)
    blob = json.dumps(_link(api, tokens)["codes"])
    assert TOKEN not in blob, "the permanent link token reached the setup screen's log"
    import re
    assert not re.search(r"\b\d{6}\b", blob), "something six digits long is in there: %s" % blob
