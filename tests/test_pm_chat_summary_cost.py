# -*- coding: utf-8 -*-
"""The unread badge stops parsing every message ever posted to produce a number.

/api/pm/chat/summary called db.list_collection("pm_chat"), which json.loads the WHOLE record —
bodies, attachments and all — for every message in the company, on every sign-in, for every user
with the Projects app. Measured: 1.8 ms at 200 messages, 8.5 ms at 2,000, 35.7 ms at 10,000,
89.3 ms at 25,000. The response is ~340 bytes at every one of those sizes.

It now pulls four scalars per row out of SQLite instead. THE FILTER IS UNCHANGED, and that is the
whole design: the four ways this goes wrong are all in the filter, not in the parsing.

  1. a per-project watermark is not a GROUP BY — one global cut-off loses whole projects and
     invents unread in others
  2. a watermark bound as NULL makes `ts > NULL` evaluate to NULL, which is not true, so a project
     nobody has ever opened reports ZERO unread instead of all of it. That is the failure this
     whole speed pass has been about: a screen that renders perfectly and says less than the truth
  3. a derived table would have to be maintained on DELETE, which db.delete_collection_item does
     not go through
  4. a message with no projectId is skipped here, and would not be by a plain aggregate

Reading fewer FIELDS costs none of that — same rows, same comparisons, same order — and the tests
below hold the new endpoint against the old logic re-implemented as a reference, rather than against
numbers I would have had to write down by hand.
"""
import json
import os
import sys
import time

import pytest

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, ROOT)

import db  # noqa: E402


def _reference(rows, me, vis, read):
    """The endpoint's loop exactly as it was before, over whole parsed records."""
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


WM = 1788000000000        # a real _utc_now_ms watermark, not a toy integer


@pytest.fixture
def corpus(base_url):
    """Every shape that has ever made this kind of count wrong.

    Timestamps are full 13-digit milliseconds because that is what _utc_now_ms writes and because
    the comparison is `str(ts) <= str(watermark)` — LEXICOGRAPHIC. At equal width that is the same
    as numeric, which is why it has never mattered in production; with toy integers it is not, and a
    fixture using them tests a comparison the app never performs. The oddity is left exactly as it
    was: this change is about what gets parsed, and quietly altering a comparison inside a
    performance fix is how a behaviour change ships without anyone deciding to make one.
    """
    made = []

    def add(i, **kw):
        row = dict(kw)
        row["id"] = "m%04d" % i
        db.put_collection_item("pm_chat", row)
        made.append(row["id"])
        return row

    rows, n = [], 0
    # P-OPEN: read up to WM. Two of these are newer.
    for t in (WM - 400, WM - 100, WM, WM + 100, WM + 900):
        n += 1
        rows.append(add(n, projectId="P-OPEN", authorId="OTHER", ts=t, text="x"))
    # P-NEVER: no watermark at all. Trap 2 lives here.
    for t in (WM + 10, WM + 20, WM + 30):
        n += 1
        rows.append(add(n, projectId="P-NEVER", authorId="OTHER", ts=t, text="x"))
    n += 1
    rows.append(add(n, projectId="P-NEVER", authorId="OTHER", ts=WM + 40,
                    mentions=[{"empId": "HML-ADM"}], text="mentions me"))
    n += 1
    rows.append(add(n, projectId="P-NEVER", authorId="OTHER", ts=WM + 50,
                    mentions=[{"empId": "SOMEONE"}], text="mentions someone else"))
    # the caller's own words are never unread
    n += 1
    rows.append(add(n, projectId="P-OPEN", authorId="HML-ADM", ts=WM + 999, text="mine"))
    # no projectId at all, and a blank one. Trap 4.
    n += 1
    rows.append(add(n, authorId="OTHER", ts=WM + 999, text="orphan"))
    n += 1
    rows.append(add(n, projectId="", authorId="OTHER", ts=WM + 999, text="blank pid"))
    # ts stored as a STRING beside ts stored as a number
    n += 1
    rows.append(add(n, projectId="P-OPEN", authorId="OTHER", ts=str(WM + 700), text="stringy"))
    # missing ts entirely — skipped, because "" <= ""
    n += 1
    rows.append(add(n, projectId="P-NEVER", authorId="OTHER", text="no ts"))
    # empty mentions array
    n += 1
    rows.append(add(n, projectId="P-NEVER", authorId="OTHER", ts=WM + 60, mentions=[], text="x"))
    yield rows
    for rid in made:
        try:
            db.delete_collection_item("pm_chat", rid)
        except Exception:
            pass


def test_the_fields_read_match_the_records_stored(corpus):
    """db.collection_fields is the whole change; if it does not agree with the parsed rows on this
    corpus, nothing above it can be right."""
    got = db.collection_fields("pm_chat", ("projectId", "authorId", "ts", "mentions"))
    parsed = db.list_collection("pm_chat")
    assert len(got) == len(parsed)
    for (pid, author, ts, mns), m in zip(got, parsed):
        assert pid == m.get("projectId")
        assert author == m.get("authorId")
        assert ts == m.get("ts")
        # arrays come back as JSON text on the fast path and as lists on the fallback
        if isinstance(mns, str):
            mns = json.loads(mns)
        assert (mns or []) == (m.get("mentions") or [])


def test_a_project_nobody_has_opened_reports_all_of_it_not_none(api, tokens, corpus):
    """Trap 2, stated as a test because it is the one that fails silently.

    P-NEVER has no entry in the read watermark. Under the SQL rewrite this endpoint deliberately did
    NOT get, `ts > NULL` evaluates to NULL, the rows vanish, and the badge reports nothing waiting
    on a project the person has never once opened.
    """
    db.put_collection_item("pm_chat_read", {"id": "HML-ADM", "empId": "HML-ADM",
                                            "read": {"P-OPEN": WM}})
    st, b = api("GET", "/api/pm/chat/summary", tokens["admin"])
    assert st == 200, b
    assert b["unread"].get("P-NEVER") == 6, (
        "a project with no watermark must count every message that has a timestamp — six of the "
        "seven, the seventh having no ts at all. Got %r" % (b["unread"],))


def test_the_new_summary_equals_the_old_loop_for_every_caller(api, tokens, corpus):
    """The strongest form available: hold the endpoint against the previous implementation, run over
    the same database, for callers with different visibility."""
    db.put_collection_item("pm_chat_read", {"id": "HML-ADM", "empId": "HML-ADM",
                                            "read": {"P-OPEN": WM}})
    db.put_collection_item("pm_chat_read", {"id": "HML-MGR", "empId": "HML-MGR", "read": {}})

    for who, uid in (("admin", "HML-ADM"), ("mgr", "HML-MGR")):
        st, b = api("GET", "/api/pm/chat/summary", tokens[who])
        assert st == 200, (who, b)
        read = (db.get_collection_item("pm_chat_read", uid) or {}).get("read") or {}
        # both fixtures are manager level or above, so visibility is "all projects"
        want_unread, want_mentions = _reference(db.list_collection("pm_chat"), uid, None, read)
        assert b["unread"] == want_unread, who
        assert b["mentions"] == want_mentions, who
        assert b["total"] == sum(want_unread.values()), who
        assert b["totalMentions"] == sum(want_mentions.values()), who

    # and the shape the traps are about, spelled out for the admin
    st, b = api("GET", "/api/pm/chat/summary", tokens["admin"])
    assert b["unread"].get("P-NEVER") == 6, \
        "a project with no watermark must count every message in it, not zero: %r" % (b["unread"],)
    assert b["unread"].get("P-OPEN") == 3, (
        "the two messages after the watermark plus the one stored with a STRING timestamp; never "
        "the caller's own: %r" % (b["unread"],))
    assert "" not in b["unread"] and None not in b["unread"], \
        "a message with no projectId was counted under a blank key"
    assert b["mentions"].get("P-NEVER") == 1, "the mention of this caller was lost"


def test_it_still_works_when_sqlite_has_no_json1(api, tokens, corpus, monkeypatch):
    """Production runs a different Python in a container and nothing here can see which. A badge
    count is not worth a 500, so the fast path falls back to the full parse."""
    real = db._rows

    def boom(sql, params=()):
        if "json_extract" in sql:
            raise db.sqlite3.OperationalError("no such function: json_extract")
        return real(sql, params)

    monkeypatch.setattr(db, "_rows", boom)
    db.put_collection_item("pm_chat_read", {"id": "HML-ADM", "empId": "HML-ADM",
                                            "read": {"P-OPEN": WM}})
    st, b = api("GET", "/api/pm/chat/summary", tokens["admin"])
    assert st == 200, b
    read = {"P-OPEN": WM}
    want_unread, want_mentions = _reference(db.list_collection("pm_chat"), "HML-ADM", None, read)
    assert b["unread"] == want_unread
    assert b["mentions"] == want_mentions


def test_it_reads_far_less_than_it_did(base_url):
    """A count, not a stopwatch — a timing on an idle runner is exactly what fails to notice a
    regression. This counts BYTES OF JSON PARSED, which is what the old version spent its time on.
    """
    big = "x" * 4000                      # a message with a real body
    ids = []
    try:
        for i in range(400):
            rid = "cost%04d" % i
            db.put_collection_item("pm_chat", {"id": rid, "projectId": "P1", "authorId": "OTHER",
                                               "ts": i, "text": big})
            ids.append(rid)

        parsed = sum(len(json.dumps(m)) for m in db.list_collection("pm_chat"))
        fields = db.collection_fields("pm_chat", ("projectId", "authorId", "ts", "mentions"))
        pulled = sum(len(str(v)) for row in fields for v in row if v is not None)

        assert parsed > 1_000_000, "the fixture is too small to prove anything: %d" % parsed
        assert pulled * 20 < parsed, (
            "the summary still reads %d characters where the old path read %d — it is not pulling "
            "scalars, it is parsing bodies again" % (pulled, parsed))
    finally:
        for rid in ids:
            try:
                db.delete_collection_item("pm_chat", rid)
            except Exception:
                pass
