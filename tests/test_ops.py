"""Ops / observability: health probe, admin error-review gate, and unhandled-error capture."""
import app


def test_health_is_public_and_ok(api):
    st, r = api("GET", "/api/health")
    assert st == 200
    assert r["status"] == "ok" and r["db"] is True
    assert "version" in r and "uptime_s" in r


def test_admin_errors_is_admin_only(api, tokens):
    # a Finance/Approver (management) must not see server stack traces
    st, _ = api("GET", "/api/admin/errors", tokens["management"])
    assert st == 403
    st, r = api("GET", "/api/admin/errors", tokens["admin"])
    assert st == 200
    assert "errors" in r and "count" in r and "uptime_s" in r


def test_record_error_captures_and_strips_query(monkeypatch):
    before = len(app._ERR_LOG)
    try:
        raise ValueError("boom-xyz")
    except ValueError as e:
        app._record_error("GET", "/api/thing?token=SECRET&x=1", e, "u@humiley.com")
    assert len(app._ERR_LOG) == before + 1
    last = app._ERR_LOG[-1]
    assert last["error"] == "ValueError" and "boom-xyz" in last["message"]
    assert last["path"] == "/api/thing", "query string (may carry tokens/PII) must be stripped"
    assert "SECRET" not in last["path"]
    assert last["email"] == "u@humiley.com"


def _boom():
    raise RuntimeError("kaboom")


def test_serve_request_captures_and_returns_500():
    h = app.Handler.__new__(app.Handler)   # no socket needed — we stub _err/_user
    h.path = "/api/explode"
    captured = {}
    h._user = lambda: {"email": "x@humiley.com"}
    h._err = lambda msg, code=200: captured.__setitem__("err", (msg, code))
    before = len(app._ERR_LOG)
    h._serve_request("GET", _boom)
    assert len(app._ERR_LOG) == before + 1
    assert app._ERR_LOG[-1]["error"] == "RuntimeError"
    assert captured["err"][1] == 500, "an unhandled error must produce a 500 response"
