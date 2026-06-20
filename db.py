"""
Database layer for the Humiley TimeKeeping web app.

Uses Python's built-in sqlite3 — no external dependencies. The whole data
model lives in a single SQLite file (timekeeping.db by default).
"""

import os
import sqlite3
import hashlib
import secrets
from datetime import datetime, timezone

DB_PATH = os.environ.get("TK_DB_PATH", os.path.join(os.path.dirname(__file__), "timekeeping.db"))

# ---------------------------------------------------------------------------
# Connection helpers
# ---------------------------------------------------------------------------

def get_conn():
    conn = sqlite3.connect(DB_PATH)
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA foreign_keys = ON")
    return conn


def now_iso():
    """Current time as an ISO-8601 UTC string (e.g. 2026-06-20T08:30:00+00:00)."""
    return datetime.now(timezone.utc).replace(microsecond=0).isoformat()


# ---------------------------------------------------------------------------
# PIN / password hashing (pbkdf2-hmac-sha256)
# ---------------------------------------------------------------------------

def hash_pin(pin, salt=None):
    if salt is None:
        salt = secrets.token_hex(16)
    dk = hashlib.pbkdf2_hmac("sha256", str(pin).encode("utf-8"), salt.encode("utf-8"), 100_000)
    return salt + "$" + dk.hex()


def verify_pin(pin, stored):
    try:
        salt, _ = stored.split("$", 1)
    except (ValueError, AttributeError):
        return False
    return secrets.compare_digest(hash_pin(pin, salt), stored)


# ---------------------------------------------------------------------------
# Schema
# ---------------------------------------------------------------------------

def init_db():
    conn = get_conn()
    cur = conn.cursor()
    cur.executescript(
        """
        CREATE TABLE IF NOT EXISTS employees (
            id          INTEGER PRIMARY KEY AUTOINCREMENT,
            name        TEXT    NOT NULL,
            email       TEXT    NOT NULL UNIQUE,
            pin_hash    TEXT    NOT NULL,
            is_admin    INTEGER NOT NULL DEFAULT 0,
            active      INTEGER NOT NULL DEFAULT 1,
            created_at  TEXT    NOT NULL
        );

        CREATE TABLE IF NOT EXISTS time_entries (
            id          INTEGER PRIMARY KEY AUTOINCREMENT,
            employee_id INTEGER NOT NULL,
            clock_in    TEXT    NOT NULL,
            clock_out   TEXT,
            note        TEXT,
            FOREIGN KEY (employee_id) REFERENCES employees (id) ON DELETE CASCADE
        );

        CREATE INDEX IF NOT EXISTS idx_entries_employee ON time_entries (employee_id);
        CREATE INDEX IF NOT EXISTS idx_entries_open ON time_entries (employee_id, clock_out);
        """
    )
    conn.commit()
    conn.close()


def seed_default_admin():
    """Create a default admin account on first run and return its credentials
    (only when freshly created) so they can be printed to the console."""
    email = os.environ.get("TK_ADMIN_EMAIL", "admin@humiley.com")
    pin = os.environ.get("TK_ADMIN_PIN", "2468")
    name = os.environ.get("TK_ADMIN_NAME", "Administrator")

    conn = get_conn()
    cur = conn.cursor()
    existing = cur.execute("SELECT 1 FROM employees WHERE email = ?", (email.lower(),)).fetchone()
    if existing:
        conn.close()
        return None

    cur.execute(
        "INSERT INTO employees (name, email, pin_hash, is_admin, active, created_at) VALUES (?,?,?,?,?,?)",
        (name, email.lower(), hash_pin(pin), 1, 1, now_iso()),
    )
    conn.commit()
    conn.close()
    return {"email": email.lower(), "pin": pin}


# ---------------------------------------------------------------------------
# Employee operations
# ---------------------------------------------------------------------------

def get_employee_by_email(email):
    conn = get_conn()
    row = conn.execute("SELECT * FROM employees WHERE email = ?", (email.lower().strip(),)).fetchone()
    conn.close()
    return dict(row) if row else None


def get_employee(emp_id):
    conn = get_conn()
    row = conn.execute("SELECT * FROM employees WHERE id = ?", (emp_id,)).fetchone()
    conn.close()
    return dict(row) if row else None


def authenticate(email, pin):
    """Return the employee dict if email+pin match and account is active, else None."""
    emp = get_employee_by_email(email)
    if not emp or not emp["active"]:
        return None
    if not verify_pin(pin, emp["pin_hash"]):
        return None
    return emp


def create_employee(name, email, pin, is_admin=False):
    conn = get_conn()
    try:
        cur = conn.execute(
            "INSERT INTO employees (name, email, pin_hash, is_admin, active, created_at) VALUES (?,?,?,?,?,?)",
            (name.strip(), email.lower().strip(), hash_pin(pin), 1 if is_admin else 0, 1, now_iso()),
        )
        conn.commit()
        return cur.lastrowid
    finally:
        conn.close()


def update_employee(emp_id, name=None, email=None, pin=None, is_admin=None, active=None):
    sets, params = [], []
    if name is not None:
        sets.append("name = ?"); params.append(name.strip())
    if email is not None:
        sets.append("email = ?"); params.append(email.lower().strip())
    if pin is not None and str(pin).strip():
        sets.append("pin_hash = ?"); params.append(hash_pin(pin))
    if is_admin is not None:
        sets.append("is_admin = ?"); params.append(1 if is_admin else 0)
    if active is not None:
        sets.append("active = ?"); params.append(1 if active else 0)
    if not sets:
        return
    params.append(emp_id)
    conn = get_conn()
    conn.execute("UPDATE employees SET " + ", ".join(sets) + " WHERE id = ?", params)
    conn.commit()
    conn.close()


def list_employees():
    conn = get_conn()
    rows = conn.execute("SELECT * FROM employees ORDER BY name COLLATE NOCASE").fetchall()
    conn.close()
    return [dict(r) for r in rows]


# ---------------------------------------------------------------------------
# Clock in / out
# ---------------------------------------------------------------------------

def get_open_entry(emp_id):
    conn = get_conn()
    row = conn.execute(
        "SELECT * FROM time_entries WHERE employee_id = ? AND clock_out IS NULL ORDER BY clock_in DESC LIMIT 1",
        (emp_id,),
    ).fetchone()
    conn.close()
    return dict(row) if row else None


def clock_in(emp_id, note=None):
    if get_open_entry(emp_id):
        raise ValueError("You are already clocked in.")
    conn = get_conn()
    ts = now_iso()
    conn.execute(
        "INSERT INTO time_entries (employee_id, clock_in, note) VALUES (?,?,?)",
        (emp_id, ts, note),
    )
    conn.commit()
    conn.close()
    return ts


def clock_out(emp_id, note=None):
    open_entry = get_open_entry(emp_id)
    if not open_entry:
        raise ValueError("You are not clocked in.")
    conn = get_conn()
    ts = now_iso()
    if note:
        conn.execute(
            "UPDATE time_entries SET clock_out = ?, note = ? WHERE id = ?",
            (ts, note, open_entry["id"]),
        )
    else:
        conn.execute("UPDATE time_entries SET clock_out = ? WHERE id = ?", (ts, open_entry["id"]))
    conn.commit()
    conn.close()
    return ts


def list_entries(emp_id, limit=50):
    conn = get_conn()
    rows = conn.execute(
        "SELECT * FROM time_entries WHERE employee_id = ? ORDER BY clock_in DESC LIMIT ?",
        (emp_id, limit),
    ).fetchall()
    conn.close()
    return [dict(r) for r in rows]


def all_entries(start=None, end=None, emp_id=None):
    """Join entries with employee info; optional date range (ISO date strings) and employee filter."""
    sql = (
        "SELECT te.*, e.name AS employee_name, e.email AS employee_email "
        "FROM time_entries te JOIN employees e ON e.id = te.employee_id WHERE 1=1"
    )
    params = []
    if emp_id:
        sql += " AND te.employee_id = ?"; params.append(emp_id)
    if start:
        sql += " AND te.clock_in >= ?"; params.append(start)
    if end:
        sql += " AND te.clock_in <= ?"; params.append(end + "T23:59:59+00:00")
    sql += " ORDER BY te.clock_in DESC"
    conn = get_conn()
    rows = conn.execute(sql, params).fetchall()
    conn.close()
    return [dict(r) for r in rows]
