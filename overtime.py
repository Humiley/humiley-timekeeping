"""Overtime: what Vietnamese law requires, written as code you can test.

The portal has recorded overtime since the attendance module was built — an employee requests it at
check-out, a manager approves it, and it is stored on the attendance row. Then it stopped. Approved
overtime never reached a payslip, never reached the statutory caps, and never reached the wage
statement. Somebody who worked forty extra hours over a Tết shutdown was paid the same as somebody
who worked none, and nothing in the system noticed.

This module is the missing half: the rate, the premium, the tax treatment and the cap. It is pure —
no database, no request, no clock — so every rule below is exercised by tests/test_overtime.py rather
than trusted.

The law, in the order it applies:

  Art. 98(1) Labour Code 2019   overtime is paid at AT LEAST 150% on a normal working day, 200% on a
                               weekly rest day, and 300% on a public holiday or paid-leave day.
  Art. 106                     night work is 22:00 to 06:00 the following morning.
  Art. 98(2)                   night work carries a further 30% of the normal-day hourly wage.
  Art. 98(3)                   overtime worked AT NIGHT carries a further 20% on top of both.
  Decree 145/2020 Art. 55      the hourly wage is the actual wage for the job that month divided by
                               the normal working hours in the month — excluding overtime pay, the
                               night premium, and meal/phone/transport welfare.
  Art. 107(2)(b), 107(3)       caps: overtime may not exceed 50% of the normal hours in a day, nor
                               40 hours in a month, nor 200 hours in a year (300 only for the
                               sectors listed in Art. 107(3), which is a decision for the company
                               and its labour authority, not a default).
  Circular 111/2013 Art. 3(1)(i)  the PREMIUM above the normal rate is exempt from personal income
                               tax. Overtime at 150% is taxed on the 100% and exempt on the 50%.

Every rate below is a statutory MINIMUM ("at least"). Paying above it is lawful; paying below it is
not. Where the drafting admits more than one reading, this module takes the reading that cannot
underpay — see NIGHT_OT_BASE.
"""

# ── Art. 106: the night window ───────────────────────────────────────────────────────────────────
NIGHT_FROM_MIN = 22 * 60        # 22:00
NIGHT_TO_MIN = 6 * 60           # 06:00 the following morning

# ── Art. 98(1): the overtime multiplier, by the kind of day ──────────────────────────────────────
OT_RATE = {"normal": 1.50, "rest": 2.00, "holiday": 3.00}

# ── Art. 98(2): night work premium, on the normal-day hourly wage ────────────────────────────────
NIGHT_PREMIUM = 0.30

# ── Art. 98(3) / Decree 145/2020 Art. 57(2): the extra 20% for overtime worked at night.
# The 20% is taken on "the daytime hourly wage of a normal working day, a weekly rest day or a public
# holiday" — i.e. the base scales with the kind of day. Commentary differs on the exact multiplier
# for a rest day, so the values here are the ones that cannot underpay: the daytime rate actually
# earned for working that day. Configurable, because a company may agree better terms and may not
# agree worse ones.
NIGHT_OT_EXTRA = 0.20
NIGHT_OT_BASE = {"normal": 1.00, "rest": 2.00, "holiday": 3.00}

# ── Art. 107: the caps ───────────────────────────────────────────────────────────────────────────
NORMAL_DAY_HOURS = 8.0          # Art. 105(1): 8 hours a day
CAP_DAY_RATIO = 0.50            # Art. 107(2)(b): OT ≤ 50% of the normal hours in a day
CAP_DAY_TOTAL = 12.0            # …and normal + OT ≤ 12 hours in a day
CAP_MONTH_HOURS = 40.0          # Art. 107(2)(b)
CAP_YEAR_HOURS = 200.0          # Art. 107(2)(c)
CAP_YEAR_HOURS_EXTENDED = 300.0  # Art. 107(3), only for the listed sectors, on notification

DAY_KINDS = ("normal", "rest", "holiday")


# ── time helpers ─────────────────────────────────────────────────────────────────────────────────

def hm_to_min(hm):
    """'22:30' → 1350. Returns None for anything that is not a HH:MM clock time."""
    try:
        h, m = str(hm).split(":")[:2]
        h, m = int(h), int(m)
    except (ValueError, AttributeError, TypeError):
        return None
    if not (0 <= h <= 23 and 0 <= m <= 59):
        return None
    return h * 60 + m


def night_minutes(a, b):
    """Minutes of the half-open span [a, b) that fall inside a night window.

    `a` and `b` are minutes from midnight of the shift's own date and may run past 1440 for a shift
    that crosses into the next day — 23:00 to 02:00 is (1380, 1560). The night windows repeat every
    24h and never overlap each other, so the overlaps simply add.
    """
    if b <= a:
        return 0.0
    total = 0.0
    for d in range(-1, 3):                       # the day before through two days after
        base = d * 1440
        lo = max(a, base + NIGHT_FROM_MIN)
        hi = min(b, base + 1440 + NIGHT_TO_MIN)
        if hi > lo:
            total += hi - lo
    return total


def _shift_date(date_iso, day_offset):
    """date_iso shifted by whole days, without importing datetime into the hot path."""
    from datetime import date, timedelta
    y, m, d = (int(x) for x in str(date_iso)[:10].split("-"))
    return (date(y, m, d) + timedelta(days=day_offset)).strftime("%Y-%m-%d")


def ot_window(clock_in, clock_out, ot_hours):
    """The overtime window as (start, end) minutes from midnight of the shift's date.

    Overtime is the TAIL of the shift: it ends when the person checked out. A shift that checks out
    before it checked in ran past midnight, so the end is carried into the next day (+1440) — which
    is what puts a 23:00–02:00 stint inside the night window rather than outside it.
    """
    try:
        hours = float(ot_hours or 0)
    except (TypeError, ValueError):
        return None
    if hours <= 0:
        return None
    end = hm_to_min(clock_out)
    if end is None:
        return None
    start_in = hm_to_min(clock_in)
    if start_in is not None and end < start_in:
        end += 1440
    start = end - hours * 60.0
    # Overtime cannot begin before the person was checked in. The endpoints validate this, but a row
    # that predates the validation — or one written directly — would otherwise reach back past the
    # check-in and collect night minutes, or roll onto the previous day at its holiday rate. Clamp it
    # here too: this function decides what the hours are WORTH, and it should not be possible to be
    # paid for a window nobody was present for.
    if start_in is not None:
        start = max(start, float(start_in))
    return (start, float(end))


def ot_segments(date_iso, start, end):
    """Split an overtime window into per-calendar-day pieces.

    Overtime that runs 22:00 on the 30th to 02:00 on the 31st is two different days, and at Tết the
    second of them can be a public holiday while the first is not. Returns
    [(date_iso, minutes_within_that_date), ...] with the window's own start/end preserved as
    (a, b) offsets so the night overlap can still be computed on the unbroken axis.
    """
    out = []
    a = start
    while a < end:
        day = int(a // 1440)
        edge = (day + 1) * 1440
        b = min(end, edge)
        out.append((_shift_date(date_iso, day), a, b))
        a = b
    return out


# ── classification ───────────────────────────────────────────────────────────────────────────────

def day_kind(date_iso, holidays=(), rest_weekdays=(5, 6)):
    """'holiday', 'rest' or 'normal' for one calendar date.

    A public holiday outranks a rest day: Art. 98(1)(c) pays 300% for it either way, and the two
    coincide every few years.
    `rest_weekdays` is Python weekday numbering — Monday 0 … Sunday 6 — so the office (Mon–Fri) is
    (5, 6) and the factory (Mon–Sat) is (6,).
    """
    d = str(date_iso)[:10]
    if d in set(holidays or ()):
        return "holiday"
    from datetime import datetime
    try:
        wd = datetime.strptime(d, "%Y-%m-%d").weekday()
    except (ValueError, TypeError):
        return "normal"
    return "rest" if wd in set(rest_weekdays or ()) else "normal"


# ── the money ────────────────────────────────────────────────────────────────────────────────────

def hourly_rate(month_wage, working_days, day_hours=NORMAL_DAY_HOURS):
    """Decree 145/2020 Art. 55(1)(a): the actual wage for the job in the month, divided by the normal
    working hours in that month.

    `month_wage` must be the wage-and-allowance part of pay — P1 + P2 here. It excludes the KPI bonus
    and the meal/phone/transport welfare, because the decree excludes bonuses and welfare from the
    base, and excludes overtime and the night premium so the rate cannot compound on itself.
    """
    hours = float(working_days or 0) * float(day_hours or 0)
    if hours <= 0:
        return 0.0
    return float(month_wage or 0) / hours


def pay_for(hours, night_hours_, kind, hourly):
    """What one stretch of overtime is worth, and how much of it is taxable.

    Returns pay, the taxable part and the exempt part. Circular 111/2013 Art. 3(1)(i) exempts the
    amount paid ABOVE the normal rate, so the taxable part is always the plain hourly wage for the
    hours worked and everything the premiums add on top is exempt.
    """
    hours = max(0.0, float(hours or 0))
    night = min(max(0.0, float(night_hours_ or 0)), hours)
    rate = OT_RATE.get(kind, OT_RATE["normal"])
    base = NIGHT_OT_BASE.get(kind, NIGHT_OT_BASE["normal"])
    hourly = float(hourly or 0)

    pay = hours * hourly * rate                                   # Art. 98(1)
    pay += night * hourly * NIGHT_PREMIUM                         # Art. 98(2)
    pay += night * hourly * NIGHT_OT_EXTRA * base                 # Art. 98(3)
    taxable = hours * hourly                                      # the 100% equivalent
    return {"pay": pay, "taxable": taxable, "exempt": max(0.0, pay - taxable),
            "hours": hours, "nightHours": night, "kind": kind, "rate": rate}


def record_pay(rec, hourly, holidays=(), rest_weekdays=(5, 6)):
    """Value ONE approved attendance row's overtime.

    `rec` is an attendance row: date, clock_in, clock_out, ot_hours. The window is split by calendar
    day so a stint running through midnight into a holiday is paid at the holiday rate for the part
    that actually falls on it.
    """
    win = ot_window(rec.get("clock_in"), rec.get("clock_out"), rec.get("ot_hours"))
    if not win:
        return {"pay": 0.0, "taxable": 0.0, "exempt": 0.0, "hours": 0.0, "nightHours": 0.0,
                "byKind": {}}
    start, end = win
    date_iso = str(rec.get("date") or "")[:10]
    tot = {"pay": 0.0, "taxable": 0.0, "exempt": 0.0, "hours": 0.0, "nightHours": 0.0, "byKind": {}}
    for seg_date, a, b in ot_segments(date_iso, start, end):
        hours = (b - a) / 60.0
        kind = day_kind(seg_date, holidays, rest_weekdays)
        part = pay_for(hours, night_minutes(a, b) / 60.0, kind, hourly)
        for k in ("pay", "taxable", "exempt", "hours", "nightHours"):
            tot[k] += part[k]
        bk = tot["byKind"].setdefault(kind, {"hours": 0.0, "nightHours": 0.0, "pay": 0.0})
        bk["hours"] += part["hours"]
        bk["nightHours"] += part["nightHours"]
        bk["pay"] += part["pay"]
    return tot


def month_summary(records, hourly, holidays=(), rest_weekdays=(5, 6)):
    """One employee's overtime for a month: hours, pay, and the taxable/exempt split.

    `records` must already be filtered to APPROVED overtime — a pending or rejected request is not
    overtime, it is a request, and paying it would be paying for a decision nobody made.
    """
    out = {"pay": 0.0, "taxable": 0.0, "exempt": 0.0, "hours": 0.0, "nightHours": 0.0,
           "byKind": {}, "records": 0, "byDate": {}}
    for rec in records or ():
        part = record_pay(rec, hourly, holidays, rest_weekdays)
        if part["hours"] <= 0:
            continue
        out["records"] += 1
        for k in ("pay", "taxable", "exempt", "hours", "nightHours"):
            out[k] += part[k]
        for kind, bk in part["byKind"].items():
            agg = out["byKind"].setdefault(kind, {"hours": 0.0, "nightHours": 0.0, "pay": 0.0})
            for k in ("hours", "nightHours", "pay"):
                agg[k] += bk[k]
        d = str(rec.get("date") or "")[:10]
        out["byDate"][d] = out["byDate"].get(d, 0.0) + part["hours"]
    return out


# ── the caps ─────────────────────────────────────────────────────────────────────────────────────

def day_cap(normal_hours=NORMAL_DAY_HOURS, kind="normal"):
    """The ceiling on ONE day's overtime.

    Art. 107(2)(b) caps overtime at half the normal working hours of a normal working DAY, and caps
    normal + overtime together at 12 hours. On a weekly rest day or a public holiday there are no
    normal hours to take half of — the whole shift is overtime — so what binds is Decree 145/2020
    Art. 60's 12-hour ceiling on total hours in a day.

    Applying the 4-hour figure to a rest day was refusing lawful Sunday shutdown work as a statutory
    breach, and writing "OVER THE STATUTORY CAP" into the audit chain against a manager who had done
    nothing wrong.
    """
    if str(kind) in ("rest", "holiday"):
        return CAP_DAY_TOTAL
    return min(float(normal_hours) * CAP_DAY_RATIO, CAP_DAY_TOTAL - float(normal_hours))


def cap_check(day_hours=0.0, month_hours=0.0, year_hours=0.0,
              normal_hours=NORMAL_DAY_HOURS, annual_cap=CAP_YEAR_HOURS, day_kind="normal"):
    """Which statutory ceilings a set of totals breaks.

    Returns {"ok": bool, "breaches": [{"cap", "limit", "value", "message"}, ...]}. The totals passed
    in are expected to ALREADY INCLUDE the hours being decided — the question this answers is "if
    this is approved, is the company over the line", which is the only question worth asking before
    approving it.
    """
    breaches = []
    dc = day_cap(normal_hours, day_kind)
    if day_hours > dc + 1e-9:
        breaches.append({"cap": "day", "limit": dc, "value": day_hours,
                         "message": "Overtime on one day may not exceed %.1fh (%s)."
                                    % (dc, "Decree 145/2020 Art. 60 — 12 hours total on a rest day "
                                           "or holiday" if str(day_kind) in ("rest", "holiday")
                                       else "Labour Code Art. 107")})
    if month_hours > CAP_MONTH_HOURS + 1e-9:
        breaches.append({"cap": "month", "limit": CAP_MONTH_HOURS, "value": month_hours,
                         "message": "Overtime in one month may not exceed %.0fh (Labour Code Art. 107)."
                                    % CAP_MONTH_HOURS})
    cap_y = float(annual_cap or CAP_YEAR_HOURS)
    if year_hours > cap_y + 1e-9:
        breaches.append({"cap": "year", "limit": cap_y, "value": year_hours,
                         "message": "Overtime in one year may not exceed %.0fh (Labour Code Art. 107)."
                                    % cap_y})
    return {"ok": not breaches, "breaches": breaches}
