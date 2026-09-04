"""Working time and rest — Labour Code 2019 Arts. 105, 106, 109, 110, 111 and Decree 145/2020.

overtime.py already holds what happens BEYOND normal hours: the Art. 107 caps and the Art. 98 rates.
This holds what normal hours themselves are, and the rest a person is owed around them. Nothing in
the portal checked any of it: an employee could be rostered 60 hours in a week, off one shift and
onto the next four hours later, with no break in a twelve-hour day, and every screen would agree.

Five duties, and they fail in different ways:

  Art. 105     the ceiling on normal hours — 8 in a day and 48 in a week, or 10 in a day if the
               employer has elected WEEKLY reckoning and said so. The 48 still binds either way.
  Art. 106     night is 22:00 to 06:00, nationwide, no regional variation and no exception.
  Art. 109     a mid-shift break of at least 30 consecutive minutes, 45 where the day has night in
               it — and whether it is PAID turns on Decree 145 Art. 63(3), not on kindness.
  Art. 110     at least 12 hours between one shift and the next for the same person.
  Art. 111     at least 24 CONSECUTIVE hours of rest every week.

Two things this module deliberately refuses to do.

It does not treat 40 hours a week as a legal limit. Art. 105(2)'s second paragraph says the State
ENCOURAGES a 40-hour week; it is hortatory. Coding it as a maximum would report a lawful company as
in breach every week. (It has one real consequence, and it is a consequence of Art. 107(1), not of
Art. 105: because overtime is measured against normal hours set by law, the CBA *or the employer's
own internal rules*, a company whose nội quy says 40 has made hours 41–48 overtime for itself. That
is configuration, so it lives in `limits()`, not in the law.)

And it does not carry a 6-hour day for arduous or hazardous work. That was the 2012 Code's Art.
104(3) and was NOT carried into the 2019 Code — Art. 105(3) replaced it with a duty to stay inside
the national technical regulations for exposure. Citing the Labour Code for a 6-hour cap in a pharma
client's compliance pack would be citing a repealed provision.

The limits are effective-dated and overridable rather than literal constants, because they move: the
monthly overtime cap has already gone 40 → 60 → 40 within the life of this Code, the holiday dates
are fixed each year by the Prime Minister under Art. 112(3), and there is a live (unenacted)
proposal to take the week to 44. `UNRESOLVED` carries the questions this could not answer; they are
printed rather than guessed, because a compliance pack that sounds certain about an open question is
worse than one that says it is open.

Pure — no database, no clock. Exercised by tests/test_working_time.py.
"""

# ── Art. 106: the night window ───────────────────────────────────────────────────────────────────
# 22:00 to 06:00 the following morning. One sentence in the Code, no clauses, no exceptions. The
# 1994 Code's north/south split (22:00–06:00 / 21:00–05:00) was abolished in 2012; any regional
# night logic in a legacy payroll is obsolete.
#
# Imported, not restated. Two definitions of when night begins is one more than the law has, and the
# one that drifts is always the one nobody is looking at.
from overtime import NIGHT_FROM_MIN, NIGHT_TO_MIN, hm_to_min, night_minutes  # noqa: F401

DAY_MIN = 24 * 60

# ── the limits, effective-dated ──────────────────────────────────────────────────────────────────
# Each entry is (effective_from_iso, limits). Newest first. A company-specific normal week (a nội
# quy that says 40) is an override, not a change of law — pass it through `overrides`.
_BASE = {
    "dayHoursDaily": 8.0,        # Art. 105(1), daily reckoning
    "dayHoursWeekly": 10.0,      # Art. 105(2), weekly reckoning only
    "weekHours": 48.0,           # Art. 105(1), binds under both
    "encouragedWeek": 40.0,      # Art. 105(2) 2nd para — encouragement, NEVER a limit
    "breakMin": 30,              # Art. 109(1)
    "breakNightMin": 45,         # Art. 109(1) + Decree 145 Art. 64(1)
    "breakTriggerHours": 6.0,    # Art. 109(1): ≥ 6 hours worked in the DAY
    "nightHoursFor45": 3.0,      # Decree 145 Art. 64(1): ≥ 3 of them inside the night window
    "shiftGapHours": 12.0,       # Art. 110
    "weeklyRestHours": 24.0,     # Art. 111(1)
    "restDaysPerMonthFallback": 4,   # Art. 111(1), the special work-cycle case
    "continuousShiftMinHours": 6.0,  # Decree 145 Art. 63(3)(a)
    "continuousHandoverMaxMin": 45,  # Decree 145 Art. 63(3)(b)
}
SCHEDULE = (
    # Labour Code 2019 (45/2019/QH14) in force 01/01/2021, unamended on these articles as at 2026.
    ("2021-01-01", _BASE),
)

BASIS_DAILY = "daily"
BASIS_WEEKLY = "weekly"


def limits(as_of=None, overrides=None):
    """The limits in force on a date, with any company-specific normal hours applied on top.

    An override may only make the company's own normal hours SHORTER. Letting a nội quy raise the
    statutory ceiling would turn a configuration field into a way of legalising a 60-hour week.
    """
    out = dict(SCHEDULE[-1][1])
    for eff, vals in SCHEDULE:
        if not as_of or str(as_of)[:10] >= eff:
            out = dict(vals)
    for k, v in (overrides or {}).items():
        if k not in out:
            continue
        try:
            v = float(v)
        except (TypeError, ValueError):
            continue
        if k in ("dayHoursDaily", "dayHoursWeekly", "weekHours") and v > out[k]:
            continue                      # a company may work less than the law allows, never more
        out[k] = v
    return out


def _f(v, d=0.0):
    try:
        return float(v)
    except (TypeError, ValueError):
        return d


# ── Art. 105: normal working hours ───────────────────────────────────────────────────────────────

OK = "ok"
OVER_DAY = "over_day"
OVER_WEEK = "over_week"


def normal_hours_check(day_hours=None, week_hours=None, basis=BASIS_DAILY, as_of=None,
                       overrides=None):
    """Are the NORMAL (non-overtime) hours within Art. 105?

    Two limits bind at once. Under daily reckoning a day may not exceed 8 hours; under weekly
    reckoning — which the employer must have elected AND notified — a day may run to 10. Either way
    the week may not exceed 48.

    Returns the breaches, not a boolean: a roster can break both at once and an approver needs to
    see which.
    """
    lim = limits(as_of, overrides)
    cap_day = lim["dayHoursWeekly"] if basis == BASIS_WEEKLY else lim["dayHoursDaily"]
    breaches = []
    d, w = _f(day_hours, -1), _f(week_hours, -1)
    if day_hours is not None and d > cap_day + 1e-9:
        breaches.append({
            "code": OVER_DAY, "limit": cap_day, "actual": d,
            "why": ("%.2gh of normal working time in one day, above the %.2gh Art. 105 allows on "
                    "%s reckoning." % (d, cap_day, "weekly" if basis == BASIS_WEEKLY else "daily")),
            "whyVn": ("%.2g giờ làm việc bình thường trong 01 ngày, vượt mức %.2g giờ theo Điều 105."
                      % (d, cap_day)),
        })
    if week_hours is not None and w > lim["weekHours"] + 1e-9:
        breaches.append({
            "code": OVER_WEEK, "limit": lim["weekHours"], "actual": w,
            "why": ("%.4gh of normal working time in one week, above the %.4gh ceiling in Art. "
                    "105(1). The weekly ceiling binds whichever reckoning is used."
                    % (w, lim["weekHours"])),
            "whyVn": ("%.4g giờ làm việc bình thường trong 01 tuần, vượt mức %.4g giờ theo khoản 1 "
                      "Điều 105." % (w, lim["weekHours"])),
        })
    return {
        "ok": not breaches, "basis": basis, "breaches": breaches,
        "capDay": cap_day, "capWeek": lim["weekHours"],
        "note": ("The 40-hour week in Art. 105(2) is encouragement, not a limit — it is not tested "
                 "here. It becomes this employer's overtime threshold only if the company's own "
                 "internal labour rules adopt it, which is configuration under Art. 107(1)."),
        "basisNote": ("Weekly reckoning is only available if the employer has elected it and "
                      "notified employees — put it in the nội quy lao động or the contract."),
    }


# ── Decree 145 Art. 63: is this shift work at all, and is it continuous? ─────────────────────────

def is_shift_work(people_at_workstation=1):
    """Art. 63(2): rostering at least 2 people or groups taking turns at the SAME workstation
    within 24 consecutive hours. One crew on one site is not shift work, whatever it is called."""
    try:
        return int(people_at_workstation or 1) >= 2
    except (TypeError, ValueError):
        return False


def is_continuous_shift(shift_hours=0.0, handover_gap_min=None, people_at_workstation=1,
                        as_of=None, overrides=None):
    """Art. 63(3): continuous shift work needs BOTH a shift of at least 6 hours AND a handover gap
    to the adjacent shift of at most 45 minutes. It matters because it is the only thing that makes
    the Art. 109 break paid.

    An unknown gap is not a pass. Defaulting it to zero would quietly make every long shift
    'continuous' and every break paid — the wrong side to be wrong on, because it is the side that
    changes what has already been paid.
    """
    lim = limits(as_of, overrides)
    if not is_shift_work(people_at_workstation):
        return {"continuous": False, "reason": "not_shift_work",
                "why": "Not shift work under Decree 145 Art. 63(2) — that needs at least two "
                       "people or groups taking turns at the same workstation within 24 hours."}
    if _f(shift_hours) < lim["continuousShiftMinHours"] - 1e-9:
        return {"continuous": False, "reason": "shift_too_short",
                "why": "The shift is under %.2g hours, so Art. 63(3)(a) is not met."
                       % lim["continuousShiftMinHours"]}
    if handover_gap_min is None:
        return {"continuous": False, "reason": "handover_unknown",
                "why": "The changeover gap to the adjacent shift is not recorded, so Art. 63(3)(b) "
                       "cannot be shown. Record it rather than assuming it."}
    if _f(handover_gap_min) > lim["continuousHandoverMaxMin"] + 1e-9:
        return {"continuous": False, "reason": "handover_too_long",
                "why": "The changeover gap is over %d minutes, so Art. 63(3)(b) is not met."
                       % lim["continuousHandoverMaxMin"]}
    return {"continuous": True, "reason": "met",
            "why": "Shift of at least %.2g hours with a changeover gap of at most %d minutes — "
                   "continuous shift work under Decree 145 Art. 63(3)."
                   % (lim["continuousShiftMinHours"], lim["continuousHandoverMaxMin"])}


# ── Art. 109 + Decree 145 Art. 64: the mid-shift break ───────────────────────────────────────────

def break_entitlement(worked_hours=0.0, night_hours=0.0, continuous_shift=False, as_of=None,
                      overrides=None):
    """How long a mid-shift break is owed, and whether it is paid.

    The trigger is 6 hours worked IN THE DAY — not 6 CONTINUOUS hours. English translations of Art.
    109 that say "working continuously for 6 hours" are rendering the repealed 2012 wording, and it
    changes who is entitled.

    45 minutes rather than 30 where at least 3 of the day's hours fall inside 22:00–06:00. Note that
    the 3-hour test is the DECREE's (Art. 64(1)); the Code's own words are broader, and nothing was
    found resolving the gap for somebody with one or two night hours. `over_compliance` flags that
    case: giving them 45 is safe, giving them 30 may not be.

    Paid only for continuous shift work. For everybody else Decree 145 Art. 64(4) merely encourages
    the parties to agree it, so an 8-hour day plus an unpaid 30-minute lunch spans 8h30 on site.
    """
    lim = limits(as_of, overrides)
    w, n = _f(worked_hours), _f(night_hours)
    if w < lim["breakTriggerHours"] - 1e-9:
        return {"minutes": 0, "paid": False, "required": False, "overCompliance": False,
                "why": "Under %.2g hours in the day, so Art. 109(1) does not require a mid-shift "
                       "break." % lim["breakTriggerHours"],
                "whyVn": "Dưới %.2g giờ trong ngày nên khoản 1 Điều 109 không yêu cầu nghỉ giữa giờ."
                         % lim["breakTriggerHours"]}
    night_qualifies = n >= lim["nightHoursFor45"] - 1e-9
    mins = lim["breakNightMin"] if night_qualifies else lim["breakMin"]
    return {
        "minutes": int(mins), "required": True, "paid": bool(continuous_shift),
        # The Code says "làm việc ban đêm" without a threshold; the Decree sets 3 hours. Somebody
        # with 1–2 night hours sits in the gap between them.
        "overCompliance": bool(0 < n < lim["nightHoursFor45"]),
        "consecutive": True,
        "why": ("At least %d consecutive minutes, %s. %s"
                % (mins,
                   "night work of %.2g hours or more" % lim["nightHoursFor45"] if night_qualifies
                   else "a day of %.2g hours or more" % lim["breakTriggerHours"],
                   ("Counted into paid working time — this is continuous shift work under Decree "
                    "145 Art. 63(3)." if continuous_shift else
                    "NOT counted into working time: outside continuous shift work Decree 145 Art. "
                    "64(4) only encourages the parties to agree it."))),
        "whyVn": ("Ít nhất %d phút liên tục. %s" % (
            mins,
            "Được tính vào giờ làm việc (ca liên tục theo khoản 3 Điều 63 Nghị định 145)."
            if continuous_shift else
            "Không tính vào giờ làm việc trừ khi hai bên thỏa thuận (khoản 4 Điều 64).")),
        "placement": "The break must fall inside the shift — Decree 145 Art. 64(3) forbids placing "
                     "it at the start or the end, which would otherwise cost the employer nothing.",
        "noSplit": "One unbroken block. The statute says 'ít nhất 30 phút liên tục' and no "
                   "authority was found for splitting it into 15+15.",
    }


def break_placement_ok(shift_start, shift_end, break_start, break_minutes):
    """Decree 145 Art. 64(3): the break may not sit at the start or the end of the shift."""
    s, e, b = hm_to_min(shift_start), hm_to_min(shift_end), hm_to_min(break_start)
    m = int(_f(break_minutes))
    if s is None or e is None or b is None or m <= 0:
        return {"ok": False, "reason": "unreadable",
                "why": "The shift or break times could not be read."}
    if e <= s:
        e += DAY_MIN
    if b < s:
        b += DAY_MIN
    if b <= s:
        return {"ok": False, "reason": "at_start",
                "why": "The break sits at the start of the shift — Decree 145 Art. 64(3) forbids it."}
    if b + m >= e:
        return {"ok": False, "reason": "at_end",
                "why": "The break sits at the end of the shift — Decree 145 Art. 64(3) forbids it."}
    return {"ok": True, "reason": "inside", "why": "The break falls inside the shift."}


# ── Art. 110: the rest between shifts ────────────────────────────────────────────────────────────

def shift_gap_check(prev_end_iso_min, next_start_iso_min, as_of=None, overrides=None):
    """At least 12 hours before the same person moves to another shift.

    Both arguments are absolute minutes on a common timeline (see `at()`), because the whole point
    is a gap that crosses midnight — comparing times of day would make 22:00 → 06:00 look like an
    eight-hour rest and a sixteen-hour one identical.

    Distinct from Decree 145 Art. 63(3)(b)'s 45-minute changeover: that is a test on the ROSTER (how
    long the workstation stands empty between two shifts), this is a test on a PERSON.
    """
    lim = limits(as_of, overrides)
    need = lim["shiftGapHours"] * 60
    a, b = prev_end_iso_min, next_start_iso_min
    if a is None or b is None:
        return {"ok": None, "gapHours": None,
                "why": "One of the two shifts has no recorded time, so the Art. 110 rest cannot be "
                       "checked. An unchecked rest is not a compliant one."}
    gap = float(b) - float(a)
    if gap < 0:
        return {"ok": False, "gapHours": gap / 60.0, "code": "overlap",
                "why": "The next shift starts before the previous one ended."}
    ok = gap >= need - 1e-9
    return {
        "ok": ok, "gapHours": round(gap / 60.0, 2), "needHours": lim["shiftGapHours"],
        "code": OK if ok else "short_rest",
        "why": ("%.2f hours between shifts%s — Art. 110 requires at least %.2g."
                % (gap / 60.0, "" if ok else ", short of the rest owed", lim["shiftGapHours"])),
        "whyVn": ("%.2f giờ giữa hai ca%s — Điều 110 yêu cầu ít nhất %.2g giờ."
                  % (gap / 60.0, "" if ok else ", chưa đủ thời gian nghỉ", lim["shiftGapHours"])),
    }


def at(day_index, hm):
    """Minutes on a common timeline: day 0 is the first day, 08:00 on day 1 is 1920.

    Callers hold real dates; this keeps the module free of a calendar it does not need.
    """
    m = hm_to_min(hm)
    return None if m is None else int(day_index) * DAY_MIN + m


# ── Art. 111: the weekly rest ────────────────────────────────────────────────────────────────────

def weekly_rest_check(rest_blocks_hours=(), as_of=None, overrides=None):
    """At least 24 CONSECUTIVE hours of rest in the week.

    Consecutive is the whole rule: two twelve-hour gaps are not a weekly rest, and adding them up
    would report a person who never had a day off as compliant. Nor is it a calendar day — 14:00
    Saturday to 14:00 Sunday satisfies Art. 111(1).
    """
    lim = limits(as_of, overrides)
    blocks = [_f(h) for h in (rest_blocks_hours or ())]
    longest = max(blocks) if blocks else 0.0
    ok = longest >= lim["weeklyRestHours"] - 1e-9
    return {
        "ok": ok, "longestHours": round(longest, 2), "needHours": lim["weeklyRestHours"],
        "why": ("Longest unbroken rest in the week: %.2f hours%s. Art. 111(1) requires at least %.2g "
                "CONSECUTIVE hours — separate shorter rests do not add up to it."
                % (longest, "" if ok else ", short of the weekly rest", lim["weeklyRestHours"])),
        "whyVn": ("Thời gian nghỉ liên tục dài nhất trong tuần: %.2f giờ%s. Khoản 1 Điều 111 yêu cầu "
                  "ít nhất %.2g giờ LIÊN TỤC."
                  % (longest, "" if ok else ", chưa đủ", lim["weeklyRestHours"])),
        "fallback": ("Where the work cycle makes a weekly rest impossible, Art. 111(1) instead "
                     "requires at least %d days off per month on average. That is a narrow special "
                     "case, not an employer option, and the reasoning belongs in the nội quy lao "
                     "động." % lim["restDaysPerMonthFallback"]),
        "restDay": ("Art. 111(2): the employer picks the rest day — Sunday or another DETERMINED "
                    "weekday — and must record it in the nội quy lao động. Sunday is not a "
                    "statutory default."),
        "clash": ("Art. 111(3): where the weekly rest day falls on an Art. 112(1) public or Tet "
                  "holiday, the weekly rest is taken on the next working day."),
    }


def monthly_rest_fallback(rest_days_in_month=0, as_of=None, overrides=None):
    """The Art. 111(1) special case, for a work cycle that cannot give a weekly rest.

    The Code does not define a 'day' here, and Decree 145 has no implementing article for Art. 111.
    This counts whole rest days inside one calendar month, which is the conservative reading — see
    UNRESOLVED. It must not be described to a client as the law's own definition.
    """
    lim = limits(as_of, overrides)
    n = int(_f(rest_days_in_month))
    need = int(lim["restDaysPerMonthFallback"])
    return {
        "ok": n >= need, "days": n, "needDays": need,
        "why": ("%d rest day(s) in the month against the %d Art. 111(1) requires on average where "
                "the work cycle prevents a weekly rest." % (n, need)),
        "caveat": "The Code does not define what a 'day' is here or the window the average is taken "
                  "over. This counts whole rest days within one calendar month — a reading, not a "
                  "quotation.",
    }


# ── Art. 98(2): the premium a rostered night shift has been missing ─────────────────────────────

def normal_night_hours(clock_in, clock_out, ot_hours=0.0):
    """Night hours inside NORMAL working time — the ones Art. 98(2)'s 30% applies to.

    overtime.py already prices night hours that fall inside the overtime tail. Nothing priced the
    night hours of a shift with no overtime at all, so a crew rostered 22:00–06:00 on a cleanroom
    shutdown earned the same as a day crew. Art. 98(2) is not conditional on overtime: it is paid
    for night work, full stop.

    The overtime tail is taken off the END of the shift, matching overtime.ot_window.
    """
    a, b = hm_to_min(clock_in), hm_to_min(clock_out)
    if a is None or b is None:
        return None
    if b <= a:
        b += DAY_MIN                                   # a shift running through midnight
    ot_min = max(0.0, _f(ot_hours) * 60.0)
    normal_end = max(a, b - ot_min)                    # OT is the tail; normal time is what precedes
    return round(night_minutes(a, normal_end) / 60.0, 4)


# ── the review, over real attendance rows ────────────────────────────────────────────────────────

def _date_ord(iso):
    from datetime import date
    try:
        return date.fromisoformat(str(iso)[:10]).toordinal()
    except (TypeError, ValueError):
        return None


def _week_key(iso):
    from datetime import date
    try:
        d = date.fromisoformat(str(iso)[:10])
    except (TypeError, ValueError):
        return None
    y, w, _ = d.isocalendar()
    return "%04d-W%02d" % (y, w)


def row_span(row):
    """One attendance row as (start, end) on the absolute minute timeline, or None.

    A row whose check-out is at or before its check-in ran through midnight — the same rule
    db._hrs_between uses. Without it, a 22:00–06:00 shift measures as minus sixteen hours and every
    rest check downstream is nonsense.
    """
    d = _date_ord(row.get("date"))
    a = hm_to_min(row.get("clock_in") or row.get("in"))
    b = hm_to_min(row.get("clock_out") or row.get("out"))
    if d is None or a is None or b is None:
        return None
    s, e = d * DAY_MIN + a, d * DAY_MIN + b
    if e <= s:
        e += DAY_MIN
    return (s, e)


# No meal break plausibly accounts for more than two hours. Beyond that the excess is working time
# whatever the break was, so the day is a breach rather than an open question.
MAX_ASSUMED_BREAK_MIN = 120

INDETERMINATE = "indeterminate"


def review_rows(rows, basis=BASIS_DAILY, break_minutes=None, continuous_shift=False, as_of=None,
                overrides=None):
    """Everything Arts. 105, 110 and 111 have to say about one person's period.

    `rows` are attendance rows with a date, a check-in, a check-out and (approved) ot_hours. Rows
    with no check-out are skipped and counted: an open row is a missing fact, and a missing fact is
    not evidence of compliance. Overtime is subtracted before the Art. 105 test, because Art. 105
    caps NORMAL hours — lawful overtime on top is Art. 107's business, not this article's.

    THE BREAK. This portal records one check-in and one check-out, so a row gives elapsed time on
    site, not working time. Decree 145 Art. 63(1) puts the mid-shift break inside the shift, and
    outside continuous shift work it is not paid working time — so the company's ordinary 08:00 to
    17:00 day is eight working hours and one unpaid hour, and measuring Art. 105 off the raw span
    would report every employee in breach every day. A compliance screen that cries wolf on 100% of
    rows teaches people to close it.

    So: pass `break_minutes` when the schedule declares one and the arithmetic is exact. With no
    declared break the day is reported as INDETERMINATE rather than as a breach — unless the excess
    is larger than any break could explain, which is a breach on any reading.
    """
    lim = limits(as_of, overrides)
    spans, open_rows, unreadable = [], 0, 0
    for r in (rows or []):
        if not (str(r.get("clock_out") or r.get("out") or "").strip()):
            open_rows += 1
            continue
        sp = row_span(r)
        if not sp:
            unreadable += 1
            continue
        spans.append((sp[0], sp[1], r))
    spans.sort(key=lambda x: x[0])

    declared = None if break_minutes is None else max(0.0, _f(break_minutes))
    cap_day = lim["dayHoursWeekly"] if basis == BASIS_WEEKLY else lim["dayHoursDaily"]

    findings = []
    days, weeks = [], {}
    any_assumed = False
    for s, e, r in spans:
        elapsed = (e - s) / 60.0
        ot = max(0.0, _f(r.get("ot_hours")))
        night_normal = normal_night_hours(r.get("clock_in") or r.get("in"),
                                          r.get("clock_out") or r.get("out"), ot) or 0.0
        ent = break_entitlement(elapsed, night_normal, continuous_shift, as_of, overrides)
        # A paid break is already working time; only an unpaid one comes off the span.
        deduct = 0.0 if (declared is None or ent["paid"]) else min(declared, elapsed * 60) / 60.0
        normal = max(0.0, elapsed - ot - deduct)
        over = normal - cap_day
        if over <= 1e-9:
            state = OK
        elif declared is None and over * 60 <= MAX_ASSUMED_BREAK_MIN:
            state = INDETERMINATE
            any_assumed = True
        else:
            state = OVER_DAY
        d = {"date": str(r.get("date"))[:10], "elapsedHours": round(elapsed, 2),
             "otHours": round(ot, 2), "breakHours": round(deduct, 2),
             "normalHours": round(normal, 2), "nightHours": round(night_normal, 2),
             "breakOwedMinutes": ent["minutes"], "breakPaid": ent["paid"], "state": state,
             "ok": state == OK}
        days.append(d)
        if state == OVER_DAY:
            findings.append({
                "code": OVER_DAY, "article": "Art. 105", "date": d["date"],
                "limit": cap_day, "actual": d["normalHours"],
                "why": ("%.2fh of normal working time, above the %.2gh Art. 105 allows — more than "
                        "any mid-shift break could account for."
                        % (d["normalHours"], cap_day)),
                "whyVn": ("%.2f giờ làm việc bình thường, vượt mức %.2g giờ theo Điều 105."
                          % (d["normalHours"], cap_day)),
            })
        wk = weeks.setdefault(_week_key(r.get("date")) or "?",
                              {"week": _week_key(r.get("date")) or "?", "normalHours": 0.0,
                               "otHours": 0.0, "nightHours": 0.0, "days": 0,
                               "indeterminate": False})
        wk["normalHours"] += normal
        wk["otHours"] += ot
        wk["nightHours"] += night_normal
        wk["days"] += 1
        wk["indeterminate"] = wk["indeterminate"] or state == INDETERMINATE

    for wk in weeks.values():
        wk["normalHours"] = round(wk["normalHours"], 2)
        wk["otHours"] = round(wk["otHours"], 2)
        wk["nightHours"] = round(wk["nightHours"], 2)
        chk = normal_hours_check(week_hours=wk["normalHours"], basis=basis, as_of=as_of,
                                 overrides=overrides)
        # A week built from days whose break is unknown is itself unknown, unless it is over even
        # after allowing the largest break each day could have had.
        slack = wk["days"] * MAX_ASSUMED_BREAK_MIN / 60.0
        certain = not wk["indeterminate"] or wk["normalHours"] - slack > lim["weekHours"] + 1e-9
        wk["ok"] = chk["ok"]
        wk["state"] = OK if chk["ok"] else (OVER_WEEK if certain else INDETERMINATE)
        if not chk["ok"] and certain:
            for b in chk["breaches"]:
                findings.append(dict(b, week=wk["week"], article="Art. 105(1)"))

    # Art. 110 — between one shift and the next, for this person.
    gaps = []
    for i in range(1, len(spans)):
        prev_end, nxt_start = spans[i - 1][1], spans[i][0]
        g = shift_gap_check(prev_end, nxt_start, as_of=as_of, overrides=overrides)
        g["from"] = str(spans[i - 1][2].get("date"))[:10]
        g["to"] = str(spans[i][2].get("date"))[:10]
        gaps.append(g)
        if g.get("ok") is False:
            findings.append({"code": "short_rest", "article": "Art. 110", "date": g["to"],
                             "limit": g.get("needHours"), "actual": g.get("gapHours"),
                             "why": g["why"], "whyVn": g.get("whyVn", "")})

    # Art. 111 — the longest unbroken rest inside each week, including the ends of the week.
    by_week = {}
    for s, e, r in spans:
        by_week.setdefault(_week_key(r.get("date")) or "?", []).append((s, e))
    rest = []
    for wkey, sp in sorted(by_week.items()):
        sp.sort()
        first_day = sp[0][0] // DAY_MIN
        from datetime import date
        monday = first_day - date.fromordinal(first_day).weekday()
        w0, w1 = monday * DAY_MIN, (monday + 7) * DAY_MIN
        blocks = [max(0, sp[0][0] - w0)]
        for i in range(1, len(sp)):
            blocks.append(max(0, sp[i][0] - sp[i - 1][1]))
        blocks.append(max(0, w1 - sp[-1][1]))
        chk = weekly_rest_check([b / 60.0 for b in blocks], as_of=as_of, overrides=overrides)
        chk["week"] = wkey
        rest.append(chk)
        if not chk["ok"]:
            findings.append({"code": "no_weekly_rest", "article": "Art. 111(1)", "week": wkey,
                             "limit": chk["needHours"], "actual": chk["longestHours"],
                             "why": chk["why"], "whyVn": chk.get("whyVn", "")})

    return {
        "days": days, "weeks": sorted(weeks.values(), key=lambda w: w["week"]),
        "gaps": gaps, "weeklyRest": rest, "findings": findings,
        "openRows": open_rows, "unreadableRows": unreadable,
        "nightHours": round(sum(d["nightHours"] for d in days), 2),
        "basis": basis, "breakMinutes": declared,
        "indeterminate": any_assumed,
        "coverage": ("%d row(s) checked; %d skipped for a missing check-out and %d unreadable. A "
                     "row that was never closed is a missing fact, not a compliant one."
                     % (len(spans), open_rows, unreadable)),
        "breakNote": (
            "Working time is measured after the unpaid mid-shift break, which this portal does not "
            "record — it holds one check-in and one check-out. A declared break length on the work "
            "schedule makes the Art. 105 figures exact."
            if declared is None else
            "Working time is measured after a declared unpaid break of %d minutes." % declared),
        "breakNoteVn": (
            "Giờ làm việc được tính sau khi trừ thời gian nghỉ giữa giờ không hưởng lương — cổng "
            "thông tin chỉ ghi một lần vào và một lần ra. Hãy khai báo thời gian nghỉ trên lịch làm "
            "việc để số liệu Điều 105 chính xác."
            if declared is None else
            "Giờ làm việc được tính sau khi trừ %d phút nghỉ giữa giờ không hưởng lương." % declared),
    }


# ── what this could not settle ───────────────────────────────────────────────────────────────────
# Printed in the compliance pack rather than guessed at. A pack that sounds certain about an open
# question is worse than one that says the question is open, because only the second gets asked.
UNRESOLVED = (
    {"topic": "Day type after midnight",
     "question": "Do hours worked 00:00–06:00 belong to the calendar date they fall in, or to the "
                 "date the shift started?",
     "why_it_matters": "A shift from Saturday 20:00 to Sunday 06:00 rates at 150% or at 200% "
                       "depending on the answer, and the same question decides when a Tet 300% band "
                       "begins.",
     "action": "Neither Art. 106 nor Decree 145 says. It is the employer's to decide — write it into "
               "the nội quy lao động, dated, BEFORE the payroll implements a convention."},
    {"topic": "Paid break time and the overtime caps",
     "question": "Where a continuous shift's break counts as working time, does it also count "
                 "toward the Art. 107 monthly and annual overtime ceilings?",
     "why_it_matters": "It moves the point at which the system refuses more overtime.",
     "action": "No decree text or ministry guidance found. Count it toward the cap — warning early "
               "is the recoverable error."},
    {"topic": "The 45-minute changeover gap",
     "question": "Is Decree 145 Art. 63(3)(b) measured on the SCHEDULED roster, or does overtime at "
                 "the end of a shift count when computing the gap?",
     "why_it_matters": "If overtime can push the gap past 45 minutes, a shift pattern flips from "
                       "paid-break to unpaid-break after the fact — a retroactive repricing.",
     "action": "Contested, no official guidance. Do not let the system reprice a past period either "
               "way without counsel."},
    {"topic": "One or two hours of night work",
     "question": "The Code grants 45 minutes to somebody who 'works at night'; Decree 145 Art. 64(1) "
                 "grants it only where 3 or more hours fall in the night window.",
     "why_it_matters": "Somebody with one or two night hours sits between the two texts.",
     "action": "No authority found. `break_entitlement` flags the case: 45 minutes over-complies and "
               "is safe, 30 may not be."},
    {"topic": "'4 days per month on average'",
     "question": "What is a 'day', and over what window is the average taken?",
     "why_it_matters": "It is the only fallback when a work cycle prevents a weekly rest.",
     "action": "Undefined in the Code, no implementing article. Encoded conservatively as four whole "
               "rest days within each calendar month; do not state that as the law."},
    {"topic": "Rest-day night overtime for a monthly-paid employee",
     "question": "200%/270% or 300%/370%?",
     "why_it_matters": "It is a payslip figure.",
     "action": "Vietnamese sources are genuinely mixed. Have the company's labour counsel confirm "
               "before a rest-day payslip goes out."},
    {"topic": "Working-time penalties",
     "question": "The Decree 12/2022 Art. 18 amounts for breaching rest and hours rules.",
     "why_it_matters": "A wrong figure in a client pack is worse than no figure.",
     "action": "Circulating summaries were internally inconsistent and the decree text could not be "
               "read. Quote no Art. 18 amount."},
)

# Provisions this module deliberately does NOT encode, and why — so nobody adds them back.
REJECTED = (
    {"claim": "40 hours a week is the legal maximum",
     "status": "Art. 105(2) says the State ENCOURAGES it. Hortatory, not a limit."},
    {"claim": "60 overtime hours a month",
     "status": "Resolution 17/2022/UBTVQH15 was a temporary COVID instrument, and even in force it "
               "applied only to employers already entitled to 300 hours a year. Encode 40."},
    {"claim": "6 hours a day for arduous or hazardous work, per the Labour Code",
     "status": "2012 Code Art. 104(3), NOT carried into the 2019 Code. Any hours limit for hazardous "
               "work now comes from OSH law and the hazard-specific QCVN, sourced separately."},
    {"claim": "The 30-minute break may be split into 15+15",
     "status": "The statute says 'ít nhất 30 phút liên tục'. No legal basis found for a split."},
    {"claim": "All break time is paid",
     "status": "Only for continuous shift work under Decree 145 Art. 63(3). Art. 64(4) merely "
               "encourages agreement for everybody else."},
    {"claim": "Night is 21:00–05:00 in the south",
     "status": "The regional split was abolished in 2012. Art. 106 is 22:00–06:00 nationwide."},
)
