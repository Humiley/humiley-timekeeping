"""The review pack for a whole ORDER, not one unit at a time.

A customer buys an order of N air handling units. An auditor, a client's inspector and the person
signing the handover all review the ORDER — and until now the portal only ever answered per unit, so
reviewing a package of eight meant opening eight dossiers and holding the result in your head. The
per-unit dossier is still the evidence; this is the covering answer that says whether the evidence
adds up and, when it does not, exactly which unit to open.

It answers one question — **can this order be handed over?** — and when the answer is no it names
every reason, per unit, in the order somebody would work through them.

Pure: units and their records in, verdict out. No database, no clock, no request.

── The trap this is written around ──────────────────────────────────────────────────────────────

`all(u["dispatched"] for u in units)` is **True for an empty list**. Written the obvious way, an
order with no units registered against it reports itself READY TO HAND OVER — the most confident
possible answer about nothing at all, produced by a rule that never looked at a unit.

That is the same vacuous truth that makes an empty test suite pass. So readiness here is never a
bare `all()`: an order with no units is NOT_READY with the reason "no units", and the count of units
the verdict is based on travels with the verdict so a reader can see what it was computed over.

── What it refuses to average ───────────────────────────────────────────────────────────────────

There is no "order 87% complete". A package is handed over whole; seven finished units and one
stuck at framing is not 87% of a handover, it is a handover that cannot happen. Progress per unit is
reported, the count ready is reported, and the single figure that would let somebody round the
problem away is not.
"""

READY = "READY"
NOT_READY = "NOT_READY"
NOTHING_TO_REVIEW = "NOTHING_TO_REVIEW"   # an order with no units — a different answer, not a no

# Statuses that mean the unit has left the factory.
_GONE = ("dispatched", "closed")


def _norm(v):
    return str(v or "").strip().lower()


def _is_dispatched(row):
    """Shipped: a dispatch record exists, or the unit itself says so.

    Both are checked because the two can disagree — a unit marked Dispatched with no dispatch record
    has no packing evidence, and that IS the finding, so it is reported rather than resolved here.
    """
    if row.get("dispatch"):
        return True
    return _norm((row.get("unit") or {}).get("status")) in _GONE


def unit_row(row):
    """One line about one unit: where it is, and what is holding it.

    `blockers` is every reason this unit is not ready to hand over, as sentences. An empty list means
    nothing is holding it — which is not the same as "it shipped", and both are reported.
    """
    unit = row.get("unit") or {}
    steps = row.get("steps") or []
    ncr = row.get("ncr") or []
    state = row.get("state") or {}

    open_ncr = [n for n in ncr
                if _norm(n.get("kind")) != "punch"
                and _norm(n.get("status")) not in ("closed", "verified", "accepted")]
    failed = [s.get("code") for s in steps if _norm(s.get("status")) in ("failed", "held")]
    unsigned = [s.get("code") for s in steps
                if s.get("kind") == "gate"
                and _norm(s.get("status")) not in ("complete", "completed", "passed", "signed",
                                                   "released")]
    dispatched = _is_dispatched(row)

    blockers = []
    # A unit whose route cannot be built is a BLOCKER, never a skip. Skipping it would let an
    # unreadable unit ride along inside a package somebody then signs for.
    if state.get("routeError"):
        blockers.append("Its route cannot be built (%s), so nothing about it has been checked."
                        % state["routeError"])
    if failed:
        blockers.append("Failed or held: %s." % ", ".join(sorted(c for c in failed if c)))
    if open_ncr:
        blockers.append("%d non-conformance(s) still open." % len(open_ncr))
    if unsigned:
        blockers.append("Gates not signed: %s." % ", ".join(sorted(c for c in unsigned if c)))
    if not dispatched:
        blockers.append("Not dispatched.")
    elif not row.get("dispatch"):
        # Marked gone with no packing record — the evidence is missing, which is the finding.
        blockers.append("Marked as shipped but carries no dispatch record.")

    return {
        "unitId": unit.get("id"), "pin": unit.get("pin"), "tag": unit.get("tag"),
        "family": unit.get("family"),
        "progress": state.get("progress"),
        "stage": state.get("stage"), "stageTitle": state.get("stageTitle"),
        "openNcr": len(open_ncr), "failed": sorted(c for c in failed if c),
        "unsignedGates": sorted(c for c in unsigned if c),
        "dispatched": dispatched,
        "routeError": state.get("routeError"),
        "blockers": blockers,
        "ready": not blockers,
    }


def pack(order, rows):
    """The covering answer for one order.

    `rows` is [{unit, steps, ncr, dispatch, state}] for the units on this order — the caller decides
    which units belong to it, because that is a database question.
    """
    units = [unit_row(r) for r in (rows or [])]

    if not units:
        # NOT a ready order. `all([])` is True, and an order with no units reporting itself ready to
        # hand over would be the most confident possible answer about nothing at all.
        return {
            "order": order or {},
            "units": [], "unitCount": 0,
            "status": NOTHING_TO_REVIEW,
            "ready": False,
            "why": ["No units are registered against this order, so there is nothing to review "
                    "and nothing to hand over."],
            "counts": {"ready": 0, "blocked": 0, "dispatched": 0, "unroutable": 0, "openNcr": 0},
            "note": _NOTE,
        }

    blocked = [u for u in units if not u["ready"]]
    why = []
    for u in blocked:
        label = u["pin"] or u["unitId"] or "(unnamed unit)"
        for b in u["blockers"]:
            why.append("%s — %s" % (label, b))

    return {
        "order": order or {},
        "units": units,
        "unitCount": len(units),
        "status": READY if not blocked else NOT_READY,
        # Every unit, never a majority and never a percentage: a package is handed over whole.
        "ready": not blocked,
        "why": why,
        "counts": {
            "ready": len(units) - len(blocked),
            "blocked": len(blocked),
            "dispatched": len([u for u in units if u["dispatched"]]),
            "unroutable": len([u for u in units if u["routeError"]]),
            "openNcr": sum(u["openNcr"] for u in units),
        },
        "note": _NOTE,
    }


_NOTE = ("Every unit must be ready, not most of them — a package is handed over whole, and there is "
         "deliberately no single completeness percentage, because seven finished units and one stuck "
         "at framing is not 87% of a handover. The per-unit dossier remains the evidence; this says "
         "whether it adds up and which unit to open when it does not.")
