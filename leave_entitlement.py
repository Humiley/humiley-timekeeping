"""How many days of annual leave somebody is actually entitled to, under Vietnamese law.

`annualTotal` on the employee record is a number a person typed. Nothing has ever checked it against
the entitlement the law requires, so an employee on 12 days who passed five years' service last March
is quietly a day short, and a hire who joined in September is either over- or under-credited depending
on who did the arithmetic. Neither shows up anywhere: the balance simply reads whatever was typed.

This module computes the statutory figure so the typed one can be compared against it. It is pure —
no database, no clock — so every rule below is exercised by tests/test_leave_entitlement.py.

The law:

  Art. 113(1) Labour Code 2019   12 working days a year in normal conditions; 14 for a minor, a
                                 disabled employee, or heavy/hazardous/dangerous work; 16 for
                                 especially heavy/hazardous/dangerous work.
  Art. 113(2)                    less than 12 months' service earns leave in proportion.
  Art. 114                       one extra day for every 5 completed years with the same employer.
  Art. 113(4)                    untaken leave is paid out when employment ends.
  Decree 145/2020 Art. 66        the proration formula, the 14-day rule for a part month, and the
                                 rounding: a fraction of 0.5 or more rounds UP to a whole day.

Every figure here is a statutory MINIMUM. A company may give more and many do; it may not give less.
"""
import math
from datetime import date

# ── Art. 113(1): the base entitlement, by working conditions ─────────────────────────────────────
BASE_DAYS = {
    "normal": 12,
    "heavy": 14,               # heavy, hazardous or dangerous work
    "especially_heavy": 16,    # especially heavy, hazardous or dangerous work
}
MINOR_OR_DISABLED_DAYS = 14    # Art. 113(1)(b), whatever the conditions

# ── Art. 114: seniority ──────────────────────────────────────────────────────────────────────────
SENIORITY_EVERY_YEARS = 5
SENIORITY_DAYS_EACH = 1

# ── Decree 145/2020 Art. 66(2): a part month counts as a whole one from 14 days ──────────────────
PART_MONTH_DAYS = 14

CONDITIONS = tuple(BASE_DAYS)


def _d(value):
    """'2021-03-15' → date(2021, 3, 15). None for anything that is not a date."""
    if isinstance(value, date):
        return value
    try:
        y, m, dd = (int(x) for x in str(value)[:10].split("-"))
        return date(y, m, dd)
    except (ValueError, AttributeError, TypeError):
        return None


def completed_years(start, as_of):
    """Whole years of service completed by `as_of`. An anniversary counts on the day it falls."""
    s, a = _d(start), _d(as_of)
    if not s or not a or a < s:
        return 0
    years = a.year - s.year
    if (a.month, a.day) < (s.month, s.day):
        years -= 1
    return max(0, years)


def seniority_days(start, as_of):
    """Art. 114: one day for every five completed years with the same employer."""
    return (completed_years(start, as_of) // SENIORITY_EVERY_YEARS) * SENIORITY_DAYS_EACH


def base_days(conditions="normal", minor=False, disabled=False):
    """Art. 113(1). A minor or disabled employee gets at least 14 days whatever the conditions, so
    the two rules are combined by taking whichever is greater rather than overriding one with the
    other — an under-18 on especially hazardous work is on 16, not 14."""
    base = BASE_DAYS.get(str(conditions or "normal"), BASE_DAYS["normal"])
    if minor or disabled:
        base = max(base, MINOR_OR_DISABLED_DAYS)
    return base


def is_minor(dob, as_of):
    """Under 18 on the date in question. Art. 113(1)(b) is about age at the time, not at hire."""
    b, a = _d(dob), _d(as_of)
    if not b or not a:
        return False
    return completed_years(b, a) < 18


def months_worked(start, period_start, period_end):
    """Decree 145/2020 Art. 66(2): whole months worked inside a window, where a part month of 14
    days or more counts as a whole one.

    Used for a first or final year, where service covers only part of the calendar year.
    """
    s, p0, p1 = _d(start), _d(period_start), _d(period_end)
    if not s or not p0 or not p1:
        return 0
    begin = max(s, p0)
    if begin > p1:
        return 0
    months = (p1.year - begin.year) * 12 + (p1.month - begin.month)
    # The days left over after those whole months — inclusive of both ends, as a worked day is a day.
    anchor_month = begin.month + months
    anchor_year = begin.year + (anchor_month - 1) // 12
    anchor_month = (anchor_month - 1) % 12 + 1
    day = min(begin.day, _days_in_month(anchor_year, anchor_month))
    leftover = (p1 - date(anchor_year, anchor_month, day)).days + 1
    if leftover < 0:
        months -= 1
        leftover = 0
    return months + (1 if leftover >= PART_MONTH_DAYS else 0)


def _days_in_month(y, m):
    if m == 12:
        return 31
    return (date(y + (m // 12), m % 12 + 1, 1) - date(y, m, 1)).days


def round_days(x):
    """Decree 145/2020 Art. 66(3): round to whole days, and a fraction of 0.5 or more rounds UP.

    Round-half-UP, not Python's round-half-to-even: at exactly 6.5 days the employee gets 7.
    """
    return int(math.floor(float(x) + 0.5))


def entitlement(start, year, conditions="normal", dob=None, disabled=False, end=None,
                as_of=None):
    """One employee's statutory annual leave for one calendar year.

    `start`  — the employment start date
    `year`   — the calendar year being asked about
    `end`    — the last day of employment, if they left during the year (Art. 113(2) prorates it too)
    `as_of`  — the date seniority is measured at; defaults to the end of the year in question, so a
               five-year anniversary falling in November counts for that whole year.

    Returns the days, and the working out — because "why is she on 13" is a question HR gets asked
    and a single number cannot answer.
    """
    s = _d(start)
    if not s:
        return {"days": 0, "base": 0, "seniority": 0, "months": 0, "prorated": False,
                "reason": "no start date on record"}

    y0, y1 = date(year, 1, 1), date(year, 12, 31)
    e = _d(end)
    last = min(e, y1) if e else y1
    if s > y1 or (e and e < y0):
        return {"days": 0, "base": 0, "seniority": 0, "months": 0, "prorated": False,
                "reason": "not employed during %d" % year}

    ref = _d(as_of) or last
    b = base_days(conditions, minor=is_minor(dob, ref), disabled=disabled)
    sen = seniority_days(s, ref)
    full = b + sen

    # A full calendar year of service earns the full entitlement; anything less is prorated.
    partial = s > y0 or last < y1
    if not partial:
        return {"days": full, "base": b, "seniority": sen, "months": 12, "prorated": False,
                "reason": "full year"}

    m = months_worked(s, y0, last)
    days = round_days(full / 12.0 * m)
    return {"days": days, "base": b, "seniority": sen, "months": m, "prorated": True,
            "fullYearDays": full,
            "reason": "%d of 12 months worked" % m}


def shortfall(stored, computed):
    """How many days short of the statutory minimum a typed entitlement is. Never negative: giving
    more than the law requires is lawful and common, and is not a finding."""
    try:
        have = float(stored or 0)
    except (TypeError, ValueError):
        have = 0.0
    return max(0.0, float(computed or 0) - have)
