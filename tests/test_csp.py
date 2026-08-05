"""The Content-Security-Policy must let the in-app file preview (tkFilePreview) render an attached PDF
inline in an <iframe> — attachments are held client-side as base64/blob, so the frame src is a blob:/data:
URL. Without `frame-src ... blob: data:` the whole preview pane renders blank (the production bug). The
rest of the policy must stay locked down.
"""
import urllib.request

import app


def test_frame_src_allows_blob_and_data_for_inline_pdf_preview():
    assert "frame-src 'self' blob: data:" in app._CSP, app._CSP


def test_csp_keeps_the_dangerous_directives_locked_down():
    csp = app._CSP
    for directive in ("default-src 'self'", "object-src 'none'", "base-uri 'self'",
                      "frame-ancestors 'self'", "form-action 'self'"):
        assert directive in csp, directive


def test_html_shell_serves_the_csp_and_frame_options(base_url):
    with urllib.request.urlopen(base_url + "/", timeout=10) as r:
        csp = r.headers.get("Content-Security-Policy") or ""
        xfo = r.headers.get("X-Frame-Options") or ""
    assert "frame-src 'self' blob: data:" in csp, csp
    assert xfo == "SAMEORIGIN", xfo


def test_frame_src_allows_the_msal_silent_renewal_frame():
    """THE bug that put 12 MB contractor PDFs in the database.

    MSAL renews access tokens SILENTLY by navigating a HIDDEN IFRAME to
    login.microsoftonline.com/.../authorize?prompt=none. That origin was allow-listed in script-src
    and in connect-src, but never in frame-src — so the browser blocked the frame outright
    (verified in a real browser: securitypolicyviolation fires with violatedDirective=frame-src and
    blockedURI=https://login.microsoftonline.com). No hash ever came back, MSAL waited out
    iframeHashTimeout and threw `monitor_window_timeout`, and the SharePoint upload fell back to
    storing the file inline in the record.

    Entra SPA refresh tokens are 24-hour and single-use, so this path is reached routinely — every
    morning, and the first time anybody needs the SharePoint scope. It was self-inflicted by the CSP
    hardening pass, and it is deterministic: no cookie policy or network speed involved.
    """
    csp = app._CSP
    frame = [d for d in csp.split(";") if d.strip().startswith("frame-src")]
    assert frame, csp
    assert "https://login.microsoftonline.com" in frame[0], \
        "MSAL cannot renew tokens silently — uploads will fall back to the database"
    # Conditional-access flows hop through this origin; it is already trusted in script-src.
    assert "https://*.msftauth.net" in frame[0], frame[0]


def test_the_login_origin_is_consistent_across_the_directives_that_need_it():
    """script-src, connect-src and frame-src all have to agree, or silent auth breaks in a way that
       surfaces as an unrelated-looking timeout."""
    csp = app._CSP
    for directive in ("script-src", "connect-src", "frame-src"):
        seg = [d for d in csp.split(";") if d.strip().startswith(directive)]
        assert seg, directive
        assert "https://login.microsoftonline.com" in seg[0], \
            directive + " is missing the Microsoft login origin: " + seg[0]
