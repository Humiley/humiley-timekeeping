"""Datasets for Power BI (and anything else that speaks HTTP + CSV).

WHY THIS EXISTS, AND WHY IT IS NOT JUST THE COLLECTION DUMP

A BI tool does not want the app's storage shape. It wants a **tidy fact table**: one row per thing
per day, already carrying the numbers a measure needs. Two properties matter enough to build a
module for:

1. **The series is DENSE.** A progress reading is filed only on the days somebody reported, so the
   raw log has holes. A line chart over holes either breaks or silently interpolates. `progress_fact`
   emits one row for every item for every day in the window, carrying the last reading forward — the
   same thing a scheduler does by hand, done once, here, instead of in everybody's DAX.

2. **The weighting travels with the data.** Percent-complete must never be averaged: a finished
   two-day item beside an untouched sixty-day one is 3% complete, not 50%. A BI user dropping
   `accumulatedPct` into a chart gets the wrong answer and no warning. So every row also carries
   `weight`, `weightedAccum` (= weight x accumulated) and `weightedPlanned`, and the documented
   measure is SUM(weightedAccum) / SUM(weight) — correct at ANY grain: item, trade, activity,
   project, portfolio. The naive average stays available for anyone who genuinely wants it, but the
   right answer is the easy one.

⚠️ `planned_pct` and `weight_of` are a deliberate port of the frontend's `_pdPlanned` / `_pdWeight`
(templates/index.html). Two implementations of one rule is a liability; they are kept together by
tests/test_bi.py, which asserts the same cases the JavaScript harness asserts. Change one, change
both, and update both test files — the same arrangement as payroll_calc.py and _payComputed.
"""
import csv
import datetime
import io

MAX_DAYS = 400          # a densified series is items x days; refuse to build an unbounded one


# ── date helpers (ISO strings in, ISO strings out — no timezones anywhere) ───────────────────────

def _d(s):
    return datetime.date(int(s[0:4]), int(s[5:7]), int(s[8:10]))


def _iso(d):
    return d.isoformat()


def _days(frm, to):
    a, b = _d(frm), _d(to)
    out = []
    while a <= b:
        out.append(_iso(a))
        a += datetime.timedelta(days=1)
    return out


def _pct(v):
    try:
        n = int(round(float(v)))
    except (TypeError, ValueError):
        return 0
    return max(0, min(100, n))


# ── the rules, ported from the frontend ─────────────────────────────────────────────────────────

def clean_log(item):
    """Readings oldest-first, ignoring anything undated. This is user data; it arrives malformed."""
    log = item.get("log")
    if not isinstance(log, list):
        return []
    good = [e for e in log if isinstance(e, dict) and e.get("d")]
    return sorted(good, key=lambda e: str(e.get("d")))


def qty_plan(item):
    """The scheduled quantity — 500 m of pipe, 240 m2 of ceiling. Zero means the line is judged."""
    try:
        q = float(item.get("qtyPlan") or 0)
    except (TypeError, ValueError):
        return 0.0
    return q if q > 0 else 0.0


def read_pct(item, e):
    """One reading as a percentage. A reading carrying a QUANTITY is a measurement; one carrying only
    a percentage is an estimate. Decided per READING so a line that gained a quantity partway keeps
    the history it already had."""
    qp = qty_plan(item)
    q = (e or {}).get("qty")
    if qp > 0 and q not in (None, ""):
        try:
            return _pct(float(q) / qp * 100.0)
        except (TypeError, ValueError, ZeroDivisionError):
            pass
    return _pct((e or {}).get("pct"))


def qty_at(item, day):
    """Quantity installed at site as at `day`, and whether it was measured or inferred."""
    v, seen = 0.0, False
    for e in clean_log(item):
        if str(e.get("d")) > day:
            break
        q = e.get("qty")
        if q not in (None, ""):
            try:
                v, seen = float(q), True
            except (TypeError, ValueError):
                pass
    if seen:
        return (v, False)
    qp = qty_plan(item)
    return ((qp * accumulated_at(item, day) / 100.0) if qp else 0.0, True)


def accumulated_at(item, day):
    """The latest reading on or before `day`. Zero before the first one."""
    v = 0
    for e in clean_log(item):
        if str(e.get("d")) <= day:
            v = read_pct(item, e)
        else:
            break
    return v


def daily_at(item, day):
    """Today's increment — zero unless a reading was actually filed for `day`.

    This is the whole reason the two columns exist. A 'daily progress' figure that simply persists is
    the characteristic lie of a paper report: a stalled item goes on advertising last week's effort.
    """
    log = clean_log(item)
    todays = [e for e in log if str(e.get("d")) == day]
    if not todays:
        return 0
    prev = 0
    for e in log:
        if str(e.get("d")) < day:
            prev = read_pct(item, e)
    return max(0, read_pct(item, todays[-1]) - prev)


def planned_pct(item, day):
    """Straight line between start and finish, both ends inclusive."""
    s, f = item.get("start"), item.get("finish")
    if not s or not f or day < s:
        return 0
    if day >= f:
        return 100
    total = max(1, (_d(f) - _d(s)).days + 1)
    done = max(0, (_d(day) - _d(s)).days + 1)
    return _pct(done * 100.0 / total)


def weight_of(item):
    """Duration in days unless a weight was given (contract value, man-hours — the unit is theirs)."""
    try:
        w = float(item.get("weight") or 0)
    except (TypeError, ValueError):
        w = 0
    if w > 0:
        return w
    s, f = item.get("start"), item.get("finish")
    if s and f:
        return float(max(1, (_d(f) - _d(s)).days + 1))
    return 1.0


# ── the datasets ────────────────────────────────────────────────────────────────────────────────

PROGRESS_COLS = [
    "date", "projectId", "project", "category", "itemId", "item", "masterRef", "unit",
    "startDate", "finishDate", "weight", "qtyPlanned", "qtyAtSite", "qtyMeasured",
    "accumulatedPct", "dailyPct", "plannedPct", "variancePct",
    "weightedAccum", "weightedPlanned", "reportedToday",
]


def window(items, frm=None, to=None, today=None):
    """The date range to emit. Defaults to the span of the work, clipped to today at the far end so
    the fact table never asserts progress for days that have not happened."""
    today = today or _iso(datetime.date.today())
    ds = []
    for it in items:
        for k in ("start", "finish"):
            if it.get(k):
                ds.append(str(it[k]))
        for e in clean_log(it):
            ds.append(str(e.get("d")))
    if not ds:
        return (today, today)
    lo = frm or min(ds)
    hi = to or min(max(ds), today)
    if hi < lo:
        hi = lo
    if len(_days(lo, hi)) > MAX_DAYS:
        # Silently truncating would understate the history with no sign that anything was dropped.
        lo = _iso(_d(hi) - datetime.timedelta(days=MAX_DAYS - 1))
    return (lo, hi)


def progress_fact(items, project=None, frm=None, to=None, today=None):
    """One row per item per day — dense, carried forward, weighted."""
    items = [i for i in (items or []) if i]
    lo, hi = window(items, frm, to, today)
    days = _days(lo, hi)
    pid = (project or {}).get("id") or ""
    pname = (project or {}).get("name") or ""
    rows = []
    for it in items:
        w = weight_of(it)
        for day in days:
            acc = accumulated_at(it, day)
            pl = planned_pct(it, day)
            dly = daily_at(it, day)
            rows.append({
                "date": day,
                "projectId": it.get("projectId") or pid,
                "project": pname,
                "category": it.get("category") or "Uncategorised",
                "itemId": it.get("id") or "",
                "item": it.get("name") or "",
                "masterRef": it.get("taskRef") or "",
                "unit": it.get("unit") or "",
                "startDate": it.get("start") or "",
                "finishDate": it.get("finish") or "",
                "weight": round(w, 4),
                "qtyPlanned": round(qty_plan(it), 4),
                # qtyMeasured=0 means the site figure was back-calculated from a typed percentage.
                # Summing an inferred quantity as if it were measured is the mistake this flag exists
                # to make visible in the model rather than invisible in a chart.
                "qtyAtSite": round(qty_at(it, day)[0], 4),
                "qtyMeasured": 0 if qty_at(it, day)[1] else 1,
                "accumulatedPct": acc,
                "dailyPct": dly,
                "plannedPct": pl,
                "variancePct": acc - pl,
                # SUM(weightedAccum)/SUM(weight) is the correct roll-up at every grain. Averaging
                # accumulatedPct is not, and this is the column that saves a BI user from that.
                "weightedAccum": round(w * acc, 4),
                "weightedPlanned": round(w * pl, 4),
                "reportedToday": 1 if dly > 0 else 0,
            })
    return rows


ITEM_COLS = ["itemId", "projectId", "category", "item", "masterRef", "unit",
             "startDate", "finishDate", "weight", "durationDays", "lastReadingDate", "readings"]


def items_dim(items):
    out = []
    for it in (items or []):
        log = clean_log(it)
        s, f = it.get("start"), it.get("finish")
        out.append({
            "itemId": it.get("id") or "",
            "projectId": it.get("projectId") or "",
            "category": it.get("category") or "Uncategorised",
            "item": it.get("name") or "",
            "masterRef": it.get("taskRef") or "",
            "unit": it.get("unit") or "",
            "startDate": s or "",
            "finishDate": f or "",
            "weight": round(weight_of(it), 4),
            "durationDays": ((_d(f) - _d(s)).days + 1) if (s and f) else "",
            "lastReadingDate": str(log[-1].get("d")) if log else "",
            "readings": len(log),
        })
    return out


ACTIVITY_COLS = ["taskId", "projectId", "masterRef", "wbs", "activity", "phase", "assignee",
                 "startDate", "finishDate", "actualFinish", "isMilestone", "status", "typedPct"]


def activities_dim(tasks):
    """The master schedule, as the dimension detail lines roll up into.

    `masterRef` is the join key and matches the frontend's `_pdTaskRef`: the WBS code where there is
    one, else the activity name. `typedPct` is deliberately named — where detail lines exist the
    authoritative figure is their weighted roll-up, not this.
    """
    out = []
    for t in (tasks or []):
        ref = str(t.get("wbs") or t.get("name") or "").strip()
        out.append({
            "taskId": t.get("id") or "",
            "projectId": t.get("projectId") or "",
            "masterRef": ref,
            "wbs": t.get("wbs") or "",
            "activity": t.get("name") or "",
            "phase": t.get("phase") or "",
            "assignee": t.get("assignee") or "",
            "startDate": t.get("start") or "",
            "finishDate": t.get("finish") or "",
            "actualFinish": t.get("actualFinish") or "",
            "isMilestone": 1 if str(t.get("isMilestone")) == "Yes" else 0,
            "status": t.get("status") or "Not started",
            "typedPct": _pct(t.get("pctComplete")),
        })
    return out


def to_csv(rows, cols):
    """UTF-8 with a BOM: Excel and Power BI Desktop both mis-read Vietnamese without it."""
    buf = io.StringIO()
    w = csv.DictWriter(buf, fieldnames=cols, extrasaction="ignore", lineterminator="\n")
    w.writeheader()
    for r in rows:
        w.writerow(r)
    return ("﻿" + buf.getvalue()).encode("utf-8")
