"""
Humiley TimeKeeping — web app server.

A dependency-free web app built on Python's standard library:
  - http.server for the HTTP layer
  - sqlite3 for storage (see db.py)

Run it with:   python3 app.py
Then open:     http://localhost:8000
"""

import json
import os
import secrets
import time
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from urllib.parse import urlparse, parse_qs

import db

HOST = os.environ.get("TK_HOST", "0.0.0.0")
PORT = int(os.environ.get("TK_PORT", "8000"))
BASE_DIR = os.path.dirname(os.path.abspath(__file__))
STATIC_DIR = os.path.join(BASE_DIR, "static")
TEMPLATE_DIR = os.path.join(BASE_DIR, "templates")

# In-memory admin sessions: token -> {employee_id, expires}
SESSIONS = {}
SESSION_TTL = 8 * 60 * 60  # 8 hours


def new_session(emp_id):
    token = secrets.token_urlsafe(32)
    SESSIONS[token] = {"employee_id": emp_id, "expires": time.time() + SESSION_TTL}
    return token


def session_employee(token):
    sess = SESSIONS.get(token)
    if not sess:
        return None
    if sess["expires"] < time.time():
        SESSIONS.pop(token, None)
        return None
    return db.get_employee(sess["employee_id"])


CONTENT_TYPES = {
    ".html": "text/html; charset=utf-8",
    ".css": "text/css; charset=utf-8",
    ".js": "application/javascript; charset=utf-8",
    ".svg": "image/svg+xml",
    ".ico": "image/x-icon",
}


class Handler(BaseHTTPRequestHandler):
    server_version = "HumileyTimeKeeping/1.0"

    # -- helpers ------------------------------------------------------------
    def _json(self, obj, status=200):
        body = json.dumps(obj).encode("utf-8")
        self.send_response(status)
        self.send_header("Content-Type", "application/json; charset=utf-8")
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        self.wfile.write(body)

    def _error(self, message, status=400):
        self._json({"error": message}, status)

    def _read_json(self):
        length = int(self.headers.get("Content-Length", 0))
        if length == 0:
            return {}
        raw = self.rfile.read(length)
        try:
            return json.loads(raw.decode("utf-8"))
        except (ValueError, UnicodeDecodeError):
            return {}

    def _bearer(self):
        auth = self.headers.get("Authorization", "")
        if auth.startswith("Bearer "):
            return auth[7:].strip()
        return None

    def _require_admin(self):
        emp = session_employee(self._bearer() or "")
        if not emp or not emp["is_admin"]:
            self._error("Admin authentication required.", 401)
            return None
        return emp

    def _serve_file(self, path, content_type=None):
        if not os.path.isfile(path):
            self._error("Not found.", 404)
            return
        ext = os.path.splitext(path)[1]
        ctype = content_type or CONTENT_TYPES.get(ext, "application/octet-stream")
        with open(path, "rb") as f:
            body = f.read()
        self.send_response(200)
        self.send_header("Content-Type", ctype)
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        self.wfile.write(body)

    def log_message(self, fmt, *args):  # quieter, single-line logging
        print("%s - %s" % (self.address_string(), fmt % args))

    # -- routing ------------------------------------------------------------
    def do_GET(self):
        parsed = urlparse(self.path)
        path = parsed.path
        qs = parse_qs(parsed.query)

        if path == "/" or path == "/index.html":
            return self._serve_file(os.path.join(TEMPLATE_DIR, "index.html"))
        if path == "/admin" or path == "/admin.html":
            return self._serve_file(os.path.join(TEMPLATE_DIR, "admin.html"))
        if path.startswith("/static/"):
            rel = path[len("/static/"):]
            safe = os.path.normpath(os.path.join(STATIC_DIR, rel))
            if not safe.startswith(STATIC_DIR):
                return self._error("Forbidden.", 403)
            return self._serve_file(safe)

        if path == "/api/status":
            return self.api_status(qs)
        if path == "/api/admin/employees":
            return self.api_admin_employees_list()
        if path == "/api/admin/entries":
            return self.api_admin_entries(qs)
        if path == "/api/admin/summary":
            return self.api_admin_summary(qs)
        if path == "/api/admin/export.csv":
            return self.api_admin_export(qs)

        return self._error("Not found.", 404)

    def do_POST(self):
        path = urlparse(self.path).path
        body = self._read_json()

        if path == "/api/clock":
            return self.api_clock(body)
        if path == "/api/history":
            return self.api_history(body)
        if path == "/api/admin/login":
            return self.api_admin_login(body)
        if path == "/api/admin/employees":
            return self.api_admin_create_employee(body)

        return self._error("Not found.", 404)

    def do_PATCH(self):
        path = urlparse(self.path).path
        body = self._read_json()
        # /api/admin/employees/<id>
        if path.startswith("/api/admin/employees/"):
            try:
                emp_id = int(path.rsplit("/", 1)[1])
            except ValueError:
                return self._error("Invalid employee id.", 400)
            return self.api_admin_update_employee(emp_id, body)
        return self._error("Not found.", 404)

    # -- employee endpoints -------------------------------------------------
    def api_clock(self, body):
        email = (body.get("email") or "").strip()
        pin = (body.get("pin") or "").strip()
        note = (body.get("note") or "").strip() or None
        if not email or not pin:
            return self._error("Email and PIN are required.")
        emp = db.authenticate(email, pin)
        if not emp:
            return self._error("Invalid email or PIN, or account is inactive.", 401)

        open_entry = db.get_open_entry(emp["id"])
        try:
            if open_entry:
                ts = db.clock_out(emp["id"], note)
                action = "out"
            else:
                ts = db.clock_in(emp["id"], note)
                action = "in"
        except ValueError as e:
            return self._error(str(e))

        return self._json({
            "ok": True,
            "action": action,
            "timestamp": ts,
            "employee": {"name": emp["name"], "email": emp["email"]},
        })

    def api_status(self, qs):
        email = (qs.get("email", [""])[0]).strip()
        if not email:
            return self._error("Email is required.")
        emp = db.get_employee_by_email(email)
        if not emp:
            return self._error("Employee not found.", 404)
        open_entry = db.get_open_entry(emp["id"])
        return self._json({
            "name": emp["name"],
            "email": emp["email"],
            "clocked_in": bool(open_entry),
            "since": open_entry["clock_in"] if open_entry else None,
        })

    def api_history(self, body):
        email = (body.get("email") or "").strip()
        pin = (body.get("pin") or "").strip()
        emp = db.authenticate(email, pin)
        if not emp:
            return self._error("Invalid email or PIN.", 401)
        entries = db.list_entries(emp["id"], limit=100)
        open_entry = db.get_open_entry(emp["id"])
        return self._json({
            "employee": {"name": emp["name"], "email": emp["email"]},
            "clocked_in": bool(open_entry),
            "entries": entries,
        })

    # -- admin endpoints ----------------------------------------------------
    def api_admin_login(self, body):
        email = (body.get("email") or "").strip()
        pin = (body.get("pin") or "").strip()
        emp = db.authenticate(email, pin)
        if not emp or not emp["is_admin"]:
            return self._error("Invalid admin credentials.", 401)
        token = new_session(emp["id"])
        return self._json({"token": token, "name": emp["name"], "email": emp["email"]})

    def api_admin_employees_list(self):
        if not self._require_admin():
            return
        emps = db.list_employees()
        out = []
        for e in emps:
            open_entry = db.get_open_entry(e["id"])
            out.append({
                "id": e["id"], "name": e["name"], "email": e["email"],
                "is_admin": bool(e["is_admin"]), "active": bool(e["active"]),
                "created_at": e["created_at"], "clocked_in": bool(open_entry),
                "since": open_entry["clock_in"] if open_entry else None,
            })
        return self._json({"employees": out})

    def api_admin_create_employee(self, body):
        if not self._require_admin():
            return
        name = (body.get("name") or "").strip()
        email = (body.get("email") or "").strip()
        pin = (body.get("pin") or "").strip()
        is_admin = bool(body.get("is_admin"))
        if not name or not email or not pin:
            return self._error("Name, email and PIN are required.")
        if len(pin) < 4:
            return self._error("PIN must be at least 4 digits.")
        if db.get_employee_by_email(email):
            return self._error("An employee with that email already exists.")
        emp_id = db.create_employee(name, email, pin, is_admin)
        return self._json({"ok": True, "id": emp_id})

    def api_admin_update_employee(self, emp_id, body):
        if not self._require_admin():
            return
        if not db.get_employee(emp_id):
            return self._error("Employee not found.", 404)
        db.update_employee(
            emp_id,
            name=body.get("name"),
            email=body.get("email"),
            pin=body.get("pin"),
            is_admin=body.get("is_admin"),
            active=body.get("active"),
        )
        return self._json({"ok": True})

    def api_admin_entries(self, qs):
        if not self._require_admin():
            return
        start = (qs.get("start", [""])[0]) or None
        end = (qs.get("end", [""])[0]) or None
        emp_id = qs.get("employee_id", [""])[0]
        emp_id = int(emp_id) if emp_id.isdigit() else None
        entries = db.all_entries(start=start, end=end, emp_id=emp_id)
        return self._json({"entries": entries})

    def api_admin_summary(self, qs):
        if not self._require_admin():
            return
        start = (qs.get("start", [""])[0]) or None
        end = (qs.get("end", [""])[0]) or None
        entries = db.all_entries(start=start, end=end)
        totals = {}
        for e in entries:
            key = e["employee_id"]
            if key not in totals:
                totals[key] = {
                    "employee_id": key, "name": e["employee_name"],
                    "email": e["employee_email"], "seconds": 0, "sessions": 0,
                    "open": 0,
                }
            totals[key]["sessions"] += 1
            if e["clock_out"]:
                totals[key]["seconds"] += _duration_seconds(e["clock_in"], e["clock_out"])
            else:
                totals[key]["open"] += 1
        return self._json({"summary": sorted(totals.values(), key=lambda x: x["name"].lower())})

    def api_admin_export(self, qs):
        if not self._require_admin():
            return
        start = (qs.get("start", [""])[0]) or None
        end = (qs.get("end", [""])[0]) or None
        emp_id = qs.get("employee_id", [""])[0]
        emp_id = int(emp_id) if emp_id.isdigit() else None
        entries = db.all_entries(start=start, end=end, emp_id=emp_id)
        lines = ["Name,Email,Clock In,Clock Out,Hours,Note"]
        for e in entries:
            hours = ""
            if e["clock_out"]:
                hours = "%.2f" % (_duration_seconds(e["clock_in"], e["clock_out"]) / 3600.0)
            note = (e.get("note") or "").replace('"', '""')
            lines.append('"%s","%s","%s","%s","%s","%s"' % (
                e["employee_name"], e["employee_email"], e["clock_in"],
                e["clock_out"] or "", hours, note))
        body = ("\r\n".join(lines)).encode("utf-8")
        self.send_response(200)
        self.send_header("Content-Type", "text/csv; charset=utf-8")
        self.send_header("Content-Disposition", "attachment; filename=timekeeping-export.csv")
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        self.wfile.write(body)


def _duration_seconds(start_iso, end_iso):
    from datetime import datetime
    try:
        a = datetime.fromisoformat(start_iso)
        b = datetime.fromisoformat(end_iso)
        return max(0, int((b - a).total_seconds()))
    except (ValueError, TypeError):
        return 0


def main():
    db.init_db()
    created = db.seed_default_admin()
    print("=" * 60)
    print("  Humiley TimeKeeping")
    print("=" * 60)
    if created:
        print("  Default admin account created:")
        print("    Email: %s" % created["email"])
        print("    PIN:   %s" % created["pin"])
        print("  >> Log in at /admin and change this PIN.")
        print("-" * 60)
    print("  Employee kiosk:  http://localhost:%d/" % PORT)
    print("  Admin dashboard: http://localhost:%d/admin" % PORT)
    print("=" * 60)
    server = ThreadingHTTPServer((HOST, PORT), Handler)
    try:
        server.serve_forever()
    except KeyboardInterrupt:
        print("\nShutting down.")
        server.shutdown()


if __name__ == "__main__":
    main()
