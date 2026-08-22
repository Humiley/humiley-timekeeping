"""Was the person who signed it qualified to?

The module already checks AUTHORITY — whether you are the person named as QC inspector on this unit.
That is a different question from COMPETENCE, which is whether you are trained and currently
certified to perform the thing you just signed. A hi-pot test at 2 kV and an aerosol filter-bypass
scan are not tasks anyone picks up on the day; ISO 9001 clause 7.2 exists because organisations
routinely conflate "allowed" with "able".

Same shape as `ahu_calibration`, and deliberately so: both answer "was this evidence produced by
something fit to produce it", one about the instrument and one about the hands.

Pure: records in, verdicts out.

── Graduated for the same reason ────────────────────────────────────────────────────────────────

An EXPIRED qualification refuses once the rule is switched on. Having NO qualification on file
refuses only under the same switch. Both are off by default so a factory can record what its people
actually hold before the rule bites — turning this on against an empty register would stop every
test in the building, and a control that has to be switched off again on its first morning is a
control nobody trusts afterwards.
"""
from datetime import datetime

QUALIFIED = "QUALIFIED"
EXPIRED = "EXPIRED"
NONE_ON_FILE = "NONE_ON_FILE"
NO_EXPIRY = "NO_EXPIRY"          # held, but with no expiry recorded


def _d(v):
    try:
        return datetime.strptime(str(v or "")[:10], "%Y-%m-%d").date()
    except (TypeError, ValueError):
        return None


def _s(v):
    return str(v or "").strip()


def _same(a, b):
    return _s(a).lower() == _s(b).lower()


def _covers(record, code, kind):
    """Does this qualification cover the step?

    A record may name a specific step code (`T7`) or a whole kind (`test`, `ipqc`). Naming a kind is
    how a factory says "this inspector is signed off for hold points" without listing five codes,
    and the specific code is how it says "and additionally for the hi-pot".
    """
    scope = _s(record.get("scope")) or _s(record.get("code"))
    if not scope:
        return False
    wanted = {_s(code).lower(), _s(kind).lower()}
    return any(_s(p).lower() in wanted for p in scope.replace(";", ",").split(","))


def status(person, code, kind, records, on_date):
    """Where this person stood on this step, on this date."""
    held = [r for r in (records or [])
            if _same(r.get("person"), person) and _covers(r, code, kind)]
    if not held:
        return {"status": NONE_ON_FILE, "why": (
            "No qualification on file for %s covering %s." % (_s(person) or "this person", code))}
    on = _d(on_date)
    best = None
    for r in held:
        exp = _d(r.get("expiresOn"))
        if not exp:
            # No expiry is not the same as current, and it is not the same as expired either.
            cand = {"status": NO_EXPIRY, "record": r,
                    "why": ("Qualification for %s is on file with no expiry date recorded." % code)}
        elif on and exp < on:
            cand = {"status": EXPIRED, "record": r,
                    "why": ("Qualification for %s expired on %s." % (code, exp.isoformat()))}
        else:
            cand = {"status": QUALIFIED, "record": r,
                    "why": ("Qualified for %s until %s." % (code, exp.isoformat()) if exp
                            else "Qualified for %s." % code)}
        # A person may hold several records; the best one decides. Otherwise an old expired
        # certificate would override the renewal sitting beside it.
        order = {QUALIFIED: 0, NO_EXPIRY: 1, EXPIRED: 2}
        if best is None or order[cand["status"]] < order[best["status"]]:
            best = cand
    return best


def check_step(person, spec, records, on_date, require=False):
    """Why this person may not sign this step on competence grounds, or None.

    Only tests and hold points. A workstation operation is signed by whoever did the work, and that
    signature MEANS "I did this" — demanding a certificate there would put the wrong name on it.
    """
    if not require or (spec or {}).get("kind") not in ("test", "ipqc"):
        return None
    st = status(person, (spec or {}).get("code"), (spec or {}).get("kind"), records, on_date)
    if st["status"] == QUALIFIED:
        return None
    if st["status"] == NO_EXPIRY:
        return None                    # on file; chase the date, do not stop the test
    if st["status"] == EXPIRED:
        return st["why"] + " Renew it, or have somebody currently qualified sign this."
    return (st["why"] + " Record the qualification, or have somebody qualified sign this — a test "
            "signed by an untrained inspector is not evidence the test was done properly.")


def gaps(records, on_date, people=None):
    """Qualifications that have expired or carry no expiry date.

    The second group again: a certificate with no expiry never appears in a report sorted by expiry,
    so it is invisible for exactly as long as nobody looks.
    """
    on = _d(on_date)
    out = {EXPIRED: [], NO_EXPIRY: []}
    for r in (records or []):
        if people and not any(_same(r.get("person"), p) for p in people):
            continue
        exp = _d(r.get("expiresOn"))
        row = {"person": r.get("person"), "scope": _s(r.get("scope")) or _s(r.get("code")),
               "expiresOn": r.get("expiresOn"), "certRef": r.get("certRef")}
        if not exp:
            out[NO_EXPIRY].append(row)
        elif on and exp < on:
            row["daysAgo"] = (on - exp).days
            out[EXPIRED].append(row)
    out[EXPIRED].sort(key=lambda r: -r.get("daysAgo", 0))
    return out


def unqualified_signatures(steps, records, spec_kind_of):
    """Signed tests and hold points whose signer holds no current qualification.

    Reported whether or not the rule is switched on — this is the evidence somebody will ask about,
    and it is more useful found now than found by an auditor.
    """
    out = []
    for s in (steps or []):
        who = _s(s.get("signedBy"))
        if not who:
            continue
        kind = spec_kind_of(s.get("code"))
        if kind not in ("test", "ipqc"):
            continue
        st = status(who, s.get("code"), kind, records, s.get("signedOn"))
        if st["status"] in (EXPIRED, NONE_ON_FILE):
            out.append({"stepId": s.get("id"), "unitId": s.get("unitId"), "code": s.get("code"),
                        "signedBy": who, "signedOn": s.get("signedOn"),
                        "status": st["status"], "why": st["why"]})
    return out
