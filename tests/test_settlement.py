"""Final settlement — what is owed when somebody leaves, and by when.

The severance exclusion decides most of the money and cuts against intuition: unemployment insurance
has been compulsory since 2009, so for anybody hired since then the qualifying service is nil.
Getting that backwards either overpays everybody consistently or underpays the long servers, so it
gets the most tests here.
"""
import settlement as S


# ── service time ─────────────────────────────────────────────────────────────────────────────────

def test_a_full_year_is_twelve_months():
    assert S.months_between("2025-01-01", "2025-12-31") == 12


def test_service_that_runs_backwards_is_zero():
    assert S.months_between("2026-01-01", "2025-01-01") == 0


def test_whole_years_are_whole_years():
    assert S.service_years(24) == 2.0


def test_a_remainder_of_six_months_or_less_is_half_a_year():
    """Decree 145/2020 Art. 8(3)."""
    assert S.service_years(12 + 6) == 1.5
    assert S.service_years(12 + 1) == 1.5


def test_a_remainder_over_six_months_is_a_whole_year():
    assert S.service_years(12 + 7) == 2.0


def test_no_service_is_no_years():
    assert S.service_years(0) == 0.0


# ── Art. 46(2): the exclusion that decides the money ─────────────────────────────────────────────

def test_service_entirely_after_unemployment_insurance_began_does_not_qualify():
    """The surprising and correct answer for almost everybody hired this century."""
    assert S.qualifying_months("2015-06-01", "2026-06-01") == 0


def test_service_entirely_before_it_qualifies_in_full():
    assert S.qualifying_months("2000-01-01", "2005-12-31") == 72


def test_a_career_spanning_the_boundary_qualifies_only_for_the_earlier_part():
    """Joined 2005, left 2026: 21 years of service, 4 of which are severance-qualifying."""
    qm = S.qualifying_months("2005-01-01", "2026-01-01")
    assert qm == 48, "1 Jan 2005 to 31 Dec 2008 is four years"


def test_a_part_month_is_not_a_whole_one_for_somebody_who_started_on_the_first():
    """The flaw a day-of-month shortcut hides. Half the workforce starts on the 1st, and counting
    their part months as whole ones overstates severance at half a month's wage per year."""
    assert S.months_between("2015-01-01", "2015-01-15") == 0
    assert S.months_between("2015-01-01", "2015-01-31") == 1
    assert S.months_between("2015-01-01", "2016-01-01") == 12, "12 months and a day is 12 months"


def test_anything_already_paid_out_is_not_paid_twice():
    assert S.qualifying_months("2000-01-01", "2005-12-31", already_paid_months=24) == 48


def test_the_boundary_is_an_input_not_a_hard_coded_assumption():
    assert S.qualifying_months("2015-06-01", "2026-06-01", ui_from="2020-01-01") > 0


# ── the allowance itself ─────────────────────────────────────────────────────────────────────────

W = 20_000_000


def test_under_twelve_months_of_service_earns_no_allowance():
    r = S.severance("2026-01-01", "2026-08-01", W)
    assert r["amount"] == 0 and "12 months" in r["reason"]


def test_a_modern_hire_gets_nothing_and_is_told_why():
    """"Why is my severance zero" is the question this will be asked. The answer has to be in it."""
    r = S.severance("2015-06-01", "2026-06-01", W)
    assert r["amount"] == 0
    assert "unemployment insurance" in r["reason"]


def test_a_long_server_from_before_2009_gets_half_a_month_per_qualifying_year():
    r = S.severance("2005-01-01", "2026-01-01", W)
    assert r["years"] == 4.0
    assert r["amount"] == 4.0 * 0.5 * W


def test_a_redundancy_is_a_job_loss_allowance_at_a_month_a_year():
    r = S.severance("2015-01-01", "2026-01-01", W, reason="redundancy")
    assert r["kind"] == "jobloss"
    assert r["years"] == 11.0
    assert r["amount"] == 11.0 * W


def test_the_job_loss_allowance_is_never_less_than_two_months():
    """Art. 47(1). Exactly one year of service earns one month at the per-year rate, and the floor
    lifts it to two — so the case has to be somebody with UNDER two years, or the floor never bites
    and the test proves nothing."""
    r = S.severance("2025-01-01", "2025-12-31", W, reason="redundancy")
    assert r["years"] == 1.0
    assert r["amount"] == 2.0 * W, "one month a year would pay 1; the Art. 47 floor makes it 2"


def test_a_redundancy_is_NOT_reduced_by_unemployment_insurance():
    """Art. 46(2)'s exclusion is written for severance alone. Reading it across to Art. 47 would
    halve what a redundancy is worth to somebody who has only ever worked in the UI era."""
    r = S.severance("2015-01-01", "2026-01-01", W, reason="redundancy")
    assert r["amount"] > 0
    assert r["monthsQualifying"] == 132


# ── Decree 145/2020 Art. 8(2): the wage the allowance is computed on ─────────────────────────────

def test_the_wage_is_the_average_of_the_last_six_months():
    assert S.average_wage([10, 10, 10, 20, 20, 20]) == 15


def test_only_the_last_six_are_taken_even_when_more_are_given():
    assert S.average_wage([1, 1, 1, 1, 1, 1, 10, 10, 10, 10, 10, 10]) == 10


def test_a_short_history_averages_what_there_is_rather_than_dividing_by_six():
    """Dividing three months by six would understate the wage and so the allowance."""
    assert S.average_wage([20, 20, 20]) == 20


def test_no_wage_history_is_zero_not_a_crash():
    assert S.average_wage([]) == 0.0


# ── Art. 48(1): the deadline ─────────────────────────────────────────────────────────────────────

def test_the_deadline_is_fourteen_working_days_not_calendar_days():
    """Employment ends Friday 31 July 2026; 14 working days lands on Thursday 20 August."""
    assert str(S.deadline("2026-07-31")) == "2026-08-20"


def test_public_holidays_push_the_deadline_out():
    """28 Aug 2026 is a Friday. Fourteen working days from the Monday, with National Day on the 2nd
    and 3rd skipped, lands on 21 September rather than the 17th it would reach without them."""
    assert str(S.deadline("2026-08-28")) == "2026-09-17"
    assert str(S.deadline("2026-08-28", holidays=["2026-09-02", "2026-09-03"])) == "2026-09-21"


def test_a_factory_pattern_counts_saturday_as_a_working_day():
    office = S.deadline("2026-07-31")
    factory = S.deadline("2026-07-31", rest_weekdays=(6,))
    assert factory < office


def test_the_extended_thirty_day_case_is_available():
    d14 = S.deadline("2026-07-31", working_days=S.SETTLE_WORKING_DAYS)
    d30 = S.deadline("2026-07-31", working_days=S.SETTLE_WORKING_DAYS_EXTENDED)
    assert d30 > d14


# ── the whole settlement ─────────────────────────────────────────────────────────────────────────

def test_untaken_leave_is_paid_out():
    """Art. 113(4)."""
    r = S.settle("2015-01-01", "2026-06-30", W, leave_days_untaken=5)
    line = next(l for l in r["lines"] if "Untaken annual leave" in l["label"])
    assert line["amount"] == 5 * (W / 26.0)
    assert "Art. 113(4)" in line["basis"]


def test_a_settlement_with_nothing_owed_is_zero_rather_than_an_error():
    r = S.settle("2026-01-01", "2026-03-01", W)
    assert r["total"] == 0 and r["lines"] == []


def test_every_line_carries_the_article_it_comes_from():
    """Somebody signs this and somebody receives it. Both should be able to see why each figure is
    there without asking."""
    r = S.settle("2005-01-01", "2026-01-31", W, leave_days_untaken=3, outstanding_salary=5_000_000)
    bases = " ".join(l["basis"] for l in r["lines"])
    assert "Art. 113(4)" in bases and "Art. 46" in bases


def test_deductions_come_off_the_total():
    r = S.settle("2015-01-01", "2026-06-30", W, leave_days_untaken=0,
                 outstanding_salary=10_000_000, deductions=3_000_000)
    assert r["total"] == 7_000_000


def test_the_deadline_travels_with_the_settlement():
    r = S.settle("2015-01-01", "2026-07-31", W)
    assert r["deadline"] == "2026-08-20"
    assert "Art. 48(1)" in r["deadlineBasis"]


def test_a_daily_rate_can_be_given_rather_than_derived():
    r = S.settle("2015-01-01", "2026-06-30", W, leave_days_untaken=2, daily_rate=1_000_000)
    assert r["leavePay"] == 2_000_000
