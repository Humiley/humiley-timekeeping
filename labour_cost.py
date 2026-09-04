"""What each project actually cost in people.

The single most valuable number a contractor does not have. The portal has run a GPS attendance
system and a PMBOK project module side by side without ever introducing them: `attendance` had no
project column, so "what did the cleanroom job cost us in labour" had no answer anywhere.

There are two honest ways to answer it and they are not the same, so this module never blends them
silently:

  **recorded**  — somebody said, at check-in, which job they were on. This is a fact.
  **allocated** — nobody recorded it, but the project register says this person is 60% on Project A
                  and 40% on Project B, so their month is split that way. This is an estimate, and a
                  contractor pricing the next job needs to know which of the two they are reading.

Every line carries its basis, and a project total made of both says so. A number that cannot say
where it came from is worse than no number, because it gets used with confidence.

**Money must reconcile.** Splitting one person's monthly cost across three projects in integer dong
loses money to rounding unless it is done deliberately, so the split uses largest-remainder and the
parts are asserted to sum to the whole. A labour report that quietly drops ₫37 a month per person is
the kind of thing that is discovered two years later in an audit.
"""

RECORDED = "recorded"
ALLOCATED = "allocated"
UNASSIGNED = "unassigned"

# Order matters when several bases contribute to one project: the weakest one is what the reader has
# to be warned about, so it wins the label.
_BASIS_RANK = {RECORDED: 0, ALLOCATED: 1, UNASSIGNED: 2}


def _num(v, default=0.0):
    try:
        n = float(v)
    except (TypeError, ValueError):
        return default
    return n if n == n and n not in (float("inf"), float("-inf")) else default


def apportion(total, weights):
    """Split `total` (integer dong) across `weights` so the parts sum EXACTLY to the total.

    Largest remainder: floor everything, then hand the leftover units out to whoever was robbed
    most by the flooring. Naive rounding of three-way splits loses or invents a few dong every
    month per person, which is invisible per payslip and material across a year of projects.
    """
    total = int(round(_num(total)))
    keys = [k for k in weights]
    pos = {k: max(0.0, _num(weights[k])) for k in keys}
    denom = sum(pos.values())
    if not keys or denom <= 0:
        return {}
    exact = {k: total * pos[k] / denom for k in keys}
    out = {k: int(exact[k] // 1) for k in keys}
    left = total - sum(out.values())
    # Hand out the remainder to the largest fractional parts; ties broken by key so the result is
    # deterministic rather than dependent on dict ordering.
    order = sorted(keys, key=lambda k: (-(exact[k] - (exact[k] // 1)), str(k)))
    i = 0
    step = 1 if left >= 0 else -1
    while left != 0 and order:
        out[order[i % len(order)]] += step
        left -= step
        i += 1
    return out


def recorded_weights(days):
    """Project → weight, from days somebody actually recorded against a job.

    A day is one unit whatever its length. Hours would be more precise, but attendance hours are
    derived from clock in/out and are missing or wrong often enough that weighting by them would
    make the recorded basis LESS trustworthy than the allocation it is meant to beat.
    """
    w = {}
    for d in (days or []):
        p = str((d or {}).get("project") or "").strip()
        if p:
            w[p] = w.get(p, 0) + 1
    return w


def allocation_weights(allocations):
    """Project → weight, from the project register's allocation percentages.

    An allocation with no percentage counts as an equal share rather than as zero — being named on a
    project and left blank means "they are on it", not "they are on it for none of their time".
    """
    w = {}
    for a in (allocations or []):
        p = str((a or {}).get("projectId") or "").strip()
        if not p:
            continue
        pct = _num((a or {}).get("allocationPct"), 0.0)
        w[p] = w.get(p, 0.0) + (pct if pct > 0 else 100.0)
    return w


def split_person(cost, days=None, allocations=None):
    """One person's month, split across projects.

    Recorded days win outright where they exist — an estimate must never override a fact. Where some
    days are recorded and some are not, the unrecorded remainder is apportioned by allocation if
    there is one and reported as `unassigned` if there is not. It is not quietly folded into the
    recorded projects, because that would inflate exactly the numbers somebody is about to trust.
    """
    cost = int(round(_num(cost)))
    days = list(days or [])
    rec = recorded_weights(days)
    total_days = len(days)
    recorded_days = sum(rec.values())

    if cost == 0:
        return {"lines": {}, "basis": {}, "total": 0}

    # No attendance at all → fall back to the allocation for the whole month.
    if total_days == 0:
        alloc = allocation_weights(allocations)
        if alloc:
            return {"lines": apportion(cost, alloc),
                    "basis": {p: ALLOCATED for p in alloc}, "total": cost}
        return {"lines": {UNASSIGNED: cost}, "basis": {UNASSIGNED: UNASSIGNED}, "total": cost}

    # Some or all days recorded. Split the cost by day count first, so the recorded part is exactly
    # proportional to the days that were actually recorded.
    unrecorded_days = total_days - recorded_days
    top = dict(rec)
    if unrecorded_days > 0:
        top["__rest__"] = unrecorded_days
    parts = apportion(cost, top)

    lines, basis = {}, {}
    for p, amount in parts.items():
        if p == "__rest__":
            continue
        lines[p] = lines.get(p, 0) + amount
        basis[p] = RECORDED

    rest = parts.get("__rest__", 0)
    if rest:
        alloc = allocation_weights(allocations)
        if alloc:
            for p, amount in apportion(rest, alloc).items():
                lines[p] = lines.get(p, 0) + amount
                # A project fed by both a fact and an estimate is reported as an estimate.
                basis[p] = _weaker(basis.get(p), ALLOCATED)
        else:
            lines[UNASSIGNED] = lines.get(UNASSIGNED, 0) + rest
            basis[UNASSIGNED] = UNASSIGNED

    return {"lines": lines, "basis": basis, "total": cost}


def _weaker(a, b):
    if not a:
        return b
    return a if _BASIS_RANK.get(a, 9) >= _BASIS_RANK.get(b, 9) else b


def report(people, project_names=None):
    """Roll every person up into a per-project report.

    `people` is assembled by the caller — one entry per employee for the period:

        {"empId", "name", "dept", "cost": <employer cost for the month>,
         "costBasis": "signed pay run" | "current salary" | …,
         "days": [{"date", "project"} …], "allocations": [{"projectId", "allocationPct"} …]}
    """
    names = dict(project_names or {})
    projects, per_person, total = {}, [], 0

    for p in (people or []):
        p = dict(p or {})
        split = split_person(p.get("cost"), p.get("days"), p.get("allocations"))
        total += split["total"]
        per_person.append({"empId": p.get("empId") or "", "name": p.get("name") or "",
                           "dept": p.get("dept") or "", "cost": split["total"],
                           "costBasis": p.get("costBasis") or "",
                           "lines": split["lines"], "basis": split["basis"]})
        for proj, amount in split["lines"].items():
            row = projects.setdefault(proj, {"projectId": proj, "name": names.get(proj, proj),
                                             "cost": 0, "people": 0, "basis": None})
            row["cost"] += amount
            row["people"] += 1
            row["basis"] = _weaker(row["basis"], split["basis"].get(proj, UNASSIGNED))

    rows = sorted(projects.values(), key=lambda r: (-r["cost"], str(r["name"])))
    for r in rows:
        r["basis"] = r["basis"] or UNASSIGNED
        if r["projectId"] == UNASSIGNED:
            r["name"] = "Not attributed to a project"

    booked = sum(r["cost"] for r in rows)
    return {
        "projects": rows,
        "people": per_person,
        "total": total,
        # The invariant, computed rather than asserted: every dong of everybody's cost landed on
        # exactly one line. If this is ever false the report is wrong and should say so on its face
        # instead of being quietly used to price the next tender.
        "reconciles": booked == total,
        "booked": booked,
        "unattributed": next((r["cost"] for r in rows if r["projectId"] == UNASSIGNED), 0),
        "recordedShare": _share(rows, RECORDED, booked),
    }


def _share(rows, basis, booked):
    """How much of the total rests on fact rather than estimate — the number that tells somebody
    how far to trust the report."""
    if not booked:
        return 0.0
    hit = sum(r["cost"] for r in rows if r["basis"] == basis)
    return round(hit * 100.0 / booked, 1)
