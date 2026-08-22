"""What measured the number, and whether it was fit to.

Every test in AHU-SOP-MASTER-001 section 11 is a measurement. T2 pressurises a casing and measures
relative deflection; T3 blanks it off and measures a leakage rate; T7 applies a test voltage and
measures insulation resistance. Each of those readings then carries a 21 CFR Part 11 signature
attesting to a number — and until now nothing recorded WHAT produced the number, or whether that
thing was in calibration when it did.

Two things follow from that, and the second is the worse one.

An auditor asks for calibration certificates in the first hour of any ISO 9001 or client audit, and
there was nothing to show. That is embarrassing but survivable.

The other is not: when an instrument IS found out of calibration — which is how calibration works,
you discover it at the next check — you have to identify every measurement it produced since it was
last known good. Without a register that question has no answer, and the honest response is to
re-test everything the instrument might have touched. `affected_steps()` exists to make that a query
instead.

Pure: dates in, verdicts out. No database, no clock — the caller passes `on_date`, so a test can ask
what the answer was on a Tuesday in June.

── What this refuses to assume ──────────────────────────────────────────────────────────────────

An instrument with no calibration due date is UNKNOWN, never valid. "We have no record" and "it is
in calibration" are opposite claims, and defaulting the first to the second would put a clean status
on exactly the instruments nobody is looking after.
"""
from datetime import datetime, timedelta

VALID = "VALID"
DUE_SOON = "DUE_SOON"
EXPIRED = "EXPIRED"
UNKNOWN = "UNKNOWN"          # registered, but no due date recorded
NOT_FOUND = "NOT_FOUND"      # a step names an instrument that is not in the register

# How long before the due date an instrument starts being reported as due soon. A portal default,
# stated as one: the SOP sets no figure, and the interval between calibrations is the calibration
# lab's business, not this module's.
DUE_SOON_DAYS = 30


def _d(v):
    """A date, or None. Never raises, never guesses a format that is not ISO."""
    try:
        return datetime.strptime(str(v or "")[:10], "%Y-%m-%d").date()
    except (TypeError, ValueError):
        return None


def status(instrument, on_date, due_soon_days=DUE_SOON_DAYS):
    """Where this instrument stood on `on_date`.

    Returns {status, dueOn, daysLeft, why}. `daysLeft` is negative once the due date has passed,
    which is what makes "how long has this been wrong" answerable without a second call.
    """
    on = _d(on_date)
    if instrument is None:
        return {"status": NOT_FOUND, "dueOn": None, "daysLeft": None,
                "why": "No such instrument in the register."}
    due = _d(instrument.get("calDue"))
    if not due or not on:
        return {"status": UNKNOWN, "dueOn": instrument.get("calDue") or None, "daysLeft": None,
                "why": ("This instrument has no calibration due date recorded. That is not the same "
                        "as being in calibration.")}
    days = (due - on).days
    if days < 0:
        st, why = EXPIRED, "Calibration was due on %s, %d day(s) before this." % (due.isoformat(),
                                                                                 -days)
    elif days <= due_soon_days:
        st, why = DUE_SOON, "Calibration is due on %s, in %d day(s)." % (due.isoformat(), days)
    else:
        st, why = VALID, "In calibration until %s." % due.isoformat()
    return {"status": st, "dueOn": due.isoformat(), "daysLeft": days, "why": why}


def index(instruments):
    """The register keyed by id, for the lookups below."""
    return {str(i.get("id")): i for i in (instruments or []) if i.get("id")}


# ── The check applied when somebody signs a test ────────────────────────────────────────────────

def check_step(step, instruments_by_id, on_date, require_named=False):
    """Why this step may not be signed on calibration grounds, or None.

    Deliberately graduated, because turning this on must not stop a factory that has not finished
    entering its register yet:

      * An instrument that is NAMED and EXPIRED always refuses. Signing a measurement to an
        instrument known to be out of calibration produces a record asserting something the company
        cannot stand behind, and that is not a specification choice — it is whether the evidence is
        evidence.
      * An instrument that is NAMED but not in the register always refuses. A free-typed id that
        matches nothing is indistinguishable from a typo, and a typo here silently detaches a
        measurement from its provenance.
      * NO instrument named refuses only when `require_named` is on. Off by default, so the register
        can be populated before the rule is enforced; the board reports the gap either way.

    UNKNOWN and DUE_SOON do not refuse. An instrument whose due date nobody recorded is a records
    problem to chase, not a reason to stop the line mid-test — and it is reported, loudly, by
    `register_gaps`.
    """
    ref = str((step or {}).get("instrumentId") or "").strip()
    if not ref:
        if require_named:
            return ("This test does not say which instrument took the reading. Record the "
                    "instrument before signing — a measurement with no traceable instrument cannot "
                    "be defended in an audit.")
        return None
    inst = (instruments_by_id or {}).get(ref)
    s = status(inst, on_date)
    if s["status"] == NOT_FOUND:
        return ("Instrument %s is not in the calibration register. Register it, or correct the "
                "reference — an id that matches nothing is a measurement with no provenance." % ref)
    if s["status"] == EXPIRED:
        return ("Instrument %s (%s) was out of calibration: %s Re-calibrate it, or record the "
                "reading against an instrument that was in calibration."
                % (ref, inst.get("name") or inst.get("type") or "unnamed", s["why"]))
    return None


# ── The question a failed calibration asks ──────────────────────────────────────────────────────

def affected_steps(instrument, steps, signed_only=True):
    """Every step this instrument measured while it was, on its own record, out of calibration.

    The date each step is judged on is the date it was SIGNED, because that is the only instant a
    step records. A reading taken on Monday and signed on Wednesday is judged on Wednesday, which
    can only over-report — it will never call a suspect measurement clean. Stated here because a
    recall list that quietly under-reports is worse than none.
    """
    due = _d((instrument or {}).get("calDue"))
    iid = str((instrument or {}).get("id") or "")
    out = []
    for s in (steps or []):
        if str(s.get("instrumentId") or "").strip() != iid or not iid:
            continue
        when = _d(s.get("signedOn")) or _sig_date(s)
        if signed_only and not when:
            continue
        row = {"stepId": s.get("id"), "unitId": s.get("unitId"), "code": s.get("code"),
               "signedOn": when.isoformat() if when else None, "signedBy": s.get("signedBy")}
        if due and when and when > due:
            row["suspect"] = True
            row["why"] = "Signed %d day(s) after calibration was due on %s." % ((when - due).days,
                                                                                due.isoformat())
        else:
            row["suspect"] = False
            row["why"] = ("Signed on or before the calibration due date." if due and when
                          else "No calibration due date on the instrument, so this cannot be judged.")
        out.append(row)
    return out


def _sig_date(step):
    for sig in reversed((step or {}).get("signatures") or []):
        d = _d(sig.get("ts"))
        if d:
            return d
    return None


# ── What the register itself is missing ─────────────────────────────────────────────────────────

def register_gaps(instruments, on_date, due_soon_days=DUE_SOON_DAYS):
    """Instruments that are expired, due soon, or have no due date at all.

    The third group is the one that matters and the one a due-date report would miss entirely: an
    instrument with no recorded due date never appears in a list sorted by due date, so it is
    invisible precisely because nobody has looked after it.
    """
    out = {EXPIRED: [], DUE_SOON: [], UNKNOWN: []}
    for i in (instruments or []):
        s = status(i, on_date, due_soon_days)
        if s["status"] in out:
            out[s["status"]].append({"id": i.get("id"), "name": i.get("name"),
                                     "type": i.get("type"), "serial": i.get("serial"),
                                     "dueOn": s["dueOn"], "daysLeft": s["daysLeft"],
                                     "why": s["why"]})
    for k in out:
        out[k].sort(key=lambda r: (r["daysLeft"] is None, r["daysLeft"]))
    return out


def untraced_tests(steps):
    """Signed test steps that name no instrument.

    Reported rather than refused while `require_named` is off — but reported by NAME, because "12
    tests are untraced" is a statistic and "T3 on PIN-2026-0417-01" is something somebody can fix.
    """
    return [{"stepId": s.get("id"), "unitId": s.get("unitId"), "code": s.get("code"),
             "signedOn": s.get("signedOn"), "signedBy": s.get("signedBy")}
            for s in (steps or [])
            if s.get("signedBy") and not str(s.get("instrumentId") or "").strip()]


def next_due(instruments, on_date, within_days=90):
    """The calibration diary: what falls due in the next `within_days`, soonest first."""
    on = _d(on_date)
    if not on:
        return []
    horizon = on + timedelta(days=within_days)
    rows = []
    for i in (instruments or []):
        due = _d(i.get("calDue"))
        if due and on <= due <= horizon:
            rows.append({"id": i.get("id"), "name": i.get("name"), "type": i.get("type"),
                         "dueOn": due.isoformat(), "daysLeft": (due - on).days})
    return sorted(rows, key=lambda r: r["daysLeft"])
