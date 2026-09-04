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
import json

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


# ── attachments ───────────────────────────────────────────────────────────────────────────────────

def test_a_message_can_carry_files(api, tokens):
    pid = _project(api, tokens, "CHAT-FILES")
    _team(api, tokens, pid, "Staff One")
    st, b = api("POST", "/api/coll/pm_chat", tokens["staff"],
                {"projectId": pid, "body": "site photo",
                 "attachments": [{"name": "clash.jpg", "url": "data:image/jpeg;base64,QQ=="},
                                 {"name": "RFI-42.pdf", "url": "https://sp/RFI-42.pdf"}]})
    assert st == 200, b
    assert [a["name"] for a in b["item"]["attachments"]] == ["clash.jpg", "RFI-42.pdf"]


def test_a_photo_on_its_own_is_a_valid_message(api, tokens):
    """On a site the picture IS the message."""
    pid = _project(api, tokens, "CHAT-PHOTOONLY")
    _team(api, tokens, pid, "Staff One")
    st, b = api("POST", "/api/coll/pm_chat", tokens["staff"],
                {"projectId": pid, "body": "",
                 "attachments": [{"name": "p.jpg", "url": "data:image/jpeg;base64,QQ=="}]})
    assert st == 200 and len(b["item"]["attachments"]) == 1


def test_the_attachment_shape_is_rebuilt_not_accepted(api, tokens):
    """Only name and url survive — no extra keys ride in on a message, and the count is bounded so a
       message cannot become a payload."""
    pid = _project(api, tokens, "CHAT-SHAPE")
    _team(api, tokens, pid, "Staff One")
    st, b = api("POST", "/api/coll/pm_chat", tokens["staff"],
                {"projectId": pid, "body": "x",
                 "attachments": [{"name": "a", "url": "https://x/a", "evil": "payload"}] * 12
                                 + [{"name": "no url"}]})
    assert st == 200, b
    files = b["item"]["attachments"]
    assert len(files) == 6, "the attachment count is not bounded"
    assert all(set(f) == {"name", "url"} for f in files), files


# ── reactions ─────────────────────────────────────────────────────────────────────────────────────

def _msg(api, tokens, pid, who="staff"):
    return api("POST", "/api/coll/pm_chat", tokens[who], {"projectId": pid, "body": "hi"})[1]["item"]


def test_anyone_on_the_project_can_react_to_anyone_elses_message(api, tokens):
    """The ONE change a non-author may make. Reacting to your own messages only would be pointless."""
    pid = _project(api, tokens, "CHAT-REACT")
    _team(api, tokens, pid, "Staff One")
    _team(api, tokens, pid, "Other Staff")
    m = _msg(api, tokens, pid)
    st, b = api("PATCH", "/api/coll/pm_chat/" + m["id"], tokens["other"],
                dict(m, reactions={"\U0001F44D": ["HML-OTH"]}))
    assert st == 200, b
    assert b["item"]["reactions"]["\U0001F44D"] == ["HML-OTH"]


def test_a_reaction_toggles_off(api, tokens):
    pid = _project(api, tokens, "CHAT-TOGGLE")
    _team(api, tokens, pid, "Staff One")
    m = _msg(api, tokens, pid)
    on = api("PATCH", "/api/coll/pm_chat/" + m["id"], tokens["staff"],
             dict(m, reactions={"\u2705": ["HML-STF"]}))[1]["item"]
    assert on["reactions"]["\u2705"] == ["HML-STF"]
    off = api("PATCH", "/api/coll/pm_chat/" + m["id"], tokens["staff"],
              dict(on, reactions={"\u2705": []}))[1]["item"]
    assert off["reactions"] == {}, "an empty reaction should disappear, not linger"


def test_you_cannot_react_on_somebody_elses_behalf(api, tokens):
    """The map is rebuilt from the stored row and only ever gains or loses YOUR id."""
    pid = _project(api, tokens, "CHAT-FAKEREACT")
    _team(api, tokens, pid, "Staff One")
    m = _msg(api, tokens, pid)
    st, b = api("PATCH", "/api/coll/pm_chat/" + m["id"], tokens["staff"],
                dict(m, reactions={"\U0001F44D": ["HML-ADM", "HML-MGR"]}))
    assert st == 200, b
    assert b["item"]["reactions"] == {}, "a client put other people's reactions on a message"


def test_an_emoji_off_the_list_is_dropped(api, tokens):
    """Otherwise the reaction field is a free-text write onto somebody else's record."""
    pid = _project(api, tokens, "CHAT-EMOJI")
    _team(api, tokens, pid, "Staff One")
    m = _msg(api, tokens, pid)
    st, b = api("PATCH", "/api/coll/pm_chat/" + m["id"], tokens["staff"],
                dict(m, reactions={"\U0001F480": ["HML-STF"], "<script>": ["HML-STF"]}))
    assert st == 200, b
    assert b["item"]["reactions"] == {}


def test_reacting_is_not_a_way_to_edit_the_words(api, tokens):
    """THE hole this guard exists for: every client echoes the whole object back, and a message always
       carries a reactions field — so seeing one is not consent to an edit."""
    pid = _project(api, tokens, "CHAT-SNEAK")
    _team(api, tokens, pid, "Staff One")
    _team(api, tokens, pid, "Other Staff")
    m = _msg(api, tokens, pid)
    st, b = api("PATCH", "/api/coll/pm_chat/" + m["id"], tokens["other"],
                dict(m, body="rewritten", reactions={"\U0001F44D": ["HML-OTH"]}))
    assert st == 403, (st, b)
    row = next(x for x in db.list_collection("pm_chat") if x["id"] == m["id"])
    assert row["body"] == "hi" and not row.get("reactions")


def test_a_message_is_never_born_with_reactions(api, tokens):
    pid = _project(api, tokens, "CHAT-BORNREACT")
    _team(api, tokens, pid, "Staff One")
    st, b = api("POST", "/api/coll/pm_chat", tokens["staff"],
                {"projectId": pid, "body": "x", "reactions": {"\U0001F44D": ["HML-ADM"]}})
    assert st == 200 and b["item"]["reactions"] == {}


def test_someone_off_the_project_cannot_react(api, tokens):
    pid = _project(api, tokens, "CHAT-OUTSIDER")
    _team(api, tokens, pid, "Staff One")
    m = _msg(api, tokens, pid)
    st, b = api("PATCH", "/api/coll/pm_chat/" + m["id"], tokens["other"],
                dict(m, reactions={"\U0001F44D": ["HML-OTH"]}))
    assert st == 403, (st, b)


# ── mentions ──────────────────────────────────────────────────────────────────────────────────────
#
# A mention is the only thing in this module that makes somebody's phone ring. So it is the one field
# the browser is least trusted about: the server rebuilds the list from employees who are actually on
# the project, and pushes to nobody else. An unchecked list would be a way to page anyone in the
# company from a project they cannot even open.

def _mention(api, token, pid, body, mentions):
    return api("POST", "/api/coll/pm_chat", token,
               {"projectId": pid, "body": body, "mentions": mentions})


def test_you_can_mention_a_colleague_on_the_project(api, tokens):
    pid = _project(api, tokens, "MEN-A")
    _team(api, tokens, pid, "Staff One", "HML-STF")
    _team(api, tokens, pid, "Other Staff", "HML-OTH")
    st, b = _mention(api, tokens["staff"], pid, "@Other Staff please check the riser",
                     [{"empId": "HML-OTH", "name": "Other Staff"}])
    assert st == 200, b
    assert b["item"]["mentions"] == [{"empId": "HML-OTH", "name": "Other Staff"}]


def test_you_cannot_mention_somebody_who_is_not_on_the_project(api, tokens):
    """The point of the check. Otherwise the @ field is a company-wide paging system."""
    pid = _project(api, tokens, "MEN-B")
    _team(api, tokens, pid, "Staff One", "HML-STF")
    st, b = _mention(api, tokens["staff"], pid, "@Other Person look at this",
                     [{"empId": "HML-OTH", "name": "Other Person"}])
    assert st == 200, b
    assert b["item"]["mentions"] == [], "an off-project person was left in the mention list"


def test_a_made_up_person_is_dropped(api, tokens):
    pid = _project(api, tokens, "MEN-C")
    _team(api, tokens, pid, "Staff One", "HML-STF")
    st, b = _mention(api, tokens["staff"], pid, "@Nobody Here hello",
                     [{"empId": "NOPE-1", "name": "Nobody Here"}])
    assert b["item"]["mentions"] == []


def test_the_mentioned_name_comes_from_the_employee_record(api, tokens):
    """So the highlighted name in the message is the person's real name, not a label the sender chose
       — '@Finance Director' pointing at a junior engineer would be a nasty little forgery."""
    pid = _project(api, tokens, "MEN-D")
    _team(api, tokens, pid, "Staff One", "HML-STF")
    _team(api, tokens, pid, "Other Staff", "HML-OTH")
    st, b = _mention(api, tokens["staff"], pid, "@Finance Director sign this",
                     [{"empId": "HML-OTH", "name": "Finance Director"}])
    assert b["item"]["mentions"] == [{"empId": "HML-OTH", "name": "Other Staff"}]


def test_a_manager_who_is_not_on_the_project_cannot_be_mentioned(api, tokens):
    """Managers can READ every conversation, but @ is a summons. Being senior is not a reason to be
       summonable to a job you are not on — otherwise the @ field is a company-wide paging system and
       the Managing Director's phone buzzes for every project in the portfolio."""
    pid = _project(api, tokens, "MEN-E", manager="Someone Else")   # NOT the Dept Manager
    _team(api, tokens, pid, "Staff One", "HML-STF")
    st, b = _mention(api, tokens["staff"], pid, "@Dept Manager can you approve",
                     [{"empId": "HML-MGR", "name": "Dept Manager"}])
    assert b["item"]["mentions"] == [], "seniority was a way onto the mention list"


def test_a_manager_put_on_the_team_can_be_mentioned(api, tokens):
    """The way to reach somebody is to put them on the project. Then they are mentionable like anyone."""
    pid = _project(api, tokens, "MEN-E2", manager="Someone Else")
    _team(api, tokens, pid, "Staff One", "HML-STF")
    _team(api, tokens, pid, "Dept Manager", "HML-MGR")
    st, b = _mention(api, tokens["staff"], pid, "@Dept Manager can you approve",
                     [{"empId": "HML-MGR", "name": "Dept Manager"}])
    assert [m["empId"] for m in b["item"]["mentions"]] == ["HML-MGR"]


def test_the_project_manager_is_mentionable_without_a_team_row(api, tokens):
    """A PM is on the project by definition — the Charter names them — so they should not have to be
       added to their own Team to be reachable."""
    pid = _project(api, tokens, "MEN-E3", manager="Dept Manager")
    _team(api, tokens, pid, "Staff One", "HML-STF")
    st, b = _mention(api, tokens["staff"], pid, "@Dept Manager please review",
                     [{"empId": "HML-MGR", "name": "Dept Manager"}])
    assert [m["empId"] for m in b["item"]["mentions"]] == ["HML-MGR"]


def test_being_mentionable_does_not_follow_you_to_another_project(api, tokens):
    """On the job: yes. The next job along: no."""
    a = _project(api, tokens, "MEN-E4", manager="Someone Else")
    c = _project(api, tokens, "MEN-E5", manager="Someone Else")
    _team(api, tokens, a, "Staff One", "HML-STF")
    _team(api, tokens, a, "Other Staff", "HML-OTH")
    _team(api, tokens, c, "Staff One", "HML-STF")
    on = _mention(api, tokens["staff"], a, "@Other Staff here", [{"empId": "HML-OTH", "name": "Other Staff"}])
    off = _mention(api, tokens["staff"], c, "@Other Staff here", [{"empId": "HML-OTH", "name": "Other Staff"}])
    assert [m["empId"] for m in on[1]["item"]["mentions"]] == ["HML-OTH"]
    assert off[1]["item"]["mentions"] == []


def test_the_mention_list_is_deduped_and_bounded(api, tokens):
    pid = _project(api, tokens, "MEN-F")
    _team(api, tokens, pid, "Staff One", "HML-STF")
    _team(api, tokens, pid, "Other Staff", "HML-OTH")
    st, b = _mention(api, tokens["staff"], pid, "hey",
                     [{"empId": "HML-OTH", "name": "Other Person"}] * 60)
    ms = b["item"]["mentions"]
    assert len(ms) == 1, "the same person was mentioned repeatedly"


def test_a_message_is_never_born_mentioning_anybody(api, tokens):
    pid = _project(api, tokens, "MEN-G")
    _team(api, tokens, pid, "Staff One", "HML-STF")
    assert _post(api, tokens["staff"], pid, "no mentions here")[1]["item"]["mentions"] == []


def test_an_edit_cannot_add_a_mention_later(api, tokens):
    """Otherwise a quiet PATCH is a silent way to page someone — or to make it look, days later, like
       a colleague was called into a decision they were never in."""
    pid = _project(api, tokens, "MEN-H")
    _team(api, tokens, pid, "Staff One", "HML-STF")
    _team(api, tokens, pid, "Other Staff", "HML-OTH")
    m = _post(api, tokens["staff"], pid, "original")[1]["item"]
    m["mentions"] = [{"empId": "HML-OTH", "name": "Other Person"}]
    st, b = api("PATCH", "/api/coll/pm_chat/" + m["id"], tokens["staff"], m)
    after = [x for x in _list(api, tokens["staff"]) if x["id"] == m["id"]][0]
    assert after.get("mentions") == [], "a mention was smuggled in through an edit"


# ── unread ────────────────────────────────────────────────────────────────────────────────────────
#
# Counted on the server. The Projects list on a phone at a site must not download every message of
# every project just to draw a badge.

def _summary(api, token):
    st, b = api("GET", "/api/pm/chat/summary", token)
    assert st == 200, b
    return b


def _read(api, token, pid):
    return api("POST", "/api/pm/chat/read", token, {"projectId": pid})


def test_a_new_message_shows_as_unread(api, tokens):
    pid = _project(api, tokens, "UNR-A")
    _team(api, tokens, pid, "Staff One", "HML-STF")
    _team(api, tokens, pid, "Other Staff", "HML-OTH")
    _post(api, tokens["other"], pid, "site is flooded")
    s = _summary(api, tokens["staff"])
    assert s["unread"].get(pid) == 1
    assert s["names"].get(pid) == "UNR-A", "the bell cannot name the job this came from"


def test_your_own_message_is_not_unread_to_you(api, tokens):
    pid = _project(api, tokens, "UNR-B")
    _team(api, tokens, pid, "Staff One", "HML-STF")
    _post(api, tokens["staff"], pid, "typing to myself")
    assert _summary(api, tokens["staff"])["unread"].get(pid) is None


def test_opening_the_conversation_clears_it(api, tokens):
    pid = _project(api, tokens, "UNR-C")
    _team(api, tokens, pid, "Staff One", "HML-STF")
    _team(api, tokens, pid, "Other Staff", "HML-OTH")
    _post(api, tokens["other"], pid, "one")
    assert _read(api, tokens["staff"], pid)[0] == 200
    assert _summary(api, tokens["staff"])["unread"].get(pid) is None


def test_a_message_posted_after_you_read_counts_again(api, tokens):
    pid = _project(api, tokens, "UNR-D")
    _team(api, tokens, pid, "Staff One", "HML-STF")
    _team(api, tokens, pid, "Other Staff", "HML-OTH")
    _post(api, tokens["other"], pid, "one")
    _read(api, tokens["staff"], pid)
    _post(api, tokens["other"], pid, "two")
    assert _summary(api, tokens["staff"])["unread"].get(pid) == 1


def test_reading_one_project_does_not_clear_another(api, tokens):
    a = _project(api, tokens, "UNR-E1")
    c = _project(api, tokens, "UNR-E2")
    for pid in (a, c):
        _team(api, tokens, pid, "Staff One", "HML-STF")
        _team(api, tokens, pid, "Other Staff", "HML-OTH")
        _post(api, tokens["other"], pid, "hello")
    _read(api, tokens["staff"], a)
    s = _summary(api, tokens["staff"])
    assert s["unread"].get(a) is None and s["unread"].get(c) == 1


def test_mentions_are_counted_separately(api, tokens):
    """A badge that says '@2' is louder than one that says '5', because it is the one aimed at you."""
    pid = _project(api, tokens, "UNR-F")
    _team(api, tokens, pid, "Staff One", "HML-STF")
    _team(api, tokens, pid, "Other Staff", "HML-OTH")
    _post(api, tokens["other"], pid, "general chatter")
    _mention(api, tokens["other"], pid, "@Staff One the valve is stuck",
             [{"empId": "HML-STF", "name": "Staff One"}])
    s = _summary(api, tokens["staff"])
    assert s["unread"][pid] == 2 and s["mentions"][pid] == 1


def test_you_are_never_told_about_a_project_you_cannot_open(api, tokens):
    """The summary is a count, but a count of a conversation you cannot read still leaks that a job
       exists and that it is busy."""
    pid = _project(api, tokens, "UNR-G")
    _team(api, tokens, pid, "Other Staff", "HML-OTH")
    _post(api, tokens["other"], pid, "confidential client call")
    assert _summary(api, tokens["staff"])["unread"].get(pid) is None


def test_you_cannot_mark_a_conversation_you_cannot_read(api, tokens):
    pid = _project(api, tokens, "UNR-H")
    _team(api, tokens, pid, "Other Staff", "HML-OTH")
    st, b = _read(api, tokens["staff"], pid)
    assert st == 403, (st, b)


def test_the_summary_never_ships_the_messages_themselves(api, tokens):
    """It is called from the Projects LIST. Returning bodies would put every project's conversation on
       the wire on a screen that shows none of them."""
    pid = _project(api, tokens, "UNR-I")
    _team(api, tokens, pid, "Staff One", "HML-STF")
    _team(api, tokens, pid, "Other Staff", "HML-OTH")
    _post(api, tokens["other"], pid, "SECRET-MARKER-TEXT")
    s = _summary(api, tokens["staff"])
    assert "SECRET-MARKER-TEXT" not in json.dumps(s)
    assert set(s) <= {"ok", "unread", "mentions", "names", "readAt", "total", "totalMentions"}
    # readAt carries timestamps, never anything anybody wrote
    assert all(isinstance(v, str) and v[:2] == "20" for v in s["readAt"].values()), s["readAt"]


def test_reading_twice_keeps_one_row_per_person(api, tokens):
    """It is written on every tab paint. One row per employee, updated — not a new row each time."""
    pid = _project(api, tokens, "UNR-J")
    _team(api, tokens, pid, "Staff One", "HML-STF")
    for _ in range(4):
        _read(api, tokens["staff"], pid)
    rows = [r for r in db.list_collection("pm_chat_read") if r.get("empId") == "HML-STF"]
    assert len(rows) == 1, "the read marker is accumulating rows on every paint"


# ── what actually buzzes a phone ──────────────────────────────────────────────────────────────────
#
# Only a direct mention pushes. Every other message is a badge you find when you look — an engineer on
# five jobs cannot have their evening interrupted by every line anybody types.

def _pushes(monkeypatch):
    sent = []
    monkeypatch.setattr(app, "_tk_push",
                        lambda emails, title, body, url="/", tag="":
                        sent.append({"to": {str(e).lower() for e in emails}, "title": title,
                                     "body": body, "url": url, "tag": tag}) or len(emails))
    return sent


def test_a_mention_pushes_to_the_person_named(api, tokens, monkeypatch):
    sent = _pushes(monkeypatch)
    pid = _project(api, tokens, "PSH-A")
    _team(api, tokens, pid, "Staff One", "HML-STF")
    _team(api, tokens, pid, "Other Staff", "HML-OTH")
    _mention(api, tokens["staff"], pid, "@Other Staff the crane is booked",
             [{"empId": "HML-OTH", "name": "Other Staff"}])
    assert len(sent) == 1 and sent[0]["to"] == {"other@humiley.com"}
    assert "Staff One" in sent[0]["title"] and "PSH-A" in sent[0]["title"]
    assert "crane is booked" in sent[0]["body"]


def test_an_ordinary_message_pushes_to_nobody(api, tokens, monkeypatch):
    sent = _pushes(monkeypatch)
    pid = _project(api, tokens, "PSH-B")
    _team(api, tokens, pid, "Staff One", "HML-STF")
    _team(api, tokens, pid, "Other Staff", "HML-OTH")
    _post(api, tokens["staff"], pid, "morning all")
    assert sent == [], "a plain message rang somebody's phone"


def test_mentioning_yourself_does_not_buzz_you(api, tokens, monkeypatch):
    sent = _pushes(monkeypatch)
    pid = _project(api, tokens, "PSH-C")
    _team(api, tokens, pid, "Staff One", "HML-STF")
    _mention(api, tokens["staff"], pid, "@Staff One note to self",
             [{"empId": "HML-STF", "name": "Staff One"}])
    assert sent == []


def test_a_rejected_mention_does_not_push(api, tokens, monkeypatch):
    """The validation and the push must agree — a name the server threw out must not still ring."""
    sent = _pushes(monkeypatch)
    pid = _project(api, tokens, "PSH-D")
    _team(api, tokens, pid, "Staff One", "HML-STF")
    _mention(api, tokens["staff"], pid, "@Other Staff you are not on this job",
             [{"empId": "HML-OTH", "name": "Other Staff"}])
    assert sent == []


def test_the_push_opens_the_app_not_an_outside_link(api, tokens, monkeypatch):
    sent = _pushes(monkeypatch)
    pid = _project(api, tokens, "PSH-E")
    _team(api, tokens, pid, "Staff One", "HML-STF")
    _team(api, tokens, pid, "Other Staff", "HML-OTH")
    _mention(api, tokens["staff"], pid, "@Other Staff see this",
             [{"empId": "HML-OTH", "name": "Other Staff"}])
    assert sent[0]["url"].startswith("/") and not sent[0]["url"].startswith("//")
    assert sent[0]["tag"] == "pmchat-" + pid, "without a per-project tag every mention stacks up"


def test_the_push_lands_on_the_message_not_the_front_door(api, tokens, monkeypatch):
    """Tapping "X mentioned you" used to open the dashboard, leaving the engineer to find the job, the
       tab and the line themselves — which is most of the work of answering."""
    sent = _pushes(monkeypatch)
    pid = _project(api, tokens, "PSH-H")
    _team(api, tokens, pid, "Staff One", "HML-STF")
    _team(api, tokens, pid, "Other Staff", "HML-OTH")
    st, b = _mention(api, tokens["staff"], pid, "@Other Staff which riser?",
                     [{"empId": "HML-OTH", "name": "Other Staff"}])
    url = sent[0]["url"]
    assert "chat=" + pid in url, "the notification does not say which project"
    assert "msg=" + b["item"]["id"] in url, "the notification does not say which message"


def test_the_push_link_stays_inside_the_app(api, tokens, monkeypatch):
    """The service worker refuses anything that is not a same-origin path, and '//host' is not one."""
    sent = _pushes(monkeypatch)
    pid = _project(api, tokens, "PSH-I")
    _team(api, tokens, pid, "Staff One", "HML-STF")
    _team(api, tokens, pid, "Other Staff", "HML-OTH")
    _mention(api, tokens["staff"], pid, "@Other Staff check",
             [{"empId": "HML-OTH", "name": "Other Staff"}])
    url = sent[0]["url"]
    assert url.startswith("/?") and not url.startswith("//")
    assert "://" not in url


def test_a_photo_only_mention_still_says_something(api, tokens, monkeypatch):
    """An empty push body shows as a blank notification on the lock screen."""
    sent = _pushes(monkeypatch)
    pid = _project(api, tokens, "PSH-F")
    _team(api, tokens, pid, "Staff One", "HML-STF")
    _team(api, tokens, pid, "Other Staff", "HML-OTH")
    api("POST", "/api/coll/pm_chat", tokens["staff"],
        {"projectId": pid, "body": "", "mentions": [{"empId": "HML-OTH", "name": "Other Staff"}],
         "attachments": [{"name": "riser.jpg", "type": "image/jpeg", "data": "data:image/jpeg;base64,AAA"}]})
    assert sent and sent[0]["body"].strip(), "a blank notification went out"


def test_a_failing_push_never_loses_the_message(api, tokens, monkeypatch):
    """The words matter more than the buzz. If the push service is down the post still lands."""
    def _boom(*a, **k):
        raise RuntimeError("push service down")
    monkeypatch.setattr(app, "_tk_push", _boom)
    pid = _project(api, tokens, "PSH-G")
    _team(api, tokens, pid, "Staff One", "HML-STF")
    _team(api, tokens, pid, "Other Staff", "HML-OTH")
    st, b = _mention(api, tokens["staff"], pid, "@Other Staff urgent",
                     [{"empId": "HML-OTH", "name": "Other Staff"}])
    assert st == 200, b
    assert any(m["body"] == "@Other Staff urgent" for m in _list(api, tokens["staff"]))


def test_the_read_watermark_is_only_for_projects_you_can_open(api, tokens):
    """readAt drives the "new since you last looked" dots on the topic pills. It is the caller's own
       watermark — it must not become a way to learn that another job exists, or when it was busy."""
    mine = _project(api, tokens, "RDA-A")
    theirs = _project(api, tokens, "RDA-B")
    _team(api, tokens, mine, "Staff One", "HML-STF")
    _team(api, tokens, theirs, "Other Staff", "HML-OTH")
    _read(api, tokens["staff"], mine)
    api("POST", "/api/pm/chat/read", tokens["other"], {"projectId": theirs})
    s = _summary(api, tokens["staff"])
    assert mine in s["readAt"]
    assert theirs not in s["readAt"], "a project the caller cannot open leaked through the watermark"


# ── topics ────────────────────────────────────────────────────────────────────────────────────────
#
# A topic is a LABEL on a thread, not a room. The stream stays single, so nothing can be filed
# somewhere people stop looking — which on a live job is how a decision ends up back on Zalo. The
# vocabulary is closed and lives in code: with ~25 people and free text you get "Vat tu", "Vật tư",
# "Materials" and "VT" for one subject inside a month, which is the opposite of consolidating.

def _topic(api, token, pid, body="hello", topic="", parent=""):
    return api("POST", "/api/coll/pm_chat", token,
               {"projectId": pid, "parentId": parent, "body": body, "topic": topic})


def test_a_message_can_be_filed_under_a_topic(api, tokens):
    pid = _project(api, tokens, "TOP-A")
    _team(api, tokens, pid, "Staff One", "HML-STF")
    st, b = _topic(api, tokens["staff"], pid, "AHU casing leak test failed", "qaqc")
    assert st == 200 and b["item"]["topic"] == "qaqc"


def test_an_unfiled_message_is_general(api, tokens):
    pid = _project(api, tokens, "TOP-B")
    _team(api, tokens, pid, "Staff One", "HML-STF")
    assert _post(api, tokens["staff"], pid, "morning")[1]["item"]["topic"] == ""


def test_an_invented_topic_becomes_general_rather_than_an_error(api, tokens):
    """A message must never fail to send over a label. The words are what matter."""
    pid = _project(api, tokens, "TOP-C")
    _team(api, tokens, pid, "Staff One", "HML-STF")
    st, b = _topic(api, tokens["staff"], pid, "urgent", "vat-tu-khac")
    assert st == 200 and b["item"]["topic"] == ""


def test_a_reply_inherits_the_topic_of_its_thread(api, tokens):
    """A thread cannot split across two topics — otherwise half an argument is filed under Safety and
       half under Cost, and neither half makes sense on its own."""
    pid = _project(api, tokens, "TOP-D")
    _team(api, tokens, pid, "Staff One", "HML-STF")
    root = _topic(api, tokens["staff"], pid, "scaffold is blocking the riser", "hse")[1]["item"]
    kid = _topic(api, tokens["staff"], pid, "moving it tomorrow", "cost", parent=root["id"])[1]["item"]
    assert kid["topic"] == "hse", "the reply chose its own topic and split the thread"


def test_a_reply_to_a_reply_still_lands_on_the_root_topic(api, tokens):
    pid = _project(api, tokens, "TOP-E")
    _team(api, tokens, pid, "Staff One", "HML-STF")
    root = _topic(api, tokens["staff"], pid, "cleanroom handover date", "programme")[1]["item"]
    kid = _post(api, tokens["staff"], pid, "which zone", parent=root["id"])[1]["item"]
    grand = _post(api, tokens["staff"], pid, "zone 3", parent=kid["id"])[1]["item"]
    assert grand["parentId"] == root["id"] and grand["topic"] == "programme"


def test_a_reply_cannot_be_hung_off_another_projects_thread(api, tokens):
    """parentId was never checked. A crafted post could attach itself to a conversation in a project
       the caller cannot even read, and inherit that thread's topic on the way in."""
    a = _project(api, tokens, "TOP-F1")
    c = _project(api, tokens, "TOP-F2")
    for pid in (a, c):
        _team(api, tokens, pid, "Staff One", "HML-STF")
    root = _topic(api, tokens["staff"], a, "in project A", "site")[1]["item"]
    st, b = _topic(api, tokens["staff"], c, "smuggled in", "", parent=root["id"])
    assert st == 400, (st, b)


# ── re-filing ─────────────────────────────────────────────────────────────────────────────────────

def _move(api, token, msg, topic):
    m = dict(msg)
    m["topic"] = topic
    return api("PATCH", "/api/coll/pm_chat/" + msg["id"], token, m)


def test_you_can_re_file_your_own_message(api, tokens):
    pid = _project(api, tokens, "MOV-A")
    _team(api, tokens, pid, "Staff One", "HML-STF")
    m = _topic(api, tokens["staff"], pid, "wrong place", "site")[1]["item"]
    st, b = _move(api, tokens["staff"], m, "cost")
    assert st == 200 and b["item"]["topic"] == "cost"


def test_the_project_manager_can_re_file_anybody_s_message(api, tokens):
    """The load-bearing permission. Without it a junior dumps a thread into General at 6pm on a site
       and the one person who wanted tidiness cannot fix it."""
    pid = _project(api, tokens, "MOV-B", manager="Dept Manager")
    _team(api, tokens, pid, "Staff One", "HML-STF")
    m = _post(api, tokens["staff"], pid, "the AHU decision, filed nowhere")[1]["item"]
    st, b = _move(api, tokens["mgr"], m, "qaqc")
    assert st == 200, b
    assert b["item"]["topic"] == "qaqc"


def test_re_filing_does_not_mark_the_message_edited(api, tokens):
    """Moving a message is not changing what it says. An 'edited' marker would suggest the words were
       touched, which on a record people rely on is a small lie."""
    pid = _project(api, tokens, "MOV-C", manager="Dept Manager")
    _team(api, tokens, pid, "Staff One", "HML-STF")
    m = _post(api, tokens["staff"], pid, "unchanged words")[1]["item"]
    b = _move(api, tokens["mgr"], m, "hse")[1]["item"]
    assert b["body"] == "unchanged words"
    assert not b.get("editedAt"), "a move was recorded as an edit"


def test_a_bystander_cannot_re_file_somebody_else_s_message(api, tokens):
    pid = _project(api, tokens, "MOV-D", manager="Someone Else")
    _team(api, tokens, pid, "Staff One", "HML-STF")
    _team(api, tokens, pid, "Other Staff", "HML-OTH")
    m = _post(api, tokens["staff"], pid, "mine")[1]["item"]
    st, b = _move(api, tokens["other"], m, "cost")
    assert st == 403, (st, b)


def test_re_filing_is_not_a_way_to_rewrite_the_words(api, tokens):
    """The move carve-out sits above the guard that stops people editing each other's messages. It
       must not have punched a hole in it."""
    pid = _project(api, tokens, "MOV-E", manager="Dept Manager")
    _team(api, tokens, pid, "Staff One", "HML-STF")
    m = _post(api, tokens["staff"], pid, "the original words")[1]["item"]
    m2 = dict(m)
    m2["topic"] = "cost"
    m2["body"] = "words the manager preferred"
    st, b = api("PATCH", "/api/coll/pm_chat/" + m["id"], tokens["mgr"], m2)
    after = [x for x in _list(api, tokens["staff"]) if x["id"] == m["id"]][0]
    assert after["body"] == "the original words", "a re-file was used to edit somebody else's message"


def test_a_reply_cannot_be_re_filed_on_its_own(api, tokens):
    pid = _project(api, tokens, "MOV-F")
    _team(api, tokens, pid, "Staff One", "HML-STF")
    root = _topic(api, tokens["staff"], pid, "root", "site")[1]["item"]
    kid = _post(api, tokens["staff"], pid, "reply", parent=root["id"])[1]["item"]
    st, b = _move(api, tokens["staff"], kid, "cost")
    assert st == 400, (st, b)


def test_a_move_to_an_unknown_topic_is_refused_loudly(api, tokens):
    """A bad POST is quiet (the message still sends, as General). A bad MOVE is deliberate, so it is
       told it failed rather than silently doing nothing."""
    pid = _project(api, tokens, "MOV-G")
    _team(api, tokens, pid, "Staff One", "HML-STF")
    m = _post(api, tokens["staff"], pid, "x")[1]["item"]
    st, b = _move(api, tokens["staff"], m, "not-a-topic")
    assert st == 400, (st, b)


def test_reacting_still_works_and_never_moves_a_message(api, tokens):
    """Every client echoes the whole record back, from a copy that may be up to 45s stale. If a PM
       re-filed the message in the meantime, that echo looks like a move attempt from somebody with no
       right to move it — and the thumbs-up gets refused for a reason nobody could work out. The
       browser therefore omits `topic` when it reacts, which is what this proves."""
    pid = _project(api, tokens, "MOV-H", manager="Dept Manager")
    _team(api, tokens, pid, "Staff One", "HML-STF")
    _team(api, tokens, pid, "Other Staff", "HML-OTH")
    m = _topic(api, tokens["staff"], pid, "leak test at 14:00", "qaqc")[1]["item"]
    _move(api, tokens["mgr"], m, "hse")                        # the PM re-files it

    react = {k: v for k, v in m.items() if k != "topic"}       # what pmChatReact actually sends
    react["reactions"] = {"\U0001F44D": ["HML-OTH"]}
    st, b = api("PATCH", "/api/coll/pm_chat/" + m["id"], tokens["other"], react)
    assert st == 200, (st, b)
    after = [x for x in _list(api, tokens["staff"]) if x["id"] == m["id"]][0]
    assert after["reactions"].get("\U0001F44D") == ["HML-OTH"], "the reaction did not land"
    assert after["topic"] == "hse", "a reaction moved the message"


def test_a_stale_client_that_does_send_the_old_topic_is_still_refused(api, tokens):
    """Belt and braces: omitting the field is the fix, but a client that sends the stale value must
       not be able to drag a message back to where it was."""
    pid = _project(api, tokens, "MOV-I", manager="Dept Manager")
    _team(api, tokens, pid, "Staff One", "HML-STF")
    _team(api, tokens, pid, "Other Staff", "HML-OTH")
    m = _topic(api, tokens["staff"], pid, "particle count", "qaqc")[1]["item"]
    _move(api, tokens["mgr"], m, "hse")
    stale = dict(m)                                            # still says qaqc
    stale["reactions"] = {"\U0001F44D": ["HML-OTH"]}
    api("PATCH", "/api/coll/pm_chat/" + m["id"], tokens["other"], stale)
    after = [x for x in _list(api, tokens["staff"]) if x["id"] == m["id"]][0]
    assert after["topic"] == "hse", "a stale echo dragged the message back to its old topic"
