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


def seed_attendance_dates():
    """The exact dates the shipped sample writes attendance for. It is deterministic — five days
    back from a fixed generator — so a punch on ANY other date cannot be a sample row, whoever it
    belongs to. That makes "is this row part of the sample" answerable per ROW, not only per person.
    """
    return {a["date"] for a in seed_data.sample_attendance()}


def seed_leave_keys():
    """(emp_id, type, startDate, endDate) for each shipped leave request."""
    return {(l["emp_id"], l["type"], l["startDate"], l["endDate"]) for l in seed_data.LEAVE}


def employee_in_use(emp_id, attendance, leave, refs):
    """Has a real person been working in this record? (bool, reason)

    An EDIT to the name or email already makes a sample row real. This is the other half of that
    idea and the stronger signal: accrued ACTIVITY. `_emp_delete` — the single-employee path that
    has been in this codebase all along — refuses to hard-delete any employee with history at all,
    on the reasoning that deleting one destroys or orphans that history. A bulk path that ignores
    the same evidence would be held to a lower standard than the button next to it.

      attendance  the employee's attendance rows
      leave       the employee's leave rows
      refs        db.employee_references(emp_id) — everything in the DB pointing at them
    """
    dates, keys = seed_attendance_dates(), seed_leave_keys()
    extra_att = [a for a in (attendance or []) if str(a.get("date") or "") not in dates]
    if extra_att:
        return True, ("%d attendance record(s) on dates the sample never writes — somebody has been "
                      "punching in on this account" % len(extra_att))
    extra_leave = [l for l in (leave or [])
                   if (l.get("emp_id"), l.get("type"), l.get("startDate"), l.get("endDate")) not in keys]
    if extra_leave:
        return True, "%d leave request(s) that are not the sample's" % len(extra_leave)
    # Anything else the database points at them with. attendance/leave are handled above by CONTENT;
    # every other reference — a pay run, a signed acknowledgement, a device, a direct report — means
    # the record is load-bearing for something real.
    other = {k: v for k, v in (refs or {}).items()
             if k not in ("attendance record", "leave request", "e-signature PIN")}
    if other:
        return True, ", ".join("%s: %s" % (k, v) for k, v in sorted(other.items()))
    return False, ""


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


def plan(employees, zones, attendance_for, leave_for, refs_for=None):
    """What a removal would do, as data. Takes readers, not a database — so it is testable, and so
    this module cannot delete anything even by accident.

      employees       list of employee dicts
      zones           list of zone dicts
      attendance_for  callable(emp_id) -> list of that employee's attendance rows
      leave_for       callable(emp_id) -> list of that employee's leave rows
      refs_for        callable(emp_id) -> db.employee_references(emp_id), or None to skip that check
    """
    seeded = _seed_employees()
    out = {
        "employees": {"demo": [], "edited": [], "protected": [], "inUse": []},
        "zones": {"demo": [], "keep": [], "edited": []},
        "attendance": 0,
        "leave": 0,
        "notes": [],
    }

    for e in employees or []:
        verdict, why = classify_employee(e, seeded)
        entry = {"id": e.get("id"), "name": e.get("name"), "email": e.get("email"), "why": why}
        if verdict == "demo":
            att = attendance_for(e.get("id")) or []
            lv = leave_for(e.get("id")) or []
            used, why_used = employee_in_use(e.get("id"), att, lv,
                                             refs_for(e.get("id")) if refs_for else {})
            if used:
                entry["why"] = why_used
                out["employees"]["inUse"].append(entry)
                continue
            out["employees"]["demo"].append(entry)
            out["attendance"] += len(att)
            out["leave"] += len(lv)
        elif verdict == "edited":
            out["employees"]["edited"].append(entry)
        elif _norm(e.get("email")) in PROTECTED_EMAILS and str(e.get("id") or "") in seeded:
            out["employees"]["protected"].append(entry)

    # A zone must match the shipped one on name AND position — somebody may have renamed a real site
    # to something similar, and a geofence is what decides whether a punch is on site.
    for z in zones or []:
        hit = None
        for sz in seed_data.ZONES:
            if (_norm(z.get("name")) == _norm(sz["name"])
                    and abs(float(z.get("lat") or 0) - sz["lat"]) < 1e-6
                    and abs(float(z.get("lon") or 0) - sz["lon"]) < 1e-6):
                hit = sz
                break
        entry = {"id": z.get("id"), "name": z.get("name")}
        if not hit:
            out["zones"]["keep"].append(entry)
        elif int(float(z.get("radius") or 0)) != int(hit["radius"]):
            # The RADIUS is the field somebody tunes on a live site, and it decides whether a punch
            # reads as on-site. A changed radius is an edit, and an edit makes the row theirs — the
            # same rule this module already applies to an employee's name or email.
            entry["why"] = "the geofence radius has been changed from the sample's"
            out["zones"]["edited"].append(entry)
        else:
            out["zones"]["demo"].append(entry)

    if out["employees"]["inUse"]:
        out["notes"].append(
            "%d sample record(s) have real activity on them — punches, leave or records elsewhere "
            "pointing at them. They are in use and are left alone."
            % len(out["employees"]["inUse"]))
    if out["zones"]["edited"]:
        out["notes"].append(
            "%d sample zone(s) have had their radius changed and are treated as real geofences."
            % len(out["zones"]["edited"]))
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
