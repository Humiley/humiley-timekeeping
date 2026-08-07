"""Headcount and turnover over time.

The portal could always say how many people work here today. It could say nothing about last March —
which is the question every board pack, bank covenant and insurance renewal actually asks. This
computes the history from dated facts (`startDate`, `endDate`) rather than from today's roster.

Three decisions worth stating, because every HR system makes them differently and quietly:

**Somebody is employed ON their last working day.** A leaver whose last day is 31 August is counted
in August's closing headcount and appears as an August leaver. Counting them out on the 31st makes a
month's closing headcount disagree with the payroll that month, which is where the argument starts.
The consequence has to be followed through. Since month-end leavers sit inside closing, closing is
not what chains from one month to the next — `carriedForward` is, and the identity that always holds
is **carriedForward = opening + joiners − leavers**, with opening(this month) = carriedForward(last).
Every naive version of this is wrong in a way that only shows on real dates: counting the 1st puts a
first-of-the-month joiner in the opening as well as in joiners; counting the previous month's closing
carries a 31st-of-the-month leaver into a month they had already left.

**Turnover is leavers ÷ AVERAGE headcount**, not ÷ opening and not ÷ closing. On a 30-person company
one leaver is 3.3%, and choosing the denominator to taste moves that by half a point — so the
denominator is named in the output, not just the number.

**No start date means not counted, ever.** A record with no start date cannot be placed in time. It is
reported as unusable rather than silently treated as "always been here", which would inflate every
historical headcount in the file.
"""
from datetime import date, timedelta

import datespan

_d = datespan.to_date


def month_end(ym):
    """'2026-08' → date(2026, 8, 31)."""
    try:
        y, m = (int(x) for x in str(ym).split("-")[:2])
    except (ValueError, TypeError):
        return None
    if not (1 <= m <= 12):
        return None
    return date(y, m, datespan.days_in_month(y, m))


def months_between(start_ym, end_ym):
    """Inclusive list of 'YYYY-MM' from start to end."""
    a, b = month_end(start_ym), month_end(end_ym)
    if not a or not b or b < a:
        return []
    out, y, m = [], a.year, a.month
    while (y, m) <= (b.year, b.month):
        out.append("%04d-%02d" % (y, m))
        m += 1
        if m > 12:
            y, m = y + 1, 1
    return out


def employed_on(person, when):
    """Was this person employed on this date?

    Employed from their start date up to AND INCLUDING their last working day.
    """
    when = _d(when)
    s = _d((person or {}).get("startDate"))
    if not when or not s or s > when:
        return False
    e = _d((person or {}).get("endDate"))
    if e and e < when:
        return False
    # An Inactive record with no end date has left at some unknown time. It cannot be placed, so it
    # is treated as gone rather than as still on the books — over-counting headcount is the more
    # flattering error and therefore the more dangerous one.
    if not e and str((person or {}).get("status") or "Active").strip().lower() == "inactive":
        return False
    return True


def headcount_at(people, when):
    return sum(1 for p in (people or []) if employed_on(p, when))


def unusable(people):
    """Records that cannot be placed in time — reported, never quietly dropped."""
    out = []
    for p in (people or []):
        s = _d((p or {}).get("startDate"))
        e = _d((p or {}).get("endDate"))
        if not s:
            out.append({"empId": (p or {}).get("id") or "", "name": (p or {}).get("name") or "",
                        "why": "No start date, so they cannot be placed in any month."})
        elif e and e < s:
            out.append({"empId": (p or {}).get("id") or "", "name": (p or {}).get("name") or "",
                        "why": "Their last working day is before their start date."})
    return out


def _in_month(when, ym):
    d = _d(when)
    return bool(d) and ("%04d-%02d" % (d.year, d.month)) == ym


def _prev_day(d):
    return d - timedelta(days=1)


def month_row(people, ym):
    """One month: opening, joiners, leavers, closing, and the average the turnover rate uses."""
    end = month_end(ym)
    if not end:
        return None
    start = date(end.year, end.month, 1)
    prev = _prev_day(start)
    # Opening = who was ALREADY here before this month's movements. Two near-misses live in that
    # sentence, and real dates caught both. Counting the first of the month puts somebody who starts
    # on the 1st into the opening AND into joiners. Counting the last day of the previous month
    # carries a 31st-of-the-month leaver into a month they had already left. So: employed the day
    # before, and not finishing on that very day.
    opening = sum(1 for p in (people or [])
                  if employed_on(p, prev) and _d((p or {}).get("endDate")) != prev)
    joiners = [p for p in (people or []) if _in_month((p or {}).get("startDate"), ym)]
    leavers = [p for p in (people or []) if _in_month((p or {}).get("endDate"), ym)]
    closing = headcount_at(people, end)
    avg = (opening + closing) / 2.0
    return {
        "ym": ym, "opening": opening, "closing": closing,
        "joiners": len(joiners), "leavers": len(leavers),
        "joinerNames": [p.get("name") or p.get("id") or "" for p in joiners],
        "leaverNames": [p.get("name") or p.get("id") or "" for p in leavers],
        "avgHeadcount": round(avg, 1),
        "turnoverPct": round(len(leavers) * 100.0 / avg, 1) if avg > 0 else 0.0,
        "netChange": closing - opening,
        # A leaver is employed ON their last working day, so a month-end leaver is still inside
        # `closing` — which is what makes closing agree with that month's payroll. The quantity that
        # chains from month to month is therefore not closing but carriedForward, and the identity
        # that is ALWAYS true is the one below. Reported rather than asserted, so a month that does
        # not balance shows itself instead of being quietly wrong.
        "carriedForward": closing - sum(1 for p in leavers
                                        if _d((p or {}).get("endDate")) == end),
        "balances": (closing - sum(1 for p in leavers if _d((p or {}).get("endDate")) == end))
                    == opening + len(joiners) - len(leavers),
    }


def series(people, start_ym, end_ym):
    return [r for r in (month_row(people, ym) for ym in months_between(start_ym, end_ym)) if r]


def tenure_days(person, as_of=None):
    s = _d((person or {}).get("startDate"))
    if not s:
        return None
    end = _d((person or {}).get("endDate")) or _d(as_of) or date.today()
    return max(0, (end - s).days)


def summary(people, start_ym, end_ym, as_of=None):
    """The figures a board pack asks for, each with the basis it was computed on."""
    rows = series(people, start_ym, end_ym)
    joiners = sum(r["joiners"] for r in rows)
    leavers = sum(r["leavers"] for r in rows)
    # Annualised turnover over the WHOLE window, not the mean of the monthly rates — averaging
    # percentages computed on different denominators is not a rate, it is a number that looks like
    # one. Denominator: the mean of every month's average headcount in the window.
    avg = (sum(r["avgHeadcount"] for r in rows) / len(rows)) if rows else 0.0
    current = [p for p in (people or []) if employed_on(p, as_of or (month_end(end_ym) or date.today()))]
    tenures = [t for t in (tenure_days(p, as_of) for p in current) if t is not None]
    by_dept = {}
    for p in current:
        d = str((p or {}).get("dept") or "—")
        by_dept[d] = by_dept.get(d, 0) + 1
    return {
        "months": rows,
        "from": start_ym, "to": end_ym,
        "joiners": joiners, "leavers": leavers, "netChange": joiners - leavers,
        "avgHeadcount": round(avg, 1),
        "turnoverPct": round(leavers * 100.0 / avg, 1) if avg > 0 else 0.0,
        "turnoverBasis": "leavers in the period ÷ the average headcount across it",
        "headcountNow": len(current),
        "medianTenureMonths": _median_months(tenures),
        "byDept": sorted(({"dept": k, "headcount": v} for k, v in by_dept.items()),
                         key=lambda r: (-r["headcount"], r["dept"])),
        "unusable": unusable(people),
    }


def _median_months(days_list):
    """Median, not mean: one twenty-year founder drags a mean tenure somewhere no employee is."""
    vals = sorted(d for d in (days_list or []) if d is not None)
    if not vals:
        return 0.0
    n = len(vals)
    mid = vals[n // 2] if n % 2 else (vals[n // 2 - 1] + vals[n // 2]) / 2.0
    return round(mid / 30.44, 1)
