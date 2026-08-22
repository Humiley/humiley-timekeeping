# -*- coding: utf-8 -*-
"""Which rows in this database came from the shipped demo seed, and which only look like it.

The portal ships a fixed sample org — fifteen employees, two zones, five leave requests, five days
of attendance — so a fresh install has something on screen. On a live database those rows sit beside
real ones and there is nothing marking them: `seed()` inserts through the same columns as a real
punch. Anything claiming to "remove the demo data" is therefore making an identification, and the
whole question is how confident that identification is.

THE RULE HERE: a row is deletable only when it can be matched to the seed by IDENTITY, not by
resemblance. An employee must match the seed record on id AND name AND email. A punch or a leave
request is deletable only because the EMPLOYEE it belongs to is a seeded one — never because the row
itself looks generated.

Everything else is reported and left alone. Three cases in particular are never deleted:

  * an employee whose email is a protected administrator's. EMP001 in the shipped seed carries
    huy.nguyen@humiley.com, which is a real super-admin — so the most obvious "delete the demo
    employees" sweep would take out an administrator. That is the trap this module exists to avoid.
  * a seeded row somebody has since EDITED. If the name or email no longer matches the seed, a
    person has been working in that record and it is theirs, not the sample's.
  * anything attached to a REAL employee. HR sample rows (a claim, an appraisal, a device) are
    generated against whichever employees exist, so on a live database they hang off real people.
    Those are listed for somebody to remove one at a time, and never swept.

Nothing in this module writes. `plan()` describes; the caller decides and does.
"""

import seed_data

# Never removed, whatever the seed says. Kept here rather than imported so this module states its
# own safety property instead of inheriting one that could change underneath it.
PROTECTED_EMAILS = {"tony.nguyen@humiley.com", "huy.nguyen@humiley.com"}


def _norm(v):
    return str(v or "").strip().lower()


def _seed_employees():
    return {e["id"]: e for e in seed_data.EMPLOYEES}


def classify_employee(row, seeded=None):
    """(verdict, reason) for one employee row. verdict is 'demo', 'keep' or 'edited'."""
    seeded = seeded if seeded is not None else _seed_employees()
    s = seeded.get(str(row.get("id") or ""))
    if not s:
        return "keep", "not in the shipped sample"
    if _norm(row.get("email")) in PROTECTED_EMAILS:
        return "keep", "protected administrator — the sample reuses this address"
    if _norm(row.get("name")) != _norm(s.get("name")) or _norm(row.get("email")) != _norm(s.get("email")):
        return "edited", "id matches the sample but the name or email has been changed since"
    return "demo", "matches the shipped sample on id, name and email"


def plan(employees, zones, attendance_count_for, leave_count_for):
    """What a removal would do, as data. Takes readers, not a database — so it is testable, and so
    this module cannot delete anything even by accident.

      employees            list of employee dicts
      zones                list of zone dicts
      attendance_count_for callable(emp_id) -> int
      leave_count_for      callable(emp_id) -> int
    """
    seeded = _seed_employees()
    out = {
        "employees": {"demo": [], "edited": [], "protected": []},
        "zones": {"demo": [], "keep": []},
        "attendance": 0,
        "leave": 0,
        "notes": [],
    }

    for e in employees or []:
        verdict, why = classify_employee(e, seeded)
        entry = {"id": e.get("id"), "name": e.get("name"), "email": e.get("email"), "why": why}
        if verdict == "demo":
            out["employees"]["demo"].append(entry)
            out["attendance"] += int(attendance_count_for(e.get("id")) or 0)
            out["leave"] += int(leave_count_for(e.get("id")) or 0)
        elif verdict == "edited":
            out["employees"]["edited"].append(entry)
        elif _norm(e.get("email")) in PROTECTED_EMAILS and str(e.get("id") or "") in seeded:
            out["employees"]["protected"].append(entry)

    # A zone must match the shipped one on name AND position — somebody may have renamed a real site
    # to something similar, and a geofence is what decides whether a punch is on site.
    for z in zones or []:
        hit = None
        for s in seed_data.ZONES:
            if (_norm(z.get("name")) == _norm(s["name"])
                    and abs(float(z.get("lat") or 0) - s["lat"]) < 1e-6
                    and abs(float(z.get("lon") or 0) - s["lon"]) < 1e-6):
                hit = s
                break
        (out["zones"]["demo"] if hit else out["zones"]["keep"]).append(
            {"id": z.get("id"), "name": z.get("name")})

    if out["employees"]["edited"]:
        out["notes"].append(
            "%d sample employee record(s) have been edited since — a person has been working in them, "
            "so they are treated as real and left alone." % len(out["employees"]["edited"]))
    if out["employees"]["protected"]:
        out["notes"].append(
            "%d sample record(s) carry a protected administrator's address and are never removed."
            % len(out["employees"]["protected"]))
    out["notes"].append(
        "HR sample rows (claims, appraisals, devices, onboarding) are generated against whichever "
        "employees exist, so on a live database they belong to REAL people. Nothing here removes "
        "them: delete those individually from their own register, where you can see what each one is.")

    out["totals"] = {
        "employees": len(out["employees"]["demo"]),
        "attendance": out["attendance"],
        "leave": out["leave"],
        "zones": len(out["zones"]["demo"]),
    }
    out["anything"] = any(out["totals"].values())
    return out
