"""
Humiley Timekeeping & Leave Management — standalone web app server.

Dependency-free (Python standard library):
  - http.server for HTTP + REST API
  - sqlite3 for storage (see db.py)
  - urllib for Microsoft 365 / Graph token verification (live mode)

Run:   python3 app.py        then open http://localhost:8000

Microsoft 365 login is used when TK_M365_CLIENT_ID / TK_M365_TENANT_ID are set;
otherwise the app runs in DEMO mode (pick Manager / Staff, no Azure needed).
"""

import json
import os
import re
import secrets
import time
import urllib.request
import urllib.error
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from urllib.parse import urlparse, parse_qs

import db

HOST = os.environ.get("TK_HOST", "0.0.0.0")
PORT = int(os.environ.get("TK_PORT") or os.environ.get("PORT") or "8000")
BASE_DIR = os.path.dirname(os.path.abspath(__file__))
STATIC_DIR = os.path.join(BASE_DIR, "static")
TEMPLATE_DIR = os.path.join(BASE_DIR, "templates")

# Microsoft 365 config (empty -> demo mode)
M365 = {
    "clientId": os.environ.get("TK_M365_CLIENT_ID", ""),
    "tenantId": os.environ.get("TK_M365_TENANT_ID", ""),
    "mapsKey": os.environ.get("TK_MAPS_KEY", ""),
}
DEMO_MODE = not (M365["clientId"] and M365["tenantId"])

# In-memory sessions: token -> {emp_id, role, expires}
SESSIONS = {}
SESSION_TTL = 8 * 60 * 60

CONTENT_TYPES = {
    ".html": "text/html; charset=utf-8", ".css": "text/css; charset=utf-8",
    ".js": "application/javascript; charset=utf-8", ".png": "image/png",
    ".jpg": "image/jpeg", ".svg": "image/svg+xml", ".ico": "image/x-icon",
}


def new_session(emp_id, role):
    token = secrets.token_urlsafe(32)
    SESSIONS[token] = {"emp_id": emp_id, "role": role, "expires": time.time() + SESSION_TTL}
    return token


def session_user(token):
    s = SESSIONS.get(token or "")
    if not s or s["expires"] < time.time():
        SESSIONS.pop(token, None)
        return None
    emp = db.get_employee(s["emp_id"]) if s["emp_id"] else None
    if emp:
        emp["role"] = s["role"]
    return emp


def graph_me(access_token):
    """Verify a Microsoft 365 access token by calling Graph /me. Returns the
    user's email (mail or userPrincipalName) or None."""
    req = urllib.request.Request(
        "https://graph.microsoft.com/v1.0/me",
        headers={"Authorization": "Bearer " + access_token})
    try:
        with urllib.request.urlopen(req, timeout=10) as resp:
            data = json.loads(resp.read().decode("utf-8"))
            return (data.get("mail") or data.get("userPrincipalName") or "").lower()
    except (urllib.error.URLError, ValueError, TimeoutError):
        return None


class Handler(BaseHTTPRequestHandler):
    server_version = "HumileyTimekeeping/2.0"

    # -- io helpers ---------------------------------------------------------
    def _json(self, obj, status=200):
        body = json.dumps(obj).encode("utf-8")
        self.send_response(status)
        self.send_header("Content-Type", "application/json; charset=utf-8")
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        self.wfile.write(body)

    def _err(self, msg, status=400):
        self._json({"error": msg}, status)

    def _body(self):
        n = int(self.headers.get("Content-Length", 0))
        if not n:
            return {}
        try:
            return json.loads(self.rfile.read(n).decode("utf-8"))
        except (ValueError, UnicodeDecodeError):
            return {}

    def _user(self):
        auth = self.headers.get("Authorization", "")
        token = auth[7:].strip() if auth.startswith("Bearer ") else ""
        return session_user(token)

    def _serve_file(self, path):
        if not os.path.isfile(path):
            return self._err("Not found.", 404)
        ext = os.path.splitext(path)[1]
        with open(path, "rb") as f:
            body = f.read()
        self.send_response(200)
        self.send_header("Content-Type", CONTENT_TYPES.get(ext, "application/octet-stream"))
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        self.wfile.write(body)

    def log_message(self, fmt, *args):
        print("%s - %s" % (self.address_string(), fmt % args))

    # -- routing ------------------------------------------------------------
    def do_GET(self):
        p = urlparse(self.path)
        path, qs = p.path, parse_qs(p.query)

        if path in ("/", "/index.html"):
            return self._serve_file(os.path.join(TEMPLATE_DIR, "index.html"))
        if path.startswith("/static/"):
            safe = os.path.normpath(os.path.join(STATIC_DIR, path[len("/static/"):]))
            if not safe.startswith(STATIC_DIR):
                return self._err("Forbidden.", 403)
            return self._serve_file(safe)

        if path == "/approve":
            return self._approve_via_link(qs)
        if path == "/api/config":
            return self._json({"demo": DEMO_MODE, "clientId": M365["clientId"],
                               "tenantId": M365["tenantId"], "mapsKey": M365["mapsKey"]})
        if path == "/api/me":
            u = self._user()
            return self._json(u) if u else self._err("Not authenticated.", 401)
        if path == "/api/employees":
            return self._guard(lambda u: self._json({"employees": self._emp_list_for(u)}))
        if path == "/api/attendance":
            return self._guard(lambda u: self._attendance_list(u, qs))
        if path == "/api/leave":
            return self._guard(lambda u: self._leave_list(u, qs))
        if path == "/api/zones":
            return self._guard(lambda u: self._json({"zones": db.list_zones()}))
        if path == "/api/portal":
            return self._guard(lambda u: self._portal_get(u))
        if path.startswith("/api/coll/"):
            name = path[len("/api/coll/"):].split("/")[0]
            return self._guard(lambda u: self._coll_list(u, name))
        return self._err("Not found.", 404)

    def do_POST(self):
        path = urlparse(self.path).path
        body = self._body()
        if path == "/api/auth/demo":
            return self._auth_demo(body)
        if path == "/api/auth/m365":
            return self._auth_m365(body)
        if path == "/api/attendance/checkin":
            return self._guard(lambda u: self._checkin(u, body))
        if path == "/api/attendance/checkout":
            return self._guard(lambda u: self._checkout(u, body))
        if path == "/api/leave":
            return self._guard(lambda u: self._leave_create(u, body))
        if path == "/api/employees":
            return self._guard(lambda u: self._emp_create(u, body), manager=True)
        if path == "/api/zones":
            return self._guard(lambda u: self._json({"id": db.create_zone(body)}), manager=True)
        if path.startswith("/api/coll/"):
            name = path[len("/api/coll/"):].split("/")[0]
            return self._guard(lambda u: self._coll_add(u, name, body), manager=(name not in self.STAFF_WRITE))
        return self._err("Not found.", 404)

    def do_PATCH(self):
        path = urlparse(self.path).path
        body = self._body()
        if path == "/api/me":
            return self._guard(lambda u: self._me_update(u, body))
        if path == "/api/portal":
            return self._guard(lambda u: self._portal_update(u, body), manager=True)
        if path.startswith("/api/coll/"):
            seg = path[len("/api/coll/"):].split("/")
            nm = seg[0]
            return self._guard(lambda u: self._coll_update(u, nm, seg[1] if len(seg) > 1 else "", body), manager=(nm not in ("padr", "enrollments", "onboarding")))
        if path.startswith("/api/employees/"):
            eid = path.rsplit("/", 1)[1]
            return self._guard(lambda u: self._emp_update(u, eid, body), manager=True)
        if path.startswith("/api/leave/"):
            lid = path.rsplit("/", 1)[1]
            return self._guard(lambda u: self._leave_status(u, lid, body))
        if path.startswith("/api/zones/"):
            zid = path.rsplit("/", 1)[1]
            return self._guard(lambda u: self._zone_update(zid, body), manager=True)
        return self._err("Not found.", 404)

    def do_DELETE(self):
        path = urlparse(self.path).path
        if path.startswith("/api/coll/"):
            seg = path[len("/api/coll/"):].split("/")
            return self._guard(lambda u: self._coll_delete(u, seg[0], seg[1] if len(seg) > 1 else ""), manager=True)
        if path.startswith("/api/employees/"):
            eid = path.rsplit("/", 1)[1]
            return self._guard(lambda u: (db.delete_employee(eid), self._json({"ok": True}))[1], manager=True)
        if path.startswith("/api/zones/"):
            zid = path.rsplit("/", 1)[1]
            return self._guard(lambda u: (db.delete_zone(int(zid)), self._json({"ok": True}))[1], manager=True)
        return self._err("Not found.", 404)

    # -- guard --------------------------------------------------------------
    def _guard(self, fn, manager=False):
        u = self._user()
        if not u:
            return self._err("Not authenticated.", 401)
        if manager and u.get("role") != "manager":
            return self._err("Manager access required.", 403)
        return fn(u)

    # -- auth ---------------------------------------------------------------
    def _auth_demo(self, body):
        if not DEMO_MODE:
            return self._err("Demo login disabled (Microsoft 365 is configured).", 403)
        role = body.get("role", "manager")
        # Demo identities: pick a real admin for manager, a real staff member otherwise
        emps = db.list_employees()
        emp = None
        if role == "manager":
            emp = next((e for e in emps if e.get("role") == "manager"), None)
        else:
            emp = next((e for e in emps if e.get("role") != "manager"), None)
        emp = emp or (emps[0] if emps else None)
        if not emp:
            return self._err("No employees in the system yet.", 400)
        token = new_session(emp["id"], emp.get("role", role))
        user = dict(emp, role=emp.get("role", role))
        if role == "manager":
            user["level"] = "admin"   # demo Manager / HR Admin = full admin (view all)
        return self._json({"token": token, "user": user})

    def _auth_m365(self, body):
        token_in = body.get("accessToken", "")
        if not token_in:
            return self._err("Missing access token.", 400)
        email = graph_me(token_in)
        if not email:
            return self._err("Could not verify Microsoft 365 account.", 401)
        emp = db.get_employee_by_email(email)
        if not emp:
            return self._err("No employee record for %s. Ask an admin to add you." % email, 403)
        token = new_session(emp["id"], emp.get("role", "staff"))
        return self._json({"token": token, "user": dict(emp, role=emp.get("role", "staff"))})

    # -- attendance ---------------------------------------------------------
    def _attendance_list(self, u, qs):
        emp_id = qs.get("emp_id", [None])[0]
        if u.get("role") != "manager":
            emp_id = u["id"]  # staff see only their own
        return self._json({"attendance": db.list_attendance(
            emp_id=emp_id, start=qs.get("start", [None])[0], end=qs.get("end", [None])[0])})

    def _checkin(self, u, body):
        emp_id = u["id"]
        date = body.get("date"); t = body.get("time")
        if not date or not t:
            return self._err("date and time required.")
        if db.open_attendance(emp_id, date):
            return self._err("Already checked in today.")
        status = "late" if t > "08:15" else "on-time"
        rid = db.clock_in(emp_id, date, t, loc=body.get("loc"),
                          lat=body.get("lat"), lon=body.get("lon"), status=status)
        return self._json({"ok": True, "id": rid, "status": status})

    def _checkout(self, u, body):
        date = body.get("date"); t = body.get("time")
        rec = db.open_attendance(u["id"], date)
        if not rec:
            return self._err("No open check-in to close.")
        hrs = db.clock_out(rec["id"], t)
        return self._json({"ok": True, "hrs": hrs})

    # -- leave --------------------------------------------------------------
    def _leave_list(self, u, qs):
        status = qs.get("status", [None])[0]
        # Everyone sees their own leave; managers also see their DIRECT reports'.
        ids = [u["id"]]
        reports = db.list_reports(u.get("email"))
        ids += [r["id"] for r in reports]
        ids = list(dict.fromkeys(ids))  # dedupe, preserve order
        return self._json({"leave": db.list_leave(emp_ids=ids, status=status)})

    def _leave_create(self, u, body):
        data = dict(body, emp_id=u["id"], status="pending")
        rid, token = db.create_leave(data)
        # surface the direct manager + approval token so the client can email them
        mgr = db.get_employee_by_email(u.get("managerEmail")) if u.get("managerEmail") else None
        return self._json({
            "ok": True, "id": rid, "token": token,
            "requester": u.get("name"),
            "managerEmail": u.get("managerEmail") or "",
            "managerName": mgr["name"] if mgr else "",
        })

    def _leave_status(self, u, lid, body):
        status = body.get("status")
        if status not in ("approved", "rejected", "pending"):
            return self._err("Invalid status.")
        lv = db.get_leave(int(lid))
        if not lv:
            return self._err("Leave request not found.", 404)
        requester = db.get_employee(lv["emp_id"])
        if not requester:
            return self._err("Requester not found.", 404)
        # Only the requester's DIRECT manager may approve/reject.
        mgr = (requester.get("managerEmail") or "").strip().lower()
        if mgr != (u.get("email") or "").strip().lower():
            return self._err("Only %s's direct manager can approve this request." % requester["name"], 403)
        db.set_leave_status(int(lid), status, body.get("note"))
        return self._json({"ok": True})

    def _html(self, title, message, color):
        icon = "✓" if color == "#00B060" else ("✕" if color == "#C00000" else "ℹ")
        css = ("body{font-family:'Segoe UI',system-ui,Arial,sans-serif;"
               "background:linear-gradient(180deg,#f7f9fc,#eef1f6);display:flex;min-height:100vh;"
               "align-items:center;justify-content:center;margin:0}"
               ".card{background:#fff;border-radius:20px;box-shadow:0 18px 40px rgba(32,80,144,.12);"
               "padding:40px 44px;max-width:440px;text-align:center}"
               ".ic{display:inline-block;width:64px;height:64px;border-radius:50%;line-height:64px;"
               "font-size:30px;color:#fff;margin-bottom:14px;background:" + color + "}"
               "h1{color:#205090;font-size:20px;margin:6px 0}"
               "p{color:#5C6470;font-size:14px;line-height:1.6}")
        html = ('<!DOCTYPE html><html><head><meta charset="utf-8">'
                '<meta name="viewport" content="width=device-width,initial-scale=1">'
                '<title>Humiley Timekeeping</title><style>' + css + '</style></head>'
                '<body><div class="card"><div class="ic">' + icon + '</div>'
                '<h1>' + title + '</h1><p>' + message + '</p></div></body></html>')
        body = html.encode("utf-8")
        self.send_response(200)
        self.send_header("Content-Type", "text/html; charset=utf-8")
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        self.wfile.write(body)

    def _approve_via_link(self, qs):
        token = qs.get("t", [""])[0] or qs.get("token", [""])[0]
        action = (qs.get("action", ["approve"])[0]).lower()
        lv = db.get_leave_by_token(token)
        if not lv:
            return self._html("Invalid or expired link", "This approval link is not valid. Please use the app to review the request.", "#C00000")
        requester = db.get_employee(lv["emp_id"])
        rname = requester["name"] if requester else "the employee"
        if (lv.get("status") or "").lower() != "pending":
            return self._html("Already " + lv["status"], "This leave request for %s was already <b>%s</b>." % (rname, lv["status"]), "#205090")
        new_status = "rejected" if action in ("reject", "decline", "deny") else "approved"
        db.set_leave_status(lv["id"], new_status)
        verb = "approved ✅" if new_status == "approved" else "rejected"
        return self._html("Leave " + new_status,
                          "%s's %s (%s → %s) has been <b>%s</b>." % (rname, lv.get("type", "leave"),
                          lv.get("startDate", ""), lv.get("endDate", ""), verb),
                          "#00B060" if new_status == "approved" else "#C00000")

    # -- employees ----------------------------------------------------------
    def _emp_create(self, u, body):
        if not body.get("name") or not body.get("email"):
            return self._err("name and email required.")
        if db.get_employee_by_email(body["email"]):
            return self._err("An employee with that email already exists.")
        body = dict(body or {})
        # Only admins may set access level / role on create (prevents privilege escalation).
        if ("level" in body or "role" in body) and self._caller_level(u) != "admin":
            body.pop("level", None)
            body.pop("role", None)
        return self._json({"ok": True, "id": db.create_employee(body)})

    def _emp_list_for(self, u):
        """Staff see a directory-safe roster (own record full); managers+ see all fields."""
        rows = db.list_employees()
        if self._caller_level(u) != "staff":
            return rows
        me = u.get("id")
        return [e if e.get("id") == me else {k: v for k, v in e.items() if k not in self.EMP_SENSITIVE} for e in rows]

    ADMIN_EMAILS = {"tony.nguyen@humiley.com", "giang.nguyen@humiley.com", "huy.nguyen@humiley.com"}

    def _caller_level(self, u):
        lv = u.get("level")
        if lv in ("staff", "manager", "management", "admin"):
            return lv
        if (u.get("email") or "").lower() in self.ADMIN_EMAILS:
            return "admin"
        if u.get("role") == "manager":
            return "management" if re.search(r"director|managing|chief|head|coo|ceo|cfo", u.get("title") or "", re.I) else "manager"
        return "staff"

    def _emp_update(self, u, eid, body):
        if not db.get_employee(eid):
            return self._err("Employee not found.", 404)
        body = dict(body or {})
        # Only admins may change access level or role (prevents privilege escalation).
        if ("level" in body or "role" in body) and self._caller_level(u) != "admin":
            body.pop("level", None)
            body.pop("role", None)
        if body:
            db.update_employee(eid, body)
        return self._json({"ok": True})

    # Fields an employee may update on their OWN profile (self-service).
    SELF_FIELDS = {"phone", "address", "emergency", "dob", "gender",
                   "familyStatus", "education", "englishCert", "personalId", "photo"}

    def _me_update(self, u, body):
        eid = u.get("id")
        if not eid or not db.get_employee(eid):
            return self._err("Profile not found.", 404)
        data = {k: v for k, v in body.items() if k in self.SELF_FIELDS}
        if data:
            db.update_employee(eid, data)
        return self._json({"ok": True, "updated": list(data.keys())})

    def _zone_update(self, zid, body):
        db.update_zone(int(zid), body)
        return self._json({"ok": True})

    # -- company portal content (announcements / holidays / learning / resources) --
    PORTAL_KEYS = ("announcements", "holidays", "learning", "resources")

    def _portal_get(self, u):
        out = {k: db.get_setting("portal_" + k) for k in self.PORTAL_KEYS}
        out["teamsWebhook"] = db.get_setting("portal_teamsWebhook")
        return self._json(out)

    def _portal_update(self, u, body):
        for k in self.PORTAL_KEYS:
            if isinstance(body.get(k), list):
                db.set_setting("portal_" + k, body[k])
        if isinstance(body.get("teamsWebhook"), str):
            db.set_setting("portal_teamsWebhook", body["teamsWebhook"])
        return self._json({"ok": True})

    # -- generic HR collections (recruitment, onboarding, performance, talent, training) --
    COLLECTIONS = {"jobs", "candidates", "onboarding", "reviews", "goals", "courses", "talent", "payruns", "padr", "competency", "pip", "claims", "acks", "audit", "travel", "exits", "benefits", "learningpaths", "enrollments", "payadjust", "devices", "handovers"}
    # Collections any authenticated user (incl. staff) may create for self-service.
    STAFF_WRITE = {"claims", "travel", "acks", "audit", "padr", "enrollments"}
    PAYROLL_ADMIN = {"payruns", "payadjust"}   # payroll writes are Administrator-only
    EMP_SENSITIVE = {"salary", "grade", "bank", "taxId", "dependents", "personalId", "address", "emergency", "annualUsed", "annualTotal", "sickUsed", "sickTotal", "compoff"}

    def _coll_list(self, u, name):
        if name not in self.COLLECTIONS:
            return self._err("Unknown collection.", 404)
        return self._json({"items": db.list_collection(name)})

    def _coll_add(self, u, name, body):
        if name not in self.COLLECTIONS:
            return self._err("Unknown collection.", 404)
        if name in self.PAYROLL_ADMIN and self._caller_level(u) != "admin":
            return self._err("Payroll changes require Administrator level.", 403)
        item = dict(body or {})
        # For staff self-service records, stamp identity from the session (no impersonation).
        if name in ("claims", "travel", "acks"):
            item["empId"] = u.get("id")
            item["name"] = u.get("name")
        # Staff-created PADR cycle: stamp identity, force self-service shape (no mgr scores/rating).
        if name == "padr" and u.get("role") != "manager":
            item["empId"] = u.get("id")
            item["name"] = u.get("name")
        # Staff self-enrolment: stamp identity (managers enrol others, so trust their body).
        if name == "enrollments" and u.get("role") != "manager":
            item["empId"] = u.get("id")
            item["name"] = u.get("name")
            item["status"] = item.get("status") or "Goal-setting"
            item["rating"] = 0
            for g in (item.get("goals") or []):
                if isinstance(g, dict):
                    g["source"] = "self"
                    g["mgrScore"] = 0
                    g.setdefault("addedBy", u.get("email") or u.get("id"))
        if name == "audit":
            item["actor"] = u.get("name") or "System"
            item["actorId"] = u.get("id") or ""
        return self._json({"ok": True, "item": db.put_collection_item(name, item)})

    def _coll_update(self, u, name, iid, body):
        if name not in self.COLLECTIONS or not iid:
            return self._err("Unknown item.", 404)
        if name in self.PAYROLL_ADMIN and self._caller_level(u) != "admin":
            return self._err("Payroll changes require Administrator level.", 403)
        # Non-managers reach this only for 'padr' and 'enrollments' (own records).
        if u.get("role") != "manager":
            if name == "enrollments":
                existing = next((x for x in db.list_collection("enrollments") if x.get("id") == iid), None)
                if not existing or existing.get("empId") != u.get("id"):
                    return self._err("Not allowed.", 403)
                # staff may only update their own progress / status / rating / feedback / completion date
                for k in ("progress", "status", "rating", "feedback", "completedOn"):
                    if k in (body or {}):
                        existing[k] = body[k]
                existing["id"] = iid
                return self._json({"ok": True, "item": db.put_collection_item("enrollments", existing)})
            if name == "onboarding":
                existing = next((x for x in db.list_collection("onboarding") if x.get("id") == iid), None)
                # Owner check: prefer empId (unique); only fall back to name when the record has no empId
                _own = (existing.get("empId") == u.get("id")) if (existing and existing.get("empId")) else (existing and existing.get("name") == u.get("name"))
                if not existing or not _own:
                    return self._err("Not allowed.", 403)
                # staff may only mark their OWN onboarding tasks done (irreversible); everything else preserved
                btasks = (body or {}).get("tasks")
                if isinstance(btasks, list):
                    ex_tasks = existing.get("tasks") or []
                    for i, bt in enumerate(btasks):
                        if i < len(ex_tasks) and isinstance(bt, dict) and bt.get("done"):
                            ex_tasks[i]["done"] = True
                    existing["tasks"] = ex_tasks
                existing["id"] = iid
                return self._json({"ok": True, "item": db.put_collection_item("onboarding", existing)})
            if name != "padr":
                return self._err("Manager access required.", 403)
            existing = next((x for x in db.list_collection("padr") if x.get("id") == iid), None)
            if not existing or existing.get("empId") != u.get("id"):
                return self._err("Not allowed.", 403)
            # Merge: staff may edit self-goals fully, and only selfScore/progress/status/note on
            # manager-assigned goals. mgrScore, rating and assigned-goal definitions are preserved.
            bgoals = (body or {}).get("goals") or []
            ex_by_id = {g.get("id"): g for g in (existing.get("goals") or []) if g.get("id")}
            merged, seen = [], set()
            for bg in bgoals:
                if not isinstance(bg, dict):
                    continue
                gid = bg.get("id")
                ex = ex_by_id.get(gid)
                if ex and ex.get("source") != "self":
                    for k in ("selfScore", "progress", "status", "note"):
                        if k in bg:
                            ex[k] = bg[k]
                    merged.append(ex)
                    seen.add(gid)
                else:
                    g = dict(bg)
                    g["source"] = "self"
                    g["mgrScore"] = (ex or {}).get("mgrScore", 0)
                    g.setdefault("addedBy", u.get("email") or u.get("id"))
                    merged.append(g)
                    if gid:
                        seen.add(gid)
            # never let staff drop manager-assigned goals by omitting them
            for ex in (existing.get("goals") or []):
                if ex.get("source") != "self" and ex.get("id") not in seen:
                    merged.append(ex)
            existing["goals"] = merged
            st = (body or {}).get("status")
            if st in ("Goal-setting", "Self-assessment", "Mid-year"):
                existing["status"] = st
            existing["id"] = iid
            return self._json({"ok": True, "item": db.put_collection_item("padr", existing)})
        item = dict(body or {})
        item["id"] = iid
        # Preserve server-trusted ownership on staff-owned records (a manager edit/approve
        # must not be able to rewrite who a claim/travel/exit belongs to).
        if name in ("claims", "travel", "acks"):
            existing = next((x for x in db.list_collection(name) if x.get("id") == iid), None)
            if existing:
                item["empId"] = existing.get("empId", item.get("empId"))
                if existing.get("name"):
                    item["name"] = existing.get("name")
        return self._json({"ok": True, "item": db.put_collection_item(name, item)})

    def _coll_delete(self, u, name, iid):
        if name not in self.COLLECTIONS or not iid:
            return self._err("Unknown item.", 404)
        if name in self.PAYROLL_ADMIN and self._caller_level(u) != "admin":
            return self._err("Payroll changes require Administrator level.", 403)
        db.delete_collection_item(name, iid)
        return self._json({"ok": True})


def main():
    db.init_db()
    seeded = db.seed()
    db.seed_hr()
    att_added = db.generate_attendance()
    if att_added:
        print("  Attendance generated: %d rows." % att_added)
    print("=" * 62)
    print("  Humiley Timekeeping & Leave Management")
    print("=" * 62)
    print("  Mode: %s" % ("DEMO (pick Manager/Staff)" if DEMO_MODE else "Microsoft 365 (live)"))
    if seeded:
        print("  Database seeded with %d employees." % len(db.list_employees()))
    print("  Open: http://localhost:%d/" % PORT)
    print("=" * 62)
    ThreadingHTTPServer((HOST, PORT), Handler).serve_forever()


if __name__ == "__main__":
    main()
