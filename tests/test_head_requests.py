"""HEAD must answer like GET without a body.

BaseHTTPRequestHandler answers 501 to any verb it has no `do_*` for, so every HEAD reached this
server as "Not Implemented" — including `HEAD /api/health`, which exists for exactly one audience:
uptime monitors. UptimeRobot, Pingdom and most others probe with HEAD by default, and would have
reported portal.humiley.com down while it served every real request perfectly.

Nothing a browser does is affected, which is why it went unnoticed for the life of the endpoint.
"""
import http.client
import urllib.parse

import pytest


def _conn(base_url):
    p = urllib.parse.urlparse(base_url)
    return http.client.HTTPConnection(p.hostname, p.port, timeout=10)


def _head(base_url, path):
    c = _conn(base_url)
    try:
        c.request("HEAD", path)
        r = c.getresponse()
        body = r.read()
        return r.status, dict(r.getheaders()), body
    finally:
        c.close()


def _get(base_url, path):
    c = _conn(base_url)
    try:
        c.request("GET", path)
        r = c.getresponse()
        body = r.read()
        return r.status, dict(r.getheaders()), body
    finally:
        c.close()


PUBLIC = ["/api/health", "/api/build", "/"]


@pytest.mark.parametrize("path", PUBLIC)
def test_head_is_not_501(base_url, path):
    """The whole defect in one assertion."""
    st, _h, _b = _head(base_url, path)
    assert st != 501, "%s still answers Not Implemented to HEAD" % path


@pytest.mark.parametrize("path", PUBLIC)
def test_head_returns_the_same_status_as_get(base_url, path):
    assert _head(base_url, path)[0] == _get(base_url, path)[0]


@pytest.mark.parametrize("path", PUBLIC)
def test_head_sends_no_body(base_url, path):
    assert _head(base_url, path)[2] == b""


@pytest.mark.parametrize("path", PUBLIC)
def test_head_reports_the_size_the_body_would_have_been(base_url, path):
    """RFC 9110 §9.3.2: HEAD carries the header fields it WOULD have sent. A monitor that reads
    Content-Length to spot a truncated page needs the real figure, so zero here would be a
    different lie from the one just fixed."""
    _st, h, _b = _head(base_url, path)
    assert "Content-Length" in h
    assert int(h["Content-Length"]) > 0


def test_head_keeps_the_security_headers(base_url):
    """A monitor is not the only thing that issues a HEAD. Dropping the headers for it would make
    the response a weaker version of the page rather than the same page without its body."""
    _st, hh, _b = _head(base_url, "/")
    _st2, hg, _b2 = _get(base_url, "/")
    for key in ("Content-Type", "X-Content-Type-Options"):
        if key in hg:
            assert hh.get(key) == hg.get(key), "%s differs between HEAD and GET" % key


def test_a_get_on_the_same_connection_still_has_its_body(base_url):
    """The way this fix breaks: the handler object is reused across keep-alive requests, so an
    override left in place would silence the body of the NEXT GET on that socket. Both requests go
    down ONE connection deliberately."""
    c = _conn(base_url)
    try:
        c.request("HEAD", "/api/build")
        r1 = c.getresponse()
        assert r1.read() == b""
        c.request("GET", "/api/build")
        r2 = c.getresponse()
        body = r2.read()
        assert r2.status == 200
        assert body, "the GET after a HEAD came back empty — the body sink outlived its request"
        assert b"hml-pwa-v" in body
    finally:
        c.close()


def test_head_on_an_unknown_path_still_reports_not_found(base_url):
    """404 is an answer; 501 is a refusal to look."""
    st, _h, _b = _head(base_url, "/no-such-path-here")
    assert st == 404


def test_head_on_a_protected_endpoint_still_refuses(base_url):
    """HEAD must not become a way to probe authenticated routes."""
    st, _h, _b = _head(base_url, "/api/employees")
    assert st in (401, 403), "HEAD bypassed the auth gate (%s)" % st
