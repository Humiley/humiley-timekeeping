"""Counting whole months between two dates, once, correctly.

Three modules grew their own version of this — contracts, settlement and certificates — and they did
not agree. The tempting shortcut is to compare day-of-month:

    months = (e.y - s.y) * 12 + (e.m - s.m)
    if e.day >= s.day - 1: months += 1

It is wrong twice over. For a start on the 1st it counts every part month as whole, which overstated
severance at half a month's wage per year. For a start mid-month it counts one month too many, which
flagged lawful 36-month labour contracts as breaching the Art. 20(1)(b) ceiling.

The rule these are all reaching for is: a period that begins on the 15th completes a month on the
14th of the next month. So the honest way to count is to ask how many whole months fit — walking the
anniversary rather than arithmetic on the day number, which also handles a 31st landing in February.
"""
from datetime import date, timedelta


def to_date(value):
    """'2026-03-15' → date(2026, 3, 15). None for anything that is not a date."""
    if isinstance(value, date):
        return value
    try:
        y, m, d = (int(x) for x in str(value)[:10].split("-"))
        return date(y, m, d)
    except (ValueError, AttributeError, TypeError):
        return None


def days_in_month(y, m):
    if m == 12:
        return 31
    return (date(y, m + 1, 1) - date(y, m, 1)).days


def add_months(d, months):
    """The same day-of-month `months` later, clamped to a shorter month — 31 Jan plus one month is
    28 Feb, not 3 March, because a period should not drift forward."""
    d = to_date(d)
    if not d:
        return None
    m = d.month - 1 + int(months)
    y = d.year + m // 12
    m = m % 12 + 1
    return date(y, m, min(d.day, days_in_month(y, m)))


def whole_months(start, end):
    """Whole months from `start` to `end`, where `end` is the LAST DAY INCLUDED.

    1 Jan → 31 Jan is one month. 1 Jan → 15 Jan is none. 15 Mar 2026 → 14 Mar 2029 is 36, which is a
    lawful three-year contract rather than the 37 the shortcut reported.
    """
    s, e = to_date(start), to_date(end)
    if not s or not e or e < s:
        return 0
    k = (e.year - s.year) * 12 + (e.month - s.month)
    while k > 0 and add_months(s, k) - timedelta(days=1) > e:
        k -= 1
    while add_months(s, k + 1) - timedelta(days=1) <= e:
        k += 1
    return max(0, k)
