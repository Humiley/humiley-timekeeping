"""The eight KPIs AHU-SOP-MASTER-001 section 1.4 defines, computed from signed production data.

The SOP has always specified these — definition, target and owning function — and nothing computed
any of them. They were a table in a Word file. This module makes them arithmetic over records that
were e-signed at the moment the work happened, which is the difference between a KPI and a number
somebody typed into a monthly slide.

It is pure: no database, no request, no clock. Callers pass the units, their steps and their orders;
tests/test_ahu_kpi.py exercises every rule.

── The one that needed thought ──────────────────────────────────────────────────────────────────

Four of the eight ask for the EN 1886 class **ACHIEVED**, not whether the unit passed. Those are
different questions, and the difference matters commercially:

    sold as L1 (<= 0.15), measured 0.30  ->  FAILS its contract, and ACHIEVED L2

The unit is a warranty problem and the casing line is performing to L2. A pass/fail figure answers
neither question. So the measurement is CLASSIFIED against the published table — the same table
AeroSelect sells against and the factory tests against — and the KPI reports the distribution of
classes actually achieved.

── The three this cannot compute, and says so ───────────────────────────────────────────────────

Thermal bridging and thermal transmittance are in the SOP's KPI table but there is NO test for
either in the production route: EN 1886 TB and T are established on a test rig with a thermal
camera and a calibrated chamber, not on the line. Customer complaints are not captured anywhere in
the portal.

Those three report NOT_MEASURED with the reason, and are excluded from any roll-up. A KPI dashboard
that quietly showed 100% for a thing nothing measures would be the worst possible version of this
module — it is the exact defect the rest of it exists to prevent.
"""
import ahu_route as R

# Statuses that mean a step was signed off as good. Mirrors ahu.is_passed; duplicated deliberately
# so this module stays free of the database layer.
PASSED = {"complete", "completed", "passed", "signed", "released"}
FAILED = {"failed", "held"}

NOT_MEASURED = "NOT_MEASURED"


def _norm(v):
    return str(v or "").strip().lower()


def _num(v):
    try:
        if v is None or (isinstance(v, str) and not v.strip()):
            return None
        return float(v)
    except (TypeError, ValueError):
        return None


# ── Classifying a measurement ────────────────────────────────────────────────────────────────────
# "The class achieved", which is what the SOP's KPI asks for. Ordered best-first; the first class
# whose threshold the reading meets is the class achieved.
def classify(value, table, better_is_lower=True):
    """The EN 1886 class a reading achieves, or None if it achieves none of them.

    `table` is one of ahu_route's EN1886_* dicts. Returns the class code. A reading worse than every
    class returns None — which is a real outcome, not an error: a casing can leak more than L3
    allows, and reporting that as L3 would flatter it.
    """
    v = _num(value)
    if v is None:
        return None
    items = sorted(table.items(), key=lambda kv: kv[1], reverse=not better_is_lower)
    for cls, threshold in items:
        if better_is_lower and v <= threshold:
            return cls
        if not better_is_lower and v >= threshold:
            return cls
    return None


def class_rank(cls, table):
    """Position of a class in its table, best = 0. Used to test 'L2 or better'."""
    if not cls:
        return None
    order = sorted(table, key=lambda c: table[c])
    return order.index(cls) if cls in order else None


def meets_or_better(achieved, target, table):
    """Is `achieved` the same as `target` or better? None when it cannot be told."""
    a, t = class_rank(achieved, table), class_rank(target, table)
    if a is None or t is None:
        return None
    return a <= t


# ── The measured-class KPIs ──────────────────────────────────────────────────────────────────────
def _reading(steps, code, key):
    for s in steps or []:
        if s.get("code") == code and _norm(s.get("status")) in PASSED:
            r = s.get("readings")
            if isinstance(r, dict):
                return _num(r.get(key))
    return None


def casing_class_achieved(units):
    """Distribution of D and L classes actually achieved, over units whose test is signed.

    `units` is a list of {"unit": {...}, "steps": [...]}. Only SIGNED tests count: an unsigned
    reading is a number somebody typed, not a result.
    """
    out = {"D": {"n": 0, "classes": {}, "meets_target": 0},
           "L": {"n": 0, "classes": {}, "meets_target": 0}}
    for u in units:
        steps = u.get("steps") or []
        unit = u.get("unit") or {}
        for kind, code, key, table in (
                ("D", "T2", "deflection", R.EN1886_STRENGTH),
                ("L", "T3", "leak_neg400", R.EN1886_LEAK_NEG400)):
            v = _reading(steps, code, key)
            if v is None:
                continue
            achieved = classify(v, table)
            out[kind]["n"] += 1
            out[kind]["classes"][achieved or "worse than class"] = \
                out[kind]["classes"].get(achieved or "worse than class", 0) + 1
            target = unit.get("class" + kind)
            if meets_or_better(achieved, target, table):
                out[kind]["meets_target"] += 1
    return out


# ── First-Pass Yield ─────────────────────────────────────────────────────────────────────────────
def first_pass_yield(units):
    """SOP 1.4: units passing all in-process and final QC WITHOUT REWORK.

    A unit counts once it has reached QC — i.e. its production gate G4 is signed. Before that it has
    not had the chance to pass or fail, and counting it would dilute the figure with work in
    progress. A unit is first-pass if no IPQC or test step was ever recorded Failed or Held, and no
    non-conformance dispositioned as rework or repair was raised against it.
    """
    eligible = passed = 0
    for u in units:
        steps = u.get("steps") or []
        if not any(s.get("code") == "G4" and _norm(s.get("status")) in PASSED for s in steps):
            continue
        eligible += 1
        failed_step = any(_norm(s.get("status")) in FAILED
                          and s.get("kind") in ("ipqc", "test") for s in steps)
        reworked = any(_norm(n.get("disposition")) in ("rework", "repair")
                       for n in (u.get("ncr") or []))
        if not failed_step and not reworked:
            passed += 1
    return {"n": eligible, "passed": passed,
            "pct": round(100.0 * passed / eligible, 1) if eligible else None}


# ── On-Time Delivery ─────────────────────────────────────────────────────────────────────────────
def on_time_delivery(units):
    """SOP 1.4: orders shipped on or before the confirmed date.

    Measured per DISPATCHED unit against its order's contracted delivery date. A unit with no
    dispatch record has not shipped and is not counted — including it as late would report a figure
    about the future.
    """
    shipped = ontime = 0
    late = []
    for u in units:
        disp = (u.get("dispatch") or [{}])[0] if u.get("dispatch") else {}
        when = str(disp.get("dispatchedOn") or "").strip()
        due = str((u.get("order") or {}).get("deliveryDate") or "").strip()
        if not when:
            continue
        shipped += 1
        if not due:
            continue                       # shipped, but nothing to measure against
        if when <= due:                    # ISO dates compare correctly as strings
            ontime += 1
        else:
            late.append({"pin": (u.get("unit") or {}).get("pin"), "due": due, "shipped": when})
    return {"n": shipped, "onTime": ontime, "late": late,
            "pct": round(100.0 * ontime / shipped, 1) if shipped else None}


# ── The same two KPIs, month by month ───────────────────────────────────────────────────────────
# A single figure says where you are. It cannot say whether you are getting better, which is the
# only question a KPI is any use for. Eight numbers on a screen with no history is a dashboard
# nobody returns to twice.
#
# Two decisions worth stating, because both could reasonably have gone the other way.
#
# EACH KPI IS BUCKETED BY ITS OWN EVENT, not by a single shared date. First-pass yield is bucketed
# on the month the unit reached QC — the moment it became eligible to pass or fail — and on-time
# delivery on the month it shipped. Bucketing both on dispatch would drop every unit that has been
# inspected but not yet shipped out of the yield series, which is precisely the most recent and most
# interesting data.
#
# A MONTH WITH TOO FEW UNITS IS LABELLED, NOT HIDDEN. One unit failing in a month of two is 50%, and
# drawn on a chart next to a month of forty it looks like a collapse. The count travels with every
# point and `enough` says whether the percentage can be read at all; suppressing the point entirely
# would leave a gap that reads as "no problem" rather than "not enough evidence".

MIN_N_TO_READ = 5      # below this a percentage is noise. Reported, and flagged as unreadable.


def _month(v):
    """The YYYY-MM a date string falls in, or None. Never guesses at an unparseable value."""
    s = str(v or "").strip()[:7]
    if len(s) == 7 and s[4] == "-" and s[:4].isdigit() and s[5:7].isdigit():
        return s
    return None


def _step_month(steps, code):
    """The month a named step was signed, from its date or its signature chain."""
    for s in steps or []:
        if s.get("code") != code or _norm(s.get("status")) not in PASSED:
            continue
        m = _month(s.get("signedOn"))
        if m:
            return m
        for sig in reversed(s.get("signatures") or []):
            m = _month(sig.get("ts"))
            if m:
                return m
    return None


def _series(buckets, months):
    """Buckets to an ordered series, most recent `months` of them, oldest first."""
    out = []
    for m in sorted(buckets)[-months:] if months else sorted(buckets):
        n, good = buckets[m]
        out.append({"month": m, "n": n, "good": good,
                    "pct": round(100.0 * good / n, 1) if n else None,
                    "enough": n >= MIN_N_TO_READ})
    return out


def monthly(units, months=12):
    """First-pass yield and on-time delivery as a series, oldest first.

    Pure, like the rest of this module: the months come from the DATA, not from a clock, so the
    series ends at the last month something actually happened rather than trailing empty months
    that look like a stoppage.

    `unbucketed` counts units that qualify for a KPI but carry no readable date to file them under.
    They are named rather than dropped — a trend quietly computed over the subset with good dates
    would move whenever the record-keeping changed, and would look like a change in performance.
    """
    fpy, otd = {}, {}
    un_fpy = un_otd = 0

    for u in units or []:
        steps = u.get("steps") or []

        # First-pass yield: bucketed on the month the unit reached QC.
        if any(s.get("code") == "G4" and _norm(s.get("status")) in PASSED for s in steps):
            m = _step_month(steps, "G4")
            if m is None:
                un_fpy += 1
            else:
                failed_step = any(_norm(s.get("status")) in FAILED
                                  and s.get("kind") in ("ipqc", "test") for s in steps)
                reworked = any(_norm(n.get("disposition")) in ("rework", "repair")
                               for n in (u.get("ncr") or []))
                n, good = fpy.get(m, (0, 0))
                fpy[m] = (n + 1, good + (0 if (failed_step or reworked) else 1))

        # On-time delivery: bucketed on the month it shipped.
        disp = (u.get("dispatch") or [{}])[0] if u.get("dispatch") else {}
        when = str(disp.get("dispatchedOn") or "").strip()
        if when:
            m = _month(when)
            if m is None:
                un_otd += 1
            else:
                due = str((u.get("order") or {}).get("deliveryDate") or "").strip()
                n, good = otd.get(m, (0, 0))
                # No contracted date means nothing to measure against — counted in n so the month's
                # sample size is honest, never counted as on time.
                otd[m] = (n + 1, good + (1 if (due and when <= due) else 0))

    return {
        "firstPassYield": _series(fpy, months),
        "onTimeDelivery": _series(otd, months),
        "minN": MIN_N_TO_READ,
        "unbucketed": {"firstPassYield": un_fpy, "onTimeDelivery": un_otd},
        "note": ("Each KPI is filed under its own event — yield under the month the unit reached QC, "
                 "delivery under the month it shipped. A month below %d units is shown with its "
                 "count and marked unreadable rather than hidden." % MIN_N_TO_READ),
    }


# ── The eight, as the SOP states them ────────────────────────────────────────────────────────────
def customer_complaints(units, complaints):
    """Complaints per delivered unit, over the units this summary covers.

    The SOP names the KPI but nothing captured a complaint, so it read NOT_MEASURED. It is a rate,
    not a count: two complaints against forty units delivered and two against four are the same
    number and opposite facts.

    Delivered is the denominator, not built. A complaint can only be raised against a unit somebody
    has — dividing by work in progress would flatter the figure by exactly the amount of work in
    progress.
    """
    delivered = [u for u in (units or [])
                 if _norm((u.get("unit") or {}).get("status")) in ("dispatched", "delivered",
                                                                   "closed")]
    if not delivered:
        return None
    ids = {str((u.get("unit") or {}).get("id")) for u in delivered}
    against = [c for c in (complaints or []) if str(c.get("unitId") or "") in ids]
    open_ = [c for c in against
             if _norm(c.get("status")) not in ("closed", "resolved", "rejected", "withdrawn")]
    return {"delivered": len(delivered), "complaints": len(against), "open": len(open_),
            "per100": round(100.0 * len(against) / len(delivered), 1)}


def summary(units, incidents=None, worked_hours=None, complaints=None):
    """Every KPI in SOP section 1.4, each with its target, its owner and its actual.

    `incidents` is the portal's OSH register (optional); `worked_hours` the exposure hours the LTIR
    is per million of. Where a KPI cannot be computed it says NOT_MEASURED and why, rather than
    reporting a flattering zero.
    """
    fpy = first_pass_yield(units)
    otd = on_time_delivery(units)
    cls = casing_class_achieved(units)

    def class_kpi(kind, target, table, title):
        c = cls[kind]
        pct = round(100.0 * c["meets_target"] / c["n"], 1) if c["n"] else None
        return {"kpi": title, "target": "%s or better" % target, "owner": "Engineering",
                "n": c["n"], "pct": pct, "distribution": c["classes"],
                "met": (pct is not None and c["n"] > 0 and c["meets_target"] == c["n"]),
                "basis": "class achieved at test, from the signed reading"}

    out = [
        {"kpi": "First-Pass Yield (FPY)", "target": ">= 97%", "owner": "QA/QC",
         "n": fpy["n"], "pct": fpy["pct"],
         "met": fpy["pct"] is not None and fpy["pct"] >= 97.0,
         "basis": "units past gate G4 with no failed hold point or test and no rework NCR"},
        {"kpi": "On-Time Delivery (OTD)", "target": ">= 95%", "owner": "PMO",
         "n": otd["n"], "pct": otd["pct"], "late": otd["late"],
         "met": otd["pct"] is not None and otd["pct"] >= 95.0,
         "basis": "dispatched units against the order's contracted delivery date"},
        class_kpi("L", "L2", R.EN1886_LEAK_NEG400, "Casing Leakage Class"),
        class_kpi("D", "D2", R.EN1886_STRENGTH, "Casing Strength Class"),
    ]

    # LTIR — the portal HAS an OSH register, so this is computable when the exposure hours are
    # supplied. Without them it is honest about which half is missing.
    if incidents is not None and worked_hours:
        lost_time = [i for i in incidents if _norm(i.get("severity")) in ("lost time", "lost-time")
                     or _num(i.get("daysLost"))]
        rate = round(1_000_000.0 * len(lost_time) / worked_hours, 2)
        out.append({"kpi": "Lost-Time Incident Rate", "target": "0", "owner": "HSE",
                    "n": len(lost_time), "value": rate, "met": rate == 0,
                    "basis": "OSH register lost-time incidents per 1,000,000 worked hours"})
    else:
        out.append({"kpi": "Lost-Time Incident Rate", "target": "0", "owner": "HSE",
                    "status": NOT_MEASURED,
                    "why": ("The OSH register records incidents, but the worked-hours exposure this "
                            "rate is per million of is not supplied to this module. Pass it to "
                            "compute the rate rather than showing a count as though it were one.")})

    for title, why in (
        ("Thermal Bridging Class",
         "EN 1886 TB is established on a test rig with a thermal camera, not on the production "
         "line, so no route step measures it. The class a unit is SOLD as is recorded; the class "
         "achieved is not something this factory tests."),
        ("Thermal Transmittance",
         "EN 1886 T likewise requires a calibrated chamber. Recorded as sold, never measured here."),
    ):
        out.append({"kpi": title, "target": "per SOP 1.4", "owner": "Engineering" if "Class" in title
                    or "Transmittance" in title else "QA/QC",
                    "status": NOT_MEASURED, "why": why})

    # Customer Complaints — computed once a register exists AND something has been delivered.
    # Both halves are stated separately, because "no complaints" and "nothing delivered yet" are
    # very different facts and a single zero would report them identically.
    cc = customer_complaints(units, complaints)
    if cc is None:
        out.append({"kpi": "Customer Complaints", "target": "per SOP 1.4", "owner": "QA/QC",
                    "status": NOT_MEASURED,
                    "why": ("No unit in this period has been dispatched, so there is nothing a "
                            "customer could yet complain about. The register exists; the "
                            "denominator does not.")})
    else:
        out.append({"kpi": "Customer Complaints", "target": "per SOP 1.4", "owner": "QA/QC",
                    "value": cc["complaints"], "pct": cc["per100"], "n": cc["delivered"],
                    "detail": ("%d complaint(s) against %d delivered unit(s); %d still open."
                               % (cc["complaints"], cc["delivered"], cc["open"])),
                    "status": "OK" if cc["complaints"] == 0 else "WATCH"})

    computed = [k for k in out if k.get("status") != NOT_MEASURED]
    return {
        "kpis": out,
        "computed": len(computed),
        "notMeasured": len(out) - len(computed),
        # Deliberately not an average of percentages. Rolling three unrelated ratios into one score
        # would invent a number the SOP does not define and nobody could act on.
        "meeting": sum(1 for k in computed if k.get("met")),
        "ofTargets": len([k for k in computed if "met" in k]),
    }
