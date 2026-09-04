# -*- coding: utf-8 -*-
"""A read that has not changed should cost a few hundred bytes, not a few hundred kilobytes.

/api/coll and every other JSON read carried NO validator of any kind — no ETag, no Last-Modified.
So every open of a screen re-serialised, re-compressed and re-sent the WHOLE collection even when
not one byte had changed since the request thirty seconds earlier. On a project carrying a
500-activity master schedule and a ~400-line detail programme whose rows each accumulate a per-day
log, that is the dominant cost of opening the Schedule tab, and it is paid again on every tab
switch, every navigation back into the project, and every expiry of the browser's 45s cache.

No client change was needed for any of it: fetch() with the default cache mode revalidates on its
own and hands JavaScript the cached 200 body, so nothing in the app ever sees a 304.

Two things make this safe rather than merely fast, and they are what this file exists to hold:

  1. A WRITE MUST CHANGE THE TAG. If it did not, a save would sit invisible behind a 304 and the
     speed-up would hide the very data it was meant to deliver faster. That is the whole risk of
     caching anything, and it is tested here through the real write endpoint.

  2. THE TAG MUST NOT BE A WAY TO READ SOMEBODY ELSE'S DATA. It is a hash of the response body,
     which every guard in _coll_list has ALREADY scoped to the caller — so two accounts entitled to
     different rows produce different bodies and therefore different tags. An account presenting
     another account's tag gets its own data, never a 304.

The fixtures here return status, headers AND raw bytes; the shared `api` fixture parses the body
away, and a byte count is exactly what several of these assertions are about.
"""
import json
import urllib.error
import urllib.request

import db
import pytest


def _raw(base_url, path, token=None, inm=None, method="GET", body=None):
    """status, headers, raw bytes — the three things a caching test is actually about."""
    data = json.dumps(body).encode() if body is not None else None
    req = urllib.request.Request(base_url + path, data=data, method=method)
    if data is not None:
        req.add_header("Content-Type", "application/json")
    if token:
        req.add_header("Authorization", "Bearer " + token)
    if inm:
        req.add_header("If-None-Match", inm)
    try:
        with urllib.request.urlopen(req, timeout=15) as r:
            return r.status, dict(r.headers), r.read()
    except urllib.error.HTTPError as e:
        return e.code, dict(e.headers), e.read()


@pytest.fixture
def rows():
    """A collection with enough in it that the saving is a fact rather than a rounding error."""
    proj = db.put_collection_item("pm_projects", {"name": "ZZ CondGet", "manager": "Admin User"})
    made = [db.put_collection_item("pm_tasks", {
        "projectId": proj["id"], "wbs": "8.%d" % i,
        "name": "activity %d with a realistic amount of text on the row" % i,
        "start": "2026-01-%02d" % ((i % 28) + 1), "finish": "2026-03-%02d" % ((i % 28) + 1),
        "assignee": "Nguyen Van A", "pctComplete": str(i % 100)}) for i in range(40)]
    yield proj
    for r in made:
        try:
            db.delete_collection_item("pm_tasks", r["id"])
        except Exception:
            pass
    try:
        db.delete_collection_item("pm_projects", proj["id"])
    except Exception:
        pass


def test_a_collection_read_carries_a_weak_validator(base_url, tokens, rows):
    st, h, b = _raw(base_url, "/api/coll/pm_tasks", tokens["admin"])
    assert st == 200, b[:200]
    etag = h.get("ETag")
    assert etag, "the read shipped no ETag, so the browser has nothing to revalidate with"
    assert etag.startswith('W/"'), (
        "the tag must be WEAK: the same resource is served gzipped or plain depending on the "
        "request, and a strong validator would be asserting byte-equality that does not hold. "
        "got %r" % etag)


def test_it_tells_the_browser_to_revalidate_rather_than_guess(base_url, tokens, rows):
    _st, h, _b = _raw(base_url, "/api/coll/pm_tasks", tokens["admin"])
    cc = h.get("Cache-Control") or ""
    assert "no-cache" in cc, (
        "'no-cache' does not mean 'do not store' — it means 'never serve this without asking me "
        "first'. Without it a browser may hand back a stale body with no request at all, and a "
        "colleague's approval would sit unseen behind it. got %r" % cc)
    assert "private" in cc, (
        "this is user-scoped data and must never enter a shared cache. got %r" % cc)


def test_the_token_is_part_of_the_cache_key(base_url, tokens, rows):
    """Kept apart from the Cache-Control assertions above, deliberately.

    They protect different things — one that a stale body is never served without asking, one that
    a second account on a shared device never reaches for the first one's entry — and a single test
    asserting both can only ever tell you that "the headers are wrong".
    """
    _st, h, _b = _raw(base_url, "/api/coll/pm_tasks", tokens["admin"])
    assert "Authorization" in (h.get("Vary") or ""), (
        "got %r. The tag alone already makes cross-account reuse impossible — a different "
        "entitlement is a different body is a different tag — but keeping the token in the cache "
        "key means the browser never even looks." % h.get("Vary"))


def test_an_unchanged_collection_answers_304_with_no_body(base_url, tokens, rows):
    _st, h1, b1 = _raw(base_url, "/api/coll/pm_tasks", tokens["admin"])
    etag = h1.get("ETag")
    st2, h2, b2 = _raw(base_url, "/api/coll/pm_tasks", tokens["admin"], inm=etag)
    assert st2 == 304, "nothing changed, so this must not re-send the collection"
    assert b2 == b"", "a 304 carries no body; got %d bytes" % len(b2)
    assert h2.get("ETag") == etag, "the 304 must repeat the validator it matched"
    assert len(b1) > 2000, (
        "the fixture is too small for this to be evidence of anything; got %d bytes" % len(b1))


def test_a_tag_that_does_not_match_still_returns_everything(base_url, tokens, rows):
    _st, _h, b1 = _raw(base_url, "/api/coll/pm_tasks", tokens["admin"])
    st, _h2, b2 = _raw(base_url, "/api/coll/pm_tasks", tokens["admin"],
                       inm='W/"00000000000000000000000000000000"')
    assert st == 200
    assert len(b2) == len(b1), "an unrecognised validator must be treated as no validator at all"


def test_a_write_changes_the_tag_so_a_save_is_never_hidden(base_url, tokens, rows):
    """The one that matters. A 304 here means the row you just saved is invisible."""
    _st, h, _b = _raw(base_url, "/api/coll/pm_tasks", tokens["admin"])
    etag = h.get("ETag")

    st, _h2, made = _raw(base_url, "/api/coll/pm_tasks", tokens["admin"], method="POST",
                         body={"projectId": rows["id"], "wbs": "9.9",
                               "name": "row added after the tag was issued"})
    assert st == 200, made[:300]

    st3, _h3, b3 = _raw(base_url, "/api/coll/pm_tasks", tokens["admin"], inm=etag)
    assert st3 == 200, (
        "the collection changed, so the old tag must NOT match. A 304 here would mean every save "
        "stayed invisible until the cache expired — the fix hiding the data it exists to deliver.")
    assert b"row added after the tag was issued" in b3


def test_a_write_response_is_never_itself_cacheable(base_url, tokens, rows):
    st, h, b = _raw(base_url, "/api/coll/pm_tasks", tokens["admin"], method="POST",
                    body={"projectId": rows["id"], "wbs": "9.8", "name": "second row"})
    assert st == 200, b[:300]
    assert not h.get("ETag"), (
        "only a GET may carry a validator; tagging a POST invites a replayed write to be answered "
        "from a cache")
    assert not (h.get("Cache-Control") or ""), "a write result is not a cacheable resource"


def test_a_refusal_carries_no_validator(base_url):
    """An unauthenticated read must hand back nothing to probe a cache with."""
    st, h, _b = _raw(base_url, "/api/coll/pm_tasks")
    assert st in (401, 403)
    assert not h.get("ETag")


def test_one_accounts_tag_never_unlocks_anothers_data(base_url, tokens, rows):
    """The tag is a hash of the ALREADY-SCOPED body, so it cannot carry data across a boundary.

    Staff and admin do not see the same pm_tasks rows. Presenting the admin's tag as staff must
    return the staff body — never a 304, which would tell the staff browser "what you already have
    is current" about data it never had.
    """
    _st, ha, _ba = _raw(base_url, "/api/coll/pm_tasks", tokens["admin"])
    a_tag = ha.get("ETag")
    assert a_tag

    st_s, hs, bs = _raw(base_url, "/api/coll/pm_tasks", tokens["staff"])
    if st_s != 200:
        pytest.skip("this account cannot read pm_tasks at all, so there is no tag to confuse")

    st_x, _hx, bx = _raw(base_url, "/api/coll/pm_tasks", tokens["staff"], inm=a_tag)
    if hs.get("ETag") == a_tag:
        # Identical entitlement produced an identical body. A 304 is then correct, and nothing
        # crossed a boundary because between these two bodies there is no boundary.
        assert st_x in (200, 304)
    else:
        assert st_x == 200, (
            "the two accounts see different rows, so the admin's tag must not match here")
        assert len(bx) == len(bs)


def test_the_bootstrap_reads_are_covered_too(base_url, tokens):
    """Not just /api/coll. These four are pulled on every boot and by every poll tick."""
    for path in ("/api/employees", "/api/leave", "/api/zones", "/api/me"):
        st, h, b = _raw(base_url, path, tokens["admin"])
        assert st == 200, "%s -> %s %s" % (path, st, b[:120])
        etag = h.get("ETag")
        assert etag, "%s ships no validator" % path
        st2, _h2, b2 = _raw(base_url, path, tokens["admin"], inm=etag)
        assert st2 == 304, "%s did not revalidate to 304 (got %s)" % (path, st2)
        assert b2 == b"", "%s sent a body with its 304" % path
