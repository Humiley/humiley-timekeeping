"""/api/build must let a device work out that the page in front of someone is out of date.

The client's staleness check compares the age of the HTML it is DISPLAYING (which the browser
reports as `document.lastModified`) against the age of the HTML the server is serving now. That
comparison only works if `appVersion` is derived from the served file's mtime — the same number the
Last-Modified header carries — and if the endpoint is reachable without a session, because a device
running a stale shell may also be holding a lapsed token.

Before this, the endpoint returned only the service worker's cache name. That answers "is the WORKER
current", which is a different question: the worker updates on its own schedule and activates
immediately, so a device could hold a current worker in front of a page loaded several deploys
earlier and every value the client could see agreed. Nothing healed, and the old screen stayed up.
"""
import os
import urllib.request

import app


def _served_html_mtime():
    return int(os.path.getmtime(os.path.join(app.TEMPLATE_DIR, "index.html")))


def test_build_reports_the_served_html_mtime_as_appversion(api):
    st, body = api("GET", "/api/build")
    assert st == 200, body
    assert "appVersion" in body, (
        "no appVersion — the client cannot tell a stale PAGE from a current one, which is the "
        "whole failure this field exists to fix: %r" % body)
    assert str(body["appVersion"]) == str(_served_html_mtime())


def test_appversion_is_comparable_with_the_last_modified_the_browser_sees(base_url):
    """`document.lastModified` comes from this header. If the two ever stop agreeing, the client's
    comparison silently reads every page as fresh and no device ever self-heals again."""
    from email.utils import parsedate_to_datetime

    with urllib.request.urlopen(base_url + "/", timeout=10) as r:
        last_mod = r.headers.get("Last-Modified")
    assert last_mod, "the shell is served without Last-Modified — document.lastModified would fall " \
                     "back to 'now' and the page would always look current"
    header_epoch = int(parsedate_to_datetime(last_mod).timestamp())

    st, body = api_get(base_url, "/api/build")
    assert st == 200
    assert int(body["appVersion"]) == header_epoch, (
        "appVersion (%s) and Last-Modified (%s) disagree — the client compares these two numbers "
        "directly" % (body["appVersion"], header_epoch))


def test_build_needs_no_session(base_url):
    """A device stuck on an old shell may also be holding a dead token. If this endpoint required
    auth, the devices most in need of healing would be the ones that could not ask."""
    st, body = api_get(base_url, "/api/build")
    assert st == 200, body
    assert body.get("ok") is True
    assert body.get("build"), "build (the worker cache name) must still be reported"


def test_build_still_reports_the_worker_cache_name(api):
    """appVersion is ADDITIVE. The cache-name comparison is still one of the two staleness signals,
    and /api/build is what the deploy runbook and 'Check for updates' read."""
    st, body = api("GET", "/api/build")
    assert st == 200
    assert str(body.get("build", "")).startswith("hml-pwa-v")


def api_get(base_url, path):
    import json
    req = urllib.request.Request(base_url + path, method="GET")
    with urllib.request.urlopen(req, timeout=10) as r:
        return r.status, json.loads(r.read().decode() or "{}")
