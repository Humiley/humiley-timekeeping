"""Who should be told, and what to tell them, when production goes wrong.

A board that shows a failed test is only useful to someone who is looking at it. The three events
that stop a line are a failed step, a gate held, and a non-conformance that has sat open too long —
and in each case there is a specific person whose day changes, named on the unit or its order.

Pure: decides recipients by ROLE NAME and composes the message. It does not know what an email
address is, does not touch the database and does not send anything. app.py resolves the names to
people and hands them to the push stack.

── The thing this module refuses to do quietly ──────────────────────────────────────────────────

A notification aimed at a name that matches no employee is a notification nobody receives, and the
sending code has no way to tell that apart from success — `_tk_push` returns a count and a count of
zero looks exactly like "nobody had push enabled". So `recipients()` returns the names it chose and
`unresolved()` names the ones that could not be turned into a person, and the caller records both.
An alert routed to a misspelled role holder must be visible as a gap, not absorbed as a zero.
"""

# Which named roles hear about each event. Deliberately narrow: an alert that reaches everybody is
# an alert nobody reads, and the second-order effect of over-notifying is that the real one is
# dismissed with the rest.
STEP_FAILED_ROLES = ("qcInspector", "qaManager", "productionLead")
GATE_HELD_ROLES = ("productionLead", "qaManager", "salesOwner")
NCR_AGING_ROLES = ("qaManager", "qcInspector", "productionLead")

# A non-conformance is "aging" after this many days open. The SOP sets no number, so this is a
# portal default and is stated as one — it is configurable per deployment (setting
# `ahu_ncr_aging_days`) rather than presented as something the standard requires.
NCR_AGING_DAYS_DEFAULT = 5

FAILED = "step-failed"
HELD = "gate-held"
AGING = "ncr-aging"


def _s(v):
    return str(v or "").strip()


def recipients(ctx, roles):
    """The distinct person-names holding any of `roles` on this unit or its order, in order.

    Order is stable and duplicates are dropped, because the same person is frequently both the QC
    inspector and the QA manager on a small job and should be told once.
    """
    out, seen = [], set()
    for src in ((ctx or {}).get("unit") or {}, (ctx or {}).get("order") or {}):
        for f in roles:
            n = _s(src.get(f))
            if n and n.lower() not in seen:
                seen.add(n.lower())
                out.append(n)
    return out


def unresolved(chosen, resolved):
    """The names `recipients()` chose that the caller could not turn into a person.

    `resolved` is the subset the caller matched. Returned so a role holder spelled in a way the
    employee register does not recognise shows up as a named gap — a silently empty send is the
    failure this whole module is here to avoid.
    """
    have = {_s(r).lower() for r in (resolved or [])}
    return [n for n in (chosen or []) if _s(n).lower() not in have]


# ── The three events ─────────────────────────────────────────────────────────────────────────────

def step_failed(ctx, step, failures=None):
    """A workstation, hold point or test recorded a failing result.

    `failures` is ahu_route.evaluate_step(...)["failures"] — the SAME judgements that refused the
    sign-off. Composing the message from them rather than re-deriving it means the alert cannot
    disagree with the decision: "IPQC-2 failed" sends someone to a screen, and "panel density: 38
    kg/m3 (minimum 42, IPQC-2-001)" sends them to the foam line.
    """
    unit = (ctx or {}).get("unit") or {}
    pin = _s(unit.get("pin")) or _s(unit.get("id")) or "an AHU"
    code = _s((step or {}).get("code"))
    title = _s((step or {}).get("title"))
    body = " ".join(("%s %s failed on %s." % (code, ("— " + title) if title else "", pin)).split())
    why = _failure_sentence(failures)
    if why:
        body += " " + why
    return {"event": FAILED, "roles": STEP_FAILED_ROLES,
            "title": "Production failure — " + pin,
            "body": body, "url": _unit_url(unit), "tag": "ahu-fail-" + (unit.get("id") or "") + code}


def _failure_sentence(failures):
    """The out-of-limit checks as one short sentence. '' when the caller passed none.

    Each judgement already carries the evaluator's own wording, including the limit it applied and
    where that limit came from. Re-phrasing it here would create a second, unverified account of the
    same measurement.
    """
    bad = []
    for r in (failures or []):
        if not isinstance(r, dict):
            continue
        label = _s(r.get("label")) or _s(r.get("key")) or "check"
        msg = _s(r.get("message"))
        bad.append(("%s: %s" % (label, msg)) if msg else label)
    if not bad:
        return ""
    return "; ".join(bad[:3]) + ("…" if len(bad) > 3 else "")


def gate_held(ctx, step, blockers):
    """A stage gate could not be passed. The blockers ARE the message.

    Whoever is being told needs to know what to go and fix, and the gate check already computed
    exactly that list — repeating it here rather than sending them to look it up is the difference
    between a notification and an interruption.
    """
    unit = (ctx or {}).get("unit") or {}
    pin = _s(unit.get("pin")) or _s(unit.get("id")) or "an AHU"
    code = _s((step or {}).get("code"))
    items = [_s(b) for b in (blockers or []) if _s(b)]
    body = "%s is held on %s." % (code, pin)
    if items:
        body += " " + "; ".join(items[:3]) + ("…" if len(items) > 3 else "")
    return {"event": HELD, "roles": GATE_HELD_ROLES,
            "title": "Gate held — " + pin,
            "body": body, "url": _unit_url(unit), "tag": "ahu-hold-" + (unit.get("id") or "") + code}


def ncr_aging(ctx, ncr, age_days, threshold):
    """A non-conformance has been open longer than the configured threshold.

    The threshold is passed in rather than read here, so the number in the message is provably the
    same number that decided to send it.
    """
    unit = (ctx or {}).get("unit") or {}
    pin = _s(unit.get("pin")) or _s(unit.get("id")) or "an AHU"
    ref = _s((ncr or {}).get("ncrNo")) or _s((ncr or {}).get("id")) or "An NCR"
    desc = _s((ncr or {}).get("description"))[:110]
    body = "%s on %s has been open %d days (threshold %d)." % (ref, pin, age_days, threshold)
    if desc:
        body += " " + desc
    return {"event": AGING, "roles": NCR_AGING_ROLES,
            "title": "Non-conformance aging — " + pin,
            "body": body, "url": _unit_url(unit),
            "tag": "ahu-ncr-" + _s((ncr or {}).get("id"))}


def _unit_url(unit):
    uid = _s((unit or {}).get("id"))
    return ("/?ahu=" + uid) if uid else "/"


def aging_threshold(setting_value):
    """The configured aging threshold in days, or the stated default.

    A bad or absent setting falls back to the documented default rather than to zero — a zero here
    would declare every non-conformance aging the moment it was raised, which is the fastest way to
    train people to ignore the alert.
    """
    try:
        n = int(setting_value)
    except (TypeError, ValueError):
        return NCR_AGING_DAYS_DEFAULT
    return n if n > 0 else NCR_AGING_DAYS_DEFAULT
