"""Optimistic concurrency on the generic collection store.

Every write carries a server-owned, monotonically-incrementing `_rev`. A PATCH may send an
`If-Match: <rev>` precondition; if the stored rev has moved on since the caller loaded the record
(someone else saved in between), the server returns 409 instead of letting the blind full-document
PATCH silently clobber the other edit. The precondition is opt-in — a PATCH without If-Match still
succeeds (and still bumps the rev), so nothing regresses for callers that don't participate yet.
"""
import db


def _mk(api, tokens, name="Concurrency Test"):
    st, b = api("POST", "/api/coll/schedules", tokens["admin"], {"name": name, "start": "08:00"})
    assert st == 200, b
    return b["item"]


def test_create_stamps_rev_1(api, tokens):
    it = _mk(api, tokens, "Born-With-Rev")
    assert it["_rev"] == 1, "a freshly-created record starts at _rev 1"
    # and a read of the stored record shows the same rev
    assert db.get_collection_item("schedules", it["id"])["_rev"] == 1


def test_patch_without_precondition_still_works_and_bumps_rev(api, tokens):
    it = _mk(api, tokens, "No-Precondition")
    # a plain full-object PATCH with NO If-Match (the legacy path) must still succeed...
    st, b = api("PATCH", "/api/coll/schedules/" + it["id"], tokens["admin"], dict(it, start="09:00"))
    assert st == 200, b
    assert b["item"]["_rev"] == 2 and b["item"]["start"] == "09:00"   # ...and advance the rev


def test_matching_ifmatch_succeeds_and_advances(api, tokens):
    it = _mk(api, tokens, "Good-IfMatch")
    st, b = api("PATCH", "/api/coll/schedules/" + it["id"], tokens["admin"],
                dict(it, start="10:00"), headers={"If-Match": it["_rev"]})   # If-Match: 1 == stored 1
    assert st == 200, b
    assert b["item"]["_rev"] == 2
    # the returned rev is usable for the next edit
    st2, b2 = api("PATCH", "/api/coll/schedules/" + it["id"], tokens["admin"],
                  dict(b["item"], start="11:00"), headers={"If-Match": b["item"]["_rev"]})   # If-Match: 2
    assert st2 == 200 and b2["item"]["_rev"] == 3


def test_stale_ifmatch_conflicts_and_leaves_record_untouched(api, tokens):
    it = _mk(api, tokens, "Stale-IfMatch")                # _rev 1
    # someone else saves first (bumps stored rev to 2)
    api("PATCH", "/api/coll/schedules/" + it["id"], tokens["admin"], dict(it, start="12:00"))
    # we try to save holding the STALE rev 1 -> 409, our change is rejected
    st, b = api("PATCH", "/api/coll/schedules/" + it["id"], tokens["admin"],
                dict(it, start="23:59"), headers={"If-Match": 1})
    assert st == 409, b
    assert b.get("conflict") is True and b.get("currentRev") == 2
    # the record still holds the other person's value, not ours
    row = db.get_collection_item("schedules", it["id"])
    assert row["start"] == "12:00" and row["_rev"] == 2


def test_lost_update_two_readers_second_must_refetch(api, tokens):
    it = _mk(api, tokens, "Two-Readers")                  # both readers see _rev 1
    a_view = dict(it)
    b_view = dict(it)
    # Reader A commits first
    stA, bA = api("PATCH", "/api/coll/schedules/" + it["id"], tokens["admin"],
                  dict(a_view, note="A wrote"), headers={"If-Match": a_view["_rev"]})
    assert stA == 200 and bA["item"]["_rev"] == 2
    # Reader B, still holding rev 1, is blocked — the classic lost update is prevented
    stB, bB = api("PATCH", "/api/coll/schedules/" + it["id"], tokens["admin"],
                  dict(b_view, note="B wrote"), headers={"If-Match": b_view["_rev"]})
    assert stB == 409 and bB.get("currentRev") == 2
    # B re-fetches, re-applies on top of A's version, and now succeeds
    fresh = db.get_collection_item("schedules", it["id"])
    stB2, bB2 = api("PATCH", "/api/coll/schedules/" + it["id"], tokens["admin"],
                    dict(fresh, note="B wrote after refetch"), headers={"If-Match": fresh["_rev"]})
    assert stB2 == 200 and bB2["item"]["_rev"] == 3 and bB2["item"]["note"] == "B wrote after refetch"


def test_put_collection_item_bumps_rev_and_ignores_client_value(base_url):
    # db-level: the stored rev is server-owned. A client-supplied _rev is never trusted as the source
    # of truth — each write increments the STORED rev regardless of what the caller put in the dict.
    a = db.put_collection_item("octest", {"id": "oc-1", "v": 1})
    assert a["_rev"] == 1
    b = db.put_collection_item("octest", {"id": "oc-1", "v": 2, "_rev": 999})   # bogus client rev
    assert b["_rev"] == 2, "server increments stored rev; a client _rev cannot jump or freeze it"
    c = db.put_collection_item("octest", {"id": "oc-1", "v": 3})
    assert c["_rev"] == 3
