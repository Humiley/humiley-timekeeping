# -*- coding: utf-8 -*-
"""The shell is 3.9 MB of one file, so how it is compressed is most of the boot.

gzip -6 gets it to 1,151,909 B. Brotli at quality 11 gets it to 832,680 B — 319 KB less on every
cold load, which on a phone on Vietnamese mobile data is the largest remaining item in the boot
path. This file is about the two ways that goes wrong.

  · QUALITY 11 TAKES ~5.4 SECONDS on this file. Built on the request thread, the first visitor after
    every deploy waits out the whole compression — long enough to read as an outage, and long enough
    for a proxy to give up. So it is built on a background thread and the request that triggers the
    build is served gzip immediately. A test that only checked "brotli is served" would pass on the
    blocking version, which is the version that hurts people.
  · IT IS AN OPTIONAL DEPENDENCY. requirements.txt is installed on a host this repo cannot see, and
    the module has been unavailable before. If its absence stops the shell being served at all, the
    portal is down; it must silently fall back to gzip.

The size budget at the end is a different guard for the same page: an image referenced by the shell
that nobody looked at. static/brand/H-mark-color.png is a 2139x2188 master that was being served to
draw a 30-pixel sidebar mark — 233 KB for 30 px.
"""
import gzip
import io
import os
import sys
import threading
import time
import urllib.request

import pytest

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, ROOT)

import app  # noqa: E402

SHELL = os.path.join(ROOT, "templates", "index.html")


def _get(base, enc, timeout=120):
    r = urllib.request.Request(base + "/")
    r.add_header("Accept-Encoding", enc)
    t = time.time()
    with urllib.request.urlopen(r, timeout=timeout) as f:
        return f.headers.get("Content-Encoding", "identity"), f.read(), time.time() - t


@pytest.fixture(scope="module")
def disk():
    with io.open(SHELL, "rb") as f:
        return f.read()


def test_a_gzip_only_client_is_unaffected(base_url, disk):
    enc, body, _ = _get(base_url, "gzip")
    assert enc == "gzip"
    assert gzip.decompress(body) == disk, "the served shell no longer matches the file on disk"


def test_a_client_that_accepts_nothing_still_gets_the_page(base_url, disk):
    enc, body, _ = _get(base_url, "identity")
    assert enc == "identity"
    assert body == disk


@pytest.mark.skipif(app.brotli is None, reason="brotli not installed in this environment")
def test_the_first_request_after_a_deploy_does_not_wait_for_the_build(base_url):
    """The whole reason the build is on a background thread.

    A fresh (path, mtime) key means nothing is cached, exactly as after a deploy. Quality 11 on this
    file takes ~5.4 s; this request must come back in a small fraction of that, carrying gzip.
    """
    app.Handler._BR_CACHE.clear()
    with app.Handler._BR_LOCK:
        app.Handler._BR_BUILDING.clear()
    enc, body, secs = _get(base_url, "br, gzip")
    assert enc == "gzip", "the first visitor was made to wait for the brotli build"
    assert secs < 2.0, "served in %.1f s — this is the blocking version" % secs


@pytest.mark.skipif(app.brotli is None, reason="brotli not installed in this environment")
def test_and_then_brotli_takes_over_and_is_byte_identical(base_url, disk):
    _get(base_url, "br, gzip")                       # trigger the build
    for _ in range(120):
        enc, body, _t = _get(base_url, "br, gzip")
        if enc == "br":
            break
        time.sleep(1)
    assert enc == "br", "the background build never produced anything"
    assert app.brotli.decompress(body) == disk, \
        "brotli served something that is not the shell — the worst possible outcome here, because " \
        "it fails as a blank page rather than as an error"
    assert len(body) < 1_000_000, \
        "brotli output is %d B; gzip already achieves 1,151,909 so this is not worth the " \
        "dependency" % len(body)


def test_the_shell_is_still_served_when_brotli_is_missing(base_url, disk, monkeypatch):
    """requirements.txt is installed on a host this repo cannot see. If the module's absence took
    the shell down, the portal would be down.

    Serving the right bytes is only half of it. Without the `brotli is not None` guard in
    _accepts_br the server still answers correctly — the build thread throws and the fallback
    catches it — so a test that checked only the response would pass while every single request on
    a brotli-less host span up a thread that was certain to fail. Hence the recorder: the question
    is whether the server even TRIES.
    """
    monkeypatch.setattr(app, "brotli", None)
    app.Handler._BR_CACHE.clear()
    tried = []
    real = app.Handler._br_start
    monkeypatch.setattr(app.Handler, "_br_start",
                        classmethod(lambda cls, key, path: tried.append(path)))
    try:
        enc, body, _ = _get(base_url, "br, gzip")
    finally:
        monkeypatch.setattr(app.Handler, "_br_start", real)
    assert enc == "gzip", "with no brotli module the server must fall back, not fail"
    assert gzip.decompress(body) == disk
    assert tried == [], \
        "a build was started with no brotli module: one doomed thread per request, for ever"


@pytest.mark.skipif(app.brotli is None, reason="brotli not installed in this environment")
def test_one_ordinary_session_does_not_evict_the_shell(base_url, disk):
    """The bug this test exists for shipped, and it made the whole feature almost a no-op.

    The first version bounded the cache with `if len(...) > 8: clear()`. There are 16 brotli-eligible
    files under /static besides "/", so fetching one page's worth of assets emptied the dict and threw
    away a 5.3-second build. Production then answered Content-Encoding: gzip — the compression worked
    perfectly and almost nobody received it. Nothing about the response was wrong, so only a test that
    fetches OTHER files and then comes back to the shell can see it.
    """
    _get(base_url, "br, gzip")
    for _ in range(120):
        enc, _b, _t = _get(base_url, "br, gzip")
        if enc == "br":
            break
        time.sleep(1)
    assert enc == "br", "the shell never reached brotli, so this test cannot prove anything"

    others = ["/static/sw.js", "/static/manifest.webmanifest", "/static/vendor/chart.umd.min.js",
              "/static/vendor/msal-browser.min.js", "/static/install.html", "/static/privacy.html",
              "/static/vendor/jspdf.umd.min.js", "/static/vendor/html2canvas.min.js",
              "/static/vendor/xlsx.full.min.js", "/static/i18n/vi.js"]
    fetched = 0
    for path in others:
        try:
            r = urllib.request.Request(base_url + path)
            r.add_header("Accept-Encoding", "br, gzip")
            with urllib.request.urlopen(r, timeout=60) as f:
                f.read()
            fetched += 1
        except Exception:
            pass
    assert fetched >= 8, "only %d of the other static files were reachable; this test needs enough " \
                         "of them to have pushed the shell out of a 9-entry cache" % fetched

    # Those builds run on background threads. Without waiting for them to land, this test races them
    # and passes on the broken version — which is exactly what happened the first time it was run
    # against the bug. Settle = the entry count stops moving.
    stable, last = 0, -1
    for _ in range(60):
        n = len(app.Handler._BR_CACHE)
        stable = stable + 1 if n == last else 0
        last = n
        if stable >= 3:
            break
        time.sleep(1)

    enc, body, _ = _get(base_url, "br, gzip")
    assert enc == "br", \
        "one page's worth of asset fetches evicted the shell — every visitor after that is served " \
        "gzip while a 5.3-second rebuild runs, which is the feature not working"
    assert app.brotli.decompress(body) == disk


def test_no_image_the_shell_loads_is_a_full_resolution_master():
    """The sidebar mark renders at 30 px and the install/privacy hero at 52 px. The file behind it
    was a 2139x2188, 233 KB master.

    The budget is deliberately loose — this is not about bytes, it is about a print-resolution
    original being referenced from a page by mistake.
    """
    import re
    import struct

    shell = io.open(SHELL, encoding="utf-8").read()
    pages = [shell]
    for extra in ("static/install.html", "static/privacy.html"):
        pages.append(io.open(os.path.join(ROOT, extra), encoding="utf-8").read())

    refs = set()
    for page in pages:
        refs |= set(re.findall(r'(?:src|data-src)="(/static/[^"]+\.png)"', page))
    assert refs, "the reference scan found no images at all — the pattern stopped matching"

    too_big = []
    for ref in sorted(refs):
        path = os.path.join(ROOT, ref.lstrip("/"))
        assert os.path.exists(path), "%s is referenced but not in the repo" % ref
        raw = io.open(path, "rb").read()
        w, h = struct.unpack(">II", raw[16:24])
        if len(raw) > 60_000 or max(w, h) > 600:
            too_big.append("%s is %dx%d, %d B" % (ref, w, h, len(raw)))
    assert not too_big, (
        "a page loads a full-resolution image:\n  " + "\n  ".join(too_big) +
        "\nResize it (sips -Z 256 in.png --out out-256.png) and point the page at the small one; "
        "keep the master in the repo for print.")
