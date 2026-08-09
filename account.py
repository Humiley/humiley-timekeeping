"""The customer, as one record with one identity — Stage 1 of the sell side.

Today the customer exists four times as a free-text string: crm_companies.name feeds
crm_deals.company, which feeds pm_projects.account, which has nothing to do with payments.payee.
Rename a company and its pipeline silently drops to zero, because the join is the spelling. "ABC
Corp" and "ABC Corp." are two customers forever, and `pmFromDeal` writes accountId:'' every time it
creates a project.

None of that is survivable once a CONTRACT or an INVOICE names the customer, which is why this is
the stage that cannot be deferred: documents raised against a spelling can never be untangled
afterwards, and a JSON blob store has no joins and no migration tooling to untangle them with.

What lives here is the part that is rules rather than plumbing:

  · the tax code (MST), because an invoice that names the wrong buyer is not the buyer's invoice
  · payment terms, and the fact that the clock can start on three different events
  · whether an account is complete enough to raise a document against at all
  · finding the duplicates that already exist, and merging them without losing history
  · the qualification pack an audited pharma or electronics customer demands, and its expiry

One thing this module deliberately does NOT do: reject a tax code it merely dislikes. Vietnamese MSTs
carry a check digit, and the algorithm circulating in blog posts is not something worth asserting
against a real customer's real tax code — a false rejection stops an invoice going out, which is
worse than the typo it was trying to catch. Format is checked and stated; the arithmetic is not
claimed. See UNVERIFIED at the bottom.

Pure — no database, no clock. Exercised by tests/test_account.py.
"""
import re
import unicodedata

# ── the tax code (mã số thuế) ────────────────────────────────────────────────────────────────────
# 10 digits identify a legal entity. A dependent unit (branch, chi nhánh) adds a 3-digit suffix,
# written 0123456789-001. Both forms appear on real invoices and both must be accepted.
ENTITY, BRANCH, UNKNOWN = "entity", "branch", "unknown"

_MST_CLEAN = re.compile(r"[^0-9-]")
_MST_ENTITY = re.compile(r"^\d{10}$")
_MST_BRANCH = re.compile(r"^\d{10}-\d{3}$")

OK = "ok"


def normalise_mst(v):
    """'0123 456 789 - 001' -> '0123456789-001'. Spaces and dots are how people type it."""
    s = _MST_CLEAN.sub("", str(v or "").strip())
    s = re.sub(r"-+", "-", s).strip("-") if s.count("-") > 1 else s
    return s


def check_mst(v):
    """Is this a usable Vietnamese tax code? A judgement with a reason, never a silent pass.

    Returns ok=False for a format that cannot be right, and `blocking=False` throughout: a wrong
    tax code should stop somebody and make them look, not stop the business. The one thing it must
    never do is quietly accept an empty value as valid — a missing MST on a customer is exactly the
    gap this stage exists to close.
    """
    raw = str(v or "").strip()
    s = normalise_mst(raw)
    if not s and raw:
        # Something was typed and none of it was a digit. Saying "no tax code recorded" here would
        # send somebody looking for an empty field that is not empty.
        return {"ok": False, "code": "bad_format", "kind": UNKNOWN, "blocking": False,
                "normalised": "",
                "why": "\u201c%s\u201d contains no digits. A Vietnamese tax code is 10 digits, or "
                       "10 digits and a 3-digit branch suffix (0123456789-001)." % raw[:40],
                "whyVn": "\u201c%s\u201d không chứa chữ số. Mã số thuế Việt Nam gồm 10 số, hoặc 10 "
                         "số kèm 3 số của chi nhánh." % raw[:40]}
    if not s:
        return {"ok": False, "code": "empty", "kind": UNKNOWN, "blocking": False,
                "why": "No tax code recorded. A Vietnamese VAT invoice must name the buyer's MST, "
                       "so this has to be filled in before you can bill this customer.",
                "whyVn": "Chưa có mã số thuế. Hóa đơn GTGT phải ghi MST của người mua, nên cần bổ "
                         "sung trước khi xuất hóa đơn cho khách hàng này."}
    if _MST_ENTITY.match(s):
        return {"ok": True, "code": OK, "kind": ENTITY, "blocking": False, "normalised": s,
                "why": "A 10-digit entity tax code.", "whyVn": "Mã số thuế 10 số của pháp nhân."}
    if _MST_BRANCH.match(s):
        return {"ok": True, "code": OK, "kind": BRANCH, "blocking": False, "normalised": s,
                "why": "A 13-digit dependent-unit code (branch).",
                "whyVn": "Mã số thuế 13 số của đơn vị phụ thuộc (chi nhánh)."}
    return {"ok": False, "code": "bad_format", "kind": UNKNOWN, "blocking": False, "normalised": s,
            "why": "A Vietnamese tax code is 10 digits, or 10 digits and a 3-digit branch suffix "
                   "(0123456789-001). Got %d character(s): %s" % (len(s), s or "(blank)"),
            "whyVn": "Mã số thuế Việt Nam gồm 10 số, hoặc 10 số kèm 3 số của chi nhánh "
                     "(0123456789-001)."}


# ── payment terms ────────────────────────────────────────────────────────────────────────────────
# WHEN the clock starts is a negotiated term, not a constant — and in Vietnam "when our AP receives
# the VAT invoice" is common and quietly adds weeks. Getting this wrong makes every aging number
# wrong in the same direction, which is the kind of error nobody notices until cash is short.
BASIS_INVOICE, BASIS_ACCEPTANCE, BASIS_AP_RECEIPT = "invoice_date", "acceptance", "ap_receipt"

DUE_BASIS = (
    {"code": BASIS_INVOICE, "label": "Invoice date", "labelVn": "Ngày hóa đơn",
     "note": "The clock starts when you issue the invoice."},
    {"code": BASIS_ACCEPTANCE, "label": "Acceptance (biên bản nghiệm thu)", "labelVn": "Ngày nghiệm thu",
     "note": "The clock starts when the work is accepted, whatever the invoice date."},
    {"code": BASIS_AP_RECEIPT, "label": "Customer AP receives the invoice", "labelVn": "Ngày AP nhận hóa đơn",
     "note": "Common in Vietnam and it adds the postal/handover time to every payment."},
)

TERMS = (
    {"code": "NET0", "days": 0, "label": "Due on receipt", "labelVn": "Thanh toán ngay"},
    {"code": "NET15", "days": 15, "label": "15 days", "labelVn": "15 ngày"},
    {"code": "NET30", "days": 30, "label": "30 days", "labelVn": "30 ngày"},
    {"code": "NET45", "days": 45, "label": "45 days", "labelVn": "45 ngày"},
    {"code": "NET60", "days": 60, "label": "60 days", "labelVn": "60 ngày"},
    {"code": "NET90", "days": 90, "label": "90 days", "labelVn": "90 ngày"},
)


def terms_days(code, fallback=None):
    """The net days for a terms code, or `fallback` when the code is not one we know.

    Returns None rather than 0 for an unknown code: 0 means "due on receipt", which is a real and
    aggressive term, and inventing it for an account nobody configured would put every invoice
    instantly overdue.
    """
    for t in TERMS:
        if t["code"] == str(code or "").strip().upper():
            return t["days"]
    return fallback


def due_date(start_iso, net_days):
    """The due date, or '' when either input is missing — never today, never a guess."""
    from datetime import date, timedelta
    try:
        d = date.fromisoformat(str(start_iso)[:10])
        n = int(net_days)
    except (TypeError, ValueError):
        return ""
    return (d + timedelta(days=n)).isoformat()


# ── is this account complete enough to bill? ─────────────────────────────────────────────────────
# The buyer's legal name, tax code and registered address are what a Vietnamese VAT invoice has to
# carry about the customer. The portal cannot issue that invoice, but it must not let a billing
# document be raised against a customer whose identity it cannot state.
INVOICE_FIELDS = (
    ("legalNameVn", "Legal name (Vietnamese)", "Tên pháp nhân (tiếng Việt)"),
    ("mst", "Tax code (MST)", "Mã số thuế"),
    ("regAddress", "Registered address", "Địa chỉ đăng ký"),
)


def invoice_readiness(acc):
    """What is still missing before this customer can be billed, named field by field."""
    acc = acc or {}
    missing = [{"field": f, "label": lbl, "labelVn": vn}
               for f, lbl, vn in INVOICE_FIELDS if not str(acc.get(f) or "").strip()]
    mst = check_mst(acc.get("mst"))
    bad_mst = bool(str(acc.get("mst") or "").strip()) and not mst["ok"]
    return {
        "ready": not missing and not bad_mst,
        "missing": missing,
        "mst": mst,
        "why": ("Ready to bill." if not missing and not bad_mst else
                "Cannot bill yet: " + ", ".join([m["label"] for m in missing] +
                                                (["the tax code is not a valid format"] if bad_mst else []))),
    }


# ── the duplicates that already exist ────────────────────────────────────────────────────────────
# "ABC Corp", "ABC Corp.", "Công ty ABC" and "abc  corp" are one customer. Detection is a SUGGESTION
# — a human confirms every merge, because two genuinely different companies can share a trading name
# and merging them would fuse two customers' contracts.
_SUFFIX = re.compile(
    r"\b(co|company|corp|corporation|inc|ltd|limited|jsc|llc|plc|pte|"
    r"cong ty|cty|tnhh|mtv|cp|co phan|tap doan|chi nhanh)\b", re.I)


def fold_name(v):
    """A comparison key: accents dropped, legal suffixes and punctuation removed, spaces collapsed.

    Only ever used to SUGGEST a duplicate. It is deliberately aggressive, which is safe for finding
    candidates and would be unsafe for deciding anything.
    """
    s = unicodedata.normalize("NFD", str(v or ""))
    s = "".join(c for c in s if unicodedata.category(c) != "Mn")
    s = s.replace("đ", "d").replace("Đ", "D").lower()
    s = re.sub(r"[^a-z0-9\s]", " ", s)
    s = _SUFFIX.sub(" ", s)
    return re.sub(r"\s+", " ", s).strip()


def duplicate_groups(accounts):
    """Accounts that look like one customer. Grouped by tax code first, then by folded name.

    The tax code is the stronger signal by far — two records sharing an MST are the same legal
    entity — so it wins, and a name match only groups records that do not contradict on MST.
    """
    live = [a for a in (accounts or []) if isinstance(a, dict) and not a.get("mergedInto")]
    by_mst, groups = {}, []
    for a in live:
        m = normalise_mst(a.get("mst"))
        if m and check_mst(m)["ok"]:
            by_mst.setdefault(m, []).append(a)
    grouped_ids = set()
    for m, rows in by_mst.items():
        if len(rows) > 1:
            groups.append({"reason": "mst", "key": m, "accounts": rows})
            grouped_ids.update(id(r) for r in rows)
    by_name = {}
    for a in live:
        if id(a) in grouped_ids:
            continue
        k = fold_name(a.get("name"))
        if k:
            by_name.setdefault(k, []).append(a)
    for k, rows in by_name.items():
        if len(rows) > 1:
            msts = {normalise_mst(r.get("mst")) for r in rows if normalise_mst(r.get("mst"))}
            if len(msts) > 1:
                continue          # same trading name, different legal entities — not a duplicate
            groups.append({"reason": "name", "key": k, "accounts": rows})
    return sorted(groups, key=lambda g: (-len(g["accounts"]), g["key"]))


# Which collection field points at an account, so a merge knows what to repoint. By NAME today,
# which is the whole problem; accountId is written alongside so the next stage can stop using names.
CHILD_LINKS = (
    {"coll": "crm_deals", "nameField": "company", "idField": "accountId"},
    {"coll": "crm_contacts", "nameField": "company", "idField": "accountId"},
    {"coll": "crm_leads", "nameField": "company", "idField": "accountId"},
    {"coll": "pm_projects", "nameField": "account", "idField": "accountId"},
)


def merge_plan(primary, duplicate, children_by_coll):
    """What a merge would do, before it does it. Refuses anything that would lose information.

    A merge is not a delete. The duplicate is kept as a tombstone pointing at the survivor, so a
    link, a report or a printed document that names the old account still resolves. Deleting it
    would break exactly the history this stage exists to protect.
    """
    p, d = primary or {}, duplicate or {}
    if not p.get("id") or not d.get("id"):
        return {"ok": False, "why": "Both accounts must exist."}
    if p["id"] == d["id"]:
        return {"ok": False, "why": "An account cannot be merged into itself."}
    if d.get("mergedInto"):
        return {"ok": False, "why": "That account has already been merged."}
    if p.get("mergedInto"):
        return {"ok": False, "why": "The surviving account has itself been merged into another."}
    pm, dm = normalise_mst(p.get("mst")), normalise_mst(d.get("mst"))
    if pm and dm and pm != dm:
        return {"ok": False, "why": "These are different legal entities — tax codes %s and %s. "
                                    "Merging them would fuse two customers." % (pm, dm)}
    moves, fills = [], {}
    for link in CHILD_LINKS:
        rows = (children_by_coll or {}).get(link["coll"]) or []
        hit = [r for r in rows
               if str(r.get(link["nameField"]) or "").strip() == str(d.get("name") or "").strip()
               or (r.get(link["idField"]) and r.get(link["idField"]) == d["id"])]
        if hit:
            moves.append({"coll": link["coll"], "count": len(hit),
                          "nameField": link["nameField"], "idField": link["idField"],
                          "ids": [r.get("id") for r in hit]})
    # A field the survivor is missing and the duplicate has is worth keeping — that is usually why
    # the duplicate was created in the first place.
    for f, _l, _v in INVOICE_FIELDS:
        if not str(p.get(f) or "").strip() and str(d.get(f) or "").strip():
            fills[f] = d[f]
    for f in ("bizRegNo", "repName", "repTitle", "phone", "website", "address", "einvEmail"):
        if not str(p.get(f) or "").strip() and str(d.get(f) or "").strip():
            fills[f] = d[f]
    return {
        "ok": True, "primaryId": p["id"], "duplicateId": d["id"],
        "moves": moves, "movedTotal": sum(m["count"] for m in moves), "fills": fills,
        "why": "%d record(s) move to %s; %s is kept as a tombstone pointing at it, never deleted."
               % (sum(m["count"] for m in moves), p.get("name") or p["id"], d.get("name") or d["id"]),
    }


def resolve_name(name, accounts):
    """Which account is this free-text name? An answer, an honest "I don't know", or "which one?".

    Exact name wins over a folded match, and a folded match only counts when it is UNIQUE. Anything
    ambiguous returns candidates and no decision, because the whole point of the backfill is to stop
    the system joining records on a guess — replacing a bad guess with a confident one would be
    worse than the free text it is fixing.

    A name that resolves to a tombstone follows the pointer to the survivor: that is what the
    tombstone is for.
    """
    n = str(name or "").strip()
    if not n:
        return {"status": "blank", "accountId": None, "candidates": []}
    by_id = {a.get("id"): a for a in (accounts or []) if a.get("id")}

    def survivor(a):
        seen = set()
        while a and a.get("mergedInto") and a["mergedInto"] not in seen:
            seen.add(a["mergedInto"])
            a = by_id.get(a["mergedInto"])
        return a

    exact = [a for a in (accounts or []) if str(a.get("name") or "").strip() == n]
    if len(exact) == 1:
        s = survivor(exact[0])
        return {"status": "exact", "accountId": s and s.get("id"), "candidates": []}
    if len(exact) > 1:
        # Two live accounts with the identical name. Merge them first; do not pick one.
        return {"status": "ambiguous", "accountId": None,
                "candidates": [{"id": a.get("id"), "name": a.get("name")} for a in exact]}
    key = fold_name(n)
    if not key:
        return {"status": "unmatched", "accountId": None, "candidates": []}
    folded = [a for a in (accounts or []) if fold_name(a.get("name")) == key]
    live = [a for a in folded if not a.get("mergedInto")]
    pool = live or folded
    if len(pool) == 1:
        s = survivor(pool[0])
        return {"status": "folded", "accountId": s and s.get("id"), "candidates": []}
    if len(pool) > 1:
        return {"status": "ambiguous", "accountId": None,
                "candidates": [{"id": a.get("id"), "name": a.get("name")} for a in pool]}
    return {"status": "unmatched", "accountId": None, "candidates": []}


def backfill_plan(accounts, children_by_coll):
    """What linking the existing data to real account ids would do, before it does it.

    Every row that cannot be resolved is REPORTED, never guessed. An exception list somebody has to
    work through is the honest output here; a silent best guess would bake today's typos into the
    joins and be invisible forever after.
    """
    link, ex, already, blank = [], [], 0, 0
    for l in CHILD_LINKS:
        for r in (children_by_coll or {}).get(l["coll"]) or []:
            if r.get(l["idField"]):
                already += 1
                continue
            nm = str(r.get(l["nameField"]) or "").strip()
            res = resolve_name(nm, accounts)
            if res["status"] == "blank":
                blank += 1
            elif res["accountId"]:
                link.append({"coll": l["coll"], "id": r.get("id"), "idField": l["idField"],
                             "name": nm, "accountId": res["accountId"], "how": res["status"]})
            else:
                ex.append({"coll": l["coll"], "id": r.get("id"), "name": nm,
                           "reason": res["status"], "candidates": res["candidates"]})
    return {
        "link": link, "exceptions": ex, "alreadyLinked": already, "noName": blank,
        "why": "%d record(s) can be linked; %d need a human (%d ambiguous, %d with no matching "
               "account); %d already linked and %d carry no customer name."
               % (len(link), len(ex), len([e for e in ex if e["reason"] == "ambiguous"]),
                  len([e for e in ex if e["reason"] == "unmatched"]), already, blank),
    }


# ── the qualification pack ───────────────────────────────────────────────────────────────────────
# A pharma or electronics customer audits its contractors. An expired certificate on their file is
# a thing that stops you invoicing, and it expires quietly.
QUALIFICATIONS = (
    {"code": "iso9001", "label": "ISO 9001", "labelVn": "ISO 9001"},
    {"code": "iso45001", "label": "ISO 45001", "labelVn": "ISO 45001"},
    {"code": "liability", "label": "Liability insurance", "labelVn": "Bảo hiểm trách nhiệm"},
    {"code": "nda", "label": "NDA", "labelVn": "Thỏa thuận bảo mật"},
    {"code": "supplierReg", "label": "Supplier registration", "labelVn": "Đăng ký nhà cung cấp"},
)

VALID, EXPIRING, EXPIRED, ABSENT = "valid", "expiring", "expired", "absent"


def qualification_status(acc, today, warn_days=60):
    """Each required document: present, expiring or already lapsed — and never silently fine.

    ABSENT is distinct from EXPIRED on purpose. "We never had it" and "it ran out" need different
    actions from different people, and collapsing them into one red badge loses that.
    """
    from datetime import date, timedelta
    try:
        t = date.fromisoformat(str(today)[:10])
    except (TypeError, ValueError):
        return {"ok": False, "items": [], "why": "No date to measure expiry against."}
    pack = (acc or {}).get("prequal") or {}
    items = []
    for q in QUALIFICATIONS:
        raw = pack.get(q["code"]) or {}
        exp = str((raw.get("expires") if isinstance(raw, dict) else raw) or "")[:10]
        try:
            e = date.fromisoformat(exp)
        except (TypeError, ValueError):
            e = None
        if e is None:
            state, days = ABSENT, None
        elif e < t:
            state, days = EXPIRED, (e - t).days
        elif e <= t + timedelta(days=warn_days):
            state, days = EXPIRING, (e - t).days
        else:
            state, days = VALID, (e - t).days
        items.append(dict(q, state=state, expires=exp, daysLeft=days))
    bad = [i for i in items if i["state"] in (EXPIRED, ABSENT)]
    soon = [i for i in items if i["state"] == EXPIRING]
    return {
        "ok": not bad, "items": items, "expired": [i for i in items if i["state"] == EXPIRED],
        "absent": [i for i in items if i["state"] == ABSENT], "expiring": soon,
        "why": ("Qualification pack complete." if not bad and not soon else
                ", ".join(([("%d document(s) missing or expired" % len(bad))] if bad else []) +
                          ([("%d expiring within %d days" % (len(soon), warn_days))] if soon else []))),
    }


# ── what this module does not claim ──────────────────────────────────────────────────────────────
UNVERIFIED = (
    {"topic": "MST check digit",
     "question": "Vietnamese tax codes carry a check digit over the first 9 digits.",
     "why_it_matters": "A checksum would catch a transposed digit that the format check cannot.",
     "action": "NOT implemented. The weighting circulating in blog posts was not verified against a "
               "primary source, and a false rejection stops a real invoice for a real customer — "
               "worse than the typo it would catch. Format is checked and stated; the arithmetic is "
               "not claimed. Add it only against the tax authority's own specification."},
    {"topic": "Which event starts the payment clock",
     "question": "Invoice date, acceptance, or the date the customer's AP receives the VAT invoice.",
     "why_it_matters": "It moves every aging figure, in the same direction, silently.",
     "action": "Offered as a per-account setting with no default. The owner sets it per customer; "
               "the portal must not pick one."},
)
