"""Annual leave entitlement — Labour Code Art. 113/114 and Decree 145/2020 Art. 66.

`annualTotal` on an employee record is a number somebody typed, and nothing has ever checked it. The
arithmetic here is what it should be checked against, so it has to be right to the day: one day short
across thirty people is thirty days of leave quietly not given.
"""
import leave_entitlement as le


# ── Art. 114: a day for every five completed years ───────────────────────────────────────────────

def test_a_new_starter_has_no_seniority_days():
    assert le.seniority_days("2026-01-01", "2026-12-31") == 0


def test_four_years_is_still_no_extra_day():
    assert le.seniority_days("2022-03-01", "2026-03-01") == 0


def test_five_completed_years_earns_the_first_extra_day():
    assert le.seniority_days("2021-03-01", "2026-03-01") == 1


def test_the_day_before_the_fifth_anniversary_it_is_not_yet_earned():
    """An off-by-one here gives somebody a day they have not earned, or withholds one they have."""
    assert le.seniority_days("2021-03-01", "2026-02-28") == 0


def test_ten_years_earns_two():
    assert le.seniority_days("2016-03-01", "2026-03-01") == 2


def test_service_measured_before_it_started_is_zero_not_negative():
    assert le.seniority_days("2026-03-01", "2020-01-01") == 0


# ── Art. 113(1): the base, by conditions and by person ───────────────────────────────────────────

def test_normal_conditions_are_twelve_days():
    assert le.base_days("normal") == 12


def test_heavy_or_hazardous_work_is_fourteen():
    assert le.base_days("heavy") == 14


def test_especially_hazardous_work_is_sixteen():
    assert le.base_days("especially_heavy") == 16


def test_a_minor_or_disabled_employee_gets_at_least_fourteen():
    assert le.base_days("normal", minor=True) == 14
    assert le.base_days("normal", disabled=True) == 14


def test_the_two_rules_combine_upwards_rather_than_overriding():
    """An under-18 on especially hazardous work is on 16, not 14. Taking the minor rule as an
    override instead of a floor would take two days off the person with the worst job."""
    assert le.base_days("especially_heavy", minor=True) == 16


def test_an_unknown_condition_falls_back_to_the_normal_twelve():
    assert le.base_days("something-else") == 12
    assert le.base_days(None) == 12


def test_age_is_measured_on_the_date_in_question_not_at_hire():
    assert le.is_minor("2009-06-01", "2026-05-31") is True     # still 16
    assert le.is_minor("2009-06-01", "2027-06-01") is False    # turned 18


# ── Decree 145/2020 Art. 66(2): months worked, and the 14-day part month ─────────────────────────

def test_a_full_calendar_year_is_twelve_months():
    assert le.months_worked("2020-01-01", "2026-01-01", "2026-12-31") == 12


def test_joining_on_the_first_of_july_is_six_months():
    assert le.months_worked("2026-07-01", "2026-01-01", "2026-12-31") == 6


def test_a_part_month_of_fourteen_days_counts_as_a_whole_one():
    """Joining on 18 December leaves 14 days of the year — a whole month under Art. 66(2)."""
    assert le.months_worked("2026-12-18", "2026-01-01", "2026-12-31") == 1


def test_a_part_month_of_thirteen_days_counts_as_none():
    assert le.months_worked("2026-12-19", "2026-01-01", "2026-12-31") == 0


def test_starting_after_the_window_closes_is_no_months_at_all():
    assert le.months_worked("2027-01-01", "2026-01-01", "2026-12-31") == 0


# ── Decree 145/2020 Art. 66(3): rounding is half-UP, in the employee's favour ────────────────────

def test_exactly_half_a_day_rounds_up():
    assert le.round_days(6.5) == 7


def test_below_half_rounds_down():
    assert le.round_days(6.49) == 6


def test_a_whole_number_is_left_alone():
    assert le.round_days(12) == 12


# ── the entitlement itself ───────────────────────────────────────────────────────────────────────

def test_a_full_year_in_normal_conditions_is_twelve_days():
    r = le.entitlement("2023-01-01", 2026)      # 3 years' service: no seniority day yet
    assert r["days"] == 12 and r["prorated"] is False


def test_a_full_year_after_five_years_service_is_thirteen():
    """The quiet one. Somebody who passed five years last March is on 13 days, and nothing in the
    portal has ever noticed that their record still says 12."""
    r = le.entitlement("2021-03-01", 2026)
    assert r["days"] == 13
    assert r["base"] == 12 and r["seniority"] == 1


def test_the_anniversary_counts_for_the_whole_year_it_falls_in():
    """Seniority is measured at the end of the leave year, not on 1 January — otherwise an employee
    whose fifth anniversary is in November waits until the following January for the day."""
    r = le.entitlement("2021-11-20", 2026)
    assert r["seniority"] == 1


def test_a_half_year_hire_gets_half_the_entitlement():
    r = le.entitlement("2026-07-01", 2026)
    assert r["months"] == 6
    assert r["days"] == 6 and r["prorated"] is True


def test_a_september_hire_is_prorated_not_rounded_to_a_whole_year():
    # 1 Sep → 31 Dec is 4 months; 12 / 12 × 4 = 4.
    r = le.entitlement("2026-09-01", 2026)
    assert r["months"] == 4 and r["days"] == 4


def test_proration_includes_the_seniority_day():
    """Art. 66 prorates the WHOLE entitlement, seniority included — not the base only. A long server
    who leaves mid-year loses the extra day pro-rata, and keeps it pro-rata."""
    r = le.entitlement("2016-01-01", 2026, end="2026-06-30")
    assert r["fullYearDays"] == 14        # 12 + 2 for ten years
    assert r["months"] == 6
    assert r["days"] == 7                 # 14 / 12 × 6 = 7


def test_leaving_mid_year_prorates_the_final_year():
    r = le.entitlement("2020-01-01", 2026, end="2026-04-30")
    assert r["months"] == 4 and r["days"] == 4


def test_someone_who_left_before_the_year_began_is_entitled_to_nothing():
    r = le.entitlement("2020-01-01", 2026, end="2025-12-31")
    assert r["days"] == 0


def test_someone_who_starts_after_the_year_ends_is_entitled_to_nothing():
    r = le.entitlement("2027-02-01", 2026)
    assert r["days"] == 0


def test_no_start_date_is_answered_honestly_rather_than_guessed():
    r = le.entitlement("", 2026)
    assert r["days"] == 0 and "no start date" in r["reason"]


def test_the_working_out_is_returned_because_hr_gets_asked_why(api=None):
    r = le.entitlement("2021-03-01", 2026)
    assert set(("days", "base", "seniority", "months", "prorated", "reason")) <= set(r)
    assert r["reason"] == "full year"


def test_a_site_worker_on_hazardous_duty_gets_the_higher_base():
    r = le.entitlement("2023-01-01", 2026, conditions="heavy")
    assert r["days"] == 14


# ── comparing it with what was typed ─────────────────────────────────────────────────────────────

def test_a_record_that_matches_the_law_is_not_a_finding():
    assert le.shortfall(13, 13) == 0


def test_a_record_below_the_statutory_minimum_is_the_shortfall():
    assert le.shortfall(12, 13) == 1


def test_giving_more_than_the_law_requires_is_lawful_and_not_a_finding():
    """Plenty of companies give 15. That is not a compliance problem and must not be reported as one."""
    assert le.shortfall(15, 13) == 0


def test_a_blank_entitlement_is_the_whole_entitlement_short():
    assert le.shortfall(None, 12) == 12
    assert le.shortfall("", 12) == 12
