"""
Database layer for the Humiley Timekeeping & Leave Management platform.

Standalone SQLite storage (Python stdlib only) — replaces the original
SharePoint/Graph backend. Holds employees, attendance, leave requests, GPS
zones, and app settings.
"""

import os
import json
import sqlite3
from datetime import datetime, timezone

import seed_data

DB_PATH = os.environ.get("TK_DB_PATH", os.path.join(os.path.dirname(__file__), "timekeeping.db"))


def get_conn():
    conn = sqlite3.connect(DB_PATH)
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA foreign_keys = ON")
    return conn


def now_iso():
    return datetime.now(timezone.utc).replace(microsecond=0).isoformat()


# ---------------------------------------------------------------------------
# Schema
# ---------------------------------------------------------------------------

def init_db():
    conn = get_conn()
    conn.executescript(
        """
        CREATE TABLE IF NOT EXISTS employees (
            id          TEXT PRIMARY KEY,
            name        TEXT NOT NULL,
            ini         TEXT,
            clr         TEXT,
            dept        TEXT,
            title       TEXT,
            email       TEXT UNIQUE,
            phone       TEXT,
            startDate   TEXT,
            status      TEXT DEFAULT 'Active',
            zone        TEXT,
            gender      TEXT,
            dob         TEXT,
            taxId       TEXT,
            bank        TEXT,
            emergency   TEXT,
            address     TEXT,
            managerEmail TEXT,
            jobLevel     TEXT,
            endDate      TEXT,
            serviceDuration TEXT,
            personalId   TEXT,
            familyStatus TEXT,
            education    TEXT,
            employmentType TEXT,
            englishCert  TEXT,
            note         TEXT,
            role        TEXT DEFAULT 'staff',
            annualUsed  INTEGER DEFAULT 0,
            annualTotal INTEGER DEFAULT 12,
            sickUsed    INTEGER DEFAULT 0,
            sickTotal   INTEGER DEFAULT 30,
            compoff     INTEGER DEFAULT 0
        );

        CREATE TABLE IF NOT EXISTS attendance (
            id        INTEGER PRIMARY KEY AUTOINCREMENT,
            emp_id    TEXT NOT NULL,
            name      TEXT,
            dept      TEXT,
            date      TEXT NOT NULL,
            clock_in  TEXT,
            clock_out TEXT,
            status    TEXT,
            hrs       TEXT,
            loc       TEXT,
            lat       REAL,
            lon       REAL,
            FOREIGN KEY (emp_id) REFERENCES employees (id) ON DELETE CASCADE
        );

        CREATE TABLE IF NOT EXISTS leave (
            id         INTEGER PRIMARY KEY AUTOINCREMENT,
            emp_id     TEXT NOT NULL,
            type       TEXT,
            startDate  TEXT,
            endDate    TEXT,
            days       INTEGER,
            status     TEXT DEFAULT 'pending',
            reason     TEXT,
            note       TEXT,
            created_at TEXT,
            FOREIGN KEY (emp_id) REFERENCES employees (id) ON DELETE CASCADE
        );

        CREATE TABLE IF NOT EXISTS zones (
            id     INTEGER PRIMARY KEY AUTOINCREMENT,
            name   TEXT,
            lat    REAL,
            lon    REAL,
            radius INTEGER
        );

        CREATE TABLE IF NOT EXISTS settings (
            key   TEXT PRIMARY KEY,
            value TEXT
        );

        CREATE INDEX IF NOT EXISTS idx_att_emp  ON attendance (emp_id);
        CREATE INDEX IF NOT EXISTS idx_att_date ON attendance (date);
        CREATE INDEX IF NOT EXISTS idx_leave_emp ON leave (emp_id);
        """
    )
    # migration: add newer columns to older databases
    for col in ("managerEmail TEXT", "jobLevel TEXT", "endDate TEXT", "serviceDuration TEXT",
                "personalId TEXT", "familyStatus TEXT", "education TEXT", "employmentType TEXT",
                "englishCert TEXT", "note TEXT"):
        try:
            conn.execute("ALTER TABLE employees ADD COLUMN " + col)
        except sqlite3.OperationalError:
            pass  # column already exists
    conn.commit()
    conn.close()


def is_seeded():
    conn = get_conn()
    n = conn.execute("SELECT COUNT(*) AS n FROM employees").fetchone()["n"]
    conn.close()
    return n > 0


def seed():
    """Populate the database from seed_data on first run only."""
    if is_seeded():
        return False
    conn = get_conn()
    cur = conn.cursor()
    for e in seed_data.EMPLOYEES:
        role = "manager" if e["title"] in seed_data.MANAGER_TITLES else "staff"
        cols = ["id", "name", "ini", "clr", "dept", "title", "email", "phone", "startDate",
                "status", "zone", "gender", "dob", "taxId", "bank", "emergency", "address",
                "role", "annualUsed", "annualTotal", "sickUsed", "sickTotal", "compoff"]
        vals = [e.get(c) for c in cols[:-6]] + [role, e["annualUsed"], e["annualTotal"],
                                                 e["sickUsed"], e["sickTotal"], e["compoff"]]
        cur.execute("INSERT INTO employees (%s) VALUES (%s)" % (
            ",".join(cols), ",".join(["?"] * len(cols))), vals)
    for z in seed_data.ZONES:
        cur.execute("INSERT INTO zones (name,lat,lon,radius) VALUES (?,?,?,?)",
                    (z["name"], z["lat"], z["lon"], z["radius"]))
    for a in seed_data.sample_attendance():
        cur.execute("INSERT INTO attendance (emp_id,name,dept,date,clock_in,clock_out,status,hrs,loc) "
                    "VALUES (?,?,?,?,?,?,?,?,?)",
                    (a["emp_id"], a["name"], a["dept"], a["date"], a.get("clock_in"),
                     a.get("clock_out"), a["status"], a.get("hrs"), a.get("loc")))
    for l in seed_data.LEAVE:
        cur.execute("INSERT INTO leave (emp_id,type,startDate,endDate,days,status,reason,created_at) "
                    "VALUES (?,?,?,?,?,?,?,?)",
                    (l["emp_id"], l["type"], l["startDate"], l["endDate"], l["days"],
                     l["status"], l["reason"], now_iso()))
    conn.commit()
    conn.close()
    return True


# ---------------------------------------------------------------------------
# Generic helpers
# ---------------------------------------------------------------------------

def _rows(sql, params=()):
    conn = get_conn()
    rows = conn.execute(sql, params).fetchall()
    conn.close()
    return [dict(r) for r in rows]


def _row(sql, params=()):
    conn = get_conn()
    row = conn.execute(sql, params).fetchone()
    conn.close()
    return dict(row) if row else None


# ---------------------------------------------------------------------------
# Employees
# ---------------------------------------------------------------------------

EMP_FIELDS = ["name", "ini", "clr", "dept", "title", "email", "phone", "startDate",
              "status", "zone", "gender", "dob", "taxId", "bank", "emergency", "address",
              "managerEmail", "jobLevel", "endDate", "serviceDuration", "personalId",
              "familyStatus", "education", "employmentType", "englishCert", "note",
              "role", "annualUsed", "annualTotal", "sickUsed", "sickTotal", "compoff"]


def list_employees():
    return _rows("SELECT * FROM employees ORDER BY id")


def get_employee(emp_id):
    return _row("SELECT * FROM employees WHERE id = ?", (emp_id,))


def get_employee_by_email(email):
    if not email:
        return None
    return _row("SELECT * FROM employees WHERE LOWER(email) = LOWER(?)", (email.strip(),))


def next_emp_id():
    rows = _rows("SELECT id FROM employees WHERE id LIKE 'EMP%'")
    nums = [int(r["id"][3:]) for r in rows if r["id"][3:].isdigit()]
    return "EMP%03d" % ((max(nums) + 1) if nums else 1)


def create_employee(data):
    emp_id = data.get("id") or next_emp_id()
    fields = ["id"] + EMP_FIELDS
    vals = [emp_id] + [data.get(f) for f in EMP_FIELDS]
    conn = get_conn()
    conn.execute("INSERT INTO employees (%s) VALUES (%s)" % (
        ",".join(fields), ",".join(["?"] * len(fields))), vals)
    conn.commit()
    conn.close()
    return emp_id


def update_employee(emp_id, data):
    sets, params = [], []
    for f in EMP_FIELDS:
        if f in data:
            sets.append("%s = ?" % f)
            params.append(data[f])
    if not sets:
        return
    params.append(emp_id)
    conn = get_conn()
    conn.execute("UPDATE employees SET %s WHERE id = ?" % ",".join(sets), params)
    conn.commit()
    conn.close()


def delete_employee(emp_id):
    conn = get_conn()
    conn.execute("DELETE FROM employees WHERE id = ?", (emp_id,))
    conn.commit()
    conn.close()


# ---------------------------------------------------------------------------
# Attendance
# ---------------------------------------------------------------------------

def list_attendance(emp_id=None, start=None, end=None):
    sql = "SELECT * FROM attendance WHERE 1=1"
    params = []
    if emp_id:
        sql += " AND emp_id = ?"; params.append(emp_id)
    if start:
        sql += " AND date >= ?"; params.append(start)
    if end:
        sql += " AND date <= ?"; params.append(end)
    sql += " ORDER BY date DESC, clock_in DESC"
    return _rows(sql, params)


def open_attendance(emp_id, date):
    return _row("SELECT * FROM attendance WHERE emp_id = ? AND date = ? AND clock_out IS NULL "
                "ORDER BY id DESC LIMIT 1", (emp_id, date))


def _hrs_between(cin, cout):
    try:
        ih, im = map(int, cin.split(":")); oh, om = map(int, cout.split(":"))
        mins = (oh * 60 + om) - (ih * 60 + im)
        return "%dh %02dm" % (mins // 60, mins % 60)
    except (ValueError, AttributeError):
        return ""


def clock_in(emp_id, date, time_hm, loc=None, lat=None, lon=None, status="on-time"):
    emp = get_employee(emp_id)
    conn = get_conn()
    cur = conn.execute(
        "INSERT INTO attendance (emp_id,name,dept,date,clock_in,status,loc,lat,lon) "
        "VALUES (?,?,?,?,?,?,?,?,?)",
        (emp_id, emp["name"] if emp else None, emp["dept"] if emp else None,
         date, time_hm, status, loc, lat, lon))
    conn.commit()
    rid = cur.lastrowid
    conn.close()
    return rid


def clock_out(att_id, time_hm):
    rec = _row("SELECT * FROM attendance WHERE id = ?", (att_id,))
    if not rec:
        return None
    hrs = _hrs_between(rec["clock_in"], time_hm)
    conn = get_conn()
    conn.execute("UPDATE attendance SET clock_out = ?, hrs = ? WHERE id = ?", (time_hm, hrs, att_id))
    conn.commit()
    conn.close()
    return hrs


# ---------------------------------------------------------------------------
# Leave
# ---------------------------------------------------------------------------

def list_leave(emp_id=None, status=None, emp_ids=None):
    sql = ("SELECT l.*, e.name AS emp_name, e.dept AS emp_dept, e.managerEmail AS emp_managerEmail "
           "FROM leave l LEFT JOIN employees e ON e.id = l.emp_id WHERE 1=1")
    params = []
    if emp_id:
        sql += " AND l.emp_id = ?"; params.append(emp_id)
    if emp_ids is not None:
        if not emp_ids:
            return []
        sql += " AND l.emp_id IN (%s)" % ",".join(["?"] * len(emp_ids))
        params.extend(emp_ids)
    if status:
        sql += " AND l.status = ?"; params.append(status)
    sql += " ORDER BY l.startDate DESC"
    return _rows(sql, params)


def list_reports(manager_email):
    """Employees whose direct manager is the given email."""
    if not manager_email:
        return []
    return _rows("SELECT * FROM employees WHERE LOWER(managerEmail) = LOWER(?)", (manager_email,))


def get_leave(leave_id):
    return _row("SELECT * FROM leave WHERE id = ?", (leave_id,))


def create_leave(data):
    conn = get_conn()
    cur = conn.execute(
        "INSERT INTO leave (emp_id,type,startDate,endDate,days,status,reason,created_at) "
        "VALUES (?,?,?,?,?,?,?,?)",
        (data["emp_id"], data.get("type"), data.get("startDate"), data.get("endDate"),
         data.get("days"), data.get("status", "pending"), data.get("reason"), now_iso()))
    conn.commit()
    rid = cur.lastrowid
    conn.close()
    return rid


def set_leave_status(leave_id, status, note=None):
    conn = get_conn()
    conn.execute("UPDATE leave SET status = ?, note = ? WHERE id = ?", (status, note, leave_id))
    conn.commit()
    conn.close()


# ---------------------------------------------------------------------------
# Zones
# ---------------------------------------------------------------------------

def list_zones():
    return _rows("SELECT * FROM zones ORDER BY id")


def create_zone(data):
    conn = get_conn()
    cur = conn.execute("INSERT INTO zones (name,lat,lon,radius) VALUES (?,?,?,?)",
                       (data.get("name"), data.get("lat"), data.get("lon"), data.get("radius")))
    conn.commit()
    rid = cur.lastrowid
    conn.close()
    return rid


def update_zone(zone_id, data):
    sets, params = [], []
    for f in ("name", "lat", "lon", "radius"):
        if f in data:
            sets.append("%s = ?" % f); params.append(data[f])
    if not sets:
        return
    params.append(zone_id)
    conn = get_conn()
    conn.execute("UPDATE zones SET %s WHERE id = ?" % ",".join(sets), params)
    conn.commit()
    conn.close()


def delete_zone(zone_id):
    conn = get_conn()
    conn.execute("DELETE FROM zones WHERE id = ?", (zone_id,))
    conn.commit()
    conn.close()


# ---------------------------------------------------------------------------
# Settings
# ---------------------------------------------------------------------------

def get_setting(key, default=None):
    row = _row("SELECT value FROM settings WHERE key = ?", (key,))
    return json.loads(row["value"]) if row else default


def set_setting(key, value):
    conn = get_conn()
    conn.execute("INSERT INTO settings (key,value) VALUES (?,?) "
                 "ON CONFLICT(key) DO UPDATE SET value = excluded.value",
                 (key, json.dumps(value)))
    conn.commit()
    conn.close()
