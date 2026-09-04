"""Overtime inside the payslip — the arithmetic the frontend's _payComputed now mirrors.

payroll_calc.py is the tested reference for the Vietnam payroll math. Overtime changes three things
in it and must change no others: gross rises by the overtime pay, PIT rises by the ORDINARY-rate part
of it only, and the SI base does not move at all. Each of those is a different way to get somebody's
pay wrong, so each gets its own test.
"""
import payroll_calc as pc


BASE = dict(gross=33_000_000, gi=2, yrs=6, rating=3, deps=0, working_days=21)


def _c(**kw):
    return pc.compute(**dict(BASE, **kw))


def test_no_overtime_leaves_the_payslip_exactly_as_it_was():
    """The regression that matters most: every employee who worked no overtime must be paid the same
    to the dong as before this feature existed."""
    a = _c()
    b = _c(ot_units=0, ot_taxable_units=0)
    assert a == b
    assert a["otPay"] == 0 and a["otExempt"] == 0


def test_overtime_pay_is_the_hourly_wage_times_the_rate_units():
    """The hourly wage is (P1 + P2) over the month's normal hours — 21 days × 8h here."""
    c = _c(ot_units=23.5, ot_taxable_units=13)
    hourly = (c["P1"] + c["P2"]) / (21 * 8)
    assert abs(c["otHourly"] - hourly) <= 1
    assert abs(c["otPay"] - hourly * 23.5) <= 2


def test_overtime_raises_the_gross_by_exactly_the_overtime_pay():
    a, b = _c(), _c(ot_units=23.5, ot_taxable_units=13)
    assert b["grossPay"] - a["grossPay"] == b["otPay"]


def test_the_premium_above_the_ordinary_rate_is_exempt_from_tax():
    """Circular 111/2013 Art. 3(1)(i). 23.5 rate-units for 13 hours worked: 13 units of ordinary wage
    are taxable, the 10.5 units of premium are not."""
    c = _c(ot_units=23.5, ot_taxable_units=13)
    assert c["otTaxable"] < c["otPay"]
    assert c["otExempt"] == c["otPay"] - c["otTaxable"]


def test_tax_rises_on_the_ordinary_part_only_not_on_the_whole_overtime_pay():
    """The test that catches the easy mistake. Taxing the whole overtime payment over-withholds from
    the person who worked late; taxing none of it under-withholds and leaves the company liable."""
    b = _c(ot_units=23.5, ot_taxable_units=13)
    # Rebuild the taxable base by hand and add ONLY the ordinary-rate part of the overtime.
    base = (b["P1"] + b["P2"] + b["P3"] + pc.TRANSPORT) - b["si"] - pc.PIT_SELF
    assert b["pit"] == pc.pit(base + b["otTaxable"])
    # …and taxing the whole payment, premium included, would cost the employee strictly more.
    over_withheld = pc.pit(base + b["otPay"])
    assert over_withheld > b["pit"]


def test_overtime_never_enters_the_social_insurance_base():
    """The SI base is wage and fixed allowances. Overtime is neither, and adding it would overstate
    both the employee's deduction and the employer's 23.5%."""
    a, b = _c(), _c(ot_units=40, ot_taxable_units=20)
    assert a["siBase"] == b["siBase"]
    assert a["si"] == b["si"] and a["erTotal"] == b["erTotal"]


def test_the_employer_cost_rises_by_the_overtime_pay_and_nothing_more():
    a, b = _c(), _c(ot_units=23.5, ot_taxable_units=13)
    assert b["employerCost"] - a["employerCost"] == b["otPay"]


def test_net_pay_is_gross_less_the_deductions_including_the_new_tax():
    c = _c(ot_units=23.5, ot_taxable_units=13)
    assert c["net"] == c["grossPay"] - c["si"] - c["pit"] - c["unpaidDeduction"]


def test_the_hours_are_carried_through_for_the_wage_statement():
    """Art. 95(3): the statement must say how many hours, not just how much money."""
    c = _c(ot_units=23.5, ot_taxable_units=13, ot_hours=13, ot_night_hours=3)
    assert c["otHours"] == 13 and c["otNightHours"] == 3


def test_a_month_with_no_working_days_does_not_divide_by_zero():
    c = pc.compute(gross=33_000_000, working_days=0, ot_units=10, ot_taxable_units=5)
    assert c["otPay"] >= 0
