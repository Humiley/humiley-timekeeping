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
import zipfile
import xml.etree.ElementTree as ET
import unicodedata
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
        # Deactivated (left/terminated) employees lose access IMMEDIATELY — a live session must not
        # survive being set Inactive. Protected super-admins are exempt so a mistaken deactivation
        # can never lock the whole company out.
        if (emp.get("status") or "Active").strip().lower() == "inactive" and (emp.get("email") or "").lower() not in Handler.ADMIN_EMAILS:
            SESSIONS.pop(token, None)
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
_EINV_MAX_BYTES = 4 * 1024 * 1024          # hard cap on any single untrusted attachment we parse


def _invtrack_app_ready():
    return bool(M365["clientId"] and M365["tenantId"] and M365["clientSecret"])


def _now_iso():
    return datetime.utcnow().strftime("%Y-%m-%dT%H:%M:%SZ")   # `datetime` is the class (from datetime import datetime)


def _vn_fold(s):
    """Fold Vietnamese diacritics for classification (đ->d, drop accents) so 'HĐĐT'/'Hóa đơn' all match."""
    return "".join(ch for ch in unicodedata.normalize("NFD", str(s or "").lower()) if unicodedata.category(ch) != "Mn").replace("đ", "d")


def _iso_minus(iso, minutes):
    """Subtract minutes from an ISO instant (for a safe overlap window). Best-effort; returns input on failure."""
    try:
        return (datetime.strptime((iso or "").split(".")[0].replace("Z", ""), "%Y-%m-%dT%H:%M:%S")
                - timedelta(minutes=minutes)).strftime("%Y-%m-%dT%H:%M:%SZ")
    except Exception:
        return iso


def _einv_num(x):
    """Parse a money value tolerant of VN/EN grouping+decimal conventions. TT78 XML uses plain integers."""
    s = re.sub(r"[^0-9,.\-]", "", str(x if x is not None else "")).strip()
    if not s:
        return 0.0
    neg = s.startswith("-")
    s = s.lstrip("-")
    last = max(s.rfind(","), s.rfind("."))
    frac = len(s) - last - 1
    if last != -1 and 1 <= frac <= 2:              # last separator with 1-2 trailing digits = decimal
        s = s[:last].replace(",", "").replace(".", "") + "." + s[last + 1:]
    else:                                          # all separators are thousands-grouping
        s = s.replace(",", "").replace(".", "")
    try:
        v = float(s or 0)
    except ValueError:
        return 0.0
    return -v if neg else v


def _einv_safe_xml(xml_bytes):
    """Reject untrusted XML that could be an entity-expansion (billion-laughs) bomb before parsing."""
    if isinstance(xml_bytes, str):
        xml_bytes = xml_bytes.encode("utf-8", "ignore")
    if not xml_bytes or len(xml_bytes) > _EINV_MAX_BYTES:
        return None
    low = xml_bytes.lower()   # scan the FULL (already <=4MB-capped) content — a padded prolog comment must not hide a DOCTYPE
    if b"<!doctype" in low or b"<!entity" in low:   # TT78 e-invoices never carry a DTD/entities
        return None
    return xml_bytes


def _einv_parse_xml(xml_bytes):
    """Vietnamese TT78 e-invoice XML -> structured dict, or None. Namespace-agnostic + bomb-guarded."""
    xml_bytes = _einv_safe_xml(xml_bytes)
    if xml_bytes is None:
        return None
    try:
        root = ET.fromstring(xml_bytes)
    except Exception:
        return None

    def _local(tag):
        return tag.rsplit("}", 1)[-1]

    def first(name):
        for el in root.iter():
            if _local(el.tag) == name:
                return (el.text or "").strip()
        return ""

    def under(parent, child):
        for p in root.iter():
            if _local(p.tag) == parent:
                for c in p.iter():
                    if _local(c.tag) == child:
                        return (c.text or "").strip()
        return ""

    serial = first("KHHDon")
    inv_no = first("SHDon")
    date_raw = first("NLap")
    seller = under("NBan", "Ten")
    seller_mst = under("NBan", "MST")
    buyer_mst = under("NMua", "MST")
    lookup = ""
    for tt in root.iter():
        if _local(tt.tag) != "TTin":
            continue
        lab = val = ""
        for ch in tt:
            if _local(ch.tag) == "TTruong":
                lab = ch.text or ""
            elif _local(ch.tag) == "DLieu":
                val = ch.text or ""
        if "tra c" in lab.lower():
            lookup = (val or "").strip() or lookup
    if not (serial or inv_no or seller):
        return None
    iso = date_raw[:10] if (len(date_raw) >= 10 and date_raw[4:5] == "-") else ""
    return {"serial": serial, "invNo": inv_no, "dateISO": iso, "dateRaw": date_raw,
            "supplier": seller, "taxCode": seller_mst, "buyerMST": buyer_mst,
            "before": _einv_num(first("TgTCThue")), "vat": _einv_num(first("TgTThue")),
            "after": _einv_num(first("TgTTTBSo")), "lookupCode": lookup,
            "docType": first("THDon"), "method": "xml"}


def _einv_from_zip(zip_bytes):
    """Unpack a ZIP e-invoice + parse the XML inside. Guards against zip decompression bombs."""
    if not zip_bytes or len(zip_bytes) > 8 * 1024 * 1024:
        return None
    try:
        z = zipfile.ZipFile(io.BytesIO(zip_bytes))
    except Exception:
        return None
    checked = 0
    for zi in z.infolist():
        if not zi.filename.lower().endswith(".xml"):
            continue
        if zi.file_size > _EINV_MAX_BYTES:          # skip an over-large (bomb) member
            continue
        checked += 1
        if checked > 20:
            break
        try:
            r = _einv_parse_xml(z.read(zi.filename))
        except Exception:
            r = None
        if r:
            r["method"] = "zip-xml"
            return r
    return None


def _einv_parse_text(text):
    """Best-effort structured fields from OCR/PDF text (Vietnamese invoice labels)."""
    if not text:
        return None
    def grab(rx):
        m = re.search(rx, text, re.IGNORECASE)
        return m.group(1).strip() if m else ""
    def numv(rx):
        return _einv_num(grab(rx))
    inv_no = grab(r"(?:Số HĐ|Số hóa đơn|Invoice No\.?)\s*[:.]?\s*([0-9]{1,10})")
    after = numv(r"(?:Tổng tiền thanh toán|Total payment|Tổng thanh toán)\s*[:.]?\s*([0-9.,]{4,})")
    if not inv_no and not after:
        return None
    return {"invNo": inv_no, "serial": grab(r"(?:Ký hiệu|Serial)\s*[:.]?\s*([0-9A-Z]{5,8})"),
            "taxCode": grab(r"(?:Mã số thuế|MST)\s*[:.]?\s*([0-9]{10}(?:-[0-9]{3})?)"),
            "vat": numv(r"(?:Tiền thuế GTGT|Thuế GTGT)\s*[:.]?\s*([0-9.,]{3,})"),
            "before": numv(r"(?:Cộng tiền hàng|Tiền hàng)\s*[:.]?\s*([0-9.,]{4,})"),
            "after": after, "method": "ocr"}


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


def _graph_app_token():
    if _GRAPH_APP_TOK["tok"] and _GRAPH_APP_TOK["exp"] > time.time() + 60:
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


def _invtrack_body_fields(html):
    """Best-effort pull from a VN e-invoice NOTIFICATION email body (no attachment): the tra-cứu
       lookup URL + code, invoice no / seller MST, and the total when clearly labelled. Identifiers
       (digits) are read from the diacritic-folded text; the code keeps its original case."""
    out = {"url": "", "code": "", "invNo": "", "taxCode": "", "after": 0}
    if not html:
        return out
    raw = re.sub(r"<[^>]+>", " ", html)
    raw = re.sub(r"\s+", " ", raw)
    low = _vn_fold(raw)
    mu = re.search(r"https?://[^\s\"'<>]*(?:tra-?cuu|tracuu|lookup|hoadon|einvoice|e-invoice|xuathoadon|minvoice|meinvoice|vnpt-invoice|viettel|misa|fpt|easyinvoice|softdreams)[^\s\"'<>]*", raw, re.I)
    if mu:
        out["url"] = mu.group(0).rstrip('.,);:"\'')
    mc = re.search(r"(?:Mã\s*tra\s*cứu|Mã\s*số\s*bí\s*mật|Mã\s*nhận\s*hóa\s*đơn|Lookup\s*code)\s*[:\-]?\s*([0-9A-Za-z]{4,24})", raw, re.I)
    if mc:
        out["code"] = mc.group(1)
    mi = re.search(r"(?:so hoa don|hoa don[^0-9]{0,18}so|invoice\s*(?:no|number|#))\s*[:\-]?\s*(\d{1,10})", low)
    if mi:
        out["invNo"] = mi.group(1)
    mt = re.search(r"(?:ma so thue|mst|tax\s*code)\s*[:\-]?\s*(\d{10}(?:-\d{3})?)", low)
    if mt:
        out["taxCode"] = mt.group(1)
    ma = re.search(r"(?:tong (?:tien )?thanh toan|tong cong (?:tien )?thanh toan|total payment|grand total)\s*[:\-]?\s*([0-9][0-9.,]{3,})", low)
    if ma:
        n = _einv_num(ma.group(1))
        if 1000 <= n < 1e12:
            out["after"] = n
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
    code = ex.get("lookupCode", "") or bf.get("code", "")
    url = bf.get("url", "")
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
            "before": ex.get("before", 0), "vat": ex.get("vat", 0), "after": after,
            "desc": subject, "attach": ex.get("_attachName", ""), "type": typ,
            "sender": from_addr or from_name, "lookup": lookup,
            "method": method,
            "needsLookup": bool(invoiceish and not (after > 0)), "source": "mailbox"}   # only invoices count toward "need lookup"


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
        seen = set(i.get("msgId") for i in (doc0.get("items") or []) if i.get("msgId"))
        since = (doc0.get("meta") or {}).get("lastSync", "")
        base = "https://graph.microsoft.com/v1.0/users/" + urllib.parse.quote(mb)
        url = base + "/mailFolders/inbox/messages?$select=subject,from,receivedDateTime,hasAttachments,internetMessageId,bodyPreview,body&$orderby=receivedDateTime%20desc&$top=40"
        if since:                                     # overlap the watermark so mail-delivery lag isn't skipped (msgId de-dupes)
            url += "&$filter=receivedDateTime%20ge%20" + _iso_minus(since, 15)
        cap = 100 if not since else 8                 # first run backfills fully; incremental stays cheap
        new_items = []
        needlook = 0
        newest = since
        pages = 0
        try:
            while url and pages < cap:
                j = _graph_get(url, token)
                for m in j.get("value", []):
                    rd = m.get("receivedDateTime", "")
                    if rd and (not newest or rd > newest):
                        newest = rd
                    mid = m.get("internetMessageId") or m.get("id")
                    if mid in seen:
                        continue
                    seen.add(mid)
                    ex = None
                    if m.get("hasAttachments"):
                        try:
                            aj = _graph_get(base + "/messages/" + m["id"] + "/attachments?$select=name,contentType,contentBytes", token)
                            for a in aj.get("value", []):
                                nm = (a.get("name") or "").lower()
                                cb = a.get("contentBytes")
                                if not cb:
                                    continue
                                raw = base64.b64decode(cb)
                                if nm.endswith(".xml"):
                                    ex = _einv_parse_xml(raw)
                                elif nm.endswith(".zip"):
                                    ex = _einv_from_zip(raw)
                                elif nm.endswith(".pdf") and INVTRACK["ocr_url"]:
                                    ex = _invtrack_ocr_pdf(raw)
                                if ex:
                                    ex["_attachName"] = a.get("name")
                                    break
                        except Exception:
                            pass
                    item = _invtrack_item(m, ex)
                    new_items.append(item)
                    if item.get("needsLookup"):
                        needlook += 1
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
        cur_seen = set(i.get("msgId") for i in cur_items if i.get("msgId"))
        added = 0
        for it in new_items:
            if it.get("msgId") and it["msgId"] in cur_seen:
                continue
            cur_items.append(it)
            cur_seen.add(it.get("msgId"))
            added += 1
        cur_meta = cur.get("meta") or {}
        cur_meta.update({"mailbox": mb, "company": cur_meta.get("company", "CÔNG TY TNHH HUMILEY VIỆT NAM (MST 0318835868)"),
                         "lastSync": newest or since, "lastSyncRun": _now_iso(), "lastTrigger": trigger})
        cur["items"] = cur_items
        cur["meta"] = cur_meta
        cur["kind"] = "invtrack-dataset"
        db.put_collection_item("invtrack", cur)
        if added:                                      # don't spam the audit trail on empty runs
            _invtrack_audit(trigger, added, needlook)
        return {"ok": True, "added": added, "needLookup": needlook, "total": len(cur_items), "lastSync": cur_meta["lastSync"]}


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
        # Baseline security response headers. HSTS is set at the TLS edge by Caddy
        # (Strict-Transport-Security in the Caddyfile) — not here, since it must only be
        # emitted over HTTPS and the app also serves plain HTTP in demo/local runs.
        self.send_header("X-Content-Type-Options", "nosniff")
        self.send_header("X-Frame-Options", "SAMEORIGIN")
        self.send_header("Referrer-Policy", "strict-origin-when-cross-origin")
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
        if path == "/api/invtrack/status":
            return self._guard(lambda u: self._invtrack_status(u))
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
        if path == "/api/invtrack/sync":
            return self._guard(lambda u: self._invtrack_sync_ep(u))
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
        # A deactivated employee cannot sign in. Protected super-admins are exempt.
        if (emp.get("status") or "Active").strip().lower() == "inactive" and email not in self.ADMIN_EMAILS:
            return self._err("This account has been deactivated. Please contact HR.", 403)
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

    def _lvl_rank(self, lvl):
        return self._LEVEL_RANK.get((lvl or "staff"), 1)

    def _is_mgmt(self, u):
        # Use the EFFECTIVE level (_caller_level derives management/manager from role+title when the
        # stored `level` column is NULL — true for seeded/M365-synced managers), not the raw column,
        # so a Director with no explicit level is not mis-treated as staff.
        return self._lvl_rank(self._caller_level(u)) >= self._LEVEL_RANK["management"]

    def _is_approver(self, u):
        # Final approval is reserved for Editor + Admin (request #6). A direct manager who is an
        # Editor/Admin approves in ONE step (request #5) — see the "approved" branch below.
        return self._lvl_rank(self._caller_level(u)) >= self._LEVEL_RANK["editor"]

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

    _RE_DATE = re.compile(r"^\d{4}-\d{2}-\d{2}$")
    _RE_TIME = re.compile(r"^([01]\d|2[0-3]):[0-5]\d$")

    @staticmethod
    def _vn_day(offset_days=0):
        """The company's calendar day (UTC+7) — never trust the server's own timezone."""
        return (datetime.utcnow() + timedelta(hours=7, days=offset_days)).strftime("%Y-%m-%d")

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
        date = body.get("date"); t = body.get("time")
        if not isinstance(date, str) or not self._RE_DATE.match(date or ""):
            return self._err("Invalid date.")
        if not isinstance(t, str) or not self._RE_TIME.match(t or ""):
            return self._err("Invalid time.")
        # attendance is recorded for the company's TODAY only — no back/future-dating
        if date != self._vn_day():
            return self._err("Check-in must be for today.")
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
        rid = db.clock_in(emp_id, date, t, loc=str(body.get("loc") or "")[:120],
                          lat=lat, lon=lon, status=status)
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
        # today's open record first; else yesterday's (overnight/OT shifts checking out after 00:00)
        rec = db.open_attendance_any(u["id"], [self._vn_day(), self._vn_day(-1)])
        if not rec:
            return self._err("No open check-in to close.")
        overnight = rec["date"] != self._vn_day()
        if not overnight and rec.get("clock_in") and t < rec["clock_in"]:
            return self._err("Check-out time is before today's check-in.")
        # Optional overtime REQUEST at checkout — pending manager approval; only approved OT counts.
        try:
            ot_hours = float(body.get("otHours") or 0)
        except (TypeError, ValueError):
            return self._err("Invalid overtime hours.")
        if not (0 <= ot_hours <= 16):
            return self._err("Overtime hours must be between 0 and 16.")
        hrs = db.clock_out(rec["id"], t, ot_hours=ot_hours,
                           ot_reason=str(body.get("otReason") or "")[:500], overnight=overnight)
        db.put_collection_item("audit", {"actor": u.get("name"), "actorId": u.get("id"),
            "action": "Check-out", "target": "attendance/" + str(rec["id"]),
            "detail": rec["date"] + " → " + t + (" · overnight" if overnight else "") + (" · OT %.1fh requested" % ot_hours if ot_hours else ""),
            "ts": self._utc_now()})
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
        st = db.decide_attendance_ot(int(aid), decision)
        db.put_collection_item("audit", {"actor": u.get("name"), "actorId": u.get("id"),
            "action": "Overtime " + ("approved" if decision == "approve" else "rejected"),
            "target": "attendance/" + str(aid),
            "detail": (rec.get("name") or "") + " · %.1fh" % float(rec.get("ot_hours") or 0),
            "ts": self._utc_now()})
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
        # Part 11 + 3-level approval: a leave DECISION (approve/reject) requires an e-signature and
        # goes ONLY through /api/esign (which runs _appr_check). This unsigned endpoint must never
        # decide leave — the UI already uses the signed flow; block the bypass.
        if status in ("approved", "rejected"):
            return self._err("Leave approval/rejection requires an e-signature — use the approval flow.", 403)
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
        return self._json({"ok": True, "id": db.create_employee(body)})

    def _emp_list_for(self, u):
        """Staff see a directory-safe roster (own record full); managers+ see all fields."""
        rows = db.list_employees()
        if self._caller_level(u) != "staff":
            return rows
        me = u.get("id")
        return [e if e.get("id") == me else {k: v for k, v in e.items() if k not in self.EMP_SENSITIVE} for e in rows]

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
        db.delete_employee(eid)
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
            for _k in ("status", "dept", "department", "managerEmail", "salary", "grade", "endDate", "email", "title"):
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
        out["teamsWebhook"] = db.get_setting("portal_teamsWebhook")
        out["financeSpUrl"] = db.get_setting("portal_financeSpUrl", "") or ""
        out["procurementUrl"] = db.get_setting("portal_procurementUrl", "") or ""
        return self._json(out)

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
                      ("procurementUrl", "portal_procurementUrl")):
            v = body.get(k)
            if not isinstance(v, str):
                continue
            if k != "teamsWebhook":
                v = v.strip()
            cur = db.get_setting(sk, "") or ""
            if v == (cur if isinstance(cur, str) else ""):
                continue
            if not is_admin:
                return self._err("Admin access required to change integration URLs.", 403)
            db.set_setting(sk, v)
        return self._json({"ok": True})

    # -- generic HR collections (recruitment, onboarding, performance, talent, training) --
    COLLECTIONS = {"jobs", "candidates", "onboarding", "reviews", "goals", "courses", "talent", "payruns", "padr", "competency", "pip", "claims", "acks", "audit", "travel", "exits", "benefits", "learningpaths", "enrollments", "payadjust", "devices", "handovers", "payments", "crm_deals", "crm_companies", "crm_contacts", "crm_leads", "crm_products", "crm_targets", "crm_aop", "pm_projects", "pm_settings", "pm_deliverables", "pm_tasks", "pm_costs", "pm_quality", "pm_quality_itp", "pm_quality_itp_items", "pm_resources", "pm_comms", "pm_issues", "pm_risks", "pm_changes", "pm_lessons", "pm_procurement", "pm_procurement_payments", "pm_stakeholders", "pm_rfis", "pm_sitereports", "pm_weekreports", "pm_portfolioSnapshots", "pm_execNotes", "invtrack"}
    # Collections any authenticated user (incl. staff) may create for self-service.
    STAFF_WRITE = {"claims", "travel", "payments", "acks", "audit", "padr", "enrollments", "crm_deals", "crm_companies", "crm_contacts", "crm_leads", "crm_products", "crm_targets", "crm_aop", "pm_tasks", "pm_deliverables", "pm_quality", "pm_quality_itp", "pm_quality_itp_items", "pm_resources", "pm_comms", "pm_issues", "pm_risks", "pm_changes", "pm_lessons", "pm_stakeholders", "pm_rfis", "pm_sitereports", "pm_weekreports"}
    PAYROLL_ADMIN = {"payruns", "payadjust"}   # payroll writes are Administrator-only
    # minimum access LEVEL required to READ a collection. Sensitive HR data raised to
    # management; recruitment/audit stay manager. Anything not listed AND not in
    # SELF_OWNED / a shared catalog (courses, learningpaths) is open to managers only
    # for staff via the self-owner scoping below.
    READ_MIN = {"invtrack": "management", "payruns": "management", "payadjust": "management", "exits": "management", "pip": "management",
                "reviews": "manager", "talent": "manager", "jobs": "manager", "candidates": "manager",
                "competency": "manager", "audit": "manager",
                # Project financials must not be world-readable to every staff account (the PM app is
                # on by default). Line-item costs + vendor payments need manager+; creation is already
                # manager-gated, so this makes read match write.
                "pm_costs": "manager", "pm_procurement_payments": "manager"}
    # Staff MAY read these collections, but ONLY their own records (scoped by empId / name / assignedTo).
    SELF_OWNED = {"claims", "travel", "payments", "acks", "padr", "enrollments", "onboarding", "goals", "benefits", "devices", "handovers"}
    # Travel / claim / payment: a staff user sees only their OWN; a LEADER (manager) sees only their
    # TEAM (direct reports + self); management/editor/admin (Finance-level and above) see the whole
    # company. Scoped below in _coll_list.
    TEAM_SCOPED = {"claims", "travel", "payments"}
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
        lvl = self._caller_level(u)
        # staff see ONLY their own records in self-service collections (no cross-employee read)
        if lvl == "staff" and name in self.SELF_OWNED:
            myid, myname = u.get("id"), u.get("name")
            items = [it for it in items
                     if it.get("empId") == myid
                     or (not it.get("empId") and myname and it.get("name") == myname)
                     or (myname and it.get("assignedTo") == myname)]
        # Travel / claim / payment: a LEADER (manager level) sees ONLY their TEAM — their own
        # records plus those of the employees who report DIRECTLY to them (managerEmail == theirs).
        # Management / editor / admin (Finance-level and above) fall through and see the whole
        # company; staff were already scoped to their own just above.
        elif lvl == "manager" and name in self.TEAM_SCOPED:
            # A department manager sees their WHOLE DEPARTMENT's payments / travel / claims (+ their
            # own), scoped by the requester's department (resolved from the employee row, with the
            # record's stored `department` as a fallback). No dept on the manager -> own records only
            # (deny-by-default, never widen). Issue #19.
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
        # Defense-in-depth: strip angle brackets from CRM string fields so a stored value
        # can never inject markup when re-rendered (frontend also HTML-escapes on output).
        out = dict(body or {})
        for k, v in list(out.items()):
            if isinstance(v, str):
                out[k] = v.replace("<", "").replace(">", "")
        return out

    _MONEY_MAX = 100_000_000_000   # 100 billion VND ceiling per record — anything above is a typo/abuse

    def _validate_money_item(self, name, item):
        def num(v):
            try:
                return float(v)
            except (TypeError, ValueError):
                return None
        for k in ("amount", "cost", "total", "advance", "grandTotal"):
            if k in item and item.get(k) not in (None, ""):
                n = num(item.get(k))
                if n is None:
                    return "%s must be a number." % k
                if n < 0:
                    return "%s cannot be negative." % k
                if n > self._MONEY_MAX:
                    return "%s exceeds the allowed maximum." % k
        adv, cost = num(item.get("advance")), num(item.get("cost") or item.get("total") or item.get("amount"))
        if adv is not None and cost is not None and adv > cost:
            return "The advance cannot exceed the total amount."
        for it in (item.get("items") or []):
            if isinstance(it, dict):
                n = num(it.get("amount"))
                if it.get("amount") not in (None, "") and (n is None or n < 0 or n > self._MONEY_MAX):
                    return "Each line amount must be a valid non-negative number."
        return None

    def _invtrack_status(self, u):
        if self._level_rank(self._caller_level(u)) < self._level_rank("management"):
            return self._err("Finance access required.", 403)
        return self._json({"appReady": _invtrack_app_ready(), "mailbox": INVTRACK["mailbox"], "interval": INVTRACK["interval"], "ocr": bool(INVTRACK["ocr_url"])})

    def _invtrack_sync_ep(self, u):
        if self._level_rank(self._caller_level(u)) < self._level_rank("management"):
            return self._err("Invoice Tracking is a Finance function \u2014 Approver level or above required.", 403)
        return self._json(_invtrack_sync("manual"))

    def _coll_add(self, u, name, body):
        if name not in self.COLLECTIONS:
            return self._err("Unknown collection.", 404)
        if name.startswith("pm_") and name not in self.STAFF_WRITE and u.get("role") != "manager":
            return self._err("Manager access required.", 403)
        if name.startswith("crm_") or name.startswith("pm_") or name in ("claims", "travel", "payments", "leave"):
            body = self._crm_sanitize(body)
        if name in self.PAYROLL_ADMIN and self._level_rank(self._caller_level(u)) < self._level_rank("editor"):
            return self._err("Payroll changes require Editor level or above.", 403)
        if name == "invtrack" and self._level_rank(self._caller_level(u)) < self._level_rank("management"):
            return self._err("Invoice Tracking is a Finance function — Approver level or above required.", 403)
        item = dict(body or {})
        # Amount sanity on money records: reject negative/non-numeric/absurd, advance<=cost.
        if name in ("claims", "travel", "payments"):
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
        if name.startswith("pm_"):
            item.setdefault("createdBy", u.get("name"))
            item.setdefault("createdById", u.get("id"))
        return self._json({"ok": True, "item": db.put_collection_item(name, item)})

    def _coll_update(self, u, name, iid, body):
        if name not in self.COLLECTIONS or not iid:
            return self._err("Unknown item.", 404)
        if name.startswith("pm_") and name not in self.STAFF_WRITE and u.get("role") != "manager":
            return self._err("Manager access required.", 403)
        if name.startswith("crm_") or name.startswith("pm_") or name in ("claims", "travel", "payments", "leave"):
            body = self._crm_sanitize(body)
        if name in self.PAYROLL_ADMIN and self._level_rank(self._caller_level(u)) < self._level_rank("editor"):
            return self._err("Payroll changes require Editor level or above.", 403)
        if name == "invtrack" and self._level_rank(self._caller_level(u)) < self._level_rank("management"):
            return self._err("Invoice Tracking is a Finance function — Approver level or above required.", 403)
        # Travel/claim/payment write scope: a LEADER (manager) may only edit records they own or that
        # belong to a direct report — mirrors the read scope so a manager can't rewrite another team's
        # finance record via a guessed id. Management+ (Finance/Editor/Admin) edit any.
        if name in self.TEAM_SCOPED and u.get("role") == "manager" and not self._is_mgmt(u):
            existing = next((x for x in db.list_collection(name) if x.get("id") == iid), None)
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
            existing = next((x for x in db.list_collection(name) if x.get("id") == iid), None)
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
        # 21 CFR Part 11 / 3-level approval integrity: the generic write path must NEVER set
        # approval status or signatures. Those transition ONLY through /api/esign (_appr_check +
        # fresh re-auth). Preserve the server-held values and drop any client attempt to change
        # them — this closes the "PATCH status=Approved / forge signatures" bypass.
        if name in ("claims", "travel", "payments", "leave"):
            existing = existing if name in ("claims", "travel", "payments", "acks") else next((x for x in db.list_collection(name) if x.get("id") == iid), None)
            # Once a money record is signed/approved/paid its CONTENT is immutable evidence — a
            # generic PATCH must not alter amount/payee/items after signing, or the Part 11
            # signature would attest to values changed afterwards. Only ADMIN may correct it.
            if existing and name in ("claims", "travel", "payments") and self._caller_level(u) != "admin":
                _st = str(existing.get("status") or "").strip().lower()
                if _st in ("approved", "paid", "reviewed") or existing.get("signatures"):
                    return self._err("This request has been signed/approved and can no longer be edited.", 403)
            # Validate money on the incoming edit too (add-time validation alone was insufficient).
            if name in ("claims", "travel", "payments"):
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
                # protect per-line statuses/signatures on multi-item claims too
                if isinstance(existing.get("items"), list) and isinstance(item.get("items"), list):
                    ex_items = existing["items"]
                    for i, it in enumerate(item["items"]):
                        if i < len(ex_items) and isinstance(it, dict) and isinstance(ex_items[i], dict):
                            for _k in ("status", "reviewedBy", "reviewedById", "approvedBy"):
                                if _k in ex_items[i]:
                                    it[_k] = ex_items[i][_k]
                                else:
                                    it.pop(_k, None)
            else:
                # no existing record to protect against — refuse to create a signed record via PATCH
                for _k in ("status", "signatures"):
                    item.pop(_k, None)
        return self._json({"ok": True, "item": {k: v for k, v in db.put_collection_item(name, item).items() if k != "token"}})

    def _coll_delete(self, u, name, iid):
        if name not in self.COLLECTIONS or not iid:
            return self._err("Unknown item.", 404)
        # The audit trail is append-only (21 CFR Part 11) — never deletable via the generic store.
        if name == "audit":
            return self._err("Audit-trail entries cannot be deleted.", 403)
        if name in self.PAYROLL_ADMIN and self._level_rank(self._caller_level(u)) < self._level_rank("editor"):
            return self._err("Payroll changes require Editor level or above.", 403)
        if name == "invtrack" and self._level_rank(self._caller_level(u)) < self._level_rank("management"):
            return self._err("Invoice Tracking is a Finance function — Approver level or above required.", 403)
        existing = next((x for x in db.list_collection(name) if x.get("id") == iid), None)
        if not existing:
            return self._err("Not found.", 404)
        is_admin = self._caller_level(u) == "admin"
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
        db.delete_collection_item(name, iid)
        db.put_collection_item("audit", {"actor": u.get("name") or "System", "actorId": u.get("id") or "",
            "action": "Deleted " + name, "target": name + "/" + str(iid),
            "detail": "status=" + str(existing.get("status") or "-"), "ts": self._utc_now()})
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
    # Part 11 e-sign PIN pepper must be set BEFORE any PIN is enrolled — a PIN hashed without the
    # pepper cannot be re-derived once one is added, so those signatures would stop validating.
    if not DEMO_MODE and not os.environ.get("TK_ESIGN_PEPPER"):
        print("  \033[1;33m⚠  TK_ESIGN_PEPPER is NOT set.\033[0m Set it (openssl rand -hex 32) BEFORE")
        print("     any user enrolls an e-signature PIN — adding it later invalidates existing PINs.")
    if seeded:
        print("  Database seeded with %d employees." % len(db.list_employees()))
    print("  Open: http://localhost:%d/" % PORT)
    print("=" * 62)
    if _invtrack_app_ready():
        threading.Thread(target=_invtrack_scheduler, daemon=True).start()
        print("  Invoice tracking: app-only mailbox sync every %d min for %s" % (INVTRACK["interval"], INVTRACK["mailbox"]))
    ThreadingHTTPServer((HOST, PORT), Handler).serve_forever()


if __name__ == "__main__":
    main()
