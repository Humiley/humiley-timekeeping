# -*- coding: utf-8 -*-
"""Many rows in one request — without opening a second, weaker door into every collection.

A 500-task import was 500 requests paced under the write rate limit: correct, and two and a half
minutes. `/api/coll/<name>/bulk` takes up to 250 rows at a time, so the same programme is two
requests and a few seconds.

The whole safety of it rests on one decision: every item goes through `_coll_add`, the SAME function
the single-item POST uses. `_coll_add` writes its outcome to the socket, so the bulk handler swaps
`_json`/`_err` for collectors and restores them in a `finally`. That is uglier than re-implementing
the checks and it is the reason this is safe — a bulk path with its own validation is a door that no
per-collection guard is watching, which is the exact shape tests/test_module_family_coverage.py
exists to catch.

Three things are pinned here, and the second and third are the ones that would rot quietly:
  · the guards still fire, per item;
  · the limiter is charged for ROWS, not for the one request that carried them — otherwise the
    endpoint hands back the flood it was added inside;
  · `_json`/`_err` are restored even when a row raises, or every later response in that request is
    written into a dictionary nobody reads.
"""
import app
import db
import pytest


@pytest.fixture
def proj():
    p = db.put_collection_item("pm_projects", {"name": "ZZ Bulk", "manager": "Tran Van Minh"})
    yield p
    for r in db.list_collection("pm_tasks"):
        if r.get("projectId") == p["id"]:
            try:
                db.delete_collection_item("pm_tasks", r["id"])
            except Exception:
                pass
    try:
        db.delete_collection_item("pm_projects", p["id"])
    except Exception:
        pass


class _H(app.Handler):
    """The handler without a socket. _json/_err are captured so the bulk result can be read."""
    def __init__(self):
        self.captured = None

    def _json(self, obj, status=200):
        self.captured = ("json", status, obj)
        return self.captured

    def _err(self, msg, status=400):
        self.captured = ("err", status, msg)
        return self.captured

    def _rate_check(self, bucket, limit, window):
        self.buckets = getattr(self, "buckets", [])
        self.buckets.append((bucket, limit, window))
        return True


ADMIN = {"id": "U-A", "name": "Admin", "role": "admin", "level": "admin"}


def _bulk(items, name="pm_tasks", h=None):
    h = h or _H()
    h._coll_add_bulk(ADMIN, name, {"items": items})
    return h, h.captured


# ── it works ────────────────────────────────────────────────────────────────────────────────────
def test_many_rows_in_one_request(base_url, proj):
    rows = [{"projectId": proj["id"], "name": "T%d" % i, "wbs": "1.%d" % i} for i in range(60)]
    h, (kind, status, out) = _bulk(rows)
    assert kind == "json", out
    assert out["createdCount"] == 60, out
    assert out["failedCount"] == 0, out["failed"]
    assert len({t["id"] for t in out["created"]}) == 60, "ids must be distinct"


def test_an_empty_batch_is_not_an_error(base_url):
    kind, status, out = _bulk([])[1]
    assert kind == "json" and out["created"] == []


def test_a_batch_over_the_cap_is_refused_with_the_number(base_url, proj):
    rows = [{"projectId": proj["id"], "name": "T%d" % i} for i in range(app.Handler.BULK_MAX + 1)]
    kind, status, msg = _bulk(rows)[1]
    assert kind == "err" and status == 413
    assert str(app.Handler.BULK_MAX) in msg, \
        "a cap that does not say what it is leaves the caller guessing the chunk size: %r" % msg


def test_items_must_be_a_list(base_url):
    h = _H()
    h._coll_add_bulk(ADMIN, "pm_tasks", {"items": "not a list"})
    assert h.captured[0] == "err" and h.captured[1] == 400
    h2 = _H()
    h2._coll_add_bulk(ADMIN, "pm_tasks", {})
    assert h2.captured[0] == "err"


# ── partial success is reported per row, with its index ─────────────────────────────────────────
def test_a_bad_row_fails_alone_and_is_named(base_url, proj):
    """The reported bug this whole line of work came from was a count with no reason. A batch that
    answers 200 and says only "40 created" repeats it at a larger scale."""
    rows = [{"projectId": proj["id"], "name": "good 1"},
            {"projectId": proj["id"], "name": "good 2"}]
    rows.insert(1, "not a dict")                       # _coll_add refuses a non-dict body
    kind, status, out = _bulk(rows)[1]
    assert kind == "json"
    assert out["createdCount"] == 2, out
    assert out["failedCount"] == 1, out
    assert out["failed"][0]["index"] == 1, \
        "the index is what lets the browser point at the row in the file: %r" % out["failed"]
    assert out["failed"][0]["error"], "a refusal with no reason is the bug, not the fix"


def test_one_row_raising_does_not_take_the_batch_down(base_url, proj):
    """`_coll_add` is a large function over user data. If it raises, the other 249 rows must still
    be written and the one that blew up reported — not the whole request 500ing."""
    class Boom(_H):
        def _coll_add(self, u, name, body):
            if body.get("name") == "boom":
                raise ValueError("kaboom")
            return app.Handler._coll_add(self, u, name, body)

    h = Boom()
    h._coll_add_bulk(ADMIN, "pm_tasks", {"items": [
        {"projectId": proj["id"], "name": "a"},
        {"projectId": proj["id"], "name": "boom"},
        {"projectId": proj["id"], "name": "b"}]})
    kind, status, out = h.captured
    assert kind == "json"
    assert out["createdCount"] == 2 and out["failedCount"] == 1
    assert "kaboom" in out["failed"][0]["error"]


# ── the guards still fire, per item ─────────────────────────────────────────────────────────────
def test_every_item_goes_through_coll_add(base_url, proj):
    """Not "a bulk path that does the same checks" — the SAME function. Counted, so a refactor that
    quietly inlines the validation fails here."""
    calls = []

    class Counting(_H):
        def _coll_add(self, u, name, body):
            calls.append(name)
            return app.Handler._coll_add(self, u, name, body)

    h = Counting()
    h._coll_add_bulk(ADMIN, "pm_tasks", {"items": [
        {"projectId": proj["id"], "name": "x"}, {"projectId": proj["id"], "name": "y"}]})
    assert calls == ["pm_tasks", "pm_tasks"], calls


def test_an_unknown_collection_is_refused_for_every_row(base_url):
    kind, status, out = _bulk([{"name": "x"}], name="not_a_collection")[1]
    assert kind == "json" and out["failedCount"] == 1 and out["createdCount"] == 0


def test_a_confidential_collection_is_refused(base_url):
    """The speak-up channel refuses all four verbs on the single-item route. Bulk must not be the
    way around it."""
    coll = sorted(app.Handler.CONFIDENTIAL)[0]
    kind, status, out = _bulk([{"name": "x"}], name=coll)[1]
    assert out["failedCount"] == 1 and out["createdCount"] == 0


def test_the_route_uses_the_same_door_as_the_single_post(base_url):
    src = open(app.__file__, encoding="utf-8").read()
    i = src.index('_parts[1] == "bulk"')
    seg = src[i - 900:i + 400]
    assert "_mgr" in seg and "self._guard(lambda u: self._coll_add_bulk(u, name, body), manager=_mgr)" in seg, \
        "the bulk route must carry the SAME manager gate the single-item POST beside it does"


# ── the limiter is charged for rows, not for the request ────────────────────────────────────────
def test_the_limiter_is_charged_for_the_rows(base_url, proj):
    h, _ = _bulk([{"projectId": proj["id"], "name": "T%d" % i} for i in range(5)])
    buckets = [b[0] for b in getattr(h, "buckets", [])]
    assert "bulkwrite" in buckets, (
        "without a per-ROW budget this endpoint hands back the write flood it was added inside: "
        "250 rows x 240 requests a minute. Buckets seen: %r" % buckets)


def test_a_spent_row_budget_stops_the_batch(base_url, proj):
    class Refusing(_H):
        def _rate_check(self, bucket, limit, window):
            if bucket == "bulkwrite":
                self._err("Too many requests", 429)
                return False
            return True

    h = Refusing()
    out = h._coll_add_bulk(ADMIN, "pm_tasks", {"items": [{"projectId": proj["id"], "name": "z"}]})
    assert out is None, "must return without writing when the limiter refuses"
    assert h.captured[1] == 429
    assert not [t for t in db.list_collection("pm_tasks")
                if t.get("projectId") == proj["id"] and t.get("name") == "z"], \
        "a refused batch must write nothing at all"


# ── and the response writers are put back ───────────────────────────────────────────────────────
def test_json_and_err_are_restored_afterwards(base_url, proj):
    """The handler swaps its own _json/_err to collect per-item outcomes. If the `finally` ever goes,
    every later response in the same request is written into a dictionary nobody reads — the request
    just hangs, and nothing in the log says why."""
    h = _H()
    h._coll_add_bulk(ADMIN, "pm_tasks", {"items": [{"projectId": proj["id"], "name": "q"}]})
    assert "_json" not in h.__dict__, "an instance attribute is still shadowing _json"
    assert "_err" not in h.__dict__, "an instance attribute is still shadowing _err"
    h.captured = None
    h._json({"after": True})
    assert h.captured == ("json", 200, {"after": True}), "the class method is not reachable again"


def test_restored_even_when_a_row_raises(base_url, proj):
    class Boom(_H):
        def _coll_add(self, u, name, body):
            raise RuntimeError("nope")

    h = Boom()
    h._coll_add_bulk(ADMIN, "pm_tasks", {"items": [{"projectId": proj["id"], "name": "r"}]})
    assert "_json" not in h.__dict__ and "_err" not in h.__dict__
