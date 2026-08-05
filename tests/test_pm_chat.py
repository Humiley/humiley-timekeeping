"""The project conversation: who can read it, who can post in it, and what an edit may change.

A chat is not a task list. People write candidly about contractors, clients and each other, so two
things have to hold that the rest of the Projects module does not bother with:

  * it is scoped to the projects you can actually open — every other pm_ collection ships the whole
    portfolio to anyone with the Projects app and lets the BROWSER filter, which for a channel would
    mean any engineer could read every project's conversation by calling the API directly;
  * a message is a statement somebody made, so authorship and time come from the session and an edit
    may change nothing but the words.

The second one nearly shipped broken. The create path stamped the author correctly while the generic
PATCH — a blind full-document overwrite whose pm_ guard pins only createdBy/createdById — would have
written authorName, authorId, ts and projectId straight from the browser. That is: put words in a
colleague's mouth, backdate a message into the middle of an argument, or move a message into another
project and out of the read scoping. The same hole closed in /api/esign the week before.
"""
import app
import db


def _project(api, tokens, code, manager="Dept Manager"):
    st, b = api("POST", "/api/coll/pm_projects", tokens["admin"],
                {"code": code, "name": code + " job", "manager": manager})
    assert st == 200, b
    return b["item"]["id"]


def _team(api, tokens, pid, name, emp_id=None):
    body = {"projectId": pid, "name": name, "projectRole": "Engineer"}
    if emp_id:
        body["empId"] = emp_id
    st, b = api("POST", "/api/coll/pm_resources", tokens["admin"], body)
    assert st == 200, b
    return b["item"]["id"]


def _post(api, token, pid, body="hello", parent=""):
    return api("POST", "/api/coll/pm_chat", token,
               {"projectId": pid, "parentId": parent, "body": body})


def _list(api, token):
    st, b = api("GET", "/api/coll/pm_chat", token)
    assert st == 200, b
    return b.get("items", b.get("pm_chat", []))


# ── it works ──────────────────────────────────────────────────────────────────────────────────────

def test_a_team_member_can_post_and_read(api, tokens):
    pid = _project(api, tokens, "CHAT-A")
    _team(api, tokens, pid, "Staff One")
    st, b = _post(api, tokens["staff"], pid, "Duct clash at grid C4")
    assert st == 200, b
    msgs = [m for m in _list(api, tokens["staff"]) if m.get("projectId") == pid]
    assert [m["body"] for m in msgs] == ["Duct clash at grid C4"]


def test_the_author_comes_from_the_session_not_the_browser(api, tokens):
    """A client claiming to be the Managing Director must not become him."""
    pid = _project(api, tokens, "CHAT-B")
    _team(api, tokens, pid, "Staff One")
    st, b = api("POST", "/api/coll/pm_chat", tokens["staff"],
                {"projectId": pid, "body": "approved by me",
                 "authorName": "Tony Nguyen", "authorId": "HML-ADM",
                 "ts": "2020-01-01T00:00:00.000Z"})
    assert st == 200, b
    m = b["item"]
    assert m["authorName"] == "Staff One" and m["authorId"] == "HML-STF"
    assert not m["ts"].startswith("2020"), "a client backdated its own message"
    assert m["createdById"] == "HML-STF", "ownership was pre-claimed by the client"


def test_timestamps_carry_milliseconds(api, tokens):
    """Rows come back ordered by a random uuid id, so second-resolution stamps would let two messages
       posted in the same second swap places between page loads."""
    pid = _project(api, tokens, "CHAT-MS")
    _team(api, tokens, pid, "Staff One")
    a = _post(api, tokens["staff"], pid, "first")[1]["item"]
    b = _post(api, tokens["staff"], pid, "second")[1]["item"]
    assert "." in a["ts"] and a["ts"].endswith("Z"), a["ts"]
    assert a["ts"] < b["ts"], "two messages in the same second are not ordered"


def test_a_reply_points_at_its_post(api, tokens):
    pid = _project(api, tokens, "CHAT-T")
    _team(api, tokens, pid, "Staff One")
    root = _post(api, tokens["staff"], pid, "Question")[1]["item"]
    st, b = _post(api, tokens["staff"], pid, "Answer", parent=root["id"])
    assert st == 200 and b["item"]["parentId"] == root["id"]


# ── the conversation is private to the project ────────────────────────────────────────────────────

def test_an_engineer_cannot_read_another_projects_conversation(api, tokens):
    """THE reason this collection is scoped server-side. 'other' is on neither project."""
    pid = _project(api, tokens, "CHAT-PRIV")
    _team(api, tokens, pid, "Staff One")
    assert _post(api, tokens["staff"], pid, "commercially sensitive")[0] == 200
    seen = [m for m in _list(api, tokens["other"]) if m.get("projectId") == pid]
    assert seen == [], "another project's conversation leaked through the API"


def test_an_engineer_cannot_post_into_a_project_they_are_not_on(api, tokens):
    """Writing must not be a way round the read scoping."""
    pid = _project(api, tokens, "CHAT-NOPOST")
    _team(api, tokens, pid, "Staff One")
    st, b = _post(api, tokens["other"], pid, "I should not be here")
    assert st == 403, (st, b)


def test_a_manager_sees_every_project_conversation(api, tokens):
    """Matching what the Projects list already shows them — _pmSeeAll is manager and above."""
    pid = _project(api, tokens, "CHAT-MGR")
    _team(api, tokens, pid, "Staff One")
    assert _post(api, tokens["staff"], pid, "visible to leadership")[0] == 200
    assert any(m.get("projectId") == pid for m in _list(api, tokens["admin"]))


def test_team_membership_is_matched_on_the_short_name_form_too(api, tokens):
    """The Team & RACI tab holds "Trung Nguyen" while the employee record says "Nguyen Van Trung".
       The server has to resolve that the same way the browser does, or chat locks people out of
       their own project exactly as the Projects list did."""
    pid = _project(api, tokens, "CHAT-NAME")
    _team(api, tokens, pid, "One Staff")          # reversed form of "Staff One"
    st, b = _post(api, tokens["staff"], pid, "it is me")
    assert st == 200, (st, b)


# ── an edit may change nothing but the words ──────────────────────────────────────────────────────

def _mine(api, tokens, pid):
    _team(api, tokens, pid, "Staff One")
    return _post(api, tokens["staff"], pid, "original")[1]["item"]


def test_you_can_edit_your_own_message_and_it_is_marked_edited(api, tokens):
    pid = _project(api, tokens, "CHAT-EDIT")
    m = _mine(api, tokens, pid)
    st, b = api("PATCH", "/api/coll/pm_chat/" + m["id"], tokens["staff"],
                dict(m, body="corrected"))
    assert st == 200, b
    assert b["item"]["body"] == "corrected" and b["item"].get("editedAt")


def test_an_edit_cannot_change_the_author(api, tokens):
    """THE hole that nearly shipped: put words in a colleague's mouth."""
    pid = _project(api, tokens, "CHAT-FORGE")
    m = _mine(api, tokens, pid)
    st, b = api("PATCH", "/api/coll/pm_chat/" + m["id"], tokens["staff"],
                dict(m, body="x", authorName="Tony Nguyen", authorId="HML-ADM"))
    assert st == 200, b
    assert b["item"]["authorName"] == "Staff One" and b["item"]["authorId"] == "HML-STF"


def test_an_edit_cannot_backdate_a_message(api, tokens):
    pid = _project(api, tokens, "CHAT-BACKDATE")
    m = _mine(api, tokens, pid)
    st, b = api("PATCH", "/api/coll/pm_chat/" + m["id"], tokens["staff"],
                dict(m, body="x", ts="2020-01-01T00:00:00.000Z"))
    assert st == 200, b
    assert b["item"]["ts"] == m["ts"], "the message was moved in time"


def test_an_edit_cannot_move_a_message_into_another_project(api, tokens):
    """Otherwise editing is a way straight out of the read scoping."""
    a = _project(api, tokens, "CHAT-SRC")
    other = _project(api, tokens, "CHAT-DST")
    m = _mine(api, tokens, a)
    st, b = api("PATCH", "/api/coll/pm_chat/" + m["id"], tokens["staff"],
                dict(m, body="x", projectId=other))
    assert st == 200, b
    assert b["item"]["projectId"] == a, "a message was moved into another project"


def test_you_cannot_edit_somebody_elses_message(api, tokens):
    pid = _project(api, tokens, "CHAT-OTHERS")
    _team(api, tokens, pid, "Staff One")
    _team(api, tokens, pid, "Other Staff")
    m = _post(api, tokens["staff"], pid, "mine")[1]["item"]
    st, b = api("PATCH", "/api/coll/pm_chat/" + m["id"], tokens["other"],
                dict(m, body="rewritten by someone else"))
    assert st == 403, (st, b)
    row = next(x for x in db.list_collection("pm_chat") if x["id"] == m["id"])
    assert row["body"] == "mine"


def test_a_message_is_never_born_edited(api, tokens):
    pid = _project(api, tokens, "CHAT-BORN")
    _team(api, tokens, pid, "Staff One")
    st, b = api("POST", "/api/coll/pm_chat", tokens["staff"],
                {"projectId": pid, "body": "hi", "editedAt": "2020-01-01T00:00:00.000Z",
                 "deletedAt": "2020-01-01T00:00:00.000Z"})
    assert st == 200, b
    assert not b["item"].get("editedAt") and not b["item"].get("deletedAt")


def test_a_very_long_message_is_clamped(api, tokens):
    pid = _project(api, tokens, "CHAT-LONG")
    _team(api, tokens, pid, "Staff One")
    st, b = _post(api, tokens["staff"], pid, "x" * 20000)
    assert st == 200, b
    assert len(b["item"]["body"]) == 8000
