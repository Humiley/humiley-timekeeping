"""Where the labour actually goes, and why it varies.

AHU-SOP-MASTER-001 quotes a tact band for every workstation, and the bands are wide: WS-04 Section
Assembly is "1 - 4 h / section". Summed over a four-section modular unit that means the *same* unit
is somewhere between **19.3 and 49.0 hours** — a 2.5x range, 61% of the total.

That spread is not physics. It is preparation, kitting, interruption and rework, and closing it is
worth more than any machine the company could buy. But it cannot be closed without knowing where in
the band each station actually runs, and on which units it runs long. That is what this module
computes.

Pure: steps and specs in, numbers out. No database, no clock.

── Two things this refuses to conflate ──────────────────────────────────────────────────────────

**Touch time is not elapsed time.** A step records when it was SIGNED. If it also records when work
STARTED, the difference is real hands-on duration; if it does not, all that can be known is the gap
since the previous sign-off, which includes queueing, breaks and overnight. Those are different
numbers with different uses — the first tells you what a job costs, the second tells you where units
sit — and this module reports them under different names and never substitutes one for the other.

**The critical path is what the route DECLARES, not what is physically necessary.** `parallel_floor`
computes what the same work would take if steps that do not depend on each other ran together. That
is a question for whoever knows the shop floor, not an assertion that they can. It is labelled as
such everywhere it is returned.
"""
import ahu_capacity as C

# Where a measured duration falls inside its own tact band.
FAST = "FAST"            # at or below the quick end
MID = "MID"
SLOW = "SLOW"            # at or near the slow end, still inside
OVER = "OVER"            # past the slow end of the band
UNKNOWN = "UNKNOWN"      # cannot be judged — no band, or no section count for a per-section band

# The causes worth offering when a step ran past its tact. Deliberately short: a list nobody reads
# gets the first option every time, and "Other" with a note is more honest than a wrong category.
DELAY_REASONS = [
    "Waiting for material or a part",
    "Waiting for a drawing or a decision",
    "Waiting for the previous station",
    "Rework on this unit",
    "Tooling or equipment problem",
    "Operator not available",
    "Design or spec change mid-build",
    "Other — see the note",
]


def _mult(band, sections):
    """How many times the band applies. None when it is per-section and we have no count."""
    if band["per"] in ("section", "panel set"):
        try:
            n = int(sections)
        except (TypeError, ValueError):
            return None
        return n if n > 0 else None
    return 1


def band_position(tact, hours, sections=None):
    """Where `hours` sits inside the step's own tact band.

    Returns {status, lo, hi, ratio, why}. `ratio` is hours ÷ the slow end, so 1.0 is exactly at
    tact and 0.25 is running at the quick end of a 4x band.

    A per-section band with no section count is UNKNOWN, not assumed to be one section — the same
    refusal the capacity chart makes, and for the same reason: assuming one would make a five-section
    unit look five times worse than it is.
    """
    band = C.parse_tact(tact)
    if not band or hours is None:
        return {"status": UNKNOWN, "lo": None, "hi": None, "ratio": None,
                "why": "No tact band on this step." if not band else "No measured duration."}
    n = _mult(band, sections)
    if n is None:
        return {"status": UNKNOWN, "lo": None, "hi": None, "ratio": None,
                "why": ("This tact is quoted per section and the unit has no section count, so the "
                        "band cannot be scaled to it.")}
    lo, hi = round(band["lo"] * n, 2), round(band["hi"] * n, 2)
    ratio = round(hours / hi, 2) if hi else None
    if hours > hi:
        st, why = OVER, "%.1f h against a band of %.1f–%.1f h." % (hours, lo, hi)
    elif hours <= lo:
        st, why = FAST, "%.1f h — at or inside the quick end (%.1f h)." % (hours, lo)
    elif hi and hours >= lo + 0.75 * (hi - lo):
        st, why = SLOW, "%.1f h — near the slow end (%.1f h)." % (hours, hi)
    else:
        st, why = MID, "%.1f h — mid-band (%.1f–%.1f h)." % (hours, lo, hi)
    return {"status": st, "lo": lo, "hi": hi, "ratio": ratio, "why": why}


# ── Touch time ──────────────────────────────────────────────────────────────────────────────────

def touch_hours(step):
    """Hands-on hours, or None when the step records no start.

    None is the honest answer and must stay distinguishable from 0.0: a step nobody started and a
    step that took no time are different facts, and a report that shows both as zero would make the
    first invisible exactly where it matters.
    """
    a = _ts(step.get("startedAt") or step.get("startedOn"))
    b = _ts(step.get("signedAt")) or _sig_ts(step)
    if not a or not b or b < a:
        return None
    return round((b - a).total_seconds() / 3600.0, 2)


def _ts(v):
    from datetime import datetime
    s = str(v or "")[:19]
    for fmt in ("%Y-%m-%dT%H:%M:%S", "%Y-%m-%d %H:%M:%S"):
        try:
            return datetime.strptime(s, fmt)
        except ValueError:
            continue
    return None


def _sig_ts(step):
    for sig in reversed((step or {}).get("signatures") or []):
        t = _ts(sig.get("ts"))
        if t:
            return t
    return None


# ── Per station, across every unit ──────────────────────────────────────────────────────────────

def station_performance(rows):
    """One row per workstation: how it runs against its own band, over every measured instance.

    `rows` is [{code, tact, hours, sections, unitId, pin, source}] where `source` is "touch" or
    "elapsed" — kept per row so a station measured both ways does not silently average them into a
    number that is neither.
    """
    by = {}
    for r in rows or []:
        code = r.get("code")
        if not code:
            continue
        pos = band_position(r.get("tact"), r.get("hours"), r.get("sections"))
        g = by.setdefault(code, {"code": code, "tact": r.get("tact"), "n": 0, "judged": 0,
                                 "over": 0, "fast": 0, "ratios": [], "worst": None,
                                 "sources": set()})
        g["n"] += 1
        g["sources"].add(r.get("source") or "elapsed")
        if pos["status"] == UNKNOWN:
            continue
        g["judged"] += 1
        if pos["ratio"] is not None:
            g["ratios"].append(pos["ratio"])
        if pos["status"] == OVER:
            g["over"] += 1
            if g["worst"] is None or (r.get("hours") or 0) > g["worst"]["hours"]:
                g["worst"] = {"unitId": r.get("unitId"), "pin": r.get("pin"),
                              "hours": r.get("hours"), "why": pos["why"]}
        if pos["status"] == FAST:
            g["fast"] += 1

    out = []
    for g in by.values():
        rs = sorted(g["ratios"])
        g["median"] = rs[len(rs) // 2] if rs else None
        g["sources"] = sorted(g["sources"])
        g.pop("ratios", None)
        # A station judged on nothing has no opinion to offer. Saying so beats a blank cell that
        # reads as "fine".
        g["note"] = ("Not enough measured runs to say anything." if g["judged"] == 0 else "")
        out.append(g)
    return sorted(out, key=lambda g: (g["median"] is None, -(g["median"] or 0)))


def delay_causes(steps):
    """The recorded reasons a step ran long, commonest first — the point of asking at all."""
    counts = {}
    for s in steps or []:
        why = str((s or {}).get("delayReason") or "").strip()
        if why:
            counts[why] = counts.get(why, 0) + 1
    return sorted(({"reason": k, "count": v} for k, v in counts.items()),
                  key=lambda r: -r["count"])


# ── The shape of the route ──────────────────────────────────────────────────────────────────────

def _op_hours(spec, sections):
    band = C.parse_tact(spec.get("tact") or "")
    if not band:
        return 0.0
    n = _mult(band, sections)
    return band["hi"] * (n if n is not None else 1)


def critical_path(specs, sections):
    """The longest chain of work the route as DECLARED forces to happen one after another.

    Every step waits on its `after` list, so this is the earliest the unit can finish however many
    people are on it. Where the chain is strictly linear — as stage 5 currently is — the critical
    path IS the total, which is the finding worth surfacing.
    """
    by = {s["code"]: s for s in specs}
    memo = {}

    def finish(code):
        if code in memo:
            return memo[code]
        s = by.get(code)
        if not s:
            return 0.0
        memo[code] = 0.0                       # guards a cycle rather than recursing forever
        start = max([finish(a) for a in (s.get("after") or []) if a in by] or [0.0])
        memo[code] = start + _op_hours(s, sections)
        return memo[code]

    for c in by:
        finish(c)
    total = sum(_op_hours(s, sections) for s in specs)
    path_len = max(memo.values() or [0.0])
    return {"criticalPathH": round(path_len, 1), "totalWorkH": round(total, 1),
            "serialShare": round(100.0 * path_len / total, 0) if total else None}


def parallel_floor(specs, sections, independent=()):
    """What the route would take if the named steps did NOT wait on their predecessors.

    A QUESTION, not a claim. This module has no way to know whether a control panel can be built
    while the casing is assembled — that is knowledge held by whoever runs the floor. What it can do
    is price the answer, so the conversation starts from a number instead of an impression.
    """
    lifted = set(independent or ())
    trimmed = [dict(s, after=[] if s["code"] in lifted else s.get("after")) for s in specs]
    before = critical_path(specs, sections)
    after = critical_path(trimmed, sections)
    return {"before": before["criticalPathH"], "after": after["criticalPathH"],
            "savedH": round(before["criticalPathH"] - after["criticalPathH"], 1),
            "lifted": sorted(lifted),
            "caveat": ("Assumes these steps can genuinely run alongside the rest, which is a "
                       "question for the production lead — this only prices the answer.")}


# ── What a unit costs, and why a small one costs so much ────────────────────────────────────────

def fixed_vs_variable(specs, sections):
    """Labour that scales with the unit against labour that does not.

    The per-AHU stations cost the same on a one-section unit as on a twelve-section one. That is why
    a small unit is disproportionately expensive, and it is invisible if a quote is priced per unit
    rather than per section.
    """
    fixed = variable = 0.0
    for s in specs:
        band = C.parse_tact(s.get("tact") or "")
        if not band:
            continue
        if band["per"] in ("section", "panel set"):
            n = _mult(band, sections)
            if n is None:
                continue
            variable += band["hi"] * n
        else:
            fixed += band["hi"]
    total = fixed + variable
    return {"fixedH": round(fixed, 1), "variableH": round(variable, 1),
            "totalH": round(total, 1),
            "fixedPct": round(100.0 * fixed / total, 0) if total else None,
            "perSectionH": round(variable / sections, 1) if sections else None}


def spread(specs, sections):
    """Best case against worst case, using the two ends of the SOP's own bands.

    The gap between them is the prize: it is the same unit, the same standard, and the difference is
    method rather than physics.
    """
    lo = hi = 0.0
    worst = []
    for s in specs:
        band = C.parse_tact(s.get("tact") or "")
        if not band:
            continue
        n = _mult(band, sections)
        if n is None:
            continue
        a, b = band["lo"] * n, band["hi"] * n
        lo += a
        hi += b
        if b > a:
            worst.append({"code": s["code"], "title": s.get("title"), "fastH": round(a, 1),
                          "slowH": round(b, 1), "ratio": round(b / a, 1) if a else None,
                          "costH": round(b - a, 1)})
    worst.sort(key=lambda r: -r["costH"])
    return {"bestH": round(lo, 1), "worstH": round(hi, 1), "spreadH": round(hi - lo, 1),
            "spreadPct": round(100.0 * (hi - lo) / hi, 0) if hi else None,
            "stations": worst}
