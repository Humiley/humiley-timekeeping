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
