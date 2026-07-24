"""Sign-out must revoke the session token SERVER-SIDE, not just clear the browser.

The stay-signed-in design mints a 30-day sliding token; a client-only logout left that token fully valid
and replayable if it had been exfiltrated. POST /api/auth/logout now pops it from SESSIONS.
"""
import app


def test_logout_revokes_session_token(api):
    # Mint a fresh, isolated session so we never disturb the shared fixture tokens.
    tok = app.new_session("HML-STF", "staff")
    assert tok in app.SESSIONS

    # The token authenticates before logout.
    st, _ = api("GET", "/api/coll/claims", tok)
    assert st == 200, "a valid token should be accepted before logout (got %s)" % st

    # Log out -> server-side revoke.
    st2, b2 = api("POST", "/api/auth/logout", tok, {})
    assert st2 == 200, (st2, b2)
    assert tok not in app.SESSIONS, "logout must remove the token from SESSIONS"

    # The revoked token is now rejected — it can no longer be replayed.
    st3, _ = api("GET", "/api/coll/claims", tok)
    assert st3 == 401, "a revoked token must be rejected after logout (got %s)" % st3


def test_logout_is_idempotent_and_safe_without_token(api):
    # Logging out with no / unknown token must not error.
    st, b = api("POST", "/api/auth/logout", None, {})
    assert st == 200, (st, b)
    st2, b2 = api("POST", "/api/auth/logout", "not-a-real-token", {})
    assert st2 == 200, (st2, b2)
