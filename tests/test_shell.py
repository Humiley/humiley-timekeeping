"""Smoke-check the served HTML shell.

The 21k-line single-file UI has no browser test, so a template/HTML regression can white-screen prod
with fully-green backend CI (then auto-deploy ships it). This asserts the shell is served whole and
carries its core structural markers + the SRI-pinned library tags — a cheap guard that catches a
broken shell before deploy without a full browser harness.
"""
import re
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
    # The supply-chain pins must survive into the served HTML.
    #
    # This asserted `count(...) >= 3` and went red when Leaflet stopped being a <script> tag in the
    # shell and became an on-demand injection — a change that REMOVED a boot-time download and took
    # its pin with it into JS. A bare count cannot tell "a pin was dropped" from "the thing it pinned
    # is no longer loaded at boot", and only the first is a regression. Assert the property instead:
    # every vendored library referenced anywhere in the shell carries a sha384 pin, however it is
    # loaded.
    _, _, html = _shell(base_url)
    tagged = re.findall(r'<script\b[^>]*src="(/static/vendor/[^"]+)"[^>]*>', html)
    for src in tagged:
        i = html.index('src="%s"' % src)
        tag = html[html.rindex("<script", 0, i):html.index(">", i)]
        assert 'integrity="sha384-' in tag, "vendored <script> with no SRI pin: %s" % src

    # ...and the ones injected at runtime pin themselves the same way.
    #
    # Read the LOADER'S OWN BODY, not a window of characters around the filename. A first version
    # took html[i-400:i+400] and asked whether "sha384-" appeared anywhere in it — which stayed green
    # when the script's pin was deleted, because the stylesheet's pin two lines up was still inside
    # the window. A proximity check cannot tell which resource a pin belongs to.
    start = html.index("function _tkLoadLeaflet()")
    body = html[start:html.index("\nfunction ", start + 10)]
    for lib in ("/static/vendor/leaflet/leaflet.js", "/static/vendor/leaflet/leaflet.css"):
        assert lib in body, "the on-demand loader no longer fetches %s" % lib
    pins = re.findall(r"\.integrity\s*=\s*['\"]sha384-", body)
    assert len(pins) == 2, (
        "_tkLoadLeaflet fetches 2 files and carries %d SRI pin(s) — both the script and the "
        "stylesheet must be pinned" % len(pins)
    )

    assert html.count('integrity="sha384-') + len(pins) >= 4, (
        "expected pins for chart.js, msal and both Leaflet files"
    )


def test_shell_leaks_no_server_error(base_url):
    _, _, html = _shell(base_url)
    assert "Traceback (most recent call last)" not in html
    assert "PORTAL_ERROR" not in html


def test_shell_toast_has_a_reveal_rule(base_url):
    # toast() reveals the notifier by adding the `show` class. Without a CSS rule that flips
    # #toast.show to display:block, EVERY toast in the app (success / error / conflict feedback) is
    # silently invisible — a bug that shipped once already. Assert the reveal rule is present.
    _, _, html = _shell(base_url)
    assert 'id="toast"' in html, "the toast element is missing from the shell"
    assert "#toast.show{display:block" in html.replace(" ", ""), \
        "no CSS rule reveals #toast.show — toasts would be invisible app-wide"
