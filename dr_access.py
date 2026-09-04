"""How a contractor with no Microsoft account gets into its own daily-report form, and nothing else.

THE SHAPE. Each contractor gets one PERMANENT link when it is created — `/dr/<token>` — which is
emailed to it and never changes. The link is not a credential: knowing it lets you ASK for access,
not submit. To submit, the person enters an email address that the contractor's setup lists, gets a
six-digit code at that address, and the confirmed device is then remembered for thirty days.

That split is the whole design, and this codebase already learned why it matters. `_coll_approve_via_link`
carries the note: *"The link no longer changes status (that let a requester self-review/approve via a
leaked token, unsigned)."* A bare token in an email is forwarded, screenshotted, left in a WhatsApp
group and indexed by whatever scans links. So a leaked daily-report link gets an attacker as far as a
form asking for an email address they cannot receive mail at.

WHAT THIS MODULE IS. Pure policy and cryptography: token minting, code hashing, the throttle, the
lockout, and the signed session. No I/O, no database, no clock of its own — `now` is always passed
in, which is what makes the expiry and lockout rules testable rather than hopeful.

THE FOUR RULES, and why each number is what it is:

  * A CODE IS SIX DIGITS AND LIVES FIFTEEN MINUTES. Six digits is 10^6; the lockout below is what
    makes that safe, not the length. Fifteen minutes is long enough to find the email on a phone on
    site and short enough that a code read over somebody's shoulder is stale by the next shift.
  * FIVE WRONG CODES LOCKS THE ADDRESS FOR FIFTEEN MINUTES. Five attempts against 10^6 is a 1-in-200,000
    chance per lockout window; without the lockout, unlimited guessing breaks a six-digit code in
    hours. The lockout is per (contractor, email), so one contractor cannot lock another out.
  * THREE CODE REQUESTS PER FIFTEEN MINUTES. Not for guessing — for the mailbox. Without it, the
    endpoint is an open relay pointed at whatever address the contractor's setup lists.
  * THE ANSWER NEVER SAYS WHETHER THE ADDRESS IS AUTHORISED. "If that address is on this
    contractor's list, a code is on its way" is returned either way. Otherwise the form is an
    oracle: try addresses, and the ones that get a different answer are the site staff — a list
    worth having if you want to phish somebody into submitting a false report.
"""
import base64
import hashlib
import hmac
import re
import secrets
import time

# ── policy ───────────────────────────────────────────────────────────────────────────────────────
TOKEN_BYTES = 24            # 192 bits: not guessable, and short enough to survive an email client
CODE_DIGITS = 6
CODE_TTL = 15 * 60          # seconds a code stays usable
CODE_MAX_ATTEMPTS = 5       # wrong codes before the address is locked
CODE_LOCKOUT = 15 * 60      # how long a lockout lasts
CODE_MAX_SENDS = 3          # code requests allowed per window, per (contractor, email)
CODE_SEND_WINDOW = 15 * 60
SESSION_TTL = 30 * 24 * 3600    # a confirmed device is remembered for thirty days
SESSION_SLIDE = 7 * 24 * 3600   # re-issued when less than a week is left, so daily use never expires
PBKDF2_ROUNDS = 120_000     # the same order as the e-signature PIN; a code lives 15 min, not forever

COOKIE = "drsite"


# ── the permanent link ───────────────────────────────────────────────────────────────────────────
def new_token():
    """The contractor's permanent form token. URL-safe, no padding, no characters an email client
    will wrap or a person will mistranscribe when reading it off a screen."""
    return base64.urlsafe_b64encode(secrets.token_bytes(TOKEN_BYTES)).decode("ascii").rstrip("=")


def valid_token(token):
    return bool(re.fullmatch(r"[A-Za-z0-9_-]{16,64}", str(token or "")))


def form_url(base_url, token):
    """The link that goes in the email. `base_url` has no trailing slash."""
    return "%s/dr/%s" % (str(base_url or "").rstrip("/"), token)


# ── email addresses ──────────────────────────────────────────────────────────────────────────────
def norm_email(value):
    return str(value or "").strip().lower()


def parse_emails(value):
    """The contractor's authorised addresses, from a comma / semicolon / newline separated field.

    Deduplicated and lower-cased so "Site@x.com " and "site@x.com" are one address — otherwise the
    same person could hold two independent lockout counters and the throttle would be worth half of
    what it says.
    """
    if isinstance(value, (list, tuple, set)):
        parts = [str(x) for x in value]
    else:
        parts = re.split(r"[,;\n]", str(value or ""))
    out = []
    for p in parts:
        e = norm_email(p)
        if e and looks_like_email(e) and e not in out:
            out.append(e)
    return out


def looks_like_email(value):
    """Deliberately loose. This is not validation of deliverability — it only keeps obvious rubbish
    out of the allow-list, and a real address that this rejected would lock somebody out of their
    own form for a reason nobody could see."""
    return bool(re.fullmatch(r"[^@\s]+@[^@\s]+\.[^@\s]+", str(value or "").strip()))


def email_allowed(contractor, email):
    return norm_email(email) in parse_emails((contractor or {}).get("emails"))


# ── the code ─────────────────────────────────────────────────────────────────────────────────────
def new_code():
    """A six-digit code, uniformly random, leading zeros kept.

    `secrets.randbelow` rather than `randint` on a module-level Random: this is a credential, and the
    default RNG is seeded and predictable.
    """
    return "%0*d" % (CODE_DIGITS, secrets.randbelow(10 ** CODE_DIGITS))


def hash_code(code, salt=None, rounds=PBKDF2_ROUNDS):
    """(salt_hex, hash_hex, rounds). The code is never stored — a leaked database must not hand
    somebody a live code, and the codes are short enough to be looked up in a rainbow table if they
    were stored as a plain digest."""
    s = salt or secrets.token_bytes(16)
    if isinstance(s, str):
        s = bytes.fromhex(s)
    dk = hashlib.pbkdf2_hmac("sha256", str(code).encode("utf-8"), s, rounds)
    return s.hex(), dk.hex(), rounds


def code_matches(code, salt_hex, hash_hex, rounds):
    """Constant-time comparison. A timing side channel on a six-digit code is not theoretical when
    the endpoint is public and the attacker controls the request rate."""
    try:
        _s, got, _r = hash_code(code, salt_hex, int(rounds or PBKDF2_ROUNDS))
    except (ValueError, TypeError):
        return False
    return hmac.compare_digest(got, str(hash_hex or ""))


# ── the throttle and the lockout ─────────────────────────────────────────────────────────────────
def send_allowed(access, now=None):
    """May this (contractor, email) be sent another code? (bool, seconds_to_wait).

    Counts sends inside a rolling window rather than since some reset, so three requests a minute
    apart cannot be turned into six by waiting for a boundary.
    """
    now = float(now if now is not None else time.time())
    sends = [float(t) for t in ((access or {}).get("sends") or []) if _isnum(t)]
    recent = [t for t in sends if now - t < CODE_SEND_WINDOW]
    if len(recent) < CODE_MAX_SENDS:
        return True, 0
    return False, int(CODE_SEND_WINDOW - (now - min(recent))) + 1


def record_send(access, now=None):
    """The access row after a code has been sent. Old timestamps are dropped so the row cannot grow
    without bound on a contractor that requests a code every day for two years."""
    now = float(now if now is not None else time.time())
    sends = [float(t) for t in ((access or {}).get("sends") or []) if _isnum(t)]
    sends = [t for t in sends if now - t < CODE_SEND_WINDOW] + [now]
    out = dict(access or {})
    out["sends"] = sends[-CODE_MAX_SENDS * 2:]
    return out


def locked_for(access, now=None):
    """Seconds remaining on a lockout, or 0."""
    now = float(now if now is not None else time.time())
    until = (access or {}).get("lockedUntil")
    if not _isnum(until):
        return 0
    return max(0, int(float(until) - now))


def check_code(access, code, now=None):
    """Verify a code against the access row.

    Returns (ok, reason, new_access). `reason` is one of "" / "locked" / "expired" / "wrong" /
    "none" — the CALLER decides what to tell the person, because the honest answer to the user and
    the precise answer for the log are not the same sentence.

    A correct code clears the failure count AND the stored hash: a code is single-use, so replaying
    a confirmation email cannot re-authorise a device later.
    """
    now = float(now if now is not None else time.time())
    acc = dict(access or {})
    if locked_for(acc, now):
        return False, "locked", acc
    if not acc.get("codeHash"):
        return False, "none", acc
    if not _isnum(acc.get("codeExpires")) or float(acc["codeExpires"]) < now:
        return False, "expired", acc
    if code_matches(code, acc.get("codeSalt"), acc.get("codeHash"), acc.get("codeRounds")):
        for k in ("codeHash", "codeSalt", "codeRounds", "codeExpires"):
            acc.pop(k, None)
        acc["fails"] = 0
        acc.pop("lockedUntil", None)
        acc["confirmedAt"] = now
        return True, "", acc
    fails = int(acc.get("fails") or 0) + 1
    acc["fails"] = fails
    if fails >= CODE_MAX_ATTEMPTS:
        acc["lockedUntil"] = now + CODE_LOCKOUT
        # The code goes with the lockout. Otherwise waiting out the lockout resumes guessing against
        # the SAME code, and the attempt limit becomes five per fifteen minutes forever rather than
        # five per code.
        for k in ("codeHash", "codeSalt", "codeRounds", "codeExpires"):
            acc.pop(k, None)
    return False, "wrong", acc


def issue_code(access, code, now=None):
    """The access row carrying a freshly issued code. Clears any previous one — asking for a second
    code must invalidate the first, or two live codes double the guessing surface."""
    now = float(now if now is not None else time.time())
    salt, h, rounds = hash_code(code)
    acc = record_send(access, now)
    acc.update({"codeSalt": salt, "codeHash": h, "codeRounds": rounds,
                "codeExpires": now + CODE_TTL, "fails": 0})
    acc.pop("lockedUntil", None)
    return acc


def attempts_left(access):
    return max(0, CODE_MAX_ATTEMPTS - int((access or {}).get("fails") or 0))


# ── the remembered device ────────────────────────────────────────────────────────────────────────
def derive_secret(pepper):
    """A key for THIS purpose only, from a secret the server already has.

    Derived rather than reused directly so a daily-report session cookie can never be replayed
    against anything else the same pepper signs, and so this needs no new environment variable to
    work on a server that is already configured.
    """
    if not pepper:
        raise ValueError("no server secret available to sign contractor sessions with")
    return hmac.new(_b(pepper), b"dr-access-v1", hashlib.sha256).digest()


def sign_session(secret, contractor_id, email, now=None, ttl=SESSION_TTL):
    """A signed, self-contained cookie value: contractor, address, expiry.

    Self-contained on purpose — no server-side session table. The portal's own sessions live in
    memory and are lost on restart, and a site crew being logged out of their form every deploy is
    the kind of friction that ends with somebody emailing the report instead.
    """
    now = int(now if now is not None else time.time())
    exp = now + int(ttl)
    body = "%s|%s|%d" % (str(contractor_id), norm_email(email), exp)
    raw = base64.urlsafe_b64encode(body.encode("utf-8")).decode("ascii").rstrip("=")
    mac = hmac.new(secret, raw.encode("ascii"), hashlib.sha256).digest()
    return raw + "." + base64.urlsafe_b64encode(mac).decode("ascii").rstrip("=")[:43]


def verify_session(secret, cookie, now=None):
    """{"contractorId", "email", "expires", "renew"} or None.

    `renew` says the cookie is inside its sliding window and should be re-issued, so a crew using
    the form daily is never logged out while one idle for a month is.
    """
    now = int(now if now is not None else time.time())
    try:
        raw, _dot, mac = str(cookie or "").partition(".")
        if not raw or not mac:
            return None
        want = hmac.new(secret, raw.encode("ascii"), hashlib.sha256).digest()
        want_b = base64.urlsafe_b64encode(want).decode("ascii").rstrip("=")[:43]
        if not hmac.compare_digest(mac, want_b):
            return None
        body = base64.urlsafe_b64decode(raw + "=" * (-len(raw) % 4)).decode("utf-8")
        cid, email, exp = body.rsplit("|", 2)
        exp = int(exp)
    except (ValueError, TypeError, UnicodeDecodeError):
        return None
    if exp <= now:
        return None
    return {"contractorId": cid, "email": email, "expires": exp,
            "renew": (exp - now) < SESSION_SLIDE}


# ── what the person is told ──────────────────────────────────────────────────────────────────────
# One sentence for every outcome of asking for a code, and the SAME sentence whether or not the
# address is on the list. See the module docstring: a different answer for an unknown address turns
# the form into a way of discovering who the site staff are.
SENT_MESSAGE = ("If that address is on this contractor's list, a six-digit code is on its way. "
                "It is good for 15 minutes.")


def code_failure_message(reason, wait_s=0):
    """What to show for a rejected code. Deliberately does not distinguish "no code was ever issued"
    from "the code expired" — both mean ask for a new one, and telling them apart tells an attacker
    whether an address has a code outstanding."""
    if reason == "locked":
        mins = max(1, int(wait_s / 60 + 0.5))
        return ("Too many wrong codes. Try again in about %d minute%s, or ask for a new code then."
                % (mins, "" if mins == 1 else "s"))
    if reason == "wrong":
        return "That code is not right."
    return "That code has expired. Ask for a new one."


def _isnum(v):
    try:
        float(v)
        return True
    except (TypeError, ValueError):
        return False


def _b(v):
    return v if isinstance(v, bytes) else str(v).encode("utf-8")
