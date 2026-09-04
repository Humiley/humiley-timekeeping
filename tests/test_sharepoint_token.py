"""A SharePoint upload must not give up the first time Microsoft's silent token renewal fails.

What a site engineer saw while saving a Daily Report with a contractor PDF attached:

    "SharePoint upload failed (monitor_window_timeout: Token acquisition in iframe failed due to
     timeout. For more visit: aka.ms/msaljs/browser-errors.) — storing in app instead."

The project WAS linked to SharePoint and he WAS signed in to Microsoft. MSAL renews tokens silently in
a hidden iframe against login.microsoftonline.com, that timed out, and `_pmSpToken` had no fallback at
all — one throw and the caller dropped a 12 MB PDF into the application database instead.

Silent renewal fails routinely, for reasons invisible to the user: the iframe is blocked outright by
third-party-cookie restrictions (Safari always, Chrome increasingly), the cached refresh token has
aged out, or the connection is slow enough to hit the timeout. Treating that as fatal meant the
platform's document filing quietly degraded into its biggest performance problem — files in the
database are shipped to every user who opens any project.

The fallback is a POPUP and deliberately not a redirect: every caller runs while the user is part way
through a form, and a redirect navigates the page away and loses everything they typed.
"""
import json
import os
import shutil
import subprocess
import tempfile

import pytest

IDX = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))),
                   "templates", "index.html")
pytestmark = pytest.mark.skipif(shutil.which("node") is None, reason="node not installed")


def _fn(src, name):
    for prefix in ("\nfunction %s(", "\nasync function %s("):
        at = src.find(prefix % name)
        if at >= 0:
            i = at + 1
            break
    else:
        raise AssertionError("no top-level function " + name)
    depth, j, started = 0, i, False
    while j < len(src):
        if src[j] == "{":
            depth += 1
            started = True
        elif src[j] == "}":
            depth -= 1
            if started and depth == 0:
                return src[i:j + 1]
        j += 1
    raise AssertionError("unterminated function " + name)


def _src():
    with open(IDX, encoding="utf-8") as fh:
        return fh.read()


def _run(js, native="false"):
    harness = (
        "function _t(s){return s;}\n"
        "function _isNative(){return %s;}\n"
        "let _account = { username: 'trung.nguyen@humiley.com' };\n"
        "let _msalApp = null;\n" % native
        + "\n".join(_fn(_src(), n) for n in ("_pmSpToken", "_pmSpWhy"))
        + "\n" + js
    )
    p = os.path.join(tempfile.mkdtemp(prefix="tk-sp-"), "t.js")
    with open(p, "w", encoding="utf-8") as fh:
        fh.write(harness)
    r = subprocess.run(["node", p], capture_output=True, text=True)
    assert r.returncode == 0, r.stderr
    return json.loads(r.stdout)


TIMEOUT = """
  const boom = Object.assign(new Error('Token acquisition in iframe failed due to timeout.'),
                             { errorCode: 'monitor_window_timeout' });
  const calls = [];
  _msalApp = {
    getAllAccounts: () => [_account],
    acquireTokenSilent: async () => { calls.push('silent'); throw boom; },
    acquireTokenPopup:  async () => { calls.push('popup'); return { accessToken: 'FROM-POPUP' }; }
  };
"""


# ── recovery ──────────────────────────────────────────────────────────────────────────────────────

def test_a_silent_timeout_recovers_through_a_popup():
    """THE fix. The exact error from the screenshot, and the upload survives it."""
    out = _run(TIMEOUT + """
      (async () => {
        const tok = await _pmSpToken(true);
        console.log(JSON.stringify({ token: tok, calls: calls }));
      })();
    """)
    assert out["token"] == "FROM-POPUP"
    assert out["calls"] == ["silent", "popup"], "it did not fall back"


def test_the_silent_path_is_still_tried_first():
    """The popup is the recovery, never the routine. A working session must not prompt anybody."""
    out = _run("""
      const calls = [];
      _msalApp = {
        getAllAccounts: () => [_account],
        acquireTokenSilent: async () => { calls.push('silent'); return { accessToken: 'QUIET' }; },
        acquireTokenPopup:  async () => { calls.push('popup'); return { accessToken: 'LOUD' }; }
      };
      (async () => {
        const tok = await _pmSpToken(true);
        console.log(JSON.stringify({ token: tok, calls: calls }));
      })();
    """)
    assert out["token"] == "QUIET" and out["calls"] == ["silent"]


def test_an_expired_session_also_recovers():
    out = _run("""
      const calls = [];
      _msalApp = {
        getAllAccounts: () => [_account],
        acquireTokenSilent: async () => { calls.push('silent'); throw { errorCode: 'interaction_required' }; },
        acquireTokenPopup:  async () => { calls.push('popup'); return { accessToken: 'FROM-POPUP' }; }
      };
      (async () => { console.log(JSON.stringify({ token: await _pmSpToken(true), calls: calls })); })();
    """)
    assert out["token"] == "FROM-POPUP"


# ── and does not prompt where it must not ─────────────────────────────────────────────────────────

def test_a_background_caller_never_opens_a_popup():
    """A popup opened outside a user gesture is blocked by the browser, and a blocked popup is worse
       than a clear message. Interactivity is opt-in per call site."""
    out = _run(TIMEOUT + """
      (async () => {
        let err = '';
        try { await _pmSpToken(false); } catch (e) { err = e.errorCode; }
        console.log(JSON.stringify({ err: err, calls: calls }));
      })();
    """)
    assert out["err"] == "monitor_window_timeout"
    assert out["calls"] == ["silent"], "it opened a popup with no gesture behind it"


def test_the_installed_app_never_tries_a_popup():
    """This codebase already records that popups fail inside the PWA / Capacitor wrapper and used to
       strand users on the login screen. Do not repeat that — fail with a message instead."""
    out = _run(TIMEOUT + """
      (async () => {
        let err = '';
        try { await _pmSpToken(true); } catch (e) { err = e.errorCode; }
        console.log(JSON.stringify({ err: err, calls: calls }));
      })();
    """, native="true")
    assert out["err"] == "monitor_window_timeout"
    assert out["calls"] == ["silent"]


# ── what the engineer is told ─────────────────────────────────────────────────────────────────────

def test_every_failure_mode_says_what_to_do_about_it():
    """The old toast pasted a raw MSAL error code at somebody standing on a site. Each message now
       names an action, and none of them leaks the code."""
    out = _run("""
      console.log(JSON.stringify({
        timeout: _pmSpWhy({ errorCode: 'monitor_window_timeout' }),
        blocked: _pmSpWhy({ errorCode: 'popup_window_error' }),
        expired: _pmSpWhy({ errorCode: 'interaction_required' }),
        cancelled: _pmSpWhy({ errorCode: 'user_cancelled' }),
        other:   _pmSpWhy(new Error('network down'))
      }));
    """)
    for key, msg in out.items():
        assert msg and len(msg) > 25, (key, msg)
        assert "errorCode" not in msg and "msaljs" not in msg, (key, "raw MSAL detail leaked")
    assert "re-attach" in out["timeout"] and "Chrome" in out["timeout"]
    assert "pop-ups" in out["blocked"]
    assert "sign in" in out["expired"].lower()
    assert out["timeout"] != out["expired"] != out["blocked"], "the modes are not distinguished"


# ── the configuration behind it ───────────────────────────────────────────────────────────────────

def test_msal_is_given_room_to_finish_a_silent_renewal():
    """MSAL's stock 6s iframe budget is tight for a phone on 4G at a site. More headroom does not fix
       a browser that blocks the iframe outright, which is why it is paired with the popup fallback
       rather than relied on alone."""
    src = _src()
    assert "iframeHashTimeout: 12000" in src and "loadFrameTimeout: 12000" in src, \
        "the silent-renewal timeouts are not configured"
    assert "windowHashTimeout" in src


def test_the_uploader_asks_for_the_interactive_path():
    """It runs immediately after the user chose a file, so a popup is still permitted there — which is
       the whole reason the upload can now recover."""
    body = _fn(_src(), "_graphUploadFile")
    assert "_pmSpToken(true)" in body, "the uploader still gives up on the first silent failure"


def test_the_fallback_message_no_longer_pastes_the_raw_error():
    src = _src()
    assert "storing in app instead.', 'warn'" not in src, "the raw-error toast is still there"
    assert "_pmSpWhy(e)" in src, "the actionable message is not wired to the fallback"
