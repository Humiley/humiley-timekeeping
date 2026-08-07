"""What is owed when somebody leaves, and by when.

An exit record in the portal has held a settlement figure somebody typed. Nothing computed it, nothing
checked it, and nothing turned it into a payment — so the amount was an opinion and the payment was a
separate act of memory. The law is more specific than that on every count.

  Art. 48(1) Labour Code 2019   both parties settle all payments within 14 WORKING DAYS of
                                termination, extendable to 30 days in the cases the article lists.
  Art. 113(4)                   annual leave earned and not taken is PAID OUT on termination.
  Art. 46                       severance allowance (trợ cấp thôi việc): half a month's wage for each
                                year of service, for an employee who worked regularly for 12 months
                                or more — but the qualifying time EXCLUDES any period for which
                                unemployment insurance was paid, and any period already paid out.
  Art. 47                       job-loss allowance (trợ cấp mất việc làm) where the ending is a
                                redundancy: one month per year, and never less than two months.
  Decree 145/2020 Art. 8(2)     the wage for both allowances is the AVERAGE of the six consecutive
                                months under the labour contract before termination.
  Decree 145/2020 Art. 8(3)     service time rounds to whole years: a remainder of up to 6 months
                                counts as half a year, more than 6 months as a full year.

The severance exclusion is the one that decides most of the money, and it cuts the other way from
what people expect: compulsory unemployment insurance has run since 1 January 2009, so for anybody
hired since then the qualifying service is usually NIL and the allowance with it. Paying severance
to everybody would be a large and consistent overpayment; assuming nobody qualifies would underpay
the long servers who were here before 2009. So the boundary is an input, not a guess.

Pure — no database, no clock. Every rule is exercised by tests/test_settlement.py.
"""
from datetime import date, timedelta

# Compulsory unemployment insurance began on 1 January 2009 (Law on Social Insurance 2006). Service
# from that date is normally covered by UI and therefore excluded from Art. 46 severance.
UI_FROM = "2009-01-01"

SEVERANCE_MONTHS_PER_YEAR = 0.5      # Art. 46(1)
JOBLOSS_MONTHS_PER_YEAR = 1.0        # Art. 47(1)
JOBLOSS_MINIMUM_MONTHS = 2.0         # Art. 47(1): never less than two months' wage
MIN_SERVICE_MONTHS = 12              # Art. 46(1): "worked regularly for 12 months or more"
SETTLE_WORKING_DAYS = 14             # Art. 48(1)
SETTLE_WORKING_DAYS_EXTENDED = 30    # …extendable in the cases Art. 48(1) lists

# Endings that attract the JOB-LOSS allowance rather than severance: a redundancy for organisational
# or technological change, or on a merger/division (Art. 34(11) via Art. 42 and 43).
JOBLOSS_REASONS = ("redundancy", "restructure", "merger")


def _d(value):
    if isinstance(value, date):
        return value
    try:
        y, m, dd = (int(x) for x in str(value)[:10].split("-"))
        return date(y, m, dd)
    except (ValueError, AttributeError, TypeError):
        return None


def _add_months(d, months):
    """The same day-of-month `months` later, clamped to a shorter month."""
    m = d.month - 1 + int(months)
    y = d.year + m // 12
    m = m % 12 + 1
    last = 31 if m == 12 else (date(y + (m // 12), m % 12 + 1, 1) - date(y, m, 1)).days
    return date(y, m, min(d.day, last))


def months_between(start, end):
    """Whole months of service from start to end, where `end` is the LAST DAY WORKED.

    A month that began on the 3rd is complete on the 2nd of the next month, so the test is against
    the day BEFORE the anniversary. The tempting shortcut — comparing day-of-month directly — is
    wrong for anybody who started on the 1st: it treats every part month as a whole one, and since
    severance is half a month's wage per year, that overstates what is owed for half the workforce.
    """
    s, e = _d(start), _d(end)
    if not s or not e or e < s:
        return 0
    k = (e.year - s.year) * 12 + (e.month - s.month)
    while k > 0 and _add_months(s, k) - timedelta(days=1) > e:
        k -= 1
    while _add_months(s, k + 1) - timedelta(days=1) <= e:
        k += 1
    return max(0, k)


def qualifying_months(start, end, ui_from=UI_FROM, already_paid_months=0):
    """Art. 46(2): actual service, LESS any period covered by unemployment insurance, less anything
    already paid out as severance or job-loss allowance.

    For anybody hired after unemployment insurance became compulsory this is nil, which is the
    correct and frequently surprising answer.
    """
    s, e, ui = _d(start), _d(end), _d(ui_from)
    if not s or not e or e < s:
        return 0
    if ui:
        e = min(e, ui - timedelta(days=1))      # only service BEFORE UI began qualifies
        if e < s:
            return 0
    return max(0, months_between(s, e) - int(already_paid_months or 0))


def service_years(months):
    """Decree 145/2020 Art. 8(3): whole years, a remainder of up to 6 months counting as half a year
    and more than 6 months as a full one."""
    if months <= 0:
        return 0.0
    years, rem = divmod(int(months), 12)
    if rem == 0:
        return float(years)
    return years + (0.5 if rem <= 6 else 1.0)


def average_wage(monthly_wages):
    """Decree 145/2020 Art. 8(2): the average of the six consecutive months before termination.

    Fewer than six months on record averages what there is rather than dividing by six — dividing a
    short history by six would understate the wage and therefore the allowance.
    """
    vals = [float(w) for w in (monthly_wages or []) if w not in (None, "")][-6:]
    if not vals:
        return 0.0
    return sum(vals) / len(vals)


def severance(start, end, wage, reason="", ui_from=UI_FROM, already_paid_months=0):
    """Art. 46 severance, or Art. 47 job-loss allowance where the ending is a redundancy.

    Returns the amount and the working out, because "why is my severance zero" is the question this
    will actually be asked, and the answer — that unemployment insurance covered the period — is not
    something anybody should have to reconstruct.
    """
    total_months = months_between(start, end)
    is_jobloss = str(reason or "").strip().lower() in JOBLOSS_REASONS

    if total_months < MIN_SERVICE_MONTHS:
        return {"amount": 0.0, "years": 0.0, "kind": "none", "monthsQualifying": 0,
                "reason": "less than 12 months of service (Art. 46(1))"}

    if is_jobloss:
        # Art. 47 is NOT reduced by unemployment insurance — the exclusion in Art. 46(2) is written
        # for severance alone, and reading it across would halve what a redundancy is worth.
        yrs = service_years(total_months)
        amount = max(yrs * JOBLOSS_MONTHS_PER_YEAR, JOBLOSS_MINIMUM_MONTHS) * float(wage or 0)
        return {"amount": amount, "years": yrs, "kind": "jobloss",
                "monthsQualifying": total_months,
                "reason": "job-loss allowance, %.1f year(s) at 1 month, minimum 2 months (Art. 47)"
                          % yrs}

    qm = qualifying_months(start, end, ui_from, already_paid_months)
    yrs = service_years(qm)
    if yrs <= 0:
        return {"amount": 0.0, "years": 0.0, "kind": "severance", "monthsQualifying": 0,
                "reason": "no qualifying service: unemployment insurance has covered the whole "
                          "period since %s, which Art. 46(2) excludes" % str(_d(ui_from) or "")}
    return {"amount": yrs * SEVERANCE_MONTHS_PER_YEAR * float(wage or 0), "years": yrs,
            "kind": "severance", "monthsQualifying": qm,
            "reason": "severance, %.1f qualifying year(s) at half a month (Art. 46); service from "
                      "%s excluded as covered by unemployment insurance"
                      % (yrs, str(_d(ui_from) or ""))}


def deadline(end, working_days=SETTLE_WORKING_DAYS, holidays=(), rest_weekdays=(5, 6)):
    """Art. 48(1): the date by which everything must be settled, counted in WORKING days from the
    day after employment ends."""
    e = _d(end)
    if not e:
        return None
    hol = {str(h)[:10] for h in (holidays or ())}
    d, left = e, int(working_days)
    while left > 0:
        d += timedelta(days=1)
        if d.weekday() not in set(rest_weekdays or ()) and d.strftime("%Y-%m-%d") not in hol:
            left -= 1
    return d


def settle(start, end, wage, leave_days_untaken=0, daily_rate=None, reason="",
           outstanding_salary=0, deductions=0, ui_from=UI_FROM, already_paid_months=0,
           holidays=(), rest_weekdays=(5, 6), working_days=SETTLE_WORKING_DAYS):
    """Everything owed on the way out, itemised.

    `daily_rate` is what one untaken leave day is worth — Art. 113(4) pays it at the wage for the
    job, so it defaults to the average monthly wage over the standard 26-day month if not given.
    """
    sev = severance(start, end, wage, reason, ui_from, already_paid_months)
    rate = float(daily_rate) if daily_rate not in (None, "") else (float(wage or 0) / 26.0)
    leave_pay = max(0.0, float(leave_days_untaken or 0)) * rate

    lines = []
    if outstanding_salary:
        lines.append({"label": "Outstanding salary to the last working day",
                      "amount": float(outstanding_salary), "basis": ""})
    if leave_pay:
        lines.append({"label": "Untaken annual leave (%.1f day(s))" % float(leave_days_untaken),
                      "amount": leave_pay,
                      "basis": "Art. 113(4) — leave earned and not taken is paid out"})
    if sev["amount"]:
        lines.append({"label": "Job-loss allowance" if sev["kind"] == "jobloss" else "Severance allowance",
                      "amount": sev["amount"], "basis": sev["reason"]})
    if deductions:
        lines.append({"label": "Deductions", "amount": -abs(float(deductions)), "basis": ""})

    total = sum(l["amount"] for l in lines)
    return {"lines": lines, "total": total, "severance": sev,
            "leavePay": leave_pay, "dailyRate": rate,
            "deadline": str(deadline(end, working_days, holidays, rest_weekdays) or ""),
            "deadlineBasis": "Art. 48(1) — %d working days from the end of employment" % working_days}
