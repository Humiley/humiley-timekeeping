# -*- coding: utf-8 -*-
"""The unread badge is answered from an index instead of by reading every message ever posted.

1.08 ms against 29.8 ms at 25,000 messages, and it grows with the number of PROJECTS rather than the
history. A partial expression index on (projectId, ts-as-text) — partial so it stays small on a table
holding every collection, expressions so no data is copied anywhere and SQLite maintains it through
inserts, updates and DELETES. That last one is why this is an index and not a table: a hand-kept
table would have to be maintained on delete, and db.delete_collection_item does not go through
anything that could.

WHY THIS NEEDED A TEST FILE OF ITS OWN. Moving the comparison into SQL changes what "greater than"
means. Python compared `str(ts) <= str(watermark)` — TEXT — while SQL applies type affinity, so a
number and a numeric string order differently. The index is therefore built on an expression that
reproduces `str(ts or "")`, and the only way to believe that is to run both and diff them:

  · a falsy ts (absent, null, 0, "", false) becomes NULL, which is never greater than anything —
    the same thing `"" <= anything` does on the Python side
  · a JSON true becomes 'True', because that is what str() produces
  · the watermark is passed as TEXT and never as None, because `ts > NULL` is NULL and a project
    nobody has opened would then report ZERO unread instead of all of it

Out of scope by choice: a ts that is a JSON object, array or boolean, where SQL and Python disagree
about what str() would produce. None can occur — _coll_add overwrites whatever a client sends with
_utc_now_ms(), which is a FIXED-WIDTH ISO-8601 STRING, and the test at the bottom holds it to that.
That is also why the comparison was always right: at constant width, text order is time order.

(The boolean case is handled correctly by the index expression but NOT by the scan fallback, where
json_extract turns JSON true into 1 and str(1) is not str(True). Recorded rather than fixed: the
fallback only runs on a host that has JSON1 but could not build the index, and no such timestamp can
reach the database anyway.)
"""
import json
import os
import sys

import pytest

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, ROOT)

import db  # noqa: E402

# What _utc_now_ms actually writes: a fixed-width ISO-8601 string, not a number. That matters more
# than anything else here — at constant width a text comparison IS the chronological one, which is
# why `str(ts) <= str(watermark)` has always been right, and why the index reproducing it is safe.
WM = "2026-09-03T02:00:00.000Z"


def _reference(rows, me, vis, read):
    """The loop as it stood before any of this, over whole parsed records."""
    out, mentions = {}, {}
    for m in rows:
        pid = m.get("projectId")
        if not pid or (vis is not None and pid not in vis):
            continue
        if (m.get("authorId") or "") == me:
            continue
        if str(m.get("ts") or "") <= str(read.get(pid) or ""):
            continue
        out[pid] = out.get(pid, 0) + 1
        if any((x or {}).get("empId") == me for x in (m.get("mentions") or [])):
            mentions[pid] = mentions.get(pid, 0) + 1
    return out, mentions


# Every timestamp shape the expression has to reproduce. The comment is the value Python's
# `str(ts or "")` produces, which is what the index must agree with.
TS_CASES = [
    ("iso-newer", "2026-09-03T02:00:00.001Z"),   # counted
    ("iso-older", "2026-09-03T01:59:59.999Z"),   # skipped
    ("iso-equal", WM),                           # equal -> skipped
    ("iso-much-newer", "2026-12-31T23:59:59.999Z"),
    ("zero", 0),                  # str(0 or "")     == ''  -> always skipped
    ("empty", ""),                # ''                      -> always skipped
    ("null", None),               # ''                      -> always skipped
    ("false", False),             # ''                      -> always skipped
    ("int", 1788000000000),       # a bare number, from an import or an older client
    ("float", 1788000000.5),
    ("text", "zzz-not-a-time"),   # sorts above any ISO date -> counted
]


@pytest.fixture
def nasty(base_url):
    made = []

    def add(rid, **kw):
        kw["id"] = rid
        db.put_collection_item("pm_chat", kw)
        made.append(rid)

    # Each shape goes into BOTH a project that has a watermark and one that has none, because the
    # two ask different questions of the expression and a corpus with only the first cannot tell a
    # correct expression from several wrong ones. Against an ISO watermark every candidate ordering
    # — text, numeric, NULL — happens to give the same answer for a falsy or numeric timestamp; it
    # is only against the EMPTY watermark that `str(0 or "")` being '' rather than '0', and text
    # rather than numeric comparison, change what is counted. Mutation testing found this: two
    # broken expressions passed against the first project alone.
    for i, (label, ts) in enumerate(TS_CASES):
        for pid, tag in (("P-WM", "w"), ("P-RAW", "r")):
            row = {"projectId": pid, "authorId": "OTHER", "text": label}
            row["ts"] = ts
            add("t%s%02d" % (tag, i), **row)
    add("t90", projectId="P-WM", authorId="OTHER", text="absent ts")          # no ts key at all
    add("t89", projectId="P-RAW", authorId="OTHER", text="absent ts")         # and with no watermark
    add("t91", projectId="P-NEW", authorId="OTHER", ts="2026-09-03T02:00:01.000Z",
        text="never opened")
    add("t92", projectId="P-NEW", authorId="OTHER", ts="2026-09-03T02:00:02.000Z",
        mentions=[{"empId": "HML-ADM"}], text="mentions me")
    add("t93", projectId="P-NEW", authorId="HML-ADM", ts="2026-09-03T02:00:03.000Z", text="my own")
    add("t94", authorId="OTHER", ts="2026-09-03T02:00:04.000Z", text="no project")
    add("t95", projectId="", authorId="OTHER", ts="2026-09-03T02:00:05.000Z", text="blank project")
    yield
    for rid in made:
        try:
            db.delete_collection_item("pm_chat", rid)
        except Exception:
            pass


def _read_doc():
    db.put_collection_item("pm_chat_read", {"id": "HML-ADM", "empId": "HML-ADM",
                                            "read": {"P-WM": WM}})
    return {"P-WM": WM}


def test_the_index_exists_and_the_query_uses_it(nasty):
    conn = db.get_conn()
    try:
        assert conn.execute("SELECT name FROM sqlite_master WHERE type='index' "
                            "AND name='idx_pm_chat_unread'").fetchone(), "the index was not created"
        plan = " | ".join(str(r[-1]) for r in conn.execute(
            "EXPLAIN QUERY PLAN SELECT json_extract(data,'$.mentions') FROM collections "
            "INDEXED BY idx_pm_chat_unread WHERE coll='pm_chat' AND " + db._PM_CHAT_PID +
            " = ? AND " + db._PM_CHAT_TS + " > ?", ("P-WM", "0")).fetchall())
    finally:
        conn.close()
    assert "idx_pm_chat_unread" in plan, plan
    assert "SEARCH" in plan, (
        "the plan is %r — a SCAN means it is walking the whole index rather than seeking into the "
        "project, which is most of the saving" % plan)


def test_every_timestamp_shape_agrees_with_the_old_loop(api, tokens, nasty):
    """The differential test. If the SQL expression and str(ts or "") ever disagree, this is where."""
    read = _read_doc()
    st, b = api("GET", "/api/pm/chat/summary", tokens["admin"])
    assert st == 200, b
    want_unread, want_mentions = _reference(db.list_collection("pm_chat"), "HML-ADM", None, read)
    assert b["unread"] == want_unread, (
        "the index and the old loop disagree.\n  index: %r\n  loop : %r" % (b["unread"], want_unread))
    assert b["mentions"] == want_mentions
    assert b["total"] == sum(want_unread.values())


def test_a_project_with_no_watermark_reports_all_of_it(api, tokens, nasty):
    """`ts > NULL` is NULL. Bound wrongly, P-NEW would report zero unread instead of two."""
    _read_doc()
    st, b = api("GET", "/api/pm/chat/summary", tokens["admin"])
    assert st == 200, b
    assert b["unread"].get("P-NEW") == 2, (
        "a project nobody has opened must report every message in it that is not the caller's own; "
        "got %r" % (b["unread"],))
    assert b["mentions"].get("P-NEW") == 1


def test_a_message_with_no_project_is_not_counted(api, tokens, nasty):
    _read_doc()
    st, b = api("GET", "/api/pm/chat/summary", tokens["admin"])
    assert "" not in b["unread"] and None not in b["unread"], b["unread"]


def test_the_index_keeps_up_with_deletes(api, tokens, nasty):
    """The reason this is an index and not a table somebody maintains.

    db.delete_collection_item issues a bare DELETE and knows nothing about any of this.
    """
    _read_doc()
    before = api("GET", "/api/pm/chat/summary", tokens["admin"])[1]["unread"].get("P-NEW")
    db.delete_collection_item("pm_chat", "t91")
    after = api("GET", "/api/pm/chat/summary", tokens["admin"])[1]["unread"].get("P-NEW")
    assert before == 2 and after == 1, "before=%r after=%r" % (before, after)


def test_the_scan_fallback_gives_the_same_answer(api, tokens, nasty, monkeypatch):
    """A SQLite without JSON1 cannot build the index. That host must be slower, never wrong."""
    monkeypatch.setattr(db, "pm_chat_project_ids", lambda: None)
    read = _read_doc()
    st, b = api("GET", "/api/pm/chat/summary", tokens["admin"])
    assert st == 200, b
    want_unread, want_mentions = _reference(db.list_collection("pm_chat"), "HML-ADM", None, read)
    assert b["unread"] == want_unread
    assert b["mentions"] == want_mentions


def test_the_server_stamps_the_timestamp_so_a_client_cannot_choose_its_type(api, tokens):
    """The invariant the whole equivalence rests on.

    A ts that is a JSON object, array or boolean is outside what the index expression reproduces.
    None can exist, because _coll_add overwrites whatever the client sent with _utc_now_ms() — a
    fixed-width ISO string. This is the test that keeps that true.
    """
    st, b = api("POST", "/api/coll/pm_chat", tokens["admin"],
                {"projectId": "P-STAMP", "body": "hello", "ts": {"not": "a time"}})
    try:
        assert st == 200, b
        stored = db.get_collection_item("pm_chat", (b.get("item") or b).get("id"))
        ts = stored.get("ts")
        assert isinstance(ts, str), "the server must stamp ts itself; a client set %r" % (ts,)
        assert len(ts) == 24 and ts.endswith("Z") and ts[4] == "-", \
            "expected the fixed-width ISO form _utc_now_ms writes, got %r" % (ts,)
    finally:
        try:
            db.delete_collection_item("pm_chat", (b.get("item") or b).get("id"))
        except Exception:
            pass


def test_it_does_not_read_the_whole_collection(base_url):
    """A count, not a stopwatch. The old path parsed every message to answer; this must not."""
    ids = []
    try:
        for i in range(600):
            rid = "cnt%04d" % i
            db.put_collection_item("pm_chat", {"id": rid, "projectId": "P%d" % (i % 4),
                                               "authorId": "OTHER",
                                               "ts": "2026-09-03T02:00:00.%03dZ" % (i % 1000),
                                               "text": "x" * 2000})
            ids.append(rid)
        seen = {"n": 0}
        real = db.list_collection

        def counted(coll):
            if coll == "pm_chat":
                seen["n"] += 1
            return real(coll)

        db.list_collection = counted
        try:
            # a DIFFERENT author, or the exclusion would remove every row and the assertion below
            # would pass on an empty result — which proves nothing at all
            n, m = db.pm_chat_unread("P1", "2026-09-03T02:00:00.300Z", "SOMEBODY-ELSE", "HML-ADM")
        finally:
            db.list_collection = real
        assert seen["n"] == 0, "the indexed path fell back to reading the whole collection"
        # 600 messages over 4 projects: P1 holds 150, and 75 of them are past the watermark. Exact on
        # purpose — "fewer than all of them" would also be satisfied by a query that counted the
        # wrong 149.
        assert n == 75, ("expected the 75 messages of P1 past the watermark, out of 600 in the "
                         "collection, got %d" % n)
        assert m == 0, "none of them mention anybody"
    finally:
        for rid in ids:
            try:
                db.delete_collection_item("pm_chat", rid)
            except Exception:
                pass
