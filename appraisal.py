"""Appraisal cycles, and which rating is allowed to move somebody's pay.

`reviews` already existed, with a free-text `cycle` field chosen from four hardcoded strings. What
did not exist was the cycle itself — anything that could say who is in this round, who has finished,
who is late, and whether it is closed. Without that a review round is a pile of records nobody can
chase to completion.

**The defect underneath it matters more than the missing feature.** Payroll built its ratings as

    ratingBy[empId] = +r.rating || 3     # for every review record, in list order

so the LAST record in the list won, whatever cycle it belonged to and whatever date it carried. A
rating drives the KPI component through `perf_factor` — 1.5× at a 5, and 0× at a 1 — so a stale
review from two years ago, or somebody's unfinished self-assessment, could quietly set this month's
pay. This module answers instead: *which rating governs this month?*

The rule, and each clause is there because the alternative is worse:

  1. Only a **closed** cycle governs pay. An appraisal still being written is not a decision.
  2. The governing cycle is the closed one whose period **covers** the month; failing that, the most
     recent closed cycle that **ended before** it. A rating applies forward, not backward.
  3. No governing cycle means the **neutral** rating, not the last one lying around. Neutral pays
     the KPI target exactly; guessing pays somebody more or less than they earned.

Two more decisions worth stating:

**Participants are frozen when the cycle opens.** Recomputing eligibility on every read means a
leaver silently drops out of the denominator and completion climbs to 100% without anybody finishing
anything.

**A salary proposal is a proposal.** This module produces figures from a rating and a matrix; it
never applies them. Applying is a separate, authorised, audited act, because it is somebody's pay.
"""
from datetime import date

import datespan

_d = datespan.to_date

NEUTRAL_RATING = 3          # pays the KPI target exactly — see perf_factor in payroll_calc
MIN_RATING, MAX_RATING = 1, 5

DRAFT, OPEN, CLOSED = "Draft", "Open", "Closed"
# The states one person's review moves through. Anything not in this list is treated as not started,
# so a typo can never read as "finished".
NOT_STARTED, SELF, REVIEW, DONE = "Not started", "Self-assessment", "In review", "Completed"
DONE_STATES = {DONE.lower(), "completed", "complete", "signed"}


def _ym(v):
    d = _d(v)
    return "%04d-%02d" % (d.year, d.month) if d else ""


def is_done(review):
    return str((review or {}).get("status") or "").strip().lower() in DONE_STATES


def clamp_rating(value):
    """A rating outside 1–5 is not clamped silently — it is rejected, because a 7 in the box is a
    typo and paying somebody on it is worse than asking again."""
    try:
        n = float(value)
    except (TypeError, ValueError):
        return None
    if n != n or n < MIN_RATING or n > MAX_RATING:
        return None
    return n


# ── who is in a cycle ────────────────────────────────────────────────────────────────────────────

def eligible(employees, period_from, period_to, min_months=3):
    """Who should be appraised for this period.

    Somebody who joined three weeks before the period ended has nothing to be appraised on, so a
    minimum service in the period is applied — and the ones excluded are RETURNED rather than
    dropped, so opening a cycle shows who it deliberately left out.
    """
    a, b = _d(period_from), _d(period_to)
    inc, exc = [], []
    for e in (employees or []):
        eid = str((e or {}).get("id") or "")
        if not eid:
            continue
        s = _d(e.get("startDate"))
        end = _d(e.get("endDate"))
        name = e.get("name") or eid
        if not s:
            exc.append({"empId": eid, "name": name, "why": "No start date on their record."})
            continue
        if a and b:
            if s > b:
                exc.append({"empId": eid, "name": name, "why": "Joined after the period ended."})
                continue
            if end and end < a:
                exc.append({"empId": eid, "name": name, "why": "Left before the period began."})
                continue
            worked_from = max(s, a)
            worked_to = min(end, b) if end else b
            months = datespan.whole_months(worked_from, worked_to)
            if months < min_months:
                exc.append({"empId": eid, "name": name,
                            "why": "Only %d month(s) in the period — under the %d-month minimum."
                                   % (months, min_months)})
                continue
        inc.append({"empId": eid, "name": name, "dept": e.get("dept") or "",
                    "managerEmail": e.get("managerEmail") or ""})
    inc.sort(key=lambda r: (r["dept"], r["name"]))
    return {"included": inc, "excluded": exc}


# ── how far along a cycle is ─────────────────────────────────────────────────────────────────────

def state(cycle, reviews, today=None):
    """Completion against the FROZEN participant list, plus who is holding it up."""
    cycle = cycle or {}
    parts = list(cycle.get("participants") or [])
    by_emp = {}
    for r in (reviews or []):
        if str(r.get("cycleId") or "") == str(cycle.get("id") or ""):
            by_emp[str(r.get("empId") or "")] = r
    t = _d(today) or date.today()
    due = _d(cycle.get("dueDate"))
    overdue = bool(due and t > due and str(cycle.get("status") or "") == OPEN)

    rows = []
    for p in parts:
        r = by_emp.get(str(p.get("empId") or ""))
        rows.append({
            "empId": p.get("empId"), "name": p.get("name"), "dept": p.get("dept"),
            "managerEmail": p.get("managerEmail"),
            "status": (r or {}).get("status") or NOT_STARTED,
            "rating": clamp_rating((r or {}).get("rating")),
            "done": is_done(r),
        })
    done = [r for r in rows if r["done"]]
    outstanding = [r for r in rows if not r["done"]]
    return {
        "cycleId": cycle.get("id"), "name": cycle.get("name"),
        "status": cycle.get("status") or DRAFT,
        "periodFrom": cycle.get("periodFrom"), "periodTo": cycle.get("periodTo"),
        "dueDate": cycle.get("dueDate"), "overdue": overdue,
        "participants": len(rows), "done": len(done), "outstanding": len(outstanding),
        "pct": round(len(done) * 100.0 / len(rows), 1) if rows else 0.0,
        "rows": rows,
        # Who to chase, grouped by the manager who owes the review — a flat list of 30 names is not
        # actionable; "these four are yours" is.
        "chase": _by_manager(outstanding),
        "distribution": distribution([r for r in rows if r["rating"] is not None]),
    }


def _by_manager(rows):
    out = {}
    for r in rows:
        out.setdefault(r.get("managerEmail") or "—", []).append(r.get("name") or r.get("empId"))
    return sorted(({"manager": k, "waitingOn": v} for k, v in out.items()),
                  key=lambda x: (-len(x["waitingOn"]), x["manager"]))


def distribution(rows):
    """The spread of ratings, and a flag when it is not credible.

    Not a judgement about individuals — a whole-company distribution where nobody is below the
    midpoint usually means the exercise was not taken seriously, and that is worth saying before the
    ratings are turned into money.
    """
    counts = {n: 0 for n in range(MIN_RATING, MAX_RATING + 1)}
    vals = []
    for r in (rows or []):
        v = clamp_rating(r.get("rating") if isinstance(r, dict) else r)
        if v is None:
            continue
        vals.append(v)
        counts[int(round(v))] = counts.get(int(round(v)), 0) + 1
    n = len(vals)
    mean = round(sum(vals) / n, 2) if n else 0.0
    below = sum(c for k, c in counts.items() if k < NEUTRAL_RATING)
    flags = []
    if n >= 5 and below == 0:
        flags.append("Nobody was rated below the midpoint — an appraisal round with no downside is "
                     "usually one that was not taken seriously.")
    if n >= 5 and counts.get(MAX_RATING, 0) * 2 > n:
        flags.append("More than half the team is on the top rating, which makes the rating "
                     "meaningless as a basis for pay.")
    return {"counts": counts, "n": n, "mean": mean, "flags": flags}


# ── which rating is allowed to move pay ──────────────────────────────────────────────────────────

def governing_cycle(cycles, ym):
    """The closed cycle whose rating governs the given month, or None.

    Covering beats preceding, and a cycle that has not closed governs nothing.
    """
    target = str(ym or "")[:7]
    if not target:
        return None
    closed = [c for c in (cycles or [])
              if str((c or {}).get("status") or "").strip().lower() == CLOSED.lower()]
    covering = [c for c in closed
                if _ym(c.get("periodFrom")) <= target <= _ym(c.get("periodTo"))
                and _ym(c.get("periodFrom")) and _ym(c.get("periodTo"))]
    if covering:
        # If two closed cycles cover the same month, the one that ended latest is the later word.
        return sorted(covering, key=lambda c: (_ym(c.get("periodTo")), str(c.get("id") or "")))[-1]
    before = [c for c in closed if _ym(c.get("periodTo")) and _ym(c.get("periodTo")) < target]
    if before:
        return sorted(before, key=lambda c: (_ym(c.get("periodTo")), str(c.get("id") or "")))[-1]
    return None


def governing_rating(cycles, reviews, emp_id, ym):
    """The rating that may set this person's KPI pay for this month, and why.

    Returns (rating, basis) — never a bare number, because "3" from a real appraisal and "3" because
    nothing was found are different facts and only one of them should survive a question from the
    person being paid.
    """
    c = governing_cycle(cycles, ym)
    if not c:
        return NEUTRAL_RATING, "No closed appraisal cycle covers this month — the neutral rating is used."
    for r in (reviews or []):
        if str(r.get("cycleId") or "") != str(c.get("id") or ""):
            continue
        if str(r.get("empId") or "") != str(emp_id or ""):
            continue
        if not is_done(r):
            return NEUTRAL_RATING, ("Their review in %s was never completed — the neutral rating is "
                                    "used rather than an unfinished one." % (c.get("name") or "the cycle"))
        v = clamp_rating(r.get("rating"))
        if v is None:
            return NEUTRAL_RATING, ("Their %s review has no usable rating — the neutral rating is used."
                                    % (c.get("name") or "cycle"))
        return v, "From their completed %s review." % (c.get("name") or "appraisal")
    return NEUTRAL_RATING, ("They were not appraised in %s — the neutral rating is used."
                            % (c.get("name") or "the closed cycle"))


# ── salary review ────────────────────────────────────────────────────────────────────────────────

DEFAULT_MATRIX = {5: 10.0, 4: 7.0, 3: 4.0, 2: 0.0, 1: 0.0}


def proposals(rows, employees, matrix=None, budget_pct=None):
    """Turn completed ratings into PROPOSED salary changes. Never applies anything.

    `budget_pct` caps the total increase as a percentage of the current payroll. When the matrix
    would exceed it every proposal is scaled down by the same factor and the report says so — the
    alternative is somebody quietly cutting the bottom of the list, which is how a review round
    becomes a rumour.
    """
    m = dict(DEFAULT_MATRIX)
    m.update({int(k): float(v) for k, v in (matrix or {}).items()})
    by_id = {str(e.get("id")): e for e in (employees or [])}

    out, base_total, raise_total = [], 0, 0
    for r in (rows or []):
        eid = str(r.get("empId") or "")
        e = by_id.get(eid)
        if not e:
            continue
        rating = clamp_rating(r.get("rating"))
        try:
            cur = int(round(float(e.get("salary") or 0)))
        except (TypeError, ValueError):
            cur = 0
        if not cur or rating is None or not r.get("done"):
            out.append({"empId": eid, "name": r.get("name") or eid, "current": cur,
                        "rating": rating, "pct": 0.0, "increase": 0, "proposed": cur,
                        "why": "No completed rating, or no salary on record — nothing proposed."})
            continue
        pct = m.get(int(round(rating)), 0.0)
        inc = int(round(cur * pct / 100.0))
        base_total += cur
        raise_total += inc
        out.append({"empId": eid, "name": r.get("name") or eid, "current": cur, "rating": rating,
                    "pct": pct, "increase": inc, "proposed": cur + inc, "why": ""})

    scale, capped = 1.0, False
    if budget_pct is not None and base_total > 0:
        allowed = base_total * float(budget_pct) / 100.0
        if raise_total > allowed > 0:
            scale = allowed / raise_total
            capped = True
            raise_total = 0
            for row in out:
                if row["increase"]:
                    row["increase"] = int(round(row["increase"] * scale))
                    row["proposed"] = row["current"] + row["increase"]
                    row["pct"] = round(row["increase"] * 100.0 / row["current"], 2) if row["current"] else 0.0
                    raise_total += row["increase"]

    return {
        "rows": sorted(out, key=lambda r: (-(r["increase"]), r["name"])),
        "currentTotal": base_total, "increaseTotal": raise_total,
        "increasePct": round(raise_total * 100.0 / base_total, 2) if base_total else 0.0,
        "capped": capped, "scale": round(scale, 4),
        "budgetPct": budget_pct,
    }
