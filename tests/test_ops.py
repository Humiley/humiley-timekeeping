"""Ops / observability: health probe, admin error-review gate, and unhandled-error capture."""
import app
import db


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


def test_audit_is_append_only(api, tokens):
    # a stored audit event must never be editable (21 CFR Part 11 append-only)
    st, r = api("POST", "/api/coll/audit", tokens["staff"],
                {"actor": "x", "action": "Test event", "target": "t/1", "detail": "d"})
    assert st == 200, r
    aid = r["item"]["id"]
    st, _ = api("PATCH", "/api/coll/audit/" + aid, tokens["admin"],
                {"actor": "x", "action": "TAMPERED", "target": "t/1", "detail": "d"})
    assert st == 403, "audit rows must not be updatable"


def test_money_validation_rejects_nan(api, tokens):
    # NaN/inf must be refused (they bypass the numeric bounds and corrupt the collection JSON)
    st, _ = api("POST", "/api/coll/payments", tokens["staff"],
                {"reqNo": "PR-NAN", "payee": "X", "category": "Office",
                 "amount": float("inf"), "status": "Submitted",
                 "attachment": "data:application/pdf;base64,JVBERi0="})
    assert st == 400, "an infinite amount must be rejected"


def _boom():
    raise RuntimeError("kaboom")


def test_audit_read_is_scoped_for_non_admin(api, tokens):
    """The full audit trail is admin-only (matching the admin-only Audit Log view). A non-admin
    reader — e.g. the management-level Signature Governance page — gets ONLY e-signature events,
    so deletions / access-level changes can't be pulled via the API by a manager+ account."""
    db.put_collection_item("audit", {"ts": "2026-07-18T01:00:00Z", "actor": "x",
                                     "action": "E-signature — Approve", "target": "payments/p1", "detail": ""})
    db.put_collection_item("audit", {"ts": "2026-07-18T02:00:00Z", "actor": "x",
                                     "action": "Delete payment", "target": "payments/p9", "detail": ""})
    db.put_collection_item("audit", {"ts": "2026-07-18T03:00:00Z", "actor": "x",
                                     "action": "Access level changed", "target": "employees/e1", "detail": ""})

    # management (the Signature Governance level) — e-signature events ONLY
    st, r = api("GET", "/api/coll/audit", tokens["management"])
    assert st == 200
    actions = [x.get("action", "") for x in r["items"]]
    assert actions, "management should still get the e-signature subset (esigngov needs it)"
    assert all("e-signature" in a.lower() for a in actions), \
        "a non-admin must NOT see delete / access-change audit rows"

    # admin — the full trail
    st, r = api("GET", "/api/coll/audit", tokens["admin"])
    assert st == 200
    actions = [x.get("action", "") for x in r["items"]]
    assert any("delete" in a.lower() for a in actions)
    assert any("access level" in a.lower() for a in actions)


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
