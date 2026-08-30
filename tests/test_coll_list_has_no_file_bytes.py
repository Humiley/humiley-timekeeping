# -*- coding: utf-8 -*-
"""A project register lists its records; it does not ship their files.

Reported from production: opening a project's Quality tab timed out after 30 seconds and Safari
reloaded the tab with "This webpage was reloaded because a problem occurred" — which is what a
browser does when a response will not fit in memory.

The cause is not slowness anywhere. Project records keep their attachment INLINE, as a base64 data:
URI on the row, so listing the collection ships every file of every record of every project. A
register of 200 inspection records with a photo each is a ~200 MB JSON response, sent to draw a table
whose File column is the word "Show".

The list carries metadata now — enough for the table to know a file exists, what it is called and how
big — and /api/coll/<name>/<id> serves that one row in full when somebody actually opens it.

WHAT MUST NOT BREAK, and is the reason the size test is not the only test here:
  · the table must still OFFER the file. The bytes it used to test are exactly what is gone, so a
    marker replaces them; get that wrong and every record with an attachment renders an em dash and
    the file looks lost rather than deferred.
  · the single-row route must not become a way around the list's access rules. It answers by running
    the LIST and picking the row out of the result, so a row you could not have listed is a row you
    cannot fetch — otherwise a scoped collection becomes readable one id at a time.
"""
import json
import os
import sys

import pytest

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, ROOT)

import db  # noqa: E402

BIG = "data:image/jpeg;base64," + ("A" * 400_000)   # one ~400 KB photo, as the app really stores it


@pytest.fixture(autouse=True)
def _clean_pm_quality():
    db.init_db()
    conn = db.get_conn()
    before = {k: v for k, v in conn.execute(
        "SELECT id, data FROM collections WHERE coll = 'pm_quality'").fetchall()} \
        if conn.execute("SELECT name FROM sqlite_master WHERE type='table' AND name='collections'").fetchone() else {}
    conn.close()
    yield
    conn = db.get_conn()
    conn.execute("DELETE FROM collections WHERE coll = 'pm_quality'")
    for i, d in before.items():
        conn.execute("INSERT INTO collections (coll,id,data) VALUES ('pm_quality',?,?)", (i, d))
    conn.commit()
    conn.close()


def _seed(n=12):
    for i in range(n):
        db.put_collection_item("pm_quality", {
            "id": "q%d" % i, "projectId": "P1", "title": "Record %d" % i,
            "attachment": BIG, "attachmentName": "photo%d.jpg" % i,
        })
    db.put_collection_item("pm_quality", {
        "id": "multi", "projectId": "P1", "title": "Multi",
        "attachments": [{"name": "a.pdf", "url": BIG}, {"name": "b.pdf", "url": BIG}],
    })


def _call(fn, *a):
    """Run a Handler method that ends in self._json, and capture what it would have sent."""
    import app
    cap = {}

    class Fake(app.Handler):
        def __init__(self):
            pass

    h = Fake()
    h._caller_level = lambda u: "admin"
    h._json = lambda obj, status=200: cap.setdefault("r", (obj, status))
    h._err = lambda msg, status=400: cap.setdefault("r", ({"error": msg}, status))
    getattr(h, fn)({"id": "u1", "name": "Admin", "level": "admin"}, *a)
    return cap.get("r", ({}, 500))


def test_the_list_does_not_carry_the_files(_clean_pm_quality):
    _seed()
    obj, status = _call("_coll_list", "pm_quality")
    assert status == 200
    size = len(json.dumps(obj))
    # 13 records × ~400 KB is >5 MB of payload if the bytes travel. The budget is generous on
    # purpose — this is about an order of magnitude, not a byte count that needs tuning.
    assert size < 200_000, (
        "the list response is %d bytes for 13 records; the attachments are still in it" % size)
    for it in obj["items"]:
        assert not it.get("attachment"), "a row still carries its file payload"
        for a in (it.get("attachments") or []):
            assert not a.get("url"), "a row still carries a multi-file payload"


def test_but_the_table_can_still_tell_there_is_a_file(_clean_pm_quality):
    """The marker the File column reads. Without it every record renders an em dash."""
    _seed()
    obj, _ = _call("_coll_list", "pm_quality")
    rows = {it["id"]: it for it in obj["items"]}
    assert rows["q0"]["hasFile"] is True
    assert rows["q0"]["attachmentName"] == "photo0.jpg", "the name must survive for the tooltip"
    assert rows["q0"]["attachmentBytes"] == len(BIG), "the size must survive"
    assert rows["multi"]["hasFile"] is True
    assert [a["name"] for a in rows["multi"]["attachments"]] == ["a.pdf", "b.pdf"], \
        "one link per file is drawn from these names"

    db.put_collection_item("pm_quality", {"id": "none", "projectId": "P1", "title": "No file"})
    obj, _ = _call("_coll_list", "pm_quality")
    plain = next(it for it in obj["items"] if it["id"] == "none")
    assert not plain.get("hasFile"), "a record with no attachment must not offer a link"


def test_the_single_row_route_returns_the_bytes(_clean_pm_quality):
    _seed()
    obj, status = _call("_coll_one", "pm_quality", "q3")
    assert status == 200
    assert obj["item"]["attachment"] == BIG, "opening a file is the one place the bytes belong"
    assert obj["item"]["attachmentName"] == "photo3.jpg"

    multi, status = _call("_coll_one", "pm_quality", "multi")
    assert status == 200
    assert [a["url"] for a in multi["item"]["attachments"]] == [BIG, BIG]


def test_the_single_row_route_never_hands_back_the_approval_token(_clean_pm_quality):
    """The list strips it; a route that returns the row IN FULL must strip it too.

    The one-click approval token is what the emailed /capprove link carries. A requester who could
    read their own token could approve their own record. The list has stripped it for a long time —
    this route is new, and "in full" was very nearly literal. Found by mutation: deleting the strip
    broke nothing, because nothing looked.
    """
    db.put_collection_item("pm_quality", {"id": "tok", "projectId": "P1", "title": "T",
                                          "attachment": BIG, "token": "secret-approval-token"})
    obj, status = _call("_coll_one", "pm_quality", "tok")
    assert status == 200
    assert "token" not in obj["item"], "the single-row route handed back the approval token"
    assert obj["item"]["attachment"] == BIG, "and it must still carry the file it exists to serve"


def test_a_missing_row_is_a_404_not_a_crash(_clean_pm_quality):
    _seed()
    obj, status = _call("_coll_one", "pm_quality", "nope")
    assert status == 404


def test_the_single_row_route_cannot_reach_a_row_the_list_would_hide(_clean_pm_quality):
    """The access rules live in the list, so the single-row route runs the list.

    Proved by making the list return nothing and checking the fetch fails with it — if _coll_one
    read the collection directly, this would still hand back the row and every scoped collection
    would be readable one id at a time.
    """
    import app
    _seed()
    cap = {}

    class Fake(app.Handler):
        def __init__(self):
            pass

    h = Fake()
    h._caller_level = lambda u: "admin"
    h._json = lambda obj, status=200: cap.setdefault("r", (obj, status))
    h._err = lambda msg, status=400: cap.setdefault("r", ({"error": msg}, status))
    h._coll_list = lambda u, name: h._json({"items": []})       # the list shows this caller nothing
    h._coll_one({"id": "u1", "level": "staff"}, "pm_quality", "q3")
    obj, status = cap["r"]
    assert status == 404, "a row the list would not show must not be fetchable by id"


def test_pm_chat_keeps_its_attachments(_clean_pm_quality):
    """Excluded on purpose: chat files render inline in the thread, so stripping them empties the
    conversation rather than deferring it."""
    db.put_collection_item("pm_chat", {"id": "m1", "projectId": "P1", "text": "hi",
                                          "attachments": [{"name": "x.png", "url": BIG}]})
    try:
        obj, status = _call("_coll_list", "pm_chat")
        assert status == 200
        m = next((x for x in obj["items"] if x["id"] == "m1"), None)
        assert m and m["attachments"][0]["url"] == BIG
    finally:
        db.delete_collection_item("pm_chat", "m1")
