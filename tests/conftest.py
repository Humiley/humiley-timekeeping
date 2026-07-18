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
    def _call(method, path, token=None, body=None):
        data = json.dumps(body).encode() if body is not None else None
        req = urllib.request.Request(base_url + path, data=data, method=method)
        req.add_header("Content-Type", "application/json")
        if token:
            req.add_header("Authorization", "Bearer " + token)
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
