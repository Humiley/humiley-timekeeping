"""E-sign §11.200 recency + the TK_REQUIRE_AUTH_TIME hardening.

`auth_time` is the only claim that proves an INTERACTIVE re-authentication — a silent token refresh
advances `iat` but never `auth_time`. Default behaviour (flag unset) falls back to `iat` for backward
compatibility; with TK_REQUIRE_AUTH_TIME set, a token missing `auth_time` is rejected — the fully-hardened
mode to enable once the Entra app registration emits `auth_time` (the frontend already requests it).
"""
import base64
import json
import time

import app


def _fake_jwt(claims):
    # A structurally-valid RS256 JWT. In the test env (no TK_ESIGN_JWKS / TK_ESIGN_REQUIRE_VERIFIED_TOKEN
    # and no configured tenant) signature verification is a no-op, so the recency logic is exercised.
    def b64(d):
        return base64.urlsafe_b64encode(json.dumps(d).encode()).rstrip(b"=").decode()
    return b64({"alg": "RS256", "typ": "JWT"}) + "." + b64(claims) + ".sig"


def _handler(monkeypatch):
    # _esign_fresh uses only helper methods + module globals (no socket/request state), so a bare
    # instance exercises it. Stub the JWKS RS256 signature check (a separate concern) so the test
    # isolates the recency / auth_time logic that this suite covers.
    monkeypatch.setattr(app.Handler, "_verify_jwt_signature", lambda self, token, hdr: (True, None))
    return app.Handler.__new__(app.Handler)


def test_missing_auth_time_falls_back_to_iat_by_default(monkeypatch):
    monkeypatch.delenv("TK_REQUIRE_AUTH_TIME", raising=False)
    tok = _fake_jwt({"exp": time.time() + 3600, "iat": time.time(), "preferred_username": "staff1@humiley.com"})
    ok, info = _handler(monkeypatch)._esign_fresh(tok)
    assert ok is True, info
    assert info["email"] == "staff1@humiley.com"


def test_missing_auth_time_rejected_when_required(monkeypatch):
    monkeypatch.setenv("TK_REQUIRE_AUTH_TIME", "1")
    tok = _fake_jwt({"exp": time.time() + 3600, "iat": time.time(), "preferred_username": "staff1@humiley.com"})
    ok, msg = _handler(monkeypatch)._esign_fresh(tok)
    assert ok is False
    assert "interactive" in msg.lower(), msg


def test_present_auth_time_accepted_when_required(monkeypatch):
    # A genuine interactive re-auth carries a recent auth_time — accepted even in required mode.
    monkeypatch.setenv("TK_REQUIRE_AUTH_TIME", "1")
    now = time.time()
    tok = _fake_jwt({"exp": now + 3600, "iat": now, "auth_time": now, "preferred_username": "staff1@humiley.com"})
    ok, info = _handler(monkeypatch)._esign_fresh(tok)
    assert ok is True, info


def test_stale_auth_time_rejected(monkeypatch):
    # Recency still bites: an auth_time older than max_age (600s) is rejected regardless of the flag.
    monkeypatch.delenv("TK_REQUIRE_AUTH_TIME", raising=False)
    now = time.time()
    tok = _fake_jwt({"exp": now + 3600, "iat": now, "auth_time": now - 5000, "preferred_username": "staff1@humiley.com"})
    ok, msg = _handler(monkeypatch)._esign_fresh(tok)
    assert ok is False
    assert "recent" in msg.lower(), msg
