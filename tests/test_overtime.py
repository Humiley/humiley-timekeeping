"""Overtime — the rate, the night premium, the tax split and the cap.

Approved overtime used to stop at the attendance row: it was requested, approved, stored, and then
never paid. These tests pin down the arithmetic that now carries it to a payslip, because a rate
applied to the wrong kind of day is the difference between paying somebody 150% and 300% for the
same Tết night shift.

Rates are the statutory minima in Labour Code 2019 Art. 98 and Decree 145/2020 Art. 57.
"""
import overtime as ot

H = 100_000.0      # a round hourly wage, so every expected figure below can be read by eye


# ── the night window (Art. 106: 22:00 – 06:00) ───────────────────────────────────────────────────

def test_an_evening_shift_that_ends_before_ten_has_no_night_hours():
    assert ot.night_minutes(17 * 60, 22 * 60) == 0


def test_the_night_window_opens_at_exactly_ten():
    assert ot.night_minutes(21 * 60, 23 * 60) == 60


def test_a_span_running_past_midnight_stays_inside_the_same_night():
    """23:00 → 02:00 is three night hours, not two-then-a-new-day."""
    assert ot.night_minutes(23 * 60, 26 * 60) == 180


def test_the_night_window_closes_at_six():
    assert ot.night_minutes(24 * 60 + 5 * 60, 24 * 60 + 8 * 60) == 60      # 05:00 → 08:00 next day


def test_a_span_covering_two_separate_nights_counts_both():
    # 20:00 on day 0 through 08:00 on day 2 — two full 22:00→06:00 windows.
    assert ot.night_minutes(20 * 60, 2 * 1440 + 8 * 60) == 2 * 8 * 60


# ── the overtime window is the TAIL of the shift ─────────────────────────────────────────────────

def test_overtime_is_the_last_hours_of_the_shift():
    assert ot.ot_window("08:00", "19:00", 2) == (17 * 60, 19 * 60)


def test_a_checkout_before_the_checkin_ran_past_midnight():
    """Without the +24h carry a 22:00 → 01:00 stint reads as a negative window and earns no night
    premium at all — the single most expensive hour of the day, unpaid."""
    assert ot.ot_window("08:00", "01:00", 3) == (22 * 60, 25 * 60)


def test_no_overtime_hours_means_no_window():
    assert ot.ot_window("08:00", "17:00", 0) is None
    assert ot.ot_window("08:00", "17:00", None) is None


def test_an_unparseable_clock_time_is_not_guessed_at():
    assert ot.ot_window("08:00", "", 2) is None
    assert ot.ot_window("08:00", "25:99", 2) is None


# ── which kind of day it was ─────────────────────────────────────────────────────────────────────

def test_a_weekday_is_a_normal_day():
    assert ot.day_kind("2026-06-10") == "normal"          # Wednesday


def test_sunday_is_a_rest_day_for_the_office():
    assert ot.day_kind("2026-06-14") == "rest"            # Sunday


def test_saturday_is_a_working_day_on_the_factory_pattern():
    """The factory runs Mon–Sat. Paying its Saturday overtime at the office's 200% rest-day rate
    would be as wrong as paying the office's at 150%."""
    assert ot.day_kind("2026-06-13", rest_weekdays=(6,)) == "normal"
    assert ot.day_kind("2026-06-13") == "rest"


def test_a_public_holiday_outranks_a_rest_day():
    assert ot.day_kind("2026-06-14", holidays=["2026-06-14"]) == "holiday"


def test_an_unparseable_date_falls_back_to_the_cheapest_honest_answer():
    assert ot.day_kind("not-a-date") == "normal"


# ── the hourly rate (Decree 145/2020 Art. 55) ────────────────────────────────────────────────────

def test_the_hourly_rate_is_the_month_wage_over_the_month_normal_hours():
    assert ot.hourly_rate(22_000_000, 22) == 125_000       # 22 days × 8h = 176h


def test_a_month_with_no_working_days_does_not_divide_by_zero():
    assert ot.hourly_rate(22_000_000, 0) == 0.0


# ── the three rates (Art. 98(1)) ─────────────────────────────────────────────────────────────────

def test_a_normal_day_pays_one_and_a_half():
    p = ot.pay_for(2, 0, "normal", H)
    assert p["pay"] == 300_000


def test_a_rest_day_pays_double():
    assert ot.pay_for(2, 0, "rest", H)["pay"] == 400_000


def test_a_public_holiday_pays_treble():
    assert ot.pay_for(2, 0, "holiday", H)["pay"] == 600_000


def test_only_the_premium_above_the_normal_rate_escapes_tax():
    """Circular 111/2013 Art. 3(1)(i). Two hours at 150% is 200,000 of ordinary taxable wage and
    100,000 of exempt premium — taxing the whole 300,000 over-withholds from the person who worked
    late, and taxing none of it under-withholds."""
    p = ot.pay_for(2, 0, "normal", H)
    assert (p["taxable"], p["exempt"]) == (200_000, 100_000)
    h = ot.pay_for(2, 0, "holiday", H)
    assert (h["taxable"], h["exempt"]) == (200_000, 400_000)


def test_night_overtime_adds_the_thirty_and_the_twenty():
    """Art. 98(2) adds 30% for working at night; Art. 98(3) adds a further 20% because it is also
    overtime. Two night hours on a normal day: 150% + 30% + 20% = 200%."""
    p = ot.pay_for(2, 2, "normal", H)
    assert p["pay"] == 400_000
    assert p["taxable"] == 200_000                       # the whole uplift is exempt


def test_the_night_uplift_applies_only_to_the_hours_actually_at_night():
    p = ot.pay_for(4, 2, "normal", H)                    # 4h overtime, 2 of them after 22:00
    assert p["pay"] == 4 * H * 1.5 + 2 * H * 0.3 + 2 * H * 0.2


def test_night_hours_can_never_exceed_the_hours_worked():
    assert ot.pay_for(1, 9, "normal", H)["nightHours"] == 1


# ── a whole attendance row ───────────────────────────────────────────────────────────────────────

def _rec(date, cin, cout, hours):
    return {"date": date, "clock_in": cin, "clock_out": cout, "ot_hours": hours}


def test_a_plain_two_hour_evening_of_overtime():
    p = ot.record_pay(_rec("2026-06-10", "08:00", "19:00", 2), H)
    assert p["hours"] == 2 and p["nightHours"] == 0
    assert p["pay"] == 300_000


def test_overtime_running_through_midnight_is_split_across_the_two_days():
    """22:00 → 01:00: two hours belong to the 10th and one to the 11th. All three are night hours."""
    p = ot.record_pay(_rec("2026-06-10", "08:00", "01:00", 3), H)
    assert p["hours"] == 3 and p["nightHours"] == 3
    assert p["pay"] == 600_000                            # 3h × (150% + 30% + 20%) × 100,000
    assert p["taxable"] == 300_000


def test_the_hours_that_land_on_the_holiday_are_paid_at_the_holiday_rate():
    """A shift starting on New Year's Eve and running into New Year's Day. The old code would have
    priced the whole stint by one date; Art. 98(1)(c) prices the part that fell on the holiday at
    300%, and that part alone."""
    p = ot.record_pay(_rec("2025-12-31", "08:00", "01:00", 3), H, holidays=["2026-01-01"])
    # 2h on the 31st (normal, night) + 1h on the 1st (holiday, night)
    expect = (2 * H * 1.5 + 2 * H * 0.3 + 2 * H * 0.2) + (1 * H * 3.0 + 1 * H * 0.3 + 1 * H * 0.2 * 3.0)
    assert round(p["pay"]) == round(expect)
    assert set(p["byKind"]) == {"normal", "holiday"}
    assert p["byKind"]["holiday"]["hours"] == 1


def test_a_record_with_no_overtime_is_worth_nothing():
    assert ot.record_pay(_rec("2026-06-10", "08:00", "17:00", 0), H)["pay"] == 0


# ── a month ──────────────────────────────────────────────────────────────────────────────────────

def test_a_month_adds_up_by_kind_and_by_date():
    recs = [_rec("2026-06-10", "08:00", "19:00", 2),      # Wednesday, normal
            _rec("2026-06-14", "08:00", "12:00", 4),      # Sunday, rest
            _rec("2026-06-11", "08:00", "19:00", 2)]      # Thursday, normal
    s = ot.month_summary(recs, H)
    assert s["records"] == 3
    assert s["hours"] == 8
    assert s["byKind"]["normal"]["hours"] == 4
    assert s["byKind"]["rest"]["hours"] == 4
    assert s["pay"] == 4 * H * 1.5 + 4 * H * 2.0
    assert s["taxable"] == 8 * H
    assert s["byDate"]["2026-06-10"] == 2


def test_an_empty_month_is_zero_not_an_error():
    s = ot.month_summary([], H)
    assert s["pay"] == 0 and s["hours"] == 0 and s["byKind"] == {}


# ── the caps (Art. 107) ──────────────────────────────────────────────────────────────────────────

def test_the_daily_cap_is_half_a_normal_day():
    assert ot.day_cap(8) == 4


def test_the_daily_cap_also_respects_the_twelve_hour_ceiling():
    """On a 10-hour normal day, half would be 5 — but normal + overtime may not pass 12."""
    assert ot.day_cap(10) == 2


def test_a_lawful_month_reports_no_breach():
    assert ot.cap_check(day_hours=3, month_hours=30, year_hours=150)["ok"] is True


def test_five_hours_in_one_day_breaks_the_daily_cap():
    r = ot.cap_check(day_hours=5)
    assert r["ok"] is False
    assert [b["cap"] for b in r["breaches"]] == ["day"]


def test_forty_one_hours_in_a_month_breaks_the_monthly_cap():
    r = ot.cap_check(month_hours=41)
    assert [b["cap"] for b in r["breaches"]] == ["month"]
    assert r["breaches"][0]["limit"] == 40


def test_the_annual_cap_is_two_hundred_unless_the_company_qualifies_for_three():
    assert ot.cap_check(year_hours=201)["ok"] is False
    assert ot.cap_check(year_hours=201, annual_cap=300)["ok"] is True
    assert ot.cap_check(year_hours=301, annual_cap=300)["ok"] is False


def test_exactly_on_the_limit_is_lawful():
    """"Not exceeding" 40 hours means 40 hours is allowed. An off-by-one here refuses a lawful
    approval on the last day of the month."""
    assert ot.cap_check(day_hours=4, month_hours=40, year_hours=200)["ok"] is True


def test_every_broken_cap_is_reported_not_just_the_first():
    r = ot.cap_check(day_hours=6, month_hours=45, year_hours=260)
    assert [b["cap"] for b in r["breaches"]] == ["day", "month", "year"]
