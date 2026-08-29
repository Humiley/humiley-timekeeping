"""Capacity, load and cycle time — reading the tact times the route has always carried.

Two things the SOP asks for and nothing computed.

**The rolling load chart.** SOP section 6.7 names it by name, as the control against the risk
"delivery date shorter than feasible": *"Capacity check by PMO using rolling 8-week load chart."*
Without it, Sales can promise a date the floor cannot meet, which is the most expensive mistake in
the process and the one the document already identifies. Every unit's route carries the SOP's tact
per workstation, so the hours are known — nothing read them.

**Actual against tact.** The same tact times are what the floor is measured against, and nobody
was measuring.

Pure: no database, no request, no clock. The caller passes `today`; tests pass a fixed date.

── What this refuses to guess ───────────────────────────────────────────────────────────────────

Five of the nine workstations are quoted PER SECTION ("30 - 90 min / section"). A unit's hours at
those stations therefore depend on how many sections it has — which the portal only knows if the
AeroSelect selection said so. Where the count is unknown the station's load is reported as
UNKNOWN with the reason, and is excluded from the total rather than defaulted to one section.
A load chart that quietly assumed one section per unit would understate the floor's commitment by
a factor of five to fifteen, and understating capacity is exactly how the date gets promised.

And "elapsed" is not "touch time". Steps carry a signature instant but no start instant, so what is
measurable today is the time BETWEEN consecutive sign-offs — which includes queueing, breaks and
overnight. It is reported under that name. Real hands-on duration needs a start stamp the shop
floor does not yet record; see cycle_note().
"""
import re
from datetime import date, datetime, timedelta

import ahu_route as R

UNKNOWN = "UNKNOWN"

# How a tact figure is quoted. The unit of work matters: "per section" multiplies by the section
# count, "per AHU" does not.
PER_UNIT = ("ahu",)
PER_SECTION = ("section", "coil section")
PER_PANEL = ("panel set", "panel")

_RANGE = re.compile(r"(\d+(?:\.\d+)?)\s*(?:-|–|to)\s*(\d+(?:\.\d+)?)\s*(min|h|hour|hr)\b", re.I)
_SINGLE = re.compile(r"(\d+(?:\.\d+)?)\s*(min|h|hour|hr)\b", re.I)
_PER = re.compile(r"/\s*([A-Za-z ]+)")


def _to_hours(v, unit):
    v = float(v)
    return v / 60.0 if unit.lower().startswith("min") else v


def parse_tact(tact):
    """{'lo': hours, 'hi': hours, 'per': 'ahu'|'section'|'panel set'|None} or None.

    Handles the three shapes the SOP uses: a range ("20 - 60 min / panel set"), a single figure
    ("30 min / AHU"), and the awkward one ("30 min cure (PU) / 15 min (rockwool)") where the slash
    separates two MATERIALS rather than naming a unit of work — that one takes the larger figure,
    because a load chart that assumes the faster material is a load chart that under-books.
    """
    if not tact:
        return None
    s = str(tact)
    m = _RANGE.search(s)
    if m:
        lo, hi = _to_hours(m.group(1), m.group(3)), _to_hours(m.group(2), m.group(3))
    else:
        figs = [_to_hours(a, b) for a, b in _SINGLE.findall(s)]
        if not figs:
            return None
        # Several single figures with no range means alternatives (PU vs rockwool). Book the worst.
        lo = hi = max(figs)
    per = None
    for m2 in _PER.finditer(s):
        w = m2.group(1).strip().lower()
        if any(k in w for k in PER_SECTION):
            per = "section"
        elif any(k in w for k in PER_PANEL):
            per = "panel set"
        elif any(k in w for k in PER_UNIT):
            per = "ahu"
        if per:
            break
    return {"lo": round(lo, 3), "hi": round(hi, 3), "per": per}


def unit_hours(unit, steps=None, only_remaining=True):
    """Planned hours per workstation for one unit, at the SOP's upper tact.

    Books the UPPER end of each range. A capacity chart exists to answer "can we take this on", and
    answering it from the optimistic end of every band is how a plan becomes a promise nobody keeps.

    `only_remaining` excludes stations already signed off — the load chart is about work still to do.
    """
    try:
        route = R.build_route(str(unit.get("family") or "modular").strip().lower(),
                              {"fat": bool(unit.get("fatRequired"))})
    except ValueError as exc:
        return {"total": 0.0, "stations": {}, "unknown": {"route": str(exc)}}

    done = {s.get("code") for s in (steps or [])
            if str(s.get("status") or "").strip().lower() in
            ("complete", "completed", "passed", "signed", "released")}
    sections = unit.get("sectionCount")
    try:
        sections = int(sections) if sections not in (None, "") else None
    except (TypeError, ValueError):
        sections = None

    stations, unknown, total = {}, {}, 0.0
    for st in route:
        if st.get("kind") != "op" or not st.get("tact"):
            continue
        if only_remaining and st["code"] in done:
            continue
        t = parse_tact(st["tact"])
        if not t:
            continue
        if t["per"] == "section":
            if not sections:
                unknown[st["code"]] = (
                    "quoted per section (%s) and this unit has no section count — import the "
                    "AeroSelect selection, which carries it" % st["tact"])
                continue
            hours = t["hi"] * sections
        elif t["per"] == "panel set":
            # A panel set is per section too in practice; without a count it is the same problem.
            if not sections:
                unknown[st["code"]] = (
                    "quoted per panel set (%s) and this unit has no section count" % st["tact"])
                continue
            hours = t["hi"] * sections
        else:
            hours = t["hi"]
        stations[st["code"]] = round(hours, 2)
        total += hours
    return {"total": round(total, 2), "stations": stations, "unknown": unknown}


# ── The rolling load chart (SOP 6.7) ─────────────────────────────────────────────────────────────
def _d(v):
    try:
        return datetime.strptime(str(v)[:10], "%Y-%m-%d").date()
    except (TypeError, ValueError):
        return None


def _monday(d):
    return d - timedelta(days=d.weekday())


def load_by_week(units, today, weeks=8):
    """Hours of remaining work per workstation per week, for the next `weeks` weeks.

    A unit's remaining hours are spread evenly across the weeks between today and its contracted
    delivery date. That is a deliberately simple model and it is stated as such: it answers "is the
    floor over-committed in week 5", not "which unit is on which machine on Tuesday". A real finite
    scheduler is a different piece of work, and a crude honest answer to the capacity question beats
    an elaborate one nobody trusts.

    A unit already past its date, or with no date, is reported separately rather than smeared across
    the horizon — those are the two cases the chart most needs to make visible.
    """
    today = _d(today) or date.today()
    start = _monday(today)
    buckets = [{"week": (start + timedelta(weeks=i)).isoformat(), "hours": 0.0, "units": 0,
                "stations": {}} for i in range(weeks)]
    overdue, undated, unknown = [], [], {}

    for u in units:
        unit = u.get("unit") or {}
        h = unit_hours(unit, u.get("steps"))
        if h["unknown"]:
            unknown[unit.get("pin") or unit.get("id")] = h["unknown"]
        if h["total"] <= 0:
            continue
        due = _d((u.get("order") or {}).get("deliveryDate"))
        if not due:
            undated.append({"pin": unit.get("pin"), "hours": h["total"]})
            continue
        if due < today:
            overdue.append({"pin": unit.get("pin"), "due": due.isoformat(), "hours": h["total"]})
            continue
        span = max(1, (_monday(due) - start).days // 7 + 1)
        share = h["total"] / span
        for i in range(min(span, weeks)):
            buckets[i]["hours"] = round(buckets[i]["hours"] + share, 2)
            buckets[i]["units"] += 1
            for code, hrs in h["stations"].items():
                buckets[i]["stations"][code] = round(
                    buckets[i]["stations"].get(code, 0.0) + hrs / span, 2)
    return {"weeks": buckets, "overdue": overdue, "undated": undated, "unknown": unknown}


def against_capacity(chart, weekly_capacity_h):
    """Mark each week over or under a stated capacity. Without a capacity, says so.

    Refusing to invent a default matters here: a chart drawn against a made-up capacity looks
    exactly like a chart drawn against a real one, and the whole point is to support a commitment.
    """
    if not weekly_capacity_h:
        return dict(chart, capacity=None,
                    note=("No weekly capacity is configured, so load is reported in hours without "
                          "a verdict. Set one to see which weeks are over-committed."))
    cap = float(weekly_capacity_h)
    for w in chart["weeks"]:
        w["capacity"] = cap
        w["utilisation"] = round(100.0 * w["hours"] / cap, 1) if cap else None
        w["over"] = w["hours"] > cap
    return dict(chart, capacity=cap)


# ── Actual against tact ──────────────────────────────────────────────────────────────────────────
def _ts(step):
    """The instant a step was signed, from its signature chain. `signedOn` is only a DATE."""
    for sig in reversed(step.get("signatures") or []):
        t = sig.get("ts")
        if t:
            try:
                return datetime.strptime(str(t)[:19], "%Y-%m-%dT%H:%M:%S")
            except ValueError:
                continue
    return None


def elapsed_between_signoffs(unit, steps):
    """Hours elapsed between each signed workstation and the one before it, against its tact band.

    ELAPSED, not touch time — it includes queueing, breaks and overnight, because a step records
    when it was signed and never when it was started. Named accordingly rather than presented as a
    cycle time it is not. It is still the most useful thing available: it shows where units SIT.
    """
    out = []
    signed = [s for s in sorted(steps or [], key=lambda x: (x.get("seq") or 0)) if _ts(s)]
    prev = None
    for s in signed:
        t = _ts(s)
        if prev is not None and s.get("kind") == "op" and s.get("tact"):
            hours = round((t - prev).total_seconds() / 3600.0, 2)
            band = parse_tact(s["tact"])
            row = {"code": s.get("code"), "title": s.get("title"), "elapsedH": hours,
                   "tact": s.get("tact")}
            if band:
                hi = band["hi"]
                if band["per"] in ("section", "panel set"):
                    n = unit.get("sectionCount")
                    hi = hi * int(n) if n else None
                row["tactHiH"] = round(hi, 2) if hi else None
                row["overTact"] = (hi is not None and hours > hi)
                if hi is None:
                    row["note"] = "tact is per section and this unit has no section count"
            out.append(row)
        prev = t
    return out


# ── Units that have stopped moving ──────────────────────────────────────────────────────────────
# Every alert this module's callers raise fires on something that went WRONG: a step failed, a gate
# was held, a non-conformance aged. None of them fires on work that simply STOPPED. A unit can sit
# untouched for a fortnight and nobody is told, because nothing failed and no gate refused it — and
# on a board, a unit stuck at 40% looks identical on Monday to how it looked last Monday.
#
# Silence is the commonest failure mode on a shop floor, and it is the one the screens hide.

MOVING = "MOVING"            # signed something recently enough
STALLED = "STALLED"          # nothing signed for longer than the threshold
NEVER_STARTED = "NEVER_STARTED"   # route exists, nothing signed on it, ever
UNDATEABLE = "UNDATEABLE"    # something is signed but no signature carries a readable instant


def stall_state(steps, today, threshold_days):
    """How long since anything on this unit was signed. {status, days, lastCode, lastAt}.

    Three refusals, and they are the whole point of the function:

    NEVER_STARTED is not "stalled for N days". A unit nobody has begun and a unit abandoned midway
    are different problems with different owners — the first belongs to planning, the second to the
    floor — and folding them together sends the wrong person to look. It carries no day count,
    because there is no signature to count from and the order date is not a promise that work began.

    UNDATEABLE is not zero days. A signature whose instant cannot be read means the clock cannot be
    started, and reporting that as "0 days since last movement" would present the unit as the
    healthiest on the board. Same rule as the ncr sweep's unaged count.

    `days` is ELAPSED calendar days, weekends and holidays included. That is deliberate: a unit does
    not care why nobody touched it, and a working-day calendar this module does not have would be
    invented arithmetic. State it plainly wherever the number is shown.
    """
    signed = [s for s in (steps or []) if _ts(s)]
    if not signed:
        # Distinguish "nothing signed and no signature attempted" from "signed but undateable".
        any_signature = any((s.get("signatures") or s.get("signedBy") or s.get("signedOn"))
                            for s in (steps or []))
        return {"status": UNDATEABLE if any_signature else NEVER_STARTED,
                "days": None, "lastCode": None, "lastAt": None}
    last = max(signed, key=lambda s: _ts(s))
    at = _ts(last)
    d = _d(today)
    if d is None:
        return {"status": UNDATEABLE, "days": None,
                "lastCode": last.get("code"), "lastAt": at.isoformat()}
    days = (d - at.date()).days
    if days < 0:
        # A signature stamped in the future cannot be aged. Refuse rather than report a negative.
        return {"status": UNDATEABLE, "days": None,
                "lastCode": last.get("code"), "lastAt": at.isoformat()}
    return {"status": STALLED if days >= threshold_days else MOVING, "days": days,
            "lastCode": last.get("code"), "lastAt": at.isoformat()}


def stalled_units(rows, today, threshold_days):
    """Every live unit that has stopped, longest-stopped first, plus what could not be judged.

    `rows` is [{unit, steps}] for the units the caller considers live — dispatched and cancelled
    ones are the caller's to exclude, because "live" is a status question and this module is pure.

    Returns {threshold, stalled: [...], neverStarted: [...], undateable: [...]}. The last two are
    SEPARATE lists rather than a silent omission: a unit nobody can age is exactly the unit most
    worth looking at, and dropping it would make the alert quieter the worse the data got.
    """
    out = {"threshold": threshold_days, "stalled": [], "neverStarted": [], "undateable": []}
    for r in rows or []:
        unit = r.get("unit") or {}
        st = stall_state(r.get("steps"), today, threshold_days)
        row = {"unitId": unit.get("id"), "pin": unit.get("pin"), "tag": unit.get("tag"),
               "orderId": unit.get("orderId"), "days": st["days"],
               "lastCode": st["lastCode"], "lastAt": st["lastAt"]}
        if st["status"] == STALLED:
            out["stalled"].append(row)
        elif st["status"] == NEVER_STARTED:
            out["neverStarted"].append(row)
        elif st["status"] == UNDATEABLE:
            out["undateable"].append(row)
    out["stalled"].sort(key=lambda r: -(r["days"] or 0))
    return out


def cycle_note():
    """Why elapsed is the honest measure today, and what would make touch time possible."""
    return ("A step records the instant it was SIGNED and never the instant it was STARTED, so what "
            "can be measured is the elapsed time between consecutive sign-offs — queueing, breaks "
            "and overnight included. To measure real hands-on duration the shop floor would have to "
            "record a start, which is a change to how people work, not just to the schema.")
