"""Granting a Graph permission must take effect without restarting the server.

An app-only access token carries the roles that existed WHEN IT WAS MINTED, and it is cached for
roughly an hour. So in the minutes right after an admin grants Sites.ReadWrite.All, the cached token
still has no Sites role and Graph keeps returning 403 — on a tenant that is now configured correctly.

That is exactly what happened: the backup uploader (a separate process, fresh token every run) started
working the moment consent landed, while Invoice Tracking → Test connection kept insisting "SharePoint
archive is not working yet" with `403 accessDenied`. Same tenant, same credentials, same folder — the
only difference was one process holding a token older than the grant.

The Test button and the archive path therefore have to be able to bust that cache, or an admin is left
with a restart as the only apparent cure, having no way to tell a stale token from a genuinely wrong
permission.
"""
import os
import re

APP = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "app.py")


def _src():
    with open(APP, encoding="utf-8") as fh:
        return fh.read()


def _func(src, name):
    """Crude but sufficient: the body of a top-level def, up to the next top-level def."""
    i = src.index("def %s(" % name)
    j = src.find("\ndef ", i + 1)
    return src[i:j if j > 0 else len(src)]


def test_the_force_parameter_exists():
    assert "def _graph_app_token(force=False):" in _src(), \
        "the cache-busting path is what makes a fresh consent usable without a restart"


def test_test_connection_mints_a_fresh_token():
    """Otherwise the button reports failure on a correctly configured tenant for up to an hour."""
    body = _func(_src(), "_invtrack_sp_diagnose")
    assert "_graph_app_token(force=True)" in body, \
        "Test connection must force a fresh token — that is the entire point of the button"


def test_the_archive_path_retries_once_with_a_fresh_token():
    """So invoices start filing the moment consent lands, not when the old token happens to expire."""
    body = _func(_src(), "_invtrack_sp_upload")
    assert "_graph_app_token(force=True)" in body, "the archive path must self-heal after consent"


def test_the_retry_rebinds_the_token_used_for_the_upload():
    """Resolving with a fresh token but uploading with the stale one would 403 at the PUT — the
       failure would move rather than disappear, which is worse than not retrying at all."""
    body = _func(_src(), "_invtrack_sp_upload")
    m = re.search(r"token = _graph_app_token\(force=True\)", body)
    assert m, "the fresh token must be assigned to `token`, not just passed to the resolver"
    after = body[m.end():]
    assert "_graph_upload_session(" in after or "_graph_put_bytes(" in after, \
        "the upload must happen AFTER the rebind so it uses the fresh token"


def test_the_negative_cache_is_cleared_before_retrying():
    """_invtrack_sp_resolve negative-caches a failure for ~5 min; without clearing it the retry would
       be answered from that cache and never reach Graph at all."""
    body = _func(_src(), "_invtrack_sp_upload")
    i = body.index("_graph_app_token(force=True)")
    assert "_invtrack_sp_reset()" in body[:i], \
        "clear the negative cache BEFORE retrying, or the retry is a no-op"
