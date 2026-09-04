# -*- coding: utf-8 -*-
"""Filing progress on a contract you are not on.

The Master Schedule got a Daily progress table, and the audit that followed asked the obvious
question about the endpoint underneath it: who may PATCH `/api/coll/pm_tasks/<id>`?

The answer was **anybody with a session**. `pm_tasks` is in STAFF_WRITE, so the route guard asks
only that you are signed in; the `pm_` branch of `_coll_update` scoped `pm_chat` and nothing else.
A staff account on ZERO projects could take another project's schedule activity to 100% complete —
and because the endpoint is a blind full-document replace, the same request also dropped whatever
fields it did not send: start, finish, pctComplete, gone. Nothing on the server refused it, and
nothing recorded it. The button being absent from that person's screen was the whole protection.

The rule was already written down twice. `_coll_delete`'s own comment says its scope "is the same
test _pm_visible_projects already applies to reading them", and — in the same paragraph — that
"_coll_update has NO ownership guard for pm_*, so any of those same people could already blank the
row's name, its dates and its progress". That was true when it was written, it stayed true, and
being able to destroy a record's contents but not the record is not a protection.

So writes now ask the same question reads and deletes ask: is this project one of YOURS — do you
manage it, or are you on its Team. This file pins both halves, because a scope change is only
honest if the people who LOSE the ability are named as precisely as the people who keep it.

    python3 -m pytest tests/test_pm_write_scope.py -q
"""
import app
import db
import pytest


PID = "ZZ-WRITE-SCOPE"
OTHER_PID = "ZZ-WRITE-SCOPE-2"


@pytest.fixture
def proj():
    """A project nobody in the fixture set manages or is on."""
    p = db.put_collection_item("pm_projects", {"id": PID, "name": "ZZ Write Scope",
                                               "manager": "Nguyen Van Khong Ai"})
    t = db.put_collection_item("pm_tasks", {"projectId": PID, "wbs": "1.1", "name": "Piling",
                                            "start": "2026-09-01", "finish": "2026-09-30",
                                            "pctComplete": 10})
    yield p, t
    for coll in ("pm_tasks", "pm_resources"):
        for r in db.list_collection(coll):
            if r.get("projectId") in (PID, OTHER_PID):
                try:
                    db.delete_collection_item(coll, r["id"])
                except Exception:
                    pass
    for _p in (PID, OTHER_PID):
        try:
            db.delete_collection_item("pm_projects", _p)
        except Exception:
            pass


def _on_team(pid, emp_id, name):
    return db.put_collection_item("pm_resources", {"projectId": pid, "empId": emp_id,
                                                   "name": name, "role": "Engineer"})


def _file_progress(api, token, tid, pct=100):
    """What the Daily progress dialog sends: the whole row, with a dated reading appended."""
    row = db.get_collection_item("pm_tasks", tid)
    body = dict(row)
    body["log"] = [{"d": "2026-09-04", "pct": pct, "by": "whoever", "at": "2026-09-04T00:00:00Z"}]
    return api("PATCH", "/api/coll/pm_tasks/" + tid, token, body)


# ── the finding itself ──────────────────────────────────────────────────────────────────────────
def test_a_stranger_to_the_project_cannot_file_its_progress(api, tokens, proj):
    _p, t = proj
    st, b = _file_progress(api, tokens["staff"], t["id"])
    assert st == 403, "a staff account on no projects filed progress on this one: %s" % (b,)
    assert "project" in str(b.get("error", "")).lower(), \
        "the refusal must say WHY, so it can be acted on: %r" % (b,)
    after = db.get_collection_item("pm_tasks", t["id"])
    assert not after.get("log"), "the reading was stored anyway"


def test_the_refused_write_does_not_take_the_rest_of_the_row_with_it(api, tokens, proj):
    """The endpoint is a blind replace, so a refused write is not just a value not changed — it is
    the difference between a schedule activity and an empty row. This is the half that makes the
    guard matter even for somebody with no intent."""
    _p, t = proj
    st, _b = api("PATCH", "/api/coll/pm_tasks/" + t["id"], tokens["staff"],
                 {"id": t["id"], "projectId": PID, "name": "Piling", "pctComplete": 100})
    assert st == 403
    after = db.get_collection_item("pm_tasks", t["id"])
    assert after.get("start") == "2026-09-01" and after.get("finish") == "2026-09-30", \
        "the dates were dropped by a request that was supposed to be refused: %r" % (after,)


def test_creating_a_row_on_somebody_elses_programme_is_refused_too(api, tokens, proj):
    """Guarding only the update would shut one door beside an open one: a new activity POSTed onto
    another project's programme is in their schedule, their roll-up and their earned value."""
    st, b = api("POST", "/api/coll/pm_tasks", tokens["staff"],
                {"projectId": PID, "wbs": "9.9", "name": "Injected"})
    assert st == 403, b
    assert not [r for r in db.list_collection("pm_tasks")
                if r.get("projectId") == PID and r.get("name") == "Injected"]


def test_a_row_cannot_be_moved_into_a_project_you_are_not_on(api, tokens, proj):
    """projectId is what every scope in this module is decided on, so rewriting it rewrites who may
    see and touch the row. Own the row, own the move."""
    _p, _t = proj
    _on_team(OTHER_PID, "HML-STF", "Staff One")
    mine = db.put_collection_item("pm_tasks", {"projectId": OTHER_PID, "name": "Mine"})
    st, b = api("PATCH", "/api/coll/pm_tasks/" + mine["id"], tokens["staff"],
                dict(mine, projectId=PID))
    assert st == 403, b
    assert db.get_collection_item("pm_tasks", mine["id"])["projectId"] == OTHER_PID


def test_a_row_cannot_be_dragged_out_of_a_project_you_are_not_on(api, tokens, proj):
    """The mirror image, and the one a check on the INCOMING projectId alone would miss."""
    _p, t = proj
    _on_team(OTHER_PID, "HML-STF", "Staff One")
    st, b = api("PATCH", "/api/coll/pm_tasks/" + t["id"], tokens["staff"],
                dict(t, projectId=OTHER_PID))
    assert st == 403, b
    assert db.get_collection_item("pm_tasks", t["id"])["projectId"] == PID


# ── the people who keep it ──────────────────────────────────────────────────────────────────────
def test_somebody_on_the_team_can_file_progress(api, tokens, proj):
    _p, t = proj
    _on_team(PID, "HML-STF", "Staff One")
    st, b = _file_progress(api, tokens["staff"], t["id"], 60)
    assert st == 200, b
    assert db.get_collection_item("pm_tasks", t["id"])["log"][0]["pct"] == 60


def test_the_project_manager_can(api, tokens, proj):
    """Matched by NAME, the way _pm_visible_projects matches a manager — the same route the
    Projects list uses, not a second definition of the same idea."""
    p, t = proj
    db.put_collection_item("pm_projects", dict(p, manager="Staff One"))
    st, b = _file_progress(api, tokens["staff"], t["id"], 45)
    assert st == 200, b


def test_manager_level_writes_across_the_portfolio(api, tokens, proj):
    """_pm_visible_projects returns None above staff level, so they write where they read. Refusing
    them here would be a rule contradicting the one beside it."""
    _p, t = proj
    st, b = _file_progress(api, tokens["mgr"], t["id"], 30)
    assert st == 200, b


def test_admin_writes_across_the_portfolio_too(api, tokens, proj):
    """Not by an `if admin` clause — there deliberately is not one. _pm_visible_projects answers
    None for every rank at or above manager, so admin passes through the same door managers do."""
    _p, t = proj
    st, b = _file_progress(api, tokens["admin"], t["id"], 20)
    assert st == 200, b
    # Asserted on the guard's OWN two lines, not on a slice of the file between two method names:
    # that slice spans _coll_add and _coll_update whole and catches every unrelated admin check in
    # them, which is a red verdict about code the assertion never meant to read.
    src = open(app.__file__, encoding="utf-8").read()
    assert src.count('if name not in ("pm_projects", "pm_chat"):') == 1
    assert src.count('if name.startswith("pm_") and name not in ("pm_projects", "pm_chat"):') == 1
    assert '"pm_chat") and self._caller_level(u) != "admin"' not in src, \
        "an admin exemption was added to the pm_ write guard: it can never decide anything there " \
        "(_pm_visible_projects already answers None for admin), and a dead condition reads as the " \
        "thing keeping admin working"


def test_a_row_belonging_to_no_project_stays_writable(api, tokens, proj):
    """A deliberate difference from the delete guard, which refuses an orphan. An orphan appears in
    no project's scope and decides nothing, so refusing to write one would break whatever
    legitimately holds cross-project rows without protecting anything."""
    orphan = db.put_collection_item("pm_tasks", {"name": "No project"})
    try:
        st, b = api("PATCH", "/api/coll/pm_tasks/" + orphan["id"], tokens["staff"],
                    dict(orphan, name="No project, edited"))
        assert st == 200, b
    finally:
        try:
            db.delete_collection_item("pm_tasks", orphan["id"])
        except Exception:
            pass


# ── nothing beside it was weakened or duplicated ────────────────────────────────────────────────
def test_a_chat_message_still_answers_with_its_own_rule(api, tokens, proj):
    """pm_chat's guard is this test PLUS authorship, and it says something more specific. Routing it
    through the general one first would answer a message edit with the wrong sentence."""
    _on_team(PID, "HML-STF", "Staff One")
    m = db.put_collection_item("pm_chat", {"projectId": PID, "authorId": "SOMEBODY-ELSE",
                                           "authorName": "Someone", "body": "hello"})
    try:
        st, b = api("PATCH", "/api/coll/pm_chat/" + m["id"], tokens["staff"],
                    {"id": m["id"], "projectId": PID, "body": "edited"})
        assert st == 403, b
        assert "own" in str(b.get("error", "")).lower() or "author" in str(b.get("error", "")).lower(), \
            "a chat edit should be refused for AUTHORSHIP, not for membership: %r" % (b,)
        # And a NON-member is refused in the chat's own words, not the schedule's. Both sentences
        # are 403 and both are true, so only the wording distinguishes them — which is the whole
        # reason pm_chat is excluded from the general guard rather than folded into it.
        st2, b2 = api("PATCH", "/api/coll/pm_chat/" + m["id"], tokens["other"],
                      {"id": m["id"], "projectId": PID, "body": "edited"})
        assert st2 == 403, b2
        assert "message" in str(b2.get("error", "")).lower(), \
            "a non-member editing a message got the schedule's sentence: %r" % (b2,)
    finally:
        try:
            db.delete_collection_item("pm_chat", m["id"])
        except Exception:
            pass


def test_the_write_guard_reuses_pm_visible_projects(base_url):
    """Two independent definitions of "is this project mine" drift, and the pair that drifts
    silently is read-allowed / write-refused: a screen full of editable fields whose save 403s.
    _coll_delete already has a test asserting exactly this about itself."""
    src = open(app.__file__, encoding="utf-8").read()
    assert "def _pm_write_refusal(" in src
    lines = src.splitlines()
    start = next(n for n, l in enumerate(lines) if l.strip().startswith("def _pm_write_refusal("))
    end = next((n for n in range(start + 1, len(lines))
                if lines[n].strip().startswith("def ")), len(lines))
    body = "\n".join(lines[start:end])
    n = len(body.splitlines())
    assert 10 < n < 80, "extracted %d lines for _pm_write_refusal — the slice is wrong" % n
    assert "_pm_visible_projects(u)" in body, \
        "the write guard must ask the same question reads and deletes ask, not a copy of it"
    # And it is actually reached from both write paths, not defined and forgotten. Counted on the
    # call, not on the name: the definition itself contains the name.
    assert src.count("self._pm_write_refusal(") >= 3, \
        "the guard is defined but the write paths do not call it"
