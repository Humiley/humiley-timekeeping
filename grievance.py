"""The speak-up channel: raising a concern that does not go through your own manager.

The company publishes a Code of Conduct & Anti-Harassment policy and collects a signature on it
from every employee. Until now there was no channel through which anybody could ever raise one —
signed evidence of an undertaking, with no way to invoke it. Essentially every multinational
supplier code of conduct requires the channel, and it is the one line in a client's social-
compliance audit that could not be filled in.

Three things make this different from a form:

**Confidential is not anonymous, and saying otherwise is a lie.** Every request to this portal
carries an authenticated session. A concern raised "anonymously" can omit the reporter from the
RECORD — and this module does exactly that — but the server's own request log still saw the
session. So the promise made to the reporter is precisely: *the handler will not see who you are,
and the company has not built a way to look;* not *nobody could ever find out.* `ANONYMITY_NOTICE`
is that sentence, and it travels with the form rather than living in a policy nobody reads.

**Who must NOT see it is more important than who must.** A concern about your line manager that
lands in your line manager's queue is worse than no channel: it identifies the reporter to the one
person they were afraid of. So routing excludes the people named in it, and `handlers_for` returns
the remaining handlers — refusing to route at all rather than routing to the subject.

**A concern with no clock is a filing cabinet.** Acknowledge and resolve deadlines are computed and
overdue is stated, because "we take all concerns seriously" is measured by when somebody replied.

Pure — no database, no clock. Exercised by tests/test_grievance.py.
"""
from datetime import date, timedelta

# What somebody is raising. `serious` marks the categories where the handler set is narrowed to the
# most senior handler only, because the ordinary HR route is too wide for them.
CATEGORIES = (
    {"key": "harassment", "label": "Harassment, bullying or discrimination",
     "labelVn": "Quấy rối, bắt nạt hoặc phân biệt đối xử", "serious": True},
    {"key": "safety", "label": "Health & safety — an unsafe condition or practice",
     "labelVn": "An toàn lao động — điều kiện hoặc cách làm không an toàn", "serious": False},
    {"key": "pay", "label": "Pay, hours or leave",
     "labelVn": "Tiền lương, giờ làm việc hoặc nghỉ phép", "serious": False},
    {"key": "fraud", "label": "Fraud, theft, bribery or a conflict of interest",
     "labelVn": "Gian lận, trộm cắp, hối lộ hoặc xung đột lợi ích", "serious": True},
    {"key": "management", "label": "How I am being managed",
     "labelVn": "Cách tôi được quản lý", "serious": False},
    {"key": "other", "label": "Something else",
     "labelVn": "Vấn đề khác", "serious": False},
)
_CAT = {c["key"]: c for c in CATEGORIES}

# The lifecycle. Deliberately short: a longer one invites a queue nobody works.
OPEN = "Open"
ACKNOWLEDGED = "Acknowledged"
INVESTIGATING = "Investigating"
CLOSED = "Closed"
STATES = (OPEN, ACKNOWLEDGED, INVESTIGATING, CLOSED)
LIVE_STATES = (OPEN, ACKNOWLEDGED, INVESTIGATING)

# The clock. Business choices, not law — but stated, because a channel with no deadline is a
# filing cabinet and every supplier code asks how fast the company responds.
ACK_DAYS = 3
RESOLVE_DAYS = 30
RESOLVE_DAYS_SERIOUS = 14

ANONYMITY_NOTICE = (
    "If you raise this anonymously, your name is not written to the record and the handler will not "
    "see it. Be aware that this portal signs you in, so the company's own server logs saw the "
    "session — we have not built a way to link them back, but we cannot promise that nobody ever "
    "could. If you need certainty, raise it outside this system.")
ANONYMITY_NOTICE_VN = (
    "Nếu bạn gửi ẩn danh, tên của bạn không được ghi vào hồ sơ và người xử lý sẽ không nhìn thấy. "
    "Lưu ý rằng cổng thông tin này có đăng nhập, nên nhật ký máy chủ của công ty vẫn ghi nhận phiên "
    "làm việc — chúng tôi không xây dựng cách liên kết ngược lại, nhưng không thể cam kết rằng "
    "không ai có thể làm được. Nếu bạn cần chắc chắn tuyệt đối, hãy phản ánh bên ngoài hệ thống này.")

NO_RETALIATION = (
    "Raising a concern in good faith cannot be used against you. Retaliation for doing so is itself "
    "a disciplinary matter under the Code of Conduct.")
NO_RETALIATION_VN = (
    "Việc phản ánh với thiện chí sẽ không bị dùng để chống lại bạn. Trả đũa vì điều đó tự nó là một "
    "hành vi bị xử lý kỷ luật theo Bộ Quy tắc ứng xử.")


def _s(v):
    return "" if v is None else str(v).strip()


def _d(v):
    if isinstance(v, date):
        return v
    try:
        return date.fromisoformat(_s(v)[:10])
    except (TypeError, ValueError):
        return None


def category(key):
    return _CAT.get(_s(key).lower())


def is_serious(key):
    c = category(key)
    return bool(c and c["serious"])


def resolve_days(key):
    return RESOLVE_DAYS_SERIOUS if is_serious(key) else RESOLVE_DAYS


# ── who may see it ───────────────────────────────────────────────────────────────────────────────

def handlers_for(concern, handler_ids, senior_ids=()):
    """Who may read this concern.

    Anybody NAMED in it is excluded — a concern about your manager that lands in your manager's
    queue identifies you to the person you were afraid of, which is worse than having no channel.
    A serious category narrows to the senior handlers, because the ordinary HR route is too wide
    for harassment or fraud.

    Returns [] when the exclusion empties the list. The caller must then refuse to record it and say
    who it would have gone to — silently routing it to the subject is the failure this prevents.
    """
    c = concern or {}
    about = {_s(x).lower() for x in (c.get("about") or []) if _s(x)}
    pool = list(senior_ids or ()) if is_serious(c.get("category")) else list(handler_ids or ())
    if not pool:
        pool = list(handler_ids or ())
    # The reporter cannot handle their own concern either.
    excluded = about | {_s(c.get("raisedById")).lower()} - {""}
    return [h for h in pool if _s(h).lower() not in excluded]


def may_read(concern, user_id, handler_ids, senior_ids=()):
    """Whether this user may see this concern at all.

    Two ways in, and no third: you are the person who raised it (and did not raise it anonymously),
    or you are one of the handlers it was routed to. Being an administrator is NOT one of them —
    that is the point of the channel. An administrator with database access can of course read the
    row; what this stops is the product handing it to them.
    """
    c = concern or {}
    uid = _s(user_id).lower()
    if not uid:
        return False
    if not c.get("anonymous") and _s(c.get("raisedById")).lower() == uid:
        return True
    return uid in {_s(h).lower() for h in (c.get("routedTo") or [])}


def public_view(concern, as_of=None):
    """What somebody holding the case REFERENCE may see, without proving who they are.

    An anonymous reporter can otherwise never find out what happened — the record deliberately does
    not know who they are, so `may_read` can never let them back in. A channel you cannot follow up
    is a channel people stop using. The reference is the answer, and it deliberately returns the
    STATUS ONLY: no handler names, no investigation notes, nothing that would let a lucky guess at a
    reference expose somebody else's account of events.
    """
    c = concern or {}
    d = due(c, as_of) or {}
    return {
        "ref": _s(c.get("ref")),
        "category": _s(c.get("category")),
        "categoryLabel": (category(c.get("category")) or {}).get("label", ""),
        "status": _s(c.get("status")) or OPEN,
        "raisedOn": _s(c.get("raisedOn")),
        "acknowledged": bool(d.get("acknowledged")),
        "ackBy": d.get("ackBy", ""), "resolveBy": d.get("resolveBy", ""),
        "overdue": bool(d.get("overdue")),
        "closedOn": _s(c.get("closedOn")),
        # The one substantive thing a reporter is entitled to: what was decided.
        "outcome": _s(c.get("outcome")) if _s(c.get("status")) == CLOSED else "",
    }


def reporter_view(concern, as_of=None):
    """What the person who RAISED a concern may see of their own case.

    They are entitled to their own account back, and to the progress of the case. They are NOT
    entitled to the investigation: `handlerNotes`, the `timeline` (which names who did what and
    when), and `routedTo` (which names the handlers) are the record OF the investigation, and the
    people investigating a complaint must be able to write freely about it without the complainant
    reading it over their shoulder — including where the complaint turns out to be unfounded, or
    where the notes concern a third party who is entitled to their own confidentiality.

    `may_read` lets the raiser in, and the list endpoint returned the RAW record — so every one of
    those fields reached them. public_view existed to prevent exactly this, and was only ever
    applied on the reference-lookup route.
    """
    c = concern or {}
    out = public_view(c, as_of)
    out.update({
        "id": _s(c.get("id")),
        "mine": True,
        # Their own submission, given back to them verbatim.
        "detail": _s(c.get("detail")),
        "about": list(c.get("about") or []),
        "anonymous": bool(c.get("anonymous")),
        "raisedByName": _s(c.get("raisedByName")),
        # How many people are handling it, never WHICH — the count is reassurance that it went
        # somewhere, the names are the investigation.
        "routedCount": len(c.get("routedTo") or []),
    })
    return out


# ── the clock ────────────────────────────────────────────────────────────────────────────────────

def due(concern, as_of):
    """When this concern was due to be acknowledged and resolved, and whether it is late."""
    c = concern or {}
    raised = _d(c.get("raisedOn"))
    today = _d(as_of) or date.today()
    if not raised:
        return None
    ack_by = raised + timedelta(days=ACK_DAYS)
    res_by = raised + timedelta(days=resolve_days(c.get("category")))
    acked = _d(c.get("acknowledgedOn"))
    closed = _d(c.get("closedOn"))
    return {
        "ackBy": ack_by.isoformat(), "resolveBy": res_by.isoformat(),
        "acknowledged": bool(acked),
        "ackLate": bool(acked and acked > ack_by) or (not acked and today > ack_by),
        "closed": bool(closed),
        "overdue": (not closed) and today > res_by,
        "daysOpen": (today - raised).days if not closed else (closed - raised).days,
        "basis": ("Acknowledged within %d days, resolved within %d — the company's own commitment, "
                  "not a statutory period." % (ACK_DAYS, resolve_days(c.get("category")))),
    }


def blockers(concern, handler_ids, senior_ids=()):
    """What stops this concern from being recorded."""
    c = concern or {}
    out = []
    if not category(c.get("category")):
        out.append("Choose what the concern is about — it decides who may see it and how quickly "
                   "somebody must reply.")
    if len(_s(c.get("detail"))) < 20:
        out.append("Say what happened, in enough detail that somebody could look into it. A line "
                   "with no facts in it cannot be investigated and will be closed unresolved.")
    if not (handler_ids or ()):
        out.append("No speak-up handler has been designated, so there is nobody this could go to. "
                   "An administrator sets that in Company Portal settings.")
    elif not handlers_for(c, handler_ids, senior_ids):
        out.append("Everybody who could handle this is named in it. Raise it outside this system, "
                   "or ask an administrator to designate a handler who is not involved — routing it "
                   "to the person it is about would be worse than not recording it.")
    return out


def summary(concerns, as_of, handler_ids=(), senior_ids=()):
    """The handler's queue, and the two numbers a supplier audit asks for."""
    today = _d(as_of) or date.today()
    live, overdue, unack, closed = [], 0, 0, 0
    by_cat = {}
    for c in (concerns or []):
        st = _s(c.get("status")) or OPEN
        d = due(c, today) or {}
        if st == CLOSED:
            closed += 1
        else:
            live.append(c)
            if d.get("overdue"):
                overdue += 1
            if not d.get("acknowledged"):
                unack += 1
        k = _s(c.get("category")) or "other"
        by_cat[k] = by_cat.get(k, 0) + 1
    total = len(concerns or [])
    return {
        "asOf": today.isoformat(), "total": total, "live": len(live),
        "closed": closed, "overdue": overdue, "unacknowledged": unack,
        "byCategory": sorted(({"category": k, "label": (category(k) or {}).get("label", k),
                               "count": v} for k, v in by_cat.items()),
                             key=lambda r: (-r["count"], r["category"])),
        # The line an auditor actually asks for.
        "statement": ("%d concern(s) raised, %d closed, %d still open, %d past the response time "
                      "the company set itself." % (total, closed, len(live), overdue)),
    }
