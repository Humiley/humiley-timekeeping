"""Sign-out must revoke the session token SERVER-SIDE, not just clear the browser.

The stay-signed-in design mints a 30-day sliding token; a client-only logout left that token fully valid
and replayable if it had been exfiltrated. POST /api/auth/logout now pops it from SESSIONS.
"""
import json
import time
import app
import db


def test_legacy_raw_token_sessions_migrate_to_hashes(base_url):
    # A pre-upgrade blob keyed by RAW tokens must re-key to sha256 on load, so existing sessions keep
    # working (no forced re-login) AND the client's raw token still authenticates.
    saved_sessions = dict(app.SESSIONS)
    saved_blob = db.get_setting("_sessions")
    try:
        app.SESSIONS.clear()
        raw = "legacy-raw-token-xyz-123"
        db.set_setting("_sessions", json.dumps({raw: {"emp_id": "HML-STF", "role": "staff",
                                                       "expires": time.time() + 999}}))
        app._load_sessions()
        assert app._tok_hash(raw) in app.SESSIONS       # re-keyed to its hash
        assert raw not in app.SESSIONS                   # raw key gone
        assert app.session_user(raw) is not None         # the raw token still authenticates
    finally:
        app.SESSIONS.clear()
        app.SESSIONS.update(saved_sessions)
        if saved_blob is not None:
            db.set_setting("_sessions", saved_blob)


def test_logout_revokes_session_token(api):
    # Mint a fresh, isolated session so we never disturb the shared fixture tokens.
    tok = app.new_session("HML-STF", "staff")
    # Tokens are stored HASHED at rest — the raw token is never a key (a DB read can't be replayed).
    assert app._tok_hash(tok) in app.SESSIONS
    assert tok not in app.SESSIONS

    # The token authenticates before logout.
    st, _ = api("GET", "/api/coll/claims", tok)
    assert st == 200, "a valid token should be accepted before logout (got %s)" % st

    # Log out -> server-side revoke.
    st2, b2 = api("POST", "/api/auth/logout", tok, {})
    assert st2 == 200, (st2, b2)
    assert app._tok_hash(tok) not in app.SESSIONS, "logout must remove the (hashed) token from SESSIONS"

    # The revoked token is now rejected — it can no longer be replayed.
    st3, _ = api("GET", "/api/coll/claims", tok)
    assert st3 == 401, "a revoked token must be rejected after logout (got %s)" % st3


def test_logout_is_idempotent_and_safe_without_token(api):
    # Logging out with no / unknown token must not error.
    st, b = api("POST", "/api/auth/logout", None, {})
    assert st == 200, (st, b)
    st2, b2 = api("POST", "/api/auth/logout", "not-a-real-token", {})
    assert st2 == 200, (st2, b2)
