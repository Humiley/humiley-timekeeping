"""Two platform-integrity guards.

A) /api/health is a REAL readiness probe. It gates the container healthcheck and Caddy's
   `depends_on: service_healthy`, so "SQLite answered SELECT 1" was not good enough — a missing or
   truncated HTML shell, or a DB whose core tables are gone, must report 503.

B) Deleting an employee must not destroy or orphan their history. attendance/leave/esign_pin cascade
   ON DELETE, and the JSON store has no FKs, so an employee with any history is deactivated, never
   deleted.
"""
import os

import app
import db


# ── A) readiness probe ───────────────────────────────────────────────────────

def _fresh_probe():
    app._HEALTH_CACHE["until"] = 0.0        # bypass the 5s memo between assertions
    app._SHELL_CACHE["sig"] = None
    return app._health_probe()


def test_health_is_ok_and_reports_the_new_fields(api, tokens):
    st, b = api("GET", "/api/health")
    assert st == 200 and b["status"] == "ok"
    assert b["db"] is True and b["shell"] is True and b["detail"] == ""
    assert "version" in b and "uptime_s" in b          # unchanged contract for existing monitors


def test_missing_or_truncated_shell_makes_it_not_ready(monkeypatch, tmp_path):
    # a shell that is present but truncated (the "bad build baked a broken index.html" case)
    stub = tmp_path / "app"; (stub / "templates").mkdir(parents=True)
    (stub / "templates" / "index.html").write_bytes(b"<html>oops")     # way under the size floor
    monkeypatch.setattr(app.os.path, "abspath", lambda p: str(stub / "app.py"))
    assert _fresh_probe()["shell"] is False
    assert _fresh_probe()["ok"] is False


def test_probe_detects_a_db_with_core_tables_missing(monkeypatch, tmp_path):
    import sqlite3
    empty = tmp_path / "empty.db"
    sqlite3.connect(str(empty)).close()                 # a real SQLite file with NO tables
    saved = db.DB_PATH
    db.DB_PATH = str(empty)
    try:
        r = _fresh_probe()
        assert r["db"] is False and r["ok"] is False
        assert "core table" in r["detail"]              # SELECT 1 would have passed here
    finally:
        db.DB_PATH = saved
    assert _fresh_probe()["ok"] is True                 # and it recovers


def test_probe_result_is_memoised():
    _fresh_probe()
    calls = {"n": 0}
    real = app._shell_ok
    app._shell_ok = lambda: (calls.__setitem__("n", calls["n"] + 1), real())[1]
    try:
        for _ in range(5):
            app._health_probe()                          # inside the TTL
        assert calls["n"] == 0, "cached probe must not re-run the checks"
    finally:
        app._shell_ok = real


# ── B) employee delete referential integrity ─────────────────────────────────

def _mk_emp(eid="HML-DELTEST", name="Delete Me"):
    db.create_employee({"id": eid, "name": name, "email": eid.lower() + "@humiley.com",
                        "role": "staff", "level": "staff", "title": "Engineer"})
    return eid


def test_employee_with_no_history_can_still_be_deleted(api, tokens):
    eid = _mk_emp("HML-CLEAN", "Clean Leaver")
    st, b = api("DELETE", "/api/employees/" + eid, tokens["admin"])
    assert st == 200, b
    assert db.get_employee(eid) is None
    # and the deletion is on the audit trail
    assert any(r.get("target") == "employees/" + eid for r in db.list_collection("audit"))


def test_employee_with_finance_history_is_refused_not_destroyed(api, tokens):
    eid = _mk_emp("HML-HASCLAIM", "Has Claims")
    db.put_collection_item("claims", {"empId": eid, "name": "Has Claims", "amount": 1_000_000,
                                      "status": "Approved"})
    st, r = api("DELETE", "/api/employees/" + eid, tokens["admin"])
    assert st == 409, (st, r)
    assert "cannot be deleted" in str(r).lower() and "inactive" in str(r).lower()
    assert db.get_employee(eid) is not None, "the employee must survive the refused delete"


def test_attendance_history_blocks_deletion_because_it_would_cascade_away(api, tokens):
    eid = _mk_emp("HML-HASATT", "Has Attendance")
    db.clock_in(eid, "Has Attendance", "", "2026-08-03", "08:00", "On time", "HQ")
    assert db.employee_references(eid), "attendance must be seen as history"
    st, r = api("DELETE", "/api/employees/" + eid, tokens["admin"])
    assert st == 409, (st, r)
    assert db.get_employee(eid) is not None


def test_deleting_a_missing_employee_is_404_not_silent_ok(api, tokens):
    st, _ = api("DELETE", "/api/employees/HML-NOSUCH", tokens["admin"])
    assert st == 404


def test_references_finds_nested_ids(api, tokens):
    eid = _mk_emp("HML-NESTED", "Nested Ref")
    db.put_collection_item("devices", {"name": "Laptop",
                                       "assignments": [{"empId": eid, "qty": 1}]})   # nested, not top level
    assert "devices" in db.employee_references(eid)
