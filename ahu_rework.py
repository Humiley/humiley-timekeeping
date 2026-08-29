"""Which workstations generate the rework.

Every non-conformance already records **where it was found** (`stepCode`) and **what was decided**
(`disposition`). Nothing has ever aggregated those two fields together, so the one question that
tells a production manager where to fix the process — *which stations produce our rework?* — has had
no answer, while the data to answer it was being typed in all along.

Nothing here asks the floor for anything new. That is the point: a report that needs fresh data entry
competes with the work, and loses.

── What this deliberately does NOT report ───────────────────────────────────────────────────────

**Cost, and hours.** The non-conformance form has no field for either. A rework figure in money or
hours would have to be invented — from a tact band, a nominal rate, an assumption about how long a
repair takes — and a fabricated cost put in front of a pricing decision is worse than an empty
column, because it will be believed. This reports FREQUENCY, says so in its own note, and names the
field that would have to exist before cost could follow.

**A rate per station.** "12% of units through WS-04 needed rework" needs a denominator: how many
units passed through that station. A unit's route is built per family and steps are skippable, so
that denominator is a real computation and not the count of units in the register. Until it is done
properly this reports counts against a stated total, not a percentage that looks authoritative and
is not.

── The refusal ──────────────────────────────────────────────────────────────────────────────────

An NCR with **no** `stepCode` is not attributed to any station. It is counted, named and reported
separately. Spreading it, defaulting it to the unit's current step, or dropping it would each make
some station look worse or better than the record supports — and the unattributed count is itself
the useful signal, because it says how much of the picture is missing.
"""

# Dispositions that mean the unit was WORKED ON AGAIN. "Use as is" and "Reject" are decisions too,
# and both are reported, but neither is rework: one accepts the deviation and the other scraps it.
REWORK_DISPOSITIONS = {"rework", "repair"}
DECISIONS = ("rework", "repair", "use as is", "reject")

UNATTRIBUTED = "(no step recorded)"


def _norm(v):
    return str(v or "").strip().lower()


def _step_of(ncr):
    """The station an NCR was found at, or None. Never guessed at."""
    s = str((ncr or {}).get("stepCode") or "").strip()
    return s or None


def by_station(units):
    """Non-conformances grouped by the station they were found at, worst first.

    `units` is [{unit, ncr}] — the same row shape the KPI and board endpoints already build.

    Each row: {code, rework, useAsIs, reject, undecided, total, units, pins}. Sorted by rework
    count descending, because the question being asked is "where do we lose time", and a station
    with one use-as-is is not the answer to it.
    """
    by = {}
    unattributed = 0
    for u in units or []:
        pin = (u.get("unit") or {}).get("pin") or (u.get("unit") or {}).get("id") or ""
        for n in (u.get("ncr") or []):
            if _norm(n.get("kind")) == "punch":
                continue          # snagging, not a non-conformance — the same rule the sweeps use
            code = _step_of(n)
            if code is None:
                unattributed += 1
                code = UNATTRIBUTED
            g = by.setdefault(code, {"code": code, "rework": 0, "useAsIs": 0, "reject": 0,
                                     "undecided": 0, "total": 0, "pins": set()})
            g["total"] += 1
            g["pins"].add(pin)
            d = _norm(n.get("disposition"))
            if d in REWORK_DISPOSITIONS:
                g["rework"] += 1
            elif d == "use as is":
                g["useAsIs"] += 1
            elif d == "reject":
                g["reject"] += 1
            else:
                # Open, or closed without anybody recording what was decided. Not counted as rework
                # — that would be inventing the disposition — but not hidden either, because an NCR
                # nobody dispositioned is its own problem.
                g["undecided"] += 1

    out = []
    for g in by.values():
        g["units"] = len(g["pins"])
        g["pins"] = sorted(p for p in g["pins"] if p)
        out.append(g)
    # Worst first, and the unattributed bucket last whatever its size — it is a data-quality row,
    # not a station, and ranking it among the stations would read as an accusation of one.
    out.sort(key=lambda g: (g["code"] == UNATTRIBUTED, -g["rework"], -g["total"], g["code"]))
    return {"stations": out, "unattributed": unattributed}


def summary(units):
    """The whole picture, with the caveats attached to the numbers rather than left to a reader."""
    grouped = by_station(units)
    stations = grouped["stations"]
    rework = sum(g["rework"] for g in stations)
    total = sum(g["total"] for g in stations)
    worst = next((g for g in stations if g["code"] != UNATTRIBUTED and g["rework"]), None)
    return {
        "stations": stations,
        "unattributed": grouped["unattributed"],
        "reworkTotal": rework,
        "ncrTotal": total,
        "unitsWithRework": len({p for g in stations for p in g["pins"] if g["rework"]}),
        "worstStation": worst["code"] if worst else None,
        # Said here, next to the figures, rather than in documentation somebody will not read.
        "note": ("Counts, not cost: the non-conformance form records no hours and no money, so a "
                 "rework cost would have to be invented. Add an hours field to cost this. "
                 "Nor is it a rate — that needs how many units actually passed through each "
                 "station, which the route makes a real computation rather than a unit count."),
    }
