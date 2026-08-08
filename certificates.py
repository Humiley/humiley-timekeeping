"""Certificates, licences and health checks — what expires, and what was never obtained.

A register that lists what you hold answers half a question. The half that matters on a cleanroom
commissioning or a client audit is the other one: who is on site today without the certificate the
job requires, and whose lapsed three months ago while they kept working.

Two statutes drive the recurring ones:

  Law on Occupational Safety and Hygiene 2015, Art. 21(1)
      a periodic health examination at least ONCE a year, and at least TWICE a year — so every six
      months — for anybody on heavy, hazardous or dangerous work, and for minors, elderly workers
      and workers with disabilities.

  Decree 44/2016 (as amended by Decree 140/2018), Art. 24
      occupational safety and hygiene training. The certificate for Group 3 — workers doing jobs on
      the list with strict OSH requirements, which is most of a site crew — is valid for 2 years,
      after which refresher training is required.

Which OSH group somebody falls in is a classification the company makes against the MOLISA list, in
the same way as the working-conditions class. It is recorded on the requirement, never guessed from
a job title.

Pure — no database, no clock. Every rule is exercised by tests/test_certificates.py.
"""
from datetime import date

import datespan

# ── the recurring requirements, and how often the law wants them ─────────────────────────────────
# Months. A requirement with no interval is a one-off qualification that either expires on its own
# printed date or does not expire at all.
HEALTH_CHECK_MONTHS = 12            # Law on OSH 2015 Art. 21(1)
HEALTH_CHECK_MONTHS_HAZARD = 6      # …and twice a year for hazardous work, minors, elderly, disabled
OSH_TRAINING_MONTHS = 24            # Decree 44/2016 Art. 24, Group 3

KIND_HEALTH = "health_check"
KIND_OSH = "osh_training"
KIND_OTHER = "other"

DEFAULT_WARN_DAYS = 45              # how far ahead "expiring soon" reaches; a business choice


def _d(value):
    if isinstance(value, date):
        return value
    try:
        y, m, dd = (int(x) for x in str(value)[:10].split("-"))
        return date(y, m, dd)
    except (ValueError, AttributeError, TypeError):
        return None


def add_months(d, months):
    """The same day-of-month `months` later, clamped to a shorter month. See datespan."""
    return datespan.add_months(d, months)


def health_check_months(conditions="normal", minor=False, disabled=False, elderly=False):
    """Art. 21(1): twice a year rather than once for anybody in the listed categories."""
    if minor or disabled or elderly or str(conditions or "") in ("heavy", "especially_heavy"):
        return HEALTH_CHECK_MONTHS_HAZARD
    return HEALTH_CHECK_MONTHS


def due_date(cert, interval_months=None):
    """When a certificate stops covering the person.

    A printed expiry date always wins — it is what an inspector reads. Failing that, a recurring
    requirement expires `interval_months` after it was issued.
    """
    e = _d(cert.get("expiryDate"))
    if e:
        return e
    if interval_months:
        return add_months(cert.get("issuedDate"), interval_months)
    return None


def status(cert, as_of, interval_months=None, warn_days=DEFAULT_WARN_DAYS):
    """'valid' | 'expiring' | 'expired' | 'permanent' | 'unknown'."""
    a = _d(as_of)
    due = due_date(cert, interval_months)
    if not a:
        return "unknown"
    if not due:
        # No printed expiry and no interval: a qualification that does not lapse (a degree, a
        # trade certificate). Only honest if the certificate really is one of those.
        return "permanent" if cert.get("issuedDate") else "unknown"
    if a > due:
        return "expired"
    return "expiring" if (due - a).days <= int(warn_days or 0) else "valid"


def days_left(cert, as_of, interval_months=None):
    due, a = due_date(cert, interval_months), _d(as_of)
    if not due or not a:
        return None
    return (due - a).days


def latest(certs, kind=None):
    """The most recently ISSUED certificate of a kind — a refresher supersedes what it renews, and
    an older one being on file does not make somebody covered."""
    pool = [c for c in (certs or ()) if (kind is None or c.get("kind") == kind) and _d(c.get("issuedDate"))]
    if not pool:
        return None
    return sorted(pool, key=lambda c: str(c.get("issuedDate"))[:10])[-1]


def review(certs, as_of, conditions="normal", minor=False, disabled=False, elderly=False,
           osh_group=None, warn_days=DEFAULT_WARN_DAYS, age_known=True):
    """One person's certificate position: what they hold, what is lapsing, and what is missing.

    `osh_group` is the Decree 44/2016 group the company has classified them into. Blank means the
    safety-training requirement is not asserted for them — the register says what it knows, and
    inventing a requirement for everybody would bury the people who genuinely need one.
    """
    certs = list(certs or ())
    out = {"items": [], "issues": []}

    # An unrecorded date of birth is not the same fact as "an adult", and the cadence below is one
    # of the places the difference bites: a minor is due a health check every six months. is_minor()
    # can only answer False when it does not know, so the caller passes age_known and the gap is
    # REPORTED rather than silently resolved to the longer interval.
    if not age_known:
        out["issues"].append({
            "kind": KIND_HEALTH, "severity": "medium", "state": "unknown",
            "message": "No date of birth on record, so the health-check interval is the adult one. "
                       "Law on OSH 2015 Art. 21(1) requires every 6 months for an employee under "
                       "18. Record the date of birth."})

    hc_months = health_check_months(conditions, minor, disabled, elderly)
    required = [(KIND_HEALTH, "Periodic health examination", hc_months,
                 "Law on OSH 2015 Art. 21(1) — %s"
                 % ("every 6 months for hazardous work" if hc_months == HEALTH_CHECK_MONTHS_HAZARD
                    else "at least once a year"))]
    if osh_group:
        required.append((KIND_OSH, "Occupational safety training (group %s)" % osh_group,
                         OSH_TRAINING_MONTHS,
                         "Decree 44/2016 Art. 24 — valid 2 years, then refresher training"))

    for kind, label, months, why in required:
        held = latest(certs, kind)
        if not held:
            out["issues"].append({"kind": kind, "severity": "high", "state": "missing",
                                  "message": "No %s on file. %s" % (label.lower(), why)})
            continue
        st = status(held, as_of, months, warn_days)
        left = days_left(held, as_of, months)
        out["items"].append({"kind": kind, "label": label, "issuedDate": held.get("issuedDate"),
                             "due": str(due_date(held, months) or ""), "status": st,
                             "daysLeft": left, "hasFile": bool(held.get("file") or held.get("fileUrl"))})
        if st == "expired":
            out["issues"].append({"kind": kind, "severity": "high", "state": "expired",
                                  "message": "%s expired %d day(s) ago. %s" % (label, -left, why)})
        elif st == "expiring":
            out["issues"].append({"kind": kind, "severity": "medium", "state": "expiring",
                                  "message": "%s is due in %d day(s). %s" % (label, left, why)})

    # Everything else somebody chose to record: a welding qualification, a forklift licence, a
    # working-at-height ticket. No statutory cadence is asserted — only its own printed expiry.
    for c in certs:
        if c.get("kind") in (KIND_HEALTH, KIND_OSH):
            continue
        st = status(c, as_of, None, warn_days)
        left = days_left(c, as_of)
        out["items"].append({"kind": c.get("kind") or KIND_OTHER,
                             "label": c.get("title") or c.get("name") or "Certificate",
                             "issuedDate": c.get("issuedDate"), "due": str(due_date(c) or ""),
                             "status": st, "daysLeft": left,
                             "hasFile": bool(c.get("file") or c.get("fileUrl"))})
        if st == "expired":
            out["issues"].append({"kind": c.get("kind") or KIND_OTHER, "severity": "high",
                                  "state": "expired",
                                  "message": "%s expired %d day(s) ago."
                                             % (c.get("title") or "Certificate", -left)})
        elif st == "expiring":
            out["issues"].append({"kind": c.get("kind") or KIND_OTHER, "severity": "medium",
                                  "state": "expiring",
                                  "message": "%s is due in %d day(s)."
                                             % (c.get("title") or "Certificate", left)})
    return out
