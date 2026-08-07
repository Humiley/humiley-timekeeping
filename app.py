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
import html as _h
import json
import threading
from datetime import datetime, timedelta
import os
import re
import secrets
import time
import urllib.request
import urllib.error
import urllib.parse
import io
import sys
import collections
import calendar
import traceback
from tkutil import (_money_vnd, _now_iso, _vn_fold, _iso_minus, _einv_num, _einv_xml_num,   # pure leaf utilities (extracted from this file)
                    _appr_state_of, _appr_epoch, _claim_items, _claim_rollup)
from einv import (_einv_safe_xml, _zip_read_bounded, _einv_parse_xml, _einv_from_zip, _einv_all_from_zip, _inv_ident, _inv_ident_str, _einv_parse_text, _pdf_engine_ok, _einv_pdf_items)   # e-invoice parsers (extracted)
from ratelimit import _rate_allow, _RATE, _RATE_LOCK   # in-process request rate limiter (extracted); _RATE/_RATE_LOCK re-exported (same objects) so callers/tests keep the app.* surface
import overtime          # Labour Code Art. 98/106/107 overtime rates, night premium and caps (pure)
import leave_entitlement  # Labour Code Art. 113/114 annual-leave entitlement + Decree 145 proration (pure)
import contracts         # Labour Code Art. 20 contract terms, expiry and the renewal limit (pure)
import certificates      # OSH Law Art. 21 health checks + Decree 44/2016 safety training (pure)
import settlement        # Labour Code Art. 46/47/48 + Art. 113(4) final settlement (pure)
import hashlib
import zipfile
import xml.etree.ElementTree as ET
import unicodedata
from html import escape as _hesc
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
# Secret shared with the Procurement app (an app OF this portal). The portal mints a short-lived
# signed token so a signed-in user opens Procurement with NO second login (like HR/CRM).
PROCUREMENT_SSO_SECRET = os.environ.get("TK_SSO_SECRET", "")

# In-memory sessions: token -> {emp_id, role, expires}. Long-lived + sliding so a signed-in user
# never sees the login screen again (until they sign out): the token is stored in localStorage on
# the client and its expiry is pushed forward on every use.
SESSIONS = {}
SESSION_TTL = 30 * 24 * 60 * 60   # 30 days


def _tok_hash(token):
    """Sessions are keyed by sha256(token), NEVER the raw token — so one read of the persisted
    _sessions blob (or a leaked DB file) can't be replayed into live access for the whole company.
    The client keeps the raw token; the server only ever stores + compares its hash."""
    return hashlib.sha256((token or "").encode("utf-8")).hexdigest()

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
        migrated = 0
        for tok, ses in (data or {}).items():
            if not (isinstance(ses, dict) and ses.get("expires", 0) > now):
                continue
            # Migrate legacy RAW-token keys (from before token hashing) to sha256, so existing
            # sessions survive the upgrade WITHOUT bouncing everyone to the login screen. A stored key
            # that isn't a 64-char hex digest is a raw token → re-key it to its hash (the client's raw
            # token then hashes to the same key on the next request).
            if len(tok) == 64 and all(c in "0123456789abcdef" for c in tok):
                SESSIONS[tok] = ses
            else:
                SESSIONS[_tok_hash(tok)] = ses
                migrated += 1
        if migrated:
            _persist_sessions()   # write the blob back with hashed keys
        print(f"[sessions] restored {len(SESSIONS)} active session(s)"
              + (f", migrated {migrated} to hashed keys" if migrated else ""), flush=True)
    except Exception as e:
        # Never fail the boot over this — but say so loudly: a silent empty restore means every
        # user is bounced to sign-in (the "signed in but must re-login in the morning" symptom).
        print(f"[sessions] RESTORE FAILED — all users must re-authenticate: {e}", flush=True)


def new_session(emp_id, role):
    token = secrets.token_urlsafe(32)
    SESSIONS[_tok_hash(token)] = {"emp_id": emp_id, "role": role, "expires": time.time() + SESSION_TTL}
    _persist_sessions()
    return token   # the RAW token goes to the client; only its hash is stored server-side


def session_user(token):
    key = _tok_hash(token)
    s = SESSIONS.get(key)
    now = time.time()
    if not s or s["expires"] < now:
        SESSIONS.pop(key, None)
        return None
    # Sliding expiration: extend on use so an active user's session never lapses. Persist only when
    # it moves by more than an hour to avoid a DB write on every request.
    new_exp = now + SESSION_TTL
    if new_exp - s.get("expires", 0) > 3600:
        s["expires"] = new_exp
        _persist_sessions()
    emp = db.get_employee(s["emp_id"]) if s["emp_id"] else None
    if emp:
        # Deactivated (left/terminated) employees lose access IMMEDIATELY — a live session must not
        # survive being set Inactive. Protected super-admins are exempt so a mistaken deactivation
        # can never lock the whole company out.
        if (emp.get("status") or "Active").strip().lower() == "inactive" and (emp.get("email") or "").lower() not in Handler.ADMIN_EMAILS:
            SESSIONS.pop(key, None)
            _persist_sessions()
            return None
        # The DB row is authoritative — a demoted manager must not keep manager rights
        # for the remainder of a 30-day sliding session. Session role is only a fallback.
        emp["role"] = emp.get("role") or s["role"]
    return emp


def _app_version():
    """Version marker for auto-update: the mtime of the served HTML, which changes on every
    deploy (git pull rewrites the file). The client reloads the PWA when this changes."""
    try:
        return str(int(os.path.getmtime(os.path.join(TEMPLATE_DIR, "index.html"))))
    except OSError:
        return "0"


# --- lightweight error tracking + alerting (no external service required) --------------------
# The app previously had no structured error capture: an unhandled exception in a request just
# printed a stack trace to stderr and reset the connection. This keeps a bounded ring buffer of
# recent errors (reviewable by an admin at /api/admin/errors), writes one structured JSON line per
# error to stderr (so `docker logs` / any log shipper can pick them up), and — if TK_ALERT_WEBHOOK
# is set — fires a Teams/Slack-compatible alert. Health is exposed at /api/health for uptime probes.
_STARTED_AT = time.time()
_ERR_LOG = collections.deque(maxlen=200)   # newest last; bounded so it can never grow unboundedly


def _alert_webhook(text):
    """Fire-and-forget alert to a Teams/Slack-style incoming webhook (never blocks the response)."""
    url = os.environ.get("TK_ALERT_WEBHOOK")
    if not url:
        return

    def _post():
        try:
            data = json.dumps({"text": text}).encode("utf-8")
            req = urllib.request.Request(url, data=data, headers={"Content-Type": "application/json"})
            urllib.request.urlopen(req, timeout=6).read()
        except Exception:
            pass   # alerting must never itself raise

    try:
        threading.Thread(target=_post, daemon=True).start()
    except Exception:
        pass


# ── Readiness probe ───────────────────────────────────────────────────────────
# /api/health gates the container healthcheck AND Caddy's `depends_on: service_healthy`, so it has to
# prove the app can actually SERVE — not merely that SQLite answers SELECT 1 (which succeeds against an
# empty file with no tables at all). It checks the HTML shell is present and whole, and that the DB is
# usable (core tables exist and a real read path answers).
#
# DELIBERATELY CONSERVATIVE: the same Caddy fronts BOTH the portal and /procurement, so a false
# "unhealthy" would take the edge down for both apps. Only unambiguously-broken states fail — a missing
# or truncated shell, a missing core table, an unusable DB. Anything softer stays "ok".
#
# Kept cheap: it is an unauthenticated, un-rate-limited GET polled every 30s by Docker and by external
# monitors. The shell check is one stat() in steady state, the DB half is ~1ms, and the whole result is
# memoised for a few seconds so a probe flood can't amplify. READ-ONLY — it never writes.
_HEALTH_CORE_TABLES = ("employees", "attendance", "leave", "settings", "collections")
_SHELL_MIN_BYTES = 100_000        # the real shell is ~2 MB; below this it is truncated (same floor as tests/test_shell.py)
_HEALTH_TTL = 5.0                 # seconds a probe result is reused
_HEALTH_CACHE = {"until": 0.0, "res": None}
_SHELL_CACHE = {"sig": None, "ok": False}
_HEALTH_STATE = {"ok": True}      # last reported state — log on TRANSITION only, never every poll


def _shell_ok():
    """True when templates/index.html is readable and looks whole: a size floor plus the closing
    </html> in the tail. Memoised on (size, mtime), so steady state is a single stat()."""
    path = os.path.join(os.path.dirname(os.path.abspath(__file__)), "templates", "index.html")
    try:
        st = os.stat(path)
    except OSError:
        _SHELL_CACHE["sig"], _SHELL_CACHE["ok"] = None, False
        return False
    sig = (st.st_size, st.st_mtime)
    if _SHELL_CACHE["sig"] == sig:
        return _SHELL_CACHE["ok"]
    ok = st.st_size >= _SHELL_MIN_BYTES
    if ok:
        try:
            with open(path, "rb") as f:                 # only re-read when the file actually changed
                f.seek(max(0, st.st_size - 256))
                ok = b"</html>" in f.read()
        except OSError:
            ok = False
    _SHELL_CACHE["sig"], _SHELL_CACHE["ok"] = sig, ok
    return ok


def _health_probe():
    """{ok, db, shell, detail} — the real readiness answer, memoised for _HEALTH_TTL seconds."""
    now = time.time()
    if _HEALTH_CACHE["res"] is not None and now < _HEALTH_CACHE["until"]:
        return _HEALTH_CACHE["res"]
    detail = ""
    shell = _shell_ok()
    if not shell:
        detail = "app shell missing or truncated"
    db_ok = True
    try:
        c = db.get_conn()
        try:
            have = {r[0] for r in c.execute(
                "SELECT name FROM sqlite_master WHERE type='table'").fetchall()}
            missing = [t for t in _HEALTH_CORE_TABLES if t not in have]
            if missing:
                db_ok = False
                detail = detail or ("core table(s) missing: " + ", ".join(missing))
            else:
                c.execute("SELECT id FROM employees LIMIT 1").fetchone()   # a real read path, not SELECT 1
        finally:
            c.close()
    except Exception as e:
        db_ok = False
        detail = detail or ("database unusable: " + type(e).__name__)
    res = {"ok": bool(db_ok and shell), "db": db_ok, "shell": shell, "detail": detail}
    _HEALTH_CACHE["res"], _HEALTH_CACHE["until"] = res, now + _HEALTH_TTL
    # Log only when readiness CHANGES — a degraded app polled every 30s must not spam the log/webhook.
    if res["ok"] != _HEALTH_STATE["ok"]:
        _HEALTH_STATE["ok"] = res["ok"]
        try:
            if res["ok"]:
                print("  health: READY again")
            else:
                print("  \033[1;31m✖ health: NOT READY\033[0m — %s" % (detail or "unknown"))
                _alert_webhook("Humiley Portal is NOT READY", detail or "health probe failed")
        except Exception:
            pass
    return res


# ── Approval-lifecycle EMAIL (branded, Graph app-only sendMail) ────────────────
# Emails the right people at each step of the 3-level approval flow. Decisions are still made IN THE
# PORTAL with an e-signature (21 CFR Part 11) — the email carries the request detail + a deep-link, never
# a one-click approve token (that was retired because a leaked link allowed unsigned self-approval).
# Sender is picked by department: HR (leave/PADR) → hr@, Finance (claims/travel/payments/payroll) →
# finance@, Procurement → procurement@. Needs Graph Mail.Send application consent; degrades gracefully.
_APPR_EMAIL_HEALTH = {"at": "", "ok": 0, "failed": 0, "lastError": ""}


def _portal_base():
    return "https://" + (os.environ.get("PORTAL_DOMAIN") or "portal.humiley.com").strip().rstrip("/")


def _appr_email_sender(coll):
    """Department mailbox that SENDS (and is CC'd on) a request's approval emails."""
    hr = (db.get_setting("portal_apprSenderHr", "") or "").strip() or "hr@humiley.com"
    fin = (db.get_setting("portal_apprSenderFinance", "") or "").strip() or "finance@humiley.com"
    proc = (db.get_setting("portal_apprSenderProc", "") or "").strip() or "procurement@humiley.com"
    c = str(coll or "")
    if c in ("claims", "travel", "payments", "payroll"):
        return fin
    if c.startswith("proc") or c.startswith("pr_") or c.startswith("po_"):
        return proc
    return hr   # leave, padr, hr, and anything else


# _money_vnd → tkutil.py (extracted)


def _graph_send_mail(sender, to, subject, html, cc=None):
    """App-only sendMail as `sender`. Fire-and-forget (own thread) so it never blocks the approval
       response; records health in _APPR_EMAIL_HEALTH so a missing Mail.Send consent is visible."""
    to = [a for a in (to or []) if a]
    if not sender or not to:
        return False

    def _send():
        try:
            msg = {"message": {"subject": subject,
                               "body": {"contentType": "HTML", "content": html},
                               "toRecipients": [{"emailAddress": {"address": a}} for a in to],
                               "ccRecipients": [{"emailAddress": {"address": a}} for a in (cc or [])]},
                   "saveToSentItems": True}
            url = "https://graph.microsoft.com/v1.0/users/" + urllib.parse.quote(sender) + "/sendMail"
            body = json.dumps(msg).encode("utf-8")

            def _post(tok):
                req = urllib.request.Request(url, data=body,
                                             headers={"Authorization": "Bearer " + tok,
                                                      "Content-Type": "application/json"})
                urllib.request.urlopen(req, timeout=15).read()

            try:
                _post(_graph_app_token())
            except urllib.error.HTTPError as he:
                # A just-granted Mail.Send consent is NOT in the cached app token (minted before consent),
                # so Graph returns 401/403. Discard the stale token, mint a fresh one, and retry ONCE —
                # this makes a new consent take effect immediately, with no app restart.
                if he.code in (401, 403):
                    _post(_graph_app_token(force=True))
                else:
                    raise
            _APPR_EMAIL_HEALTH.update({"at": _now_iso(), "ok": _APPR_EMAIL_HEALTH["ok"] + 1, "lastError": ""})
        except Exception as e:
            _APPR_EMAIL_HEALTH.update({"at": _now_iso(), "failed": _APPR_EMAIL_HEALTH["failed"] + 1,
                                       "lastError": _graph_err_text(e)})
    try:
        threading.Thread(target=_send, daemon=True).start()
    except Exception:
        pass
    return True


def _appr_email_html(title, status, intro, rows, cta_label, cta_url):
    NAVY = "#205090"; INK = "#1F2937"; MUT = "#5C6470"; LINE = "#e3e8f0"; BG = "#f0f2f8"
    scolor = {"Approved": "#00B060", "Reviewed": "#205090", "Rejected": "#C0392B", "Paid": "#008548",
              "Submitted": "#8a6d1f"}.get(str(status), "#205090")

    def esc(v):
        return _hesc("" if v is None else str(v))
    tr = ""
    for k, v in rows:
        tr += ("<tr><td style='padding:7px 0;color:" + MUT + ";font-size:13px;width:150px;vertical-align:top'>" + esc(k) +
               "</td><td style='padding:7px 0;color:" + INK + ";font-size:13px;font-weight:600'>" + esc(v) + "</td></tr>")
    return (
        "<div style='margin:0;padding:24px;background:" + BG + ";font-family:Segoe UI,Roboto,Helvetica,Arial,sans-serif'>"
        "<div style='max-width:600px;margin:0 auto;background:#fff;border-radius:14px;overflow:hidden;border:1px solid " + LINE + "'>"
        "<div style='background:" + NAVY + ";padding:18px 24px;color:#fff'>"
        "<img src='" + _portal_base() + "/static/brand/Humiley_Logo_White.png' alt='Humiley' height='30' "
        "style='height:30px;width:auto;display:block;border:0;margin:0 0 6px'>"
        "<div style='font-size:12px;opacity:.85'>Creating Sustainable Value</div></div>"
        "<div style='padding:24px'>"
        "<span style='display:inline-block;background:" + scolor + "22;color:" + scolor + ";font-size:11px;font-weight:700;padding:4px 12px;border-radius:20px;letter-spacing:.5px'>" + esc(str(status).upper()) + "</span>"
        "<h1 style='font-size:19px;color:" + INK + ";margin:14px 0 6px'>" + esc(title) + "</h1>"
        "<p style='font-size:14px;color:" + MUT + ";line-height:1.6;margin:0 0 18px'>" + esc(intro) + "</p>"
        "<table style='width:100%;border-collapse:collapse;border-top:1px solid " + LINE + ";border-bottom:1px solid " + LINE + ";margin:0 0 22px'>" + tr + "</table>"
        "<a href='" + esc(cta_url) + "' style='display:inline-block;background:" + NAVY + ";color:#fff;text-decoration:none;font-size:14px;font-weight:600;padding:12px 26px;border-radius:9px'>" + esc(cta_label) + " &rarr;</a>"
        "<p style='font-size:12px;color:" + MUT + ";margin:20px 0 0;line-height:1.6'>Approvals are made in the portal with your e-signature (21 CFR Part 11). This is an automated message — please do not reply.</p>"
        "</div></div>"
        "<div style='max-width:600px;margin:10px auto 0;text-align:center;font-size:11px;color:" + MUT + "'>&copy; Humiley Việt Nam &middot; portal.humiley.com</div></div>"
    )


_APPR_EVENT = {"reviewed": "reviewed", "approved": "approved", "rejected": "rejected", "paid": "paid"}
# The effective defaults the config GET substitutes for these keys — the SAVE side must compare against the
# SAME defaults, else a manager's unchanged (echoed-default) value looks like a change and trips the admin gate.
_APPR_SETTING_DEFAULTS = {"apprEmail": "1", "apprSenderHr": "hr@humiley.com",
                          "apprSenderFinance": "finance@humiley.com", "apprSenderProc": "procurement@humiley.com",
                          "apprReminders": "1", "apprReminderDays": "2",
                          "apprEscalateDays": "0", "apprEscalateTo": "",
                          "digestEnabled": "0", "digestDay": "0", "digestLeadTo": "",
                          "tkNudges": "0", "tkCheckinHour": "10", "tkCheckoutHour": "19",
                          "monthlyReports": "0", "monthlyDay": "1", "monthlyTo": "",
                          "payerSeparation": "1",   # require a 2nd Editor/Admin to pay a request they approved (disbursement SoD)
                          # Named authorised payers (comma/newline separated emails). Releasing money is a
                          # NAMED duty, not a side effect of holding an access level: with this list set,
                          # only these people can mark a request paid, whatever their level — and everyone
                          # else with Editor/Admin loses that one power while keeping the rest.
                          # The DEFAULT IS DELIBERATELY BLANK = "any Editor/Admin", the pre-existing
                          # behaviour. Never bake real names into the authorization path: a shipped default
                          # would lock every other install out of paying anything (the test suite caught
                          # exactly that). The company's actual payers are SEEDED into the database once at
                          # first boot — see _seed_default_payers — and are editable from then on.
                          # The hard rules always still apply on top: never your own request, and never one
                          # you approved (unless payerSeparation is off).
                          "apprPayers": "",
                          # Who is HR (comma/newline separated emails). Publishing a company document
                          # commits everyone to signing it and starts chasing them, so it is a NAMED
                          # duty like paying — it belongs to the people who actually run HR, not to
                          # whoever happens to sit high enough in the approval chain. Requiring an
                          # approval LEVEL for it was the wrong axis: it locked out the HR officer who
                          # writes the policies and let in a site manager who does not.
                          # DEFAULT BLANK on purpose = fall back to Approver (Management) or above,
                          # so an install that never sets this keeps working. Never bake real names in
                          # here — a shipped default would grant strangers HR on every other install.
                          # An admin can always publish, listed or not, so nobody is ever locked out.
                          "hrAdmins": "",
                          # Art. 107(3): 300 overtime hours a year instead of 200, but only for the
                          # industries the article lists and only after notifying the labour
                          # authority. Blank = the ordinary 200-hour ceiling, which is the answer for
                          # every company that has not made and recorded that decision.
                          "otAnnualCap": ""}
_APPR_REMIND_LOCK = threading.Lock()

# Seeded ONCE into the DB on first boot (not used as a code default — see the note above). Clearing the
# list in the UI afterwards is honoured: the seed marker stops it from being re-applied.
_APPR_PAYERS_SEED = "tony.nguyen@humiley.com,nancy.duong@humiley.com"


def _seed_default_payers():
    """Write the company's authorised payers once, on an install that has never had the setting."""
    try:
        if db.get_setting("portal_apprPayersSeeded", ""):
            return
        if not (db.get_setting("portal_apprPayers", "") or "").strip():
            db.set_setting("portal_apprPayers", _APPR_PAYERS_SEED)
        db.set_setting("portal_apprPayersSeeded", "1")
    except Exception:
        pass


def _payer_emails():
    """The configured authorised payers, lower-cased. Empty set = no allow-list, so any Editor/Admin
       may pay (the historical rule). Accepts commas, semicolons or whitespace as separators."""
    raw = db.get_setting("portal_apprPayers", "") or ""
    return {e.strip().lower() for e in re.split(r"[,;\s]+", str(raw)) if e.strip()}


def _hr_admin_emails():
    """The people named as HR, lower-cased. Empty set = nobody named, so the fallback level rule
       applies. Same separators as the payer list."""
    raw = db.get_setting("portal_hrAdmins", "") or ""
    return {e.strip().lower() for e in re.split(r"[,;\s]+", str(raw)) if e.strip()}

# ── Idempotency for financial submits ─────────────────────────────────────────────────────────
# A retried identical financial POST over a flaky field connection must not create a DUPLICATE
# claim/payment/travel (which could then be approved and paid twice). Keyed by an explicit client
# Idempotency-Key header, or a hash of (owner, collection, payload). A hit within the window returns
# the record the first attempt already created instead of a second one. In-process + short window
# (single-process server), so restart-loss is irrelevant — mirrors the rate-limiter's pattern.
_IDEM = {}                        # key -> (created_item_snapshot, ts)
_IDEM_LOCK = threading.Lock()
_IDEM_WINDOW = 60                 # seconds — long enough to swallow a transport retry, short enough that
#                                   two deliberately-identical submits are very unlikely to collide. A
#                                   client that wants a hard guarantee sends an explicit Idempotency-Key.
_IDEM_COLLS = ("claims", "travel", "payments")


def _idem_key(uid, name, item, header_key):
    if header_key:
        return "%s|%s|k:%s" % (uid, name, str(header_key)[:120])
    payload = {k: v for k, v in item.items() if k not in ("token", "id")}   # token is server-added + random
    blob = json.dumps(payload, sort_keys=True, default=str)
    return "%s|%s|h:%s" % (uid, name, hashlib.sha256(blob.encode("utf-8", "replace")).hexdigest())


# ── Lightweight request telemetry ─────────────────────────────────────────────────────────────
# The app was metric-blind (no latency / error-rate / per-endpoint counts). Aggregate them in
# process and expose at /api/admin/metrics. Path ids are collapsed to ":id" so cardinality is bound.
_METRICS = {}                      # "METHOD /route" -> {"n","err","ms","max"}
_METRICS_LOCK = threading.Lock()
_ID_SEG_RE = re.compile(
    r"^\d+$"                          # numeric ids (leave rows)
    r"|^[0-9a-fA-F]{6,}$"             # bare hex ids
    r"|^[0-9a-fA-F-]{16,}$"           # uuid / long hex-dash
    r"|^[A-Za-z]{2,6}-[A-Za-z0-9]{3,}$"   # app item + employee ids: pay-1a2b3c4d, HML-001 (the real id shape)
    r"|^[A-Za-z0-9_-]{20,}$")         # long opaque tokens

# Persist unhandled errors to a JSONL in the DB volume so the in-memory ring buffer isn't lost on
# every auto-deploy (exactly when you're investigating a deploy regression). Rotated at ~2 MB.
_ERR_FILE = os.path.join(os.path.dirname(os.path.abspath(db.DB_PATH)), "portal_errors.jsonl")
_ERR_FILE_LOCK = threading.Lock()


def _metrics_route(method, path):
    out = []
    for seg in (path or "/").split("?")[0].split("/"):
        out.append(":id" if seg and _ID_SEG_RE.match(seg) else seg)
    return method + " " + ("/".join(out) or "/")


def _metrics_record(route, status, ms):
    try:
        with _METRICS_LOCK:
            m = _METRICS.get(route)
            if m is None:
                if len(_METRICS) >= 800:          # bound cardinality — ignore brand-new routes past the cap
                    return
                m = _METRICS[route] = {"n": 0, "err": 0, "ms": 0.0, "max": 0.0}
            m["n"] += 1
            if status and status >= 500:
                m["err"] += 1
            m["ms"] += ms
            if ms > m["max"]:
                m["max"] = ms
    except Exception:
        pass


def _appr_notify(coll, rec, event, actor_name="", reminder=False, age_days=0, escalate_to=None):
    """Send the branded lifecycle email for ONE request. event ∈ submitted/reviewed/approved/rejected/paid.
       reminder=True reframes it as an overdue nudge to whoever must act next; escalate_to (an email)
       additionally CCs a higher authority and re-labels it an escalation.
       Best-effort; gated by the portal_apprEmail setting (default on). Never raises."""
    try:
        if (db.get_setting("portal_apprEmail", "1") or "1").lower() not in ("1", "true", "on", "yes"):
            return
        sender = _appr_email_sender(coll)
        emp = db.get_employee(rec.get("emp_id") or rec.get("empId")) if (rec.get("emp_id") or rec.get("empId")) else None
        req_email = (emp or {}).get("email") or rec.get("email") or ""
        req_name = (emp or {}).get("name") or rec.get("name") or "the requester"
        mgr_email = (emp or {}).get("managerEmail") or ""
        label = {"claims": "Expense claim", "travel": "Travel request", "payments": "Payment request",
                 "leave": "Leave request", "payroll": "Payroll"}.get(coll, "Request")
        ref = rec.get("reqNo") or rec.get("title") or rec.get("dest") or (("#" + str(rec.get("id"))) if rec.get("id") else "—")
        status = rec.get("status") or (event.title())
        rows = [("Type", label), ("Reference", ref), ("Requester", req_name)]
        if coll == "leave":
            rows.append(("Dates", (rec.get("startDate", "") + " → " + rec.get("endDate", "")).strip(" →")))
            if rec.get("leaveType") or rec.get("type"):
                rows.append(("Leave type", rec.get("leaveType") or rec.get("type")))
        if coll == "payments":
            # Same beneficiary block the requester filled in and the request PDF prints, so the decision
            # email matches the request form field-for-field. Blank fields are skipped (cash requests).
            for _lbl, _k in (("Company", "payeeCompany"), ("Tax code (MST)", "payeeMst"), ("Bank", "bankName"),
                             ("Account number", "bankAcc"), ("Account holder", "bankHolder"), ("Branch", "bankBranch")):
                if str(rec.get(_k) or "").strip():
                    rows.append((_lbl, str(rec[_k]).strip()))
        amt = rec.get("amount") or rec.get("total")
        if amt:
            rows.append(("Amount", _money_vnd(amt)))
        rows.append(("Current status", status))
        low = label.lower()
        table = {
            "submitted": (req_name + " submitted a " + low + " that needs your review.",
                          [mgr_email], [sender], "Review this request", label + " from " + req_name + " — needs review"),
            "reviewed": (label + " from " + req_name + " was reviewed by " + (actor_name or "a manager") + " and now needs final approval.",
                         [sender], [req_email, mgr_email], "Give final approval", label + " from " + req_name + " — awaiting approval"),
            "approved": ("Your " + low + " has been approved by " + (actor_name or "management") + ".",
                         [req_email], [mgr_email, sender], "View in the portal", label + " from " + req_name + " — approved"),
            "rejected": ("Your " + low + " was rejected by " + (actor_name or "a manager") + ". Open the portal for details.",
                         [req_email], [mgr_email], "View in the portal", label + " from " + req_name + " — rejected"),
            "paid": ("Your " + low + " has been paid.",
                     [req_email], [sender], "View in the portal", label + " from " + req_name + " — paid"),
        }.get(event)
        if not table:
            return
        intro, to, cc, cta, subject = table
        if reminder:
            wait = str(int(age_days)) + (" day" if int(age_days) == 1 else " days")
            need = "your review" if event == "submitted" else "final approval"
            if escalate_to:
                intro = ("Escalation — this " + low + " from " + req_name + " has been waiting " + wait +
                         " for " + need + " and is now overdue. Please make sure it is actioned in the portal.")
                subject = "Escalated · " + subject
                cc = list(cc) + [escalate_to]
            else:
                intro = ("Reminder — this " + low + " from " + req_name + " has been waiting " + wait +
                         " for " + need + ". Please action it in the portal.")
                subject = "Reminder · " + subject
        to = [x for x in to if x]
        if not to:
            to = [sender]
        cc = [x for x in cc if x and x not in to]
        html = _appr_email_html(subject, status, intro, rows, cta, _portal_base() + "/?inbox=1")
        _graph_send_mail(sender, to, "[Humiley] " + subject, html, cc)
    except Exception:
        pass


# _appr_state_of, _appr_epoch → tkutil.py (extracted)


def _appr_waiting_since(item, st):
    """When the request entered its CURRENT waiting state (review vs submit) — the clock for overdue."""
    sigs = item.get("signatures")
    if isinstance(sigs, str):                        # leave rows carry signatures as a raw JSON string (db.list_leave)
        try:
            sigs = json.loads(sigs or "[]")
        except Exception:
            sigs = []
    sigs = sigs if isinstance(sigs, list) else []
    if st == "review":
        for s in reversed(sigs):
            if str(s.get("setStatus") or "").lower() == "reviewed":
                t = _appr_epoch(s.get("ts"))
                if t:
                    return t
        t = _appr_epoch(item.get("reviewedOn"))
        if t:
            return t
    # 'created_at' is the leave table's snake_case submission column; the rest cover the JSON collections.
    for k in ("submittedOn", "createdOn", "createdAt", "created_at", "date", "reqDate", "startDate"):
        t = _appr_epoch(item.get(k))
        if t:
            return t
    if sigs:
        return _appr_epoch(sigs[0].get("ts"))
    return None


def _appr_reminders():
    """Scan pending 3-level requests and email a reminder to whoever must act next, once/day, once a
       request has waited ≥ portal_apprReminderDays (default 2). Dedup + age tracked in a settings blob
       so no request schema changes and leave (separate table) is covered too. Best-effort; never raises."""
    if not _APPR_REMIND_LOCK.acquire(blocking=False):
        return 0   # a sweep (6h scheduler vs a manual click) is already running — avoid the dedup-blob read/modify/write race
    try:
        if (db.get_setting("portal_apprReminders", "1") or "1").lower() not in ("1", "true", "on", "yes"):
            return 0
        if (db.get_setting("portal_apprEmail", "1") or "1").lower() not in ("1", "true", "on", "yes"):
            return 0
        try:
            days = max(1, int(db.get_setting("portal_apprReminderDays", "2") or "2"))
        except Exception:
            days = 2
        try:
            esc_days = int(db.get_setting("portal_apprEscalateDays", "0") or "0")   # 0 = escalation off
        except Exception:
            esc_days = 0
        esc_to = (db.get_setting("portal_apprEscalateTo", "") or "").strip()
        now = time.time()
        try:
            seen = json.loads(db.get_setting("_apprRemindedAt") or "{}")
        except Exception:
            seen = {}
        sent = 0

        def _due(key, since):
            if since is None or (now - since) < days * 86400:
                return False
            last = seen.get(key) or 0
            return not (last and (now - last) < 20 * 3600)   # at most ~once/day per request

        def _remind(coll, rec, st):
            since = _appr_waiting_since(rec, st)
            key = coll + ":" + str(rec.get("id"))
            if not _due(key, since):
                return 0
            age = int((now - since) // 86400)
            esc = esc_to if (esc_days > 0 and esc_to and age >= esc_days) else None   # escalate once past the higher threshold
            _appr_notify(coll, rec, "submitted" if st == "submit" else "reviewed", "",
                         reminder=True, age_days=age, escalate_to=esc)
            seen[key] = now
            return 1

        for coll in ("claims", "travel", "payments"):
            for item in db.list_collection(coll):
                status = _claim_rollup(item) if coll == "claims" else item.get("status")
                st = _appr_state_of(status)
                if st in ("submit", "review"):
                    sent += _remind(coll, item, st)
        try:
            for lv in (db.list_leave(status="pending") or []) + (db.list_leave(status="reviewed") or []):
                st = _appr_state_of(lv.get("status"))
                if st in ("submit", "review"):
                    sent += _remind("leave", lv, st)
        except Exception:
            pass
        try:
            seen = {k: v for k, v in seen.items() if (now - (v or 0)) < 30 * 86400}   # prune >30-day-old dedup keys
            db.set_setting("_apprRemindedAt", json.dumps(seen))
        except Exception:
            pass
        return sent
    except Exception:
        return 0
    finally:
        _APPR_REMIND_LOCK.release()


def _appr_reminder_scheduler():
    """Background thread: nudge overdue approvals every 6 h (the per-request once/day guard prevents spam)."""
    while True:
        time.sleep(6 * 3600)
        try:
            _appr_reminders()
        except Exception:
            pass


# ── Weekly leadership & manager digest ──────────────────────────────────────────────────────
# One email per manager on the configured weekday: what's awaiting their review, plus a company
# roll-up to leadership. Reuses the SAME pending-state machinery as the reminder engine so the two
# never disagree. Opt-in (off by default); best-effort; never raises into a request or the scheduler.
_DIGEST_LOCK = threading.Lock()
_DIGEST_HEALTH = {"at": "", "sent": 0, "lastError": ""}
_DIGEST_LABELS = {"claims": "Expense claim", "travel": "Travel request",
                  "payments": "Payment request", "leave": "Leave request"}


def _digest_enabled():
    return (db.get_setting("portal_digestEnabled", "0") or "0").lower() in ("1", "true", "on", "yes")


def _emp_name_by_email(email):
    if not email:
        return ""
    fn = getattr(db, "get_employee_by_email", None)
    if fn:
        try:
            e = fn(email)
            if e and e.get("name"):
                return e["name"]
        except Exception:
            pass
    return email


def _digest_gather():
    """Roll every pending 3-level request up by who must act next. Returns
       (managers, leadership, counts): managers = {mgrEmail: {"name":.., "rows":[row]}} (items in
       SUBMIT state, awaiting that manager's review); leadership = [row] (items in REVIEW state,
       awaiting the Director); counts = {await, review, overdue, valuePending}. Never raises."""
    now = time.time()
    try:
        days = max(1, int(db.get_setting("portal_apprReminderDays", "2") or "2"))
    except Exception:
        days = 2
    managers, leadership = {}, []
    counts = {"await": 0, "review": 0, "overdue": 0, "valuePending": 0.0}

    def _row(coll, item, st, emp):
        since = _appr_waiting_since(item, st)
        age = int((now - since) // 86400) if since else 0
        overdue = since is not None and (now - since) >= days * 86400
        ref = item.get("reqNo") or item.get("title") or item.get("dest") or (("#" + str(item.get("id"))) if item.get("id") else "—")
        amt = item.get("amount") or item.get("total") or 0
        try:
            counts["valuePending"] += float(str(amt).replace(",", "").replace(" ", "").replace("₫", "") or 0)
        except Exception:
            pass
        if overdue:
            counts["overdue"] += 1
        return {"label": _DIGEST_LABELS.get(coll, "Request"), "ref": ref,
                "requester": (emp or {}).get("name") or item.get("name") or "—",
                "amount": _money_vnd(amt) if amt else "", "age": age, "overdue": overdue}

    def _scan(coll, item, status):
        st = _appr_state_of(status)
        if st not in ("submit", "review"):
            return
        emp = None
        rid = item.get("emp_id") or item.get("empId")
        if rid:
            try:
                emp = db.get_employee(rid)
            except Exception:
                emp = None
        row = _row(coll, item, st, emp)
        if st == "submit":
            counts["await"] += 1
            mgr = (emp or {}).get("managerEmail") or ""
            if mgr:
                managers.setdefault(mgr, {"name": _emp_name_by_email(mgr), "rows": []})["rows"].append(row)
        else:
            counts["review"] += 1
            leadership.append(row)

    try:
        for coll in ("claims", "travel", "payments"):
            for item in db.list_collection(coll):
                _scan(coll, item, _claim_rollup(item) if coll == "claims" else item.get("status"))
    except Exception:
        pass
    try:
        for lv in (db.list_leave(status="pending") or []) + (db.list_leave(status="reviewed") or []):
            _scan("leave", lv, lv.get("status"))
    except Exception:
        pass
    return managers, leadership, counts


def _digest_html(title, intro, sections, summary):
    """Branded digest email: same navy header + real logo as the approval emails, then one table
       per section (heading + rows) and a summary strip. `sections` = [(heading, [row])]."""
    NAVY = "#205090"; INK = "#1F2937"; MUT = "#5C6470"; LINE = "#e3e8f0"; BG = "#f0f2f8"; EMER = "#00B060"

    def esc(v):
        return _hesc("" if v is None else str(v))
    body = ""
    for heading, rows in sections:
        body += ("<div style='font-size:12px;font-weight:700;color:" + NAVY + ";text-transform:uppercase;letter-spacing:.5px;margin:18px 0 6px'>"
                 + esc(heading) + " <span style='color:" + MUT + ";font-weight:600'>(" + str(len(rows)) + ")</span></div>")
        if not rows:
            body += "<div style='font-size:13px;color:" + MUT + "'>Nothing — all clear.</div>"
            continue
        body += "<table style='width:100%;border-collapse:collapse'>"
        for r in rows:
            flag = ("<span style='color:#C0392B;font-weight:700'>&#9888; " + str(r["age"]) + "d</span>") if r.get("overdue") else ("<span style='color:" + MUT + "'>" + str(r["age"]) + "d</span>")
            body += ("<tr>"
                     "<td style='padding:6px 0;border-top:1px solid " + LINE + ";font-size:13px;color:" + INK + ";font-weight:600'>" + esc(r["label"]) + " <span style='color:" + MUT + ";font-weight:400'>" + esc(r["ref"]) + "</span></td>"
                     "<td style='padding:6px 0;border-top:1px solid " + LINE + ";font-size:13px;color:" + MUT + "'>" + esc(r["requester"]) + "</td>"
                     "<td style='padding:6px 0;border-top:1px solid " + LINE + ";font-size:13px;color:" + INK + ";text-align:right'>" + esc(r["amount"]) + "</td>"
                     "<td style='padding:6px 0;border-top:1px solid " + LINE + ";font-size:12px;text-align:right;white-space:nowrap;padding-left:10px'>" + flag + "</td>"
                     "</tr>")
        body += "</table>"
    chips = ""
    for lbl, val in summary:
        chips += ("<span style='display:inline-block;background:#fff;border:1px solid " + LINE + ";border-radius:8px;padding:6px 12px;margin:0 6px 6px 0;font-size:12px;color:" + MUT + "'>"
                  + esc(lbl) + " <b style='color:" + NAVY + "'>" + esc(val) + "</b></span>")
    return (
        "<div style='margin:0;padding:24px;background:" + BG + ";font-family:Segoe UI,Roboto,Helvetica,Arial,sans-serif'>"
        "<div style='max-width:620px;margin:0 auto;background:#fff;border-radius:14px;overflow:hidden;border:1px solid " + LINE + "'>"
        "<div style='background:" + NAVY + ";padding:18px 24px;color:#fff'>"
        "<img src='" + _portal_base() + "/static/brand/Humiley_Logo_White.png' alt='Humiley' height='28' style='height:28px;width:auto;display:block;border:0;margin:0 0 6px'>"
        "<div style='font-size:12px;opacity:.85'>Weekly digest &middot; Creating Sustainable Value</div></div>"
        "<div style='padding:22px 24px'>"
        "<h1 style='font-size:19px;color:" + INK + ";margin:0 0 6px'>" + esc(title) + "</h1>"
        "<p style='font-size:14px;color:" + MUT + ";line-height:1.6;margin:0 0 6px'>" + esc(intro) + "</p>"
        "<div style='margin:12px 0 4px'>" + chips + "</div>"
        + body +
        "<a href='" + esc(_portal_base()) + "/?inbox=1' style='display:inline-block;margin-top:20px;background:" + NAVY + ";color:#fff;text-decoration:none;font-size:14px;font-weight:600;padding:11px 24px;border-radius:9px'>Open the portal &rarr;</a>"
        "<p style='font-size:12px;color:" + MUT + ";margin:18px 0 0;line-height:1.6'>Decisions are made in the portal with your e-signature. Automated weekly summary — please do not reply. Turn off in Access &amp; Permissions &rarr; System Integrations.</p>"
        "</div></div>"
        "<div style='max-width:620px;margin:10px auto 0;text-align:center;font-size:11px;color:" + MUT + "'>&copy; Humiley Vi&#7879;t Nam &middot; portal.humiley.com</div></div>")


def _digest_send(preview_to=None):
    """Scheduled: email each manager their awaiting-review list, plus a company roll-up to the
       leadership address. preview_to: send that ONE address the full company preview instead.
       Gated by portal_digestEnabled AND portal_apprEmail. Returns number of emails sent."""
    try:
        if not preview_to and not _digest_enabled():
            return 0
        if (db.get_setting("portal_apprEmail", "1") or "1").lower() not in ("1", "true", "on", "yes"):
            return 0
        managers, leadership, counts = _digest_gather()
        sender = _appr_email_sender("leave")   # the HR mailbox is the neutral cross-company ops sender
        summary = [("Awaiting review", str(counts["await"])), ("Awaiting approval", str(counts["review"])),
                   ("Overdue", str(counts["overdue"])), ("Pending value", _money_vnd(counts["valuePending"]))]
        sent = 0
        if preview_to:
            html = _digest_html("Company approvals — weekly summary (preview)",
                                "This is a preview of the weekly digest sent to leadership. It shows everything currently in flight.",
                                [("Awaiting final approval (with Director)", leadership)], summary)
            if _graph_send_mail(sender, [preview_to], "[Humiley] Weekly digest — preview", html):
                sent = 1
            _DIGEST_HEALTH.update({"at": _now_iso(), "sent": _DIGEST_HEALTH["sent"] + sent})
            return sent
        for mgr_email, data in managers.items():
            html = _digest_html("Your team — awaiting your review",
                                "These requests from your team are waiting for you. Overdue items are flagged.",
                                [("Awaiting your review", data["rows"])],
                                [("Awaiting you", str(len(data["rows"]))),
                                 ("Overdue", str(sum(1 for r in data["rows"] if r["overdue"])))])
            if _graph_send_mail(sender, [mgr_email], "[Humiley] Weekly digest — " + str(len(data["rows"])) + " awaiting your review", html):
                sent += 1
        lead_to = (db.get_setting("portal_digestLeadTo", "") or "").strip()
        if lead_to:
            html = _digest_html("Company approvals — weekly summary",
                                "Everything currently in the approval pipeline across the company.",
                                [("Awaiting final approval (with Director)", leadership)], summary)
            if _graph_send_mail(sender, [lead_to], "[Humiley] Weekly leadership digest", html):
                sent += 1
        _DIGEST_HEALTH.update({"at": _now_iso(), "sent": _DIGEST_HEALTH["sent"] + sent})
        return sent
    except Exception as e:
        _DIGEST_HEALTH.update({"at": _now_iso(), "lastError": str(e)[:200]})
        return 0


def _digest_scheduler():
    """Background thread: once a week on the configured weekday (VN morning), send the digest.
       Wakes hourly; a per-ISO-week dedup flag makes the actual send idempotent."""
    while True:
        time.sleep(3600)
        try:
            if not _digest_enabled():
                continue
            now_vn = datetime.utcnow() + timedelta(hours=7)   # Humiley operates on ICT (UTC+7)
            try:
                want_day = int(db.get_setting("portal_digestDay", "0") or "0")
            except Exception:
                want_day = 0
            if now_vn.weekday() != want_day or now_vn.hour < 7:
                continue
            wk = now_vn.strftime("%G-W%V")
            if (db.get_setting("_digestSentWeek", "") or "") == wk:
                continue
            with _DIGEST_LOCK:
                if (db.get_setting("_digestSentWeek", "") or "") == wk:
                    continue
                _digest_send()
                db.set_setting("_digestSentWeek", wk)
        except Exception:
            pass


# ── Timekeeping nudges ──────────────────────────────────────────────────────────────────────
# Web-push reminders on working days: a check-in nudge to active staff with no record yet, and a
# check-out nudge to anyone still clocked in. Opt-in (off by default); skips weekends, configured
# holidays, and staff on approved leave. Best-effort; never raises into a request or the scheduler.
_TK_NUDGE_LOCK = threading.Lock()


def _tk_push(emails, title, body, url="/", tag=""):
    """Fan a Web Push out to a set of employee emails. Best-effort; returns count of pushes sent."""
    if not _PUSH_OK:
        return 0
    emails = [str(e).lower() for e in emails if e]
    if not emails:
        return 0
    payload = {"title": title[:120], "body": body[:400], "url": url[:300], "tag": tag[:80]}
    sent = 0
    try:
        for endpoint, sub in db.push_subs_for(emails):
            if _web_push(endpoint, sub, payload):
                sent += 1
    except Exception:
        pass
    return sent


def _tk_is_workday(date_str):
    try:
        if datetime.strptime(date_str, "%Y-%m-%d").weekday() >= 5:   # Sat / Sun
            return False
    except Exception:
        return True
    try:
        hols = db.get_setting("portal_holidays") or []
        if any(isinstance(h, dict) and (h.get("date") or "")[:10] == date_str for h in hols):
            return False
    except Exception:
        pass
    return True


def _ot_holiday_set():
    """The public-holiday dates (YYYY-MM-DD) from the company register.

    Overtime on a public holiday is paid at 300% rather than 150% (Labour Code Art. 98(1)(c)), so
    this set is worth twice the hourly rate to the person who worked it. An unreadable register
    returns empty rather than raising: the pay is then understated and visible, not wrong and silent.
    """
    try:
        raw = db.get_setting("portal_holidays") or []
        if isinstance(raw, str):
            raw = json.loads(raw or "[]") or []
        return {str((h or {}).get("date") or (h or {}).get("d") or "")[:10]
                for h in raw if isinstance(h, dict)}
    except Exception:
        return set()


_OT_MON_SUN = re.compile(r"mon\s*-\s*sun|t2\s*-\s*cn", re.I)
_OT_MON_SAT = re.compile(r"mon\s*-\s*sat|t2\s*-\s*t7", re.I)


def _rest_weekdays_for(emp, schedules=None):
    """Which weekdays this person does NOT normally work — Python numbering, Monday 0 … Sunday 6.

    `employee.schedule` holds the NAME of a work-schedule pattern picked from the dropdown ("Factory
    Shift A"), not the pattern itself — so the days have to be read from the schedule that name
    points at. Matching the name directly against /mon.*sat/ finds nothing, which silently treated
    the whole factory as a Mon–Fri office and paid its Saturday overtime at the rest-day rate it had
    not earned. Falls back to Sat + Sun, the office pattern.
    """
    name = str((emp or {}).get("schedule") or "").strip()
    if not name:
        return (5, 6)
    days = ""
    for s in (schedules if schedules is not None else db.list_collection("schedules")):
        if str(s.get("name") or "").strip().lower() == name.lower():
            days = str(s.get("days") or "")
            break
    d = (days or name).replace("–", "-").replace("—", "-")
    if _OT_MON_SUN.search(d):
        return ()
    if _OT_MON_SAT.search(d):
        return (6,)
    return (5, 6)


def _ot_annual_cap():
    """Art. 107: 200 overtime hours a year, or 300 for the sectors listed in Art. 107(3).

    300 is not a default. It applies only to named industries and only on notification to the labour
    authority, so it has to be a decision somebody made and recorded in settings.
    """
    try:
        v = float(db.get_setting("portal_otAnnualCap") or 0)
    except (TypeError, ValueError):
        v = 0
    return v if v > 0 else overtime.CAP_YEAR_HOURS


def _tk_on_leave_today(today):
    out = set()
    try:
        for lv in db.list_leave() or []:
            if (str(lv.get("status") or "").lower() == "approved"
                    and (lv.get("startDate") or "")[:10] <= today <= (lv.get("endDate") or "9999")[:10]
                    and lv.get("emp_id")):
                out.add(lv.get("emp_id"))
    except Exception:
        pass
    return out


def _hrdoc_targets(doc, employees):
    """Who must sign this document. Mirrors the browser's _onbForMe exactly — if these two ever
    disagree, somebody is chased for a document they cannot see."""
    aud = str((doc or {}).get("audience") or "All")
    out = []
    for e in employees:
        if str(e.get("status") or "Active").lower() == "inactive":
            continue
        if aud == "All":
            out.append(e)
        elif aud == "Department" and str(e.get("dept") or "") == str(doc.get("dept") or ""):
            out.append(e)
        elif aud == "Selected" and e.get("id") in [x.strip() for x in str(doc.get("empIds") or "").split(",")]:
            out.append(e)
    return out


def _hrdoc_has_file(doc):
    """Whether there is actually something to read. A published record with no file is a title, and
    nobody can honestly sign for a title — so it is neither chased nor signable until HR uploads it."""
    return bool((doc or {}).get("file") or (doc or {}).get("fileUrl"))


def _hrdoc_due(doc, emp):
    """The date this person's signature is due, as YYYY-MM-DD, or "" when the document sets no
    deadline.

    Measured from the LATER of publication and the person's start date. A policy published in March
    is not overdue for somebody who joined in June — counting from publication would show every new
    hire as instantly delinquent, which is how a compliance report becomes noise nobody reads."""
    try:
        days = int(doc.get("dueDays") or 0)
    except Exception:
        days = 0
    if days <= 0:
        return ""
    pub = str(doc.get("effectiveFrom") or doc.get("ts") or "")[:10]
    if len(pub) != 10:
        # No publication date means we cannot say what the deadline is measured from. Falling through
        # to the join date would make the document overdue for every existing employee the moment it
        # appeared — a deadline invented out of nothing, then chased daily. Documents published
        # through _coll_add always carry `ts`; this covers anything written before that.
        return ""
    join = str((emp or {}).get("joinDate") or (emp or {}).get("onboardDate") or "")[:10]
    start = max([d for d in (pub, join) if len(d) == 10] or [""])
    if not start:
        return ""
    try:
        return (datetime.strptime(start, "%Y-%m-%d") + timedelta(days=days)).strftime("%Y-%m-%d")
    except Exception:
        return ""


def _hrdoc_outstanding(today=None):
    """Every (document, employee) pair still waiting for a signature, with its due date.

    One pass over both collections rather than a query per employee: this feeds the daily sweep and
    the compliance matrix, and on a 30-person company the whole thing is a few hundred pairs."""
    today = today or (datetime.utcnow() + timedelta(hours=7)).strftime("%Y-%m-%d")
    # A document with no file attached is excluded: chasing somebody daily to sign a record they
    # cannot open is how a compliance system teaches people to ignore it. HR sees those instead, on
    # the register, as the ones still needing a file.
    docs = [d for d in db.list_collection("hrdocs")
            if not d.get("archived") and _hrdoc_has_file(d)]
    if not docs:
        return []
    emps = db.list_employees()
    signed = set()
    for a in db.list_collection("hrdoc_acks"):
        signed.add((a.get("docId"), a.get("empId"), str(a.get("docVersion") or "")))
    out = []
    for d in docs:
        ver = str(d.get("version") or "")
        for e in _hrdoc_targets(d, emps):
            if (d.get("id"), e.get("id"), ver) in signed:
                continue
            due = _hrdoc_due(d, e)
            out.append({"doc": d, "emp": e, "due": due,
                        "overdue": bool(due and due < today)})
    return out


def _hrdoc_reminders(today=None):
    """Daily: remind people what they still owe a signature for, and tell a manager when it is late.

    Chasing by hand is what makes this decay in every company that tries it. Reminders go out once a
    day at most, and only to people who actually have something outstanding."""
    today = today or (datetime.utcnow() + timedelta(hours=7)).strftime("%Y-%m-%d")
    pend = _hrdoc_outstanding(today)
    if not pend:
        return 0
    by_emp, late_by_mgr = {}, {}
    for row in pend:
        e = row["emp"]
        by_emp.setdefault(e.get("id"), {"emp": e, "docs": [], "late": []})
        by_emp[e["id"]]["docs"].append(row)
        if row["overdue"]:
            by_emp[e["id"]]["late"].append(row)
            mgr = (e.get("managerEmail") or "").strip().lower()
            if mgr:
                late_by_mgr.setdefault(mgr, []).append(row)
    sent = 0
    for _eid, v in by_emp.items():
        em = (v["emp"].get("email") or "").strip().lower()
        if not em:
            continue
        n, late = len(v["docs"]), len(v["late"])
        title = ("%d document%s to sign" % (n, "" if n == 1 else "s")) if not late else \
                ("%d overdue — please sign" % late)
        body = "; ".join((r["doc"].get("title") or "") for r in v["docs"][:3])[:150]
        try:
            _tk_push([em], title, body, "/?tab=myonboarding", "hrdoc-" + today)
            sent += 1
        except Exception:
            pass
        try:
            _sender = _appr_email_sender("hrdocs")
            if _sender:
                _graph_send_mail(_sender, [em], "[Humiley] " + title,
                    "<p>These company documents are waiting for your signature:</p><ul>" +
                    "".join("<li>%s%s</li>" % (_h.escape(r["doc"].get("title") or ""),
                                               (" &mdash; due %s" % r["due"]) if r["due"] else "")
                            for r in v["docs"]) +
                    "</ul><p>Open <b>My Space &rarr; Onboarding</b> in the portal to read and sign them.</p>")
        except Exception:
            pass
    # The manager hears only about what is actually LATE — a manager copied on every routine
    # reminder stops reading them, and then the escalation is worth nothing.
    for mgr_email, rows in late_by_mgr.items():
        try:
            _sender = _appr_email_sender("hrdocs")
            if _sender:
                _graph_send_mail(_sender, [mgr_email],
                    "[Humiley] %d overdue document signature(s) in your team" % len(rows),
                    "<p>These are past their due date:</p><ul>" +
                    "".join("<li>%s &mdash; %s (due %s)</li>" % (_h.escape(r["emp"].get("name") or ""),
                                                                 _h.escape(r["doc"].get("title") or ""), r["due"])
                            for r in rows) + "</ul>")
        except Exception:
            pass
    return sent


def _tk_nudges(kind, today=None):
    """kind='checkin' → active staff with NO attendance record today; kind='checkout' → still clocked in.
       Working days only; skips staff on approved leave. Returns the list of emails nudged."""
    today = today or (datetime.utcnow() + timedelta(hours=7)).strftime("%Y-%m-%d")
    if not _tk_is_workday(today):
        return []
    on_leave = _tk_on_leave_today(today)
    todays = {}
    try:
        for a in db.list_attendance(start=today, end=today):
            todays.setdefault(a.get("emp_id"), a)
    except Exception:
        return []
    targets = []
    for e in (db.list_employees() or []):
        if str(e.get("status") or "Active").lower() == "inactive" or e.get("id") in on_leave or not e.get("email"):
            continue
        rec = todays.get(e.get("id"))
        if kind == "checkin" and not rec:
            targets.append(e["email"])
        elif kind == "checkout" and rec and str(rec.get("clock_out") or "").strip() in ("", "—"):
            targets.append(e["email"])
    if targets:
        if kind == "checkin":
            _tk_push(targets, "Check-in reminder", "You haven't checked in yet today — tap to check in.", "/?checkin=1", "tk-checkin-" + today)
        else:
            _tk_push(targets, "Check-out reminder", "You're still checked in — tap to check out before you leave.", "/?checkin=1", "tk-checkout-" + today)
    return targets


def _tk_nudge_scheduler():
    """Hourly wake; fires the check-in nudge at portal_tkCheckinHour and check-out at portal_tkCheckoutHour
       (VN local, UTC+7), once per day per kind (dedup blob), only while portal_tkNudges is on.

       ALSO runs the outstanding-signature reminders — deliberately OUTSIDE that switch. Policy
       chasing and attendance nudges are unrelated features, and gating one on a checkbox labelled
       "Timekeeping nudges" is a trap: signatures would silently never be chased and nobody would
       ever work out why. Publishing a document with a deadline is the opt-in; with no deadlines set,
       the sweep finds nothing and sends nothing."""
    while True:
        time.sleep(3600)
        try:
            now_vn = datetime.utcnow() + timedelta(hours=7)
            today = now_vn.strftime("%Y-%m-%d")
            # 09:00 VN — before the day gets away from people, and independent of the nudge hours.
            if now_vn.hour == 9:
                _pkey = "hrdoc:" + today
                with _TK_NUDGE_LOCK:
                    try:
                        _pseen = json.loads(db.get_setting("_tkNudgeSent") or "{}")
                    except Exception:
                        _pseen = {}
                    if not _pseen.get(_pkey):
                        try:
                            _hrdoc_reminders(today)
                        except Exception:
                            pass
                        _pseen[_pkey] = time.time()
                        _pseen = {k: v for k, v in _pseen.items() if v and (time.time() - v) < 30 * 86400}
                        db.set_setting("_tkNudgeSent", json.dumps(_pseen))
            if (db.get_setting("portal_tkNudges", "0") or "0").lower() not in ("1", "true", "on", "yes"):
                continue
            try:
                ci = int(db.get_setting("portal_tkCheckinHour", "10") or "10")
            except Exception:
                ci = 10
            try:
                co = int(db.get_setting("portal_tkCheckoutHour", "19") or "19")
            except Exception:
                co = 19
            for kind, want in (("checkin", ci), ("checkout", co)):
                if now_vn.hour != want:
                    continue
                key = kind + ":" + today
                with _TK_NUDGE_LOCK:
                    try:
                        seen = json.loads(db.get_setting("_tkNudgeSent") or "{}")
                    except Exception:
                        seen = {}
                    if seen.get(key):
                        continue
                    _tk_nudges(kind, today)
                    seen[key] = time.time()
                    seen = {k: v for k, v in seen.items() if v and (time.time() - v) < 30 * 86400}
                    db.set_setting("_tkNudgeSent", json.dumps(seen))
        except Exception:
            pass


# ── Scheduled monthly report pack ───────────────────────────────────────────────────────────
# On a configured day of the month, email leadership a branded month-end summary of the just-closed
# month (payments, invoices+VAT, approvals, headcount) with a deep-link to open + export the full
# pack in the portal. Reuses the approval-email template. Opt-in; best-effort; never raises.
_MONTHLY_LOCK = threading.Lock()
_MONTHLY_HEALTH = {"at": "", "sent": 0, "lastError": ""}


def _invtrack_all_items():
    """The flat list of captured invoices. invtrack is stored as ONE dataset doc with an `.items`
       array (NOT one row per invoice), so any aggregation must read `.items`, not the collection rows."""
    out = []
    try:
        for d in db.list_collection("invtrack"):
            if isinstance(d.get("items"), list):
                out.extend(d["items"])
    except Exception:
        pass
    return out


def _monthly_gather(ym):
    """Aggregate one closed month (YYYY-MM): payments approved/paid + invoices captured, plus a live
       approvals-pending snapshot and current headcount. Best-effort; never raises."""
    def _n(v):
        try:
            return float(str(v).replace(",", "").replace(" ", "").replace("₫", "") or 0)
        except Exception:
            return 0.0
    pay_total = 0.0
    pay_n = 0
    try:
        for p in db.list_collection("payments"):
            if str(p.get("status") or "").lower() in ("approved", "paid"):
                d = str(p.get("paidOn") or p.get("approvedOn") or p.get("submittedOn") or p.get("date") or "")[:7]
                if d == ym:
                    pay_total += _n(p.get("amount") or p.get("total"))
                    pay_n += 1
    except Exception:
        pass
    inv_total = inv_vat = 0.0
    inv_n = 0
    try:
        for it in _invtrack_all_items():
            if str(it.get("dateISO") or "")[:7] == ym:
                inv_n += 1
                tot = _n(it.get("after"))
                if not tot:
                    tot = _n(it.get("before")) + _n(it.get("vat"))
                inv_total += tot
                inv_vat += _n(it.get("vat"))
    except Exception:
        pass
    try:
        _m, _l, counts = _digest_gather()
    except Exception:
        counts = {"await": 0, "review": 0, "overdue": 0, "valuePending": 0.0}
    try:
        headcount = sum(1 for e in (db.list_employees() or []) if str(e.get("status") or "Active").lower() != "inactive")
    except Exception:
        headcount = 0
    return {"ym": ym, "payTotal": pay_total, "payCount": pay_n, "invCount": inv_n,
            "invTotal": inv_total, "invVat": inv_vat, "headcount": headcount,
            "apprPending": counts.get("await", 0) + counts.get("review", 0),
            "apprOverdue": counts.get("overdue", 0)}


def _monthly_send(preview_to=None, ym=None):
    """Email the month-end pack to leadership (portal_monthlyTo, falling back to portal_digestLeadTo).
       preview_to overrides the recipient (admin self-test). Gated by portal_monthlyReports + portal_apprEmail."""
    try:
        if not preview_to and (db.get_setting("portal_monthlyReports", "0") or "0").lower() not in ("1", "true", "on", "yes"):
            return 0
        if (db.get_setting("portal_apprEmail", "1") or "1").lower() not in ("1", "true", "on", "yes"):
            return 0
        if not ym:
            first = (datetime.utcnow() + timedelta(hours=7)).replace(day=1)
            ym = (first - timedelta(days=1)).strftime("%Y-%m")   # the just-closed month
        g = _monthly_gather(ym)
        try:
            mlabel = datetime.strptime(ym + "-01", "%Y-%m-%d").strftime("%B %Y")
        except Exception:
            mlabel = ym
        rows = [
            ("Payments approved", _money_vnd(g["payTotal"]) + " · " + str(g["payCount"]) + " request(s)"),
            ("Invoices captured", str(g["invCount"]) + " · " + _money_vnd(g["invTotal"])),
            ("VAT captured", _money_vnd(g["invVat"])),
            ("Approvals in flight (now)", str(g["apprPending"]) + " pending" + ((", " + str(g["apprOverdue"]) + " overdue") if g["apprOverdue"] else "")),
            ("Active headcount", str(g["headcount"])),
        ]
        to = (preview_to or (db.get_setting("portal_monthlyTo", "") or "").strip() or (db.get_setting("portal_digestLeadTo", "") or "").strip())
        if not to:
            return 0
        intro = ("Month-end summary for " + mlabel + ". Open the portal to view the live dashboards and export the full branded pack (PDF).")
        html = _appr_email_html("Month-end pack — " + mlabel, "Month-end", intro, rows, "Open & export the full pack", _portal_base() + "/")
        n = 1 if _graph_send_mail(_appr_email_sender("payments"), [to], "[Humiley] Month-end pack — " + mlabel, html) else 0
        _MONTHLY_HEALTH.update({"at": _now_iso(), "sent": _MONTHLY_HEALTH["sent"] + n})
        return n
    except Exception as e:
        _MONTHLY_HEALTH.update({"at": _now_iso(), "lastError": str(e)[:200]})
        return 0


def _monthly_scheduler():
    """Hourly wake; on portal_monthlyDay (VN morning) email the month-end pack once that month."""
    while True:
        time.sleep(3600)
        try:
            if (db.get_setting("portal_monthlyReports", "0") or "0").lower() not in ("1", "true", "on", "yes"):
                continue
            now_vn = datetime.utcnow() + timedelta(hours=7)
            try:
                want_day = max(1, min(28, int(db.get_setting("portal_monthlyDay", "1") or "1")))
            except Exception:
                want_day = 1
            if now_vn.day != want_day or now_vn.hour < 8:
                continue
            this_month = now_vn.strftime("%Y-%m")
            with _MONTHLY_LOCK:
                if (db.get_setting("_monthlySentMonth", "") or "") == this_month:
                    continue
                _monthly_send()
                db.set_setting("_monthlySentMonth", this_month)
        except Exception:
            pass


def _record_error(method, path, exc, email=None):
    """Capture one unhandled request error: ring buffer + structured stderr line + optional alert."""
    entry = {
        "ts": datetime.utcnow().isoformat() + "Z",
        "method": method,
        "path": (path or "?").split("?")[0],   # drop the query string (may carry tokens/PII)
        "error": type(exc).__name__,
        "message": str(exc)[:400],
        "email": email,
        "trace": traceback.format_exc()[-4000:],
    }
    _ERR_LOG.append(entry)
    line = {k: v for k, v in entry.items() if k != "trace"}
    try:
        sys.stderr.write("PORTAL_ERROR " + json.dumps(line) + "\n")
        sys.stderr.flush()
    except Exception:
        pass
    # Persist to a JSONL in the DB volume so errors survive the next auto-deploy (which wipes the
    # in-memory ring buffer — exactly when you're investigating a deploy regression). Rotated at ~2 MB.
    try:
        with _ERR_FILE_LOCK:
            if os.path.exists(_ERR_FILE) and os.path.getsize(_ERR_FILE) > 2_000_000:
                try:
                    os.replace(_ERR_FILE, _ERR_FILE + ".1")
                except Exception:
                    pass
            with open(_ERR_FILE, "a", encoding="utf-8") as f:
                f.write(json.dumps(line) + "\n")
    except Exception:
        pass
    _alert_webhook("🚨 Portal error: %s %s → %s: %s" % (entry["method"], entry["path"], entry["error"], entry["message"]))


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



# ══════════════════════════════════════════════════════════════════════════════
# INVOICE TRACKING — server-side extraction + app-only 24/7 mailbox sync.
# Reads hd@humiley.com/Inbox via Microsoft Graph (APP-ONLY client-credentials,
# Mail.Read application) so tracking runs 24/7 with nobody signed in; extracts each
# supplier invoice from its XML/ZIP e-invoice (Vietnamese TT78) using ONLY the Python
# stdlib; de-dupes by internetMessageId; MERGES into one `invtrack` dataset doc
# (re-read before write so a concurrent browser import/sync is never clobbered);
# audits real changes. Env-gated: no secret => no-op with a clear status.
# HARDENED against untrusted-attachment DoS (XML entity-expansion + ZIP bombs).
# ══════════════════════════════════════════════════════════════════════════════
M365["clientSecret"] = os.environ.get("TK_M365_CLIENT_SECRET", "")
INVTRACK = {
    "mailbox": os.environ.get("TK_INVTRACK_MAILBOX", "hd@humiley.com"),
    "interval": max(2, int(os.environ.get("TK_INVTRACK_INTERVAL_MIN", "10") or "10")),
    "ocr_url": os.environ.get("TK_OCR_ENDPOINT", ""),
}
_INVTRACK_LOCK = threading.Lock()          # serialize backend syncs
_GRAPH_APP_TOK = {"tok": "", "exp": 0.0}
# (moved to einv.py)

# Where the real invoice attachments (PDF / XML / ZIP) captured from the mailbox are kept, so the
# register can SHOW + serve the actual file — even for a provider whose XML the parser can't read yet.
# Lives beside the DB on the persistent data volume (never committed; the .db dir is gitignored).
_INVTRACK_FILE_DIR = os.path.join(os.path.dirname(os.path.abspath(db.DB_PATH)), "invtrack_files")
_INVTRACK_FILE_MAX = 8 * 1024 * 1024       # don't persist an attachment larger than this
_INVTRACK_FILE_CT = {"pdf": "application/pdf", "xml": "application/xml", "zip": "application/zip"}


def _invtrack_kind(name, ct):
    n = (name or "").lower(); c = (ct or "").lower()
    if n.endswith(".pdf") or "pdf" in c:
        return "pdf"
    if n.endswith(".xml") or "xml" in c:
        return "xml"
    if n.endswith(".zip") or "zip" in c or "compressed" in c:
        return "zip"
    return ""


def _invtrack_store_file(raw, name, ct):
    """Persist a downloaded invoice attachment (content-addressed) and return {id,name,kind} — or None.
       Best-effort: any failure returns None and NEVER breaks the sync. Dedupes identical files."""
    try:
        kind = _invtrack_kind(name, ct)
        if not kind or not raw or len(raw) > _INVTRACK_FILE_MAX:
            return None
        os.makedirs(_INVTRACK_FILE_DIR, exist_ok=True)
        fid = hashlib.sha256(raw).hexdigest()[:32]
        path = os.path.join(_INVTRACK_FILE_DIR, fid + "." + kind)
        # Atomic write: an interrupted sync used to leave a truncated file that the exists-guard then
        # treated as good forever. Write to a temp then os.replace (atomic), and self-heal a file whose
        # size doesn't match (a leftover partial from an older crash).
        if not os.path.exists(path) or os.path.getsize(path) != len(raw):
            tmp = path + ".tmp-" + hashlib.sha256(raw).hexdigest()[32:48]
            with open(tmp, "wb") as fh:
                fh.write(raw); fh.flush(); os.fsync(fh.fileno())
            os.replace(tmp, path)
        return {"id": fid, "name": (name or (fid + "." + kind))[:200], "kind": kind}
    except Exception:
        return None


def _invtrack_app_ready():
    return bool(M365["clientId"] and M365["tenantId"] and M365["clientSecret"])


# _now_iso → tkutil.py (extracted)


# ── Rate limiting (in-memory, per real client IP) ──────────────────────────────────────────────
# Sliding-window counters guard against brute-forcing the login and against write floods / cheap DoS
# on a single-process stdlib server. Keyed by the REAL client (X-Forwarded-For from Caddy), so the
# loopback proxy hop is never the key; loopback callers (health probes, the test harness) are exempt.
# rate limiter (_RATE, _RATE_LOCK, _rate_allow) → ratelimit.py (extracted)


# _claim_items, _claim_rollup → tkutil.py (extracted)


# _vn_fold → tkutil.py (extracted)


# _iso_minus → tkutil.py (extracted)


# _einv_num → tkutil.py (extracted)


# _einv_xml_num → tkutil.py (extracted)


# (moved to einv.py)


# (moved to einv.py)


# (moved to einv.py)


# (moved to einv.py)


# (moved to einv.py)


# (moved to einv.py)


# (moved to einv.py)


def _invtrack_merge_inv(dst, src, sf):
    """Fold a duplicate parse of the SAME invoice (delivered as a second file) into dst: fill blank fields,
       take a positive amount over a blank one, and add the file."""
    def pos(v):
        try:
            return float(v or 0)
        except Exception:
            return 0.0
    for f in ("before", "vat", "after"):
        if pos(dst.get(f)) <= 0 and pos(src.get(f)) > 0:
            dst[f] = src[f]
    for f in ("serial", "invNo", "taxCode", "supplier", "dateISO", "dateRaw", "desc", "lookup", "lookupCode", "method", "_attachName",
              "buyerName", "buyerMST", "sellerAddr", "buyerAddr", "currency", "payMethod", "vatRate"):
        if not dst.get(f) and src.get(f):
            dst[f] = src[f]
    if not (dst.get("items") or []) and (src.get("items") or []):   # the XML usually carries the line items; a PDF may not
        dst["items"] = src["items"]
    if sf and sf.get("id") not in {x.get("id") for x in (dst.get("_files") or [])}:
        dst.setdefault("_files", []).append(sf)


def _invtrack_dedupe_invoices(parsed):
    """parsed = [(invoice_dict, its_stored_file_ref_or_None), …] gathered from ALL of an email's attachments.
       Collapse the same invoice delivered as multiple files (XML + PDF share the invoice-no), keep DISTINCT
       invoices separate. Tolerant: one file may miss the seller-MST. Returns invoice dicts, each with `_files`."""
    out = []
    for ex, sf in parsed:
        if not ex:
            continue
        n = str(ex.get("invNo") or "").strip()
        t = str(ex.get("taxCode") or "").split("-")[0].strip()
        merged = False
        if n:
            for prev in out:
                pn = str(prev.get("invNo") or "").strip()
                pt = str(prev.get("taxCode") or "").split("-")[0].strip()
                if pn == n and (not t or not pt or t == pt):   # same invoice-no + compatible (or missing) seller-MST
                    _invtrack_merge_inv(prev, ex, sf)
                    merged = True
                    break
        if not merged:
            ex = dict(ex)
            ex["_files"] = [sf] if sf else []
            out.append(ex)
    return out


# (moved to einv.py)


def _invtrack_ocr_pdf(pdf_bytes):
    """OCR hook (rec #3): POST the PDF to TK_OCR_ENDPOINT, expect {\"text\": ...}, parse. No-op unless configured."""
    if not INVTRACK["ocr_url"] or not pdf_bytes or len(pdf_bytes) > 10 * 1024 * 1024:
        return None
    try:
        req = urllib.request.Request(INVTRACK["ocr_url"], data=pdf_bytes, headers={"Content-Type": "application/pdf"})
        with urllib.request.urlopen(req, timeout=45) as resp:
            j = json.loads(resp.read().decode("utf-8"))
        return _einv_parse_text(j.get("text", "") if isinstance(j, dict) else "")
    except Exception:
        return None


# (moved to einv.py)


# (moved to einv.py)
# (moved to einv.py)


# (moved to einv.py)


def _einv_from_pdf(pdf_bytes):
    """Extract a VN e-invoice from a PDF attachment's TEXT layer (no OCR). Most VN e-invoice PDFs are
       generated (not scanned), so pypdf reads the amounts / tax-code / invoice-no directly. Returns
       the same dict shape as _einv_parse_xml, or None (e.g. an image-only PDF -> caller tries OCR)."""
    if not pdf_bytes or len(pdf_bytes) > 12 * 1024 * 1024:
        return None
    try:
        import pypdf
        rd = pypdf.PdfReader(io.BytesIO(pdf_bytes))
        pages = list(rd.pages)[:30]                    # bound work on untrusted input
        text = "\n".join((p.extract_text() or "") for p in pages)
    except Exception:
        return None
    if not text or len(text) < 20:
        return None
    bf = _invtrack_body_fields(text)                   # amounts + invNo + seller MST + lookup (diacritic-folded)
    serial = ""
    ms = re.search(r"K[\u00fdy]\s*hi[\u1ec7e]u\s*(?:\([^)]*\))?\s*[:\-]?\s*([0-9A-Z]{3,14})", text, re.I)
    if ms:
        serial = ms.group(1).upper()
    if not (bf.get("after") or bf.get("invNo") or serial):
        return None
    diso = ""
    dr = ""
    md = re.search(r"[Nn]g[àa]y\s*0?(\d{1,2})\s*th[áa]ng\s*0?(\d{1,2})\s*n[ăa]m\s*(\d{4})", text)
    if not md:
        md = re.search(r"\b(\d{4})-(\d{2})-(\d{2})\b", text)   # some PDFs print an ISO date
        if md:
            diso = md.group(0)
            dr = diso
    if md and not diso:
        try:
            diso = "%s-%02d-%02d" % (md.group(3), int(md.group(2)), int(md.group(1)))
            dr = md.group(0)
        except Exception:
            diso = ""
    # A Bkav-layout total row lists the three sums together: "Tổng cộng <before> <VAT> <after>" — read
    # all three so we never mislabel the pre-tax subtotal as the grand total (the body regex grabs one).
    b3 = v3 = a3 = 0
    mt = re.search(r"T[ổo]ng\s*c[ộo]ng(?:\s*ti[ềe]n\s*thanh\s*to[áa]n)?\s*[:\-]?\s*([\d.,]{4,})\s+([\d.,]{2,})\s+([\d.,]{4,})", text)
    if mt:
        b3 = _einv_num(mt.group(1))
        v3 = _einv_num(mt.group(2))
        a3 = _einv_num(mt.group(3))
    items = _einv_pdf_items(text)
    vrate = ""
    for it in items:
        if it.get("taxRate"):
            vrate = it["taxRate"]
            break
    return {"invNo": bf.get("invNo", ""), "serial": serial, "taxCode": bf.get("taxCode", ""),
            "before": b3 or bf.get("before", 0), "vat": v3 or bf.get("vat", 0), "after": a3 or bf.get("after", 0),
            "supplier": "", "dateISO": diso, "dateRaw": dr, "lookupCode": bf.get("code", ""),
            "items": items, "vatRate": vrate, "_method": "pdf"}


_INVLINK_HOSTS = ("vnpt-invoice.vn", "vnpt-invoice.com.vn", "vnpt.vn", "meinvoice.vn", "misa.vn", "misa.com.vn",
                  "sinvoice.viettel.vn", "viettel.vn", "einvoice.fpt.com.vn", "fpt.com.vn", "easyinvoice.vn",
                  "softdreams.vn", "bkav.com", "ehoadon.vn", "hilo.com.vn", "hoadondientu.gdt.gov.vn", "gdt.gov.vn",
                  "einvoice.com.vn", "hoadon.vn", "wininvoice.vn", "vininvoice.vn", "cyberbill.vn",
                  "hoadondientu.vn", "vnpt-invoice.com", "einvoice.vn")

# Content-Security-Policy for the portal HTML — allowlists exactly the CDNs + APIs the app loads.
_CSP = (
    "default-src 'self'; base-uri 'self'; object-src 'none'; frame-ancestors 'self'; form-action 'self'; "
    "script-src 'self' 'unsafe-inline' 'unsafe-eval' https://cdnjs.cloudflare.com https://unpkg.com "
    "https://alcdn.msauth.net https://*.msftauth.net https://login.microsoftonline.com https://maps.googleapis.com; "
    "style-src 'self' 'unsafe-inline' https://fonts.googleapis.com https://unpkg.com; "
    "font-src 'self' data: https://fonts.gstatic.com; "
    "img-src 'self' data: blob: https:; "
    "connect-src 'self' https://graph.microsoft.com https://login.microsoftonline.com https://*.msftauth.net "
    "https://nominatim.openstreetmap.org https://*.sharepoint.com https://*.webhook.office.com "
    "https://maps.googleapis.com https://cdnjs.cloudflare.com; "
    # frame-src allows blob:/data: so the in-app file preview (tkFilePreview) can render an attached
    # PDF inline in an <iframe> — attachments are held client-side as base64/blob, so the src is a
    # blob:/data: URL, not a same-origin path. These framed docs are opaque-origin (same-origin policy
    # still blocks them from reading the parent's tokens); without this the PDF pane renders blank.
    # frame-src MUST also allow Microsoft's login origin. MSAL renews access tokens SILENTLY by
    # navigating a HIDDEN IFRAME to login.microsoftonline.com/.../authorize?prompt=none. That origin
    # was allow-listed in script-src and connect-src but never here, so the browser blocked the frame
    # outright (verified: securitypolicyviolation fires with violatedDirective=frame-src). No hash
    # ever came back, MSAL waited out iframeHashTimeout and threw `monitor_window_timeout` — which is
    # what a site engineer saw instead of their PDF reaching SharePoint, and why 12 MB contractor
    # reports have been landing in the database. Entra SPA refresh tokens are 24-hour and single-use,
    # so this path is reached routinely: every morning, and the first time anyone needs the SharePoint
    # scope. Self-inflicted, by the CSP hardening pass. Microsoft's interactive pages set their own
    # frame-ancestors and still refuse to be framed, so only the prompt=none flow benefits.
    "worker-src 'self' blob: https://cdnjs.cloudflare.com; "
    "frame-src 'self' blob: data: https://login.microsoftonline.com https://*.msftauth.net"
)


def _invtrack_url_safe(url):
    """SSRF guard for a URL taken from an untrusted email: http(s) only, host must be a known VN
       e-invoice provider, and it must resolve to a PUBLIC IP (blocks internal/metadata endpoints)."""
    try:
        import socket, ipaddress
        u = urllib.parse.urlparse(url)
        if u.scheme not in ("http", "https"):
            return False
        host = (u.hostname or "").lower()
        if not host or not any(host == h or host.endswith("." + h) for h in _INVLINK_HOSTS):
            return False
        for res in socket.getaddrinfo(host, None):
            ip = ipaddress.ip_address(res[4][0])
            if ip.is_private or ip.is_loopback or ip.is_link_local or ip.is_reserved or ip.is_multicast or ip.is_unspecified:
                return False
        return True
    except Exception:
        return False


def _invtrack_fetch_ehoadon(serial, invno, mtc):
    """BKAV eHoadon (noreply@ehoadon.vn notifications) serves the invoice's DISPLAY PDF publicly at a
       derivable path — the tra-cứu code (MTC) in the filename IS the access token, so NO login/CAPTCHA
       is needed. Given the serial (Ký hiệu), invoice-no and MTC from the email, build the URL, fetch
       the PDF and parse it. Returns (pdf_bytes, parsed_dict) or (None, None)."""
    serial = re.sub(r"[^0-9A-Za-z]", "", (serial or "")).upper()
    mtc = re.sub(r"[^0-9A-Za-z]", "", (mtc or ""))
    ivn = re.sub(r"\D", "", str(invno or ""))
    if not (len(serial) >= 4 and len(mtc) >= 6 and ivn):
        return (None, None)
    ivn8 = ivn.zfill(8)
    for suffix in ("DPH", "DCT", "GOC", "TBP"):          # DPH = issued display copy; a few known fallbacks
        url = "https://tchd.ehoadon.vn/Invoice_View/%s/%s/%s-%s-%s-%s.pdf" % (serial[:2], serial[2:4], serial, ivn8, mtc, suffix)
        if not _invtrack_url_safe(url):
            return (None, None)
        try:
            req = urllib.request.Request(url, headers={"User-Agent": "Mozilla/5.0 (HumileyInvoiceBot)"})
            with urllib.request.urlopen(req, timeout=12) as resp:
                ct = (resp.headers.get("Content-Type") or "").lower()
                data = resp.read(12 * 1024 * 1024 + 1)
        except Exception:
            continue
        if len(data) > 12 * 1024 * 1024:
            return (None, None)
        if not (data[:5] == b"%PDF-" or "pdf" in ct):    # a wrong suffix returns an HTML error page → try next
            continue
        ex = _einv_from_pdf(data) or {}
        if not ex.get("serial"):
            ex["serial"] = serial
        if not ex.get("invNo"):
            ex["invNo"] = ivn.lstrip("0") or ivn
        ex["lookupCode"] = mtc
        ex["method"] = "ehoadon-pdf"
        return (data, ex)
    return (None, None)


def _invtrack_fetch_misa(sc):
    """MISA meInvoice serves the invoice XML + display PDF PUBLICLY via its DownloadHandler keyed only by
       the tra-cứu code (sc) — no session, no CAPTCHA (verified server-side). Prefer the XML (full line
       items + parties, exact amounts); attach the PDF. Returns (pdf_bytes, parsed_dict) or (None, None)."""
    sc = re.sub(r"[^0-9A-Za-z]", "", (sc or ""))
    if len(sc) < 6:
        return (None, None)
    base = "https://www.meinvoice.vn/tra-cuu/tra-cuu/DownloadHandler.ashx?Code=" + sc + "&Type="
    if not _invtrack_url_safe(base + "xml"):
        return (None, None)
    ex = None
    try:
        req = urllib.request.Request(base + "xml", headers={"User-Agent": "Mozilla/5.0 (HumileyInvoiceBot)"})
        with urllib.request.urlopen(req, timeout=15) as resp:
            xdata = resp.read(8 * 1024 * 1024 + 1)
        if 0 < len(xdata) <= 8 * 1024 * 1024:
            ex = _einv_parse_xml(xdata)
    except Exception:
        ex = None
    pdf = None
    try:
        req = urllib.request.Request(base + "pdf", headers={"User-Agent": "Mozilla/5.0 (HumileyInvoiceBot)"})
        with urllib.request.urlopen(req, timeout=15) as resp:
            pdata = resp.read(12 * 1024 * 1024 + 1)
        if pdata[:5] == b"%PDF-" and len(pdata) <= 12 * 1024 * 1024:
            pdf = pdata
    except Exception:
        pdf = None
    if not ex and pdf:
        ex = _einv_from_pdf(pdf)
    if not ex:
        return (None, None)
    ex["lookupCode"] = sc
    ex["method"] = "misa-xml" if ex.get("method") == "xml" else "misa-pdf"
    return (pdf, ex)


def _invtrack_fetch_by_url(url, serial="", invno="", code=""):
    """Dispatch to the right issuer-portal fetcher by the lookup URL / sender host. Returns
       (pdf_bytes_or_None, parsed_dict) or (None, None). Extend here to add another provider."""
    host = (urllib.parse.urlparse(url or "").hostname or "").lower() + " " + (url or "").lower()
    if "ehoadon.vn" in host:
        return _invtrack_fetch_ehoadon(serial, invno, code)
    if "meinvoice.vn" in host:
        return _invtrack_fetch_misa(code)
    return (None, None)


def _invtrack_fetch_linked(url):
    """If the email links DIRECTLY to the invoice FILE (xml/zip/pdf) on a known provider, download +
       parse it — no CAPTCHA. A link to a CAPTCHA lookup PAGE returns None (unreadable by any tool)."""
    if not url or not re.search(r"\.(xml|zip|pdf)(\?|#|$)|/download|/getfile|/export|/tai", url, re.I):
        return None
    if not _invtrack_url_safe(url):
        return None
    try:
        req = urllib.request.Request(url, headers={"User-Agent": "Mozilla/5.0 (HumileyInvoiceBot)"})
        with urllib.request.urlopen(req, timeout=8) as resp:
            ct = (resp.headers.get("Content-Type") or "").lower()
            data = resp.read(10 * 1024 * 1024 + 1)
        if len(data) > 10 * 1024 * 1024:
            return None
        low = url.lower()
        if "xml" in ct or low.endswith(".xml"):
            return _einv_parse_xml(data)
        if "zip" in ct or low.endswith(".zip") or "compressed" in ct:
            return _einv_from_zip(data)
        if "pdf" in ct or ".pdf" in low:
            return _einv_from_pdf(data)
        return _einv_from_zip(data) or _einv_parse_xml(data) or _einv_from_pdf(data)
    except Exception:
        return None


def _graph_granted_roles(force=False):
    """The APPLICATION permissions the app-only token actually carries (its `roles` claim).

    Worth the few lines: the health panel used to print fixed advice like "Grant Mail.Send consent"
    whether or not it was granted, which is actively misleading — an admin who HAS granted it goes
    looking in the wrong place, and one who has not gets no confirmation when they do. Reading the
    claim turns guesses into facts. Decoded WITHOUT verification on purpose: this is our own token,
    read for diagnosis, never trusted for authorisation."""
    try:
        tok = _graph_app_token(force=force)
        payload = tok.split(".")[1]
        payload += "=" * (-len(payload) % 4)
        return sorted(json.loads(base64.urlsafe_b64decode(payload)).get("roles") or [])
    except Exception:
        return []


def _graph_app_token(force=False):
    # force=True busts the cache — needed right after a NEW application permission is consented, because
    # the cached token was minted before consent and still lacks the new role (Graph would 403 it).
    if not force and _GRAPH_APP_TOK["tok"] and _GRAPH_APP_TOK["exp"] > time.time() + 60:
        return _GRAPH_APP_TOK["tok"]
    data = urllib.parse.urlencode({
        "client_id": M365["clientId"], "client_secret": M365["clientSecret"],
        "scope": "https://graph.microsoft.com/.default", "grant_type": "client_credentials",
    }).encode("utf-8")
    req = urllib.request.Request(
        "https://login.microsoftonline.com/" + M365["tenantId"] + "/oauth2/v2.0/token",
        data=data, headers={"Content-Type": "application/x-www-form-urlencoded"})
    try:
        with urllib.request.urlopen(req, timeout=20) as resp:
            j = json.loads(resp.read().decode("utf-8"))
    except Exception as he:                        # surface Azure's real reason (e.g. AADSTS7000215 invalid secret)
        body = ""
        try: body = he.read().decode("utf-8", "replace")
        except Exception: pass
        if body:
            try:
                ej = json.loads(body); det = ej.get("error_description") or ej.get("error") or body[:200]
            except Exception:
                det = body[:200]
            raise Exception("Sign-in to Microsoft failed (%s): %s" % (getattr(he, "code", "?"), str(det).split("\n")[0][:200]))
        raise
    _GRAPH_APP_TOK["tok"] = j["access_token"]
    _GRAPH_APP_TOK["exp"] = time.time() + int(j.get("expires_in", 3600))
    return _GRAPH_APP_TOK["tok"]


def _graph_get(url, token):
    req = urllib.request.Request(url, headers={"Authorization": "Bearer " + token})
    with urllib.request.urlopen(req, timeout=30) as resp:
        return json.loads(resp.read().decode("utf-8"))


def _graph_put_bytes(url, token, data, ctype):
    req = urllib.request.Request(url, data=data, method="PUT",
                                 headers={"Authorization": "Bearer " + token, "Content-Type": ctype or "application/octet-stream"})
    with urllib.request.urlopen(req, timeout=45) as resp:
        return json.loads(resp.read().decode("utf-8"))


def _graph_err_text(e):
    """Short, human-readable reason for a failed Graph call, safe to show an admin in the UI.
       Pulls Graph's own error.message out of the HTTPError body; never echoes tokens or secrets."""
    code = getattr(e, "code", None)
    detail = ""
    try:
        body = e.read().decode("utf-8", "replace")          # HTTPError is also a file object
        ej = json.loads(body)
        err = ej.get("error") or {}
        detail = (err.get("message") if isinstance(err, dict) else str(err)) or ""
        if isinstance(err, dict) and err.get("code"):
            detail = "%s: %s" % (err["code"], detail)
    except Exception:
        detail = str(e)
    detail = re.sub(r"[A-Za-z0-9_\-]{40,}", "…", str(detail)).strip()   # scrub anything token-shaped
    detail = detail.split("\n")[0][:300]
    return ("HTTP %s — %s" % (code, detail)) if code else (detail or "unknown error")


# Resolved (siteId, driveId, folder-relative-path) for the configured Invoice-Tracking SharePoint
# folder, plus a short negative cache so a missing-consent / bad-URL case doesn't re-resolve per file.
_INVTRACK_SP = {"url": None, "site": "", "drive": "", "rel": ""}
_INVTRACK_SP_FAIL = {"url": "", "until": 0.0}


def _sp_parse_folder(folder):
    """Parse a pasted SharePoint folder URL → (host, site_path, folder_rel). Accepts BOTH the clean
       folder path (…/sites/<Site>/Shared Documents/<Folder>) and the browser's library VIEW url
       (…/sites/<Site>/Forms/AllItems.aspx?id=%2Fsites%2F<Site>%2FShared Documents%2F<Folder>&viewid=…),
       which is what an admin most often copies from the address bar. Raises ValueError otherwise."""
    pu = urlparse(folder)
    host = pu.netloc
    if not host:
        raise ValueError("Expected a full https://<tenant>.sharepoint.com/... link")
    qs = parse_qs(pu.query or "")
    src = ""                                             # a view URL keeps the real folder in ?id= / ?RootFolder=
    for key in ("id", "RootFolder", "rootfolder", "FolderCTID".lower()):
        if qs.get(key):
            src = qs[key][0]; break
    parts = [urllib.parse.unquote(p) for p in (src or pu.path).split("/") if p]
    while parts and (parts[-1].lower().endswith(".aspx") or parts[-1].lower() == "forms"):
        parts = parts[:-1]                               # strip a trailing /Forms/AllItems.aspx from the path form
    if len(parts) < 2 or parts[0].lower() != "sites":
        raise ValueError("Expected a link like https://<tenant>.sharepoint.com/sites/<Site>/Shared Documents/<Folder>")
    site_path = "/sites/" + parts[1]
    rest = parts[2:]
    if rest and rest[0].lower() in ("shared documents", "documents"):   # the default doc library == drive root
        rest = rest[1:]
    return host, site_path, "/".join(rest)


def _invtrack_sp_resolve(token):
    """Resolve the configured SharePoint folder URL → (siteId, driveId, folderRel). Cached per-URL;
       failures negative-cached ~5 min. Returns the cache dict or None (→ the local copy stays canonical)."""
    folder = (db.get_setting("portal_invtrackSpUrl", "") or "").strip()
    if not folder:
        return None
    if _INVTRACK_SP["url"] == folder and _INVTRACK_SP["site"] and _INVTRACK_SP["drive"]:
        return _INVTRACK_SP
    if _INVTRACK_SP_FAIL["url"] == folder and _INVTRACK_SP_FAIL["until"] > time.time():
        return None
    try:
        host, site_path, folder_rel = _sp_parse_folder(folder)
        site = _graph_get("https://graph.microsoft.com/v1.0/sites/" + host + ":" + site_path, token)
        site_id = site.get("id")
        drive = _graph_get("https://graph.microsoft.com/v1.0/sites/" + site_id + "/drive", token) if site_id else {}
        drive_id = drive.get("id")
        if not (site_id and drive_id):
            raise ValueError("could not resolve site/drive")
        _INVTRACK_SP.update({"url": folder, "site": site_id, "drive": drive_id, "rel": folder_rel})
        return _INVTRACK_SP
    except Exception:
        _INVTRACK_SP_FAIL.update({"url": folder, "until": time.time() + 300})
        return None


def _invtrack_sp_reset():
    """Drop every SharePoint cache. Called when an admin changes the folder URL (or runs the
       connection test) so a corrected URL / freshly-granted consent takes effect IMMEDIATELY
       instead of waiting out the 5-minute negative cache or a container restart."""
    _INVTRACK_SP.update({"url": None, "site": "", "drive": "", "rel": ""})
    _INVTRACK_SP_FAIL.update({"url": "", "until": 0.0})
    _INVTRACK_SP_DIRS.clear()


# Health of the most recent archive attempt, surfaced read-only in Invoice Tracking → Settings so a
# silent SharePoint failure is visible instead of invisible. Never holds secrets.
_INVTRACK_SP_HEALTH = {"at": "", "ok": 0, "failed": 0, "lastError": "", "lastUrl": ""}


_INVTRACK_SP_DIRS = set()   # folder paths already ensured this process (so we don't re-create per file)


def _invtrack_sp_ensure_dir(drive_id, rel_path, token):
    """Create every level of rel_path under the drive root if it doesn't exist yet. Graph's PUT-to-path
       does not reliably auto-create parent folders, so we make the Year/Month tree explicitly. 409 =
       already exists (fine). Cached per process."""
    if not rel_path:
        return
    ck = drive_id + "|" + rel_path
    if ck in _INVTRACK_SP_DIRS:
        return
    acc = ""
    for seg in rel_path.split("/"):
        if not seg:
            continue
        parent = acc
        acc = (acc + "/" + seg) if acc else seg
        parent_ref = ("root:/" + "/".join(urllib.parse.quote(p) for p in parent.split("/") if p) + ":") if parent else "root"
        url = "https://graph.microsoft.com/v1.0/drives/" + drive_id + "/" + parent_ref + "/children"
        body = json.dumps({"name": seg, "folder": {}, "@microsoft.graph.conflictBehavior": "fail"}).encode("utf-8")
        req = urllib.request.Request(url, data=body, method="POST",
                                     headers={"Authorization": "Bearer " + token, "Content-Type": "application/json"})
        try:
            urllib.request.urlopen(req, timeout=30)
        except urllib.error.HTTPError as e:
            if e.code != 409:                        # 409 Conflict = the folder is already there
                raise
    _INVTRACK_SP_DIRS.add(ck)


_SP_SIMPLE_PUT_MAX = 4 * 1024 * 1024   # Graph's simple PUT ceiling; bigger files go via an upload session


def _graph_upload_session(drive_id, path, token, raw, ct):
    """Upload a 4–8 MB file (a scanned-PDF invoice) via a Graph upload session. Files this size used to
       be stored locally but SILENTLY skipped for SharePoint, so the archive was quietly incomplete.
       Sends the whole payload as one chunk (<=8 MB is well inside the 60 MiB per-request limit)."""
    su = "https://graph.microsoft.com/v1.0/drives/" + drive_id + "/root:/" + path + ":/createUploadSession"
    body = json.dumps({"item": {"@microsoft.graph.conflictBehavior": "replace"}}).encode("utf-8")
    req = urllib.request.Request(su, data=body, method="POST",
                                 headers={"Authorization": "Bearer " + token, "Content-Type": "application/json"})
    with urllib.request.urlopen(req, timeout=60) as r:
        sess = json.loads(r.read().decode("utf-8"))
    up = sess.get("uploadUrl")
    if not up:
        raise ValueError("no uploadUrl in session")
    n = len(raw)
    put = urllib.request.Request(up, data=raw, method="PUT",
                                 headers={"Content-Length": str(n),
                                          "Content-Range": "bytes 0-%d/%d" % (n - 1, n),
                                          "Content-Type": ct or "application/octet-stream"})
    with urllib.request.urlopen(put, timeout=180) as r2:     # the session URL is pre-authorized — no bearer
        return json.loads(r2.read().decode("utf-8") or "{}")


def _sp_safe_leaf(filename, fid):
    """Collision-proof, path-safe SharePoint file name. The mailbox routinely sends invoices with the
       SAME default name (VNPT/MISA/Viettel all emit 'HoaDon.pdf'), so naming the archived file after
       the raw attachment name + conflictBehavior=replace made two different suppliers' invoices in the
       same month overwrite each other — and the register row then linked to the wrong document. We
       prefix the content hash so distinct files never collide, and strip any path/illegal characters
       (SharePoint forbids " * : < > ? / \\ | and a leading ~$) so the name can't escape the folder."""
    base = os.path.basename((filename or "").replace("\\", "/")) or "invoice"
    base = re.sub(r'[\\/:*?"<>|]+', "_", base).lstrip("~$ ").strip() or "invoice"
    base = base[:120]
    pref = (fid or "")[:12]
    return (pref + "-" + base) if pref else base


def _invtrack_sp_upload(raw, filename, ct, iso, fid=""):
    """Best-effort upload one captured invoice file to SharePoint under <folder>/Invoice Monthly (MM-YY)/,
       creating the monthly folder automatically so every tracked invoice for a month lands together.
       Returns the webUrl or None. NEVER raises — SharePoint is an add-on to the always-present local
       copy. Needs Graph Sites.ReadWrite.All (application) consent. Records the outcome in
       _INVTRACK_SP_HEALTH so a silent failure is visible in Settings."""
    if not (db.get_setting("portal_invtrackSpUrl", "") or "").strip():
        return None                                  # not configured → zero Graph calls, no health noise
    try:
        if not raw or len(raw) > _INVTRACK_FILE_MAX:
            raise ValueError("file too large to archive (%d bytes)" % (len(raw or b""),))
        token = _graph_app_token()
        tgt = _invtrack_sp_resolve(token)
        if not tgt:
            # Could be a genuinely bad link — or a token minted before consent was granted, which is
            # indistinguishable from here. Bust the cache and try once with a fresh one so the archive
            # starts working the moment consent lands, instead of an hour later.
            _invtrack_sp_reset()
            token = _graph_app_token(force=True)   # rebind: the UPLOAD below must use the fresh token
            tgt = _invtrack_sp_resolve(token)      # too, or resolve succeeds and the PUT then 403s
        if not tgt:
            raise ValueError("could not resolve the SharePoint folder — check the link and Sites.ReadWrite.All consent")
        ym = (iso or "")[:7]
        y = ym[:4] or "0000"; mo = ym[5:7] or "00"
        yy = y[2:] if len(y) == 4 else (y or "00")
        month_folder = "Invoice Monthly (%s-%s)" % (mo, yy)   # one folder per month, e.g. "Invoice Monthly (07-26)"
        base_segs = [s for s in (tgt["rel"].split("/") if tgt["rel"] else []) if s] + [month_folder]
        _invtrack_sp_ensure_dir(tgt["drive"], "/".join(base_segs), token)   # AUTO-CREATE the monthly folder
        path = "/".join(urllib.parse.quote(s) for s in (base_segs + [_sp_safe_leaf(filename, fid)]))
        if len(raw) > _SP_SIMPLE_PUT_MAX:
            it = _graph_upload_session(tgt["drive"], path, token, raw, ct)
        else:
            url = ("https://graph.microsoft.com/v1.0/drives/" + tgt["drive"] + "/root:/" + path
                   + ":/content?@microsoft.graph.conflictBehavior=replace")
            it = _graph_put_bytes(url, token, raw, ct or "application/octet-stream")
        web = it.get("webUrl") or None
        _INVTRACK_SP_HEALTH.update({"at": _now_iso(), "ok": _INVTRACK_SP_HEALTH["ok"] + 1,
                                    "lastError": "", "lastUrl": web or ""})
        return web
    except Exception as e:
        _INVTRACK_SP_HEALTH.update({"at": _now_iso(), "failed": _INVTRACK_SP_HEALTH["failed"] + 1,
                                    "lastError": _graph_err_text(e)})
        return None


# ── Finance SharePoint archive — SERVER-SIDE ─────────────────────────────────────────────────────
# The Finance archive used to run ENTIRELY in the browser (_finSpUploadAttachment), through the
# signed-in user's delegated MSAL token. That meant it only worked while somebody happened to be
# signed in to Microsoft in that tab, and it swallowed every error — so the Year/Month folders often
# simply never appeared, while Invoice Tracking (server-side, app-only) filed reliably. Same tenant,
# same library, completely different reliability.
#
# Now that the app has app-only SharePoint access, the request's PDF is filed by the SERVER on submit,
# exactly like an invoice: <library>/<Payments|Claims|Travel>/<YYYY>/<MM>/<ref>/. Best-effort — the
# in-portal copy stays canonical and a failure never blocks a submission — but it is RECORDED so a
# silent failure is visible rather than invisible.
_HRSP = {"url": "", "site": "", "drive": "", "rel": ""}
_HRSP_FAIL = {"url": "", "until": 0.0}
_FINSP = {"url": "", "site": "", "drive": "", "rel": ""}
_FINSP_FAIL = {"url": "", "until": 0.0}
_FINSP_HEALTH = {"at": "", "ok": 0, "failed": 0, "lastError": "", "lastUrl": ""}


def _finsp_reset():
    _FINSP.update({"url": "", "site": "", "drive": "", "rel": ""})
    _FINSP_FAIL.update({"url": "", "until": 0.0})


def _finsp_resolve(token):
    """Resolve the Finance folder URL → cache dict, or None. Mirrors _invtrack_sp_resolve."""
    folder = (db.get_setting("portal_financeSpUrl", "") or "").strip()
    if not folder:
        return None
    if _FINSP["url"] == folder and _FINSP["site"] and _FINSP["drive"]:
        return _FINSP
    if _FINSP_FAIL["url"] == folder and _FINSP_FAIL["until"] > time.time():
        return None
    try:
        host, site_path, folder_rel = _sp_parse_folder(folder)
        site = _graph_get("https://graph.microsoft.com/v1.0/sites/" + host + ":" + site_path, token)
        site_id = site.get("id")
        drive = _graph_get("https://graph.microsoft.com/v1.0/sites/" + site_id + "/drive", token) if site_id else {}
        if not (site_id and drive.get("id")):
            raise ValueError("could not resolve site/drive")
        _FINSP.update({"url": folder, "site": site_id, "drive": drive["id"], "rel": folder_rel})
        return _FINSP
    except Exception:
        _FINSP_FAIL.update({"url": folder, "until": time.time() + 300})
        return None


def _hrsp_reset():
    _HRSP.update({"url": "", "site": "", "drive": "", "rel": ""})
    _HRSP_FAIL.update({"url": "", "until": 0.0})


def _hrsp_resolve(token):
    """Resolve the HR folder URL -> cache dict, or None. Mirrors _finsp_resolve deliberately."""
    folder = (db.get_setting("portal_hrSpUrl", "") or "").strip()
    if not folder:
        return None
    if _HRSP["url"] == folder and _HRSP["site"] and _HRSP["drive"]:
        return _HRSP
    if _HRSP_FAIL["url"] == folder and _HRSP_FAIL["until"] > time.time():
        return None
    try:
        host, site_path, folder_rel = _sp_parse_folder(folder)
        site = _graph_get("https://graph.microsoft.com/v1.0/sites/" + host + ":" + site_path, token)
        site_id = site.get("id")
        drive = _graph_get("https://graph.microsoft.com/v1.0/sites/" + site_id + "/drive", token) if site_id else {}
        if not (site_id and drive.get("id")):
            raise ValueError("could not resolve site/drive")
        _HRSP.update({"url": folder, "site": site_id, "drive": drive["id"], "rel": folder_rel})
        return _HRSP
    except Exception:
        _HRSP_FAIL.update({"url": folder, "until": time.time() + 300})
        return None


def _hrsp_put(sub_dirs, filename, raw, ctype):
    """Put one file into <configured HR folder>/<sub_dirs...>/<filename>. Returns its webUrl.

    Raises with a sentence an HR admin can act on — unlike the Finance archiver this one runs while
    somebody is watching, so a silent failure would just look broken."""
    if not _invtrack_app_ready():
        raise ValueError("Microsoft 365 is not connected for the server — ask IT to grant Sites consent.")
    token = _graph_app_token()
    tgt = _hrsp_resolve(token)
    if not tgt:
        # The cached token can predate a fresh consent grant; retry once with a forced token.
        _hrsp_reset()
        token = _graph_app_token(force=True)
        tgt = _hrsp_resolve(token)
    if not tgt:
        raise ValueError("Could not open the HR SharePoint folder - check the link in Company Portal settings.")
    parts = [x for x in (tgt["rel"].split("/") if tgt["rel"] else []) if x]
    for d in sub_dirs:
        d = _sp_safe_leaf(str(d or ""), "")
        # Don't create JD/JD: an admin who already pointed the setting at the JD folder should get
        # their files in it, not in a second one nested inside.
        if d and (not parts or parts[-1].strip().lower() != d.lower()):
            parts.append(d)
    rel = "/".join(parts)
    _invtrack_sp_ensure_dir(tgt["drive"], rel, token)      # creates every missing level
    name = _sp_safe_leaf(str(filename or "JD.pdf"), "")
    path = "/".join(urllib.parse.quote(x) for x in (parts + [name]))
    if len(raw) > 4 * 1024 * 1024:
        it = _graph_upload_session(tgt["drive"], path, token, raw, ctype)
    else:
        url = "https://graph.microsoft.com/v1.0/drives/" + tgt["drive"] + "/root:/" + path + ":/content"
        it = _graph_put_bytes(url, token, raw, ctype)
    return (it or {}).get("webUrl") or ""


def _finsp_ref(item, kind):
    """Folder-safe reference — mirrors the frontend _finSpRef so both produce the SAME folder name
       (Hà Nội → Ha_Noi), otherwise the server and the browser would file into two different trees."""
    raw = str(item.get("reqNo") or item.get("title") or item.get("dest") or item.get("name") or kind or "request")
    raw = unicodedata.normalize("NFD", raw)
    raw = "".join(c for c in raw if unicodedata.category(c) != "Mn")
    raw = raw.replace("đ", "d").replace("Đ", "D")
    return re.sub(r"[^\w.\-]+", "_", raw)[:60] or "request"


def _finsp_archive(item, kind):
    """File one request's combined PDF into the Finance library. NEVER raises."""
    try:
        folder = (db.get_setting("portal_financeSpUrl", "") or "").strip()
        if not folder or not _invtrack_app_ready():
            return None
        att = item.get("attachment") or ""
        if not isinstance(att, str) or not att.startswith("data:"):
            return None                                   # nothing to file (or a URL, already elsewhere)
        head, _, b64 = att.partition(",")
        raw = base64.b64decode(b64 + "=" * (-len(b64) % 4))
        if not raw or len(raw) > _INVTRACK_FILE_MAX:
            return None
        ct = head[5:].split(";")[0] or "application/pdf"
        token = _graph_app_token()
        tgt = _finsp_resolve(token)
        if not tgt:
            # Same trap as Invoice Tracking: the cached token may predate a fresh consent grant.
            _finsp_reset()
            token = _graph_app_token(force=True)
            tgt = _finsp_resolve(token)
        if not tgt:
            raise ValueError("could not resolve the Finance SharePoint folder — check the link and Sites consent")
        label = {"claim": "Claims", "travel": "Travel"}.get(kind, "Payments")
        base = [x for x in (tgt["rel"].split("/") if tgt["rel"] else []) if x]
        # Don't create Payments/Payments. Admins usually point the setting straight at the folder for
        # the dominant kind ("…/Shared Documents/Payments"), so if the configured folder is ALREADY
        # named for this kind, use it rather than nesting an identically named child inside it.
        if base and base[-1].strip().lower() == label.lower():
            segs = base + time.strftime("%Y/%m").split("/") + [_finsp_ref(item, kind)]
        else:
            segs = base + [label] + time.strftime("%Y/%m").split("/") + [_finsp_ref(item, kind)]
        rel = "/".join(segs)
        _invtrack_sp_ensure_dir(tgt["drive"], rel, token)   # creates every missing level, like invoices
        name = _sp_safe_leaf(item.get("attachmentName") or (_finsp_ref(item, kind) + ".pdf"), "")
        path = "/".join(urllib.parse.quote(x) for x in (rel.split("/") + [name]))
        if len(raw) > 4 * 1024 * 1024:
            it = _graph_upload_session(tgt["drive"], path, token, raw, ct)
        else:
            url = "https://graph.microsoft.com/v1.0/drives/" + tgt["drive"] + "/root:/" + path + ":/content"
            it = _graph_put_bytes(url, token, raw, ct)
        _FINSP_HEALTH.update({"at": _now_iso(), "ok": _FINSP_HEALTH["ok"] + 1,
                              "lastError": "", "lastUrl": (it or {}).get("webUrl", "")})
        return (it or {}).get("webUrl") or None
    except Exception as e:
        _FINSP_HEALTH.update({"at": _now_iso(), "failed": _FINSP_HEALTH["failed"] + 1,
                              "lastError": _graph_err_text(e)[:300]})
        return None


def _invtrack_sp_diagnose():
    """Run the WHOLE SharePoint archive path end-to-end and report exactly which stage fails, so an
       admin configuring the folder link gets a real answer instead of silence. Writes (and then
       removes) a tiny probe file, which is the only way to prove write consent actually works.
       Returns {ok, stages:[{key,label,ok,detail}], folder}. Never raises."""
    folder = (db.get_setting("portal_invtrackSpUrl", "") or "").strip()
    stages = []

    def add(key, label, ok, detail=""):
        stages.append({"key": key, "label": label, "ok": bool(ok), "detail": str(detail)[:300]})
        return ok

    if not add("config", "SharePoint folder link is set", bool(folder),
               folder or "No link configured — paste the folder URL above and Save."):
        return {"ok": False, "stages": stages, "folder": ""}
    if not add("secret", "Server has the Microsoft app credentials", _invtrack_app_ready(),
               "" if _invtrack_app_ready() else "TK_M365_CLIENT_SECRET / client id / tenant id missing on the server."):
        return {"ok": False, "stages": stages, "folder": folder}

    _invtrack_sp_reset()          # a test must never be answered from a stale negative cache
    try:
        # force=True is the whole point of this button. An app-only token carries the roles that
        # existed WHEN IT WAS MINTED, and it lives ~1h. Right after an admin grants Sites.ReadWrite.All
        # the cached token still has no Sites role, so Graph keeps returning 403 and the test reports
        # "not working" on a tenant that is now correct — with a restart as the only apparent cure.
        token = _graph_app_token(force=True)
        add("token", "Signed in to Microsoft (app-only)", True)
    except Exception as e:
        add("token", "Signed in to Microsoft (app-only)", False, _graph_err_text(e))
        return {"ok": False, "stages": stages, "folder": folder}

    # --- URL shape (accepts the browser's Forms/AllItems.aspx?id=… view URL too) ---
    try:
        host, site_path, folder_rel = _sp_parse_folder(folder)
        add("url", "Folder link is a valid SharePoint site path", True, "site " + site_path + " · folder /" + (folder_rel or "(library root)"))
    except Exception as e:
        add("url", "Folder link is a valid SharePoint site path", False, str(e)[:300])
        return {"ok": False, "stages": stages, "folder": folder}

    # --- site + drive (needs Sites.Read.All at minimum) ---
    try:
        site = _graph_get("https://graph.microsoft.com/v1.0/sites/" + host + ":" + site_path, token)
        site_id = site.get("id")
        if not site_id:
            raise ValueError("site not found")
        add("site", "Found the SharePoint site", True, site.get("displayName") or site_path)
    except Exception as e:
        add("site", "Found the SharePoint site", False, _graph_err_text(e))
        return {"ok": False, "stages": stages, "folder": folder}
    try:
        drive = _graph_get("https://graph.microsoft.com/v1.0/sites/" + site_id + "/drive", token)
        drive_id = drive.get("id")
        if not drive_id:
            raise ValueError("document library not found")
        add("drive", "Opened the document library", True, drive.get("name") or "Documents")
    except Exception as e:
        add("drive", "Opened the document library", False, _graph_err_text(e))
        return {"ok": False, "stages": stages, "folder": folder}

    # --- write test into this month's folder (proves Sites.ReadWrite.All consent) ---
    now = datetime.utcnow()
    base_segs = [s for s in folder_rel.split("/") if s] + [now.strftime("%Y"), now.strftime("%m")]
    ym_label = "/" + "/".join(base_segs)
    try:
        _invtrack_sp_ensure_dir(drive_id, "/".join(base_segs), token)
        add("folder", "Created / found this month's folder", True, ym_label)
    except Exception as e:
        add("folder", "Created / found this month's folder", False, _graph_err_text(e))
        return {"ok": False, "stages": stages, "folder": folder}

    probe = "_humiley-portal-connection-test.txt"
    ppath = "/".join(urllib.parse.quote(s) for s in (base_segs + [probe]))
    try:
        payload = ("Humiley Portal — Invoice Tracking archive connection test.\nWritten %s UTC. Safe to delete.\n"
                   % now.strftime("%Y-%m-%d %H:%M:%S")).encode("utf-8")
        _graph_put_bytes("https://graph.microsoft.com/v1.0/drives/" + drive_id + "/root:/" + ppath
                         + ":/content?@microsoft.graph.conflictBehavior=replace", token, payload, "text/plain")
        add("write", "Wrote a test file (Sites.ReadWrite.All consent OK)", True, ym_label + "/" + probe)
    except Exception as e:
        add("write", "Wrote a test file (Sites.ReadWrite.All consent OK)", False, _graph_err_text(e))
        return {"ok": False, "stages": stages, "folder": folder}
    try:                                   # tidy up our own probe; failure here doesn't matter
        req = urllib.request.Request("https://graph.microsoft.com/v1.0/drives/" + drive_id + "/root:/" + ppath,
                                     method="DELETE", headers={"Authorization": "Bearer " + token})
        urllib.request.urlopen(req, timeout=30)
    except Exception:
        pass
    return {"ok": True, "stages": stages, "folder": folder, "target": ym_label}


def _invtrack_sp_backfill(limit=1000):
    """Archive to SharePoint every already-captured file that has no spUrl yet. Without this, turning
       the archive ON only affects invoices that arrive AFTER it is configured — the weeks of invoices
       already sitting in the portal would never reach SharePoint. Idempotent + bounded; returns counts."""
    if not (db.get_setting("portal_invtrackSpUrl", "") or "").strip():
        return {"ok": False, "error": "not_configured"}
    uploaded = skipped = failed = 0
    with _INVTRACK_LOCK:
        docs = [d for d in db.list_collection("invtrack") if isinstance(d.get("items"), list)]
        docs.sort(key=lambda d: len(d.get("items") or []), reverse=True)
        if not docs:
            return {"ok": True, "uploaded": 0, "skipped": 0, "failed": 0, "remaining": 0}
        cur = docs[0]
        changed = False
        remaining = 0
        for it in (cur.get("items") or []):
            for f in (it.get("files") or []):
                if not isinstance(f, dict):
                    continue
                if f.get("spUrl"):
                    continue
                fid = f.get("id"); kind = f.get("kind")
                if not (re.fullmatch(r"[0-9a-f]{1,64}", str(fid or "")) and kind in _INVTRACK_FILE_CT):
                    continue
                if uploaded >= limit:                    # bound one pass; the button can be pressed again
                    remaining += 1
                    continue
                path = os.path.abspath(os.path.join(_INVTRACK_FILE_DIR, fid + "." + kind))
                if not (path.startswith(os.path.abspath(_INVTRACK_FILE_DIR) + os.sep) and os.path.isfile(path)):
                    skipped += 1
                    continue
                try:
                    with open(path, "rb") as fh:
                        raw = fh.read()
                except OSError:
                    skipped += 1
                    continue
                sp = _invtrack_sp_upload(raw, f.get("name"), _INVTRACK_FILE_CT.get(kind), it.get("dateISO") or "", fid)
                if sp:
                    f["spUrl"] = sp; uploaded += 1; changed = True
                else:
                    failed += 1
        if changed:
            db.put_collection_item("invtrack", cur)
    return {"ok": True, "uploaded": uploaded, "skipped": skipped, "failed": failed, "remaining": remaining}


def _invtrack_body_fields(html):
    """Best-effort pull from a VN e-invoice NOTIFICATION email body (no attachment): the tra-cứu
       lookup URL + code, invoice no / seller MST, and amounts (before/VAT/after) when clearly
       labelled. Identifiers (digits) are read from the diacritic-folded text; the code keeps its case."""
    out = {"url": "", "code": "", "invNo": "", "serial": "", "taxCode": "", "before": 0, "vat": 0, "after": 0, "fileUrls": []}
    if not html:
        return out
    href_urls = re.findall(r'''(?:href|src)\s*=\s*["']?(https?://[^\s"'<>]+)''', html, re.I)   # links live in the href, not visible text
    raw = re.sub(r"<[^>]+>", " ", html)
    raw = re.sub(r"\s+", " ", raw)
    low = _vn_fold(raw)
    hosts = r"tra-?cuu|tracuu|lookup|hoadon|einvoice|e-invoice|xuathoadon|minvoice|meinvoice|vnpt-invoice|viettel|misa|fpt|easyinvoice|softdreams|bkav|hilo|wininvoice|ehoadon"
    for cand in list(href_urls) + re.findall(r"https?://[^\s\"'<>]+", raw):
        if re.search(hosts, cand, re.I):
            out["url"] = cand.rstrip('.,);:"\''); break
    # DIRECT DOWNLOAD links to the REAL invoice file (PDF/XML) — these need NO CAPTCHA, so following
    # them lets us auto-fetch the invoice + amount instead of a manual lookup. Identify them by the
    # anchor TEXT ("tải …", "download", "PDF", "XML") — note "tải" (download, ả) is distinct from the
    # lookup link's "tại đây … xem ngay" (ạ) even before diacritics are folded — or by the href itself
    # pointing at a file/download endpoint. Only same-provider (SSRF-safe) hosts.
    for am in re.finditer(r'<a\b[^>]*?href\s*=\s*["\']?(https?://[^"\'\s>]+)["\']?[^>]*>(.*?)</a>', html, re.I | re.S):
        href = am.group(1).rstrip('.,);:"\'')
        atext = re.sub(r"<[^>]+>", " ", am.group(2))
        is_dl = bool(re.search(r'tải|download|\bPDF\b|\bXML\b', atext, re.I)) or \
                bool(re.search(r'\.(pdf|xml|zip)(\?|#|$)|/download|/getfile|/export|/tai\b|type=(pdf|xml)|action=(download|export)', href, re.I))
        if is_dl and _invtrack_url_safe(href) and href not in out["fileUrls"]:
            out["fileUrls"].append(href)
    out["fileUrls"].sort(key=lambda u: 0 if re.search(r'pdf|type=pdf', u, re.I) else 1)   # try the PDF first (human-readable + carries the total)
    mc = re.search(r"(?:Mã\s*tra\s*cứu|Mã\s*số\s*bí\s*mật|Mã\s*nhận\s*hóa\s*đơn|Mã\s*bí\s*mật|Lookup\s*code|[?&](?:MTC|sc)=)\s*[:\-]?\s*([0-9A-Za-z]{4,24})", raw + " " + " ".join(href_urls), re.I)
    if mc:
        out["code"] = mc.group(1)
    ms = re.search(r"(?:Ký\s*hiệu|Ky\s*hieu|Serial)\s*(?:hóa\s*đơn)?\s*[:\-]?\s*([0-9A-Z]{5,8})\b", raw, re.I)   # e-invoice serial e.g. C26MME
    if ms:
        out["serial"] = ms.group(1).upper()
    mi = re.search(r"(?:so hoa don|hoa don[^0-9]{0,18}so|so hd|so\s*\(no\.?\)?|invoice\s*(?:no|number|#))\s*[:\-]?\s*0*(\d{1,10})", low)
    if mi:
        out["invNo"] = mi.group(1)
    for g in re.findall(r"(?:ma so thue|mst|tax\s*code)[^0-9]{0,15}(\d{10}(?:-\d{3})?)", low):   # skip Humiley's own (buyer) MST
        if g.split("-")[0] != "0318835868":
            out["taxCode"] = g
            break

    def _amt(labels):
        m = re.search(r"(?:" + labels + r")\s*(?:\([^)]*\))?\s*[:\-]?\s*(?:vnd|vnđ|đ|d)?\s*([0-9][0-9.,]{3,})(?!\s*%)", low)
        if m:
            n = _einv_num(m.group(1))
            if 1000 <= n < 1e12:
                return n
        return 0
    aft = _amt(r"tong (?:tien )?thanh toan|tong cong (?:tien )?thanh toan|tong cong thanh toan|so tien (?:can )?thanh toan|cong tien thanh toan|tong thanh toan|total payment|grand total|amount due|total amount")
    bef = _amt(r"cong tien hang|tong tien truoc thue|tien hang truoc thue|tien truoc thue|thanh tien truoc thue|tong tien chua thue")
    vt = _amt(r"tong tien thue gtgt|tien thue gtgt|tong tien thue|tien thue gtgt|thue gtgt")
    if not aft and bef and vt:
        aft = bef + vt
    if aft:                                    # only trust before/VAT when a real total anchors the summary
        out["after"] = aft
        out["before"] = bef
        out["vat"] = vt
    return out


def _invtrack_item(m, ex):
    """Build one invtrack item from a Graph message + its parsed e-invoice (ex may be None).
       When there is no attachment, fall back to fields parsed from the notification body so the
       invoice is still reachable (lookup URL/code) and identified (invoice no / MST)."""
    fa = ((m.get("from") or {}).get("emailAddress") or {})
    from_addr = (fa.get("address") or "")
    from_name = fa.get("name") or ""
    subject = m.get("subject") or ""
    ex = ex or {}
    bf = _invtrack_body_fields(((m.get("body") or {}).get("content") or "") or (m.get("bodyPreview") or ""))
    after = ex.get("after", 0) or bf.get("after", 0)
    inv_no = ex.get("invNo", "") or bf.get("invNo", "")
    serial = ex.get("serial", "")
    tax = ex.get("taxCode", "") or bf.get("taxCode", "")
    before = ex.get("before", 0) or bf.get("before", 0)
    vat = ex.get("vat", 0) or bf.get("vat", 0)
    code = ex.get("lookupCode", "") or bf.get("code", "")
    url = bf.get("url", "")
    file_url = ex.get("_fileUrl", "") or (bf.get("fileUrls") or [""])[0]   # direct PDF/XML download link from the email
    lookup = ((code or "") + ("  " + url if url else "")).strip()
    extracted = bool(inv_no or serial or after > 0)
    s = _vn_fold(subject + " " + from_name + " " + from_addr)
    invoiceish = extracted or bool(url or code) or any(k in s for k in ["hoa don", "hddt", "invoice", "einvoice", "e-invoice", "hoadon", "xuat hoa don", "gtgt", "vat"])
    from_humiley = "@humiley.com" in from_addr.lower()
    typ = ("Hoá đơn bán ra (Humiley phát hành)" if (from_humiley and invoiceish)
           else "Hoá đơn mua vào (NCC)" if invoiceish else "Khác / không phải hoá đơn")
    rd = (m.get("receivedDateTime") or "")[:10]
    method = ex.get("method") or ("attachment" if ex.get("_attachName") else ("link" if url else "email"))
    return {"msgId": m.get("internetMessageId") or m.get("id"),
            "dateISO": ex.get("dateISO") or rd, "dateRaw": ex.get("dateRaw") or rd,
            "supplier": ex.get("supplier") or from_name or (from_addr.split("@")[0] if from_addr else ""),
            "invNo": inv_no, "serial": serial, "taxCode": tax,
            "before": before, "vat": vat, "after": after,
            "desc": subject, "attach": ex.get("_attachName", ""), "type": typ,
            "sender": from_addr or from_name, "lookup": lookup, "fileUrl": file_url,
            "files": ex.get("_files") or [],   # real attached PDF/XML/ZIP, served by /api/invtrack/file/<id>
            "method": method,
            "buyerMST": ex.get("buyerMST", ""), "buyerName": ex.get("buyerName", ""),
            "sellerAddr": ex.get("sellerAddr", ""), "buyerAddr": ex.get("buyerAddr", ""),
            "currency": ex.get("currency", ""), "vatRate": ex.get("vatRate", ""),
            "payMethod": ex.get("payMethod", ""), "items": ex.get("items") or [],
            "needsLookup": bool(invoiceish and not (after > 0)), "source": "mailbox"}   # only invoices count toward "need lookup"


def _invtrack_portal_backfill(items, limit=12):
    """During a sync / 'Get all tracks', AUTO-FETCH the real invoice for EXISTING rows that only carry a
       portal lookup (eHoadon / MISA) and have no file yet — so the user doesn't have to click the
       per-row button. Bounded (default 12/run) + a `_portalTried` flag caps retries; for eHoadon it
       re-reads the source email once to recover the serial (Ký hiệu) it needs to build the file URL."""
    if not _invtrack_app_ready():
        return 0
    token_box = [None]
    done = 0
    for it in items:
        if done >= limit:
            break
        if it.get("files") or it.get("_portalTried") == 3:   # bump this int to force a retry of all rows after a fix
            continue
        blob = (it.get("sender") or "") + " " + (it.get("lookup") or "") + " " + (it.get("desc") or "")
        if not re.search(r"ehoadon\.vn|meinvoice\.vn", blob, re.I):
            continue
        mc = re.search(r"(?:MTC[:=\s]*|[?&](?:MTC|sc)=|M[ãa]\s*tra\s*c[ứu]+u[:=\s]*)([0-9A-Za-z]{6,24})", blob, re.I)
        code = mc.group(1) if mc else ""
        serial = it.get("serial") or ""
        invno = str(it.get("invNo") or "")
        murl = re.search(r"https?://[^\s\"'<>]+", blob)
        url = murl.group(0) if murl else ("https://www.meinvoice.vn/" if "meinvoice" in blob.lower() else "https://tchd.ehoadon.vn/")
        is_eh = "ehoadon" in (url + " " + (it.get("sender") or "")).lower()
        # eHoadon needs serial + the REAL invoice-no; the row's stored invNo is often wrong (e.g. "1" from
        # the notification), so re-read the email body and PREFER its values (Ký hiệu / Hóa đơn số / MTC).
        graph_ok = True
        if is_eh and it.get("msgId"):
            try:
                if token_box[0] is None:
                    token_box[0] = _graph_app_token()
                q = ("https://graph.microsoft.com/v1.0/users/" + urllib.parse.quote(INVTRACK["mailbox"]) +
                     "/messages?$filter=internetMessageId eq '" + urllib.parse.quote(str(it["msgId"]).replace("'", "''")) + "'&$select=body&$top=1")
                arr = (_graph_get(q, token_box[0]) or {}).get("value") or []
                if arr:
                    bf = _invtrack_body_fields(((arr[0].get("body") or {}).get("content") or ""))
                    serial = bf.get("serial") or serial
                    invno = bf.get("invNo") or invno
                    code = bf.get("code") or code
            except Exception:
                graph_ok = False   # transient Graph error — retry next run, don't give up on the row
        if not code or (is_eh and not (serial and invno)):
            if graph_ok:           # genuinely can't build the link (email lacks the fields) → stop retrying this row
                it["_portalTried"] = 3
            continue
        raw, ex = _invtrack_fetch_by_url(url, serial, invno, code)
        if not ex:
            it["_portalTried"] = 3   # the portal genuinely returned nothing for this row → stop retrying
            continue
        if raw:
            sf = _invtrack_store_file(raw, (serial or ex.get("serial") or "hoadon") + "-" + (invno or code) + ".pdf", "application/pdf")
            if sf:
                try:
                    sp = _invtrack_sp_upload(raw, sf.get("name"), "application/pdf", it.get("dateISO") or ex.get("dateISO") or "", sf["id"])
                    if sp:
                        sf["spUrl"] = sp
                except Exception:
                    pass
                fs = it.get("files") or []
                if sf["id"] not in {x.get("id") for x in fs}:
                    fs.append(sf)
                it["files"] = fs
                it["attach"] = it.get("attach") or sf["name"]
        for k in ("before", "vat", "after"):
            if (ex.get(k) or 0) > 0:
                it[k] = ex.get(k)
        for k in ("invNo", "serial"):                    # the fetched invoice is authoritative → correct a wrong stored value
            if ex.get(k):
                it[k] = ex.get(k)
        for k in ("taxCode", "dateISO", "dateRaw", "supplier",
                  "buyerName", "buyerMST", "sellerAddr", "buyerAddr", "currency", "payMethod", "vatRate"):
            if ex.get(k) and not it.get(k):
                it[k] = ex.get(k)
        if ex.get("items") and not (it.get("items") or []):
            it["items"] = ex["items"]
        if (it.get("after") or 0) > 0:
            it["needsLookup"] = False
        it["method"] = ex.get("method") or it.get("method")
        done += 1
    return done


def _invtrack_enrich_existing(items, limit=400):
    """One-time BACKFILL: re-read each row's already-stored attachment (xml/zip/pdf) and fill the richer
       fields added later — buyer, addresses, currency, payment method, VAT rate and line items — so
       invoices synced BEFORE the enrichment still show full detail without a re-download. Bounded +
       idempotent via the `_enrichedV2` flag, so it processes each row at most once."""
    done = 0
    for it in items:
        if done >= limit:
            break
        if it.get("_enrichedV2"):
            continue
        if it.get("items") and it.get("buyerName"):     # already rich (freshly parsed) → just mark it
            it["_enrichedV2"] = True
            continue
        ex = None
        for f in (it.get("files") or []):
            fid = f.get("id")
            kind = f.get("kind")
            if not fid or kind not in ("xml", "zip", "pdf"):
                continue
            try:
                with open(os.path.join(_INVTRACK_FILE_DIR, str(fid) + "." + kind), "rb") as fh:
                    raw = fh.read()
            except Exception:
                continue
            if kind == "xml":
                ex = _einv_parse_xml(raw)
            elif kind == "zip":
                exs = _einv_all_from_zip(raw)
                ex = exs[0] if exs else None
            else:
                ex = _einv_from_pdf(raw)
            if ex and (ex.get("items") or ex.get("buyerName")):
                break
        it["_enrichedV2"] = True                          # attempted once — don't retry a fileless/unparseable row forever
        if not ex:
            continue
        for k in ("buyerName", "buyerMST", "sellerAddr", "buyerAddr", "currency", "payMethod", "vatRate", "dateISO"):
            if not it.get(k) and ex.get(k):
                it[k] = ex[k]
        if not (it.get("items") or []) and (ex.get("items") or []):
            it["items"] = ex["items"]
        done += 1
    return done


def _invtrack_audit(trigger, added, needlook, err=""):
    try:
        db.put_collection_item("audit", {
            "ts": _now_iso(), "by": "invtrack-" + trigger, "actor": "invtrack-" + trigger,
            "action": "Invoice mailbox sync", "target": INVTRACK["mailbox"],
            "detail": (("ERROR: " + err) if err else (str(added) + " new invoice(s), " + str(needlook) + " need lookup"))})
    except Exception:
        pass


def _invtrack_sync(trigger="manual"):
    """Read hd@humiley.com/Inbox app-only, extract, de-dupe, MERGE-upsert. Returns a status dict; never raises."""
    if not _invtrack_app_ready():
        return {"ok": False, "error": "not_configured",
                "message": "App-only Graph is not configured. Set TK_M365_CLIENT_SECRET and grant Mail.Read (application) admin consent, or use the in-browser (delegated) sync."}
    with _INVTRACK_LOCK:
        try:
            token = _graph_app_token()
        except Exception as e:
            _invtrack_audit(trigger, 0, 0, err=str(e)[:160])
            return {"ok": False, "error": "token", "message": str(e)[:200]}
        mb = INVTRACK["mailbox"]
        docs = [d for d in db.list_collection("invtrack") if isinstance(d.get("items"), list)]
        docs.sort(key=lambda d: len(d.get("items") or []), reverse=True)
        doc0 = docs[0] if docs else {"kind": "invtrack-dataset", "meta": {}, "items": []}
        cur_by_id0 = {i.get("msgId"): i for i in (doc0.get("items") or []) if i.get("msgId")}
        stored_since = (doc0.get("meta") or {}).get("lastSync", "")
        since = "" if trigger == "manual" else stored_since   # manual "Get all tracks" = full re-scan to backfill existing rows
        base = "https://graph.microsoft.com/v1.0/users/" + urllib.parse.quote(mb)
        url = base + "/mailFolders/inbox/messages?$select=subject,from,receivedDateTime,hasAttachments,internetMessageId,bodyPreview,body&$orderby=receivedDateTime%20desc&$top=40"
        if since:                                     # overlap the watermark so mail-delivery lag isn't skipped (msgId de-dupes)
            url += "&$filter=receivedDateTime%20ge%20" + _iso_minus(since, 15)
        cap = 100 if not since else 8                 # first run / manual re-scan backfills fully; scheduler stays cheap
        new_items = []
        enrich = {}                                   # msgId -> body-extracted item, to backfill already-stored rows
        needlook = 0
        newest = stored_since
        pages = 0
        try:
            link_budget = [20]                         # bound outbound file downloads per sync run
            att_seen = [0]; att_parsed = [0]
            def _fetch_ex(msg):                        # parse EVERY parseable attachment (many invoices per email); else a body file link
                if not msg.get("hasAttachments") and link_budget[0] <= 0:
                    return None
                if not msg.get("hasAttachments"):
                    return _fetch_linked(msg)
                try:
                    # NOTE: no $select — Graph returns 400 on the attachments collection when
                    # contentBytes is $select'ed; the full projection includes contentBytes anyway.
                    aj = _graph_get(base + "/messages/" + urllib.parse.quote(msg["id"], safe="") + "/attachments", token)
                    files = []                                          # every stored PDF/XML/ZIP → shown as a real file link
                    parsed = []                                         # (invoice_dict, its stored file ref) for EVERY invoice found
                    for a in aj.get("value", []):
                        nm = (a.get("name") or "").lower()
                        ct = (a.get("contentType") or "").lower()
                        cb = a.get("contentBytes")
                        if not cb:
                            continue
                        raw = base64.b64decode(cb)
                        sf = _invtrack_store_file(raw, a.get("name"), a.get("contentType"))
                        if sf:
                            sp = _invtrack_sp_upload(raw, a.get("name"), a.get("contentType"), (msg.get("receivedDateTime") or ""), sf["id"])
                            if sp:
                                sf["spUrl"] = sp   # SharePoint archive link (when configured + consented)
                            files.append(sf)
                        exs = []                                        # a ZIP may bundle MANY invoices; an XML/PDF = one
                        if nm.endswith(".xml") or "xml" in ct:
                            r = _einv_parse_xml(raw); exs = [r] if r else []
                        elif nm.endswith(".zip") or "zip" in ct or "compressed" in ct:
                            exs = _einv_all_from_zip(raw)
                        elif nm.endswith(".pdf") or "pdf" in ct:
                            r = _einv_from_pdf(raw)                      # text-layer PDF (no OCR needed)
                            if not r and INVTRACK["ocr_url"]:
                                r = _invtrack_ocr_pdf(raw)               # image-only PDF fallback
                            exs = [r] if r else []
                        for r in exs:
                            if r:
                                r["_attachName"] = a.get("name")
                                parsed.append((r, sf))
                    invoices = _invtrack_dedupe_invoices(parsed)         # collapse same-invoice XML+PDF, keep distinct invoices apart
                    if invoices:
                        attributed = {f.get("id") for inv in invoices for f in (inv.get("_files") or [])}
                        leftover = [f for f in files if f.get("id") not in attributed]   # non-parsing files → onto the primary row
                        primary = invoices[0]
                        primary["_files"] = (primary.get("_files") or []) + leftover
                        extra = [inv for inv in invoices[1:] if str(inv.get("invNo") or "").strip()]   # only well-identified extras
                        if extra:
                            primary["_extra"] = extra                    # additional DISTINCT invoices → one extra row each
                        return primary
                    if files:
                        # attachments were captured but none parsed cleanly — still surface the files, and
                        # try the body/link so the amount can come from the notification text.
                        lk = _fetch_linked(msg) or {}
                        lk["_files"] = files
                        lk.setdefault("_attachName", files[0]["name"])
                        return lk
                except Exception:
                    pass
                return _fetch_linked(msg)
            def _fetch_linked(msg):                    # follow the email's OWN download links (tải PDF/XML) — no CAPTCHA; bounded
                if link_budget[0] <= 0:
                    return None
                body = ((msg.get("body") or {}).get("content") or "") or (msg.get("bodyPreview") or "")
                bf = _invtrack_body_fields(body)
                # 0) Issuer portals that serve the file PUBLICLY by the lookup code (Bkav eHoadon, MISA
                #    meInvoice): fetch the REAL invoice (no CAPTCHA), attach it, and fill every field.
                from_addr0 = (((msg.get("from") or {}).get("emailAddress") or {}).get("address") or "").lower()
                lu0 = bf.get("url") or ""
                if link_budget[0] > 0 and bf.get("code") and re.search(r"ehoadon\.vn|meinvoice\.vn", lu0 + " " + from_addr0, re.I):
                    link_budget[0] -= 1
                    hint = lu0 if re.search(r"https?://", lu0) else ("https://www.meinvoice.vn/" if "meinvoice" in (lu0 + from_addr0) else "https://tchd.ehoadon.vn/")
                    raw, ex = _invtrack_fetch_by_url(hint, bf.get("serial"), bf.get("invNo"), bf.get("code"))
                    if ex:
                        if raw:
                            nm = (bf.get("serial") or ex.get("serial") or "hoadon") + "-" + (bf.get("invNo") or ex.get("invNo") or bf.get("code")) + ".pdf"
                            sf = _invtrack_store_file(raw, nm, "application/pdf")
                            if sf:
                                sp = _invtrack_sp_upload(raw, sf.get("name"), "application/pdf", (msg.get("receivedDateTime") or ""), sf["id"])
                                if sp:
                                    sf["spUrl"] = sp
                                ex["_files"] = [sf]
                                ex["_attachName"] = sf["name"]
                        return ex
                # 1) the real invoice download links ("tải PDF/XML") — auto-fetch the file + amount, no lookup
                for fu in (bf.get("fileUrls") or []):
                    if link_budget[0] <= 0:
                        break
                    link_budget[0] -= 1
                    ex = _invtrack_fetch_linked(fu)
                    if ex and (ex.get("after") or ex.get("invNo") or ex.get("serial")):
                        ex["_fileUrl"] = fu                # remember the working download link for the UI
                        return ex
                # 2) some providers serve the file straight off the lookup URL — try it as a fallback
                lu = bf.get("url")
                if lu and link_budget[0] > 0:
                    link_budget[0] -= 1
                    ex = _invtrack_fetch_linked(lu)
                    if ex:
                        return ex
                return None
            def _emit_extras(mm, exn, mid_):           # additional DISTINCT invoices in the same email → one row each
                for ex2 in ((exn or {}).get("_extra") or []):
                    it2 = _invtrack_item(mm, ex2)
                    it2["msgId"] = (mid_ or "") + "::" + _inv_ident_str(ex2)   # distinct row key per invoice; deduped by content at merge
                    new_items.append(it2)
            while url and pages < cap:
                j = _graph_get(url, token)
                for m in j.get("value", []):
                    rd = m.get("receivedDateTime", "")
                    if rd and (not newest or rd > newest):
                        newest = rd
                    mid = m.get("internetMessageId") or m.get("id")
                    stored = cur_by_id0.get(mid)
                    if stored is not None:             # already stored -> enrich. A MANUAL re-scan also re-parses the
                        ex = None                      # attachment to backfill a missing amount (e.g. a PDF invoice);
                        # …and to backfill the captured FILE (view-file column + SharePoint archive) onto rows that
                        # predate it — re-fetch once when the amount OR the files are still missing. After the first
                        # manual pass every row has its files, so later manual syncs only re-touch amount-blank rows.
                        if trigger == "manual" and (not (float(stored.get("after") or 0) > 0) or not stored.get("files") or (m.get("hasAttachments") and not stored.get("_multiScanned"))):
                            ex = _fetch_ex(m)           # the scheduler stays cheap (body-only) to avoid per-message cost
                        if m.get("hasAttachments"):
                            att_seen[0] += 1
                            if ex and ex.get("_attachName"):
                                att_parsed[0] += 1
                        ei = _invtrack_item(m, ex)
                        if ex is not None:              # we scanned this email's attachments for additional invoices
                            ei["_multiScanned"] = True
                            _emit_extras(m, ex, mid)    # add any not-yet-stored extra invoices (deduped by content at merge)
                        enrich[mid] = ei
                        continue
                    exn = _fetch_ex(m)
                    if m.get("hasAttachments"):
                        att_seen[0] += 1
                        if exn and exn.get("_attachName"):
                            att_parsed[0] += 1
                    item = _invtrack_item(m, exn)
                    new_items.append(item)
                    if item.get("needsLookup"):
                        needlook += 1
                    _emit_extras(m, exn, mid)           # extra distinct invoices in the same email get their own rows
                url = j.get("@odata.nextLink", "")
                pages += 1
        except Exception as e:
            _invtrack_audit(trigger, len(new_items), needlook, err=str(e)[:160])
            return {"ok": False, "error": "graph", "message": str(e)[:200], "added": len(new_items)}
        # RE-READ right before write so a concurrent browser import/delegated-sync isn't clobbered (both are additive).
        fresh = [d for d in db.list_collection("invtrack") if isinstance(d.get("items"), list)]
        fresh.sort(key=lambda d: len(d.get("items") or []), reverse=True)
        cur = fresh[0] if fresh else doc0
        cur_items = cur.get("items") or []
        cur_by_id = {i.get("msgId"): i for i in cur_items if i.get("msgId")}
        def _ckey(x):                                  # content identity for rows lacking a msgId (e.g. Excel-imported)
            inv = x.get("invNo") or ""
            tax = (x.get("taxCode") or "").split("-")[0]
            return (inv, tax, x.get("dateISO") or "") if (inv and tax) else None   # invNo+seller-MST is unique per seller; avoids false-dedup
        seen_ckey = set(filter(None, (_ckey(i) for i in cur_items)))
        added = 0
        for it in new_items:
            ck = _ckey(it)
            if (it.get("msgId") and it["msgId"] in cur_by_id) or (ck is not None and ck in seen_ckey):
                continue                               # dedupe by msgId AND by content (prevents import+sync double-count)
            cur_items.append(it)
            if it.get("msgId"):
                cur_by_id[it["msgId"]] = it
            if ck is not None:
                seen_ckey.add(ck)
            added += 1
        enriched = 0                                   # backfill already-stored rows with newly-extractable fields (never overwrite good data)
        for mid, bfi in enrich.items():
            ex_item = cur_by_id.get(mid)
            if not ex_item:
                continue
            ch = False
            if not ex_item.get("lookup") and bfi.get("lookup"):
                ex_item["lookup"] = bfi["lookup"]; ch = True
            for f in ("invNo", "serial", "taxCode", "attach", "supplier"):
                if not ex_item.get(f) and bfi.get(f):
                    ex_item[f] = bfi[f]; ch = True
            if bfi.get("files") and not ex_item.get("files"):   # attach the real files to an already-stored row
                ex_item["files"] = bfi["files"]; ch = True
            if not (float(ex_item.get("after") or 0) > 0) and (float(bfi.get("after") or 0) > 0):
                ex_item["after"] = bfi["after"]; ex_item["needsLookup"] = False; ch = True
            for f in ("before", "vat"):
                if not (float(ex_item.get(f) or 0) > 0) and (float(bfi.get(f) or 0) > 0):
                    ex_item[f] = bfi[f]; ch = True
            if bfi.get("method") == "link" and (ex_item.get("method") in (None, "", "email")):
                ex_item["method"] = "link"; ch = True
            if bfi.get("_multiScanned"):
                ex_item["_multiScanned"] = True   # remember we've scanned this email's attachments for extra invoices (bounds re-fetch)
            if ch:
                enriched += 1
        cur_items = _invtrack_collapse(cur_items)   # fold any blank-notification + filled duplicate rows
        _invtrack_enrich_existing(cur_items)        # backfill richer detail (buyer/items/…) onto pre-enrichment rows
        _invtrack_portal_backfill(cur_items)        # AUTO-FETCH existing eHoadon/MISA portal rows (file + amounts), bounded
        needlook = sum(1 for it in cur_items if it.get("needsLookup"))   # report ALL outstanding, not only newly-added
        cur_meta = cur.get("meta") or {}
        cur_meta.update({"mailbox": mb, "company": cur_meta.get("company", "CÔNG TY TNHH HUMILEY VIỆT NAM (MST 0318835868)"),
                         "lastSync": (newest or stored_since) if not url else stored_since, "lastSyncRun": _now_iso(), "lastTrigger": trigger})
        cur["items"] = cur_items
        cur["meta"] = cur_meta
        cur["kind"] = "invtrack-dataset"
        db.put_collection_item("invtrack", cur)
        if added or enriched:                          # don't spam the audit trail on empty runs
            _invtrack_audit(trigger, added, needlook)
        return {"ok": True, "added": added, "enriched": enriched, "needLookup": needlook, "total": len(cur_items),
                "lastSync": cur_meta["lastSync"], "attach": att_seen[0], "parsed": att_parsed[0], "pdfEngine": _pdf_engine_ok()}


def _code_of(x):
    """The VN e-invoice tra-cứu lookup CODE from a row's desc/lookup — a unique per-invoice id, so a
       forwarded notification and the real invoice (with amount) share it and can be merged."""
    blob = _vn_fold((x.get("desc") or "") + " " + (x.get("lookup") or ""))
    m = re.search(r"(?:ma tra cuu|ma nhan hoa don|ma so bi mat|tra cuu|lookup code|[?&]code=)\s*[:=]?\s*([0-9a-z]{6,24})", blob)
    return m.group(1) if m else ""


def _invtrack_merge_pair(dst, src):
    """Fold src into dst: keep amounts > 0; take the REAL invoice's identity (whichever row has the
       invoice number) for supplier/invNo/serial/desc; fill any other blank field."""
    def num(v):
        try:
            return float(v or 0)
        except Exception:
            return 0.0
    for f in ("before", "vat", "after"):
        if not (num(dst.get(f)) > 0) and num(src.get(f)) > 0:
            dst[f] = num(src.get(f))
    src_better = bool(src.get("invNo")) and not dst.get("invNo")   # src is the real invoice, dst was a bare forward/notification
    for f in ("invNo", "serial", "taxCode", "supplier", "desc", "attach"):
        if (src_better and src.get(f)) or (not dst.get(f) and src.get(f)):
            dst[f] = src.get(f)
    for f in ("lookup", "msgId", "sender", "dateISO", "dateRaw"):
        if not dst.get(f) and src.get(f):
            dst[f] = src.get(f)
    if num(dst.get("after")) > 0:
        dst["needsLookup"] = False


def _invtrack_collapse(items):
    """Merge duplicate rows for the SAME invoice — e.g. a blank notification row (no invoice-no) and
       the filled import/reference row. Match on invNo+MST, invNo+date, or date+description-prefix;
       never merge two rows that both carry DIFFERENT invoice numbers."""
    def keys(x):
        inv = str(x.get("invNo") or "").strip()
        tax = str(x.get("taxCode") or "").split("-")[0].strip()
        d = str(x.get("dateISO") or "").strip()
        desc = _vn_fold(x.get("desc") or "")[:36]
        code = _code_of(x)
        ks = []
        if code:
            ks.append(("co", code))
        if inv and tax:
            ks.append(("it", inv, tax))
        if inv and d:
            ks.append(("id", inv, d))
        if d and len(desc) >= 8:
            ks.append(("dd", d, desc))
        return ks
    def conflict(a, b):
        ia = str(a.get("invNo") or "").strip(); ib = str(b.get("invNo") or "").strip()
        ta = str(a.get("taxCode") or "").split("-")[0].strip(); tb = str(b.get("taxCode") or "").split("-")[0].strip()
        if ia and ib and ia != ib:
            return True                                # two different invoice numbers = not the same invoice
        if ta and tb and ta != tb and ta != "0318835868" and tb != "0318835868":
            return True                                # two different (real) seller MSTs
        return False
    canon = {}
    out = []
    for x in items:
        target = None
        for k in keys(x):
            c = canon.get(k)
            if c is not None and not conflict(c, x):
                target = c; break
        if target is None:
            out.append(x)
            for k in keys(x):
                canon.setdefault(k, x)
        else:
            _invtrack_merge_pair(target, x)
            for k in keys(target):
                canon.setdefault(k, target)
    return out


def _invtrack_import(body):
    """MERGE imported invoice rows (from a GDT / accounting / tracker export) into the invtrack doc:
       fill blank amounts on the matching email-tracked row (by invoice-no + seller-MST, or invoice-no
       + date), add rows we have never seen, and NEVER overwrite good data or drop mailbox-synced rows.
       Runs under the same lock + re-read as the sync, so it can't clobber a concurrent sync."""
    rows = (body or {}).get("items")
    ow = bool((body or {}).get("overwrite"))           # manual inline edit = authoritative; bulk import = fill-blank only
    if not isinstance(rows, list):
        return {"ok": False, "error": "bad_input", "message": "No rows to import."}
    def _keys(x):                                  # match on msgId, else invoice-no + seller-MST OR invoice-no + date
        ks = []
        mid = str(x.get("msgId") or "").strip()
        if mid:
            ks.append(("m", mid))
        inv = str(x.get("invNo") or "").strip()
        tax = str(x.get("taxCode") or "").split("-")[0].strip()
        d = str(x.get("dateISO") or "").strip()
        if inv and tax:
            ks.append(("it", inv, tax))
        if inv and d:
            ks.append(("id", inv, d))
        desc = _vn_fold(x.get("desc") or "")[:36]
        if d and len(desc) >= 8:
            ks.append(("dd", d, desc))
        code = _code_of(x)
        if code:
            ks.append(("co", code))
        return ks
    def _num(v):
        try:
            return float(v or 0)
        except Exception:
            return 0.0
    OWN_MST = "0318835868"                          # Humiley's own (buyer) MST — never a supplier's
    with _INVTRACK_LOCK:
        docs = [d for d in db.list_collection("invtrack") if isinstance(d.get("items"), list)]
        docs.sort(key=lambda d: len(d.get("items") or []), reverse=True)
        cur = docs[0] if docs else {"kind": "invtrack-dataset", "meta": {}, "items": []}
        cur_items = _invtrack_collapse(cur.get("items") or [])   # clean any existing blank+filled duplicates first
        index = {}
        for it in cur_items:
            for k in _keys(it):
                index.setdefault(k, it)
        added = updated = 0
        for r in rows:
            if not isinstance(r, dict):
                continue
            rk = _keys(r)
            ex = None
            for k in rk:
                if k in index:
                    ex = index[k]; break
            if ex:
                ch = False
                for f in ("before", "vat", "after"):
                    rv = _num(r.get(f))
                    if rv > 0 and (ow or not (_num(ex.get(f)) > 0)):
                        ex[f] = rv; ch = True
                for f in ("invNo", "serial", "taxCode", "supplier"):
                    if not ex.get(f) and r.get(f):
                        ex[f] = r.get(f); ch = True
                # correct a wrong seller MST that was actually Humiley's own (buyer) MST
                if str(ex.get("taxCode") or "").split("-")[0] == OWN_MST and r.get("taxCode") and str(r.get("taxCode")).split("-")[0] != OWN_MST:
                    ex["taxCode"] = r.get("taxCode"); ch = True
                if _num(ex.get("after")) > 0:
                    ex["needsLookup"] = False
                if ch:
                    updated += 1
            else:
                item = {"msgId": "", "dateISO": r.get("dateISO") or "", "dateRaw": r.get("dateRaw") or "",
                        "supplier": r.get("supplier") or "", "invNo": r.get("invNo") or "", "serial": r.get("serial") or "",
                        "taxCode": r.get("taxCode") or "", "before": _num(r.get("before")), "vat": _num(r.get("vat")),
                        "after": _num(r.get("after")), "desc": r.get("desc") or "", "attach": r.get("attach") or "",
                        "type": r.get("type") or "Hoá đơn mua vào (NCC)", "sender": r.get("sender") or "",
                        "lookup": r.get("lookup") or "", "method": "import",
                        "needsLookup": not (_num(r.get("after")) > 0), "source": "import"}
                cur_items.append(item)
                for k in _keys(item):
                    index.setdefault(k, item)
                added += 1
        cur_meta = cur.get("meta") or {}
        cur_meta.update({"lastImport": _now_iso()})
        cur_meta.setdefault("mailbox", INVTRACK["mailbox"])
        cur_meta.setdefault("company", "CÔNG TY TNHH HUMILEY VIỆT NAM (MST 0318835868)")
        cur["items"] = cur_items
        cur["meta"] = cur_meta
        cur["kind"] = "invtrack-dataset"
        db.put_collection_item("invtrack", cur)
        if added or updated:
            _invtrack_audit("import", added, 0)
        return {"ok": True, "added": added, "updated": updated, "total": len(cur_items)}


def _invtrack_portal_fetch(body):
    """On-demand (a button on a tracked row): pull the REAL invoice PDF from BKAV eHoadon, store it,
       fill amounts/date/parties, and attach the file — so an EXISTING row (synced before auto-fetch,
       or a CAPTCHA-notification row) gets its data + file with one click. Accepts {msgId} (re-reads
       the source email to recover the serial when the row lacks it) or explicit {serial,invNo,code}."""
    def _n(v):
        try:
            return float(v or 0)
        except Exception:
            return 0.0
    b = body or {}
    msgid = str(b.get("msgId") or "").strip()
    serial = str(b.get("serial") or "").strip()
    invno = str(b.get("invNo") or "").strip()
    code = str(b.get("code") or "").strip()
    with _INVTRACK_LOCK:
        docs = [d for d in db.list_collection("invtrack") if isinstance(d.get("items"), list)]
        docs.sort(key=lambda d: len(d.get("items") or []), reverse=True)
        cur = docs[0] if docs else None
        row = None
        if cur and msgid:
            for it in (cur.get("items") or []):
                if it.get("msgId") == msgid:
                    row = it
                    break
        if row:
            serial = serial or row.get("serial") or ""
            invno = invno or str(row.get("invNo") or "")
            blob = (row.get("desc") or "") + " " + (row.get("lookup") or "")
            if not code:
                mc = re.search(r"(?:MTC[:=\s]*|[?&](?:MTC|sc)=|M[ãa]\s*tra\s*c[ứu]+u[:=\s]*)([0-9A-Za-z]{6,24})", blob, re.I)
                code = mc.group(1) if mc else ""
            if not invno:
                mi = re.search(r"(?:hóa\s*đơn\s*số|số\s*hd|invoice)\D{0,6}0*(\d{1,10})", blob, re.I)
                invno = mi.group(1) if mi else ""
        # serial lives in the email BODY, not the subject/row — re-read the source message if we must
        if not serial and msgid and _invtrack_app_ready():
            try:
                token = _graph_app_token()
                q = ("https://graph.microsoft.com/v1.0/users/" + urllib.parse.quote(INVTRACK["mailbox"]) +
                     "/messages?$filter=internetMessageId eq '" + urllib.parse.quote(msgid.replace("'", "''")) +
                     "'&$select=body,subject&$top=1")
                arr = (_graph_get(q, token) or {}).get("value") or []
                if arr:
                    bf = _invtrack_body_fields(((arr[0].get("body") or {}).get("content") or ""))
                    serial = bf.get("serial") or serial          # PREFER the email body — the row's stored
                    code = bf.get("code") or code                # invNo is often the wrong "1" from the note
                    invno = bf.get("invNo") or invno
            except Exception:
                pass
        # pick the issuer portal from the row's lookup URL / sender
        _blob = ((row or {}).get("desc") or "") + " " + ((row or {}).get("lookup") or "")
        _snd = ((row or {}).get("sender") or "")
        url = ""
        _mu = re.search(r"https?://[^\s\"'<>]+", _blob)
        if _mu:
            url = _mu.group(0)
        if not url:
            if "meinvoice" in (_blob + " " + _snd).lower():
                url = "https://www.meinvoice.vn/"
            elif "ehoadon" in (_blob + " " + _snd).lower():
                url = "https://tchd.ehoadon.vn/"
        is_eh = "ehoadon" in (url + " " + _snd).lower()
        if not code or (is_eh and not (serial and invno)):
            return {"ok": False, "message": ("Couldn't build the portal link — got serial='%s' invNo='%s' code='%s' from the row + email. eHoadon needs all three (the Ký hiệu is often missing from the notification email); MISA needs only the code. If the portal has a CAPTCHA, use 'Attach invoice file'." % (serial, invno, code))}
        raw, ex = _invtrack_fetch_by_url(url, serial, invno, code)
        if not ex:                                       # ex is what matters; the PDF file (raw) is a bonus
            host = (url.split("/")[2] if "//" in url else url)
            return {"ok": False, "message": ("The portal (%s) returned nothing for serial='%s' invNo='%s' code='%s' — the values may be wrong, or it needs a CAPTCHA. Use 'Attach invoice file' instead." % (host, serial, invno, code))}
        sf = None
        if raw:
            sf = _invtrack_store_file(raw, (serial or ex.get("serial") or "hoadon") + "-" + (invno or code) + ".pdf", "application/pdf")
            if sf:
                try:
                    sp = _invtrack_sp_upload(raw, sf.get("name"), "application/pdf", (row.get("dateISO") if row else "") or "", sf["id"])
                    if sp:
                        sf["spUrl"] = sp
                except Exception:
                    pass
        if row is None and cur is not None:
            row = {"msgId": msgid, "type": "Hoá đơn mua vào (NCC)", "source": "portal", "desc": ""}
            cur.setdefault("items", []).append(row)
        if row is None:
            return {"ok": False, "message": "No invoice dataset to update."}
        for k in ("before", "vat", "after"):
            if _n(ex.get(k)) > 0:
                row[k] = _n(ex.get(k))
        for k in ("invNo", "serial", "taxCode", "dateISO", "dateRaw", "supplier",
                  "buyerName", "buyerMST", "sellerAddr", "buyerAddr", "currency", "payMethod", "vatRate"):
            if ex.get(k) and not row.get(k):
                row[k] = ex.get(k)
        if ex.get("items") and not (row.get("items") or []):
            row["items"] = ex["items"]
        if sf:
            fs = row.get("files") or []
            if sf["id"] not in {x.get("id") for x in fs}:
                fs.append(sf)
            row["files"] = fs
            row["attach"] = row.get("attach") or sf["name"]
        if _n(row.get("after")) > 0:
            row["needsLookup"] = False
        row["method"] = ex.get("method") or "portal"
        db.put_collection_item("invtrack", cur)
        return {"ok": True, "before": row.get("before"), "vat": row.get("vat"), "after": row.get("after"),
                "file": (sf or {}).get("name"), "items": len(row.get("items") or []),
                "invNo": row.get("invNo"), "serial": row.get("serial")}


def _invtrack_attach_file(body):
    """UNIVERSAL fallback: attach a manually-downloaded invoice file (XML/PDF/ZIP) to a tracked row and
       auto-parse it. For providers we can't auto-fetch (a CAPTCHA-gated VNPT lookup, EasyInvoice, any
       new issuer), the user opens the portal, downloads the file, and uploads it here — we store it,
       fill every field, and it shows in the list like a fetched one. Accepts {msgId, name, contentB64}."""
    def _n(v):
        try:
            return float(v or 0)
        except Exception:
            return 0.0
    b = body or {}
    msgid = str(b.get("msgId") or "").strip()
    name = (str(b.get("name") or "invoice").strip() or "invoice")[:120]
    try:
        raw = base64.b64decode((b.get("contentB64") or "").split(",")[-1], validate=False)
    except Exception:
        raw = b""
    if not raw:
        return {"ok": False, "message": "Empty file."}
    if len(raw) > _INVTRACK_FILE_MAX:
        return {"ok": False, "message": "File too large (max 8 MB)."}
    low = name.lower()
    ct = ("application/xml" if low.endswith(".xml") else "application/zip" if low.endswith(".zip")
          else "application/pdf" if low.endswith(".pdf") else "")
    if not ct:                                          # sniff by content when the name has no extension
        head = raw[:8]
        if head[:5] == b"%PDF-":
            ct = "application/pdf"; name += ".pdf"
        elif head[:2] == b"PK":
            ct = "application/zip"; name += ".zip"
        elif raw.lstrip()[:1] == b"<":
            ct = "application/xml"; name += ".xml"
        else:
            return {"ok": False, "message": "Please upload the invoice XML, PDF or ZIP file."}
    ex = None
    if "xml" in ct:
        ex = _einv_parse_xml(raw)
    elif "zip" in ct:
        exs = _einv_all_from_zip(raw)
        ex = exs[0] if exs else None
    else:
        ex = _einv_from_pdf(raw)
    with _INVTRACK_LOCK:
        docs = [d for d in db.list_collection("invtrack") if isinstance(d.get("items"), list)]
        docs.sort(key=lambda d: len(d.get("items") or []), reverse=True)
        cur = docs[0] if docs else None
        if cur is None:
            return {"ok": False, "message": "No invoice dataset to update."}
        row = None
        for it in (cur.get("items") or []):
            if msgid and it.get("msgId") == msgid:
                row = it
                break
        if row is None:
            return {"ok": False, "message": "Row not found — reopen the invoice and retry."}
        sf = _invtrack_store_file(raw, name, ct)
        if sf:
            try:
                sp = _invtrack_sp_upload(raw, sf.get("name"), ct, row.get("dateISO") or "", sf["id"])
                if sp:
                    sf["spUrl"] = sp
            except Exception:
                pass
            fs = row.get("files") or []
            if sf["id"] not in {x.get("id") for x in fs}:
                fs.append(sf)
            row["files"] = fs
            row["attach"] = row.get("attach") or sf["name"]
        if ex:
            for k in ("before", "vat", "after"):
                if _n(ex.get(k)) > 0:
                    row[k] = _n(ex.get(k))
            for k in ("invNo", "serial", "taxCode", "dateISO", "dateRaw", "supplier",
                      "buyerName", "buyerMST", "sellerAddr", "buyerAddr", "currency", "payMethod", "vatRate"):
                if ex.get(k) and not row.get(k):
                    row[k] = ex.get(k)
            if ex.get("items") and not (row.get("items") or []):
                row["items"] = ex["items"]
            if _n(row.get("after")) > 0:
                row["needsLookup"] = False
        db.put_collection_item("invtrack", cur)
        return {"ok": True, "file": (sf or {}).get("name"), "parsed": bool(ex),
                "after": row.get("after"), "items": len(row.get("items") or [])}


def _invtrack_scheduler():
    """Background thread: sync every INVTRACK['interval'] minutes (24/7, app-only). Never dies on error."""
    while True:
        time.sleep(INVTRACK["interval"] * 60)
        try:
            if _invtrack_app_ready():
                _invtrack_sync("scheduler")
        except Exception:
            pass


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
    # Site-report PDFs from contractors run to 10-15 MB, and base64 inflates them by a third, so a
    # single 15 MB attachment arrives as ~20 MB and a daily report may carry one per contractor. The
    # body is read into memory, so this is a real memory ceiling, not a formality — the browser
    # refuses anything over 45 MB of attachments first, which keeps the rejection somewhere the user
    # can act on it. Files stored in SharePoint never come through here at all.
    MAX_BODY = 64 * 1024 * 1024   # reject request bodies larger than 64 MB (memory-safety)

    # -- io helpers ---------------------------------------------------------
    # gzip text responses: the single-file app HTML is ~1.6 MB raw — uncompressed it took
    # seconds per open on 4G (the "app feels flat/slow on mobile" complaint). ~5x smaller gzipped.
    GZIP_TYPES = ("text/", "application/json", "application/javascript", "application/manifest+json", "image/svg+xml")

    def _accepts_gzip(self):
        return "gzip" in (self.headers.get("Accept-Encoding") or "")

    def _emit_sec_headers(self, ctype):
        """Baseline security headers for EVERY response, plus CSP + Permissions-Policy on HTML
        documents only (both are meaningless on JSON/static assets). The CSP allowlists exactly the
        CDNs/APIs the app really loads (cdnjs, MSAL, Graph, Google Fonts, unpkg/Leaflet, OSM/Nominatim,
        SharePoint, Teams webhook) and locks down object-src / base-uri / form-action / frame-ancestors
        — defence-in-depth on top of the output-escaping. 'unsafe-inline'/'unsafe-eval' stay until the
        inline scripts move to nonces (a modularisation follow-up). HSTS is added at the TLS edge by
        Caddy — not here — since it must only be emitted over HTTPS (the app also serves plain HTTP
        in demo/local runs). Called from _send AND _serve_file so the HTML shell is covered too."""
        self.send_header("X-Content-Type-Options", "nosniff")
        self.send_header("X-Frame-Options", "SAMEORIGIN")
        self.send_header("Referrer-Policy", "strict-origin-when-cross-origin")
        if ctype.startswith("text/html"):
            self.send_header("Content-Security-Policy", _CSP)
            self.send_header("Permissions-Policy",
                             "geolocation=(self), camera=(), microphone=(), payment=(), usb=()")

    def _send(self, body, ctype, status=200, cache=None):
        gz = (
            len(body) > 1024
            and self._accepts_gzip()
            and any(ctype.startswith(t) for t in self.GZIP_TYPES)
        )
        if gz:
            # Level 1, not 6. This runs on the request thread holding the GIL, so on a small VPS
            # a multi-MB portfolio JSON at level 6 blocks every other in-flight request. Level 1
            # gives most of the saving for a fraction of the CPU.
            body = gzip.compress(body, 1)
        self.send_response(status)
        self.send_header("Content-Type", ctype)
        if gz:
            self.send_header("Content-Encoding", "gzip")
        self.send_header("Vary", "Accept-Encoding")
        if cache:
            self.send_header("Cache-Control", cache)
        self._emit_sec_headers(ctype)
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        self.wfile.write(body)

    def _json(self, obj, status=200):
        self._send(json.dumps(obj).encode("utf-8"), "application/json; charset=utf-8", status)

    def _err(self, msg, status=400):
        self._json({"error": msg}, status)

    def _body(self):
        try:
            n = int(self.headers.get("Content-Length", 0))
        except (TypeError, ValueError):
            return {}   # a malformed Content-Length is treated as an empty body, not a 500
        if n <= 0:
            return {}   # 0 or a negative length -> empty body (a negative n would make rfile.read block)
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

    def _auth_logout(self):
        """Revoke the caller's session token server-side. Sign-out was client-only (it just cleared
        localStorage/MSAL), so a stay-signed-in token stayed valid on the server for up to 30 days and
        could be replayed if it had been exfiltrated before logout. Idempotent — always returns ok."""
        auth = self.headers.get("Authorization", "")
        token = auth[7:].strip() if auth.startswith("Bearer ") else ""
        key = _tok_hash(token)
        if token and key in SESSIONS:
            SESSIONS.pop(key, None)
            _persist_sessions()
        return self._json({"ok": True})

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
                    self._emit_sec_headers(ctype)
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
            self._emit_sec_headers(ctype)
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
        self._emit_sec_headers(ctype)
        self.end_headers()
        self.wfile.write(body)

    def log_message(self, fmt, *args):
        print("%s - %s" % (self.address_string(), fmt % args))

    # -- routing ------------------------------------------------------------
    # do_* are thin wrappers so ANY unhandled exception in routing is captured (ring buffer +
    # structured log + optional webhook alert) and turned into a clean 500 instead of a reset
    # connection. The real routing lives in _do_get/_do_post/_do_patch/_do_delete.
    def do_GET(self):    self._serve_request("GET", self._do_get)
    def do_POST(self):   self._serve_request("POST", self._do_post)
    def do_PATCH(self):  self._serve_request("PATCH", self._do_patch)
    def do_DELETE(self): self._serve_request("DELETE", self._do_delete)

    def _client_ip(self):
        # Behind exactly one trusted reverse proxy (Caddy on this VPS: `reverse_proxy app:8000`),
        # Caddy APPENDS the real transport peer as the LAST X-Forwarded-For hop. The leftmost
        # entries are client-supplied and fully spoofable, so we must NOT trust them for rate-limit
        # keying or the loopback exemption (a request carrying `X-Forwarded-For: 127.0.0.1` would
        # otherwise become throttle-exempt, and rotating the left value would mint unlimited buckets).
        # Take the rightmost (Caddy-added) hop instead. If there is no proxy header at all (direct
        # localhost hit — health probes, the in-process test harness), fall back to the socket peer.
        xff = self.headers.get("X-Forwarded-For")
        if xff:
            hops = [h.strip() for h in xff.split(",") if h.strip()]
            if hops:
                return hops[-1]
        try:
            return self.client_address[0]
        except Exception:
            return "?"

    def _rate_check(self, bucket, limit, window):
        """Return True if allowed; on breach, emit 429 and return False. Loopback (health probes,
        the in-process test harness, the server itself) is never throttled."""
        ip = self._client_ip()
        if ip in ("127.0.0.1", "::1", "localhost") or ip.startswith("127."):
            return True
        if _rate_allow(bucket + ":" + ip, limit, window):
            return True
        try:
            self._err("Too many requests — please slow down and try again.", 429)
        except Exception:
            pass
        return False

    def send_response_only(self, code, message=None):
        self._resp_status = code    # stash the status for the per-request metrics recorder
        return super().send_response_only(code, message)

    def _serve_request(self, method, fn):
        _t0 = time.time()
        self._resp_status = 0
        try:
            if method != "GET" and not self._rate_check("write", 240, 60):
                return   # write flood / cheap DoS guard (per real client IP, ~4/sec sustained)
            return fn()
        except (BrokenPipeError, ConnectionResetError):
            return   # client hung up mid-response — not an application error
        except Exception as e:
            self._resp_status = 500
            email = None
            try:
                u = self._user()
                email = u.get("email") if u else None
            except Exception:
                pass
            try:
                _record_error(method, getattr(self, "path", "?"), e, email)
            except Exception:
                pass
            try:
                self._err("Something went wrong. The team has been notified.", 500)
            except Exception:
                pass   # headers may already be on the wire; nothing more we can do
        finally:
            try:
                _metrics_record(_metrics_route(method, getattr(self, "path", "/")),
                                self._resp_status or 200, (time.time() - _t0) * 1000.0)
            except Exception:
                pass

    def _do_get(self):
        p = urlparse(self.path)
        path, qs = p.path, parse_qs(p.query)

        # Public health probe for uptime monitors (UptimeRobot/Pingdom/etc.) — no auth, cheap DB ping.
        if path == "/api/health":
            # Real readiness (shell whole + DB usable), not just "SQLite answered". Body is purely
            # ADDITIVE — status/db/version/uptime_s/time keep their meaning for existing monitors,
            # tests and the runbooks; `shell` and `detail` are new.
            h = _health_probe()
            return self._json({"status": "ok" if h["ok"] else "degraded", "db": h["db"],
                               "shell": h["shell"], "detail": h["detail"],
                               "version": _app_version(), "uptime_s": int(time.time() - _STARTED_AT),
                               "time": datetime.utcnow().isoformat() + "Z"},
                              200 if h["ok"] else 503)
        if path == "/api/admin/errors":   # admin-only review of recent unhandled errors
            return self._guard(lambda u: self._admin_errors(u))
        if path == "/api/admin/metrics":  # admin-only request telemetry (latency / error-rate / per-route)
            return self._guard(lambda u: self._metrics_report(u))
        if path == "/api/admin/audit/verify":  # admin-only tamper-evidence check of the audit hash chain
            return self._guard(lambda u: self._audit_verify(u))

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
            # Require the resolved path to be strictly INSIDE STATIC_DIR. Compare against
            # STATIC_DIR + os.sep so a sibling like ".../static-evil" can't satisfy a bare
            # startswith(STATIC_DIR) (the invtrack file guards already do this).
            if not safe.startswith(STATIC_DIR + os.sep):
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
                               "hrSpUrl": db.get_setting("portal_hrSpUrl", "") or "",
                               # Procurement app URL (the separate procurement portal — an app of
                               # this portal, opened from the sidebar for granted users).
                               "procurementUrl": db.get_setting("portal_procurementUrl", "") or "",
                               # App version = mtime of the served HTML (changes on every deploy). The
                               # client polls this and reloads the PWA when it changes, so an installed
                               # app never keeps running stale code after an update.
                               "appVersion": _app_version()})
        if path == "/api/me":
            u = self._user()
            return self._json(u) if u else self._err("Not authenticated.", 401)
        if path == "/api/procurement/sso":
            # Mint a signed SSO token for the current user to open the Procurement app seamlessly.
            return self._guard(lambda u: self._procurement_sso_token(u))
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
        if path == "/api/pm/chat/summary":
            return self._guard(lambda u: self._pm_chat_summary(u))
        if path == "/api/hr/compliance":
            return self._guard(lambda u: self._hr_compliance_ep(u))
        if path.startswith("/api/hr/exit/") and path.endswith("/settlement"):
            _xid = path[len("/api/hr/exit/"):-len("/settlement")]
            return self._guard(lambda u: self._exit_settlement(u, urllib.parse.unquote(_xid)))
        if path == "/api/hr/certificates/review":
            return self._guard(lambda u: self._certificates_review_ep(u, qs))
        if path == "/api/hr/contracts/review":
            return self._guard(lambda u: self._contracts_review_ep(u, qs))
        if path == "/api/hr/leave-entitlement":
            return self._guard(lambda u: self._leave_entitlement_ep(u, qs))
        if path == "/api/hr/overtime":
            return self._guard(lambda u: self._ot_summary_ep(u, qs))
        if path.startswith("/api/employees/") and path.endswith("/history"):
            _eid = path[len("/api/employees/"):-len("/history")]
            return self._guard(lambda u: self._emp_history_ep(u, urllib.parse.unquote(_eid)))
        if path.startswith("/api/hr/doc/") and path.endswith("/file"):
            _did = path[len("/api/hr/doc/"):-len("/file")]
            return self._guard(lambda u: self._hr_doc_file_ep(u, urllib.parse.unquote(_did)))
        if path == "/api/myspace/summary":
            return self._guard(lambda u: self._myspace_summary(u))
        if path == "/api/exec/summary":
            return self._guard(lambda u: self._exec_summary(u))
        if path == "/api/exec/trends":
            return self._guard(lambda u: self._exec_trends(u))
        if path == "/api/invtrack/status":
            return self._guard(lambda u: self._invtrack_status(u))
        if path == "/api/health/integrations":
            return self._guard(lambda u: self._health_integrations(u))
        if path.startswith("/api/invtrack/file/"):
            seg = path[len("/api/invtrack/file/"):]
            fid, _dot, ext = seg.partition(".")
            return self._guard(lambda u: self._invtrack_file(u, fid, ext.lower()))
        if path == "/api/esign/pin/all":
            return self._guard(lambda u: self._json({"pins": db.all_pin_statuses()}), manager=True)
        if path.startswith("/api/coll/"):
            name = path[len("/api/coll/"):].split("/")[0]
            return self._guard(lambda u: self._coll_list(u, name))
        return self._err("Not found.", 404)

    def _do_post(self):
        path = urlparse(self.path).path
        body = self._body()
        # Brute-force guard on sign-in: at most ~20 attempts / minute per real client IP.
        if path in ("/api/auth/demo", "/api/auth/m365", "/api/esign", "/api/esign/pin"):
            if not self._rate_check("auth", 20, 60):
                return
        if path == "/api/auth/demo":
            return self._auth_demo(body)
        if path == "/api/auth/m365":
            return self._auth_m365(body)
        if path == "/api/auth/logout":
            return self._auth_logout()
        if path == "/api/invtrack/sync":
            return self._guard(lambda u: self._invtrack_sync_ep(u))
        if path == "/api/invtrack/sptest":
            return self._guard(lambda u: self._invtrack_sptest_ep(u))
        if path == "/api/invtrack/spbackfill":
            return self._guard(lambda u: self._invtrack_spbackfill_ep(u))
        if path == "/api/finsp/backfill":
            return self._guard(lambda u: self._finsp_backfill_ep(u))
        if path == "/api/finsp/test":
            return self._guard(lambda u: self._finsp_test_ep(u))
        if path == "/api/hr/jd":
            return self._guard(lambda u: self._hr_jd_ep(u, body))
        if path == "/api/hr/onboarding/file":
            return self._guard(lambda u: self._hr_onb_file_ep(u, body))
        if path.startswith("/api/hr/exit/") and path.endswith("/settlement"):
            _xid = path[len("/api/hr/exit/"):-len("/settlement")]
            return self._guard(lambda u: self._exit_settlement(u, urllib.parse.unquote(_xid),
                                                               create=True, body=body), manager=True)
        if path == "/api/hr/leave-entitlement/apply":
            return self._guard(lambda u: self._leave_entitlement_apply_ep(u, body), manager=True)
        if path == "/api/hr/history-repair":
            return self._guard(lambda u: self._emp_history_repair_ep(u), manager=True)
        if path == "/api/hr/history-backfill":
            return self._guard(lambda u: self._emp_history_backfill_ep(u), manager=True)
        if path == "/api/hr/employee-folders":
            return self._guard(lambda u: self._hr_emp_folders_ep(u))
        if path == "/api/hr/remind":
            return self._guard(lambda u: self._hr_remind_ep(u))
        if path == "/api/hr/policy-migrate":
            return self._guard(lambda u: self._hr_policy_migrate_ep(u))
        if path == "/api/invtrack/import":
            return self._guard(lambda u: self._invtrack_import_ep(u, body))
        if path == "/api/invtrack/portal_fetch":
            return self._guard(lambda u: self._invtrack_portal_fetch_ep(u, body))
        if path == "/api/invtrack/attach_file":
            return self._guard(lambda u: self._invtrack_attach_file_ep(u, body))
        if path == "/api/appr/emailtest":
            return self._guard(lambda u: self._appr_email_test(u))
        if path == "/api/appr/remind":
            return self._guard(lambda u: self._appr_remind_ep(u))
        if path == "/api/pm/chat/read":
            return self._guard(lambda u: self._pm_chat_read(u, body))
        if path == "/api/appr/digesttest":
            return self._guard(lambda u: self._appr_digest_test(u))
        if path == "/api/tk/nudgetest":
            return self._guard(lambda u: self._tk_nudge_test(u))
        if path == "/api/monthly/test":
            return self._guard(lambda u: self._monthly_test(u))
        if path == "/api/esign":
            return self._guard(lambda u: self._esign(u, body))
        if path == "/api/esign/pin":
            return self._guard(lambda u: self._pin_dispatch(u, body))
        if path == "/api/attendance/checkin":
            return self._guard(lambda u: self._checkin(u, body))
        if path == "/api/attendance/checkout":
            return self._guard(lambda u: self._checkout(u, body))
        if path.startswith("/api/attendance/") and path.endswith("/amend"):
            _aid = path[len("/api/attendance/"):-len("/amend")]
            return self._guard(lambda u: self._attendance_amend(u, _aid, body), manager=True)
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
        if path == "/api/devices/ack-backfill":
            return self._guard(lambda u: self._device_ack_backfill_ep(u), manager=True)
        # Narrow, Finance-only backfill of beneficiary bank details on a DECIDED payment. Deliberately
        # NOT `manager=True`: that tests the raw role column, which both admits every dept manager and
        # would exclude an Editor whose role is 'staff'. The level check inside the handler is the gate.
        if path == "/api/payments/bankdetails":
            return self._guard(lambda u: self._pay_bank_backfill(u, body))
        if path == "/api/employees":
            return self._guard(lambda u: self._emp_create(u, body), manager=True)
        if path == "/api/zones":
            return self._guard(lambda u: self._json({"id": db.create_zone(body)}), manager=True)
        if path.startswith("/api/coll/"):
            name = path[len("/api/coll/"):].split("/")[0]
            # `hrdocs` is exempt from the blunt role=="manager" door so it can reach _coll_add, where
            # _is_hr_admin is the real gate. Being NAMED as HR is the grant, and the HR officer who
            # writes the policies is often plain staff — this guard would refuse her at the route
            # before the grant was ever consulted. Same reason `devices` is exempt on PATCH.
            return self._guard(lambda u: self._coll_add(u, name, body),
                               manager=(name not in self.STAFF_WRITE and name != "hrdocs"))
        return self._err("Not found.", 404)

    def _do_patch(self):
        path = urlparse(self.path).path
        body = self._body()
        if path == "/api/me":
            return self._guard(lambda u: self._me_update(u, body))
        if path == "/api/portal":
            return self._guard(lambda u: self._portal_update(u, body), manager=True)
        if path.startswith("/api/coll/"):
            seg = path[len("/api/coll/"):].split("/")
            nm = seg[0]
            # devices: let it reach _coll_update so the OWNER can append a receipt-acknowledgment
            # signature (staff self-service); _coll_update still blocks every other staff device write.
            return self._guard(lambda u: self._coll_update(u, nm, seg[1] if len(seg) > 1 else "", body), manager=(nm not in self.STAFF_WRITE and nm not in ("onboarding", "devices", "hrdocs") and not nm.startswith("crm_")))
        if path.startswith("/api/employees/"):
            eid = path.rsplit("/", 1)[1]
            return self._guard(lambda u: self._emp_update(u, eid, body), manager=True)
        if path.startswith("/api/leave/"):
            lid = path.rsplit("/", 1)[1]
            if not lid.isdigit():
                return self._err("Invalid leave id.", 400)
            return self._guard(lambda u: self._leave_status(u, lid, body), manager=True)
        if path.startswith("/api/zones/"):
            zid = path.rsplit("/", 1)[1]
            if not zid.isdigit():
                return self._err("Invalid zone id.", 400)
            return self._guard(lambda u: self._zone_update(zid, body), manager=True)
        return self._err("Not found.", 404)

    def _do_delete(self):
        path = urlparse(self.path).path
        if path.startswith("/api/coll/"):
            seg = path[len("/api/coll/"):].split("/")
            return self._guard(lambda u: self._coll_delete(u, seg[0], seg[1] if len(seg) > 1 else ""), manager=(seg[0] not in self.STAFF_WRITE and seg[0] != "hrdocs" and not seg[0].startswith("crm_")))
        if path.startswith("/api/employees/"):
            eid = path.rsplit("/", 1)[1]
            return self._guard(lambda u: self._emp_delete(u, eid), manager=True)
        if path.startswith("/api/zones/"):
            zid = path.rsplit("/", 1)[1]
            if not zid.isdigit():
                return self._err("Invalid zone id.", 400)
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
        # A deactivated employee cannot sign in. Protected super-admins are exempt.
        if (emp.get("status") or "Active").strip().lower() == "inactive" and email not in self.ADMIN_EMAILS:
            return self._err("This account has been deactivated. Please contact HR.", 403)
        token = new_session(emp["id"], emp.get("role", "staff"))
        return self._json({"token": token, "user": dict(emp, role=emp.get("role", "staff"))})

    # -- 21 CFR Part 11 electronic signatures -------------------------------
    @staticmethod
    def _utc_now_ms():
        """UTC to the millisecond. Chat needs it: _utc_now() is 1-second resolution, and rows come back
        ordered by a random uuid id, so two messages posted in the same second would swap places
        between page loads."""
        t = time.time()
        return time.strftime("%Y-%m-%dT%H:%M:%S", time.gmtime(t)) + (".%03dZ" % int((t % 1) * 1000))

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

    @staticmethod
    def _jwt_header(token):
        try:
            import base64
            seg = token.split(".")[0]; seg += "=" * (-len(seg) % 4)
            return json.loads(base64.urlsafe_b64decode(seg).decode("utf-8"))
        except Exception:
            return None

    def _esign_fresh(self, id_token, max_age=600):
        """Validate a FRESH Microsoft 365 ID token for an electronic signature (Part 11 §11.200):
        tenant + audience must match our Entra app, and auth_time must be within max_age seconds —
        proving the user just re-authenticated interactively for this signing.

        Token authenticity: a genuine Entra ID token is a signed RS256 JWT. We reject any token
        that is unsigned (alg=none) or has an empty signature segment — this defeats the trivial
        forge-an-unsigned-JWT attack. Full JWKS RS256 signature verification is layered when the
        `cryptography` library is available (TK_ESIGN_JWKS); otherwise the structural + tenant +
        audience + recency checks stand and the gap is logged (see docs)."""
        parts = (id_token or "").split(".")
        if len(parts) != 3 or not parts[2].strip():
            return False, "The signing sign-in is not a valid signed token."
        hdr = self._jwt_header(id_token) or {}
        if str(hdr.get("alg", "")).lower() in ("none", ""):
            return False, "The signing sign-in is not cryptographically signed."
        ok_sig, sig_err = self._verify_jwt_signature(id_token, hdr)
        if not ok_sig:
            return False, sig_err
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
            # `auth_time` is the ONLY claim that proves an INTERACTIVE re-auth: a silent token refresh
            # advances `iat` but never `auth_time`. Once the Entra app registration emits auth_time as an
            # optional claim (the frontend already requests it), set TK_REQUIRE_AUTH_TIME=1 to HARD-FAIL
            # when it is absent — fully closing the "a silently-refreshed token passes §11.200 recency"
            # gap (see docs). Until then we fall back to `iat`: with prompt=login the token was just
            # minted by a fresh interactive re-auth, so iat is an equally-recent proof for max_age.
            if os.getenv("TK_REQUIRE_AUTH_TIME"):
                return False, "Please re-authenticate to sign — an interactive sign-in is required."
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

    _JWKS_CACHE = {"keys": None, "at": 0}
    _ESIGN_LOCK = threading.Lock()   # serialize signature append (read-modify-write) — no lost sigs

    def _verify_jwt_signature(self, token, hdr):
        """Verify the RS256 signature against the tenant JWKS. Returns (True, None) on success,
        (False, msg) on a definite failure. If the crypto lib or JWKS is unavailable we do NOT
        hard-fail (the structural alg!=none + tenant/aud/recency checks still apply) unless the
        deployment sets TK_ESIGN_REQUIRE_VERIFIED_TOKEN=1, which enforces full verification."""
        require = os.environ.get("TK_ESIGN_REQUIRE_VERIFIED_TOKEN") == "1"
        tid = M365.get("tenantId")
        try:
            from cryptography.hazmat.primitives.asymmetric import padding
            from cryptography.hazmat.primitives import hashes
        except Exception:
            # crypto lib absent: don't hard-fail unless the deployment demands verified tokens
            return (not require), ("Server cannot verify the sign-in signature." if require else None)
        if not tid:
            return (not require), ("Tenant not configured for signature verification." if require else None)
        try:
            now = time.time()
            if not self._JWKS_CACHE["keys"] or now - self._JWKS_CACHE["at"] > 3600:
                url = "https://login.microsoftonline.com/%s/discovery/v2.0/keys" % tid
                with urllib.request.urlopen(url, timeout=5) as r:
                    self._JWKS_CACHE["keys"] = json.loads(r.read()).get("keys", [])
                    self._JWKS_CACHE["at"] = now
            kid = hdr.get("kid")
            jwk = next((k for k in (self._JWKS_CACHE["keys"] or []) if k.get("kid") == kid), None)
            if not jwk:
                return False, "The signing sign-in used an unrecognized key."
            def b64d(v):
                import base64
                return base64.urlsafe_b64decode(v + "=" * (-len(v) % 4))
            n = int.from_bytes(b64d(jwk["n"]), "big"); e = int.from_bytes(b64d(jwk["e"]), "big")
            from cryptography.hazmat.primitives.asymmetric import rsa
            pub = rsa.RSAPublicNumbers(e, n).public_key()
            signing_input = (".".join(token.split(".")[:2])).encode()
            sig = b64d(token.split(".")[2])
            from cryptography.exceptions import InvalidSignature
            try:
                pub.verify(sig, signing_input, padding.PKCS1v15(), hashes.SHA256())
                return True, None
            except InvalidSignature:
                return False, "The signing sign-in signature is invalid."
        except Exception:
            return (not require), ("Could not verify the sign-in signature — please try again." if require else None)

    # -- 3-level approval workflow: Perform (requester) -> Review (direct manager) -> Approve (Management/Director) --
    _LEVEL_RANK = {"staff": 1, "manager": 2, "management": 3, "editor": 4, "admin": 5}
    THREE_LEVEL_COLLS = ("claims", "travel", "payments", "leave")

    # ── Undo window ──────────────────────────────────────────────────────────────────────────────
    # People misclick. For a short time after you sign a DECISION you may sign one reversal of it.
    # The window is measured from the SERVER's own stamp on your signature and from nothing else —
    # a window keyed on a browser clock is defeated by changing the browser clock.
    UNDO_WINDOW_SEC = max(0, int(os.environ.get("TK_UNDO_WINDOW_SEC", "900") or "900"))   # 15 minutes
    # Reacting touches SOMEBODY ELSE'S message, so it is the one edit a non-author may make — and it
    # is confined to a fixed set. An open emoji field would be a free-text write onto another person's
    # record, which is exactly what the author guard exists to prevent.
    CHAT_REACTIONS = ("\U0001F44D", "\u2764\uFE0F", "\U0001F389", "\u2705", "\U0001F440", "\U0001F602")
    # Chat topics are a CLOSED vocabulary, exactly like CHAT_REACTIONS above: what gets stored is a
    # key THIS FILE chose, never a string somebody typed. That is why no escaping, no de-duplicating
    # ("Vat tu" / "Vật tư" / "Materials" for one subject) and no translation hazard applies to it.
    # '' is General and is deliberately NOT a member — it is the absence of a topic, not a topic.
    # ONE-WAY DOOR: a key that has ever shipped stays here. Removing one deletes nothing, it just
    # silently drops the label off every message filed under it.
    PM_CHAT_TOPICS = ("site", "design", "materials", "qaqc", "hse", "cost", "programme", "client")
    # Leave lives in its own table with its own signature store and is handled separately; payruns are
    # deliberately absent — a finalised payroll run stays immutable.
    UNDOABLE_COLLS = ("claims", "travel", "payments",
                      "pm_changes", "pm_procurement_payments", "pm_quality")
    # Which record fields each decision OWNS, and therefore restores. Keyed on setStatus.lower().
    # "paid" carries no "status" on purpose: reversing a disbursement does not rewind the record to
    # Approved, because that would present it to the next payer as though it had never been released.
    _UNDO_FIELDS = {
        "reviewed":  ("status", "reviewedBy", "reviewedById", "reviewedAt", "reviewedOn"),
        "approved":  ("status", "approvedBy", "approvedById", "approvedAt", "approvedOn",
                      "decision", "decidedBy", "decidedOn"),
        "rejected":  ("status", "rejectedBy", "rejectedAt", "decision", "decidedBy", "decidedOn"),
        "certified": ("status", "certifiedBy", "certDate"),
        "closed":    ("status", "verifiedBy", "verifiedOn", "closedDate", "result"),
        "paid":      ("paidOn", "paidBy"),
    }
    # Reversing a disbursement demands a reason, and both accepted reasons assert the money did NOT
    # move. There is deliberately no third option: this feature corrects the record, never the bank.
    UNDO_PAID_REASONS = {
        "wrong-record": "Recorded against the wrong request — no money moved.",
        "not-executed": "The transfer was not executed, or it failed.",
    }
    UNDO_CLOSED_MSG = ("The window to undo this has closed. Nothing was changed. "
                       "File a corrected request — a decided request cannot be reopened.")
    UNDO_MOVED_MSG = ("This record has changed since you signed it, so it can no longer be undone. "
                      "Nothing was changed.")

    def _lvl_rank(self, lvl):
        return self._LEVEL_RANK.get((lvl or "staff"), 1)

    def _is_mgmt(self, u):
        # Use the EFFECTIVE level (_caller_level derives management/manager from role+title when the
        # stored `level` column is NULL — true for seeded/M365-synced managers), not the raw column,
        # so a Director with no explicit level is not mis-treated as staff.
        return self._lvl_rank(self._caller_level(u)) >= self._LEVEL_RANK["management"]

    def _is_approver(self, u):
        # Editor + Admin. This is the FINANCE/PAYROLL tier, NOT "may approve" — see _can_approve.
        # It still gates the one-step review collapse, the payer fallback and payroll.
        return self._lvl_rank(self._caller_level(u)) >= self._LEVEL_RANK["editor"]

    def _can_approve(self, u):
        """May this caller give FINAL APPROVAL on a request?

        Deliberately a lower bar than _is_approver. The access level literally labelled
        "Approver (Management)" could not approve anything — final approval demanded Editor
        (Payroll) or Admin — so promoting somebody to Approver did nothing, and they never even
        appeared in the requester's approver dropdown. The label now means what it says.

        This widens who may APPROVE. It does not widen who may PAY: disbursement is gated
        separately by _is_payer (the named authorised-payers list), so approving and releasing
        money remain two different duties held by different people. Approving your own request,
        and approving one you reviewed yourself, both stay blocked."""
        return self._lvl_rank(self._caller_level(u)) >= self._LEVEL_RANK["management"]

    def _is_payer(self, u):
        """May this caller RELEASE money (mark a request paid)?

        Disbursement is a named duty. When authorised payers are configured, membership of that list
        IS the grant — it both admits someone who is not an Editor/Admin and excludes an Editor/Admin
        who is not on it. With no list configured we fall back to the historical rule (any Editor or
        Admin) so an unconfigured install never locks itself out of paying anything."""
        payers = _payer_emails()
        if payers:
            return (u.get("email") or "").strip().lower() in payers
        return self._is_approver(u)

    def _is_hr_admin(self, u):
        """May this caller publish, edit, archive or withdraw a COMPANY DOCUMENT?

        Editor and Admin always qualify — they already administer the portal, and they are who steps
        in when HR is away. Naming somebody as HR ADDS to that: it admits the HR officer who actually
        writes the policies without having to promote her to Editor first.

        Note the difference from the authorised-payer list this borrows its shape from. That one is
        EXCLUSIVE — being on it is the only way to release money, and an Editor not on it loses that
        power. This one is ADDITIVE. Releasing money is a duty you want narrowed to named people;
        publishing a policy is a job several people already do, and taking it away from the Editors
        who do it today would break a working arrangement to solve a problem nobody has.

        A site manager still cannot publish. Committing every employee to signing something is not a
        thing you inherit by running a department. With nobody named at all it falls back to Approver
        (Management) or above, so an install that never sets this keeps working as it did."""
        _rank = self._level_rank(self._caller_level(u))
        if _rank >= self._level_rank("editor"):          # Editor + Admin, listed or not
            return True
        if (u.get("email") or "").strip().lower() in _hr_admin_emails():
            return True
        # Nobody named — the pre-existing level rule, so an unconfigured install is unchanged.
        return not _hr_admin_emails() and _rank >= self._level_rank(self.HRDOC_MIN)

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
        if s == "payment reversed":
            return "reversed"
        return "submit"   # submitted / pending / partially approved / empty

    @staticmethod
    def _epoch_of(ts):
        """Parse a server _utc_now() stamp back to epoch seconds. UTC, never local."""
        try:
            return calendar.timegm(time.strptime(str(ts), "%Y-%m-%dT%H:%M:%SZ"))
        except (ValueError, TypeError):
            return None

    def _undo_snapshot(self, holder, t):
        """Capture the fields a decision is about to overwrite, so the reversal can put them back.
        `unset` records fields that were ABSENT — restoring those means deleting, not blanking."""
        snap = {"set": {}, "unset": []}
        for k in (self._UNDO_FIELDS.get(t) or ()):
            if k in holder:
                snap["set"][k] = holder[k]
            else:
                snap["unset"].append(k)
        return snap

    @staticmethod
    def _undo_restore(holder, snap):
        for k, v in (snap.get("set") or {}).items():
            holder[k] = v
        for k in (snap.get("unset") or []):
            holder.pop(k, None)

    def _undo_check(self, u, coll, item, sigs):
        """None if this caller may reverse the last signature, else the reason they may not."""
        if coll not in self.UNDOABLE_COLLS:
            return "This kind of record cannot be undone."
        if not sigs:
            return "There is nothing to undo on this record."
        last = sigs[-1]
        # 1. It must be YOUR OWN signature. No admin override and no delegate: undoing is un-saying
        #    something you personally attested to, and nobody else can un-say it for you.
        if not last.get("userId") or last.get("userId") != u.get("id"):
            return self.UNDO_CLOSED_MSG
        # 2. It must be a DECISION, marked as such by the server on the way in — never by the client.
        #    This also refuses undoing an undo, and refuses submissions and amendments.
        if last.get("undo") or last.get("undoKind") != "decision":
            return self.UNDO_CLOSED_MSG
        t = str(last.get("setStatus") or "").strip().lower()
        if t not in self._UNDO_FIELDS or not isinstance(last.get("undoRestore"), dict):
            return self.UNDO_CLOSED_MSG
        # 3. The clock, from the server stamp only, bounded at BOTH ends — a signature dated in the
        #    future is a broken clock, not an open window.
        ts = self._epoch_of(last.get("ts"))
        if ts is None:
            return self.UNDO_CLOSED_MSG
        age = time.time() - ts
        if age < 0 or age > self.UNDO_WINDOW_SEC:
            return self.UNDO_CLOSED_MSG
        # 4. NOTHING may have happened since, on two independent anchors. Status equality catches a
        #    later transition; the revision counter catches a content-only edit that left the status
        #    alone (an admin PATCH, for instance) which status equality cannot see.
        line = None
        if last.get("itemId"):
            lines = item.get("items") if isinstance(item.get("items"), list) else []
            line = next((x for x in lines if x.get("id") == last["itemId"]), None)
            if not line or str(line.get("status") or "").strip().lower() != t:
                return self.UNDO_MOVED_MSG
        elif str(item.get("status") or "").strip().lower() != t:
            return self.UNDO_MOVED_MSG
        if int(item.get("_rev") or 0) != int(last.get("undoRev") or -1):
            return self.UNDO_MOVED_MSG
        # 5. The authority you exercised must still be yours TODAY. Somebody demoted since signing
        #    does not get to keep reaching back into the record.
        if t == "paid" and not self._is_payer(u):
            return "Your authority to release payment has changed — you can no longer reverse this."
        if coll in self.THREE_LEVEL_COLLS:
            if t == "approved" and not self._can_approve(u):
                return "Your approval authority has changed — you can no longer reverse this."
            if t in ("reviewed", "rejected") and u.get("role") != "manager":
                return "Your authority for this step has changed — you can no longer reverse this."
        elif self._level_rank(self._caller_level(u)) < self._level_rank("manager"):
            return "Your authority for this step has changed — you can no longer reverse this."
        return None

    def _appr_check(self, u, coll, cur_status, set_status, sigs, owner_id, owns=None):
        """Enforce the 3-level approval flow. Returns None if allowed, else an error string.
        Review = direct manager; Approve / Paid = Management (Director); Reject = manager at either stage.

        `owns` — whether the caller owns the record, as computed by the caller (ownership is spelled
        differently per collection: empId, createdById, owner, name). Only the STATUS-LESS branch uses
        it; every status transition below is gated on authority, not ownership. Pass None to fall back
        to the empId comparison."""
        t = str(set_status or "").strip().lower()
        # Payroll runs are dual-controlled (owner_id here is the PREPARER, preparedById): only a
        # Director (Management or Admin level) may finalise, and never the person who prepared the run.
        if coll == "payruns":
            if t in ("finalised", "finalized"):
                if self._caller_level(u) not in ("management", "admin"):
                    return "Director approval (Management or Admin level) is required to finalise a payroll run."
                if owner_id and owner_id == u.get("id"):
                    return "The person who prepared a payroll run cannot also finalise it (segregation of duties)."
                if str(cur_status or "").strip().lower() not in ("pending approval", "pending", "prepared"):
                    return "Only a pending payroll run can be finalised."
                return None
            return "A payroll run can only be finalised, via a Director e-signature."
        # Deciding a variation order or certifying an interim payment certificate is a manager act.
        # It used to be gated only in the browser, so any staff account with PM access could PATCH a
        # decision — and an arbitrary signer name — onto any CR. Gated on LEVEL (what the sign button
        # itself checks) rather than the coarse `role` flag, so the two agree.
        if coll in ("pm_changes", "pm_procurement_payments"):
            if t in ("approved", "rejected", "certified") and \
                    self._level_rank(self._caller_level(u)) < self._level_rank("manager"):
                return "Manager access is required to decide a change request or certify a payment certificate."
            return None
        if coll not in self.THREE_LEVEL_COLLS:
            if t in ("approved", "rejected", "paid") and u.get("role") != "manager":
                return "Manager access required to approve, reject or mark paid."
            return None
        cur = self._appr_state(cur_status)
        same_person = owner_id and owner_id == u.get("id")
        if not t:
            # A status-less signature is a SUBMISSION or an AMENDMENT of your OWN still-pending
            # request. It used to `return None` unconditionally, which — combined with the record gate
            # waiving ownership for anyone whose role is "manager", i.e. every level above plain staff
            # — let any non-staff user append their own signature, carrying arbitrary `meaning` text,
            # to ANY claim / travel / payment / leave record, in ANY status, including ones already
            # approved or paid and belonging to somebody else. It could not forge a name (the signer
            # comes from the session) or move money, but it polluted the Part 11 signature
            # manifestation that renders on the record and on the archived PDF, which is precisely the
            # evidence this system exists to keep clean.
            if not (same_person if owns is None else owns):
                return "You can only sign your own request."
            if cur not in ("submit", "review"):
                return "This request has been decided and can no longer be signed. Raise a new one."
            return None
        if t == "reviewed":
            if u.get("role") != "manager":
                return "Manager access required to review this request."
            if cur != "submit":
                return "This request has already been reviewed."
            if same_person:
                return "You cannot review your own request."
            # Review must come from the requester's DIRECT manager (request #6) when one is on
            # record. Anyone who can APPROVE skips this — they can act directly (one step). Using
            # _can_approve rather than _is_approver here keeps the two consistent: it would be
            # nonsense for a Director to be allowed to give final approval but refused the lesser
            # act of reviewing.
            if not self._can_approve(u):
                owner = db.get_employee(owner_id) if owner_id else None
                mgr_email = ((owner or {}).get("managerEmail") or "").lower()
                if mgr_email and mgr_email != (u.get("email") or "").lower():
                    return "Only the requester's direct manager can review this request."
            return None
        if t == "approved":
            if not self._can_approve(u):
                return "Approver access or above is required for final approval."
            # One-step collapse (request #5): an Editor/Admin can approve straight from the
            # submitted state, so a direct manager who is Editor/Admin reviews+approves in one go.
            if cur not in ("submit", "review"):
                return "This request is no longer pending approval."
            if same_person:
                return "You cannot approve your own request."
            reviewer_ids = [s.get("userId") for s in (sigs or [])
                            if str(s.get("setStatus") or "").lower() == "reviewed"        # server-applied (authoritative)
                            or "review" in str(s.get("meaning", "")).lower()]             # legacy sigs fallback
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
            # Disbursement (Mark paid) is restricted to the NAMED authorised payers (portal_apprPayers).
            # An Approver (management) can approve a request but must not release the money; and an
            # Editor/Admin who is not a named payer no longer can either. With no list configured this
            # falls back to the historical "any Editor or Admin".
            if not self._is_payer(u):
                return ("You are not an authorised payer. Only a named payer may release payment — "
                        "an admin can change the list in Company Portal → Approvals.")
            if cur not in ("approved", "reversed"):
                return "Only an approved request can be marked paid."
            if cur == "reversed":
                # This payment was released once and reversed. Releasing it again is a NEW decision,
                # and the person who mis-attested the first one does not get to make it alone.
                _revs = [x.get("userId") for x in (sigs or []) if x.get("undo")]
                if u.get("id") in _revs:
                    return ("You reversed this payment — a different authorised payer must release it. "
                            "Ask a second payer, or raise a fresh payment request.")
            # Disbursement segregation of duties. Paying your OWN request is never allowed (hard rule).
            if same_person:
                return "You cannot release payment on your own request."
            # The person who releases the money must not also be the one who gave final approval.
            # Requires a 2nd Editor/Admin; a single-finance-person org can relax this by setting
            # portal_payerSeparation to "0" (owner!=payer above still holds).
            sep = (db.get_setting("portal_payerSeparation", "") or _APPR_SETTING_DEFAULTS["payerSeparation"]) == "1"
            if sep:
                approver_ids = [s.get("userId") for s in (sigs or [])
                                if str(s.get("setStatus") or "").lower() == "approved"          # server-applied (authoritative)
                                or "approv" in str(s.get("meaning", "")).lower()]               # legacy sigs fallback
                if u.get("id") in approver_ids:
                    # Name the setting. Hitting this mid-signature with no idea what to do next is
                    # the single most confusing refusal in the app — you have the access, you are
                    # simply the wrong person for this one request.
                    return ("A different person must release payment than the one who gave final "
                            "approval. Either have another authorised payer release it, or an admin "
                            "can switch off ‘Disbursement segregation of duties’ in Company Portal → "
                            "Approvals. (Paying your own request stays blocked either way.)")
            return None
        # Any other status is NOT a valid approval transition on a three-level record. Deny it — a
        # requester could otherwise self-sign their OWN record with an intermediate status such as
        # "Pending Approval" (which _appr_state maps to the 'review' state), advancing it past the
        # mandatory manager review with no reviewer signature and collapsing the 3-level control. Only
        # submit (empty t), reviewed, approved, rejected and paid are legitimate here.
        return "This status change isn't a valid approval step."

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
        # Serialize the whole read-append-write so two concurrent approvals on the same record
        # can't each read the item, append one signature, and write — dropping the other's sig.
        with self._ESIGN_LOCK:
            return self._esign_locked(u, body, coll, iid, meaning, set_status)

    def _esign_locked(self, u, body, coll, iid, meaning, set_status):
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
        if set_status:
            # Record the SERVER-applied status transition on the signature. Segregation-of-duties
            # (reviewer != approver) keys off this, not the client-controlled free-text `meaning`
            # (which a signer could word to omit "review" and then approve their own review).
            sig["setStatus"] = set_status
        if auth_time:
            sig["authTime"] = auth_time
        # Optional hand-drawn signature (the visual mark) — a small PNG data-URI drawn in the sign
        # modal. Bounded so a signature can't bloat the record; the PIN/M365 auth above remains the
        # Part 11 identity component, so a missing/oversized image never weakens the signature.
        _sig_img = body.get("sigImage") or ""
        if isinstance(_sig_img, str) and _sig_img.startswith("data:image/png;base64,") and len(_sig_img) <= 260000:
            sig["image"] = _sig_img
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
            _err = self._appr_check(u, "leave", lv.get("status"), set_status, _lsigs, lv.get("emp_id"),
                                    owns=(lv.get("emp_id") == u.get("id")))
            if _err:
                return self._err(_err, 403)
            row = db.append_leave_signature(int(iid), sig, new_status=(set_status or None))
            # Only decrement on a GENUINE transition into 'approved' — `lv` holds the PRE-signature
            # status, so if it was already approved (e.g. via the one-click email link) skip, else the
            # balance would be double-counted for one leave.
            if (set_status or "").lower() == "approved" and (lv.get("status") or "").lower() != "approved":
                self._leave_apply_balance(lv)   # actually decrement annual/sick balance on approval
            db.put_collection_item("audit", {"actor": signer_name, "actorId": u.get("id"),
                "action": "E-signature — " + meaning, "target": "leave/" + str(iid),
                "detail": (set_status or "signed") + " · " + method + (" · auth_time=" + str(auth_time) if auth_time else ""),
                "ts": self._utc_now()})
            _lev = _APPR_EVENT.get(str(set_status or "").strip().lower())               # lifecycle email (best-effort)
            if not _lev and not set_status and lv.get("emp_id") == u.get("id"):
                _lev = "submitted"
            if _lev:
                _lrec = dict(lv); _lrec["status"] = set_status or lv.get("status")
                _appr_notify("leave", _lrec, _lev, signer_name)
            return self._json({"ok": True, "item": {k: v for k, v in (row or {}).items() if k != "token"}})
        if coll not in self.COLLECTIONS:
            return self._err("Unknown collection.", 404)
        item = db.get_collection_item(coll, iid)
        if not item:
            return self._err("Record not found.", 404)
        # A non-manager may only sign a record they OWN. The old gate only checked empId, which is
        # never set on crm_/pm_ records — so `... and item.get("empId") ...` short-circuited to False
        # and let a plain staff user sign/tamper with ANY CRM or PM record they don't own. Now ownership
        # is checked across empId / createdById / owner / name, so a missing empId no longer opens it up.
        # Computed for EVERYONE, not just non-managers: a manager legitimately signs other people's
        # records to approve them, but a signature that carries NO status change is a submission or an
        # amendment, and that is only ever your own. _appr_check needs to know which this is.
        _owns_rec = bool((item.get("empId") and item.get("empId") == u.get("id"))
            or (item.get("createdById") and item.get("createdById") == u.get("id"))
            or (item.get("owner") and item.get("owner") == u.get("name"))
            or ((not item.get("empId")) and item.get("name") and item.get("name") == u.get("name")))
        # A quality record is "owned" by the people the register itself names: whoever raised it
        # and whoever it is assigned to. Without this a QA engineer could never sign the closure
        # of an NCR they were assigned but did not personally raise — which is the normal case.
        if not _owns_rec and coll == "pm_quality":
            _owns_rec = bool((item.get("assignedTo") and item.get("assignedTo") == u.get("name"))
                or (item.get("raisedBy") and item.get("raisedBy") == u.get("name")))
        if u.get("role") != "manager" and not _owns_rec:
            return self._err("You can only sign your own record.", 403)
        # ── Undo ─────────────────────────────────────────────────────────────────────────────────
        # Placed BEFORE the claim-line branch so a request carrying undo:true can never be absorbed
        # by it. An undo reverses exactly one thing — the caller's own last signature — and it does
        # so by APPENDING a reversal, never by touching what is already there.
        if body.get("undo"):
            if body.get("setStatus"):
                return self._err("An undo does not carry a status.", 400)
            if body.get("itemId"):
                # The line an undo addresses comes from the stored signature, which the server wrote.
                # Accepting it from the client would let somebody reverse a line they never signed.
                return self._err("An undo does not carry an item id.", 400)
            _sigs = item.get("signatures") or []
            _err = self._undo_check(u, coll, item, _sigs)
            if _err:
                return self._err(_err, 403)
            last = _sigs[-1]
            t = str(last.get("setStatus") or "").strip().lower()
            reason_code = str(body.get("undoReason") or "").strip()
            if t == "paid":
                if reason_code not in self.UNDO_PAID_REASONS:
                    return self._err("Choose why this payment is being reversed.", 400)
            elif reason_code:
                return self._err("A reason is only recorded when reversing a payment.", 400)

            if last.get("itemId"):
                # Per-line: restore the line, then RE-DERIVE the header. The header status is a
                # rollup, never a snapshot — restoring it verbatim would let it drift from its lines.
                _lines = item.get("items") if isinstance(item.get("items"), list) else []
                _ln = next((x for x in _lines if x.get("id") == last["itemId"]), None)
                self._undo_restore(_ln, last["undoRestore"])
                item["status"] = self._claim_rollup(_lines)
            elif t == "paid":
                # Reversing a disbursement. The slip is EVIDENCE, not decision metadata: it is moved
                # into an append-only list of withdrawn slips rather than deleted, so the system never
                # loses the only proof of payment it holds. paidOn/paidBy are renamed rather than
                # dropped, so the record can still say "was marked paid on X, reversed by Y".
                if item.get("bankSlip"):
                    item.setdefault("voidedBankSlips", []).append({
                        "slip": item.pop("bankSlip"),
                        "name": item.pop("bankSlipName", ""),
                        "reason": reason_code,
                        "note": self.UNDO_PAID_REASONS[reason_code],
                        "sigTs": last.get("ts"),
                        "reversedBy": signer_name,
                        "reversedAt": self._utc_now()})
                if item.get("paidOn"):
                    item["reversedPaidOn"] = item.pop("paidOn")
                if item.get("paidBy"):
                    item["reversedPaidBy"] = item.pop("paidBy")
                self._undo_restore(item, last["undoRestore"])
                # NOT back to Approved. A payment that was once released and reversed must never
                # present to the next payer as though it had never been released.
                item["status"] = "Payment reversed"
            else:
                self._undo_restore(item, last["undoRestore"])

            _restored = str(item.get("status") or "")
            # The reversal carries NO setStatus key. Segregation-of-duties reads setStatus, so a
            # reversal must not enrol its signer as a reviewer or an approver of this record.
            rsig = {"name": signer_name, "email": signer_email, "userId": u.get("id"),
                    "ts": self._utc_now(),
                    "meaning": "Reversal — " + str(last.get("meaning") or ""),
                    "method": method,
                    "undo": True, "undoKind": "reversal",
                    "voidsIndex": len(_sigs) - 1,
                    "voidsTs": last.get("ts"),
                    "voidsSetStatus": last.get("setStatus") or "",
                    "restoredStatus": _restored}
            if last.get("itemId"):
                rsig["itemId"] = last["itemId"]
            if reason_code:
                rsig["undoReason"] = reason_code
            if auth_time:
                rsig["authTime"] = auth_time
            item["signatures"].append(rsig)          # pure append — nothing existing is touched
            saved = db.put_collection_item(coll, item)
            db.put_collection_item("audit", {"actor": signer_name, "actorId": u.get("id"),
                "action": "E-signature reversed — " + rsig["meaning"],
                "target": coll + "/" + str(iid) + (("/item/" + str(last["itemId"])) if last.get("itemId") else ""),
                "detail": ("undo · was " + (last.get("setStatus") or "-") + " · restored " + _restored
                           + " · reversed sig ts=" + str(last.get("ts")) + " · " + method
                           + (" · reason=" + reason_code if reason_code else "")),
                "ts": self._utc_now()})
            return self._json({"ok": True, "undone": True,
                               "item": {k: v for k, v in saved.items() if k != "token"}})

        # Per-line-item signed decision on a claim (itemId present): review / approve / reject one line.
        item_id = body.get("itemId")
        if coll == "claims" and item_id:
            lines = item.get("items") if isinstance(item.get("items"), list) else []
            line = next((x for x in lines if x.get("id") == item_id), None)
            if not line:
                return self._err("Claim item not found.", 404)
            synth = [{"meaning": "review", "userId": line.get("reviewedById")}] if line.get("reviewedById") else []
            _err = self._appr_check(u, "claims", line.get("status") or "Submitted", set_status, synth, item.get("empId"),
                                    owns=_owns_rec)
            if _err:
                return self._err(_err, 403)
            _prev_roll = self._claim_rollup(lines)   # rolled-up status BEFORE this line's change (for one-email-per-transition)
            # Same snapshot, taken against the LINE rather than the header — the header status is
            # derived by _claim_rollup and is never restored from a snapshot (see the undo branch).
            _tl = str(set_status or "").strip().lower()
            if set_status and _tl in self._UNDO_FIELDS:
                sig["undoKind"] = "decision"
                sig["undoRestore"] = self._undo_snapshot(line, _tl)
                sig["undoRev"] = int(item.get("_rev") or 0) + 1
                sig["itemId"] = item_id
            elif not set_status:
                sig["undoKind"] = "submission" if not (item.get("signatures") or []) else "amendment"
            item.setdefault("signatures", []).append(sig)
            if set_status:
                line["status"] = set_status
                if set_status == "Reviewed":
                    line["reviewedBy"] = signer_name; line["reviewedById"] = u.get("id")
                    line.setdefault("reviewedOn", time.strftime("%Y-%m-%d"))
                elif set_status == "Approved":
                    line["approvedBy"] = signer_name
                    line.setdefault("approvedOn", time.strftime("%Y-%m-%d"))
                item["status"] = self._claim_rollup(lines)
            db.put_collection_item("claims", item)
            db.put_collection_item("audit", {"actor": signer_name, "actorId": u.get("id"),
                "action": "E-signature — " + meaning, "target": "claims/" + str(iid) + "/item/" + str(item_id),
                "detail": (set_status or "signed") + " · " + method, "ts": self._utc_now()})
            _cev = _APPR_EVENT.get(str(item.get("status") or "").strip().lower())       # fire on the claim's ROLLED-UP status,
            if _cev and item.get("status") != _prev_roll:                               # ONCE, only when it actually transitions (not per line)
                _appr_notify("claims", item, _cev, signer_name)
            return self._json({"ok": True, "item": {k: v for k, v in item.items() if k != "token"}})
        # For payroll runs the segregation-of-duties owner is the PREPARER (preparedById), not empId
        # (empId on an individual run is the employee the run is FOR).
        _appr_owner = item.get("preparedById") if coll == "payruns" else item.get("empId")
        _err = self._appr_check(u, coll, item.get("status"), set_status, item.get("signatures"), _appr_owner,
                                owns=_owns_rec)
        if _err:
            return self._err(_err, 403)
        # A payment disbursement MUST carry the bank transfer slip (proof of payment). Enforce it BEFORE
        # appending the signature so a slip-less attempt never strands an orphan Paid e-signature. Allow
        # it if the record already holds one (re-signing / an already-attached slip).
        if set_status == "Paid" and coll == "payments":
            _att = body.get("attach") or {}
            _slip = _att.get("bankSlip") if isinstance(_att, dict) else ""
            _has_slip = (isinstance(_slip, str) and _slip.startswith("data:") and len(_slip) <= 21_000_000) or bool(item.get("bankSlip"))
            if not _has_slip:
                return self._err("A bank payment slip is required to mark a payment paid.", 400)
        # Everything a reversal will need, captured BEFORE the decision overwrites it, and stamped by
        # the server. `undoRev` is the revision this write is about to produce (put_collection_item
        # sets cur_rev + 1, and we hold _ESIGN_LOCK) — so any other write landing in between makes the
        # anchors disagree and the window closes, which is the safe direction to fail.
        _t_low = str(set_status or "").strip().lower()
        if set_status and coll in self.UNDOABLE_COLLS and _t_low in self._UNDO_FIELDS:
            sig["undoKind"] = "decision"
            sig["undoRestore"] = self._undo_snapshot(item, _t_low)
            sig["undoRev"] = int(item.get("_rev") or 0) + 1
        elif not set_status:
            sig["undoKind"] = "submission" if not (item.get("signatures") or []) else "amendment"
        item.setdefault("signatures", []).append(sig)
        if set_status:
            item["status"] = set_status
            if coll == "claims" and isinstance(item.get("items"), list):
                for it in item["items"]:
                    if (it.get("status") or "Submitted") in ("Submitted", "Reviewed"):
                        it["status"] = set_status
            if set_status == "Reviewed":
                item["reviewedBy"] = signer_name
                item.setdefault("reviewedOn", time.strftime("%Y-%m-%d"))
            if set_status == "Approved":
                item["approvedBy"] = signer_name
                item.setdefault("approvedOn", time.strftime("%Y-%m-%d"))
            # PMC variation order / interim payment certificate. The signer's name comes from the
            # re-authenticated identity on THIS request, never from the browser — that is the whole
            # difference between this path and the generic PATCH it replaced.
            if coll == "pm_changes" and set_status in ("Approved", "Rejected"):
                item["decision"] = set_status
                item["decidedBy"] = signer_name
                item.setdefault("decidedOn", time.strftime("%Y-%m-%d"))
            if coll == "pm_procurement_payments" and set_status == "Certified":
                item["certifiedBy"] = signer_name
                item.setdefault("certDate", time.strftime("%Y-%m-%d"))
            # Verification of closure on a nonconformance (ISO 9001 §8.7.2) — the authority who
            # accepted the close-out, on the record, rather than a one-click "Pass" by nobody.
            if coll == "pm_quality" and set_status == "Closed":
                item["verifiedBy"] = signer_name
                item["verifiedOn"] = time.strftime("%Y-%m-%d")
                item.setdefault("closedDate", time.strftime("%Y-%m-%d"))
                if not str(item.get("result") or "").strip():
                    item["result"] = "Closed"
            if set_status in ("Finalised", "Finalized") and coll == "payruns":
                item["finalisedBy"] = signer_name                       # the Director who signed off payroll
                item["approvedBy"] = signer_name
                item.setdefault("finalisedOn", time.strftime("%Y-%m-%d"))
            if set_status == "Paid":
                item.setdefault("paidOn", time.strftime("%Y-%m-%d"))
                item["paidBy"] = signer_name
                # Proof of payment: the bank transfer slip attached at Mark-paid rides through THIS
                # authorized disbursement e-signature — decided money records are otherwise immutable to
                # non-admins, so this is the only place it can be attached. Bounded so it can't bloat
                # the record; must be a data: URI (an uploaded file, never a URL/script).
                _att = body.get("attach") or {}
                _slip = _att.get("bankSlip") if isinstance(_att, dict) else ""
                if coll == "payments" and isinstance(_slip, str) and _slip.startswith("data:") and len(_slip) <= 21_000_000:
                    item["bankSlip"] = _slip
                    item["bankSlipName"] = str(_att.get("bankSlipName") or "bank-payment-slip")[:120]
        db.put_collection_item(coll, item)
        db.put_collection_item("audit", {"actor": signer_name, "actorId": u.get("id"),
            "action": "E-signature — " + meaning,
            "target": coll + "/" + str(iid),
            "detail": (set_status or "signed") + " · " + method + (" · auth_time=" + str(auth_time) if auth_time else ""),
            "ts": self._utc_now()})
        # The client cannot compute this itself — its clock is not the one the window is measured
        # against. Hand it the exact deadline the server will enforce.
        _undo_hint = None
        if sig.get("undoKind") == "decision" and self.UNDO_WINDOW_SEC > 0:
            _ts = self._epoch_of(sig.get("ts"))
            if _ts is not None:
                _undo_hint = {"can": True, "coll": coll, "id": iid, "sigTs": sig.get("ts"),
                              "label": set_status, "seconds": self.UNDO_WINDOW_SEC,
                              "until": time.strftime("%Y-%m-%dT%H:%M:%SZ",
                                                     time.gmtime(_ts + self.UNDO_WINDOW_SEC)),
                              "needsReason": (str(set_status or "").lower() == "paid")}
        if coll in self.THREE_LEVEL_COLLS:                        # branded lifecycle email (best-effort)
            _ev = _APPR_EVENT.get(str(set_status or "").strip().lower())
            if not _ev and not set_status and item.get("empId") == u.get("id"):
                _ev = "submitted"
            if _ev:
                _appr_notify(coll, item, _ev, signer_name)
        _resp = {"ok": True, "item": {k: v for k, v in item.items() if k != "token"}}
        if _undo_hint:
            _resp["undo"] = _undo_hint
        return self._json(_resp)

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

        if action == "revoke":   # de-authorize another employee's signing PIN (cannot read/set it)
            # Governance action, triggered from the management-level Signature Governance page — require
            # Management (Approver) level or above, not merely a manager ROLE, so a low-tier "Contributor"
            # can't disrupt a higher-privileged user's ability to e-sign. Matches the UI's own gate.
            if self._level_rank(self._caller_level(u)) < self._level_rank("management"):
                return self._err("Signature governance requires Approver level or above.", 403)
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
        start = qs.get("start", [None])[0]
        end = qs.get("end", [None])[0]
        # Attendance rows carry GPS lat/lon — an out-of-scope read is a privacy leak. Management/Admin
        # see everyone; a STAFF or DIRECT-MANAGER caller sees only their OWN rows + their direct reports'
        # (mirrors _leave_list). A specific emp_id outside that scope is clamped back to self.
        if self._is_mgmt(u):
            rows = db.list_attendance(emp_id=emp_id, start=start, end=end)
        else:
            ids = set([u["id"]] + [r["id"] for r in db.list_reports(u.get("email"))])
            if emp_id:
                if emp_id not in ids:
                    emp_id = u["id"]
                rows = db.list_attendance(emp_id=emp_id, start=start, end=end)
            else:
                rows = [r for r in db.list_attendance(emp_id=None, start=start, end=end) if r.get("emp_id") in ids]
        return self._json({"attendance": rows})

    _RE_DATE = re.compile(r"^\d{4}-\d{2}-\d{2}$")
    _RE_TIME = re.compile(r"^([01]\d|2[0-3]):[0-5]\d$")

    @staticmethod
    def _vn_day(offset_days=0):
        """The company's calendar day (UTC+7) — never trust the server's own timezone."""
        return (datetime.utcnow() + timedelta(hours=7, days=offset_days)).strftime("%Y-%m-%d")

    _PUNCH_SKEW_MIN = 10   # tolerate a device clock a little ahead of the company clock

    @staticmethod
    def _vn_now():
        """Current company (UTC+7) datetime — the server clock, never the device's."""
        return datetime.utcnow() + timedelta(hours=7)

    def _is_future_punch(self, date, t):
        """True if a check-in/out time falls AFTER the company clock (beyond a small skew). A punch may
        be backdated (a late or forgotten punch) but must never be POST-dated — otherwise a future time
        fabricates hours (e.g. a 21:00 check-out entered at 09:05 = a phantom 15-hour shift, which the
        16h overnight cap does not catch on a same day)."""
        try:
            claimed = datetime.strptime((date or "") + " " + (t or ""), "%Y-%m-%d %H:%M")
        except (TypeError, ValueError):
            return False   # malformed — the caller's format/date guards handle it
        return claimed > self._vn_now() + timedelta(minutes=self._PUNCH_SKEW_MIN)

    def _is_workday(self, date):
        """Sundays and company holidays never count as late (advisory lateness only)."""
        try:
            wd = datetime.strptime(date, "%Y-%m-%d").weekday()
            if wd == 6:
                return False
            hol = db.get_setting("portal_holidays") or []
            return date not in {h.get("date") for h in hol if isinstance(h, dict)}
        except Exception:
            return True

    @staticmethod
    def _late_threshold(schedule):
        """Work schedules are ADVISORY: they set the lateness expectation (shift start
        + 15 min grace) and NEVER block a check-in. Flexible/WFH staff are never late;
        employees without an assigned schedule fall back to the standard 08:00 + grace."""
        s = (schedule or "").strip()
        if not s:
            return "08:15"
        if "flex" in s.lower() or "wfh" in s.lower():
            return None
        m = re.search(r"(\d{1,2}):(\d{2})", s)
        if not m:
            return "08:15"
        hh, mm = int(m.group(1)), int(m.group(2)) + 15
        if mm >= 60:
            hh, mm = hh + 1, mm - 60
        return "%02d:%02d" % (hh % 24, mm)

    def _checkin(self, u, body):
        emp_id = u["id"]
        # Record against the COMPANY's day (UTC+7) — never the device's local date. A traveller west of
        # VN whose device still reads "yesterday" was otherwise blocked ("Check-in must be for today").
        date = self._vn_day()
        t = body.get("time")
        if not isinstance(t, str) or not self._RE_TIME.match(t or ""):
            return self._err("Invalid time.")
        if self._is_future_punch(date, t):
            return self._err("Check-in time can't be in the future — enter the actual time you arrived.")
        try:
            lat = float(body.get("lat")) if body.get("lat") is not None else None
            lon = float(body.get("lon")) if body.get("lon") is not None else None
            if lat is not None and not (-90 <= lat <= 90 and -180 <= lon <= 180):
                lat = lon = None
        except (TypeError, ValueError):
            lat = lon = None
        if db.open_attendance(emp_id, date):
            return self._err("Already checked in today.")
        thr = self._late_threshold(u.get("schedule"))
        status = "on-time" if (thr is None or t <= thr or not self._is_workday(date)) else "late"
        # Strip angle brackets from the free-text location server-side (defense-in-depth): the In/Out
        # report escapes it on render, but attendance rows bypass the /api/coll _crm_sanitize path, so
        # neutralise HTML markup here too before it ever reaches storage.
        loc = str(body.get("loc") or "").replace("<", "").replace(">", "")[:120]
        rid = db.clock_in(emp_id, date, t, loc=loc, lat=lat, lon=lon, status=status)
        if rid is None:
            return self._err("Already checked in today.")   # atomic double-tap guard (unique index)
        db.put_collection_item("audit", {"actor": u.get("name"), "actorId": emp_id,
            "action": "Check-in", "target": "attendance/" + str(rid),
            "detail": date + " " + t + " · " + status, "ts": self._utc_now()})
        return self._json({"ok": True, "id": rid, "status": status})

    def _checkout(self, u, body):
        date = body.get("date"); t = body.get("time")
        if not isinstance(t, str) or not self._RE_TIME.match(t or ""):
            return self._err("Invalid time.")
        if not isinstance(date, str) or not self._RE_DATE.match(date or ""):
            date = self._vn_day()
        # A check-out happens now: its time can be backdated but never post-dated past the company
        # clock (a 21:00 check-out entered at 09:05 would otherwise fabricate a ~15h same-day shift).
        if self._is_future_punch(self._vn_day(), t):
            return self._err("Check-out time can't be in the future — enter the actual time.")
        # today's open record first; else yesterday's (overnight/OT shifts checking out after 00:00)
        rec = db.open_attendance_any(u["id"], [self._vn_day(), self._vn_day(-1)])
        if not rec:
            return self._err("No open check-in to close.")
        overnight = rec["date"] != self._vn_day()
        if not overnight and rec.get("clock_in") and t < rec["clock_in"]:
            return self._err("Check-out time is before today's check-in.")
        # Worked span in minutes (the overnight case wraps +24h, matching db._hrs_between).
        try:
            ih, im = map(int, (rec.get("clock_in") or "0:0").split(":"))
            oh, om = map(int, t.split(":"))
            span_min = (oh * 60 + om) - (ih * 60 + im)
            if span_min < 0:
                span_min += 1440
        except (ValueError, AttributeError):
            span_min = 0
        # Guard against a FORGOTTEN check-out from an earlier day: with the overnight +24h wrap, that
        # would otherwise be recorded as a ~19-23h shift (a genuine night shift is <16h). Reject it so
        # HR can correct the record, instead of storing a fabricated overnight.
        if overnight and span_min > 16 * 60:
            return self._err("This looks like a missed check-out from an earlier day (the shift would "
                             "exceed 16 hours). Please ask HR to correct your attendance record.", 400)
        # Optional overtime REQUEST at checkout — pending manager approval; only approved OT counts.
        try:
            ot_hours = float(body.get("otHours") or 0)
        except (TypeError, ValueError):
            return self._err("Invalid overtime hours.")
        if not (0 <= ot_hours <= 16):
            return self._err("Overtime hours must be between 0 and 16.")
        # OT can't exceed the time actually checked in (small grace for minute rounding).
        if span_min > 0 and ot_hours * 60 > span_min + 5:
            return self._err("Overtime (%.1fh) cannot exceed the hours you were checked in (%.1fh)."
                             % (ot_hours, span_min / 60.0), 400)
        hrs = db.clock_out(rec["id"], t, ot_hours=ot_hours,
                           ot_reason=str(body.get("otReason") or "")[:500], overnight=overnight)
        db.put_collection_item("audit", {"actor": u.get("name"), "actorId": u.get("id"),
            "action": "Check-out", "target": "attendance/" + str(rec["id"]),
            "detail": rec["date"] + " → " + t + (" · overnight" if overnight else "") + (" · OT %.1fh requested" % ot_hours if ot_hours else ""),
            "ts": self._utc_now()})
        return self._json({"ok": True, "hrs": hrs, "id": rec["id"],
                           "otStatus": ("pending" if ot_hours else "none")})

    _AMEND_FIELDS = ("clock_in", "clock_out", "ot_hours", "ot_reason", "status")

    def _attendance_amend(self, u, aid, body):
        """Correct an attendance record — and say who corrected it, when, and why.

        Until now there was no way to correct one at all, while check-out told an employee whose
        check-out was missed to "ask HR to correct your attendance record". HR had no such facility,
        so the record simply stayed wrong.

        Attendance is no longer only a timesheet: approved overtime reaches the payslip, so editing
        one of these rows moves money. Three rules follow from that.

          1. A month that a Director has e-signed is CLOSED. Its attendance cannot be amended,
             because the figures built on it are signed and an amendment would change their basis
             with nothing to show for it.
          2. Changing the times or the hours REOPENS the overtime decision. The manager approved a
             particular stretch of work; move it and they have not approved what is now there.
          3. Every amendment carries a reason and lands in the tamper-evident audit chain with the
             before and after. A correction nobody can see is indistinguishable from a falsification.
        """
        rec = db.get_attendance(int(aid)) if str(aid).isdigit() else None
        if not rec:
            return self._err("Attendance record not found.", 404)
        # Their own manager, or Management and above. Not the employee: correcting your own
        # attendance is not a correction, and the hours are now worth money.
        emp = db.get_employee(rec.get("emp_id")) if rec.get("emp_id") else None
        is_direct_mgr = emp and (emp.get("managerEmail") or "").lower() == (u.get("email") or "").lower()
        if not (is_direct_mgr or self._is_mgmt(u)):
            return self._err("Only the employee's direct manager (or Management) can correct an "
                             "attendance record.", 403)
        # Correcting your OWN record is not forbidden — at this size the Managing Director is the top
        # of the chain, and a rule nobody can satisfy would mean their record could never be fixed at
        # all. It is NAMED instead: the audit row says so, which is the accountability that actually
        # bites when somebody reads the trail later.
        self_correction = rec.get("emp_id") == u.get("id")

        reason = str(body.get("reason") or "").strip()
        if len(reason) < 4:
            return self._err("Give a reason for the correction — it goes on the record.", 400)

        _month = str(rec.get("date") or "")[:7]
        if _month and self._payperiod_finalised(self._period_label(_month)):
            return self._err("%s payroll has been finalised and signed, so its attendance can no "
                             "longer be corrected. Raise a payroll adjustment for the next month "
                             "instead." % self._period_label(_month), 403)

        changes, fields = [], {}
        for k in self._AMEND_FIELDS:
            if k not in body:
                continue
            v = body[k]
            if k in ("clock_in", "clock_out"):
                v = str(v or "").strip()
                if v and not self._RE_TIME.match(v):
                    return self._err("%s must be a time like 08:30." % k.replace("_", "-"), 400)
            elif k == "ot_hours":
                try:
                    v = float(v or 0)
                except (TypeError, ValueError):
                    return self._err("Overtime hours must be a number.", 400)
                if not (0 <= v <= 16):
                    return self._err("Overtime hours must be between 0 and 16.", 400)
            else:
                v = str(v or "")[:60]
            if str(rec.get(k) if rec.get(k) is not None else "") != str(v):
                changes.append("%s %s → %s" % (k, rec.get(k) if rec.get(k) not in (None, "") else "—",
                                               v if v not in (None, "") else "—"))
                fields[k] = v
        if not fields:
            return self._json({"ok": True, "unchanged": True, "id": rec.get("id")})

        # Recompute the worked span from whatever the times now are, so `hrs` can never disagree
        # with the clock it is derived from.
        _in = fields.get("clock_in", rec.get("clock_in"))
        _out = fields.get("clock_out", rec.get("clock_out"))
        if _in and _out:
            fields["hrs"] = db._hrs_between(_in, _out, overnight=(_out < _in))

        # Rule 2: the times or the hours moved, so the overtime decision no longer describes what
        # happened. Send it back for a decision rather than carrying an approval across the change.
        reopened = False
        if any(k in fields for k in ("clock_in", "clock_out", "ot_hours")) \
                and str(rec.get("ot_status") or "") == "approved":
            _h = fields.get("ot_hours", rec.get("ot_hours"))
            fields["ot_status"] = "pending" if float(_h or 0) > 0 else ""
            reopened = True

        db.amend_attendance(int(aid), fields, actor=u.get("name") or "", actor_id=u.get("id") or "",
                            reason=reason)
        db.put_collection_item("audit", {
            "actor": u.get("name"), "actorId": u.get("id"),
            "action": "Attendance corrected",
            "target": "attendance/" + str(aid),
            "detail": "%s %s · %s · reason: %s%s"
                      % (rec.get("name") or rec.get("emp_id") or "", rec.get("date") or "",
                         "; ".join(changes), reason[:300],
                         (" · overtime approval reopened" if reopened else "")
                         + (" · SELF-CORRECTION (own record)" if self_correction else "")),
            "ts": self._utc_now()})
        return self._json({"ok": True, "id": rec.get("id"), "otReopened": reopened,
                           "record": db.get_attendance(int(aid))})

    def _period_label(self, ym):
        """'2026-08' → 'August 2026', the form pay runs are stored under."""
        try:
            y, m = str(ym)[:7].split("-")
            return "%s %s" % (self._PAY_MONTHS[int(m) - 1], y)
        except (ValueError, IndexError, TypeError):
            return ""

    def _attendance_ot(self, u, aid, body):
        """Manager approves / rejects a pending overtime request (request #2). Only approved OT
        is added to the system; a rejected request never counts."""
        rec = db.get_attendance(int(aid)) if str(aid).isdigit() else None
        if not rec:
            return self._err("Attendance record not found.", 404)
        if rec.get("emp_id") == u.get("id"):
            return self._err("You cannot approve your own overtime.", 403)
        decision = (body.get("decision") or "approve").lower()
        if decision not in ("approve", "reject"):
            return self._err("Invalid decision.")
        if (rec.get("ot_status") or "") != "pending":
            return self._err("No pending overtime request on this record.")
        # only the employee's direct manager or management/admin may decide (not any manager)
        emp = db.get_employee(rec.get("emp_id")) if rec.get("emp_id") else None
        is_direct_mgr = emp and (emp.get("managerEmail") or "").lower() == (u.get("email") or "").lower()
        if not (is_direct_mgr or self._is_mgmt(u)):
            return self._err("Only the employee's direct manager (or Management) can decide overtime.", 403)

        # Art. 107: approving is the moment the hours become the company's overtime, so it is the
        # moment to measure them against the statutory ceilings — 50% of a normal day, 40 hours a
        # month, 200 a year. A breach does NOT delete the record: hours worked were worked, and
        # refusing to record them just moves the liability off the books where nobody can see it.
        # The approver is told what the approval would break and may proceed only by saying why,
        # and that override is written into the audit chain under their name.
        breaches, override = [], str(body.get("override") or "").strip()
        if decision == "approve":
            try:
                this_h = float(rec.get("ot_hours") or 0)
            except (TypeError, ValueError):
                this_h = 0.0
            d, mo, yr = self._ot_totals_for(rec.get("emp_id"), rec.get("date"), exclude_id=rec.get("id"))
            caps = overtime.cap_check(d + this_h, mo + this_h, yr + this_h,
                                      annual_cap=_ot_annual_cap())
            breaches = caps["breaches"]
            if breaches and not override:
                return self._json({"ok": False, "capBreach": True, "breaches": breaches,
                                   "dayHours": round(d + this_h, 2), "monthHours": round(mo + this_h, 2),
                                   "yearHours": round(yr + this_h, 2),
                                   # 422, not 409: in this API a 409 means "somebody else changed
                                   # this record", and the client says exactly that. Nothing changed
                                   # here — the request is understood and refused on its merits.
                                   "error": " ".join(b["message"] for b in breaches)}, 422)

        st = db.decide_attendance_ot(int(aid), decision)
        db.put_collection_item("audit", {"actor": u.get("name"), "actorId": u.get("id"),
            "action": "Overtime " + ("approved" if decision == "approve" else "rejected"),
            "target": "attendance/" + str(aid),
            "detail": (rec.get("name") or "") + " · %.1fh" % float(rec.get("ot_hours") or 0)
                      + ("" if not breaches else
                         " · OVER THE STATUTORY CAP (%s) — approved anyway: %s"
                         % (", ".join(b["cap"] for b in breaches), override[:200])),
            "ts": self._utc_now()})
        return self._json({"ok": True, "otStatus": st, "id": rec.get("id"),
                           "overCap": [b["cap"] for b in breaches]})

    # -- leave --------------------------------------------------------------
    def _leave_list(self, u, qs):
        status = qs.get("status", [None])[0]
        # Everyone sees their own leave; managers also see their DIRECT reports'.
        ids = [u["id"]]
        reports = db.list_reports(u.get("email"))
        ids += [r["id"] for r in reports]
        ids = list(dict.fromkeys(ids))  # dedupe, preserve order
        # Strip the one-click approval `token` from every row — it must never be readable on a list
        # fetch (a requester could otherwise pull their own leave's token and self-approve via /approve).
        rows = [{k: v for k, v in r.items() if k != "token"} for r in db.list_leave(emp_ids=ids, status=status)]
        # Anyone who can give FINAL APPROVAL must be able to see what they are being asked to approve.
        #
        # Without this the reminder mail and the Approval Inbox disagreed, and the system asked for an
        # action it then gave you nowhere to take: _appr_reminders scans EVERY pending leave company-
        # wide and mails the requester's manager, while this endpoint returned only your own leave plus
        # your direct reports' — for everyone, admins included. So a Director who is not somebody's
        # line manager got "this request has been waiting 39 days for your review" and an empty inbox.
        # Claims, travel and payments never had the problem: _coll_list scopes to own records only at
        # STAFF level and shows the whole company to every manager. Leave was the odd one out.
        #
        # Scoped to rows that are actually AWAITING A DECISION, not to everyone's leave history — an
        # approver needs the queue, not the archive. Their own and their reports' rows above still come
        # through in full whatever the status.
        if self._can_approve(u):
            have = {r.get("id") for r in rows}
            for st in ("pending", "reviewed"):
                if status and status != st:
                    continue
                for r in (db.list_leave(status=st) or []):
                    if r.get("id") in have:
                        continue
                    have.add(r.get("id"))
                    rows.append({k: v for k, v in r.items() if k != "token"})
        return self._json({"leave": rows})

    def _leave_create(self, u, body):
        # `days` drives the annual/sick balance decrement on approval, and the frontend derives it from
        # the date range — but a direct API caller could send days=0 (a full leave that consumes no
        # balance) or an inflated value. Bound it to the inclusive calendar span of the requested dates
        # (working days are always ≤ calendar days), so the stored count can't corrupt the balance.
        body = dict(body)
        # `days` MUST be a strict positive number, validated OUTSIDE the date try/except below. A
        # non-numeric value (e.g. "5 days") would otherwise be stored verbatim and later silently skip
        # the balance decrement on approval (float() raises, gets swallowed) — free paid leave. Normalise
        # it to a float so create and _leave_apply_balance always agree.
        try:
            dv = float(body.get("days") or 0)
        except (TypeError, ValueError):
            return self._err("Enter the number of leave days as a number.", 400)
        if dv <= 0:
            return self._err("Enter the number of leave days.", 400)
        body["days"] = dv
        _sd, _ed = body.get("startDate"), body.get("endDate")
        if _sd and _ed:
            try:
                d0 = datetime.strptime(str(_sd)[:10], "%Y-%m-%d")
                d1 = datetime.strptime(str(_ed)[:10], "%Y-%m-%d")
                span = (d1 - d0).days + 1
                if span < 1:
                    return self._err("The leave end date can't be before the start date.", 400)
                # Bound by WORKING days, not the calendar span. A public holiday is not annual leave
                # (Labour Code Art. 112) and neither is a rest day, so the browser excludes both —
                # this is the same rule enforced where it cannot be edited.
                #
                # `db.get_setting` ALREADY json-decodes, so json.loads on its result raised TypeError
                # on every deployment that had actually saved a holiday register — swallowed by the
                # except below, leaving the bound at the raw calendar span. The check therefore ran
                # only when there were no holidays to apply it to, and a nine-day Tết request went
                # through at nine days of annual leave. `_ot_holiday_set` is the one reader of this
                # setting, and it tolerates both shapes.
                #
                # Rest days come from the requester's own schedule, so a Mon–Sat factory Saturday is
                # a working day for them and a rest day for the office — the same rule the browser
                # applies, from the same source.
                _hol = _ot_holiday_set()
                _rest = set(_rest_weekdays_for(db.get_employee(u["id"]) or {}))
                _work, _c = 0, d0
                while _c <= d1:
                    if _c.weekday() not in _rest and _c.strftime("%Y-%m-%d") not in _hol:
                        _work += 1
                    _c += timedelta(days=1)
                if not _work:
                    return self._err("That range is all rest days and public holidays — no leave "
                                     "would be used.", 400)
                if dv > _work:
                    return self._err("The number of leave days exceeds the working days in that range "
                                     "(weekends and public holidays are not annual leave).", 400)
            except (TypeError, ValueError):
                pass
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
        # Part 11 + 3-level approval: a leave DECISION (approve/reject) requires an e-signature and
        # goes ONLY through /api/esign (which runs _appr_check). This unsigned endpoint must never
        # decide leave — the UI already uses the signed flow; block the bypass.
        if status in ("approved", "rejected"):
            return self._err("Leave approval/rejection requires an e-signature — use the approval flow.", 403)
        lv = db.get_leave(int(lid))
        if not lv:
            return self._err("Leave request not found.", 404)
        # An APPROVED leave has already decremented the requester's balance in _leave_apply_balance, and
        # there is no restore path — so flipping it back to 'pending' and re-approving would decrement a
        # SECOND time (the esign guard keys off status != 'approved'). Block the reset outright.
        if str(lv.get("status") or "").lower() == "approved":
            return self._err("An approved leave can't be reset to pending — its balance is already applied.", 409)
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
                '<h1>' + _hesc(title) + '</h1><p>' + message + '</p></div></body></html>')
        body = html.encode("utf-8")
        self.send_response(200)
        self.send_header("Content-Type", "text/html; charset=utf-8")
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        self.wfile.write(body)

    def _leave_apply_balance(self, lv):
        """On APPROVAL, actually decrement the requester's annual/sick balance by the leave's day
        count (previously the balances were display-only). Idempotent by construction: a leave
        transitions pending → approved exactly once (the email link only fires while 'pending', and
        _appr_check blocks re-approving in the portal). Unpaid / comp-off types don't touch these."""
        try:
            if not lv or not lv.get("emp_id"):
                return
            try:
                days = float(lv.get("days") or 0)
            except (TypeError, ValueError):
                days = 0
            if days <= 0:
                # Defense-in-depth: never let a malformed `days` skip the decrement silently — fall back
                # to the calendar span so an approved paid leave always consumes balance.
                try:
                    d0 = datetime.strptime(str(lv.get("startDate"))[:10], "%Y-%m-%d")
                    d1 = datetime.strptime(str(lv.get("endDate"))[:10], "%Y-%m-%d")
                    days = (d1 - d0).days + 1
                except (TypeError, ValueError):
                    days = 0
            if days <= 0:
                return
            emp = db.get_employee(lv.get("emp_id"))
            if not emp:
                return
            lt = str(lv.get("type") or "").strip().lower()
            if "sick" in lt:
                db.update_employee(lv["emp_id"], {"sickUsed": (float(emp.get("sickUsed") or 0)) + days})
            elif "annual" in lt or lt in ("", "leave", "paid", "vacation"):
                db.update_employee(lv["emp_id"], {"annualUsed": (float(emp.get("annualUsed") or 0)) + days})
        except Exception:
            pass

    def _approve_via_link(self, qs):
        token = qs.get("t", [""])[0] or qs.get("token", [""])[0]
        action = (qs.get("action", ["approve"])[0]).lower()
        lv = db.get_leave_by_token(token)
        if not lv:
            return self._html("Invalid or expired link", "This approval link is not valid. Please review the request in the app.", "#C00000")
        requester = db.get_employee(lv["emp_id"])
        rname = requester["name"] if requester else "the employee"
        if (lv.get("status") or "").lower() != "pending":
            return self._html("Already " + lv["status"], "This leave request for %s was already <b>%s</b>." % (_hesc(rname), _hesc(lv["status"])), "#205090")
        # The link no longer FINALIZES the decision (that bypassed the Part 11 e-signature and, because
        # the requester holds the token, allowed self-approval). It deep-links into the portal, where the
        # authenticated manager approves with a signature.
        return self._approve_landing(rname, "leave request",
                                     "%s → %s" % (lv.get("startDate", ""), lv.get("endDate", "")))

    def _approve_landing(self, who, what, detail):
        """Landing page for the retired one-click email approval links — routes the manager into the
        portal's Approvals inbox, where every decision is made with an authenticated e-signature."""
        d = (" (" + _hesc(detail) + ")") if detail else ""
        msg = ("%s's %s%s needs your review. For security and 21 CFR Part 11 compliance, approvals are now "
               "made in the Humiley Portal with your e-signature — the one-click email approval has been "
               "retired.<br><br>"
               "<a href=\"/?inbox=1\" style=\"display:inline-block;background:#205090;color:#fff;"
               "padding:11px 22px;border-radius:9px;text-decoration:none;font-weight:600\">"
               "Open the Approvals inbox →</a>") % (_hesc(who), _hesc(what), d)
        return self._html("Review in the portal", msg, "#205090")

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
            if self._appr_state(cur) not in ("submit", "review", "approved"):
                return self._html("Already " + cur, "This %s from %s is already <b>%s</b>." % (LABEL[coll], _hesc(who), _hesc(cur)), "#205090")
            detail = item.get("reqNo") or item.get("title") or item.get("dest") or ""
            # The link no longer changes status (that let a requester self-review/approve via a leaked
            # token, unsigned). It deep-links into the portal for an authenticated, e-signed decision.
            return self._approve_landing(who, LABEL[coll], detail)
        return self._html("Invalid or expired link",
                          "This approval link is not valid — the item may have been removed. Please review it in the app.", "#C00000")

    # -- employees ----------------------------------------------------------
    def _emp_create(self, u, body):
        if not body.get("name") or not body.get("email"):
            return self._err("name and email required.")
        if db.get_employee_by_email(body["email"]):
            return self._err("An employee with that email already exists.")
        # Admin-assigned Employee ID must be unique (it is the primary key). Blank → auto-generated.
        if body.get("id") and db.get_employee(body["id"]):
            return self._err("Employee ID '%s' is already in use — choose a different one." % body["id"])
        # The ID is echoed into inline on* handlers across the app (Access & Permissions); keep it to
        # a safe charset so a crafted ID can never break out of those attributes (stored-XSS defence).
        if body.get("id") and not re.match(r'^[A-Za-z0-9._\-]{1,40}$', str(body["id"])):
            return self._err("Employee ID may only use letters, numbers, '.', '-' and '_'.")
        body = dict(body or {})
        # Only admins may set access level / role / procurement role on create (privilege escalation).
        if ("level" in body or "role" in body or "appsDenied" in body or "appsAllowed" in body or "procRole" in body) and self._caller_level(u) != "admin":
            body.pop("level", None)
            body.pop("role", None)
            body.pop("appsDenied", None)
            body.pop("appsAllowed", None)
            body.pop("procRole", None)
        # Strip angle brackets from free-text identity fields — they're rendered into many <option>/
        # <td> builders that don't all HTML-escape, and a name/title never legitimately contains them.
        for _f in ("name", "title", "dept", "department"):
            if isinstance(body.get(_f), str):
                body[_f] = body[_f].replace("<", "").replace(">", "")
        return self._json({"ok": True, "id": db.create_employee(body)})

    def _emp_list_for(self, u):
        """Directory roster scoped by level (own record is always full):
        - Approver (management) + : all fields, incl. compensation (they run/see Payroll).
        - Contributor (manager)   : all fields EXCEPT compensation (PAY_SENSITIVE) — payroll is hidden,
                                     but leave balances etc. stay visible so they can approve requests.
        - User (staff)            : directory-safe (the full EMP_SENSITIVE set is stripped from others)."""
        rows = db.list_employees()
        lvl = self._caller_level(u)
        if self._level_rank(lvl) >= self._level_rank("management"):
            return rows
        me = u.get("id")
        if lvl == "staff":
            return [e if e.get("id") == me else {k: v for k, v in e.items() if k not in self.EMP_SENSITIVE}
                    for e in rows]
        # A Contributor-level manager needs the personal file of the people they actually manage — and
        # of nobody else. Until now they lost only PAY_SENSITIVE, so every line manager could read the
        # whole company's CCCD, home address, date of birth and next-of-kin. That is a purpose-limitation
        # problem under Decree 13 before it is anything else: needing Nguyen's emergency contact because
        # he reports to you is not a reason to hold everyone's.
        my_email = (u.get("email") or "").strip().lower()
        def _mine(e):
            return e.get("id") == me or (my_email and (e.get("managerEmail") or "").strip().lower() == my_email)
        # Two different questions, so two different rules. Compensation: never, for anybody they
        # manage. Identity PII: only for the people they manage. Leave counters stay visible
        # company-wide, because a manager approving a request has to see the balance it comes out of —
        # stripping those broke leave approval, which is what the payroll-access test correctly caught.
        #
        # Their OWN row goes through untouched, which is the rule the docstring has always stated and
        # which splitting these branches quietly dropped: `_mine` is true for yourself as well as your
        # reports, so a department head's own salary and grade were being stripped from their own
        # record. Their payslip then priced them at the grade mid-point, printed a full invented PIT
        # and net, and badged none of it — while an ordinary staff member on the same screen saw the
        # right figure. Nobody is protected from their own pay.
        return [e if e.get("id") == me
                else {k: v for k, v in e.items() if k not in self.PAY_SENSITIVE} if _mine(e)
                else {k: v for k, v in e.items() if k not in (self.PAY_SENSITIVE | self.PII_SENSITIVE)}
                for e in rows]

    ADMIN_EMAILS = {"tony.nguyen@humiley.com", "huy.nguyen@humiley.com"}

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
        emp = db.get_employee(eid)
        if not emp:
            return self._err("Employee not found.", 404)
        # REFERENTIAL INTEGRITY. attendance/leave/esign_pin cascade ON DELETE, so a hard delete does not
        # just orphan history — it DESTROYS it; and the JSON store has no FKs, so claims/payments/payruns
        # would be left pointing at an id that no longer resolves (and could later be recycled). An
        # employee who has any history is DEACTIVATED, never deleted — the roster already filters on
        # status, so deactivation is the intended way to remove someone from the active org.
        refs = db.employee_references(eid)
        if refs:
            what = ", ".join("%d %s%s" % (n, k, "" if n == 1 else "s") for k, n in sorted(refs.items()))
            return self._err(
                "%s has history in the system (%s) and cannot be deleted — deleting would destroy or "
                "orphan those records. Set their status to Inactive instead; they stay out of the active "
                "roster and their history remains intact." % (emp.get("name") or eid, what), 409)
        db.delete_employee(eid)
        db.put_collection_item("audit", {
            "actor": u.get("name") or "System", "actorId": u.get("id") or "",
            "action": "Employee deleted", "target": "employees/" + str(eid),
            "detail": "%s <%s> — no history on record" % (emp.get("name") or "", emp.get("email") or ""),
            "ts": self._utc_now()})
        return self._json({"ok": True})

    def _emp_update(self, u, eid, body):
        ex = db.get_employee(eid)
        if not ex:
            return self._err("Employee not found.", 404)
        body = dict(body or {})
        # Only admins may change access level or role, incl. the procurement role that the SSO
        # token carries (prevents privilege escalation — a non-admin must not set procRole:ADMIN).
        if ("level" in body or "role" in body or "appsDenied" in body or "appsAllowed" in body or "procRole" in body) and self._caller_level(u) != "admin":
            body.pop("level", None)
            body.pop("role", None)
            body.pop("appsDenied", None)
            body.pop("appsAllowed", None)
            body.pop("procRole", None)
        # `status` is now a HARD access control (session_user/_auth_m365 lock out Inactive users) and
        # `dept` drives the finance read-scope, so only MANAGEMENT+ may change these org fields on another
        # employee. Otherwise the lowest manager tier ("Contributor") could lock out — or dept-hijack the
        # financial records of — a higher-privileged user. (QA #1)
        if self._level_rank(self._caller_level(u)) < self._level_rank("management"):
            for _k in ("status", "dept", "department", "managerEmail", "salary", "grade", "endDate",
                       "email", "title", "bank", "taxId", "personalId", "dependents",
                       "annualTotal", "annualUsed", "sickTotal", "sickUsed", "compoff"):
                body.pop(_k, None)
        # Protected super-admins can never be demoted OR deactivated. A DEDICATED level/role/app/status
        # change (the Access-Levels dropdown sends ONLY those fields) is rejected LOUDLY so the acting
        # admin sees why — instead of the old silent pop-and-return-ok that looked like a phantom success
        # reverting on reload. But a full employee-record save (the Edit-Employee form re-sends
        # level/role/status alongside name/phone/…) must still succeed: preserve the protected fields
        # and let the benign profile edits through.
        if (ex.get("email") or "").lower() in self.ADMIN_EMAILS:
            _priv = [k for k in ("level", "role", "appsDenied", "status") if k in body]
            if _priv:
                if not (set(body.keys()) - {"level", "role", "appsDenied", "status"}):
                    return self._err("This is a protected super-admin account — its access level, apps and status are locked.", 403)
                for _k in _priv:
                    body.pop(_k, None)
        # Strip angle brackets from free-text identity fields (rendered into <option>/<td> builders
        # that don't all HTML-escape; a name/title/dept never legitimately contains them).
        for _f in ("name", "title", "dept", "department"):
            if isinstance(body.get(_f), str):
                body[_f] = body[_f].replace("<", "").replace(">", "")
        if body:
            self._audit_emp_change(u, eid, ex, body)
            db.update_employee(eid, body)
        return self._json({"ok": True})

    # The employee-record fields worth a line in the permanent trail: the ones that move money,
    # route approvals, or decide what somebody can see.
    EMP_AUDITED = ("salary", "grade", "title", "dept", "department", "managerEmail",
                   "status", "level", "role", "employmentType", "endDate", "dependents", "bank")
    # Never write the VALUE of these into the audit trail — the log is readable by admins and would
    # otherwise quietly become a second, unprotected compensation database.
    EMP_AUDIT_MASKED = ("salary", "bank")

    @staticmethod
    def _same_field_value(old, new):
        """Has this field actually changed?

        A plain string comparison is wrong here: `salary` is a SQLite REAL, so the stored value comes
        back as 30000000.0 while the browser sends the integer 30000000. Comparing those as text made
        every re-save of an unchanged salary look like a raise — a phantom row in both the audit trail
        and the dated history, which is worse than no history at all because it invents events that
        never happened. Compare numerically when both sides are numbers, textually otherwise."""
        if old is None and new is None:
            return True
        try:
            if old is not None and new is not None:
                return float(old) == float(new)
        except (TypeError, ValueError):
            pass
        return str(old if old is not None else "") == str(new if new is not None else "")

    def _audit_emp_change(self, u, eid, before, after):
        """One audit row per changed employee field.

        A ₫50,000 payroll adjustment lands in a tamper-evident HMAC chain; a salary rise, a promotion,
        a transfer or an access-level change wrote nothing at all. That was the loudest inconsistency
        in the platform — the controls were guarding a record that did not exist."""
        try:
            _name = (before or {}).get("name") or eid
            for f in self.EMP_AUDITED:
                if f not in (after or {}):
                    continue
                old, new = (before or {}).get(f), (after or {}).get(f)
                if self._same_field_value(old, new):
                    continue
                if f in self.EMP_AUDIT_MASKED:
                    detail = "%s changed" % f            # that it moved, never to what
                else:
                    detail = "%s: %s -> %s" % (f, old if old not in (None, "") else "(blank)",
                                               new if new not in (None, "") else "(blank)")
                db.put_collection_item("audit", {
                    "actor": u.get("name") or "System", "actorId": u.get("id") or "",
                    "action": "Employee record changed", "target": "employees/" + str(eid),
                    "detail": _name + " · " + detail, "ts": self._utc_now()})
                # …and the DATED row, which is a different thing from the audit row. The audit answers
                # "who changed this and when did they change it". This answers "what was it in March",
                # which is what a payslip reprint, a headcount trend and the Decree 145 labour
                # management book all need. It stores the salary VALUE — that is the entire point —
                # so the read side is management-only.
                if f in db.EMP_HISTORY_FIELDS:
                    db.add_emp_event(eid, f, old, new,
                                     effective=str((after or {}).get("_effective") or "")[:10] or None,
                                     reason=str((after or {}).get("_reason") or "")[:200],
                                     actor=u.get("name") or "", actor_id=u.get("id") or "")
        except Exception:
            pass          # the change is legitimate; a failed audit write must not block it

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

    def _procurement_sso_token(self, u):
        """Short-lived HMAC-signed token {email,name,exp}. Procurement (an app of this portal)
        verifies it against the SAME TK_SSO_SECRET and opens a session with no password — the
        user already authenticated to the portal via Microsoft 365. Only granted users get here
        (the launcher is hidden unless Procurement is in appsAllowed)."""
        import base64, hmac, hashlib
        secret = PROCUREMENT_SSO_SECRET
        if not secret or len(secret) < 16:
            return self._err("Procurement single sign-on is not configured (set TK_SSO_SECRET).", 503)
        # Second gate (defence-in-depth on top of the DB-user check procurement does): the user
        # must actually have Procurement granted — admins always, else it must be in appsAllowed.
        allowed = set(x.strip().lower() for x in str(u.get("appsAllowed") or "").split(",") if x.strip())
        if self._caller_level(u) != "admin" and "procurement" not in allowed:
            return self._err("You do not have access to the Procurement app.", 403)
        payload = json.dumps({"email": u.get("email") or "", "name": u.get("name") or "",
                              "role": (u.get("procRole") or ""),  # procurement role assigned in Access & Permissions
                              "exp": int(time.time()) + 120}, separators=(",", ":"))
        p_b64 = base64.urlsafe_b64encode(payload.encode("utf-8")).decode("ascii").rstrip("=")
        sig = hmac.new(secret.encode("utf-8"), p_b64.encode("ascii"), hashlib.sha256).digest()
        s_b64 = base64.urlsafe_b64encode(sig).decode("ascii").rstrip("=")
        return self._json({"token": p_b64 + "." + s_b64})

    def _portal_get(self, u):
        out = {k: db.get_setting("portal_" + k) for k in self.PORTAL_KEYS}
        rank = self._level_rank(self._caller_level(u))
        # Integration endpoints are only sent to callers who actually use them, so a plain staff
        # account can't read the Teams webhook (a posting credential) or the Invoice-Tracking
        # SharePoint path. financeSpUrl + procurementUrl stay readable — staff legitimately open
        # bills in SharePoint and launch the granted Procurement app with them.
        out["teamsWebhook"] = (db.get_setting("portal_teamsWebhook") or "") if rank >= self._level_rank("manager") else ""
        out["financeSpUrl"] = db.get_setting("portal_financeSpUrl", "") or ""
        out["hrSpUrl"] = db.get_setting("portal_hrSpUrl", "") or ""
        out["invtrackSpUrl"] = (db.get_setting("portal_invtrackSpUrl", "") or "") if rank >= self._level_rank(self.INVTRACK_MIN) else ""
        out["procurementUrl"] = db.get_setting("portal_procurementUrl", "") or ""
        # Approval-lifecycle email (department senders + on/off + last-send health for managers+).
        out["apprEmail"] = db.get_setting("portal_apprEmail", "1") or "1"
        out["apprSenderHr"] = db.get_setting("portal_apprSenderHr", "") or "hr@humiley.com"
        out["apprSenderFinance"] = db.get_setting("portal_apprSenderFinance", "") or "finance@humiley.com"
        out["apprSenderProc"] = db.get_setting("portal_apprSenderProc", "") or "procurement@humiley.com"
        out["apprReminders"] = db.get_setting("portal_apprReminders", "1") or "1"
        out["apprReminderDays"] = db.get_setting("portal_apprReminderDays", "2") or "2"
        out["apprEscalateDays"] = db.get_setting("portal_apprEscalateDays", "0") or "0"
        out["apprEscalateTo"] = db.get_setting("portal_apprEscalateTo", "") or ""
        out["digestEnabled"] = db.get_setting("portal_digestEnabled", "0") or "0"
        out["digestDay"] = db.get_setting("portal_digestDay", "0") or "0"
        out["digestLeadTo"] = db.get_setting("portal_digestLeadTo", "") or ""
        out["tkNudges"] = db.get_setting("portal_tkNudges", "0") or "0"
        out["tkCheckinHour"] = db.get_setting("portal_tkCheckinHour", "10") or "10"
        out["tkCheckoutHour"] = db.get_setting("portal_tkCheckoutHour", "19") or "19"
        out["monthlyReports"] = db.get_setting("portal_monthlyReports", "0") or "0"
        out["monthlyDay"] = db.get_setting("portal_monthlyDay", "1") or "1"
        out["monthlyTo"] = db.get_setting("portal_monthlyTo", "") or ""
        out["payerSeparation"] = db.get_setting("portal_payerSeparation", "1") or "1"   # disbursement SoD: 2nd approver to pay
        # The payer ALLOW-LIST is an authorization list, so only an admin (who can edit it) reads it
        # back. Everyone gets `canPay` instead — their OWN capability, computed by the same helper the
        # e-signature gate uses, so the Mark-paid button can never appear for someone the server will
        # refuse. (It reflects the list + level only; the per-request rules — not your own request, not
        # one you approved — are still decided per request at signing time.)
        out["apprPayers"] = (db.get_setting("portal_apprPayers", "") or "") \
            if self._caller_level(u) == "admin" else ""
        out["canPay"] = self._is_payer(u)
        # Same treatment for the HR list: it is an authorization list, so only an admin reads it
        # back. Everyone gets `canPublishDocs` — their OWN capability, from the same helper the write
        # gate uses, so the Publish button can never appear for somebody the server will refuse.
        out["hrAdmins"] = (db.get_setting("portal_hrAdmins", "") or "") \
            if self._caller_level(u) == "admin" else ""
        out["canPublishDocs"] = self._is_hr_admin(u)
        out["otAnnualCap"] = str(int(_ot_annual_cap()))   # the ceiling everyone's OT is measured against
        out["apprEmailHealth"] = _APPR_EMAIL_HEALTH if rank >= self._level_rank("manager") else {}
        return self._json(out)

    def _myspace_summary(self, u):
        """Per-user counts for the My Space landing page in ONE small request, so it no longer blocks
        first paint on six full company-wide collection loads. Self-scoped: only the caller's own
        travel/payments/claims/devices/enrolments are counted. Matches the frontend's own arithmetic."""
        uid = u.get("id"); uname = u.get("name")
        def mine(rows, name_field="name"):
            out = []
            for r in rows:
                if (uid and r.get("empId") == uid) or (uname and r.get(name_field) == uname):
                    out.append(r)
            return out
        decided = ("Approved", "Rejected", "Paid", "Cancelled")
        travel = mine(db.list_collection("travel"))
        pays = mine(db.list_collection("payments"))
        claims = mine(db.list_collection("claims"))
        devices = mine(db.list_collection("devices"), name_field="assignedTo")
        enrols = [e for e in db.list_collection("enrollments") if uid and e.get("empId") == uid]
        pending = (sum(1 for t in travel if str(t.get("status") or "") not in decided)
                   + sum(1 for p in pays if str(p.get("status") or "") not in decided)
                   + sum(1 for c in claims if _claim_rollup(c) not in decided))
        train_done = sum(1 for e in enrols if e.get("status") == "Completed")
        train_avg = round(sum(float(e.get("progress") or 0) for e in enrols) / len(enrols)) if enrols else 0
        return self._json({
            "pending": pending, "trips": len(travel), "claims": len(claims), "payments": len(pays),
            "devices": len(devices), "trainDone": train_done, "trainTotal": len(enrols), "trainAvg": train_avg,
        })

    def _exec_trends(self, u, months=6):
        """Management+: per-month finance trend series for the last `months` months — payments approved,
           invoice value captured, and VAT — so the Executive Dashboard can chart direction, not just a snapshot."""
        if not self._is_mgmt(u):
            return self._err("Management access required.", 403)

        def _n(v):
            try:
                return float(str(v).replace(",", "").replace(" ", "").replace("₫", "") or 0)
            except Exception:
                return 0.0
        now_vn = datetime.utcnow() + timedelta(hours=7)
        y, m = now_vn.year, now_vn.month
        labels = []
        for i in range(months - 1, -1, -1):
            mm, yy = m - i, y
            while mm <= 0:
                mm += 12
                yy -= 1
            labels.append("%04d-%02d" % (yy, mm))
        lbset = set(labels)
        pay = {lb: 0.0 for lb in labels}
        inv = {lb: 0.0 for lb in labels}
        vat = {lb: 0.0 for lb in labels}
        try:
            for p in db.list_collection("payments"):
                if str(p.get("status") or "").lower() in ("approved", "paid"):
                    d = str(p.get("paidOn") or p.get("approvedOn") or p.get("submittedOn") or p.get("date") or "")[:7]
                    if d in lbset:
                        pay[d] += _n(p.get("amount") or p.get("total"))
        except Exception:
            pass
        try:
            for it in _invtrack_all_items():
                d = str(it.get("dateISO") or "")[:7]
                if d in lbset:
                    tot = _n(it.get("after"))
                    if not tot:
                        tot = _n(it.get("before")) + _n(it.get("vat"))
                    inv[d] += tot
                    vat[d] += _n(it.get("vat"))
        except Exception:
            pass
        return self._json({"months": labels,
                           "payments": [round(pay[lb], 2) for lb in labels],
                           "invoices": [round(inv[lb], 2) for lb in labels],
                           "vat": [round(vat[lb], 2) for lb in labels]})

    def _exec_summary(self, u):
        """Company-on-one-screen aggregate for the Executive Dashboard (management+). Reuses the tested
           digest gatherer for approvals-in-flight; everything else is a bounded read of collections."""
        if not self._is_mgmt(u):
            return self._err("Management access required.", 403)

        def _n(v):
            try:
                return float(str(v).replace(",", "").replace(" ", "").replace("₫", "") or 0)
            except Exception:
                return 0.0
        today = _now_iso()[:10]
        ym = today[:7]
        try:
            emps = db.list_employees() or []
        except Exception:
            emps = []
        active = [e for e in emps if str(e.get("status") or "Active").lower() != "inactive"]
        liability = 0
        for e in active:
            try:
                liability += max(0, int(e.get("annualTotal") or 12) - int(e.get("annualUsed") or 0))
            except Exception:
                pass
        try:
            _m, _l, counts = _digest_gather()
        except Exception:
            counts = {"await": 0, "review": 0, "overdue": 0, "valuePending": 0.0}
        on_leave_today = pending_leave = 0
        try:
            for lv in db.list_leave() or []:
                st = str(lv.get("status") or "").lower()
                if st in ("pending", "reviewed"):
                    pending_leave += 1
                elif st == "approved" and (lv.get("startDate") or "")[:10] <= today <= (lv.get("endDate") or "9999")[:10]:
                    on_leave_today += 1
        except Exception:
            pass
        pay_month = 0.0
        pay_n = 0
        try:
            for p in db.list_collection("payments"):
                if str(p.get("status") or "").lower() in ("approved", "paid"):
                    d = str(p.get("paidOn") or p.get("approvedOn") or p.get("submittedOn") or p.get("date") or "")[:7]
                    if d == ym:
                        pay_month += _n(p.get("amount") or p.get("total"))
                        pay_n += 1
        except Exception:
            pass
        inv_total = inv_vat = 0.0
        inv_n = 0
        try:
            for it in _invtrack_all_items():
                inv_n += 1
                tot = _n(it.get("after"))
                if not tot:
                    tot = _n(it.get("before")) + _n(it.get("vat"))
                inv_total += tot
                inv_vat += _n(it.get("vat"))
        except Exception:
            pass
        try:
            projs = db.list_collection("pm_projects")
        except Exception:
            projs = []
        _closed = ("closed", "completed", "cancelled", "canceled", "archived", "on hold")
        proj_active = sum(1 for p in projs if str(p.get("status") or "").lower() not in _closed)
        return self._json({
            "headcount": len(active), "onLeaveToday": on_leave_today,
            "leaveLiabilityDays": liability, "pendingLeave": pending_leave,
            "apprAwait": counts.get("await", 0), "apprReview": counts.get("review", 0),
            "apprOverdue": counts.get("overdue", 0), "apprValue": counts.get("valuePending", 0.0),
            "payMonth": pay_month, "payMonthCount": pay_n,
            "invoiceCount": inv_n, "invoiceTotal": inv_total, "invoiceVat": inv_vat,
            "projectCount": len(projs), "projectActive": proj_active,
            "month": ym, "at": _now_iso(),
        })

    def _portal_update(self, u, body):
        for k in self.PORTAL_KEYS:
            if isinstance(body.get(k), list):
                db.set_setting("portal_" + k, body[k])
        # Integration endpoints are admin-only: a manager-level account must not be able to
        # repoint the Teams webhook, the SharePoint archive, or the Procurement launcher
        # (redirect / exfiltration vectors). Content lists above stay manager-editable; the
        # frontend echoes the current URLs back on every save, so an UNCHANGED value passes
        # through silently and only an actual change requires admin.
        is_admin = self._caller_level(u) == "admin"
        for k, sk in (("teamsWebhook", "portal_teamsWebhook"),
                      ("financeSpUrl", "portal_financeSpUrl"),
                      ("hrSpUrl", "portal_hrSpUrl"),
                      ("invtrackSpUrl", "portal_invtrackSpUrl"),
                      ("procurementUrl", "portal_procurementUrl"),
                      ("apprEmail", "portal_apprEmail"),
                      ("apprSenderHr", "portal_apprSenderHr"),
                      ("apprSenderFinance", "portal_apprSenderFinance"),
                      ("apprSenderProc", "portal_apprSenderProc"),
                      ("apprReminders", "portal_apprReminders"),
                      ("apprReminderDays", "portal_apprReminderDays"),
                      ("apprEscalateDays", "portal_apprEscalateDays"),
                      ("apprEscalateTo", "portal_apprEscalateTo"),
                      ("digestEnabled", "portal_digestEnabled"),
                      ("digestDay", "portal_digestDay"),
                      ("digestLeadTo", "portal_digestLeadTo"),
                      ("tkNudges", "portal_tkNudges"),
                      ("tkCheckinHour", "portal_tkCheckinHour"),
                      ("tkCheckoutHour", "portal_tkCheckoutHour"),
                      ("monthlyReports", "portal_monthlyReports"),
                      ("monthlyDay", "portal_monthlyDay"),
                      ("monthlyTo", "portal_monthlyTo"),
                      ("payerSeparation", "portal_payerSeparation"),
                      ("apprPayers", "portal_apprPayers"),   # who may release money — admin-only to change
                      ("hrAdmins", "portal_hrAdmins"),      # who is HR — admin-only to change
                      ("otAnnualCap", "portal_otAnnualCap")):   # Art. 107(3) 300h election
            v = body.get(k)
            if not isinstance(v, str):
                continue
            # The payer allow-list is only READ BACK to an admin (it is an authorization list), so a
            # manager saving this same form echoes a BLANK for it. Without this skip that blank would
            # read as "clear the payer list" and 403 the entire save for every non-admin. Ignore the
            # key outright unless the caller is an admin — they are the only one allowed to change it.
            if k == "apprPayers" and not is_admin:
                continue
            if k != "teamsWebhook":
                v = v.strip()
            cur = db.get_setting(sk, "") or _APPR_SETTING_DEFAULTS.get(k, "")   # compare against the SAME effective default the GET returns
            if v == (cur if isinstance(cur, str) else ""):
                continue
            if not is_admin:
                return self._err("Admin access required to change integration URLs.", 403)
            db.set_setting(sk, v)
            if k == "invtrackSpUrl":
                _invtrack_sp_reset()   # a corrected link must take effect now, not after the 5-min negative cache
        return self._json({"ok": True})

    # -- generic HR collections (recruitment, onboarding, performance, talent, training) --
    COLLECTIONS = {"hrdocs", "hrdoc_acks", "jobs", "candidates", "onboarding", "reviews", "goals", "courses", "talent", "payruns", "padr", "competency", "pip", "claims", "acks", "audit", "travel", "exits", "benefits", "learningpaths", "enrollments", "payadjust", "devices", "handovers", "payments", "crm_deals", "crm_companies", "crm_contacts", "crm_leads", "crm_products", "crm_targets", "crm_aop", "pm_projects", "pm_settings", "pm_deliverables", "pm_tasks", "pm_costs", "pm_quality", "pm_quality_itp", "pm_quality_itp_items", "pm_resources", "pm_comms", "pm_issues", "pm_risks", "pm_changes", "pm_lessons", "pm_procurement", "pm_procurement_payments", "pm_stakeholders", "pm_rfis", "pm_sitereports", "pm_weekreports", "pm_chat", "pm_portfolioSnapshots", "pm_execNotes", "invtrack", "schedules", "contracts", "certificates"}
    # Collections any authenticated user (incl. staff) may create for self-service.
    STAFF_WRITE = {"hrdoc_acks", "claims", "travel", "payments", "acks", "audit", "padr", "enrollments", "crm_deals", "crm_companies", "crm_contacts", "crm_leads", "crm_products", "crm_targets", "crm_aop", "pm_tasks", "pm_deliverables", "pm_quality", "pm_quality_itp", "pm_quality_itp_items", "pm_resources", "pm_comms", "pm_issues", "pm_risks", "pm_changes", "pm_lessons", "pm_stakeholders", "pm_rfis", "pm_sitereports", "pm_weekreports", "pm_chat"}
    PAYROLL_ADMIN = {"payruns", "payadjust"}   # payroll writes are Administrator-only
    # minimum access LEVEL required to READ a collection. Sensitive HR data raised to
    # management; recruitment/audit stay manager. Anything not listed AND not in
    # SELF_OWNED / a shared catalog (courses, learningpaths) is open to managers only
    # for staff via the self-owner scoping below.
    # Invoice Tracking is locked to EDITOR + ADMIN only (company policy). A Finance/Approver
    # (management) account may run Payroll + Finance Control but must NOT see Invoice Tracking.
    # Every invtrack gate — read, status/sync/import, and coll add/update/delete — references this
    # single constant so the enforcement can never drift apart between sites.
    # HR records that are EVIDENCE about a person — the ones a labour inspector, an ISO auditor or a
    # former employee's lawyer would ask to see. Deleting one snapshots it into the audit chain first.
    HR_EVIDENCE_COLLS = {"exits", "padr", "reviews", "pip", "hrdoc_acks", "acks",
                         "onboarding", "handovers", "enrollments", "payadjust", "candidates"}
    INVTRACK_MIN = "editor"
    # Publishing a company document commits every employee to signing it and starts chasing them.
    # That is a management act, not a line-manager one.
    HRDOC_MIN = "management"
    READ_MIN = {"invtrack": INVTRACK_MIN, "payruns": "management", "payadjust": "management", "exits": "management", "pip": "management",
                # A labour contract states the agreed wage, so it is compensation data — management
                # and above, matching payruns. An employee reads their own through _coll_list's
                # self-scoped branch, never anyone else's.
                "contracts": "management",
                "reviews": "manager", "talent": "manager", "jobs": "manager", "candidates": "manager",
                "competency": "manager", "audit": "manager",
                # Project financials must not be world-readable to every staff account (the PM app is
                # on by default). Line-item costs + vendor payments need manager+; creation is already
                # manager-gated, so this makes read match write.
                "pm_costs": "manager", "pm_procurement_payments": "manager",
                # Not compensation data: a site manager has to know whether their crew is covered
                # before sending them out, so this is manager-and-above, not management.
                "certificates": "manager"}
    # Staff MAY read these collections, but ONLY their own records (scoped by empId / name / assignedTo).
    # `benefits` is deliberately NOT here. It is the per-GRADE benefits CATALOGUE — a policy table, not
    # personal data — so scoping it to "your own rows" matched nothing and every employee's Benefits
    # card was permanently empty while HR maintained a table nobody could see.
    SELF_OWNED = {"hrdoc_acks", "claims", "travel", "payments", "acks", "padr", "enrollments", "onboarding", "goals", "devices", "handovers"}
    # Travel / claim / payment: a staff user sees only their OWN; a LEADER (manager) sees only their
    # TEAM (direct reports + self); management/editor/admin (Finance-level and above) see the whole
    # company. Scoped below in _coll_list.
    TEAM_SCOPED = {"claims", "travel", "payments"}
    # Manager-only HR collections gated by the per-user "hr" app toggle (crm_*/pm_* inferred by prefix).
    HR_APP_COLLS = {"jobs", "candidates", "reviews", "talent", "competency", "pip", "exits", "contracts", "certificates"}
    EMP_SENSITIVE = {"salary", "grade", "bank", "taxId", "dependents", "personalId", "address", "emergency", "annualUsed", "annualTotal", "sickUsed", "sickTotal", "compoff"}
    # Compensation / payroll fields — visible ONLY to Approver (management) level and above, matching
    # the Payroll page's data-level="management" gate and READ_MIN for payruns/payadjust. A Contributor
    # (manager) can approve leave etc. but must NOT see anyone's pay; leave balances stay visible to them.
    PAY_SENSITIVE = {"salary", "grade", "bank", "taxId"}
    # Identity PII a line manager may see for their OWN reports and for nobody else. Deliberately
    # excludes the leave counters — a manager must see the balance a request draws down, whoever it is.
    PII_SENSITIVE = {"personalId", "address", "emergency", "dob", "familyStatus", "dependents"}
    LEVEL_ORDER = ["staff", "manager", "management", "editor", "admin"]

    @staticmethod
    def _pm_name_tokens(v):
        """Fold a name to comparable ASCII tokens. Mirrors _pmNameTokens in the frontend."""
        t = unicodedata.normalize("NFD", str(v or ""))
        t = "".join(c for c in t if not unicodedata.combining(c))
        t = t.replace("\u0111", "d").replace("\u0110", "D").lower()
        return [w for w in re.split(r"[^a-z0-9]+", t) if w]

    def _pm_same_person(self, a, b):
        """Two spellings of one person. The Team & RACI tab holds "Trung Nguyen" while the employee
        record says "Nguyen Van Trung" — short Western order against full Vietnamese order — so an
        exact comparison locks people out of their own projects. Requires two shared tokens (half this
        company is a Nguyen) and containment one way or the other."""
        A, B = self._pm_name_tokens(a), self._pm_name_tokens(b)
        if len(A) < 2 or len(B) < 2:
            return False
        sa, sb = set(A), set(B)
        shared = len(sa & sb)
        return shared >= 2 and (shared == len(sa) or shared == len(sb))

    def _pm_visible_projects(self, u):
        """Ids of the projects this caller may see, or None meaning "all of them".

        Manager level and above see the whole portfolio, which is what the frontend already does
        (_pmSeeAll). Below that it is the projects you MANAGE plus the ones you are on the Team of —
        the same two routes the Projects list uses, evaluated here so the rule cannot be bypassed by
        calling the API directly."""
        if self._level_rank(self._caller_level(u)) >= self._level_rank("manager"):
            return None
        me_id, me_name = u.get("id"), u.get("name") or ""
        ids = set()
        for p in db.list_collection("pm_projects"):
            if p.get("manager") and self._pm_same_person(p.get("manager"), me_name):
                ids.add(p.get("id"))
        for r in db.list_collection("pm_resources"):
            if not r.get("projectId"):
                continue
            if (r.get("empId") and r.get("empId") == me_id) or self._pm_same_person(r.get("name"), me_name):
                ids.add(r.get("projectId"))
        return ids

    def _pm_chat_summary(self, u):
        """Unread counts per project, and how many of them name you.

        Counting happens HERE rather than by shipping messages to the browser: the Projects list on a
        4G phone must not download every message of every project to draw a badge."""
        vis = self._pm_visible_projects(u)
        me = u.get("id") or ""
        read = (db.get_collection_item("pm_chat_read", me) or {}).get("read") or {}
        out, mentions = {}, {}
        for m in db.list_collection("pm_chat"):
            pid = m.get("projectId")
            if not pid or (vis is not None and pid not in vis):
                continue
            if (m.get("authorId") or "") == me:
                continue                                    # your own words are not unread
            if str(m.get("ts") or "") <= str(read.get(pid) or ""):
                continue
            out[pid] = out.get(pid, 0) + 1
            if any((x or {}).get("empId") == me for x in (m.get("mentions") or [])):
                mentions[pid] = mentions.get(pid, 0) + 1
        # A label per project that has something waiting, so the notification bell can name the job
        # without the dashboard having to load the whole portfolio. Only projects already counted
        # above appear here, so this adds no visibility the caller did not already have.
        names = {}
        if out:
            for p in db.list_collection("pm_projects"):
                if p.get("id") in out:
                    names[p["id"]] = p.get("code") or p.get("name") or ""
        return self._json({"ok": True, "unread": out, "mentions": mentions, "names": names,
                           # The caller's OWN watermark, scoped by the same visibility as names. It
                           # ships no bodies and no per-topic counts — the browser already holds the
                           # messages it is allowed to hold, and works the per-topic dots out itself.
                           "readAt": {k: v for k, v in read.items() if vis is None or k in vis},
                           "total": sum(out.values()), "totalMentions": sum(mentions.values())})

    def _pm_chat_read(self, u, body):
        """Mark one project's conversation read up to now. One small row per employee."""
        pid = str((body or {}).get("projectId") or "")
        if not pid:
            return self._err("projectId is required.", 400)
        vis = self._pm_visible_projects(u)
        if vis is not None and pid not in vis:
            return self._err("Not your project.", 403)
        me = u.get("id") or ""
        if not me:
            return self._err("Unknown user.", 403)
        row = db.get_collection_item("pm_chat_read", me) or {"id": me, "empId": me, "read": {}}
        rd = row.get("read") if isinstance(row.get("read"), dict) else {}
        rd[pid] = self._utc_now_ms()
        row["read"] = rd
        row["id"] = me
        db.put_collection_item("pm_chat_read", row)
        return self._json({"ok": True})

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
            # Your OWN payslip is the one exception. Pay runs are management-only, which is right for
            # the register and the company totals — but it also meant an employee's own payslip could
            # never reach the FROZEN, Director-signed line, so their My Payslip screen recomputed the
            # month live and showed them today's salary under an old month's heading. What comes back
            # here is one line, theirs, from finalised runs only: no other employee, no company totals.
            # Your own labour contract is yours to read — Art. 13(1) requires you to be given a copy,
            # so a portal that holds it and will not show it to you is worse than not holding it.
            # Somebody else's is compensation data and stays out of reach.
            if name == "contracts":
                return self._json({"ok": True, "items": [
                    c for c in db.list_collection(name) if c.get("empId") == u.get("id")]})
            if name == "payruns":
                mine = []
                for r in db.list_collection(name):
                    if "final" not in str(r.get("status") or "").lower():
                        continue
                    ln = [l for l in (r.get("lines") or [])
                          if isinstance(l, dict) and l.get("empId") == u.get("id")]
                    if ln:
                        mine.append({"id": r.get("id"), "period": r.get("period"),
                                     "scope": r.get("scope"), "empId": r.get("empId"),
                                     "status": r.get("status"), "created": r.get("created"),
                                     "lines": ln})
                return self._json({"ok": True, "items": mine})
            return self._err("Access restricted to %s level or above." % need, 403)
        items = db.list_collection(name)
        lvl = self._caller_level(u)
        # Audit trail: the FULL immutable log (deletions, access-level changes, attendance, invoice
        # syncs) is ADMIN-only — matching the admin-only Audit Log view. A non-admin reader (the
        # Signature Governance page is management-level and filters to e-signature events client-side
        # anyway) gets ONLY the e-signature subset, so the rest of the trail can't be pulled via the
        # API by a manager/management/editor account whose UI hides the Audit Log.
        if name == "audit" and lvl != "admin":
            items = [it for it in items if "e-signature" in str(it.get("action") or "").lower()]
        # A project conversation is scoped to the projects you can actually open. Every other pm_
        # collection ships the whole portfolio to anyone with the Projects app and lets the browser
        # filter — tolerable for a task list, not for a channel where people write candidly about
        # contractors, clients and each other. Enforced here so it cannot be stepped around by calling
        # /api/coll/pm_chat directly. Manager level and above get everything, matching _pmSeeAll.
        # Company documents. Two problems here, both invisible until real PDFs were attached:
        #  - The audience rule ("All" / one department / named people) lived ONLY in the browser, so
        #    any authenticated account could pull a document addressed to three named people.
        #  - Every row carried the whole file inline as base64. Six 8 MB policies is ~64 MB down the
        #    wire on every Onboarding render and every My Dashboard load, on a phone, on 4G.
        # The list now carries metadata only; the bytes come from /api/hr/doc/<id>/file, which
        # re-checks the audience. Manager level and above see every document — they run the register.
        if name == "hrdocs":
            if self._level_rank(lvl) < self._level_rank("manager"):
                # Reuse _hrdoc_targets against a one-element list rather than re-implementing the
                # audience rule: a second copy of it is a second thing to keep in step with the
                # browser, and the reminder sweep already depends on this one being right.
                me = next((e for e in db.list_employees() if e.get("id") == u.get("id")), None) or {
                    "id": u.get("id") or "", "name": u.get("name") or "",
                    "dept": u.get("dept") or u.get("department") or "", "status": "Active"}
                items = [it for it in items
                         if not it.get("archived") and _hrdoc_targets(it, [me])]
            items = [dict(it, file="", hasFile=_hrdoc_has_file(it)) for it in items]
        if name == "pm_chat":
            vis = self._pm_visible_projects(u)
            if vis is not None:
                items = [it for it in items if it.get("projectId") in vis]
        # staff see ONLY their own records in self-service collections (no cross-employee read)
        if lvl == "staff" and name in self.SELF_OWNED:
            myid, myname = u.get("id"), u.get("name")

            def _holds(it):
                # A device is a stock LINE that several people can hold at once. Matching only the
                # row's own empId / assignedTo found the FIRST holder and nobody else: from the
                # second assignment on, assignedTo is a comma-joined display string that equals no
                # employee's name, so the other holders were told they had no company devices at all
                # — while the register had them signed for the kit.
                for a in (it.get("assignments") or []):
                    if not isinstance(a, dict):
                        continue
                    if a.get("empId") == myid or (not a.get("empId") and myname and a.get("name") == myname):
                        return True
                return False

            items = [it for it in items
                     if it.get("empId") == myid
                     or (not it.get("empId") and myname and it.get("name") == myname)
                     or (myname and it.get("assignedTo") == myname)
                     or _holds(it)]
        # Travel / claim / payment: a LEADER (manager level) sees ONLY their TEAM — their own
        # records plus those of the employees who report DIRECTLY to them (managerEmail == theirs).
        # Management / editor / admin (Finance-level and above) fall through and see the whole
        # company; staff were already scoped to their own just above.
        elif lvl == "manager" and (name in self.TEAM_SCOPED or name in ("padr", "goals")):
            # A department manager sees their WHOLE DEPARTMENT's payments / travel / claims — and their
            # team's PADR / goals (performance data must not be readable across the whole company by a
            # rank-2 leader; HR / management+ fall through and still see all). Scoped by the requester's
            # department (resolved from the employee row, with the record's stored `department` as a
            # fallback). No dept on the manager -> own records only (deny-by-default, never widen).
            myid, myname = u.get("id"), u.get("name")
            mydept = (u.get("dept") or u.get("department") or "").strip()
            emps = db.list_employees()
            dept_by_id = {e.get("id"): (e.get("dept") or "") for e in emps}
            dept_by_name = {e.get("name"): (e.get("dept") or "") for e in emps}
            def _in_dept(it):
                if (it.get("empId") and it.get("empId") == myid) or (myname and (it.get("name") or it.get("assignedTo")) == myname):
                    return True
                if not mydept:
                    return False
                d = dept_by_id.get(it.get("empId")) or dept_by_name.get(it.get("name") or it.get("assignedTo")) or (it.get("department") or "")
                return d == mydept
            items = [it for it in items if _in_dept(it)]
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
        # Defense-in-depth: strip angle brackets from EVERY string in the record — including nested
        # arrays/objects (claim & travel line-items, PADR goals, onboarding tasks) — so a stored value
        # can never inject markup when re-rendered. Angle brackets are never legitimate in this app's
        # HR/finance text, and the frontend also HTML-escapes on output.
        def _clean(v):
            if isinstance(v, str):
                return v.replace("<", "").replace(">", "")
            if isinstance(v, list):
                return [_clean(x) for x in v]
            if isinstance(v, dict):
                return {k: _clean(x) for k, x in v.items()}
            return v
        return _clean(dict(body or {}))

    _MONEY_MAX = 100_000_000_000   # 100 billion VND ceiling per record — anything above is a typo/abuse

    def _validate_money_item(self, name, item):
        def num(v):
            try:
                f = float(v)
            except (TypeError, ValueError):
                return None
            # Reject NaN / ±inf: they slip past the < 0 and > MAX comparisons (all NaN comparisons are
            # False) and, once stored, json.dumps emits non-standard NaN/Infinity that breaks the whole
            # collection's API response.
            if f != f or f in (float("inf"), float("-inf")):
                return None
            return f
        for k in ("amount", "cost", "total", "advance", "grandTotal"):
            if k in item and item.get(k) not in (None, ""):
                n = num(item.get(k))
                if n is None:
                    return "%s must be a number." % k
                if n < 0:
                    return "%s cannot be negative." % k
                if n > self._MONEY_MAX:
                    return "%s exceeds the allowed maximum." % k
        def _first_num(*keys):   # first PRESENT value (so an explicit cost of 0 isn't skipped by `or`)
            for k in keys:
                if item.get(k) not in (None, ""):
                    return num(item.get(k))
            return None
        adv, cost = num(item.get("advance")), _first_num("cost", "total", "amount")
        if adv is not None and cost is not None and adv > cost:
            return "The advance cannot exceed the total amount."
        for it in (item.get("items") or []):
            if isinstance(it, dict):
                n = num(it.get("amount"))
                if it.get("amount") not in (None, "") and (n is None or n < 0 or n > self._MONEY_MAX):
                    return "Each line amount must be a valid non-negative number."
        # Payroll records use their own money field names (no amount/cost/total). Every run total,
        # salary component and statutory deduction is an absolute value and must be a non-negative
        # number within the ceiling — a fat-fingered salary/override otherwise flows straight into
        # gross/net/employer-cost with nothing to reject it (these were previously unvalidated).
        if name in ("payruns", "payadjust"):
            pay_keys = ("gross", "net", "ee", "er", "pit", "erCost",
                        "basic", "posAllow", "responsibility", "skillSen", "P3",
                        "lunch", "phone", "transport", "eeBhxh", "eeBhyt", "eeBhtn")
            for k in pay_keys:
                if k in item and item.get(k) not in (None, ""):
                    n = num(item.get(k))
                    if n is None:
                        return "%s must be a number." % k
                    if n < 0:
                        return "%s cannot be negative." % k
                    if n > self._MONEY_MAX:
                        return "%s exceeds the allowed maximum." % k
            for arr in ("extraEarn", "extraDeduct"):
                for it in (item.get(arr) or []):
                    if isinstance(it, dict) and it.get("amt") not in (None, ""):
                        n = num(it.get("amt"))
                        if n is None or n < 0 or n > self._MONEY_MAX:
                            return "A payroll %s amount is invalid." % ("earning" if arr == "extraEarn" else "deduction")
        return None

    def _admin_errors(self, u):
        """Recent unhandled server errors — admin only (traces can contain sensitive request detail)."""
        if self._caller_level(u) != "admin":
            return self._err("Admin access required.", 403)
        return self._json({
            "count": len(_ERR_LOG),
            "uptime_s": int(time.time() - _STARTED_AT),
            "version": _app_version(),
            "alerting": bool(os.environ.get("TK_ALERT_WEBHOOK")),
            "errors": list(_ERR_LOG)[-100:],   # newest last
        })

    def _audit_verify(self, u):
        """Tamper-evidence check — admin only. Recomputes the audit hash chain end to end and reports
        whether it is intact (and if not, the first broken sequence number + why). This is what turns
        the append-only audit log into a *provably* untampered ledger: an edit, reorder, insertion, or
        deletion made directly against the DB file (bypassing the API's append-only guards) is detected."""
        if self._caller_level(u) != "admin":
            return self._err("Admin access required.", 403)
        return self._json(db.verify_audit_chain())

    def _metrics_report(self, u):
        """Request telemetry — admin only. Per-route counts, error count, avg + max latency, so the
        platform is diagnosable ('what is my p-ish latency / error rate') instead of guesswork."""
        if self._caller_level(u) != "admin":
            return self._err("Admin access required.", 403)
        rows = []
        tot_n = tot_err = 0
        tot_ms = 0.0
        with _METRICS_LOCK:
            for route, m in _METRICS.items():
                tot_n += m["n"]; tot_err += m["err"]; tot_ms += m["ms"]
                rows.append({"route": route, "n": m["n"], "err": m["err"],
                             "avgMs": round(m["ms"] / m["n"], 1) if m["n"] else 0,
                             "maxMs": round(m["max"], 1)})
        rows.sort(key=lambda r: r["n"], reverse=True)
        return self._json({
            "uptime_s": int(time.time() - _STARTED_AT),
            "version": _app_version(),
            "totalRequests": tot_n,
            "errorRequests": tot_err,
            "errorRate": round(tot_err / tot_n, 4) if tot_n else 0,
            "avgMs": round(tot_ms / tot_n, 1) if tot_n else 0,
            "routeCount": len(rows),
            "routes": rows[:200],
        })

    def _invtrack_status(self, u):
        if self._level_rank(self._caller_level(u)) < self._level_rank(self.INVTRACK_MIN):
            return self._err("Invoice Tracking requires Editor level or above.", 403)
        return self._json({"appReady": _invtrack_app_ready(), "mailbox": INVTRACK["mailbox"], "interval": INVTRACK["interval"],
                           "ocr": bool(INVTRACK["ocr_url"]), "pdf": _pdf_engine_ok(),
                           # SharePoint archive health — so a silently-failing archive is visible in Settings
                           "spConfigured": bool((db.get_setting("portal_invtrackSpUrl", "") or "").strip()),
                           "spHealth": dict(_INVTRACK_SP_HEALTH)})

    def _health_integrations(self, u):
        """One-screen operations health: each integration as ok / warn / down + a fix hint, so an admin
        can VERIFY the go-live switch-ons worked (M365 consent, invoice sync, approval email, SharePoint,
        push) instead of discovering a silent failure later. Manager+ (read-only status; no secrets)."""
        if self._level_rank(self._caller_level(u)) < self._level_rank("manager"):
            return self._err("Manager access required.", 403)
        rows = []

        def add(key, label, status, detail="", hint=""):
            rows.append({"key": key, "label": label, "status": status, "detail": detail, "hint": hint})

        ready = _invtrack_app_ready()
        add("m365", "Microsoft 365 app connection", "ok" if ready else "down",
            ("Connected · " + INVTRACK["mailbox"]) if ready else "Not connected",
            "" if ready else "Grant admin consent for Mail.Read (application) to the Humiley app in Entra, and set the client secret in .env.")

        cnt, ls = 0, ""
        try:
            docs = [d for d in db.list_collection("invtrack") if isinstance(d.get("items"), list)]
            docs.sort(key=lambda d: len(d.get("items") or []), reverse=True)
            if docs:
                meta = docs[0].get("meta") or {}
                cnt = len(docs[0].get("items") or [])
                ls = meta.get("lastSync") or meta.get("lastSyncRun") or ""
        except Exception:
            pass
        add("invsync", "Invoice inbox sync", "ok" if ls else ("warn" if ready else "down"),
            (str(cnt) + " invoices · last sync " + (ls or "never")),
            "" if ls else "Open Invoice Tracking → Get all tracks (needs the M365 connection above).")

        _roles = _graph_granted_roles() if ready else []
        ae_on = (db.get_setting("portal_apprEmail", "1") or "1").lower() in ("1", "true", "on", "yes")
        h = _APPR_EMAIL_HEALTH
        if not ae_on:
            st, det = "warn", "Turned off in Settings"
        elif h.get("lastError"):
            st, det = "down", "Last error: " + h.get("lastError", "")
        elif h.get("ok"):
            st, det = "ok", str(h.get("ok")) + " sent · last " + (h.get("at") or "")
        else:
            st, det = "warn", "On, but nothing sent yet — send a test"
        if st != "ok" and "Mail.Send" not in _roles:
            _fix = ("Mail.Send is NOT granted to this app. Entra → App registrations → API permissions "
                    "→ Microsoft Graph → Application permissions → Mail.Send → Grant admin consent.")
        elif st != "ok":
            _fix = "Mail.Send IS granted — just press 'Send a test email' above to prove it end to end."
        else:
            _fix = ""
        add("apprmail", "Approval emails (Mail.Send)", st, det, _fix)

        sp_conf = bool((db.get_setting("portal_invtrackSpUrl", "") or "").strip())
        sh = _INVTRACK_SP_HEALTH
        if not sp_conf:
            sst, sdet = "warn", "Not configured (files stay inside the portal)"
        elif sh.get("lastError"):
            sst, sdet = "down", "Last error: " + sh.get("lastError", "")
        elif sh.get("ok"):
            sst, sdet = "ok", str(sh.get("ok")) + " archived · last " + (sh.get("at") or "")
        else:
            sst, sdet = "warn", "Configured, nothing archived yet"
        _site_ok = any(r.startswith("Sites.") for r in _roles)
        if sp_conf and not _site_ok:
            _spfix = ("No Sites.* permission is granted, so every archive attempt will 403. Entra → "
                      "App registrations → API permissions → Microsoft Graph → Application "
                      "permissions → Sites.Selected (or Sites.ReadWrite.All) → Grant admin consent.")
        elif sst == "warn" and sp_conf:
            _spfix = "Press 'Archive existing files' on Invoice Tracking → Settings to file what is already captured."
        elif sst == "down":
            _spfix = "Check the folder link, then Invoice Tracking → Settings → Test connection."
        else:
            _spfix = ""
        add("sharepoint", "SharePoint invoice archive", sst, sdet, _spfix)

        # The FINANCE archive (payments / claims / travel) had no health row at all, so the exact
        # failure the owner hit — configured, permitted, and silently filing nothing — was invisible.
        fin_conf = bool((db.get_setting("portal_financeSpUrl", "") or "").strip())
        fh = _FINSP_HEALTH
        if not fin_conf:
            fst, fdet = "warn", "Not configured (files stay inside the portal)"
        elif fh.get("lastError"):
            fst, fdet = "down", "Last error: " + fh.get("lastError", "")
        elif fh.get("ok"):
            fst, fdet = "ok", str(fh.get("ok")) + " filed · last " + (fh.get("at") or "")
        else:
            fst, fdet = "warn", "Configured, nothing filed yet"
        add("finsp", "SharePoint finance archive (payments/claims/travel)", fst, fdet,
            ("No Sites.* permission is granted — see the row above." if (fin_conf and not _site_ok)
             else ("Press 'Archive existing files' under Access & Permissions → System Integrations."
                   if fst == "warn" and fin_conf else "")))

        # And say plainly what Microsoft has actually granted, so nobody has to guess again.
        _need = [("Mail.Read", "invoice inbox sync"), ("Mail.Send", "approval email")]
        _missing = [n for n, _ in _need if n not in _roles] + ([] if _site_ok else ["Sites.*"])
        add("graphperms", "Microsoft Graph permissions",
            "ok" if not _missing else "warn",
            ("Granted: " + (", ".join(_roles) if _roles else "(none)")),
            "" if not _missing else ("Missing: " + ", ".join(_missing) +
                                     " — add under Entra → App registrations → API permissions "
                                     "(Application), then Grant admin consent."))

        pdfok = _pdf_engine_ok()
        add("pdf", "Invoice PDF reader", "ok" if pdfok else "warn",
            "pypdf available" if pdfok else "pypdf missing — PDF invoices can't be read",
            "" if pdfok else "Add pypdf to the app image.")

        try:
            vp = _ensure_vapid()
            push_ok = bool(vp and vp.get("pub"))
        except Exception:
            push_ok = False
        add("push", "Push notifications", "ok" if push_ok else "warn",
            "Enabled" if push_ok else "Web-push keys unavailable",
            "" if push_ok else "Install pywebpush + cryptography in the app image.")

        rem_on = (db.get_setting("portal_apprReminders", "1") or "1").lower() in ("1", "true", "on", "yes")
        add("reminders", "Overdue-approval reminders", "ok" if rem_on else "warn",
            ("On · after " + (db.get_setting("portal_apprReminderDays", "2") or "2") + " days") if rem_on else "Off",
            "" if rem_on else "Turn on in Settings → Approval emails.")

        dig_on = _digest_enabled()
        _DAYS = ["Monday", "Tuesday", "Wednesday", "Thursday", "Friday", "Saturday", "Sunday"]
        try:
            _dd = _DAYS[int(db.get_setting("portal_digestDay", "0") or "0")]
        except Exception:
            _dd = "Monday"
        # Digest/monthly email go through the fire-and-forget _graph_send_mail, whose async 401/403 is
        # recorded in _APPR_EMAIL_HEALTH — NOT in _DIGEST/_MONTHLY_HEALTH. Surface that shared transport
        # error here so a missing Mail.Send consent can't leave these rows falsely green. The counter is
        # "queued" (attempts), not "sent" — fire-and-forget can't confirm delivery.
        _mail_err = _APPR_EMAIL_HEALTH.get("lastError") or ""
        _dig_err = _DIGEST_HEALTH.get("lastError") or _mail_err
        add("digest", "Weekly manager & leadership digest",
            "down" if (dig_on and _dig_err) else ("ok" if dig_on else "warn"),
            ("On · every " + _dd + (" · " + str(_DIGEST_HEALTH["sent"]) + " queued" if _DIGEST_HEALTH.get("sent") else "")) if dig_on else "Off (opt-in)",
            _dig_err if (dig_on and _dig_err) else ("" if dig_on else "Optional — turn on in Access & Permissions → System Integrations."))

        tkn_on = (db.get_setting("portal_tkNudges", "0") or "0").lower() in ("1", "true", "on", "yes")
        add("tknudge", "Timekeeping check-in/out nudges", "ok" if tkn_on else "warn",
            ("On · check-in " + (db.get_setting("portal_tkCheckinHour", "10") or "10") + ":00, check-out " + (db.get_setting("portal_tkCheckoutHour", "19") or "19") + ":00 (working days)") if tkn_on else "Off (opt-in)",
            "" if tkn_on else "Optional — push reminders; turn on in Access & Permissions → System Integrations.")

        mth_on = (db.get_setting("portal_monthlyReports", "0") or "0").lower() in ("1", "true", "on", "yes")
        _mth_err = _MONTHLY_HEALTH.get("lastError") or _mail_err
        add("monthly", "Monthly report pack",
            "down" if (mth_on and _mth_err) else ("ok" if mth_on else "warn"),
            ("On · day " + (db.get_setting("portal_monthlyDay", "1") or "1") + " each month" + (" · " + str(_MONTHLY_HEALTH["sent"]) + " queued" if _MONTHLY_HEALTH.get("sent") else "")) if mth_on else "Off (opt-in)",
            _mth_err if (mth_on and _mth_err) else ("" if mth_on else "Optional — auto-email leadership the month-end summary; turn on in Settings."))

        return self._json({"rows": rows, "checkedAt": _now_iso(),
                           "ok": sum(1 for r in rows if r["status"] == "ok"),
                           "warn": sum(1 for r in rows if r["status"] == "warn"),
                           "down": sum(1 for r in rows if r["status"] == "down"), "total": len(rows)})

    def _invtrack_sptest_ep(self, u):
        """Admin-only: run the SharePoint archive path end-to-end and report which stage fails.
           Admin-gated because it writes a probe file and is the same privilege as setting the link."""
        if self._caller_level(u) != "admin":
            return self._err("Admin access required to test the SharePoint connection.", 403)
        res = _invtrack_sp_diagnose()
        bad = next((s for s in res.get("stages", []) if not s.get("ok")), None)
        try:
            db.put_collection_item("audit", {
                "ts": _now_iso(), "by": u.get("name") or u.get("email") or "admin",
                "actor": u.get("email") or u.get("name") or "admin",
                "action": "Invoice SharePoint connection test", "target": res.get("folder") or "(not set)",
                "detail": "OK" if res.get("ok") else ("FAILED at " + (bad or {}).get("key", "?") + ": " + (bad or {}).get("detail", ""))})
        except Exception:
            pass
        return self._json(res)

    def _invtrack_spbackfill_ep(self, u):
        """Admin-only: push every already-captured file that isn't in SharePoint yet, so enabling the
           archive also covers invoices received before it was turned on."""
        if self._caller_level(u) != "admin":
            return self._err("Admin access required to archive to SharePoint.", 403)
        res = _invtrack_sp_backfill()
        if res.get("error") == "not_configured":
            return self._err("Set the SharePoint folder link first.", 400)
        try:
            db.put_collection_item("audit", {
                "ts": _now_iso(), "by": u.get("name") or u.get("email") or "admin",
                "actor": u.get("email") or u.get("name") or "admin",
                "action": "Invoice SharePoint backfill",
                "target": db.get_setting("portal_invtrackSpUrl", "") or "",
                "detail": "uploaded %s · failed %s · skipped %s · remaining %s" % (
                    res.get("uploaded", 0), res.get("failed", 0), res.get("skipped", 0), res.get("remaining", 0))})
        except Exception:
            pass
        return self._json(res)

    def _invtrack_file(self, u, fid, ext):
        """Serve a captured invoice attachment (PDF/XML/ZIP) by its content id. Gated to Invoice
        Tracking level. The id is a SHA-256 hex prefix — no path component — so no traversal."""
        if self._level_rank(self._caller_level(u)) < self._level_rank(self.INVTRACK_MIN):
            return self._err("Invoice Tracking requires Editor level or above.", 403)
        if not re.fullmatch(r"[0-9a-f]{1,64}", fid or "") or ext not in _INVTRACK_FILE_CT:
            return self._err("Not found.", 404)
        path = os.path.abspath(os.path.join(_INVTRACK_FILE_DIR, fid + "." + ext))
        if not path.startswith(os.path.abspath(_INVTRACK_FILE_DIR) + os.sep) or not os.path.isfile(path):
            return self._err("Not found.", 404)
        try:
            with open(path, "rb") as fh:
                data = fh.read()
        except OSError:
            return self._err("Not found.", 404)
        # SECURITY: these bytes are MAILBOX-SUPPLIED (anyone can email hd@humiley.com). Only a PDF is
        # safe to render inline — an XML/ZIP is an ACTIVE document type (XSLT / XHTML <script>), so
        # serving it inline as application/xml lets an attacker's attachment run JavaScript in the
        # portal origin and steal the session token. Force non-PDF to download as opaque bytes, and
        # sandbox EVERY file response so nothing scripts against portal.humiley.com.
        if ext == "pdf":
            ctype = "application/pdf"; disp = 'inline; filename="invoice-%s.pdf"' % fid[:12]
        else:
            ctype = "application/octet-stream"; disp = 'attachment; filename="invoice-%s.%s"' % (fid[:12], ext)
        self.send_response(200)
        self.send_header("Content-Type", ctype)
        self.send_header("Content-Length", str(len(data)))
        self.send_header("Content-Disposition", disp)
        self.send_header("X-Content-Type-Options", "nosniff")
        self.send_header("Content-Security-Policy", "sandbox; default-src 'none'")   # no scripts/network from this doc
        self.send_header("X-Download-Options", "noopen")
        self._emit_sec_headers(ctype)
        self.end_headers()
        try:
            self.wfile.write(data)
        except Exception:
            pass

    def _invtrack_sync_ep(self, u):
        if self._level_rank(self._caller_level(u)) < self._level_rank(self.INVTRACK_MIN):
            return self._err("Invoice Tracking requires Editor level or above.", 403)
        return self._json(_invtrack_sync("manual"))

    def _invtrack_import_ep(self, u, body):
        if self._level_rank(self._caller_level(u)) < self._level_rank(self.INVTRACK_MIN):
            return self._err("Invoice Tracking requires Editor level or above.", 403)
        return self._json(_invtrack_import(body or {}))

    def _invtrack_portal_fetch_ep(self, u, body):
        if self._level_rank(self._caller_level(u)) < self._level_rank(self.INVTRACK_MIN):
            return self._err("Invoice Tracking requires Editor level or above.", 403)
        return self._json(_invtrack_portal_fetch(body or {}))

    def _invtrack_attach_file_ep(self, u, body):
        if self._level_rank(self._caller_level(u)) < self._level_rank(self.INVTRACK_MIN):
            return self._err("Invoice Tracking requires Editor level or above.", 403)
        return self._json(_invtrack_attach_file(body or {}))

    def _appr_email_test(self, u):
        """Admin sends themselves a sample approval email — the way to verify Mail.Send consent works
        and to preview the branded template. Reports the last-send health so a 403/consent error shows."""
        if self._caller_level(u) != "admin":
            return self._err("Admin access required.", 403)
        to = (u.get("email") or "").strip()
        if not to:
            return self._err("Your account has no email address to send the test to.", 400)
        sender = _appr_email_sender("claims")
        rows = [("Type", "Test message"), ("Requester", u.get("name") or "Admin"),
                ("Reference", "TEST-0001"), ("Current status", "Submitted")]
        html = _appr_email_html("Approval email — connection test", "Submitted",
                                "This confirms the Humiley approval-email system can send from " + sender +
                                ". If it arrived, the Microsoft 365 Mail.Send permission is consented and working.",
                                rows, "Open the portal", _portal_base() + "/?inbox=1")
        _graph_send_mail(sender, [to], "[Humiley] Approval email — connection test", html)
        time.sleep(2.5)   # let the async send (incl. a possible token-refresh + retry) finish so health reflects THIS attempt
        h = _APPR_EMAIL_HEALTH
        ok = bool(h.get("ok")) and not h.get("lastError")
        return self._json({"ok": ok, "sentFrom": sender, "sentTo": to, "lastError": h.get("lastError", ""),
                           "message": ("Sent from %s to %s — check your inbox." % (sender, to)) if ok
                           else ("Send failed: " + (h.get("lastError") or "unknown — is Mail.Send consented for the app, and does the sender mailbox exist?"))})

    def _appr_remind_ep(self, u):
        """Admin: run the overdue-approval reminder sweep now (it otherwise runs every 6 h)."""
        if self._caller_level(u) != "admin":
            return self._err("Admin access required.", 403)
        n = _appr_reminders()
        return self._json({"ok": True, "sent": n,
                           "message": ("Sent %d reminder(s) for overdue approvals." % n) if n
                           else "No approvals are overdue for a reminder right now."})

    def _monthly_test(self, u):
        """Admin: email the month-end pack to YOURSELF as a preview (uses last month's data)."""
        if self._caller_level(u) != "admin":
            return self._err("Admin access required.", 403)
        to = (u.get("email") or "").strip()
        if not to:
            return self._err("Your account has no email address.", 400)
        _monthly_send(preview_to=to)
        time.sleep(2.5)
        h = _APPR_EMAIL_HEALTH
        ok = not h.get("lastError")
        return self._json({"ok": ok, "sentTo": to, "lastError": h.get("lastError", ""),
                           "message": ("Month-end pack sent to %s — check your inbox." % to) if ok
                           else ("Send failed: " + (h.get("lastError") or "unknown — is Mail.Send consented?"))})

    def _tk_nudge_test(self, u):
        """Admin: send a sample timekeeping nudge to YOURSELF only (verifies push works, no staff pinged)."""
        if self._caller_level(u) != "admin":
            return self._err("Admin access required.", 403)
        to = (u.get("email") or "").strip()
        if not to:
            return self._err("Your account has no email / push identity.", 400)
        if not _PUSH_OK:
            return self._json({"ok": False, "message": "Web Push isn't available on the server (install pywebpush + cryptography)."})
        n = _tk_push([to], "Check-in reminder (test)", "This is a test timekeeping nudge — real nudges reach staff who forget to check in/out.", "/?checkin=1", "tk-test")
        return self._json({"ok": n > 0, "sent": n,
                           "message": ("Test nudge pushed to your device." if n else "No push device is registered for your account — enable notifications on this device, then retry.")})

    def _appr_digest_test(self, u):
        """Admin: send yourself a preview of the weekly leadership digest (verifies it renders & delivers).
           Reports the same Mail.Send health as the approval-email test."""
        if self._caller_level(u) != "admin":
            return self._err("Admin access required.", 403)
        to = (u.get("email") or "").strip()
        if not to:
            return self._err("Your account has no email address to send the preview to.", 400)
        _digest_send(preview_to=to)
        time.sleep(2.5)   # let the async send (incl. a possible token-refresh + retry) finish
        h = _APPR_EMAIL_HEALTH
        ok = not h.get("lastError")
        return self._json({"ok": ok, "sentTo": to, "lastError": h.get("lastError", ""),
                           "message": ("Preview digest sent to %s — check your inbox." % to) if ok
                           else ("Send failed: " + (h.get("lastError") or "unknown — is Mail.Send consented?"))})

    @staticmethod
    def _invtrack_dup_error(body):
        """Server-side duplicate guard for the invoice register.

        invtrack is a single dataset doc whose `.items` array is the legal tax-invoice register. The
        BACKEND sync path de-dupes (_invtrack_dedupe_invoices), but the client's manual save writes an
        arbitrary array — so duplicate prevention was app-logic-only and a buggy/hostile client could
        inject the same legal invoice twice. Enforce it here, at the write boundary, for every caller.
        Identity mirrors the frontend's _invKey: mailbox message id first, else invoice-number+serial.
        """
        items = (body or {}).get("items")
        if not isinstance(items, list):
            return None
        seen = set()
        for it in items:
            if not isinstance(it, dict):
                continue
            msg = str(it.get("msgId") or it.get("internetMessageId") or "").strip()
            inv = str(it.get("invNo") or "").strip()
            key = ("m:" + msg) if msg else (("i:" + inv + "|" + str(it.get("serial") or "").strip()) if inv else "")
            if not key:
                continue                                  # unidentifiable row (still being captured) — don't block
            if key in seen:
                return ("Duplicate invoice in the register: %s. Each tax invoice may appear only once."
                        % (inv or msg))
            seen.add(key)
        return None

    def _payperiod_finalised(self, period):
        """True once a COMPANY pay run for this period has been finalised (Director-e-signed). A finalised
        month is closed — its manual payroll adjustments (payadjust) must not be added, edited or deleted
        afterwards, or a signed month's basis could be changed with no trail."""
        if not period:
            return False
        p = str(period).strip().lower()
        for r in db.list_collection("payruns"):
            if str(r.get("period") or "").strip().lower() == p and r.get("scope") != "individual" \
                    and str(r.get("status") or "").strip().lower() in ("finalised", "finalized"):
                return True
        return False

    def _audit_payadjust(self, u, action, item):
        """Manual payroll adjustments are money-affecting but had no audit trail — record every add/edit to
        the tamper-evident audit chain (delete is already audited by _coll_delete)."""
        db.put_collection_item("audit", {"actor": u.get("name") or "System", "actorId": u.get("id") or "",
            "action": action, "target": "payadjust/" + str(item.get("id") or ""),
            "detail": (str(item.get("empId") or "") + " · " + str(item.get("period") or "")
                       + (" · net " + str(item.get("net")) if item.get("net") is not None else "")),
            "ts": self._utc_now()})

    def _coll_add(self, u, name, body):
        if name not in self.COLLECTIONS:
            return self._err("Unknown collection.", 404)
        if not isinstance(body, dict):     # json.loads can return a list/str/number → dict() would 500
            return self._err("Invalid record.", 400)
        # Per-user app access — same gate as read/update/delete, so a disabled CRM/PM/HR app blocks
        # CREATE too (POST routes here, not through _coll_update).
        _app = "crm" if name.startswith("crm_") else ("pm" if name.startswith("pm_") else ("hr" if name in self.HR_APP_COLLS else None))
        if _app and _app in self._apps_denied(u):
            return self._err("Access restricted — the %s app is not enabled for your account." % _app.upper(), 403)
        if name.startswith("pm_") and name not in self.STAFF_WRITE and u.get("role") != "manager":
            return self._err("Manager access required.", 403)
        if name.startswith("crm_") or name.startswith("pm_") or name in ("claims", "travel", "payments", "leave", "audit", "padr", "acks", "enrollments", "onboarding", "jobs", "candidates", "reviews", "talent", "competency", "pip", "exits", "benefits", "devices", "handovers", "goals"):
            body = self._crm_sanitize(body)
        if name in self.PAYROLL_ADMIN and self._level_rank(self._caller_level(u)) < self._level_rank("editor"):
            return self._err("Payroll changes require Editor level or above.", 403)
        if name == "invtrack" and self._level_rank(self._caller_level(u)) < self._level_rank(self.INVTRACK_MIN):
            return self._err("Invoice Tracking requires Editor level or above.", 403)
        # A company policy is chased from every employee and signed against. The only gate used to be
        # `role == "manager"`, which let any line manager publish an audience=All document — and
        # locked out an Admin whose employee role is not literally "manager".
        if name == "hrdocs" and not self._is_hr_admin(u):
            return self._err("Publishing or changing a company document is for HR, Editors and "
                             "Administrators. An administrator can add you under Access & Permissions.", 403)
        if name == "invtrack":
            _dup = self._invtrack_dup_error(body)
            if _dup:
                return self._err(_dup, 400)
        item = dict(body or {})
        # SECURITY: a create must CREATE. put_collection_item is a blind upsert (INSERT ... ON CONFLICT
        # DO UPDATE), so a client-supplied `id` that already exists would OVERWRITE that row wholesale —
        # bypassing every owner/status/append-only guard the PATCH/DELETE paths enforce (a staff user
        # could destroy a signed claim/payment, re-own a CRM deal, or forge an audit entry via a known
        # id). Strip any incoming id so a fresh one is always minted; genuine edits go through PATCH.
        item.pop("id", None)
        # Amount sanity on money records: reject negative/non-numeric/absurd, advance<=cost.
        if name in ("claims", "travel", "payments", "payruns", "payadjust"):
            _err = self._validate_money_item(name, item)
            if _err:
                return self._err(_err, 400)
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
            item["ts"] = self._utc_now()   # server-stamp the time — a client-supplied ts could backdate an event
        if name.startswith("pm_"):
            item.setdefault("createdBy", u.get("name"))
            item.setdefault("createdById", u.get("id"))
        # A chat message says who said it, so authorship is stamped from the SESSION and the client's
        # version is discarded — setdefault would let a browser claim to be somebody else. Same for the
        # time: a client-supplied ts could backdate a message into the middle of an argument. Posting
        # is also refused outright on a project the caller cannot see, so the read scoping above
        # cannot be sidestepped by writing instead.
        # A signed acknowledgement is a statement that THIS person read THIS document. Identity, time
        # and the document version are stamped from the session and the published record — a browser
        # that could choose them could sign a policy in somebody else's name, or backdate a signature
        # to before an incident.
        # When a document was published, and by whom. Nothing recorded either before, and the due
        # date depends on it: _hrdoc_due takes the later of publication and the person's start date,
        # so with no publication date it collapses to the join date and every existing employee is
        # overdue the moment the document appears. Deletion was audited; publication was not.
        if name == "hrdocs":
            item["ts"] = self._utc_now()
            item["publishedBy"] = u.get("name") or ""
            item["publishedById"] = u.get("id") or ""
            item.pop("updatedBy", None)
            item.pop("updatedAt", None)
        if name == "hrdoc_acks":
            _doc = db.get_collection_item("hrdocs", str(item.get("docId") or "")) or {}
            if not _doc:
                return self._err("That document is no longer published.", 404)
            # You cannot have read a document that has no body. The acknowledgement PDF says in so
            # many words "I have received and read this document" — signing one for an empty record
            # produces a false statement on a controlled form, and the compliance matrix then reports
            # it green. The browser hides the button; this is the gate that cannot be walked past.
            if not (_doc.get("file") or _doc.get("fileUrl")):
                return self._err("That document has no file attached yet — there is nothing to read. "
                                 "HR needs to upload it before it can be signed.", 409)
            item["empId"] = u.get("id") or ""
            item["name"] = u.get("name") or ""
            item["ts"] = self._utc_now_ms()
            item["docTitle"] = _doc.get("title") or ""
            item["docCode"] = _doc.get("code") or ""
            item["docVersion"] = _doc.get("version") or ""
            item.pop("webUrl", None)             # only the server may say where it was filed
        if name == "pm_chat":
            vis = self._pm_visible_projects(u)
            if vis is not None and item.get("projectId") not in vis:
                return self._err("You can only post in a project you are on.", 403)
            item["authorName"] = u.get("name") or "User"
            item["authorId"] = u.get("id") or ""
            item["authorEmail"] = (u.get("email") or "").lower()
            item["createdBy"] = u.get("name")          # plain assignment, not setdefault: the pm_ block
            item["createdById"] = u.get("id")          # above would let a client pre-claim somebody
            item["ts"] = self._utc_now_ms()            # else's id and inherit their delete rights
            item["body"] = str(item.get("body") or "")[:8000]
            # Attachments are {name, url} and nothing else — a SharePoint webUrl, or an inline data:
            # URI when the project has no SharePoint folder. Bounded so a message cannot become a
            # payload, and the shape is rebuilt rather than accepted, so no extra keys ride along.
            _att = item.get("attachments")
            item["attachments"] = [
                {"name": str((a or {}).get("name") or "file")[:160],
                 "url": str((a or {}).get("url") or "")}
                for a in (_att if isinstance(_att, list) else [])[:6]
                if isinstance(a, dict) and str((a or {}).get("url") or "").strip()
            ][:6]
            item["reactions"] = {}                     # never born with reactions
            # The topic is rebuilt here. `item = dict(body)` above passes unknown keys straight
            # through, so without this the browser's value would be stored raw. An unrecognised key
            # becomes General rather than a 400 — a message must never fail to send over a label.
            _par_id = str(item.get("parentId") or "")
            if _par_id:
                # A reply has no topic of its own: it is stamped from the thread ROOT, so a thread
                # cannot split across two topics. The parent's project is checked at the same time —
                # parentId was never validated, so a crafted post could hang itself off a thread in
                # a project the caller cannot see.
                _par = db.get_collection_item("pm_chat", _par_id) or {}
                if _par.get("projectId") != item.get("projectId"):
                    return self._err("That reply does not belong to this project.", 400)
                if _par.get("parentId"):                   # one level only — re-point at the root
                    _root = db.get_collection_item("pm_chat", str(_par.get("parentId") or "")) or {}
                    if _root.get("projectId") == item.get("projectId"):
                        _par = _root
                        item["parentId"] = _root.get("id") or _par_id
                item["topic"] = str(_par.get("topic") or "")
            else:
                _tp = str(item.get("topic") or "")
                item["topic"] = _tp if _tp in self.PM_CHAT_TOPICS else ""
            # Mentions are {empId, name} and are checked against the project, not taken on trust. A
            # mention is the only thing here that buzzes somebody's phone, so an unchecked list would
            # be a way to make the portal ring anyone in the company from a project they cannot see.
            _vis_ids = set()
            for _r in db.list_collection("pm_resources"):
                if _r.get("projectId") == item.get("projectId") and _r.get("empId"):
                    _vis_ids.add(_r.get("empId"))
            _proj = next((x for x in db.list_collection("pm_projects") if x.get("id") == item.get("projectId")), {})
            _men, _seen = [], set()
            for _m in (item.get("mentions") if isinstance(item.get("mentions"), list) else [])[:20]:
                if not isinstance(_m, dict):
                    continue
                _eid = str(_m.get("empId") or "")
                if not _eid or _eid in _seen:
                    continue
                _emp = db.get_employee(_eid)
                if not _emp:
                    continue
                # ON THIS PROJECT ONLY: a row on its Team, or its Project Manager. Being a manager
                # is NOT a route in — a manager can READ every conversation, but @ is a summons, and
                # summoning somebody to a job they are not on is how a channel turns into a paging
                # system for the whole company. If they are needed, put them on the Team.
                _ok = _eid in _vis_ids or self._pm_same_person(_proj.get("manager"), _emp.get("name"))
                if not _ok:
                    for _r in db.list_collection("pm_resources"):
                        if _r.get("projectId") == item.get("projectId") and self._pm_same_person(_r.get("name"), _emp.get("name")):
                            _ok = True
                            break
                if _ok:
                    _seen.add(_eid)
                    _men.append({"empId": _eid, "name": _emp.get("name") or ""})
            item["mentions"] = _men
            for k in ("editedAt", "deletedAt", "deletedBy"):
                item.pop(k, None)                      # a message is never born edited or deleted
        # Payroll dual-control: a run is PREPARED here (never born finalised, even if the client says so)
        # and only a Director e-signature (/api/esign, preparer != approver) can finalise it. Stamp the
        # preparer so segregation of duties can exclude them.
        if name == "payruns":
            # A salary nobody agreed can never enter a pay run. `_payComputed` prices an employee with
            # no salary on file at the GRADE MID-POINT — a full gross, PIT and statutory footprint
            # invented for a figure nobody signed — and the browser guard covered only one of the
            # three buttons that create a run. This is the boundary that covers all of them, and any
            # future one: the run is refused, by name, before it can be prepared and e-signed.
            _no_salary = []
            for _ln in (item.get("lines") if isinstance(item.get("lines"), list) else []):
                if not isinstance(_ln, dict):
                    continue
                _e = db.get_employee(str(_ln.get("empId") or "")) if _ln.get("empId") else None
                try:
                    _ok = _e and float(_e.get("salary") or 0) > 0
                except (TypeError, ValueError):
                    _ok = False
                if not _ok:
                    _no_salary.append(str(_ln.get("name") or _ln.get("empId") or "?"))
            if _no_salary:
                return self._err("These employees have no salary on record, so there is nothing to "
                                 "pay them from: %s. Enter the agreed salary first."
                                 % ", ".join(_no_salary[:8]), 400)
            item["status"] = "Pending Approval"
            item["preparedBy"] = u.get("name")
            item["preparedById"] = u.get("id")
        # Manual payroll adjustment: a finalised (closed) month is locked, and every add is written to the
        # tamper-evident audit trail (adjustments are money-affecting but previously had no audit record).
        if name == "payadjust":
            if self._payperiod_finalised(item.get("period")):
                return self._err("That pay period is finalised and locked — payroll adjustments can no longer be added.", 403)
            created = db.put_collection_item("payadjust", item)
            self._audit_payadjust(u, "Payroll adjustment added", created)
            return self._json({"ok": True, "item": created})
        # Idempotency: a retried identical financial submit within the window returns the record the
        # first attempt already created, instead of a duplicate (transport-retry double-pay guard).
        # For financial collections the check + create + store all run under ONE lock, so a CONCURRENT
        # identical submit (this is a ThreadingHTTPServer) cannot slip a second row in between the
        # check and the store. Financial creates are low-volume, so serialising them here is fine.
        if name in _IDEM_COLLS:
            _ik = _idem_key(u.get("id"), name, item, self.headers.get("Idempotency-Key"))
            with _IDEM_LOCK:
                _prev = _IDEM.get(_ik)
                if _prev and time.time() - _prev[1] < _IDEM_WINDOW:
                    return self._json({"ok": True, "item": _prev[0], "idempotent": True})
                created = db.put_collection_item(name, item)
                _IDEM[_ik] = (created, time.time())
                if len(_IDEM) > 2000:                                  # bound memory: drop entries past the window
                    _cut = time.time() - _IDEM_WINDOW
                    for _k in [k for k, v in list(_IDEM.items()) if v[1] < _cut]:
                        _IDEM.pop(_k, None)
            self._finsp_file(name, created)
            return self._json({"ok": True, "item": created})
        _created = db.put_collection_item(name, item)
        # A mention is the ONLY thing in the conversation that reaches somebody's phone. Not every
        # message, not a reply — a direct mention. An engineer standing on a site who gets one false
        # alarm mutes the app, and then the approval reminders stop reaching them too, so the bar for
        # buzzing a pocket is deliberately high. Fan-out runs server-side off a caller whose project
        # membership was proved a few lines above, so no new client-callable broadcast exists.
        if name == "pm_chat" and _created.get("mentions"):
            try:
                _ids = {m.get("empId") for m in _created["mentions"] if m.get("empId")}
                _me = (u.get("email") or "").lower()
                _to = [(e.get("email") or "").lower() for e in db.list_employees()
                       if e.get("id") in _ids and e.get("email")
                       and str(e.get("status") or "Active").lower() != "inactive"]
                _to = [e for e in _to if e and e != _me][:20]          # never buzz yourself
                if _to:
                    _pj = next((x for x in db.list_collection("pm_projects")
                                if x.get("id") == _created.get("projectId")), {})
                    _label = (_pj.get("code") or _pj.get("name") or "Project")
                    _txt = (_created.get("body") or "").strip() or "(attachment)"
                    # Deep-link to the message, not the front door: being told you were named and
                    # then having to find the job, the tab and the line yourself is most of the work
                    # of answering. Same-origin path only — the service worker refuses anything else.
                    _url = "/?chat=" + urllib.parse.quote(str(_created.get("projectId") or "")) + \
                           "&msg=" + urllib.parse.quote(str(_created.get("id") or ""))
                    _tk_push(_to, (_created.get("authorName") or "Someone") + " \u00b7 " + _label,
                             _txt[:160], _url, "pmchat-" + str(_created.get("projectId") or ""))
            except Exception:
                pass                                                   # a chat post must never fail on a push
        if name == "hrdocs":
            self._audit_hrdoc(u, "Published document", _created)
        self._finsp_file(name, _created)
        return self._json({"ok": True, "item": _created})

    def _audit_hrdoc(self, u, action, doc):
        """Record a change to a company document in the tamper-evident chain.

        Destruction was already logged and creation was not, which is the asymmetry that matters
        least for accidents and most for arguments: 'who changed this policy after people signed it'
        had no answer."""
        try:
            db.put_collection_item("audit", {
                "actor": u.get("name") or "System", "actorId": u.get("id") or "",
                "action": action,
                "target": "hrdocs/" + str((doc or {}).get("id") or ""),
                "detail": " ".join(x for x in [
                    (doc or {}).get("code") or "", (doc or {}).get("title") or "",
                    ("v" + str((doc or {}).get("version"))) if (doc or {}).get("version") else "",
                    "audience=" + str((doc or {}).get("audience") or "All"),
                    "file=" + ("yes" if ((doc or {}).get("file") or (doc or {}).get("fileUrl")) else "NO"),
                ] if x)[:400],
                "ts": self._utc_now()})
        except Exception:
            pass                       # the document is published; a failed audit write must not undo it

    @staticmethod
    def _finsp_file(name, created):
        """File a newly submitted payment/claim/travel into the Finance SharePoint library, server-side.

        Runs in a thread so a slow SharePoint never delays the submit response — the in-portal copy is
        canonical and this is an archive. Failures are recorded in _FINSP_HEALTH, never raised: a
        request must not fail to submit because SharePoint is unreachable."""
        kind = {"payments": "payment", "claims": "claim", "travel": "travel"}.get(name)
        if not kind or not isinstance(created, dict) or not created.get("attachment"):
            return
        try:
            threading.Thread(target=_finsp_archive, args=(created, kind), daemon=True).start()
        except Exception:
            pass

    def _device_ack_backfill_ep(self, u):
        # One-time migration (admin): every CURRENTLY-ASSIGNED asset/assignment with no acknowledgment is
        # marked acknowledged-on-record, so pre-feature assignments don't all show "Awaiting signature".
        # Records a NON-drawn legacy ack (method=migration, no image) so the audit stays honest — it is
        # explicitly not a forged hand signature.
        if self._caller_level(u) != "admin":
            return self._err("Admin access required.", 403)
        now = self._utc_now()
        today = time.strftime("%Y-%m-%d")

        def _acked(sigs, ack_on):
            if ack_on:
                return True
            for s in (sigs or []):
                m = str((s or {}).get("meaning") or "").lower()
                if (s or {}).get("ack") or "acknowled" in m or "handover" in m:
                    return True
            return False

        def _mk(who):
            return {"name": who or "", "meaning": "Asset handover — acknowledged (existing record, migrated)",
                    "ts": now, "method": "migration", "by": "System — pre-existing record", "ack": True, "legacy": True}

        n = 0
        for x in db.list_collection("devices"):
            changed = False
            assigns = x.get("assignments")
            if isinstance(assigns, list) and assigns:
                for a in assigns:
                    if not isinstance(a, dict) or _acked(a.get("signatures"), a.get("ackOn")):
                        continue
                    a.setdefault("signatures", []).append(_mk(a.get("name")))
                    a["ackOn"] = a.get("assignedOn") or today
                    a["ackBy"] = a.get("name") or ""
                    changed = True
                    n += 1
                if changed:
                    x["assignments"] = assigns
            else:
                status = str(x.get("status") or "")
                assigned = (x.get("empId") or x.get("assignedTo")) and status not in ("Available", "Retired")
                if assigned and not _acked(x.get("signatures"), x.get("ackOn")):
                    x.setdefault("signatures", []).append(_mk(x.get("assignedTo")))
                    x["ackOn"] = x.get("assignedOn") or x.get("purchaseDate") or today
                    x["ackBy"] = x.get("assignedTo") or ""
                    changed = True
                    n += 1
            if changed:
                db.put_collection_item("devices", x)
        if n:
            db.put_collection_item("audit", {"actor": u.get("name"), "actorId": u.get("id"),
                "action": "Asset acknowledgment backfill", "target": "devices",
                "detail": "%d assignment(s) marked acknowledged-on-record" % n, "ts": now})
        return self._json({"ok": True, "count": n})

    # The ONLY fields the backfill endpoint may touch. Everything else in the request is ignored — the
    # whole point of a narrow endpoint is that it can never become a second full-document PATCH.
    PAY_BANK_FIELDS = ("payeeCompany", "payeeMst", "bankName", "bankAcc", "bankHolder", "bankBranch")

    def _pay_bank_backfill(self, u, body):
        """Finance fills in the beneficiary bank details of an ALREADY-DECIDED payment.

        The generic PATCH path correctly refuses to edit a decided money record (signed evidence), but
        payments created before these fields existed have no beneficiary details at all, and Finance
        needs them to release a transfer and to file the accounting export. So: a separate endpoint
        that can change nothing else — not the amount, the payee, the status, the signatures or the
        attachment — and that audits every change with its before and after value.

        Once a payment has been PAID, recorded details become the historical record of where the money
        actually went: blanks may still be filled in, but an existing value can no longer be altered.
        Before payment Finance may also correct a typo, since the people who can do this are the same
        people who execute the transfer — restricting them further would not prevent anything."""
        if not self._rate_check("paybank", 30, 60):
            return
        if self._level_rank(self._caller_level(u)) < self._level_rank("editor"):
            return self._err("Finance (Editor) access is required to update beneficiary bank details.", 403)
        # _body() is fail-soft: a malformed or oversized payload arrives as {}. Without these checks
        # a truncated request would read as "blank out every beneficiary field".
        if not isinstance(body, dict):
            return self._err("Invalid request.", 400)
        pid = str(body.get("id") or "").strip()
        if not pid:
            return self._err("A payment id is required.", 400)
        raw = body.get("fields")
        if not isinstance(raw, dict):
            return self._err("No bank details were supplied.", 400)
        # Build from the WHITELIST, never from the body. _crm_sanitize strips angle brackets — these
        # values are rendered into approval emails, the request PDF and the Excel export, so skipping
        # it on a new write path would reopen the stored-XSS hole the QA pass closed.
        clean = self._crm_sanitize({k: raw.get(k) for k in self.PAY_BANK_FIELDS if k in raw})
        incoming = {}
        for k in self.PAY_BANK_FIELDS:
            if k not in clean or clean.get(k) is None:
                continue
            incoming[k] = str(clean[k]).strip()[:120]
        if not incoming:
            return self._err("No bank details were supplied.", 400)
        try:
            want_rev = int(body.get("_rev")) if body.get("_rev") is not None else None
        except (TypeError, ValueError):
            want_rev = None
        # Same lock /api/esign takes, so a signature append and a backfill can't each read the record
        # and then clobber the other's write.
        with self._ESIGN_LOCK:
            return self._pay_bank_backfill_locked(u, pid, incoming, want_rev)

    def _pay_bank_backfill_locked(self, u, pid, incoming, want_rev):
        item = db.get_collection_item("payments", pid)
        if not item:
            return self._err("Payment not found.", 404)
        if want_rev is not None and int(item.get("_rev") or 0) != want_rev:
            # _json, not _err: _err emits only {"error": …} and would drop the fields the frontend's
            # 409 branch reads.
            return self._json({"error": "This record was just changed by someone else. Reload the "
                                        "latest version and re-apply your change.",
                               "conflict": True, "currentRev": int(item.get("_rev") or 0)}, 409)
        paid = str(item.get("status") or "").strip().lower() == "paid"
        changes = []
        for k, new in incoming.items():
            old = str(item.get(k) or "").strip()
            if old == new:
                continue                      # no-op: a retried request must not 403
            if paid and old:
                return self._err("This payment has already been released. A recorded beneficiary "
                                 "detail is the historical record of where the money went and cannot "
                                 "be changed — only blank fields can be filled in.", 403)
            changes.append((k, old, new))
        # Validate the WHOLE batch before mutating anything, so a partially-rejected request never
        # half-applies.
        if not changes:
            return self._json({"ok": True, "item": {k: v for k, v in item.items() if k != "token"},
                               "changed": []})
        for k, _old, new in changes:
            item[k] = new
        db.put_collection_item("payments", item)

        def _mask(field, v):
            # The audit trail is append-only and un-redactable, and admins read it wholesale — keeping
            # full beneficiary account numbers in it forever is the wrong trade.
            if field == "bankAcc" and len(v) > 4:
                return "••••" + v[-4:]
            return v or "—"
        detail = " · ".join("%s: %s → %s" % (k, _mask(k, old), _mask(k, new))
                                 for k, old, new in changes)
        db.put_collection_item("audit", {
            "actor": u.get("name") or "System", "actorId": u.get("id") or "",
            "action": "Payment beneficiary bank details updated",
            "target": "payments/" + str(pid),
            "detail": (str(item.get("reqNo") or pid) + " · " + str(item.get("status") or "-")
                       + " · " + detail),
            "ts": self._utc_now()})
        return self._json({"ok": True, "item": {k: v for k, v in item.items() if k != "token"},
                           "changed": [c[0] for c in changes]})

    @staticmethod
    def _hr_emp_folder(emp):
        """One folder per employee, named so it sorts by id and stays readable: "HML-007 - Nguyen Van A".
        The id leads because names repeat and change; the name follows so a human can find it."""
        eid = str((emp or {}).get("id") or "").strip() or "unknown"
        nm = str((emp or {}).get("name") or "").strip()
        return (eid + " - " + nm).strip(" -")

    def _hr_onb_file_ep(self, u, body):
        """File a signed onboarding acknowledgement into the employee's own HR SharePoint folder.

        The signature is the record that somebody read a policy, so it belongs with the rest of that
        person's file — not only in an application database. Runs while the employee is watching, so
        it reports what happened; if SharePoint is not configured the acknowledgement still stands and
        stays in the portal."""
        aid = str((body or {}).get("ackId") or "")
        ack = db.get_collection_item("hrdoc_acks", aid) if aid else None
        if not ack:
            return self._err("Acknowledgement not found.", 404)
        # Only the person who signed it (or an HR manager) may file it.
        if (ack.get("empId") or "") != (u.get("id") or "") and \
                self._level_rank(self._caller_level(u)) < self._level_rank("manager"):
            return self._err("You can only file your own acknowledgement.", 403)
        data = str((body or {}).get("data") or "")
        if not data.startswith("data:"):
            return self._err("No document received.", 400)
        head, _, b64 = data.partition(",")
        try:
            raw = base64.b64decode(b64 + "=" * (-len(b64) % 4))
        except Exception:
            return self._err("That document could not be read.", 400)
        if not raw or len(raw) > _INVTRACK_FILE_MAX:
            return self._err("That document is empty or too large.", 400)
        emp = db.get_employee(ack.get("empId") or "") or {"id": ack.get("empId"), "name": ack.get("name")}
        code = str(ack.get("docCode") or "").strip()
        name = (("%s - " % code) if code else "") + str(ack.get("docTitle") or "Acknowledgement") + " - signed.pdf"
        out = {"ok": True, "filed": False, "error": ""}
        try:
            web = _hrsp_put(["Employees", self._hr_emp_folder(emp), "Onboarding"], name, raw,
                            head[5:].split(";")[0] or "application/pdf")
            if web:
                ack["webUrl"] = web
                ack["fileName"] = name
                db.put_collection_item("hrdoc_acks", ack)
                out["filed"] = True
                out["webUrl"] = web
        except Exception as e:
            out["error"] = _graph_err_text(e)[:200]
        return self._json(out)

    def _hr_emp_folders_ep(self, u):
        """Create the HR SharePoint folder for every active employee and drop their record in it.

        Idempotent: re-running refreshes each profile file and creates only what is missing. The
        profile is a plain text summary rather than a database dump — a folder somebody opens in a
        browser should be readable, and it must not carry more personal data than the HR file needs."""
        if self._level_rank(self._caller_level(u)) < self._level_rank("admin"):
            return self._err("Admin access required.", 403)
        if not (db.get_setting("portal_hrSpUrl", "") or "").strip():
            return self._err("Set the HR SharePoint folder in Company Portal settings first.", 400)
        made, failed, errs = 0, 0, []
        for e in db.list_employees():
            if str(e.get("status") or "Active").lower() == "inactive":
                continue
            lines = [
                "EMPLOYEE RECORD", "",
                "Employee ID   : %s" % (e.get("id") or ""),
                "Name          : %s" % (e.get("name") or ""),
                "Position      : %s" % (e.get("title") or ""),
                "Department    : %s" % (e.get("dept") or ""),
                "Email         : %s" % (e.get("email") or ""),
                "Phone         : %s" % (e.get("phone") or ""),
                "Join date     : %s" % (e.get("joinDate") or e.get("onboardDate") or ""),
                "Direct manager: %s" % (e.get("managerEmail") or ""),
                "Status        : %s" % (e.get("status") or "Active"),
                "", "Generated by the Humiley Portal on %s." % self._utc_now(),
                "This folder holds this employee's HR documents: signed policy acknowledgements,",
                "contracts and onboarding records.",
            ]
            try:
                _hrsp_put(["Employees", self._hr_emp_folder(e)], "00 - Employee record.txt",
                          "\r\n".join(lines).encode("utf-8"), "text/plain")
                made += 1
            except Exception as ex:
                failed += 1
                if len(errs) < 3:
                    errs.append((e.get("name") or e.get("id") or "?") + ": " + _graph_err_text(ex)[:120])
        try:
            db.put_collection_item("audit", {
                "actor": u.get("name") or "", "actorId": u.get("id") or "", "action": "hr.folders",
                "detail": "HR SharePoint employee folders: %d created/refreshed, %d failed" % (made, failed),
                "ts": self._utc_now()})
        except Exception:
            pass
        return self._json({"ok": True, "created": made, "failed": failed, "errors": errs})

    # The six policies that were hardcoded in the frontend, with the codes they carried. Published
    # at v1.0 so the EXISTING tick-box acknowledgements map onto them; HR then re-issues at a higher
    # version to collect real signatures against the actual PDF.
    LEGACY_POLICIES = [
        ("Employee Handbook", "HML-HR-001", "Handbook"),
        ("Code of Conduct & Anti-Harassment", "HML-HR-002", "Code of Conduct"),
        ("IT Acceptable Use Policy", "HML-IT-001", "IT"),
        ("Confidentiality, IP & Data", "HML-LE-001", "Policy"),
        ("HSE / Site Safety", "HML-HSE-001", "HSE"),
        ("C&B Policy (HML-CB-001)", "HML-CB-001", "Policy"),
    ]

    def _hr_policy_migrate_ep(self, u):
        """Move the six hardcoded policies, and every tick-box acknowledgement of them, into the
        document system — once.

        The old records are NOT discarded and NOT dressed up. Each becomes an acknowledgement marked
        method='legacy-tickbox' with no signature image, because that is what actually happened: the
        person ticked a box. Inventing a signature image for them would be a forgery, and an auditor
        who finds one is far worse off than one who reads "acknowledged by tick-box on 12 Mar 2026".

        Idempotent: re-running adds nothing that is already there."""
        if self._level_rank(self._caller_level(u)) < self._level_rank("admin"):
            return self._err("Admin access required.", 403)
        existing = {str(d.get("code") or ""): d for d in db.list_collection("hrdocs")}
        made, mapped, skipped = 0, 0, 0
        code_by_title = {}
        for title, code, cat in self.LEGACY_POLICIES:
            doc = existing.get(code)
            if not doc:
                doc = db.put_collection_item("hrdocs", {
                    "title": title, "code": code, "version": "1.0", "category": cat,
                    "audience": "All", "dueDays": 0,
                    # `summary` is labelled "Short summary shown to the employee" and is rendered on
                    # their card and above the signature block. HR's own to-do belongs in hrNote,
                    # which only the register reads — everybody in the company was being shown
                    # "Upload the controlled PDF and re-issue at a new version".
                    "summary": "",
                    "hrNote": "Migrated from the portal's built-in policy list. Attach the controlled "
                              "PDF, then re-issue at a new version to collect real signatures.",
                    "migrated": True, "ts": self._utc_now()})
                made += 1
            elif doc.get("migrated") and str(doc.get("summary") or "").startswith("Migrated from the portal"):
                # Repair the records already published with HR's note in the employee-facing field.
                doc = db.put_collection_item("hrdocs", dict(
                    doc, summary="",
                    hrNote=doc.get("hrNote") or "Migrated from the portal's built-in policy list. "
                                                "Attach the controlled PDF, then re-issue at a new "
                                                "version to collect real signatures."))
            code_by_title[title] = doc
        have = {(a.get("docId"), a.get("empId"), str(a.get("docVersion") or ""))
                for a in db.list_collection("hrdoc_acks")}
        for a in db.list_collection("acks"):
            doc = code_by_title.get(str(a.get("doc") or ""))
            if not doc:
                skipped += 1
                continue
            key = (doc.get("id"), a.get("empId"), "1.0")
            if key in have:
                continue
            emp = db.get_employee(a.get("empId") or "") or {}
            db.put_collection_item("hrdoc_acks", {
                "docId": doc.get("id"), "empId": a.get("empId") or "",
                "name": emp.get("name") or a.get("name") or "",
                "ts": a.get("ts") or "", "docTitle": doc.get("title"), "docCode": doc.get("code"),
                "docVersion": "1.0",
                # Deliberately no signature image. This was a tick-box, and the record says so.
                "method": "legacy-tickbox",
                "meaning": "Acknowledged by tick-box in the portal (migrated record, not a signature)",
                "legacy": True})
            have.add(key)
            mapped += 1
        try:
            db.put_collection_item("audit", {
                "actor": u.get("name") or "", "actorId": u.get("id") or "", "action": "hr.policy.migrate",
                "detail": "Legacy policies migrated: %d documents published, %d tick-box "
                          "acknowledgements carried over as legacy records, %d unmatched"
                          % (made, mapped, skipped),
                "ts": self._utc_now()})
        except Exception:
            pass
        return self._json({"ok": True, "documents": made, "acknowledgements": mapped, "unmatched": skipped})

    def _hr_compliance_ep(self, u):
        """Who has signed what, and who has not. The one screen an auditor asks for.

        Computed here rather than in the browser because it needs EVERY employee — and staff reads of
        hrdoc_acks are scoped to the caller's own, correctly so. Manager and above only: it is a list
        of who is behind, which is management information, not self-service."""
        if self._level_rank(self._caller_level(u)) < self._level_rank("manager"):
            return self._err("Manager access required.", 403)
        today = time.strftime("%Y-%m-%d")
        docs = [d for d in db.list_collection("hrdocs") if not d.get("archived")]
        emps = [e for e in db.list_employees()
                if str(e.get("status") or "Active").lower() != "inactive"]
        acks = {}
        for a in db.list_collection("hrdoc_acks"):
            acks[(a.get("docId"), a.get("empId"), str(a.get("docVersion") or ""))] = a
        rows, doc_stats = [], []
        for d in docs:
            ver = str(d.get("version") or "")
            targets = _hrdoc_targets(d, emps)
            has_file = _hrdoc_has_file(d)
            signed = 0
            for e in targets:
                a = acks.get((d.get("id"), e.get("id"), ver))
                due = _hrdoc_due(d, e)
                if a:
                    signed += 1
                # "nofile" is HR's problem, not the employee's — showing it as overdue would put a red
                # mark against a person for not signing something nobody gave them.
                state = "signed" if a else ("nofile" if not has_file
                                           else ("overdue" if (due and due < today) else "outstanding"))
                rows.append({
                    "docId": d.get("id"), "docTitle": d.get("title") or "", "docCode": d.get("code") or "",
                    "version": ver, "empId": e.get("id"), "name": e.get("name") or "",
                    "dept": e.get("dept") or "", "due": due, "state": state,
                    "signedOn": (a or {}).get("ts", ""), "filed": bool((a or {}).get("webUrl")),
                })
            doc_stats.append({"id": d.get("id"), "title": d.get("title") or "", "code": d.get("code") or "",
                              "version": ver, "required": len(targets), "signed": signed,
                              "hasFile": has_file,
                              "pct": (round(signed * 100.0 / len(targets)) if targets else 100)})
        return self._json({"ok": True, "rows": rows, "docs": doc_stats,
                           "employees": [{"id": e.get("id"), "name": e.get("name") or "",
                                          "dept": e.get("dept") or ""} for e in emps]})

    def _emp_history_ep(self, u, eid):
        """One employee's effective-dated history — the answer to "what was this in March".

        Scoped exactly like the roster, because it holds the same data over time. Management and above
        see everything. You always see your OWN full history, salary included: it is your pay, and
        being able to check what you were paid and from when is the point of keeping it. A line
        manager sees their own reports WITHOUT the compensation fields, matching `_emp_list_for` —
        anything looser would make this endpoint a way around the roster's scoping."""
        emp = db.get_employee(eid)
        if not emp:
            return self._err("Employee not found.", 404)
        rank = self._level_rank(self._caller_level(u))
        mine = (eid == u.get("id"))
        my_email = (u.get("email") or "").strip().lower()
        manages = bool(my_email) and (emp.get("managerEmail") or "").strip().lower() == my_email
        if not (mine or manages or rank >= self._level_rank("management")):
            return self._err("You can only see the history of your own record or your own team.", 403)
        hide_pay = not (mine or rank >= self._level_rank("management"))
        rows = [r for r in db.list_emp_events(emp_id=eid)
                if not (hide_pay and r.get("field") in ("salary", "grade"))]
        return self._json({"ok": True, "empId": eid, "name": emp.get("name") or "",
                           "events": rows, "payHidden": hide_pay})

    def _ot_totals_for(self, emp_id, date_iso, exclude_id=None):
        """This employee's approved overtime on that day, in that month and in that year.

        `exclude_id` drops the record being decided, so the caller can add its hours itself and ask
        the honest question — "if I approve this, where does it leave us" — rather than measuring a
        total that already contains, or already excludes, the thing under consideration.
        """
        year, ym, day = str(date_iso)[:4], str(date_iso)[:7], str(date_iso)[:10]
        rows = db.list_ot_approved(year + "-01-01", year + "-12-31", emp_id=emp_id)
        d = mo = yr = 0.0
        for r in rows:
            if exclude_id is not None and r.get("id") == exclude_id:
                continue
            try:
                h = float(r.get("ot_hours") or 0)
            except (TypeError, ValueError):
                continue
            yr += h
            rd = str(r.get("date") or "")
            if rd[:7] == ym:
                mo += h
            if rd[:10] == day:
                d += h
        return d, mo, yr

    def _ot_summary_ep(self, u, qs):
        """Approved overtime for a month, valued in rate-units and measured against the caps.

        The money is deliberately NOT finished here. This returns `units` — the multiplier-hours
        Art. 98 produces once the day type and the night window are applied — and the payroll screen
        multiplies them by that employee's own hourly wage, which is the one number the wage model
        already owns. So the law lives in overtime.py where it is tested, the wage lives with the
        wage, and neither has to be restated in the other's language.

        Scoped like the roster: your own overtime always, your direct reports' if you manage them,
        everybody's from management up.
        """
        period = str((qs.get("period", [None])[0] or ""))[:7]
        if not re.match(r"^\d{4}-\d{2}$", period):
            period = self._vn_day()[:7]
        rank = self._level_rank(self._caller_level(u))
        emps = db.list_employees()
        if rank < self._level_rank("management"):
            my_email = (u.get("email") or "").strip().lower()
            emps = [e for e in emps if e.get("id") == u.get("id")
                    or (my_email and (e.get("managerEmail") or "").strip().lower() == my_email)]
        allowed = {e.get("id") for e in emps}

        rows_by_emp = {}
        for r in db.list_ot_approved(period + "-01", period + "-31"):
            if r.get("emp_id") in allowed:
                rows_by_emp.setdefault(r.get("emp_id"), []).append(r)

        hols = _ot_holiday_set()
        scheds = db.list_collection("schedules")
        cap_y = _ot_annual_cap()
        out = []
        for e in emps:
            recs = rows_by_emp.get(e.get("id")) or []
            if not recs:
                continue
            rest = _rest_weekdays_for(e, scheds)
            # hourly = 1.0, so `pay` comes back as the pure multiplier-hours the frontend scales.
            s = overtime.month_summary(recs, 1.0, hols, rest)
            _, month_h, year_h = self._ot_totals_for(e.get("id"), period + "-01")
            worst_day = max(s["byDate"].values()) if s["byDate"] else 0.0
            caps = overtime.cap_check(worst_day, month_h, year_h, annual_cap=cap_y)
            out.append({"empId": e.get("id"), "name": e.get("name") or "", "dept": e.get("dept") or "",
                        "hours": round(s["hours"], 2), "nightHours": round(s["nightHours"], 2),
                        "units": round(s["pay"], 6), "taxableUnits": round(s["taxable"], 6),
                        "byKind": {k: {kk: round(vv, 2) for kk, vv in v.items()}
                                   for k, v in s["byKind"].items()},
                        "records": s["records"], "monthHours": round(month_h, 2),
                        "yearHours": round(year_h, 2), "breaches": caps["breaches"]})
        return self._json({"ok": True, "period": period, "annualCap": cap_y,
                           "restNote": "Rates are Labour Code Art. 98 minima.", "rows": out})

    def _leave_entitlement_ep(self, u, qs):
        """What annual leave the law requires for each employee this year, beside what is on record.

        `annualTotal` is a number somebody typed and nothing has ever checked it. This does not
        overwrite it — a company may lawfully give MORE than the statutory minimum, and plenty do —
        it computes the minimum and reports the difference where the record falls short. Art. 113(1)
        for the base, Art. 114 for the seniority day, Decree 145/2020 Art. 66 for the proration of a
        first or final year, and its round-half-UP rule.
        """
        if self._level_rank(self._caller_level(u)) < self._level_rank("manager"):
            return self._err("Manager access required.", 403)
        try:
            year = int(str(qs.get("year", [""])[0] or "")[:4])
        except (TypeError, ValueError):
            year = 0
        if not (2000 <= year <= 2100):
            year = int(self._vn_day()[:4])

        rows, short = [], 0
        for e in db.list_employees():
            if str(e.get("status") or "Active").strip().lower() == "inactive" and not e.get("endDate"):
                continue
            r = leave_entitlement.entitlement(
                e.get("startDate"), year,
                conditions=e.get("workConditions") or "normal",
                dob=e.get("dob"), disabled=bool(e.get("disabled")),
                end=e.get("endDate") or None)
            gap = leave_entitlement.shortfall(e.get("annualTotal"), r["days"])
            if gap:
                short += 1
            rows.append({"empId": e.get("id"), "name": e.get("name") or "",
                         "dept": e.get("dept") or "", "startDate": e.get("startDate") or "",
                         "conditions": e.get("workConditions") or "normal",
                         "onRecord": e.get("annualTotal"), "required": r["days"],
                         "base": r["base"], "seniority": r["seniority"], "months": r["months"],
                         "prorated": r["prorated"], "why": r["reason"], "shortfall": gap})
        rows.sort(key=lambda x: (-x["shortfall"], x["name"]))
        return self._json({"ok": True, "year": year, "rows": rows, "short": short})

    def _leave_entitlement_apply_ep(self, u, body):
        """Raise every entitlement that is below the statutory minimum to the minimum.

        Only ever UPWARDS. Somebody on 15 days keeps 15 — that is a term of their employment, not an
        error to be normalised away — and a company that has agreed better terms must not have them
        quietly reduced by a compliance tool. Each change goes through the same path as an HR edit, so
        it lands in the audit chain and in the dated history.
        """
        if self._level_rank(self._caller_level(u)) < self._level_rank("editor"):
            return self._err("Editor access required to change leave entitlements.", 403)
        try:
            year = int(str(body.get("year") or "")[:4])
        except (TypeError, ValueError):
            year = 0
        if not (2000 <= year <= 2100):
            year = int(self._vn_day()[:4])
        only = body.get("empIds") if isinstance(body.get("empIds"), list) else None

        changed = []
        for e in db.list_employees():
            if only is not None and e.get("id") not in only:
                continue
            if str(e.get("status") or "Active").strip().lower() == "inactive":
                continue
            r = leave_entitlement.entitlement(
                e.get("startDate"), year,
                conditions=e.get("workConditions") or "normal",
                dob=e.get("dob"), disabled=bool(e.get("disabled")),
                end=e.get("endDate") or None)
            gap = leave_entitlement.shortfall(e.get("annualTotal"), r["days"])
            if not gap:
                continue
            was = e.get("annualTotal")
            db.update_employee(e.get("id"), {"annualTotal": r["days"]})
            db.put_collection_item("audit", {
                "actor": u.get("name"), "actorId": u.get("id"),
                "action": "Leave entitlement raised to the statutory minimum",
                "target": "employee/" + str(e.get("id")),
                "detail": "%s · %s → %s days for %d (%s)" % (e.get("name") or "", was, r["days"],
                                                             year, r["reason"]),
                "ts": self._utc_now()})
            changed.append({"empId": e.get("id"), "name": e.get("name") or "",
                            "from": was, "to": r["days"]})
        return self._json({"ok": True, "year": year, "changed": changed, "count": len(changed)})

    def _contracts_review_ep(self, u, qs):
        """Every employee's contract position, and what Art. 20 says about it.

        The consequences in that article happen by operation of law rather than by anybody's
        decision — a fixed term that expires unnoticed for 30 days has ALREADY become an
        indefinite-term contract, and a third fixed term is unlawful whether or not anybody meant
        it — so they have to be computed, not remembered. This is what the register exists to say
        out loud before a labour inspector does.
        """
        if self._level_rank(self._caller_level(u)) < self._level_rank("management"):
            return self._err("Approver (management) level or above is required — a labour contract "
                             "states the agreed wage.", 403)
        as_of = str(qs.get("asOf", [""])[0] or "")[:10]
        if not self._RE_DATE.match(as_of or ""):
            as_of = self._vn_day()

        by_emp = {}
        for c in db.list_collection("contracts"):
            if c.get("empId"):
                by_emp.setdefault(c["empId"], []).append(c)

        rows, flagged = [], 0
        for e in db.list_employees():
            if str(e.get("status") or "Active").strip().lower() == "inactive":
                continue
            r = contracts.review(by_emp.get(e.get("id")) or [], as_of,
                                 exempt=e.get("contractExempt") or None)
            cur = r["contract"] or {}
            if r["issues"]:
                flagged += 1
            rows.append({
                "empId": e.get("id"), "name": e.get("name") or "", "dept": e.get("dept") or "",
                "title": e.get("title") or "", "startDate": e.get("startDate") or "",
                "contractId": cur.get("id"), "contractNo": cur.get("no") or "",
                "type": cur.get("type") or "", "from": cur.get("startDate") or "",
                "to": cur.get("endDate") or "", "status": r["status"],
                "daysLeft": r["daysLeft"], "definiteCount": r["definiteCount"],
                "mustBeIndefinite": r["mustBeIndefinite"],
                "hasFile": bool(cur.get("file") or cur.get("fileUrl")),
                "issues": r["issues"]})
        _rank = {"none": 0, "lapsed": 1, "grace": 2, "unknown": 3, "expiring": 4,
                 "active": 5, "indefinite": 6}
        rows.sort(key=lambda x: (_rank.get(x["status"], 9), x["daysLeft"] if x["daysLeft"] is not None else 9999))
        return self._json({"ok": True, "asOf": as_of, "rows": rows, "flagged": flagged,
                           "maxTermMonths": contracts.MAX_DEFINITE_MONTHS,
                           "graceDays": contracts.GRACE_DAYS})

    def _certificates_review_ep(self, u, qs):
        """Who is covered, whose certificate is lapsing, and who never had one.

        The last of those is the answer a plain register cannot give, and the one that matters on a
        site or in a client audit. Health-check cadence follows Law on OSH 2015 Art. 21(1) — once a
        year, twice for hazardous work, minors, elderly and disabled workers — and safety training
        follows Decree 44/2016 Art. 24 where the company has classified somebody into a group.
        """
        if self._level_rank(self._caller_level(u)) < self._level_rank("manager"):
            return self._err("Manager access required.", 403)
        as_of = str(qs.get("asOf", [""])[0] or "")[:10]
        if not self._RE_DATE.match(as_of or ""):
            as_of = self._vn_day()

        by_emp = {}
        for c in db.list_collection("certificates"):
            if c.get("empId"):
                by_emp.setdefault(c["empId"], []).append(c)

        # A manager sees their own crew; management sees everybody. A certificate is not pay, but it
        # is still somebody's medical cadence, so it is not company-wide reading for everyone.
        emps = db.list_employees()
        if self._level_rank(self._caller_level(u)) < self._level_rank("management"):
            my_email = (u.get("email") or "").strip().lower()
            emps = [e for e in emps if e.get("id") == u.get("id")
                    or (my_email and (e.get("managerEmail") or "").strip().lower() == my_email)]

        rows, flagged = [], 0
        for e in emps:
            if str(e.get("status") or "Active").strip().lower() == "inactive":
                continue
            r = certificates.review(
                by_emp.get(e.get("id")) or [], as_of,
                conditions=e.get("workConditions") or "normal",
                minor=leave_entitlement.is_minor(e.get("dob"), as_of),
                disabled=bool(e.get("disabled")),
                elderly=self._is_elderly(e.get("dob"), as_of),
                osh_group=str(e.get("oshGroup") or "").strip() or None)
            if r["issues"]:
                flagged += 1
            rows.append({"empId": e.get("id"), "name": e.get("name") or "",
                         "dept": e.get("dept") or "", "title": e.get("title") or "",
                         "conditions": e.get("workConditions") or "normal",
                         "oshGroup": e.get("oshGroup") or "",
                         "items": r["items"], "issues": r["issues"]})
        _sev = lambda x: 0 if any(i["severity"] == "high" for i in x["issues"]) \
            else (1 if x["issues"] else 2)
        rows.sort(key=lambda x: (_sev(x), x["name"]))
        return self._json({"ok": True, "asOf": as_of, "rows": rows, "flagged": flagged})

    @staticmethod
    def _is_elderly(dob, as_of):
        """Art. 148 defines an elderly employee by the retirement age, which Art. 169 is raising a
        few months every year. Rather than track a moving figure, this triggers at 60 — which can
        only ever ask for MORE health checks than the law requires, never fewer."""
        d, a = leave_entitlement._d(dob), leave_entitlement._d(as_of)
        if not d or not a:
            return False
        return leave_entitlement.completed_years(d, a) >= 60

    def _exit_settlement(self, u, exit_id, create=False, body=None):
        """What is owed on the way out — computed, itemised, and optionally raised as a payable.

        The exit record has always carried a settlement figure. Nobody computed it: severance was a
        number somebody typed, beside a comment claiming a calculation the code never did. And the
        figure went nowhere — paying it was a separate act of memory, outside the approval and
        disbursement path every other payment in the company goes through.

        This computes it from the law (Art. 113(4) untaken leave, Art. 46 severance or Art. 47
        job-loss allowance, Art. 48(1) deadline) and, on POST, raises it as a payment request so it
        is approved and released like anything else. Once. A second POST returns the first payable
        rather than minting a duplicate — this is somebody's final pay, and paying it twice is not a
        recoverable clerical error.
        """
        if self._level_rank(self._caller_level(u)) < self._level_rank("management"):
            return self._err("Approver (management) level or above is required — a final settlement "
                             "states somebody's pay.", 403)
        rec = db.get_collection_item("exits", str(exit_id or "")) or {}
        if not rec:
            return self._err("Exit record not found.", 404)
        emp = db.get_employee(rec.get("empId")) if rec.get("empId") else None
        if not emp:
            return self._err("That exit has no employee record to settle against.", 404)

        body = body or {}
        last_day = str(rec.get("lastDay") or emp.get("endDate") or "")[:10]
        if not self._RE_DATE.match(last_day):
            return self._err("The exit has no last working day, so nothing can be settled or dated.", 400)

        # The wage the allowances are computed on: Decree 145/2020 Art. 8(2) takes the average of the
        # six months before termination. The dated history is the only honest source for that — a
        # current salary would price a leaver on a raise they had for one month.
        wages = []
        try:
            hist = db.list_emp_events(emp_id=emp.get("id"), field="salary")
            for m in range(6):
                d = (datetime.strptime(last_day, "%Y-%m-%d") - timedelta(days=30 * m)).strftime("%Y-%m-%d")
                v = db.emp_value_asof(emp.get("id"), "salary", d)
                if v not in (None, ""):
                    wages.append(float(v))
        except Exception:
            hist = []
        if not wages:
            try:
                wages = [float(emp.get("salary") or 0)]
            except (TypeError, ValueError):
                wages = [0.0]
        wage = settlement.average_wage(list(reversed(wages)))

        # Art. 113(4): leave earned and not taken. The entitlement engine gives the earned figure for
        # the leaving year — prorated, which a leaver's is — rather than the annual headline.
        ent = leave_entitlement.entitlement(
            emp.get("startDate"), int(last_day[:4]),
            conditions=emp.get("workConditions") or "normal", dob=emp.get("dob"),
            disabled=bool(emp.get("disabled")), end=last_day)
        try:
            used = float(emp.get("annualUsed") or 0)
        except (TypeError, ValueError):
            used = 0.0
        untaken = max(0.0, float(ent["days"]) - used)

        _hol = _ot_holiday_set()
        _rest = _rest_weekdays_for(emp)
        res = settlement.settle(
            emp.get("startDate"), last_day, wage,
            leave_days_untaken=untaken,
            reason=rec.get("type") or rec.get("reason") or "",
            outstanding_salary=float(body.get("outstandingSalary") or rec.get("outstandingSalary") or 0),
            deductions=float(body.get("deductions") or rec.get("deductions") or 0),
            holidays=_hol, rest_weekdays=_rest)
        res["employee"] = {"id": emp.get("id"), "name": emp.get("name") or "",
                           "startDate": emp.get("startDate") or "", "lastDay": last_day}
        res["wage"] = wage
        res["leaveEarned"] = ent["days"]
        res["leaveUsed"] = used
        res["leaveUntaken"] = untaken
        res["paymentId"] = rec.get("settlementPaymentId") or ""

        if not create:
            return self._json(dict({"ok": True}, **res))

        # Already raised: hand back the one that exists. Never a second.
        if rec.get("settlementPaymentId"):
            return self._json(dict({"ok": True, "alreadyRaised": True}, **res))
        if res["total"] <= 0:
            return self._err("There is nothing owed on this settlement, so there is nothing to pay.", 400)

        _rows = "\n".join("%s: %s" % (l["label"], _money_vnd(l["amount"])) for l in res["lines"])
        pay = db.put_collection_item("payments", {
            "reqNo": "FS-" + str(exit_id)[:12],
            "name": u.get("name"), "empId": u.get("id"),
            "department": emp.get("dept") or "", "payee": emp.get("name") or "",
            "category": "Final settlement", "method": "Bank transfer",
            "purpose": "Final settlement — %s, last day %s" % (emp.get("name") or "", last_day),
            "amount": round(res["total"]),
            "dueDate": res["deadline"],
            "note": _rows + "\n\nDue by %s — %s" % (res["deadline"], res["deadlineBasis"]),
            "status": "Pending Approval",
            # The itemisation IS the supporting document here: there is no third-party invoice for
            # somebody's own final pay, and the article behind each line is on the record.
            "attachment": "", "spUrl": "", "settlementFor": exit_id,
            "settlementLines": res["lines"],
        })
        db.put_collection_item("exits", dict(rec, settlementPaymentId=pay.get("id"),
                                             settlementTotal=round(res["total"]),
                                             settlementDeadline=res["deadline"]))
        db.put_collection_item("audit", {
            "actor": u.get("name"), "actorId": u.get("id"),
            "action": "Final settlement raised as a payment",
            "target": "exits/" + str(exit_id),
            "detail": "%s · %s · due %s (%s)" % (emp.get("name") or "", _money_vnd(res["total"]),
                                                 res["deadline"], res["deadlineBasis"]),
            "ts": self._utc_now()})
        res["paymentId"] = pay.get("id")
        return self._json(dict({"ok": True, "payment": pay}, **res))

    def _hr_doc_file_ep(self, u, doc_id):
        """The bytes of one published document, for somebody it is actually addressed to.

        The list endpoint deliberately ships metadata only — six real policy PDFs inline is tens of
        megabytes on every Onboarding render. This is where the file comes from, and it re-checks the
        audience rather than trusting that the caller only asked for what the list showed them."""
        doc = db.get_collection_item("hrdocs", str(doc_id or "")) or {}
        if not doc:
            return self._err("That document is no longer published.", 404)
        if self._level_rank(self._caller_level(u)) < self._level_rank("manager"):
            me = next((e for e in db.list_employees() if e.get("id") == u.get("id")), None) or {
                "id": u.get("id") or "", "name": u.get("name") or "",
                "dept": u.get("dept") or u.get("department") or "", "status": "Active"}
            if doc.get("archived") or not _hrdoc_targets(doc, [me]):
                return self._err("That document is not addressed to you.", 403)
        if not _hrdoc_has_file(doc):
            return self._err("That document has no file attached yet.", 404)
        return self._json({"ok": True, "id": doc.get("id"), "file": doc.get("file") or "",
                           "fileUrl": doc.get("fileUrl") or "",
                           "fileName": doc.get("fileName") or "document"})

    _PAY_MONTHS = ("January", "February", "March", "April", "May", "June", "July",
                   "August", "September", "October", "November", "December")

    def _emp_history_backfill_ep(self, u):
        """Seed the history from the pay runs already finalised.

        Every finalised run froze a line per employee carrying dept, title, grade and the contractual
        salary as they stood that month — so the history for those months already exists, it was just
        never queryable. This reads them oldest-first and writes a dated event wherever a value
        differs from the previous month, marked source='backfill' so an inferred row is never mistaken
        for a recorded one. Idempotent: re-running adds nothing, because the events it would write
        already exist."""
        if self._level_rank(self._caller_level(u)) < self._level_rank("admin"):
            return self._err("Admin access required.", 403)
        return self._json(dict({"ok": True}, **self._emp_history_backfill(u)))

    def _emp_history_repair_ep(self, u):
        """Rebuild every inferred history row, because the first version of the inference was wrong.

        Two defects wrote permanent rows: the salary field was read from the pay-run line's `gross`,
        which is the payslip TOTAL (P1+P2+P3+welfare, plus any one-off bonus) rather than the
        contractual salary; and unsigned runs were ingested, so a draft a Director had refused became
        record. Both are fixed, but the rows they already wrote are still there, and the table has no
        delete — which is right for something somebody recorded, and wrong for a reconstruction that
        was never true.

        So: every source='backfill' row is snapshotted into the tamper-evident audit chain, removed,
        and rebuilt under the corrected rules. Rows somebody actually recorded (source='edit') are
        never touched. Safe to run when the old backfill was never run at all — it removes nothing
        and rebuilds from the same runs.
        """
        if self._level_rank(self._caller_level(u)) < self._level_rank("admin"):
            return self._err("Admin access required.", 403)
        removed = db.drop_inferred_emp_events()
        if removed:
            # The removal is itself a record. Keep enough of each row to reconstruct what the bad
            # inference had claimed, so "why did his March salary change in the portal" is answerable.
            _detail = "; ".join("%s %s@%s %s\u2192%s" % (r.get("emp_id"), r.get("field"),
                                                     r.get("effective"), r.get("old_value"),
                                                     r.get("new_value")) for r in removed)
            db.put_collection_item("audit", {
                "actor": u.get("name"), "actorId": u.get("id"),
                "action": "Employment history rebuilt",
                "target": "emp_events",
                "detail": ("Removed %d INFERRED row(s) written by the earlier backfill, which read "
                           "the payslip total as salary and ingested unsigned pay runs, and rebuilt "
                           "them under the corrected rules. Removed: " % len(removed))
                          + _detail[:3000],
                "ts": self._utc_now()})
        out = self._emp_history_backfill(u)
        return self._json(dict({"ok": True, "removed": len(removed),
                                "employeesAffected": len({r.get("emp_id") for r in removed})}, **out))

    def _emp_history_backfill(self, u):
        """The backfill itself, so the repair endpoint can rebuild with exactly the same rules."""
        def _period_key(p):
            parts = str(p or "").split()
            if len(parts) == 2 and parts[0] in self._PAY_MONTHS:
                return "%s-%02d" % (parts[1], self._PAY_MONTHS.index(parts[0]) + 1)
            return ""

        # FINALISED runs only. Every run is created as "Pending Approval" (see _coll_add), so without
        # this filter a draft the Director refused to sign was seeded into the permanent record
        # alongside the corrected one — two same-day rows, one of them a figure nobody approved.
        runs = [r for r in db.list_collection("payruns")
                if (r.get("lines") or []) and _period_key(r.get("period"))
                and "final" in str(r.get("status") or "").lower()]
        runs.sort(key=lambda r: _period_key(r.get("period")))
        existing = {(e.get("emp_id"), e.get("field"), e.get("effective"))
                    for e in db.list_emp_events()}
        seen, made, skipped = {}, 0, 0
        for r in runs:
            ym = _period_key(r.get("period"))
            eff = ym + "-01"                       # a pay run describes the whole month
            for ln in (r.get("lines") or []):
                eid = ln.get("empId")
                if not eid:
                    continue
                # The CONTRACTUAL salary, never the payslip total. `gross` on a line is
                # P1+P2+P3+welfare — it carries a KPI factor, ₫1,530,000 of fixed welfare and any
                # one-off bonus, so reading it as salary understated every ordinary month and turned
                # a Tết bonus into a raise followed by an equal pay cut. Runs finalised before
                # `contractGross` was recorded simply contribute no salary row: a gap in the history
                # is honest, a wrong figure in it is not.
                _salary = ln.get("contractGross")
                if _salary in (None, "") and isinstance(ln.get("calc"), dict):
                    _salary = ln["calc"].get("contractGross")
                if _salary in (None, ""):
                    skipped += 1
                for field, val in (("salary", _salary), ("grade", ln.get("grade")),
                                   ("title", ln.get("title")), ("dept", ln.get("dept"))):
                    if val in (None, ""):
                        continue
                    prev = seen.get((eid, field))
                    if str(prev) == str(val):
                        continue                   # unchanged since the previous run
                    if (eid, field, eff) not in existing:
                        db.add_emp_event(eid, field, prev, val, effective=eff,
                                         reason="Backfilled from the %s pay run" % r.get("period"),
                                         actor=u.get("name") or "", actor_id=u.get("id") or "",
                                         source="backfill")
                        # Record it NOW, not just in `seen`: two runs can share a month, and without
                        # this the second one writes a second row on the same effective date.
                        existing.add((eid, field, eff))
                        made += 1
                    seen[(eid, field)] = val
        return {"runs": len(runs), "events": made,
                "salaryUnavailable": skipped, "total": db.emp_events_count()}

    def _hr_remind_ep(self, u):
        """Send the outstanding-signature reminders now, instead of waiting for tomorrow."""
        if self._level_rank(self._caller_level(u)) < self._level_rank("manager"):
            return self._err("Manager access required.", 403)
        try:
            n = _hrdoc_reminders()
        except Exception as e:
            return self._err(_graph_err_text(e)[:200] or "Could not send reminders.", 500)
        return self._json({"ok": True, "reminded": n})

    def _hr_jd_ep(self, u, body):
        """Attach a Job Description file to a requisition and file it in HR SharePoint.

        The SharePoint copy is the one HR and a candidate get sent, so unlike the Finance archiver
        this runs while somebody is watching and reports what happened instead of failing quietly.
        If SharePoint is not configured the JD is still kept in the portal — losing the document
        because a folder link is blank would be the worse outcome."""
        if self._level_rank(self._caller_level(u)) < self._level_rank("manager"):
            return self._err("Only a manager can attach a Job Description.", 403)
        jid = str((body or {}).get("jobId") or "")
        job = db.get_collection_item("jobs", jid) if jid else None
        if not job:
            return self._err("Requisition not found.", 404)
        data = str((body or {}).get("data") or "")
        if not data.startswith("data:"):
            return self._err("No file received.", 400)
        head, _, b64 = data.partition(",")
        try:
            raw = base64.b64decode(b64 + "=" * (-len(b64) % 4))
        except Exception:
            return self._err("That file could not be read.", 400)
        if not raw:
            return self._err("That file is empty.", 400)
        if len(raw) > _INVTRACK_FILE_MAX:
            return self._err("That file is too large (limit %d MB)." % (_INVTRACK_FILE_MAX // (1024 * 1024)), 400)
        ctype = head[5:].split(";")[0] or "application/pdf"
        name = str((body or {}).get("name") or "").strip() or (
            (job.get("title") or "Job Description") + ".pdf")

        jd = {"name": name, "size": len(raw), "type": ctype,
              "ts": self._utc_now_ms(), "by": u.get("name") or ""}
        # Year folder so a library does not become one flat list of every JD ever written.
        sub = ["JD", time.strftime("%Y")]
        try:
            web = _hrsp_put(sub, name, raw, ctype)
            if web:
                jd["webUrl"] = web
        except Exception as e:
            jd["fileError"] = _graph_err_text(e)[:200]
        if not jd.get("webUrl"):
            jd["data"] = data                       # no SharePoint copy -> keep it in the portal
        job["jd"] = jd
        saved = db.put_collection_item("jobs", job)
        try:
            db.put_collection_item("audit", {
                "actor": u.get("name") or "", "actorId": u.get("id") or "", "action": "hr.jd",
                "detail": "Job Description '%s' attached to '%s'%s" % (
                    name, job.get("title") or jid,
                    " — filed to SharePoint" if jd.get("webUrl") else " — kept in the portal"),
                "ts": self._utc_now()})
        except Exception:
            pass
        return self._json({"ok": True, "item": saved, "jd": jd,
                           "filed": bool(jd.get("webUrl")), "error": jd.get("fileError", "")})

    def _finsp_test_ep(self, u):
        """Prove the Finance folder is reachable, without uploading anything. Mirrors Invoice
           Tracking's Test connection — including forcing a FRESH token, since this is exactly the
           button an admin presses right after granting consent."""
        if self._level_rank(self._caller_level(u)) < self._level_rank("editor"):
            return self._err("Finance (Editor) access is required.", 403)
        folder = (db.get_setting("portal_financeSpUrl", "") or "").strip()
        if not folder:
            return self._json({"ok": False, "error": "No Finance SharePoint folder URL is set."})
        try:
            _finsp_reset()
            tok = _graph_app_token(force=True)
            tgt = _finsp_resolve(tok)
            if not tgt:
                raise ValueError("could not resolve that folder — check the link and Sites consent")
            return self._json({"ok": True, "folder": folder, "rel": tgt["rel"],
                               "health": _FINSP_HEALTH})
        except Exception as e:
            return self._json({"ok": False, "error": _graph_err_text(e)[:300], "health": _FINSP_HEALTH})

    def _finsp_backfill_ep(self, u):
        """File EXISTING payment/claim/travel PDFs that were never archived.

        The browser-side uploader only ever ran when the submitter happened to have a live Microsoft
        session, so most historical requests were never filed at all. This walks the records and
        uploads the ones still missing a SharePoint link, newest first — that is the direction anyone
        checking the folder looks. Bounded per call so one request cannot run for minutes; the
        response reports what is left so it can simply be pressed again."""
        if self._level_rank(self._caller_level(u)) < self._level_rank("editor"):
            return self._err("Finance (Editor) access is required.", 403)
        if not (db.get_setting("portal_financeSpUrl", "") or "").strip():
            return self._err("No Finance SharePoint folder URL is set.", 400)
        limit = 40
        done, failed, todo = 0, 0, 0
        for coll, kind in (("payments", "payment"), ("claims", "claim"), ("travel", "travel")):
            rows = [r for r in db.list_collection(coll)
                    if isinstance(r.get("attachment"), str) and r["attachment"].startswith("data:")
                    and not r.get("spUrl")]
            rows.sort(key=lambda r: str(r.get("ts") or ""), reverse=True)
            for r in rows:
                if done + failed >= limit:
                    todo += 1
                    continue
                url = _finsp_archive(r, kind)
                if url:
                    r["spUrl"] = url                      # remember, so a re-run skips it
                    try:
                        db.put_collection_item(coll, r)
                    except Exception:
                        pass
                    done += 1
                else:
                    failed += 1
        return self._json({"ok": failed == 0, "uploaded": done, "failed": failed, "remaining": todo,
                           "health": _FINSP_HEALTH})

    def _coll_update(self, u, name, iid, body):
        if name not in self.COLLECTIONS or not iid:
            return self._err("Unknown item.", 404)
        if not isinstance(body, dict):     # a non-object JSON body would 500 in dict(body) below
            return self._err("Invalid record.", 400)
        # Optimistic concurrency (lost-update guard): if the caller sent an `If-Match: <rev>` precondition,
        # it must equal the record's CURRENT server `_rev`. If it doesn't, the record was changed by
        # someone else since the caller loaded it, and this blind full-document PATCH would silently
        # clobber that edit — so 409 and let the client re-fetch and re-apply. Opt-in by header, so a
        # caller that doesn't send it is unaffected (the write still bumps `_rev` in put_collection_item).
        _ifm = self.headers.get("If-Match")
        _ifm_rev = None            # carried to the write below, so the precondition is ATOMIC
        if _ifm is not None:
            _cur = db.get_collection_item(name, iid)
            if _cur is not None:
                try:
                    _cur_rev = int(_cur.get("_rev") or 0)
                except (TypeError, ValueError):
                    _cur_rev = 0
                try:
                    _want_rev = int(str(_ifm).strip().strip('"'))
                except (TypeError, ValueError):
                    _want_rev = None
                if _want_rev is not None and _want_rev != _cur_rev:
                    return self._json({"error": "This record was just changed by someone else. "
                                                 "Reload the latest version and re-apply your change.",
                                       "conflict": True, "currentRev": _cur_rev}, 409)
                # Checking here and writing hundreds of lines later is two transactions with a gap
                # between them — a concurrent write landing in that gap passed the check and was then
                # overwritten anyway, which is the exact failure If-Match exists to prevent. The rev
                # is re-verified inside the write's own transaction.
                _ifm_rev = _want_rev
        # The audit trail is APPEND-ONLY (21 CFR Part 11). _coll_delete already blocks deletion; block
        # updates here too so a stored audit event can never be edited/rewritten via the generic store.
        if name == "audit":
            return self._err("The audit trail is append-only and cannot be modified.", 403)
        # Payroll dual-control: a run's status changes ONLY through the Director e-signature (/api/esign),
        # and a FINALISED run is immutable. A plain PATCH may only amend a still-pending run's figures —
        # it can neither finalise a run nor edit a finalised one.
        if name == "payruns":
            _pr = db.get_collection_item("payruns", iid)
            if _pr and str(_pr.get("status") or "").strip().lower() in ("finalised", "finalized"):
                return self._err("A finalised payroll run is immutable.", 403)
            if _pr:
                # A PATCH may amend a pending run's figures but can never CHANGE its status (the update
                # is a blind full-document overwrite, so pin status to its stored value rather than
                # dropping it) — finalisation happens only through the Director e-signature.
                body["status"] = _pr.get("status") or "Pending Approval"
                # SoD: the PREPARER identity is immutable evidence. Pin it from the stored record so a
                # preparer can't blank or spoof preparedById via this blind overwrite and then finalise
                # their own run (with owner_id falsy/mismatched, the preparer!=signer check would be
                # skipped) — that would defeat the whole dual-control guarantee.
                for _k in ("preparedById", "preparedBy"):
                    if _pr.get(_k) is not None:
                        body[_k] = _pr.get(_k)
                    else:
                        body.pop(_k, None)
        # Manual payroll adjustment: a finalised (closed) month is locked against edits (check the STORED
        # period, so the period can't be moved to dodge the lock). The audited-write happens below.
        if name == "payadjust":
            _cur = db.get_collection_item("payadjust", iid)
            if self._payperiod_finalised((_cur or {}).get("period") or body.get("period")):
                return self._err("That pay period is finalised and locked — its payroll adjustments can no longer be edited.", 403)
        # Per-user app access — mirror the READ gate in _coll_list on the WRITE path too, otherwise a
        # user whose CRM/PM/HR app was disabled by an admin could still create/edit those records by
        # calling the API directly (the block was read-only before).
        _app = "crm" if name.startswith("crm_") else ("pm" if name.startswith("pm_") else ("hr" if name in self.HR_APP_COLLS else None))
        if _app and _app in self._apps_denied(u):
            return self._err("Access restricted — the %s app is not enabled for your account." % _app.upper(), 403)
        # Asset receipt acknowledgment (any role, incl. staff): the HOLDER of a device may e-sign to
        # acknowledge receipt from their own My Devices. Owner-scoped + APPEND-ONLY — exactly one ack
        # signature is added; no other field is touched, so it can't rewrite the asset register. Handled
        # up here so it's uniform for staff (who otherwise can't PATCH devices) and managers alike.
        if name == "devices" and isinstance(body, dict) and "ackSignature" in body:
            # Validate BEFORE taking the lock and before reading the row. put_collection_item rewrites
            # the whole document, so this is a read-modify-write on a row several people share — a
            # device is a stock LINE, and ten holders of the same line all acknowledge on their phones
            # the same morning. Whatever sits between the read and the write is the window in which
            # one of their signatures is lost, so nothing slow (a 2 MB data URI, an identity lookup)
            # belongs inside it. Same reasoning as _ESIGN_LOCK on the e-signature path.
            _sig = body.get("ackSignature")
            _img = _sig.get("image") if isinstance(_sig, dict) else None
            if not (isinstance(_img, str) and _img.startswith("data:image") and len(_img) <= 2_000_000):
                return self._err("A drawn signature is required to acknowledge receipt.", 400)
            _uid, _uname, _today = u.get("id"), u.get("name"), time.strftime("%Y-%m-%d")
            _is_admin = self._caller_level(u) == "admin"
            _ack = {"name": _uname, "meaning": "Asset handover — acknowledged receipt", "ts": self._utc_now(),
                    "method": "signature", "image": _img, "by": _uname, "ack": True}
            # Read, append, COMPARE-AND-SWAP, retry. The lock alone was not enough: it only serialises
            # other ack requests, and the write that actually destroys a signature is a MANAGER's
            # ordinary device PATCH, which takes no lock at all. Assigning the item to a new holder
            # between this read and this write used to overwrite the ack; acking between the manager's
            # read and write used to overwrite the assignment, its quantity and its handover signature.
            # put_collection_item_if_rev writes only while the stored rev is still the one we read, so
            # the loser re-reads and re-applies instead of clobbering. Measured on this code: twelve
            # concurrent signatures on one stock line, one survived; with the swap, all twelve do.
            for _try in range(5):
                with self._ESIGN_LOCK:          # keeps ack-vs-ack from even needing a retry
                    existing = db.get_collection_item("devices", iid)
                    if not existing:
                        return self._err("You can only sign for a device assigned to you.", 403)
                    _rev0 = existing.get("_rev")
                    # Re-checked on every attempt, against the row as it is NOW: a retry must not
                    # sign for an assignment that was released while we were losing the race.
                    _assigns = existing.get("assignments")
                    if isinstance(_assigns, list) and _assigns:
                        # Per-assignment model: sign ONLY the assignment(s) belonging to the caller.
                        _mine = [a for a in _assigns if isinstance(a, dict) and ((a.get("empId") and a.get("empId") == _uid) or (not a.get("empId") and a.get("name") == _uname))]
                        if not _mine and not _is_admin:
                            return self._err("You can only sign for a device assigned to you.", 403)
                        for a in _mine:
                            a.setdefault("signatures", []).append(dict(_ack))
                            a["ackOn"] = _today
                            a["ackBy"] = _uname
                        existing["assignments"] = _assigns
                    else:
                        # Legacy single-assignee record.
                        _own = (existing.get("empId") == _uid) if existing.get("empId") else (existing.get("assignedTo") == _uname)
                        if not _own and not _is_admin:
                            return self._err("You can only sign for a device assigned to you.", 403)
                        _sigs = list(existing.get("signatures") or [])
                        _sigs.append(_ack)
                        existing["signatures"] = _sigs
                        existing["ackOn"] = _today
                        existing["ackBy"] = _uname
                    existing["id"] = iid
                    _saved = db.put_collection_item_if_rev("devices", existing, _rev0)
                if _saved is not None:
                    existing = _saved
                    break
            else:
                # Five losses in a row is not contention, it is something hammering this row. Say so
                # rather than writing a signature over whatever is there now.
                return self._json({"error": "That device was being changed at the same moment. "
                                            "Please try signing again.",
                                   "conflict": True}, 409)
            # Only after the signature is safely stored — an audit row asserting a signature the record
            # does not hold is worse than no audit row.
            db.put_collection_item("audit", {"actor": _uname, "actorId": _uid,
                "action": "E-signature — asset receipt acknowledged", "target": "devices/" + str(iid),
                "detail": existing.get("name") or "", "ts": self._utc_now()})
            return self._json({"ok": True, "item": {k: v for k, v in existing.items() if k != "token"}})
        if name.startswith("pm_") and name not in self.STAFF_WRITE and u.get("role") != "manager":
            return self._err("Manager access required.", 403)
        if name.startswith("crm_") or name.startswith("pm_") or name in ("claims", "travel", "payments", "leave", "audit", "padr", "acks", "enrollments", "onboarding", "jobs", "candidates", "reviews", "talent", "competency", "pip", "exits", "benefits", "devices", "handovers", "goals"):
            body = self._crm_sanitize(body)
        if name in self.PAYROLL_ADMIN and self._level_rank(self._caller_level(u)) < self._level_rank("editor"):
            return self._err("Payroll changes require Editor level or above.", 403)
        if name == "invtrack" and self._level_rank(self._caller_level(u)) < self._level_rank(self.INVTRACK_MIN):
            return self._err("Invoice Tracking requires Editor level or above.", 403)
        # A company policy is chased from every employee and signed against. The only gate used to be
        # `role == "manager"`, which let any line manager publish an audience=All document — and
        # locked out an Admin whose employee role is not literally "manager".
        if name == "hrdocs" and not self._is_hr_admin(u):
            return self._err("Publishing or changing a company document is for HR, Editors and "
                             "Administrators. An administrator can add you under Access & Permissions.", 403)
        if name == "invtrack":
            _dup = self._invtrack_dup_error(body)
            if _dup:
                return self._err(_dup, 400)
        # Travel/claim/payment write scope: a LEADER (manager) may only edit records they own or that
        # belong to a direct report — mirrors the read scope so a manager can't rewrite another team's
        # finance record via a guessed id. Management+ (Finance/Editor/Admin) edit any.
        if name in self.TEAM_SCOPED and u.get("role") == "manager" and not self._is_mgmt(u):
            existing = db.get_collection_item(name, iid)
            if existing is not None:
                myemail = (u.get("email") or "").strip().lower()
                is_own = (existing.get("empId") and existing.get("empId") == u.get("id")) \
                    or (not existing.get("empId") and existing.get("name") == u.get("name")) \
                    or (existing.get("assignedTo") == u.get("name"))
                owner_emp = None
                if existing.get("empId"):
                    owner_emp = db.get_employee(existing.get("empId"))
                else:
                    nm = existing.get("name") or existing.get("assignedTo")
                    owner_emp = next((e for e in db.list_employees() if e.get("name") == nm), None) if nm else None
                is_report = bool(owner_emp) and (owner_emp.get("managerEmail") or "").strip().lower() == myemail and bool(myemail)
                if not (is_own or is_report):
                    return self._err("You can only edit your own or your team's records.", 403)
        # CRM ownership: a staff/manager caller may only edit records they OWN (or, for a
        # manager, in their department), and only management+ may reassign the 'owner' field —
        # the generic overwrite otherwise lets anyone who learns an id rewrite/steal a deal.
        if name.startswith("crm_") and not self._is_mgmt(u):
            existing = db.get_collection_item(name, iid)
            if existing is not None:
                owner = existing.get("owner") or ""
                mine = owner == u.get("name")
                if not mine and u.get("role") == "manager":
                    mydept = u.get("dept") or u.get("department") or ""
                    deptof = {e.get("name"): (e.get("dept") or "") for e in db.list_employees()}
                    mine = bool(mydept) and deptof.get(owner) == mydept
                if not mine:
                    return self._err("You can only edit your own CRM records.", 403)
                if "owner" in (body or {}) and body.get("owner") != owner:
                    return self._err("Only management can reassign a CRM record's owner.", 403)
        # Non-managers reach this only for 'padr'/'enrollments'/crm_* (own records) — and for their own
        # pending claims/travel/payments, which fall through to the owner-scoped money block below
        # (a STAFF requester must be able to amend their own request before it's approved; the owner
        # check at "You can only edit your own pending request" is the real gate there).
        # `hrdocs` is excluded because its own gate ran above: _is_hr_admin already decided, and being
        # NAMED as HR is the grant. Leaving it here would let this blunt role check overrule that and
        # refuse an HR officer who is plain staff — which is most of them.
        if (u.get("role") != "manager" and not name.startswith("crm_") and not name.startswith("pm_")
                and name not in ("claims", "travel", "payments", "hrdocs")):
            if name == "enrollments":
                existing = db.get_collection_item("enrollments", iid)
                if not existing or existing.get("empId") != u.get("id"):
                    return self._err("Not allowed.", 403)
                # staff may only update their own progress / status / rating / feedback / completion date
                for k in ("progress", "status", "rating", "feedback", "completedOn"):
                    if k in (body or {}):
                        existing[k] = body[k]
                existing["id"] = iid
                return self._json({"ok": True, "item": db.put_collection_item("enrollments", existing)})
            if name == "onboarding":
                existing = db.get_collection_item("onboarding", iid)
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
            existing = db.get_collection_item("padr", iid)
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
        # WHOSE enrolment this is can never come from the request body. The self-service branch that
        # re-stamps empId/name only runs for a non-manager, so a MANAGER saving somebody's course
        # progress hit the blind whole-document replace and wiped the enrolment's owner, name and
        # course — 200 OK, success toast, record orphaned. Identity is preserved from the stored row
        # for every caller; progress and status stay editable.
        if name == "enrollments":
            _prev_en = db.get_collection_item("enrollments", iid) or {}
            for _k in ("empId", "name", "course", "courseId", "enrolledOn"):
                if _prev_en.get(_k) is not None:
                    item[_k] = _prev_en.get(_k)
        # PATCH here is a blind full overwrite, so the publication facts have to be carried across by
        # hand or the first edit erases who published the document and when — and the due date, which
        # is derived from that date, silently moves.
        if name == "hrdocs":
            _prev = db.get_collection_item(name, iid) or {}
            if not _prev:
                return self._err("That document is no longer published.", 404)
            for _k in ("ts", "publishedBy", "publishedById"):
                if _prev.get(_k) is not None:
                    item[_k] = _prev.get(_k)
            # List reads no longer carry the file bytes, so the edit form cannot send them back. A
            # blind overwrite would therefore delete the attachment on any edit that did not re-upload
            # it — the exact opposite of what "just fixing a typo" should do. Only an explicit
            # removeFile flag clears it.
            if item.get("removeFile"):
                item["file"] = ""
                item["fileName"] = ""
            elif not item.get("file") and _prev.get("file"):
                item["file"] = _prev.get("file")
                item.setdefault("fileName", _prev.get("fileName") or "")
                if not item.get("fileName"):
                    item["fileName"] = _prev.get("fileName") or ""
            item.pop("removeFile", None)
            item.pop("hasFile", None)      # a derived read-only flag, never stored
            item["updatedBy"] = u.get("name") or ""
            item["updatedAt"] = self._utc_now()
            # An edit that changes the version is a re-issue: it invalidates every signature, because
            # acknowledgements are matched on (docId, empId, docVersion). That is a legitimate thing
            # to do deliberately and a terrible thing to do by accident, so it is recorded as its own
            # kind of event rather than folded into "updated".
            _reissue = str(_prev.get("version") or "") != str(item.get("version") or "")
            self._audit_hrdoc(u, "Re-issued document at a new version" if _reissue else "Updated document", item)
        if name.startswith("pm_"):
            existing = db.get_collection_item(name, iid)
            if existing:
                if existing.get("createdBy") is not None:
                    item["createdBy"] = existing.get("createdBy")
                if existing.get("createdById") is not None:
                    item["createdById"] = existing.get("createdById")
            # A chat message is a statement somebody made. The ONLY thing an edit may change is the
            # words, and only the person who said them may change those.
            #
            # Without this the generic PATCH — a blind full-document overwrite (`item = dict(body)`)
            # whose pm_ guard pins only createdBy/createdById — would happily write authorName,
            # authorId, ts and projectId straight from the browser. That is: put words in a colleague's
            # mouth, backdate a message into the middle of an argument, or move a message into another
            # project and out of the read scoping above. Exactly the hole closed in /api/esign last
            # week, and it would have shipped again here.
            if name == "pm_chat":
                if not existing:
                    return self._err("Message not found.", 404)
                vis = self._pm_visible_projects(u)
                if vis is not None and existing.get("projectId") not in vis:
                    return self._err("You can only edit a message in a project you are on.", 403)
                is_admin = self._caller_level(u) == "admin"
                is_author = (existing.get("authorId") or "") == (u.get("id") or "")
                # A reaction is the one change anybody on the project may make to a message that is
                # not theirs. It is rebuilt from the stored row, so a client can only ever add or
                # remove ITS OWN id, and only against an emoji from the fixed set — it cannot stuff
                # somebody else into a reaction or invent a new one.
                want = item.get("reactions") if isinstance(item.get("reactions"), dict) else None
                item = dict(existing)
                item["id"] = iid
                if want is not None:
                    me = u.get("id") or ""
                    cur = existing.get("reactions") if isinstance(existing.get("reactions"), dict) else {}
                    out = {}
                    for emo in self.CHAT_REACTIONS:
                        others = [x for x in (cur.get(emo) or []) if x and x != me]
                        mine_now = me and me in (want.get(emo) or [])
                        who = others + ([me] if mine_now else [])
                        if who:
                            out[emo] = who
                    item["reactions"] = out
                # Re-filing into another topic: the one other field a PATCH may change. Sits ABOVE
                # the non-author refusal on purpose — the Project Manager must be able to tidy up
                # after somebody who dumped a thread in the wrong place, and widening the guard that
                # stops people rewriting each other's WORDS is not the way to allow it.
                _want_t = body.get("topic")
                if _want_t is not None and str(_want_t) != str(existing.get("topic") or ""):
                    if existing.get("parentId"):
                        return self._err("A reply follows the topic of its thread.", 400)
                    if str(_want_t) and str(_want_t) not in self.PM_CHAT_TOPICS:
                        return self._err("Unknown topic.", 400)
                    _proj = next((x for x in db.list_collection("pm_projects")
                                  if x.get("id") == existing.get("projectId")), {})
                    _is_pm = self._pm_same_person(_proj.get("manager"), u.get("name"))
                    if not (is_author or is_admin or _is_pm):
                        return self._err("Only the author or the project manager can move a message.", 403)
                    item["topic"] = str(_want_t)
                    # deliberately no editedAt: moving a message is not changing what it says
                if not is_author and not is_admin:
                    # A non-author may send reactions and NOTHING else. Every client echoes the whole
                    # object back, and a message now always carries a reactions field — so merely
                    # seeing one is not consent to an edit. If the words differ too, this is somebody
                    # trying to rewrite a colleague's message, and it is refused rather than quietly
                    # succeeding as a no-op.
                    _moved = item.get("topic") != existing.get("topic")   # an allowed PM re-file
                    if (want is None and not _moved) or str(body.get("body") or "") != str(existing.get("body") or ""):
                        return self._err("You can only edit your own message.", 403)
                    return self._json({"ok": True, "item": db.put_collection_item(name, item)})
                body_txt = str(body.get("body") or "")[:8000]
                if body_txt != str(existing.get("body") or ""):
                    item["body"] = body_txt
                    item["editedAt"] = self._utc_now_ms()   # so the UI can show it was changed
            # A variation order and an interim payment certificate are the two documents where money
            # and time actually move on a construction contract, and the classic dispute surface. They
            # were the LEAST protected records in the system: signer name and signature rode through
            # from the browser, and a CR signed for "+500M / +30 days" could afterwards be edited to
            # different figures while the signature kept rendering. Now the signature chain and signer
            # identity are e-sign-only on every write, and a signed record is frozen — the single
            # exception being that a certified certificate may still be recorded as PAID, which is a
            # later fact about the document rather than a change to it.
            # Signer identity on a quality record is stamped by /api/esign, never sent by the browser.
            # The record itself stays editable — a QA register legitimately gains photos and notes
            # after closure — but who verified it, and when, cannot be rewritten.
            if name == "pm_quality" and existing:
                for _k in ("signatures", "verifiedBy", "verifiedOn"):
                    if _k in existing:
                        item[_k] = existing[_k]
                    else:
                        item.pop(_k, None)
            if name in ("pm_changes", "pm_procurement_payments") and existing:
                for _k in ("signatures", "decidedBy", "decidedOn", "certifiedBy", "certDate"):
                    if _k in existing:
                        item[_k] = existing[_k]
                    else:
                        item.pop(_k, None)
                # A record is frozen by a LIVE decision, not by the mere presence of signatures.
                # `signatures` never shrinks — an undo appends a reversal rather than deleting — so
                # testing it would leave a reversed record frozen forever, which defeats the whole
                # point of being able to take a decision back. The decision stamps below are exactly
                # what the undo clears, so they are the honest test.
                _signed = bool(existing.get("decidedBy") or existing.get("certifiedBy"))
                if _signed and self._caller_level(u) != "admin":
                    _old = str(existing.get("status") or "").strip().lower()
                    _new = str(item.get("status") or "").strip().lower()
                    if name == "pm_procurement_payments" and _old == "certified" and _new == "paid":
                        item = dict(existing)
                        item["status"] = "Paid"
                        item["id"] = iid
                    else:
                        return self._err("This record has been signed and can no longer be edited. "
                                         "Raise a superseding one instead.", 403)
            elif name in ("pm_changes", "pm_procurement_payments"):
                item.pop("signatures", None)      # never create an already-signed record via PATCH
        # Preserve server-trusted ownership on staff-owned records (a manager edit/approve
        # must not be able to rewrite who a claim/travel/exit belongs to).
        if name in ("claims", "travel", "payments", "acks"):
            existing = db.get_collection_item(name, iid)
            if existing:
                item["empId"] = existing.get("empId", item.get("empId"))
                if existing.get("name"):
                    item["name"] = existing.get("name")
        # 21 CFR Part 11 / 3-level approval integrity: the generic write path must NEVER set
        # approval status or signatures. Those transition ONLY through /api/esign (_appr_check +
        # fresh re-auth). Preserve the server-held values and drop any client attempt to change
        # them — this closes the "PATCH status=Approved / forge signatures" bypass.
        if name in ("claims", "travel", "payments", "leave"):
            existing = existing if name in ("claims", "travel", "payments", "acks") else db.get_collection_item(name, iid)
            _st = str((existing or {}).get("status") or "").strip().lower()
            # A money record's CONTENT is immutable signed evidence ONCE it is finally DECIDED
            # (approved / paid / rejected). While still pending (submitted / reviewed) the OWNER may
            # amend their own request to fix a mistake — the frontend re-signs the change as an
            # Amendment via /api/esign. Only ADMIN may touch anything beyond that. The owner-scope
            # check here is now the SOLE gate stopping a non-owner from PATCHing a pending money
            # record (the previous blanket "has signatures" guard rejected EVERY edit, because the
            # submission e-signature is always present — which killed the edit feature entirely).
            if existing and name in ("claims", "travel", "payments") and self._caller_level(u) != "admin":
                if _st in ("approved", "paid", "rejected", "payment reversed"):
                    return self._err("This request has been decided and can no longer be edited.", 403)
                _en = str(existing.get("name") or "").strip().lower()
                _owner = (existing.get("empId") and existing.get("empId") == u.get("id")) or \
                         ((not existing.get("empId")) and _en and _en == str(u.get("name") or "").strip().lower())
                if not _owner:
                    return self._err("You can only edit your own pending request.", 403)
            # Validate money on the incoming edit too (add-time validation alone was insufficient).
            if name in ("claims", "travel", "payments", "payruns", "payadjust"):
                _merr = self._validate_money_item(name, item)
                if _merr:
                    return self._err(_merr, 400)
            if existing:
                for _k in ("status", "signatures", "reviewedBy", "reviewedById", "reviewedAt",
                           "approvedBy", "approvedById", "approvedAt", "paidOn", "paidBy",
                           "rejectedBy", "rejectedAt", "token"):
                    if _k in existing:
                        item[_k] = existing[_k]
                    else:
                        item.pop(_k, None)
                # An owner amending a REVIEWED request changes signed content, so it drops back to
                # 'Submitted' for re-review and the review fields clear; the amendment is separately
                # e-signed (append-only), so the Part 11 audit trail stays intact.
                if name in ("claims", "travel", "payments") and self._caller_level(u) != "admin" and _st == "reviewed":
                    item["status"] = "Submitted"
                    for _rk in ("reviewedBy", "reviewedById", "reviewedAt"):
                        item.pop(_rk, None)
                # protect per-line statuses/signatures on multi-item claims too
                if isinstance(existing.get("items"), list) and isinstance(item.get("items"), list):
                    ex_items = existing["items"]
                    _admin_edit = self._caller_level(u) == "admin"
                    def _amt(d):
                        try:
                            return round(float(d.get("amount") or 0), 4)
                        except (TypeError, ValueError):
                            return None
                    for i, it in enumerate(item["items"]):
                        if i < len(ex_items) and isinstance(it, dict) and isinstance(ex_items[i], dict):
                            ex_it = ex_items[i]
                            _line_st = str(ex_it.get("status") or "").strip().lower()
                            # A line already reviewed/approved must NOT keep that decision when its signed
                            # money content (amount) changes — otherwise an owner could inflate an approved
                            # line while retaining its 'Approved' stamp with no re-signature. Reset it to
                            # Submitted so it re-enters review/approval (which is SoD-checked + separately
                            # e-signed, keeping the Part 11 trail). Unchanged lines keep their decision.
                            if (not _admin_edit) and _line_st in ("reviewed", "approved") and _amt(it) != _amt(ex_it):
                                it["status"] = "Submitted"
                                for _k in ("reviewedBy", "reviewedById", "reviewedAt",
                                           "approvedBy", "approvedById", "approvedAt"):
                                    it.pop(_k, None)
                            else:
                                for _k in ("status", "reviewedBy", "reviewedById", "approvedBy"):
                                    if _k in ex_it:
                                        it[_k] = ex_it[_k]
                                    else:
                                        it.pop(_k, None)
            else:
                # no existing record to protect against — refuse to create a signed record via PATCH
                for _k in ("status", "signatures"):
                    item.pop(_k, None)
        if name == "payadjust":
            saved = db.put_collection_item("payadjust", item)
            self._audit_payadjust(u, "Payroll adjustment edited", saved)
            return self._json({"ok": True, "item": saved})
        if _ifm_rev is not None:
            # The caller supplied a precondition, so honour it AT THE WRITE. Losing here means the row
            # changed while this request was being processed — the same answer the check above gives,
            # just no longer possible to slip past.
            _out = db.put_collection_item_if_rev(name, item, _ifm_rev)
            if _out is None:
                return self._json({"error": "This record was just changed by someone else. "
                                            "Reload the latest version and re-apply your change.",
                                   "conflict": True}, 409)
        else:
            _out = db.put_collection_item(name, item)
        return self._json({"ok": True, "item": {k: v for k, v in _out.items() if k != "token"}})

    def _coll_delete(self, u, name, iid):
        if name not in self.COLLECTIONS or not iid:
            return self._err("Unknown item.", 404)
        # The audit trail is append-only (21 CFR Part 11) — never deletable via the generic store.
        if name == "audit":
            return self._err("Audit-trail entries cannot be deleted.", 403)
        # Per-user app access — same gate as read/update, so a disabled CRM/PM/HR app also blocks delete.
        _app = "crm" if name.startswith("crm_") else ("pm" if name.startswith("pm_") else ("hr" if name in self.HR_APP_COLLS else None))
        if _app and _app in self._apps_denied(u):
            return self._err("Access restricted — the %s app is not enabled for your account." % _app.upper(), 403)
        if name in self.PAYROLL_ADMIN and self._level_rank(self._caller_level(u)) < self._level_rank("editor"):
            return self._err("Payroll changes require Editor level or above.", 403)
        if name == "invtrack" and self._level_rank(self._caller_level(u)) < self._level_rank(self.INVTRACK_MIN):
            return self._err("Invoice Tracking requires Editor level or above.", 403)
        if name == "hrdocs" and not self._is_hr_admin(u):
            return self._err("Publishing or changing a company document is for HR, Editors and "
                             "Administrators. An administrator can add you under Access & Permissions.", 403)
        # A signed acknowledgement is the artefact this whole feature exists to produce — the thing an
        # inspector asks for. hrdoc_acks is staff-writable and self-owned, so until now the signer
        # could simply delete their own signature and the compliance matrix would show them as
        # outstanding again, with nothing recording that a signature had ever existed.
        if name == "hrdoc_acks":
            return self._err("A signed acknowledgement is a permanent record and cannot be deleted. "
                             "Re-issue the document at a new version if it has to be signed again.", 403)
        existing = db.get_collection_item(name, iid)
        if not existing:
            return self._err("Not found.", 404)
        # Deleting a published document leaves every signature against it orphaned: the acks survive
        # but nothing can reach them, because both the compliance matrix and the reminder sweep walk
        # documents and look acks up by (docId, empId, version). Withdraw it instead — `archived` is
        # honoured by all three readers.
        if name == "hrdocs":
            _acks = [a for a in db.list_collection("hrdoc_acks")
                     if str(a.get("docId") or "") == str(iid)]
            if _acks:
                return self._err("%d person(s) have already signed this document, so deleting it would "
                                 "orphan their signatures. Archive it instead — it stops being chased "
                                 "and the signatures stay retrievable." % len(_acks), 409)
        is_admin = self._caller_level(u) == "admin"
        # A payroll adjustment in a FINALISED (closed) month is locked — it can't be deleted either.
        if name == "payadjust" and self._payperiod_finalised(existing.get("period")):
            return self._err("That pay period is finalised and locked — its payroll adjustments can no longer be deleted.", 403)
        # A signed variation order and a certified interim payment certificate are contract evidence —
        # exactly what a dispute or an audit asks to see. They used to be deletable outright by their
        # creator behind one confirm dialog, because the guard below only ever covered the three
        # finance collections.
        if name in ("pm_changes", "pm_procurement_payments"):
            if existing.get("signatures") or existing.get("decidedBy") or existing.get("certifiedBy"):
                return self._err("This record has been signed and cannot be deleted. "
                                 "Raise a superseding change request instead.", 403)
        # Approved / paid financial records are immutable evidence — block deletion (admin included).
        if name in ("claims", "travel", "payments"):
            st = str(existing.get("status") or "").strip().lower()
            if st in ("approved", "paid", "reviewed") or existing.get("signatures"):
                return self._err("This request has been signed/approved and cannot be deleted. Cancel or reverse it instead.", 403)
        # Ownership: non-admins may only delete their OWN self-owned / crm / pm records.
        if not is_admin:
            owner_id = existing.get("empId") or existing.get("createdById")
            owner_nm = existing.get("owner") or existing.get("name")
            mine = (owner_id and owner_id == u.get("id")) or (not owner_id and owner_nm and owner_nm == u.get("name"))
            if (name in self.SELF_OWNED or name.startswith("crm_") or name.startswith("pm_")) and not mine:
                if not (u.get("role") == "manager" and self._is_mgmt(u)):
                    return self._err("You can only delete your own records.", 403)
        # A completed exit is the file you produce if a former employee disputes their settlement:
        # the figure, the signed asset return, the SI book handover. It is not deletable.
        if name == "exits" and str(existing.get("status") or "").strip().lower() == "completed":
            return self._err("A completed exit record is the company's evidence of final settlement "
                             "and cannot be deleted.", 403)
        db.delete_collection_item(name, iid)
        # Snapshot the record INTO the trail, not just the fact that it went. An appraisal, a PIP or an
        # exit could be destroyed with one click and the audit row proved only that a deletion had
        # happened — useless in the argument it exists for. The document is already in hand here.
        _snap = ""
        if name in self.HR_EVIDENCE_COLLS:
            try:
                _clean = {k: v for k, v in (existing or {}).items()
                          if k != "token" and not (isinstance(v, str) and v.startswith("data:"))}
                _snap = " · record=" + json.dumps(_clean, ensure_ascii=False, sort_keys=True)[:3000]
            except Exception:
                _snap = " · record=(could not be serialised)"
        db.put_collection_item("audit", {"actor": u.get("name") or "System", "actorId": u.get("id") or "",
            "action": "Deleted " + name, "target": name + "/" + str(iid),
            "detail": "status=" + str(existing.get("status") or "-") + _snap, "ts": self._utc_now()})
        return self._json({"ok": True})


def main():
    db.init_db()
    _load_sessions()
    _seed_default_payers()   # one-time: name the company's authorised payers (editable in the UI after)
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
    # Part 11 e-sign PIN pepper must be set BEFORE any PIN is enrolled — a PIN hashed without the
    # pepper cannot be re-derived once one is added, so those signatures would stop validating.
    if not DEMO_MODE and not os.environ.get("TK_ESIGN_PEPPER"):
        print("  \033[1;33m⚠  TK_ESIGN_PEPPER is NOT set.\033[0m Set it (openssl rand -hex 32) BEFORE")
        print("     any user enrolls an e-signature PIN — adding it later invalidates existing PINs.")
    # Audit hash chain is keyed by TK_AUDIT_PEPPER — without it the chain still forms but is not
    # cryptographically unforgeable (an attacker with DB write access could recompute valid links).
    # Must be stable once set: changing the key invalidates every existing link's verification.
    if not DEMO_MODE and not os.environ.get("TK_AUDIT_PEPPER"):
        print("  \033[1;33m⚠  TK_AUDIT_PEPPER is NOT set.\033[0m Set it (openssl rand -hex 32) to make the")
        print("     audit trail tamper-EVIDENT. Set it once and keep it stable — changing it later")
        print("     invalidates verification of all existing audit links (then reseal, see below).")
    if os.environ.get("TK_AUDIT_RESEAL") == "1":
        print("  \033[1;33m↻  TK_AUDIT_RESEAL=1\033[0m — the audit chain was re-sealed under the current")
        print("     TK_AUDIT_PEPPER on this start. UNSET this flag now so normal restarts don't reseal.")
    # Part 11 signing tokens: without this flag, JWKS signature verification SOFT-FAILS if the crypto
    # lib / JWKS endpoint is unavailable (a structurally-valid but unverified token would be accepted).
    if not DEMO_MODE and os.environ.get("TK_ESIGN_REQUIRE_VERIFIED_TOKEN") != "1":
        print("  \033[1;33m⚠  TK_ESIGN_REQUIRE_VERIFIED_TOKEN is not '1'.\033[0m E-signature token")
        print("     verification will soft-fail on a JWKS/crypto outage. Set it to 1 in production so a")
        print("     signing token is accepted only when its RS256 signature is fully verified.")
    if seeded:
        print("  Database seeded with %d employees." % len(db.list_employees()))
    print("  Open: http://localhost:%d/" % PORT)
    print("=" * 62)
    if _invtrack_app_ready():
        threading.Thread(target=_invtrack_scheduler, daemon=True).start()
        threading.Thread(target=_appr_reminder_scheduler, daemon=True).start()   # overdue-approval nudges
        threading.Thread(target=_digest_scheduler, daemon=True).start()          # weekly manager/leadership digest
        threading.Thread(target=_tk_nudge_scheduler, daemon=True).start()        # check-in/out timekeeping nudges
        threading.Thread(target=_monthly_scheduler, daemon=True).start()         # month-end report pack to leadership
        print("  Invoice tracking: app-only mailbox sync every %d min for %s" % (INVTRACK["interval"], INVTRACK["mailbox"]))
    ThreadingHTTPServer((HOST, PORT), Handler).serve_forever()


if __name__ == "__main__":
    main()
