"""Cutting off access when somebody leaves — what has to happen, when, and what is still open.

The offboarding checklist already had a line reading "IT: disable email account". Somebody ticked it.
Nothing checked. That is the shape of almost every real offboarding failure: not a refusal, a
tick-box that nobody could contradict, and an account that still works eighteen months later.

Two things this module exists to get right.

**Timing.** An exit is recorded when the resignation lands — thirty days before the last working day.
Revoking on the day HR types it in would lock somebody out of their notice period. Revoking "when we
get round to it" is the failure above. So revocation is DUE at the end of the last working day, may
be done EARLY with a stated reason (a dismissal for cause does not serve notice), and is OVERDUE from
the day after. Overdue is the number the company should be looking at.

**Completeness.** Deactivating the portal account is the easy half and the half that was already
done. The half that matters is Microsoft 365 — the mailbox, the files, the Teams history. Blocking
sign-in is not enough on its own either: an issued refresh token keeps working for its lifetime, so
the sessions have to be revoked as well, and in that order.

Everything here is pure. Whether Graph answered is the server's problem; whether the answer means the
company is exposed is this module's.
"""
from datetime import date

import datespan

# ── what has to happen ───────────────────────────────────────────────────────────────────────────
# `auto` — the portal can do it itself. `needs` — the Graph application permission it requires, so a
# preview can say "this is not consented" instead of failing at the moment somebody presses the
# button. `exposure` — what is still open while the step is outstanding, in the words of the risk
# rather than the words of the API.

STEPS = [
    {"key": "portal", "system": "portal", "auto": True,
     "label": "Portal account deactivated",
     "exposure": "They can still sign in to the portal and read HR, payroll and project records."},
    {"key": "portal_sessions", "system": "portal", "auto": True,
     "label": "Portal sign-in sessions ended",
     "exposure": "A phone already signed in stays signed in for up to thirty days."},
    {"key": "portal_pin", "system": "portal", "auto": True,
     "label": "E-signature credential revoked",
     "exposure": "They can still put a legally binding signature on a company document."},
    {"key": "portal_push", "system": "portal", "auto": True,
     "label": "Push notifications stopped",
     "exposure": "Their phone keeps receiving approval and payroll notifications."},
    # `needsAny` is a list of ALTERNATIVE permission sets — the step can run if the app holds every
    # permission in ANY ONE of them. It is not one name, because Microsoft does not offer one name.
    #
    # I first shipped both of these as `needs: "User.ReadWrite.All"` and that was wrong twice over.
    # For revokeSignInSessions the Application row of Microsoft's own permissions table reads
    # "User.RevokeSessions.All" as least privileged and "Not available." for higher privileged —
    # User.ReadWrite.All is a DELEGATED-only answer there. The portal would have reported the step as
    # runnable, the owner would have granted the wrong permission, and the button would have 403'd on
    # the day somebody left: precisely the failure this design exists to prevent.
    {"key": "m365_sessions", "system": "m365", "auto": True,
     "needsAny": [["User.RevokeSessions.All"]],
     "label": "Microsoft 365 sign-in sessions revoked",
     "exposure": "Mail and Teams keep working on any device already signed in, for the life of the "
                 "refresh token — blocking the account alone does not stop this."},
    # Blocking sign-in is a "sensitive action": a Graph permission is necessary and NOT sufficient.
    # Microsoft requires an app-only caller to ALSO hold a privileged directory role. That role is not
    # in the token's `roles` claim, so no amount of reading the token can confirm it — which is why it
    # is carried as a caveat that is always shown rather than a check that would quietly pass.
    {"key": "m365_account", "system": "m365", "auto": True,
     "needsAny": [["User.EnableDisableAccount.All", "User.Read.All"],
                  ["User.ReadWrite.All"],
                  ["Directory.ReadWrite.All"]],
     "roleCaveat": "Microsoft also requires the app itself to hold a privileged directory role (User "
                   "Administrator is enough for ordinary staff). That role is not visible in the "
                   "token, so the portal cannot confirm it here — if it is missing, this step fails "
                   "with Authorization_RequestDenied and says so.",
     "label": "Microsoft 365 sign-in blocked",
     "exposure": "They can sign in to email, SharePoint and Teams with their existing password."},
    {"key": "m365_mailbox", "system": "manual", "auto": False,
     "label": "Mailbox delegated to their manager",
     "exposure": "Customer mail sent to their address is not being read by anybody."},
    {"key": "m365_licence", "system": "manual", "auto": False,
     "label": "Microsoft 365 licence released",
     "exposure": "The company is paying a monthly licence for somebody who has left."},
]

STEP_BY_KEY = {s["key"]: s for s in STEPS}

# Sessions before the account block. Reversing this leaves a window in which the account is blocked
# but the issued tokens have not been invalidated, and Graph refuses to revoke sessions for a
# disabled user in some tenants — which would leave the tokens live with no way to reach them.
ORDER = ["m365_sessions", "m365_account"]


def _d(value):
    return datespan.to_date(value)


def due_on(exit_rec):
    """Revocation is due at the END of the last working day."""
    return _d((exit_rec or {}).get("lastDay"))


def overdue_days(exit_rec, today=None):
    """Days past the last working day. Zero on the day itself — that day is still theirs."""
    due, t = due_on(exit_rec), _d(today) or date.today()
    if not due:
        return 0
    return max(0, (t - due).days)


def is_early(exit_rec, today=None):
    """Before the end of the last working day, revoking cuts somebody off mid-notice. Allowed — a
    dismissal for cause does not serve notice — but it is a decision, so it needs a reason."""
    due, t = due_on(exit_rec), _d(today) or date.today()
    return bool(due) and t <= due


def done_map(exit_rec):
    """What the record says has already been done. Shape: {key: {"at":…, "by":…, "note":…}}."""
    raw = (exit_rec or {}).get("revoked")
    return dict(raw) if isinstance(raw, dict) else {}


def missing_permissions(step, granted_roles):
    """Which permissions are still needed for this step, or [] if it can run.

    A step may be satisfied by any one of several alternative sets. When none is satisfied we report
    the set that is CLOSEST to complete — telling somebody to grant Directory.ReadWrite.All when they
    are one granular permission away from the least-privileged answer is bad advice.
    """
    alts = step.get("needsAny") or []
    if not alts:
        return []
    have = set(granted_roles or [])
    gaps = [[p for p in alt if p not in have] for alt in alts]
    if any(not g for g in gaps):
        return []
    return min(gaps, key=len)


def plan(exit_rec, today=None, granted_roles=None, m365_configured=True):
    """The full picture for one leaver: every step, whether it is done, and what is blocking it."""
    roles = set(granted_roles or [])
    done = done_map(exit_rec)
    due, t = due_on(exit_rec), _d(today) or date.today()
    steps = []
    for s in STEPS:
        rec = done.get(s["key"]) if isinstance(done.get(s["key"]), dict) else None
        row = dict(s, done=bool(rec and rec.get("at")), at=(rec or {}).get("at", ""),
                   by=(rec or {}).get("by", ""), note=(rec or {}).get("note", ""))
        # `blocked` is the English prose an API consumer or a log reader gets; `blockedCode` is the
        # same fact as a token, so the UI can say it in the reader's own language instead of shipping
        # a sentence with a permission name glued into the middle of it.
        row["blocked"], row["blockedCode"], row["missing"] = "", "", []
        if s["system"] == "m365" and not row["done"]:
            if not m365_configured:
                row["blockedCode"] = "unconfigured"
                row["blocked"] = "Microsoft 365 is not connected in Company Portal settings."
            else:
                missing = missing_permissions(s, roles)
                if missing:
                    row["blockedCode"] = "consent"
                    row["missing"] = missing
                    row["blocked"] = ("The portal's app registration has not been granted %s, so it "
                                      "cannot do this." % " + ".join(missing))
        steps.append(row)

    outstanding = [s for s in steps if not s["done"]]
    auto_left = [s for s in outstanding if s["auto"] and not s["blocked"]]
    return {
        "dueOn": due.isoformat() if due else "",
        "today": t.isoformat(),
        "overdueDays": overdue_days(exit_rec, t),
        "early": is_early(exit_rec, t),
        "steps": steps,
        "outstanding": [s["key"] for s in outstanding],
        "canRunNow": [s["key"] for s in auto_left],
        "state": state(steps, exit_rec, t),
    }


def state(steps, exit_rec, today=None):
    """One word for the register. `exposed` is the one that should never be sitting there."""
    outstanding = [s for s in steps if not s["done"]]
    if not outstanding:
        return "complete"
    if not due_on(exit_rec):
        return "nodate"
    if overdue_days(exit_rec, today) > 0:
        # Anything still open after the last working day is live access for somebody who has left.
        return "exposed"
    return "scheduled"


def runnable(exit_rec, keys=None, granted_roles=None, m365_configured=True):
    """The steps to attempt now, in the order they must be attempted."""
    p = plan(exit_rec, granted_roles=granted_roles, m365_configured=m365_configured)
    want = set(keys) if keys else set(p["canRunNow"])
    out = [k for k in ORDER if k in want and k in p["canRunNow"]]
    out += [k for k in p["canRunNow"] if k in want and k not in ORDER]
    return out


def record(exit_rec, key, actor, note="", at=None, ok=True):
    """Stamp one step's result onto the exit record. A failure is recorded as a failure — it does not
    silently leave the step looking untouched, because "we tried and Graph said no" is the thing HR
    has to chase, and it is not the same as "nobody has been here yet"."""
    rec = dict(exit_rec or {})
    box = dict(done_map(rec))
    entry = {"by": actor or "", "note": note or ""}
    if ok:
        entry["at"] = at or ""
    else:
        entry["at"] = ""
        entry["failed"] = at or ""
    box[key] = entry
    rec["revoked"] = box
    return rec


# ── the chase list ───────────────────────────────────────────────────────────────────────────────

def review(people, today=None):
    """Everybody whose access should be shut and is not, worst first.

    `people` is assembled by the caller — one dict per person the company has any reason to think has
    left, with what is actually live rather than what a checklist claims:

        {"empId", "name", "dept", "status", "endDate", "lastDay", "exitId", "exitStatus",
         "revoked": {...}, "live": {"pin": bool, "push": int, "m365": True|False|None}}

    The reverse check matters as much as the forward one. An exit record with every box ticked proves
    nothing; an account that still answers proves everything. `live.m365` is None when the tenant
    could not be asked, and that is reported as unknown rather than as clear.
    """
    t = _d(today) or date.today()
    rows = []
    for p in (people or []):
        p = dict(p or {})
        live = dict(p.get("live") or {})
        gone_on = _d(p.get("lastDay")) or _d(p.get("endDate"))
        inactive = str(p.get("status") or "Active").strip().lower() == "inactive"
        # Somebody counts as departed once their last day has passed, or once the portal says they
        # are inactive — either is enough to expect their access to be shut.
        departed = bool(inactive or (gone_on and gone_on < t))
        if not departed:
            continue

        findings = []
        if not inactive:
            findings.append(("portal", "Their portal account is still active."))
        if live.get("pin"):
            findings.append(("portal_pin", "Their e-signature credential still works."))
        if int(live.get("push") or 0) > 0:
            findings.append(("portal_push", "Their phone is still subscribed to company notifications."))
        if live.get("m365") is True:
            findings.append(("m365_account", "Their Microsoft 365 account can still sign in."))
        elif live.get("m365") is None:
            findings.append(("m365_unknown", "Microsoft 365 could not be checked, so their mail and "
                                             "files may still be reachable."))
        if not p.get("exitId"):
            findings.append(("norecord", "There is no exit record for them at all — nothing was "
                                         "offboarded through the portal."))

        if not findings:
            continue
        days = max(0, (t - gone_on).days) if gone_on else 0
        rows.append({
            "empId": p.get("empId") or "", "name": p.get("name") or "", "dept": p.get("dept") or "",
            "goneOn": gone_on.isoformat() if gone_on else "",
            "daysSince": days,
            "exitId": p.get("exitId") or "",
            "findings": [{"key": k, "why": w} for k, w in findings],
            "severity": _severity(findings),
        })
    rows.sort(key=lambda r: (-_SEV_RANK.get(r["severity"], 0), -r["daysSince"], r["name"]))
    return rows


_SEV_RANK = {"open": 3, "unknown": 2, "residual": 1}

# Splitting these apart is the difference between a list somebody acts on and a list somebody stops
# reading. A live mailbox is not the same finding as a leftover push subscription, and if both are
# painted red the red stops meaning anything.
_OPEN = {"portal", "m365_account", "norecord"}
_UNKNOWN = {"m365_unknown"}


def _severity(findings):
    keys = {k for k, _ in findings}
    if keys & _OPEN:
        return "open"
    if keys & _UNKNOWN:
        return "unknown"
    return "residual"


def summary(rows):
    out = {"open": 0, "unknown": 0, "residual": 0, "total": len(rows or []), "oldestDays": 0}
    for r in (rows or []):
        out[r["severity"]] = out.get(r["severity"], 0) + 1
        out["oldestDays"] = max(out["oldestDays"], int(r.get("daysSince") or 0))
    return out
