"""Smoke-check the served HTML shell.

The 21k-line single-file UI has no browser test, so a template/HTML regression can white-screen prod
with fully-green backend CI (then auto-deploy ships it). This asserts the shell is served whole and
carries its core structural markers + the SRI-pinned library tags — a cheap guard that catches a
broken shell before deploy without a full browser harness.
"""
import urllib.request


def _shell(base_url):
    with urllib.request.urlopen(base_url + "/", timeout=10) as r:
        return r.status, r.headers.get("Content-Type", ""), r.read().decode("utf-8", "replace")


def test_shell_serves_whole_and_has_core_markers(base_url):
    status, ctype, html = _shell(base_url)
    assert status == 200
    assert "text/html" in ctype
    assert len(html) > 100_000, "the shell looks truncated (%d bytes)" % len(html)
    for marker in ('id="content"', 'id="sidebar"', "serviceWorker", "Humiley",
                   "/static/vendor/chart.umd.min.js", "/static/vendor/msal-browser.min.js"):
        assert marker in html, "shell is missing a core marker: %s" % marker


def test_shell_carries_sri_integrity_on_vendored_scripts(base_url):
    # the supply-chain pins must survive into the served HTML
    _, _, html = _shell(base_url)
    assert html.count("integrity=\"sha384-") >= 3


def test_shell_leaks_no_server_error(base_url):
    _, _, html = _shell(base_url)
    assert "Traceback (most recent call last)" not in html
    assert "PORTAL_ERROR" not in html
