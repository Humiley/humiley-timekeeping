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

import gzip
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
    # Public SPA identifiers (no client secret) — baked in so M365 stays live across restarts.
    "clientId": os.environ.get("TK_M365_CLIENT_ID", "8810a31e-788a-4f96-881c-c522fdc5b338"),
    "tenantId": os.environ.get("TK_M365_TENANT_ID", "2a586c8f-fc2f-4c59-be46-938adfa3579c"),
    "mapsKey": os.environ.get("TK_MAPS_KEY", ""),
}
DEMO_MODE = not (M365["clientId"] and M365["tenantId"])

# In-memory sessions: token -> {emp_id, role, expires}. Long-lived + sliding so a signed-in user
# never sees the login screen again (until they sign out): the token is stored in localStorage on
# the client and its expiry is pushed forward on every use.
SESSIONS = {}
SESSION_TTL = 30 * 24 * 60 * 60   # 30 days

CONTENT_TYPES = {
    ".html": "text/html; charset=utf-8", ".css": "text/css; charset=utf-8",
    ".js": "application/javascript; charset=utf-8", ".png": "image/png",
    ".jpg": "image/jpeg", ".svg": "image/svg+xml", ".ico": "image/x-icon",
    ".json": "application/json; charset=utf-8", ".webmanifest": "application/manifest+json; charset=utf-8",
}


def _persist_sessions():
    try:
        # Prune expired tokens on every write so the blob can never grow without bound.
        now = time.time()
        for tok in [t for t, s in SESSIONS.items() if not isinstance(s, dict) or s.get("expires", 0) <= now]:
            SESSIONS.pop(tok, None)
        db.set_setting("_sessions", json.dumps(SESSIONS))
    except Exception as e:
        print(f"[sessions] persist failed: {e}", flush=True)


def _load_sessions():
    try:
        data = json.loads(db.get_setting("_sessions") or "{}")
        now = time.time()
        for tok, ses in (data or {}).items():
            if isinstance(ses, dict) and ses.get("expires", 0) > now:
                SESSIONS[tok] = ses
        print(f"[sessions] restored {len(SESSIONS)} active session(s)", flush=True)
    except Exception as e:
        # Never fail the boot over this — but say so loudly: a silent empty restore means every
        # user is bounced to sign-in (the "signed in but must re-login in the morning" symptom).
        print(f"[sessions] RESTORE FAILED — all users must re-authenticate: {e}", flush=True)


def new_session(emp_id, role):
    token = secrets.token_urlsafe(32)
    SESSIONS[token] = {"emp_id": emp_id, "role": role, "expires": time.time() + SESSION_TTL}
    _persist_sessions()
    return token


def session_user(token):
    s = SESSIONS.get(token or "")
    now = time.time()
    if not s or s["expires"] < now:
        SESSIONS.pop(token, None)
        return None
    # Sliding expiration: extend on use so an active user's session never lapses. Persist only when
    # it moves by more than an hour to avoid a DB write on every request.
    new_exp = now + SESSION_TTL
    if new_exp - s.get("expires", 0) > 3600:
        s["expires"] = new_exp
        _persist_sessions()
    emp = db.get_employee(s["emp_id"]) if s["emp_id"] else None
    if emp:
        emp["role"] = s["role"]
    return emp


def _app_version():
    """Version marker for auto-update: the mtime of the served HTML, which changes on every
    deploy (git pull rewrites the file). The client reloads the PWA when this changes."""
    try:
        return str(int(os.path.getmtime(os.path.join(TEMPLATE_DIR, "index.html"))))
    except OSError:
        return "0"


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


# ── Web Push (OS notifications for PWA + web) ──────────────────────────────────
# Free, no external account: self-signed VAPID keys (generated once, kept in the DB
# settings table on the data volume) + the standard Web Push protocol via pywebpush.
# Degrades gracefully: if pywebpush/cryptography aren't installed the app still runs
# and simply skips push (email notifications still go out).
try:
    from pywebpush import webpush, WebPushException
    from cryptography.hazmat.primitives.asymmetric import ec
    from cryptography.hazmat.primitives import serialization
    _PUSH_OK = True
except Exception:                       # pragma: no cover - optional dependency
    _PUSH_OK = False

import base64

VAPID_SUBJECT = os.environ.get("TK_VAPID_SUBJECT", "mailto:portal@humiley.com")
_VAPID = {"priv": None, "pub": None}


def _b64url(raw):
    return base64.urlsafe_b64encode(raw).rstrip(b"=").decode("ascii")


def _ensure_vapid():
    """Return {'priv': <raw 32-byte EC scalar, base64url>, 'pub': <applicationServerKey base64url>}.
    Prefers env secrets TK_VAPID_PRIVATE / TK_VAPID_PUBLIC (kept OUT of the DB, like the e-sign
    pepper — set both to harden against a DB-file leak); otherwise generates a keypair once and
    persists it in the DB settings table so push works out-of-the-box."""
    if _VAPID["pub"]:
        return _VAPID
    if not _PUSH_OK:
        return _VAPID
    env_priv = os.environ.get("TK_VAPID_PRIVATE", "").strip()
    env_pub = os.environ.get("TK_VAPID_PUBLIC", "").strip()
    if env_priv and env_pub:
        _VAPID.update({"priv": env_priv, "pub": env_pub})
        return _VAPID
    saved = None
    try:
        saved = db.get_setting("_vapid")
    except Exception:
        saved = None
    if isinstance(saved, dict) and saved.get("priv") and saved.get("pub"):
        _VAPID.update(saved)
        return _VAPID
    try:
        priv = ec.generate_private_key(ec.SECP256R1())
        # Private key as the raw 32-byte scalar, base64url — the format pywebpush accepts
        # directly and the conventional Web Push "private key" encoding.
        raw = priv.private_numbers().private_value.to_bytes(32, "big")
        point = priv.public_key().public_bytes(
            serialization.Encoding.X962,
            serialization.PublicFormat.UncompressedPoint)   # 65 bytes: 0x04 || X || Y (applicationServerKey)
        _VAPID.update({"priv": _b64url(raw), "pub": _b64url(point)})
        db.set_setting("_vapid", _VAPID)
    except Exception as e:               # pragma: no cover
        print("VAPID keygen failed:", e)
    return _VAPID


def _web_push(endpoint, sub, payload):
    """Send one Web Push message; drop the subscription if the browser reports it gone."""
    if not _PUSH_OK:
        return False
    v = _ensure_vapid()
    if not v.get("priv"):
        return False
    try:
        webpush(subscription_info=sub, data=json.dumps(payload),
                vapid_private_key=v["priv"],
                vapid_claims={"sub": VAPID_SUBJECT}, ttl=86400, timeout=10)
        return True
    except WebPushException as e:        # pragma: no cover - network dependent
        code = getattr(getattr(e, "response", None), "status_code", None)
        if code in (404, 410):           # subscription expired / unsubscribed
            try:
                db.push_sub_remove(endpoint)
            except Exception:
                pass
        return False
    except Exception:
        return False


class Handler(BaseHTTPRequestHandler):
    server_version = "HumileyTimekeeping/2.0"
    MAX_BODY = 30 * 1024 * 1024   # reject request bodies larger than 30 MB (memory-safety)

    # -- io helpers ---------------------------------------------------------
    # gzip text responses: the single-file app HTML is ~1.6 MB raw — uncompressed it took
    # seconds per open on 4G (the "app feels flat/slow on mobile" complaint). ~5x smaller gzipped.
    GZIP_TYPES = ("text/", "application/json", "application/javascript", "application/manifest+json", "image/svg+xml")

    def _accepts_gzip(self):
        return "gzip" in (self.headers.get("Accept-Encoding") or "")

    def _send(self, body, ctype, status=200, cache=None):
        gz = (
            len(body) > 1024
            and self._accepts_gzip()
            and any(ctype.startswith(t) for t in self.GZIP_TYPES)
        )
        if gz:
            body = gzip.compress(body, 6)
        self.send_response(status)
        self.send_header("Content-Type", ctype)
        if gz:
            self.send_header("Content-Encoding", "gzip")
        self.send_header("Vary", "Accept-Encoding")
        if cache:
            self.send_header("Cache-Control", cache)
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        self.wfile.write(body)

    def _json(self, obj, status=200):
        self._send(json.dumps(obj).encode("utf-8"), "application/json; charset=utf-8", status)

    def _err(self, msg, status=400):
        self._json({"error": msg}, status)

    def _body(self):
        n = int(self.headers.get("Content-Length", 0))
        if not n:
            return {}
        if n > self.MAX_BODY:
            return {}   # oversized payload — drop it (a TLS reverse proxy returns a proper 413)
        try:
            return json.loads(self.rfile.read(n).decode("utf-8"))
        except (ValueError, UnicodeDecodeError):
            return {}

    def _user(self):
        auth = self.headers.get("Authorization", "")
        token = auth[7:].strip() if auth.startswith("Bearer ") else ""
        return session_user(token)

    # Pre-gzipped file cache keyed by (path, mtime) — the index.html is served on every
    # navigation, so compress it once per deploy instead of per request.
    _GZ_CACHE = {}

    def _serve_file(self, path):
        if not os.path.isfile(path):
            return self._err("Not found.", 404)
        ext = os.path.splitext(path)[1]
        ctype = CONTENT_TYPES.get(ext, "application/octet-stream")
        # HTML + sw.js must always revalidate (deploys show immediately); other static files are
        # fingerprint-stable enough for a day (the SW is cache-first for them anyway).
        cache = "no-cache" if ext in (".html", "") or path.endswith("sw.js") else "public, max-age=86400"
        mtime = os.path.getmtime(path)
        # Cheap revalidation: If-Modified-Since -> 304 (an unchanged 1.6 MB shell revalidates in
        # ~200 bytes instead of a full re-download on every open).
        from email.utils import formatdate, parsedate_to_datetime
        last_mod = formatdate(mtime, usegmt=True)
        ims = self.headers.get("If-Modified-Since")
        if ims:
            try:
                if int(mtime) <= int(parsedate_to_datetime(ims).timestamp()):
                    self.send_response(304)
                    self.send_header("Cache-Control", cache)
                    self.send_header("Last-Modified", last_mod)
                    self.end_headers()
                    return
            except Exception:
                pass
        gzippable = any(ctype.startswith(t) for t in self.GZIP_TYPES)
        if gzippable and self._accepts_gzip():
            key = (path, mtime)
            gz = self._GZ_CACHE.get(key)
            if gz is None:
                with open(path, "rb") as f:
                    gz = gzip.compress(f.read(), 6)
                if len(self._GZ_CACHE) > 16:   # bound memory; stale (path, old-mtime) keys get evicted here
                    self._GZ_CACHE.clear()
                self._GZ_CACHE[key] = gz
            self.send_response(200)
            self.send_header("Content-Type", ctype)
            self.send_header("Content-Encoding", "gzip")
            self.send_header("Vary", "Accept-Encoding")
            self.send_header("Cache-Control", cache)
            self.send_header("Last-Modified", last_mod)
            self.send_header("Content-Length", str(len(gz)))
            self.end_headers()
            self.wfile.write(gz)
            return
        with open(path, "rb") as f:
            body = f.read()
        self.send_response(200)
        self.send_header("Content-Type", ctype)
        self.send_header("Vary", "Accept-Encoding")
        self.send_header("Cache-Control", cache)
        self.send_header("Last-Modified", last_mod)
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
        if path in ("/privacy", "/privacy.html"):   # public privacy policy (App Store requirement)
            return self._serve_file(os.path.join(STATIC_DIR, "privacy.html"))
        if path in ("/install", "/install.html"):   # public "add to home screen" guide for staff
            return self._serve_file(os.path.join(STATIC_DIR, "install.html"))
        if path == "/sw.js":   # service worker must be served from the origin root for full scope
            return self._serve_file(os.path.join(STATIC_DIR, "sw.js"))
        if path in ("/manifest.webmanifest", "/favicon.ico"):
            return self._serve_file(os.path.join(STATIC_DIR, path.lstrip("/") if path != "/favicon.ico" else "icons/favicon-32.png"))
        if path.startswith("/static/"):
            safe = os.path.normpath(os.path.join(STATIC_DIR, path[len("/static/"):]))
            if not safe.startswith(STATIC_DIR):
                return self._err("Forbidden.", 403)
            return self._serve_file(safe)

        if path == "/approve":
            return self._approve_via_link(qs)
        if path == "/capprove":
            return self._coll_approve_via_link(qs)
        if path == "/api/config":
            return self._json({"demo": DEMO_MODE, "clientId": M365["clientId"],
                               "tenantId": M365["tenantId"], "mapsKey": M365["mapsKey"],
                               "vapidPublicKey": _ensure_vapid().get("pub") or "",
                               # Finance SharePoint folder for payment/claim/travel attachments (request #4).
                               # Public in config so every requester (incl. staff) can upload on submit.
                               "financeSpUrl": db.get_setting("portal_financeSpUrl", "") or "",
                               # App version = mtime of the served HTML (changes on every deploy). The
                               # client polls this and reloads the PWA when it changes, so an installed
                               # app never keeps running stale code after an update.
                               "appVersion": _app_version()})
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
        if path == "/api/esign/pin/all":
            return self._guard(lambda u: self._json({"pins": db.all_pin_statuses()}), manager=True)
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
        if path == "/api/esign":
            return self._guard(lambda u: self._esign(u, body))
        if path == "/api/esign/pin":
            return self._guard(lambda u: self._pin_dispatch(u, body))
        if path == "/api/attendance/checkin":
            return self._guard(lambda u: self._checkin(u, body))
        if path == "/api/attendance/checkout":
            return self._guard(lambda u: self._checkout(u, body))
        if path.startswith("/api/attendance/") and path.endswith("/ot"):
            aid = path[len("/api/attendance/"):-len("/ot")]
            return self._guard(lambda u: self._attendance_ot(u, aid, body), manager=True)
        if path == "/api/leave":
            return self._guard(lambda u: self._leave_create(u, body))
        if path == "/api/push/subscribe":
            return self._guard(lambda u: self._push_subscribe(u, body))
        if path == "/api/push/unsubscribe":
            return self._guard(lambda u: self._push_unsub(u, body))
        if path == "/api/push/send":
            return self._guard(lambda u: self._push_send(u, body))
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
            return self._guard(lambda u: self._coll_update(u, nm, seg[1] if len(seg) > 1 else "", body), manager=(nm not in self.STAFF_WRITE and nm not in ("onboarding",) and not nm.startswith("crm_")))
        if path.startswith("/api/employees/"):
            eid = path.rsplit("/", 1)[1]
            return self._guard(lambda u: self._emp_update(u, eid, body), manager=True)
        if path.startswith("/api/leave/"):
            lid = path.rsplit("/", 1)[1]
            return self._guard(lambda u: self._leave_status(u, lid, body), manager=True)
        if path.startswith("/api/zones/"):
            zid = path.rsplit("/", 1)[1]
            return self._guard(lambda u: self._zone_update(zid, body), manager=True)
        return self._err("Not found.", 404)

    def do_DELETE(self):
        path = urlparse(self.path).path
        if path.startswith("/api/coll/"):
            seg = path[len("/api/coll/"):].split("/")
            return self._guard(lambda u: self._coll_delete(u, seg[0], seg[1] if len(seg) > 1 else ""), manager=(seg[0] not in self.STAFF_WRITE and not seg[0].startswith("crm_")))
        if path.startswith("/api/employees/"):
            eid = path.rsplit("/", 1)[1]
            return self._guard(lambda u: self._emp_delete(u, eid), manager=True)
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

    # -- web push -----------------------------------------------------------
    def _push_subscribe(self, u, body):
        sub = body.get("subscription") or body
        if not (isinstance(sub, dict) and sub.get("endpoint")):
            return self._err("Bad subscription.", 400)
        try:
            db.push_sub_add(u.get("email"), sub)
        except Exception:
            return self._err("Could not save subscription.", 500)
        return self._json({"ok": True})

    def _push_unsub(self, u, body):
        try:
            db.push_sub_remove(body.get("endpoint"))
        except Exception:
            pass
        return self._json({"ok": True})

    def _push_send(self, u, body):
        """Relay an OS notification to users' devices. To stop the relay being abused as an
        internal phishing/spam channel: (1) the click URL is forced to a SAME-ORIGIN path,
        (2) a non-manager may only notify THEMSELVES or their direct manager (which is all the
        legitimate 'I submitted a request' flow needs); managers may fan out (that is how
        approval/update alerts reach requesters), (3) recipients are capped."""
        if not _PUSH_OK:
            return self._json({"ok": False, "disabled": True})
        to = body.get("to") or []
        if isinstance(to, str):
            to = [to]
        to = [str(e).lower() for e in to if e][:200]
        me = (u.get("email") or "").lower()
        if u.get("role") != "manager":
            allowed = {me}
            mgr = (u.get("managerEmail") or "").lower()
            if mgr:
                allowed.add(mgr)
            to = [e for e in to if e in allowed]
        # Click target must be a site-relative path (never a scheme or protocol-relative URL).
        url = str(body.get("url") or "/")
        if (not url.startswith("/")) or url.startswith("//"):
            url = "/"
        payload = {
            "title": (str(body.get("title") or "Humiley Portal"))[:120],
            "body": (str(body.get("body") or ""))[:400],
            "url": url[:300],
            "tag": (str(body.get("tag") or ""))[:80],
        }
        sent = 0
        try:
            for endpoint, sub in db.push_subs_for(to):
                if _web_push(endpoint, sub, payload):
                    sent += 1
        except Exception:
            pass
        return self._json({"ok": True, "sent": sent})

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

    @staticmethod
    def _jwt_claims(token):
        """Best-effort decode of a JWT payload (no signature verification). Returns dict or None."""
        try:
            import base64
            seg = token.split(".")[1]
            seg += "=" * (-len(seg) % 4)
            return json.loads(base64.urlsafe_b64decode(seg).decode("utf-8"))
        except Exception:
            return None

    def _auth_m365(self, body):
        token_in = body.get("accessToken", "")
        if not token_in:
            return self._err("Missing access token.", 400)
        # Validate the token's critical claims against our Entra app/tenant before trusting it
        # (defence against replaying a Graph token minted for another app the user also consented to).
        claims = self._jwt_claims(token_in)
        if claims:
            if claims.get("exp") and claims["exp"] < time.time():
                return self._err("Microsoft 365 token expired — please sign in again.", 401)
            tid = claims.get("tid")
            if M365.get("tenantId") and tid and tid != M365["tenantId"]:
                return self._err("Sign-in is from an unexpected Microsoft 365 tenant.", 403)
            appid = claims.get("appid") or claims.get("azp")
            if M365.get("clientId") and appid and appid != M365["clientId"]:
                return self._err("This Microsoft 365 token was not issued for the Humiley Portal.", 403)
        email = graph_me(token_in)
        if not email:
            return self._err("Could not verify Microsoft 365 account.", 401)
        emp = db.get_employee_by_email(email)
        if not emp:
            return self._err("No employee record for %s. Ask an admin to add you." % email, 403)
        # Self-heal protected super-admins so a mistaken demotion can never lock them out.
        if email in self.ADMIN_EMAILS and (emp.get("level") != "admin" or emp.get("role") != "manager"):
            db.update_employee(emp["id"], {"level": "admin", "role": "manager"})
            emp["level"] = "admin"; emp["role"] = "manager"
        token = new_session(emp["id"], emp.get("role", "staff"))
        return self._json({"token": token, "user": dict(emp, role=emp.get("role", "staff"))})

    # -- 21 CFR Part 11 electronic signatures -------------------------------
    @staticmethod
    def _utc_now():
        return time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime())

    @staticmethod
    def _same_m365_identity(a, b):
        """True if two Microsoft 365 identities are the same person. The login path stores the
        Graph /me `mail` (or UPN) as the session email, while a signing ID token exposes
        `preferred_username`/`upn`; for aliased mailboxes, onmicrosoft UPNs, guest #EXT# accounts
        or mere casing these legitimately differ for the SAME user — which is why setting a PIN
        ("confirm by Microsoft 365") was being rejected. Match on the full address OR the mailbox
        local-part (case-insensitive). A genuinely different account (different local-part) is
        still rejected, so the Part 11 identity binding is preserved."""
        a = (a or "").strip().lower(); b = (b or "").strip().lower()
        if not a or not b:
            return True   # nothing to compare against -> don't block (the session is already authenticated)
        if a == b:
            return True
        la = a.split("#ext#")[0].split("@")[0]
        lb = b.split("#ext#")[0].split("@")[0]
        return bool(la) and la == lb

    def _esign_fresh(self, id_token, max_age=600):
        """Validate a FRESH Microsoft 365 ID token for an electronic signature (Part 11 §11.200):
        tenant + audience must match our Entra app, and auth_time must be within max_age seconds —
        proving the user just re-authenticated interactively for this signing."""
        claims = self._jwt_claims(id_token)
        if not claims:
            return False, "Could not read the Microsoft 365 sign-in."
        now = time.time()
        if claims.get("exp") and claims["exp"] < now:
            return False, "The signing sign-in expired — please try again."
        tid = claims.get("tid")
        if M365.get("tenantId") and tid and tid != M365["tenantId"]:
            return False, "Signed in from an unexpected Microsoft 365 tenant."
        aud = claims.get("aud")
        if M365.get("clientId") and aud and aud != M365["clientId"]:
            return False, "This sign-in was not issued for the Humiley Portal."
        at = claims.get("auth_time")
        if at is None:
            # Some Entra apps don't emit the optional `auth_time` claim. With prompt=login the
            # token was just minted by a fresh interactive re-authentication, so `iat` is an
            # equally-recent proof of re-auth for the max_age window (Part 11 recency preserved).
            at = claims.get("iat")
        if at is None:
            return False, "The sign-in did not include an authentication time."
        try:
            if now - float(at) > max_age:
                return False, "Please re-authenticate to sign — the sign-in is not recent enough."
        except (TypeError, ValueError):
            return False, "Invalid authentication time in the sign-in."
        email = claims.get("preferred_username") or claims.get("upn") or claims.get("email") or ""
        return True, {"name": claims.get("name") or email, "email": email, "auth_time": int(float(at)), "oid": claims.get("oid")}

    # -- 3-level approval workflow: Perform (requester) -> Review (direct manager) -> Approve (Management/Director) --
    _LEVEL_RANK = {"staff": 1, "manager": 2, "management": 3, "editor": 4, "admin": 5}
    THREE_LEVEL_COLLS = ("claims", "travel", "payments", "leave")

    def _lvl_rank(self, lvl):
        return self._LEVEL_RANK.get((lvl or "staff"), 1)

    def _is_mgmt(self, u):
        return self._lvl_rank(u.get("level")) >= self._LEVEL_RANK["management"]

    def _is_approver(self, u):
        # Final approval is reserved for Editor + Admin (request #6). A direct manager who is an
        # Editor/Admin approves in ONE step (request #5) — see the "approved" branch below.
        return self._lvl_rank(u.get("level")) >= self._LEVEL_RANK["editor"]

    @staticmethod
    def _appr_state(status):
        s = str(status or "").strip().lower()
        if s in ("reviewed", "pending approval"):
            return "review"
        if s == "approved":
            return "approved"
        if s == "paid":
            return "paid"
        if s == "rejected":
            return "rejected"
        return "submit"   # submitted / pending / partially approved / empty

    def _appr_check(self, u, coll, cur_status, set_status, sigs, owner_id):
        """Enforce the 3-level approval flow. Returns None if allowed, else an error string.
        Review = direct manager; Approve / Paid = Management (Director); Reject = manager at either stage."""
        t = str(set_status or "").strip().lower()
        if coll not in self.THREE_LEVEL_COLLS:
            if t in ("approved", "rejected", "paid") and u.get("role") != "manager":
                return "Manager access required to approve, reject or mark paid."
            return None
        if not t:
            return None   # requester's own submit signing (no status change)
        cur = self._appr_state(cur_status)
        same_person = owner_id and owner_id == u.get("id")
        if t == "reviewed":
            if u.get("role") != "manager":
                return "Manager access required to review this request."
            if cur != "submit":
                return "This request has already been reviewed."
            if same_person:
                return "You cannot review your own request."
            # Review must come from the requester's DIRECT manager (request #6) when one is on
            # record. Editors/Admins skip this — they approve directly (one step).
            if not self._is_approver(u):
                owner = db.get_employee(owner_id) if owner_id else None
                mgr_email = ((owner or {}).get("managerEmail") or "").lower()
                if mgr_email and mgr_email != (u.get("email") or "").lower():
                    return "Only the requester's direct manager can review this request."
            return None
        if t == "approved":
            if not self._is_approver(u):
                return "Editor or Admin access is required for final approval."
            # One-step collapse (request #5): an Editor/Admin can approve straight from the
            # submitted state, so a direct manager who is Editor/Admin reviews+approves in one go.
            if cur not in ("submit", "review"):
                return "This request is no longer pending approval."
            if same_person:
                return "You cannot approve your own request."
            reviewer_ids = [s.get("userId") for s in (sigs or []) if "review" in str(s.get("meaning", "")).lower()]
            if u.get("id") in reviewer_ids:
                return "A different person must give final approval than the one who reviewed."
            return None
        if t == "rejected":
            if u.get("role") != "manager":
                return "Manager access required to reject this request."
            if cur not in ("submit", "review"):
                return "This request is no longer pending."
            if same_person:
                return "You cannot reject your own request."
            return None
        if t == "paid":
            if not self._is_mgmt(u):
                return "Director / Management access is required to mark a request paid."
            if cur != "approved":
                return "Only an approved request can be marked paid."
            return None
        return None

    @staticmethod
    def _claim_rollup(items):
        """Roll a claim's overall status up from its line-item statuses (mirrors the frontend)."""
        if not items:
            return "Submitted"
        st = lambda it: it.get("status") or "Submitted"
        if any(st(it) == "Submitted" for it in items):
            return "Partially approved" if any(st(it) in ("Approved", "Rejected", "Reviewed") for it in items) else "Submitted"
        if all(st(it) == "Reviewed" for it in items):
            return "Reviewed"
        if all(st(it) == "Approved" for it in items):
            return "Approved"
        if all(st(it) == "Rejected" for it in items):
            return "Rejected"
        if any(st(it) == "Reviewed" for it in items):
            return "Reviewed"
        return "Partially approved"

    def _esign(self, u, body):
        """Apply an electronic signature to a record (Part 11): re-authenticate the signer via a
        fresh M365 sign-in, stamp an immutable signature manifestation (signer, UTC time, meaning,
        method) onto the record, optionally set its status, and write a secure audit-trail entry."""
        coll = body.get("coll"); iid = body.get("id"); meaning = (body.get("meaning") or "").strip()
        set_status = body.get("setStatus")
        if not coll or not iid or not meaning:
            return self._err("coll, id and meaning are required.", 400)
        # Identify + re-authenticate the signer. Two components (Part 11 §11.200): the authenticated
        # session identity (something you have) + either a fresh M365 sign-in or the secret PIN.
        if DEMO_MODE:
            method = "Demo mode (no re-authentication)"; auth_time = None
            signer_name = u.get("name") or "User"; signer_email = (u.get("email") or "").lower()
        elif body.get("method") == "pin" or body.get("pin"):
            ok, reason = db.verify_pin(u.get("id"), body.get("pin") or "")
            if not ok:
                if reason == "locked":
                    return self._err("Signing PIN locked for 15 minutes after too many attempts. Sign with Microsoft 365, or try again later.", 423)
                if reason == "must_change":
                    return self._err("Your signing PIN was reset — please set a new one in My Profile.", 409)
                if reason == "revoked":
                    return self._err("Your signing PIN was de-authorized — please set a new one in My Profile.", 409)
                if reason == "expired":
                    return self._err("Your signing PIN has expired — please set a new one in My Profile.", 409)
                return self._err("Incorrect PIN.", 401)  # no_pin / bad_pin collapse (no enumeration)
            method = "Signature PIN"; auth_time = None
            signer_name = u.get("name") or "User"; signer_email = (u.get("email") or "").lower()
        else:
            ok, info = self._esign_fresh(body.get("idToken") or "")
            if not ok:
                return self._err(info, 401)
            method = "Microsoft 365 re-authentication"; auth_time = info.get("auth_time")
            signer_name = info.get("name") or u.get("name") or "User"
            signer_email = (info.get("email") or "").lower()
            sess_email = (u.get("email") or "").lower()
            if not self._same_m365_identity(signer_email, sess_email):
                return self._err("The Microsoft 365 account you signed with does not match your session.", 403)
        sig = {"name": signer_name, "email": signer_email, "userId": u.get("id"),
               "ts": self._utc_now(), "meaning": meaning, "method": method}
        if auth_time:
            sig["authTime"] = auth_time
        # Leave lives in its own structured table (not the generic JSON collections).
        if coll == "leave":
            lv = db.get_leave(int(iid)) if str(iid).isdigit() else None
            if not lv:
                return self._err("Leave record not found.", 404)
            if u.get("role") != "manager" and lv.get("emp_id") and lv.get("emp_id") != u.get("id"):
                return self._err("You can only sign your own record.", 403)
            try:
                _lsigs = json.loads(lv.get("signatures") or "[]")
            except Exception:
                _lsigs = []
            _err = self._appr_check(u, "leave", lv.get("status"), set_status, _lsigs, lv.get("emp_id"))
            if _err:
                return self._err(_err, 403)
            row = db.append_leave_signature(int(iid), sig, new_status=(set_status or None))
            db.put_collection_item("audit", {"actor": signer_name, "actorId": u.get("id"),
                "action": "E-signature — " + meaning, "target": "leave/" + str(iid),
                "detail": (set_status or "signed") + " · " + method + (" · auth_time=" + str(auth_time) if auth_time else ""),
                "ts": self._utc_now()})
            return self._json({"ok": True, "item": {k: v for k, v in (row or {}).items() if k != "token"}})
        if coll not in self.COLLECTIONS:
            return self._err("Unknown collection.", 404)
        item = next((x for x in db.list_collection(coll) if x.get("id") == iid), None)
        if not item:
            return self._err("Record not found.", 404)
        if u.get("role") != "manager" and item.get("empId") and item.get("empId") != u.get("id"):
            return self._err("You can only sign your own record.", 403)
        # Per-line-item signed decision on a claim (itemId present): review / approve / reject one line.
        item_id = body.get("itemId")
        if coll == "claims" and item_id:
            lines = item.get("items") if isinstance(item.get("items"), list) else []
            line = next((x for x in lines if x.get("id") == item_id), None)
            if not line:
                return self._err("Claim item not found.", 404)
            synth = [{"meaning": "review", "userId": line.get("reviewedById")}] if line.get("reviewedById") else []
            _err = self._appr_check(u, "claims", line.get("status") or "Submitted", set_status, synth, item.get("empId"))
            if _err:
                return self._err(_err, 403)
            item.setdefault("signatures", []).append(sig)
            if set_status:
                line["status"] = set_status
                if set_status == "Reviewed":
                    line["reviewedBy"] = signer_name; line["reviewedById"] = u.get("id")
                elif set_status == "Approved":
                    line["approvedBy"] = signer_name
                item["status"] = self._claim_rollup(lines)
            db.put_collection_item("claims", item)
            db.put_collection_item("audit", {"actor": signer_name, "actorId": u.get("id"),
                "action": "E-signature — " + meaning, "target": "claims/" + str(iid) + "/item/" + str(item_id),
                "detail": (set_status or "signed") + " · " + method, "ts": self._utc_now()})
            return self._json({"ok": True, "item": {k: v for k, v in item.items() if k != "token"}})
        _err = self._appr_check(u, coll, item.get("status"), set_status, item.get("signatures"), item.get("empId"))
        if _err:
            return self._err(_err, 403)
        item.setdefault("signatures", []).append(sig)
        if set_status:
            item["status"] = set_status
            if coll == "claims" and isinstance(item.get("items"), list):
                for it in item["items"]:
                    if (it.get("status") or "Submitted") in ("Submitted", "Reviewed"):
                        it["status"] = set_status
            if set_status == "Reviewed":
                item["reviewedBy"] = signer_name
            if set_status == "Approved":
                item["approvedBy"] = signer_name
            if set_status == "Paid":
                item.setdefault("paidOn", time.strftime("%Y-%m-%d"))
        db.put_collection_item(coll, item)
        db.put_collection_item("audit", {"actor": signer_name, "actorId": u.get("id"),
            "action": "E-signature — " + meaning,
            "target": coll + "/" + str(iid),
            "detail": (set_status or "signed") + " · " + method + (" · auth_time=" + str(auth_time) if auth_time else ""),
            "ts": self._utc_now()})
        return self._json({"ok": True, "item": {k: v for k, v in item.items() if k != "token"}})

    # Freshness window for PIN-lifecycle M365 tokens (enroll/change/reset/remove). Relaxed vs the
    # 600s signing window because the token is acquired SILENTLY (no popup/redirect — reliable in
    # the installed app/PWA) and the session identity is already M365-verified; signing stays 600s.
    PIN_REAUTH_MAX_AGE = 90 * 24 * 3600

    PIN_POLICY_MSG = {
        "length": "PIN must be 6 to 12 letters or digits.",
        "charset": "PIN may contain only letters and digits.",
        "all_same": "Choose a less predictable PIN — avoid repeated characters.",
        "sequential": "Avoid sequential characters like 123456.",
        "trivial": "That PIN is too common — please choose another.",
        "personal_info": "Don't use your phone, ID or birth date as your PIN.",
        "reuse": "Please choose a PIN different from your previous one.",
    }

    def _pin_audit(self, u, event, target_id, detail):
        db.put_collection_item("audit", {"actor": u.get("name"), "actorId": u.get("id"),
            "action": "E-signature PIN — " + event, "target": "esign_pin/" + str(target_id),
            "detail": detail, "ts": self._utc_now()})

    def _pin_dispatch(self, u, body):
        """Self-service signature-PIN lifecycle (Part 11 §11.300). One consolidated endpoint keyed by
        `action`; every path operates on the server-derived session id (never a client-supplied id),
        except `revoke` which is a manager act on a named employee."""
        action = (body.get("action") or "status").strip().lower()
        uid = u.get("id")

        if action == "status":
            return self._json(dict({"ok": True}, **db.get_pin_status(uid)))

        if action == "verify":   # pre-flight check so a wrong PIN never orphans a just-created record
            ok, reason = db.verify_pin(uid, body.get("pin") or "")
            if ok:
                return self._json({"ok": True})
            if reason == "locked":
                return self._err("Signing PIN locked for 15 minutes after too many attempts. Sign with Microsoft 365, or try again later.", 423)
            if reason == "must_change":
                return self._err("Your signing PIN was reset — please set a new one in My Profile.", 409)
            if reason == "revoked":
                return self._err("Your signing PIN was de-authorized — please set a new one in My Profile.", 409)
            if reason == "expired":
                return self._err("Your signing PIN has expired — please set a new one in My Profile.", 409)
            return self._err("Incorrect PIN.", 401)

        if action == "revoke":   # manager de-authorizes another employee's PIN (cannot read/set it)
            if u.get("role") != "manager":
                return self._err("Manager access required.", 403)
            emp_id = body.get("empId")
            if not emp_id or not db.get_employee(emp_id):
                return self._err("Employee not found.", 404)
            db.revoke_pin(emp_id)
            self._pin_audit(u, "revoke", emp_id, "de-authorized by manager")
            return self._json({"ok": True})

        if action == "remove":   # owner removes their own PIN — must prove identity
            if body.get("currentPin"):
                ok, r = db.verify_pin(uid, body.get("currentPin"))
                if not ok:
                    if r == "locked":
                        return self._err("Too many attempts — the PIN is locked. Try again later.", 423)
                    return self._err("Current PIN is incorrect.", 401)
            elif not DEMO_MODE:
                # PIN management (not signing): a valid Microsoft 365 session token — acquired
                # SILENTLY on the client, works on web + the installed app without a popup — is
                # sufficient identity proof (§11.100(b): the session identity is already M365-
                # verified). Signing itself stays strict (fresh 600s re-auth, above).
                ok, info = self._esign_fresh(body.get("idToken") or "", max_age=self.PIN_REAUTH_MAX_AGE)
                if not ok:
                    return self._err(info, 401)
            db.remove_pin(uid)
            self._pin_audit(u, "remove", uid, "removed by owner")
            return self._json({"ok": True, "enrolled": False})

        if action in ("enroll", "change", "reset"):
            emp = db.get_employee(uid) or dict(u)
            new_pin = body.get("newPin") or ""
            reason = db.validate_pin_policy(emp, new_pin)
            if reason:
                return self._err(self.PIN_POLICY_MSG.get(reason, "That PIN isn't allowed."), 400)
            # Authorization to set: `change` may prove the current PIN; otherwise a FRESH M365 re-auth
            # is required (§11.100(b) identity binding), except in demo mode.
            if action == "change" and body.get("currentPin"):
                ok, r = db.verify_pin(uid, body.get("currentPin"))
                if not ok:
                    if r == "locked":
                        return self._err("Too many attempts — the PIN is locked. Try again later or use Microsoft 365.", 423)
                    return self._err("Current PIN is incorrect.", 401)
                enrolled_via = "current PIN"; oid = None
            elif DEMO_MODE:
                enrolled_via = "demo"; oid = None
            else:
                # PIN enrollment: accept a valid Microsoft 365 session token (acquired silently on
                # the client — no popup, so it works in the installed app / PWA where popups fail).
                # Freshness is relaxed for PIN management only; SIGNING still requires a fresh
                # re-auth (§11.200). Identity is still verified against the session below.
                ok, info = self._esign_fresh(body.get("idToken") or "", max_age=self.PIN_REAUTH_MAX_AGE)
                if not ok:
                    return self._err(info, 401)
                sess_email = (u.get("email") or "").lower(); tok_email = (info.get("email") or "").lower()
                if not self._same_m365_identity(tok_email, sess_email):
                    return self._err("The Microsoft 365 account does not match your session.", 403)
                enrolled_via = "M365 re-authentication"; oid = info.get("oid")
            ok, r = db.set_pin(uid, new_pin, enrolled_via, oid)
            if not ok:
                return self._err(self.PIN_POLICY_MSG.get(r, "Could not set the PIN."), 400)
            self._pin_audit(u, action, uid, "via " + enrolled_via)
            return self._json(dict({"ok": True}, **db.get_pin_status(uid)))

        return self._err("Unknown PIN action.", 400)

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
        # Optional overtime REQUEST at checkout — pending manager approval; only approved OT counts.
        ot_hours = body.get("otHours") or 0
        hrs = db.clock_out(rec["id"], t, ot_hours=ot_hours, ot_reason=body.get("otReason") or "")
        return self._json({"ok": True, "hrs": hrs, "id": rec["id"],
                           "otStatus": ("pending" if ot_hours else "none")})

    def _attendance_ot(self, u, aid, body):
        """Manager approves / rejects a pending overtime request (request #2). Only approved OT
        is added to the system; a rejected request never counts."""
        rec = db.get_attendance(int(aid)) if str(aid).isdigit() else None
        if not rec:
            return self._err("Attendance record not found.", 404)
        if rec.get("emp_id") == u.get("id"):
            return self._err("You cannot approve your own overtime.", 403)
        st = db.decide_attendance_ot(int(aid), body.get("decision") or "approve")
        return self._json({"ok": True, "otStatus": st, "id": rec.get("id")})

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

    def _coll_approve_via_link(self, qs):
        """One-click Approve / Reject / Mark-paid from an email link (no login), by token.
        Covers expense claims, travel requests and payment requests."""
        token = qs.get("t", [""])[0] or qs.get("token", [""])[0]
        action = (qs.get("action", ["approve"])[0]).lower()
        if not token:
            return self._html("Invalid link", "This approval link is not valid.", "#C00000")
        LABEL = {"claims": "expense claim", "travel": "travel request", "payments": "payment request"}
        for coll in ("claims", "travel", "payments"):
            item = next((x for x in db.list_collection(coll) if x.get("token") == token), None)
            if not item:
                continue
            who = item.get("name") or "the employee"
            cur = item.get("status") or "Submitted"
            state = self._appr_state(cur)
            detail = item.get("reqNo") or item.get("title") or item.get("dest") or ""
            # Email links do the manager's REVIEW step (and Reject). Final Director approval and
            # mark-paid happen in the portal, where the session enforces Management level + segregation.
            if action == "paid" and coll == "payments":
                if state != "approved":
                    return self._html("Not approved yet", "This payment from %s is <b>%s</b> — a Director must approve it in the portal before it can be marked paid." % (who, cur), "#205090")
                new_status = "Paid"
            elif action in ("reject", "decline", "deny"):
                if state not in ("submit", "review"):
                    return self._html("Already " + cur, "This %s from %s is already <b>%s</b>." % (LABEL[coll], who, cur), "#205090")
                new_status = "Rejected"
            else:   # approve / review link from the direct manager
                if state != "submit":
                    return self._html("Already " + cur, "This %s from %s is already <b>%s</b> — final approval happens in the portal." % (LABEL[coll], who, cur), "#205090")
                new_status = "Reviewed"
            item["status"] = new_status
            if new_status == "Paid":
                item.setdefault("paidOn", time.strftime("%Y-%m-%d"))
            if coll == "claims" and isinstance(item.get("items"), list):
                for it in item["items"]:
                    if (it.get("status") or "Submitted") in ("Submitted", "Reviewed"):
                        it["status"] = new_status
            if new_status == "Reviewed":
                item["reviewedBy"] = item.get("reviewedBy") or "Email review"
            db.put_collection_item(coll, item)
            color = "#00B060" if new_status in ("Paid",) else ("#C00000" if new_status == "Rejected" else "#205090")
            msg = {"Reviewed": "has been <b>reviewed</b> and is now awaiting Director approval in the portal",
                   "Rejected": "has been <b>rejected</b>",
                   "Paid": "has been <b>marked paid</b>"}.get(new_status, "has been updated")
            return self._html(LABEL[coll].capitalize() + " " + ("reviewed" if new_status == "Reviewed" else new_status.lower()),
                              "%s's %s%s %s. You can close this tab." % (
                                  who, LABEL[coll], (" (" + detail + ")" if detail else ""), msg),
                              color)
        return self._html("Invalid or expired link",
                          "This approval link is not valid — the item may have been removed. Please review it in the app.", "#C00000")

    # -- employees ----------------------------------------------------------
    def _emp_create(self, u, body):
        if not body.get("name") or not body.get("email"):
            return self._err("name and email required.")
        if db.get_employee_by_email(body["email"]):
            return self._err("An employee with that email already exists.")
        body = dict(body or {})
        # Only admins may set access level / role on create (prevents privilege escalation).
        if ("level" in body or "role" in body or "appsDenied" in body or "appsAllowed" in body) and self._caller_level(u) != "admin":
            body.pop("level", None)
            body.pop("role", None)
            body.pop("appsDenied", None)
            body.pop("appsAllowed", None)
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
        # Protected super-admins are ALWAYS admin — they can never be demoted or locked out,
        # regardless of what the stored level says.
        if (u.get("email") or "").lower() in self.ADMIN_EMAILS:
            return "admin"
        lv = u.get("level")
        if lv in ("staff", "manager", "management", "editor", "admin"):
            return lv
        if u.get("role") == "manager":
            return "management" if re.search(r"director|managing|chief|head|coo|ceo|cfo", u.get("title") or "", re.I) else "manager"
        return "staff"

    def _level_rank(self, lvl):
        try:
            return self.LEVEL_ORDER.index(lvl) + 1
        except ValueError:
            return 1

    def _apps_denied(self, u):
        """The set of app ids (crm/pm/hr) an admin has disabled for this user."""
        raw = u.get("appsDenied")
        if isinstance(raw, (list, tuple, set)):
            return set(str(x).strip().lower() for x in raw if str(x).strip())
        return set(x.strip().lower() for x in str(raw or "").split(",") if x.strip())

    def _emp_delete(self, u, eid):
        # Deleting an employee record is destructive — require Approver (management) or above,
        # not just any manager-tier (Contributor) account.
        if self._level_rank(self._caller_level(u)) < self._level_rank("management"):
            return self._err("Management access required to delete an employee.", 403)
        db.delete_employee(eid)
        return self._json({"ok": True})

    def _emp_update(self, u, eid, body):
        ex = db.get_employee(eid)
        if not ex:
            return self._err("Employee not found.", 404)
        body = dict(body or {})
        # Only admins may change access level or role (prevents privilege escalation).
        if ("level" in body or "role" in body or "appsDenied" in body or "appsAllowed" in body) and self._caller_level(u) != "admin":
            body.pop("level", None)
            body.pop("role", None)
            body.pop("appsDenied", None)
            body.pop("appsAllowed", None)
        # Protected super-admins can never be demoted — drop any level/role/app change on them.
        if (ex.get("email") or "").lower() in self.ADMIN_EMAILS:
            body.pop("level", None)
            body.pop("role", None)
            body.pop("appsDenied", None)
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
        out["financeSpUrl"] = db.get_setting("portal_financeSpUrl", "") or ""
        return self._json(out)

    def _portal_update(self, u, body):
        for k in self.PORTAL_KEYS:
            if isinstance(body.get(k), list):
                db.set_setting("portal_" + k, body[k])
        if isinstance(body.get("teamsWebhook"), str):
            db.set_setting("portal_teamsWebhook", body["teamsWebhook"])
        if isinstance(body.get("financeSpUrl"), str):
            db.set_setting("portal_financeSpUrl", body["financeSpUrl"].strip())
        return self._json({"ok": True})

    # -- generic HR collections (recruitment, onboarding, performance, talent, training) --
    COLLECTIONS = {"jobs", "candidates", "onboarding", "reviews", "goals", "courses", "talent", "payruns", "padr", "competency", "pip", "claims", "acks", "audit", "travel", "exits", "benefits", "learningpaths", "enrollments", "payadjust", "devices", "handovers", "payments", "crm_deals", "crm_companies", "crm_contacts", "crm_leads", "crm_products", "crm_targets", "crm_aop", "pm_projects", "pm_settings", "pm_deliverables", "pm_tasks", "pm_costs", "pm_quality", "pm_quality_itp", "pm_quality_itp_items", "pm_resources", "pm_comms", "pm_issues", "pm_risks", "pm_changes", "pm_lessons", "pm_procurement", "pm_procurement_payments", "pm_stakeholders", "pm_rfis", "pm_sitereports", "pm_weekreports", "pm_portfolioSnapshots", "pm_execNotes"}
    # Collections any authenticated user (incl. staff) may create for self-service.
    STAFF_WRITE = {"claims", "travel", "payments", "acks", "audit", "padr", "enrollments", "crm_deals", "crm_companies", "crm_contacts", "crm_leads", "crm_products", "crm_targets", "crm_aop", "pm_tasks", "pm_deliverables", "pm_quality", "pm_quality_itp", "pm_quality_itp_items", "pm_resources", "pm_comms", "pm_issues", "pm_risks", "pm_changes", "pm_lessons", "pm_stakeholders", "pm_rfis", "pm_sitereports", "pm_weekreports"}
    PAYROLL_ADMIN = {"payruns", "payadjust"}   # payroll writes are Administrator-only
    # minimum access LEVEL required to READ a collection. Sensitive HR data raised to
    # management; recruitment/audit stay manager. Anything not listed AND not in
    # SELF_OWNED / a shared catalog (courses, learningpaths) is open to managers only
    # for staff via the self-owner scoping below.
    READ_MIN = {"payruns": "management", "payadjust": "management", "exits": "management", "pip": "management",
                "reviews": "manager", "talent": "manager", "jobs": "manager", "candidates": "manager",
                "competency": "manager", "audit": "manager"}
    # Staff MAY read these collections, but ONLY their own records (scoped by empId / name / assignedTo).
    SELF_OWNED = {"claims", "travel", "payments", "acks", "padr", "enrollments", "onboarding", "goals", "benefits", "devices", "handovers"}
    # Manager-only HR collections gated by the per-user "hr" app toggle (crm_*/pm_* inferred by prefix).
    HR_APP_COLLS = {"jobs", "candidates", "reviews", "talent", "competency", "pip", "exits"}
    EMP_SENSITIVE = {"salary", "grade", "bank", "taxId", "dependents", "personalId", "address", "emergency", "annualUsed", "annualTotal", "sickUsed", "sickTotal", "compoff"}
    LEVEL_ORDER = ["staff", "manager", "management", "editor", "admin"]

    def _coll_list(self, u, name):
        if name not in self.COLLECTIONS:
            return self._err("Unknown collection.", 404)
        # per-user app access — an admin can disable CRM / Projects / HR for a user
        app = "crm" if name.startswith("crm_") else ("pm" if name.startswith("pm_") else ("hr" if name in self.HR_APP_COLLS else None))
        if app and app in self._apps_denied(u):
            return self._err("Access restricted — the %s app is not enabled for your account." % app.upper(), 403)
        # minimum access level to read
        need = self.READ_MIN.get(name)
        if need and self._level_rank(self._caller_level(u)) < self._level_rank(need):
            return self._err("Access restricted to %s level or above." % need, 403)
        items = db.list_collection(name)
        # staff see ONLY their own records in self-service collections (no cross-employee read)
        if self._caller_level(u) == "staff" and name in self.SELF_OWNED:
            myid, myname = u.get("id"), u.get("name")
            items = [it for it in items
                     if it.get("empId") == myid
                     or (not it.get("empId") and myname and it.get("name") == myname)
                     or (myname and it.get("assignedTo") == myname)]
        # CRM records: salesperson (staff) sees own, manager sees their department,
        # management+ sees all. crm_products is a shared catalogue and is never scoped.
        if name.startswith("crm_") and name != "crm_products":
            lvl = self._caller_level(u)
            if self._level_rank(lvl) < self._level_rank("management"):
                myname = u.get("name") or ""
                if lvl == "staff":
                    items = [it for it in items if (it.get("owner") or "") == myname]
                else:
                    mydept = u.get("dept") or u.get("department") or ""
                    deptof = {e.get("name"): (e.get("dept") or "") for e in db.list_employees()}
                    items = [it for it in items
                             if (it.get("owner") or "") == myname
                             or (mydept and deptof.get(it.get("owner") or "") == mydept)]
        # Never expose the one-click approval token in list reads — only the create response
        # carries it (once, for the email). Stops a requester from reading their own token and
        # self-approving via the unauthenticated /capprove link.
        items = [{k: v for k, v in it.items() if k != "token"} for it in items]
        return self._json({"items": items})

    @staticmethod
    def _crm_sanitize(body):
        # Defense-in-depth: strip angle brackets from CRM string fields so a stored value
        # can never inject markup when re-rendered (frontend also HTML-escapes on output).
        out = dict(body or {})
        for k, v in list(out.items()):
            if isinstance(v, str):
                out[k] = v.replace("<", "").replace(">", "")
        return out

    def _coll_add(self, u, name, body):
        if name not in self.COLLECTIONS:
            return self._err("Unknown collection.", 404)
        if name.startswith("pm_") and name not in self.STAFF_WRITE and u.get("role") != "manager":
            return self._err("Manager access required.", 403)
        if name.startswith("crm_") or name.startswith("pm_"):
            body = self._crm_sanitize(body)
        if name in self.PAYROLL_ADMIN and self._level_rank(self._caller_level(u)) < self._level_rank("editor"):
            return self._err("Payroll changes require Editor level or above.", 403)
        item = dict(body or {})
        # A payment request must carry its supporting invoice/bill (inline PDF or a SharePoint copy).
        if name == "payments" and not (item.get("attachment") or item.get("spUrl")):
            return self._err("An invoice / bill attachment is required for a payment request.", 400)
        # For staff self-service records, stamp identity from the session (no impersonation).
        if name in ("claims", "travel", "payments", "acks"):
            item["empId"] = u.get("id")
            item["name"] = u.get("name")
        # Unguessable token for one-click email Approve/Reject (no login), like leave.
        if name in ("claims", "travel", "payments"):
            item.setdefault("token", secrets.token_urlsafe(18))
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
        if name.startswith("pm_"):
            item.setdefault("createdBy", u.get("name"))
            item.setdefault("createdById", u.get("id"))
        return self._json({"ok": True, "item": db.put_collection_item(name, item)})

    def _coll_update(self, u, name, iid, body):
        if name not in self.COLLECTIONS or not iid:
            return self._err("Unknown item.", 404)
        if name.startswith("pm_") and name not in self.STAFF_WRITE and u.get("role") != "manager":
            return self._err("Manager access required.", 403)
        if name.startswith("crm_") or name.startswith("pm_"):
            body = self._crm_sanitize(body)
        if name in self.PAYROLL_ADMIN and self._level_rank(self._caller_level(u)) < self._level_rank("editor"):
            return self._err("Payroll changes require Editor level or above.", 403)
        # Non-managers reach this only for 'padr'/'enrollments'/crm_* (own records).
        if u.get("role") != "manager" and not name.startswith("crm_") and not name.startswith("pm_"):
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
        if name.startswith("pm_"):
            existing = next((x for x in db.list_collection(name) if x.get("id") == iid), None)
            if existing:
                if existing.get("createdBy") is not None:
                    item["createdBy"] = existing.get("createdBy")
                if existing.get("createdById") is not None:
                    item["createdById"] = existing.get("createdById")
        # Preserve server-trusted ownership on staff-owned records (a manager edit/approve
        # must not be able to rewrite who a claim/travel/exit belongs to).
        if name in ("claims", "travel", "payments", "acks"):
            existing = next((x for x in db.list_collection(name) if x.get("id") == iid), None)
            if existing:
                item["empId"] = existing.get("empId", item.get("empId"))
                if existing.get("name"):
                    item["name"] = existing.get("name")
        return self._json({"ok": True, "item": db.put_collection_item(name, item)})

    def _coll_delete(self, u, name, iid):
        if name not in self.COLLECTIONS or not iid:
            return self._err("Unknown item.", 404)
        if name in self.PAYROLL_ADMIN and self._level_rank(self._caller_level(u)) < self._level_rank("editor"):
            return self._err("Payroll changes require Editor level or above.", 403)
        db.delete_collection_item(name, iid)
        return self._json({"ok": True})


def main():
    db.init_db()
    _load_sessions()
    seeded = False
    att_added = 0
    # Fresh deploy on a host without a persistent disk (e.g. Render free): start
    # clean with ONLY the admin account so Microsoft 365 sign-in + "Sync from
    # Microsoft 365" work right away, instead of loading demo data.
    if os.environ.get("TK_BOOTSTRAP_ADMIN") and not db.list_employees():
        admin_email = os.environ.get("TK_ADMIN_EMAIL", "tony.nguyen@humiley.com")
        db.create_employee({
            "id": "HML-001", "name": os.environ.get("TK_ADMIN_NAME", "Tony Nguyen"),
            "email": admin_email, "ini": "TN", "clr": "#205090", "dept": "",
            "title": "Managing Director", "role": "manager", "level": "admin",
            "status": "Active", "zone": "HQ", "annualTotal": 12, "sickTotal": 30,
        })
        db.set_setting("seed_disabled", "1")
        print("  Bootstrapped clean DB with admin: %s" % admin_email)
    if os.environ.get("TK_ALLOW_SEED") and not db.get_setting("seed_disabled"):
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
