"""Test harness for the Humiley portal backend.

Spins the real Handler up on a random port over a throwaway SQLite DB, seeds a small org
(admin / dept-manager / two staff), and hands tests both raw session tokens and an `api()`
caller. Env is set at import time — BEFORE app/db are imported — so the temp DB is used.
"""
import os
import sys
import json
import socket
import tempfile
import threading
import urllib.request
import urllib.error
from http.server import ThreadingHTTPServer

import pytest

# --- point the app at a throwaway DB + a test pepper, before importing it -------------------
os.environ["TK_DB_PATH"] = os.path.join(tempfile.mkdtemp(prefix="tk-test-"), "test.db")
os.environ.setdefault("TK_ESIGN_PEPPER", "test-pepper-abcdefghijklmnop")
os.environ.setdefault("TK_AUDIT_PEPPER", "test-audit-pepper-qrstuvwxyz")   # keys the audit hash chain
os.environ.setdefault("TK_ADMIN_EMAIL", "admin@humiley.com")
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

import db     # noqa: E402
import app    # noqa: E402


@pytest.fixture(scope="session")
def base_url():
    db.init_db()
    if not db.list_employees():
        db.create_employee({"id": "HML-ADM", "name": "Admin User", "email": "admin@humiley.com",
                             "role": "manager", "level": "admin", "title": "Managing Director",
                             "annualTotal": 12, "annualUsed": 0, "sickTotal": 30, "sickUsed": 0})
        db.create_employee({"id": "HML-MGR", "name": "Dept Manager", "email": "mgr@humiley.com",
                             "role": "manager", "level": "manager", "title": "Manager",
                             "managerEmail": "admin@humiley.com"})
        db.create_employee({"id": "HML-STF", "name": "Staff One", "email": "staff1@humiley.com",
                             "role": "staff", "level": "staff", "title": "Engineer",
                             "managerEmail": "mgr@humiley.com",
                             "annualTotal": 12, "annualUsed": 0, "sickTotal": 30, "sickUsed": 0})
        db.create_employee({"id": "HML-OTH", "name": "Other Staff", "email": "other@humiley.com",
                             "role": "staff", "level": "staff", "title": "Engineer",
                             "managerEmail": "admin@humiley.com"})
        # Finance/Approver (management level) + Editor — for the Invoice Tracking access boundary.
        db.create_employee({"id": "HML-MGT", "name": "Finance Approver", "email": "fin@humiley.com",
                             "role": "manager", "level": "management", "title": "Finance Approver"})
        db.create_employee({"id": "HML-EDT", "name": "Editor User", "email": "editor@humiley.com",
                             "role": "manager", "level": "editor", "title": "Finance Editor"})
    s = socket.socket()
    s.bind(("127.0.0.1", 0))
    port = s.getsockname()[1]
    s.close()
    srv = ThreadingHTTPServer(("127.0.0.1", port), app.Handler)
    threading.Thread(target=srv.serve_forever, daemon=True).start()
    yield "http://127.0.0.1:%d" % port
    srv.shutdown()


@pytest.fixture(scope="session")
def tokens(base_url):
    # tokens carry only the emp_id; the caller's level is re-read from the employee row each request.
    return {
        "admin": app.new_session("HML-ADM", "manager"),
        "mgr": app.new_session("HML-MGR", "manager"),
        "staff": app.new_session("HML-STF", "staff"),
        "other": app.new_session("HML-OTH", "staff"),
        "management": app.new_session("HML-MGT", "manager"),  # Finance/Approver level
        "editor": app.new_session("HML-EDT", "manager"),
    }


@pytest.fixture
def api(base_url):
    def _call(method, path, token=None, body=None, headers=None):
        data = json.dumps(body).encode() if body is not None else None
        req = urllib.request.Request(base_url + path, data=data, method=method)
        req.add_header("Content-Type", "application/json")
        if token:
            req.add_header("Authorization", "Bearer " + token)
        for _k, _v in (headers or {}).items():
            req.add_header(_k, str(_v))
        try:
            with urllib.request.urlopen(req, timeout=10) as r:
                raw = r.read().decode() or "{}"
                return r.status, (json.loads(raw) if raw.strip() else {})
        except urllib.error.HTTPError as e:
            try:
                return e.code, json.loads(e.read().decode() or "{}")
            except Exception:
                return e.code, {}
    return _call


@pytest.fixture(autouse=True)
def _reset_global_state():
    # The idempotency cache is module-global and outlives a single test; different tests reuse the
    # same financial payload as a fixture, so without this a later identical submit would dedup to an
    # earlier test's record. Clear it before each test (same hygiene as the rate limiter's _RATE).
    try:
        app._IDEM.clear()
    except Exception:
        pass
    yield


@pytest.fixture(autouse=True)
def _company_tax_settings_are_not_shared_between_tests():
    """Restore every `portal_vat_*` setting after each test.

    These are COMPANY-level settings in one shared test database, so a test that records "deposits
    include VAT" or a discount threshold silently rewrote the tax treatment for every test that ran
    after it — which is how a receivables test came to report ₫212,727,272.73 of advance owed back
    instead of ₫240,000,000, with nothing wrong in the code it was testing. Save and restore rather
    than wipe, so the per-file cleanup fixtures still do their own thing.
    """
    def _has_settings(conn):
        # Pure-module test files never boot the server, so the schema may not exist yet. Checked
        # explicitly rather than caught: a bare except here would also swallow a real DB failure
        # and quietly stop restoring anything.
        return bool(conn.execute("SELECT name FROM sqlite_master WHERE type='table' AND name='settings'").fetchone())

    conn = db.get_conn()
    live = _has_settings(conn)
    before = {} if not live else {k: v for k, v in conn.execute(
        "SELECT key, value FROM settings WHERE key LIKE 'portal_vat_%'").fetchall()}
    conn.close()
    yield
    conn = db.get_conn()
    if not _has_settings(conn):
        conn.close(); return
    conn.execute("DELETE FROM settings WHERE key LIKE 'portal_vat_%'")
    for k, v in before.items():
        conn.execute("INSERT INTO settings (key, value) VALUES (?, ?)", (k, v))
    conn.commit(); conn.close()
