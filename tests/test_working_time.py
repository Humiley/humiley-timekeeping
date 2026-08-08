"""Working time and rest — the law the portal never checked.

overtime.py covers what happens beyond normal hours. These cover normal hours themselves and the
rest owed around them: Arts. 105, 106, 109, 110, 111 and Decree 145/2020 Arts. 63 and 64.

The tests that matter most are the ones locking down what must NOT be encoded. Three separate
plausible-sounding rules were checked and rejected during the research — a 40-hour legal maximum, a
60-hour overtime month, and a 6-hour day for hazardous work — and each of them would look right to
somebody reading a consultancy blog. If they ever get added back, these fail.
"""
import pytest

import working_time as wt


# ── Art. 105: the ceiling on normal hours ────────────────────────────────────────────────────────

def test_eight_hours_a_day_is_the_daily_reckoning_ceiling():
    assert wt.normal_hours_check(day_hours=8)["ok"] is True
    assert wt.normal_hours_check(day_hours=8.5)["ok"] is False


def test_weekly_reckoning_allows_ten_hours_in_a_day():
    """Art. 105(2): only if the employer elected weekly reckoning AND notified employees."""
    assert wt.normal_hours_check(day_hours=10, basis=wt.BASIS_WEEKLY)["ok"] is True
    assert wt.normal_hours_check(day_hours=10, basis=wt.BASIS_DAILY)["ok"] is False


def test_the_forty_eight_hour_week_binds_under_both_reckonings():
    for basis in (wt.BASIS_DAILY, wt.BASIS_WEEKLY):
        r = wt.normal_hours_check(day_hours=10, week_hours=50, basis=basis)
        assert any(b["code"] == wt.OVER_WEEK for b in r["breaches"]), basis


def test_a_ten_hour_day_inside_a_forty_eight_hour_week_is_lawful_on_weekly_reckoning():
    """10+10+10+10+8 is the pattern the article exists to permit."""
    assert wt.normal_hours_check(day_hours=10, week_hours=48, basis=wt.BASIS_WEEKLY)["ok"] is True


def test_both_limits_can_break_at_once_and_both_are_reported():
    r = wt.normal_hours_check(day_hours=12, week_hours=60)
    assert {b["code"] for b in r["breaches"]} == {wt.OVER_DAY, wt.OVER_WEEK}


def test_forty_hours_a_week_is_NEVER_treated_as_a_limit():
    """Art. 105(2)'s second paragraph is an encouragement. Coding it as a maximum would report a
    lawful company in breach every week of its life."""
    r = wt.normal_hours_check(day_hours=8, week_hours=44)
    assert r["ok"] is True
    assert "encouragement" in r["note"]


def test_a_missing_figure_is_not_a_breach():
    assert wt.normal_hours_check(day_hours=None, week_hours=None)["ok"] is True


# ── the limits are configurable, but only downwards ──────────────────────────────────────────────

def test_a_company_may_set_shorter_normal_hours_than_the_law():
    assert wt.limits(overrides={"weekHours": 40})["weekHours"] == 40


def test_a_company_may_NOT_raise_the_statutory_ceiling():
    """Otherwise a configuration field becomes a way of legalising a 60-hour week."""
    assert wt.limits(overrides={"weekHours": 60})["weekHours"] == 48.0
    assert wt.limits(overrides={"dayHoursDaily": 12})["dayHoursDaily"] == 8.0


def test_an_unreadable_override_is_ignored_rather_than_crashing_the_check():
    assert wt.limits(overrides={"weekHours": "lots", "nope": 1})["weekHours"] == 48.0


# ── Art. 106: the night window ───────────────────────────────────────────────────────────────────

def test_night_is_ten_at_night_to_six_in_the_morning():
    assert (wt.NIGHT_FROM_MIN, wt.NIGHT_TO_MIN) == (22 * 60, 6 * 60)


def test_there_is_one_night_window_not_a_northern_and_a_southern_one():
    """The 1994 Code's regional split was abolished in 2012. This module shares overtime.py's
    definition rather than keeping a second copy that could drift from it."""
    import overtime
    assert wt.NIGHT_FROM_MIN is overtime.NIGHT_FROM_MIN
    assert wt.night_minutes is overtime.night_minutes


# ── Art. 98(2): the premium a rostered night shift was never paid ────────────────────────────────

def test_a_night_shift_with_no_overtime_still_has_night_hours():
    """This is the gap. overtime.py only ever priced night hours inside the overtime tail, so a crew
    rostered 22:00–06:00 on a shutdown earned exactly what a day crew earned."""
    assert wt.normal_night_hours("22:00", "06:00") == 8.0


def test_the_overtime_tail_is_taken_off_the_end_so_it_is_not_paid_twice():
    """20:00–06:00 with 2h of overtime: normal time ends at 04:00, so 22:00–04:00 is six night hours
    of NORMAL time. The last two are already priced by overtime.py."""
    assert wt.normal_night_hours("20:00", "06:00", ot_hours=2) == 6.0


def test_a_day_shift_has_no_night_hours():
    assert wt.normal_night_hours("08:00", "17:00") == 0.0


def test_an_evening_shift_counts_only_the_part_after_ten():
    assert wt.normal_night_hours("18:00", "23:30") == 1.5


def test_unreadable_times_give_None_not_zero():
    """Zero would read as 'no night work'; None says 'this could not be worked out'."""
    assert wt.normal_night_hours("", "06:00") is None
    assert wt.normal_night_hours("22:00", None) is None


# ── Decree 145 Art. 63: shift work, and whether it is continuous ─────────────────────────────────

def test_one_crew_on_one_site_is_not_shift_work():
    """Art. 63(2) needs at least two people or groups taking turns at the SAME workstation. A
    ~30-person contractor running one crew per site is not doing shift work at all."""
    assert wt.is_shift_work(1) is False
    assert wt.is_shift_work(2) is True


def test_a_long_shift_by_one_crew_is_still_not_continuous_shift_work():
    """The most likely way to get this wrong: treat a ten-hour day as 'continuous' because it is
    long and unbroken. Art. 63(3) only ever applies to work that is shift work under Art. 63(2)
    first, and getting it wrong makes every break paid for a company that owes none."""
    r = wt.is_continuous_shift(shift_hours=10, handover_gap_min=0, people_at_workstation=1)
    assert r["continuous"] is False and r["reason"] == "not_shift_work"


def test_continuous_shift_needs_both_limbs():
    ok = dict(shift_hours=8, handover_gap_min=30, people_at_workstation=2)
    assert wt.is_continuous_shift(**ok)["continuous"] is True
    assert wt.is_continuous_shift(**dict(ok, shift_hours=5))["continuous"] is False
    assert wt.is_continuous_shift(**dict(ok, handover_gap_min=46))["continuous"] is False


def test_an_unrecorded_handover_gap_is_not_a_pass():
    """Defaulting it to zero would make every long shift continuous and every break paid — and that
    is the error you cannot take back, because it has already been paid."""
    r = wt.is_continuous_shift(shift_hours=8, handover_gap_min=None, people_at_workstation=2)
    assert r["continuous"] is False and r["reason"] == "handover_unknown"


def test_the_forty_five_minute_handover_is_not_the_twelve_hour_rest():
    """Different tests on different subjects: one on the roster, one on a person."""
    assert wt.limits()["continuousHandoverMaxMin"] == 45
    assert wt.limits()["shiftGapHours"] == 12.0


# ── Art. 109 + Decree 145 Art. 64: the mid-shift break ───────────────────────────────────────────

def test_six_hours_in_the_day_triggers_a_thirty_minute_break():
    assert wt.break_entitlement(6, 0)["minutes"] == 30
    assert wt.break_entitlement(5.9, 0)["required"] is False


def test_the_trigger_is_six_hours_in_the_DAY_not_six_continuous_hours():
    """English translations saying 'working continuously for 6 hours' are rendering the repealed
    2012 wording, and it changes who is entitled. The function takes the day's total."""
    assert wt.break_entitlement(worked_hours=6.5)["required"] is True


def test_three_night_hours_make_it_forty_five_minutes():
    assert wt.break_entitlement(8, 3)["minutes"] == 45
    assert wt.break_entitlement(8, 2.9)["minutes"] == 30


def test_one_or_two_night_hours_are_flagged_rather_than_silently_decided():
    """The Code grants 45 to somebody who 'works at night'; the Decree's test is 3 hours. Nothing
    was found resolving the gap, so the case is surfaced: 45 over-complies and is safe."""
    r = wt.break_entitlement(8, 1)
    assert r["minutes"] == 30 and r["overCompliance"] is True
    assert wt.break_entitlement(8, 0)["overCompliance"] is False
    assert wt.break_entitlement(8, 4)["overCompliance"] is False


def test_the_break_is_paid_ONLY_for_continuous_shift_work():
    """The widely repeated claim that all break time is paid reads Art. 109(1)'s third sentence as
    if 'theo ca liên tục' were not there."""
    assert wt.break_entitlement(8, 0, continuous_shift=True)["paid"] is True
    assert wt.break_entitlement(8, 0, continuous_shift=False)["paid"] is False


def test_the_unpaid_case_says_what_it_costs_the_employee_in_time():
    assert "only encourages" in wt.break_entitlement(8, 0, False)["why"]


def test_the_break_must_be_one_unbroken_block():
    r = wt.break_entitlement(8, 0)
    assert r["consecutive"] is True
    assert "15+15" in r["noSplit"]


def test_a_break_at_the_start_or_the_end_of_the_shift_is_refused():
    """Decree 145 Art. 64(3). Tacking it onto either end would cost the employer nothing."""
    assert wt.break_placement_ok("08:00", "17:00", "08:00", 30)["reason"] == "at_start"
    assert wt.break_placement_ok("08:00", "17:00", "16:30", 30)["reason"] == "at_end"
    assert wt.break_placement_ok("08:00", "17:00", "12:00", 30)["ok"] is True


def test_break_placement_handles_a_shift_through_midnight():
    assert wt.break_placement_ok("22:00", "06:00", "01:00", 45)["ok"] is True
    assert wt.break_placement_ok("22:00", "06:00", "22:00", 45)["reason"] == "at_start"


def test_unreadable_break_times_are_refused_not_passed():
    assert wt.break_placement_ok("08:00", "17:00", "noon", 30)["ok"] is False


# ── Art. 110: the rest between shifts ────────────────────────────────────────────────────────────

def test_twelve_hours_between_shifts():
    assert wt.shift_gap_check(wt.at(0, "22:00"), wt.at(1, "10:00"))["ok"] is True
    assert wt.shift_gap_check(wt.at(0, "22:00"), wt.at(1, "09:59"))["ok"] is False


def test_the_gap_is_measured_across_days_not_on_the_clock_face():
    """22:00 → 06:00 is eight hours, not sixteen. Comparing times of day would get this backwards."""
    r = wt.shift_gap_check(wt.at(0, "22:00"), wt.at(1, "06:00"))
    assert r["gapHours"] == 8.0 and r["ok"] is False


def test_a_full_day_off_between_shifts_passes():
    assert wt.shift_gap_check(wt.at(0, "17:00"), wt.at(2, "08:00"))["ok"] is True


def test_an_overlapping_pair_of_shifts_is_reported_as_such():
    assert wt.shift_gap_check(wt.at(1, "08:00"), wt.at(0, "22:00"))["code"] == "overlap"


def test_a_missing_time_is_None_not_a_pass():
    """An unchecked rest is not a compliant one — False would accuse, True would excuse."""
    assert wt.shift_gap_check(None, wt.at(1, "08:00"))["ok"] is None


# ── Art. 111: the weekly rest ────────────────────────────────────────────────────────────────────

def test_twenty_four_consecutive_hours_a_week():
    assert wt.weekly_rest_check([24])["ok"] is True
    assert wt.weekly_rest_check([23.5])["ok"] is False


def test_two_short_rests_do_not_add_up_to_a_weekly_rest():
    """Somebody who never had a day off would otherwise be reported as compliant."""
    assert wt.weekly_rest_check([12, 12, 12])["ok"] is False


def test_the_longest_block_is_what_counts_not_the_last_one():
    assert wt.weekly_rest_check([30, 8])["ok"] is True
    assert wt.weekly_rest_check([8, 30])["ok"] is True


def test_a_week_with_no_rest_at_all_is_a_breach_not_an_error():
    r = wt.weekly_rest_check([])
    assert r["ok"] is False and r["longestHours"] == 0.0


def test_the_weekly_rest_is_hours_not_a_calendar_day():
    """14:00 Saturday to 14:00 Sunday satisfies Art. 111(1)."""
    assert "CONSECUTIVE" in wt.weekly_rest_check([24])["why"]


def test_sunday_is_not_stated_as_a_default():
    assert "not a statutory default" in wt.weekly_rest_check([24])["restDay"]


def test_the_monthly_fallback_needs_four_days_and_says_it_is_a_reading():
    """The Code defines neither the 'day' nor the averaging window. Encoding one is unavoidable;
    describing it to a client as the law's own is not."""
    assert wt.monthly_rest_fallback(4)["ok"] is True
    assert wt.monthly_rest_fallback(3)["ok"] is False
    assert "a reading, not a quotation" in wt.monthly_rest_fallback(4)["caveat"]


# ── the review over real attendance rows ─────────────────────────────────────────────────────────

MON, TUE, WED = "2026-07-27", "2026-07-28", "2026-07-29"


def _r(date, cin, cout, **kw):
    return dict({"date": date, "clock_in": cin, "clock_out": cout}, **kw)


def test_an_ordinary_eight_to_five_day_is_NOT_reported_as_a_breach():
    """THE thing that would have made this screen useless. The portal records one check-in and one
    check-out, so 08:00–17:00 is nine hours ON SITE — eight of work and an unpaid hour of lunch.
    Measuring Art. 105 off the raw span would report every employee in breach every single day, and
    a compliance screen that cries wolf on 100% of rows teaches people to close it."""
    r = wt.review_rows([_r(MON, "08:00", "17:00")])
    assert r["days"][0]["state"] == wt.INDETERMINATE
    assert r["findings"] == []


def test_a_declared_break_makes_the_same_day_a_clean_pass():
    r = wt.review_rows([_r(MON, "08:00", "17:00")], break_minutes=60)
    assert r["days"][0]["normalHours"] == 8.0
    assert r["days"][0]["state"] == wt.OK and r["indeterminate"] is False


def test_a_day_no_break_could_explain_is_a_breach_even_with_nothing_declared():
    """Two hours of slack is generous for a meal. Sixteen hours on site is not a long lunch."""
    r = wt.review_rows([_r(MON, "06:00", "22:00")])
    assert r["days"][0]["state"] == wt.OVER_DAY
    assert r["findings"][0]["article"] == "Art. 105"


def test_the_uncertainty_is_stated_rather_than_hidden():
    assert "does not record" in wt.review_rows([_r(MON, "08:00", "17:00")])["breakNote"]
    assert "declared unpaid break of 60" in wt.review_rows([_r(MON, "08:00", "17:00")],
                                                           break_minutes=60)["breakNote"]


def test_a_paid_break_is_not_deducted_because_it_is_already_working_time():
    r = wt.review_rows([_r(MON, "08:00", "17:00")], break_minutes=60, continuous_shift=True)
    assert r["days"][0]["breakHours"] == 0.0


def test_approved_overtime_comes_off_before_the_article_105_test():
    """Art. 105 caps NORMAL hours. Lawful overtime on top is Art. 107's business."""
    r = wt.review_rows([_r(MON, "08:00", "20:00", ot_hours=3)], break_minutes=60)
    assert r["days"][0]["normalHours"] == 8.0 and r["days"][0]["state"] == wt.OK


def test_a_week_over_forty_eight_hours_is_found():
    rows = [_r("2026-07-%02d" % d, "08:00", "18:00") for d in range(27, 32)] + \
           [_r("2026-08-01", "08:00", "18:00"), _r("2026-08-02", "08:00", "18:00")]
    r = wt.review_rows(rows, break_minutes=60)
    assert any(f["code"] == wt.OVER_WEEK for f in r["findings"])


def test_a_week_built_from_unknown_breaks_is_not_asserted_to_be_over():
    """Six nine-hour spans total 54 hours on site, which looks like a breach of the 48-hour week —
    but it is exactly 48 once each day's unpaid hour of lunch comes off. Asserting the breach would
    be the same wolf-crying one level up, on the figure a labour inspector would be shown."""
    rows = [_r("2026-07-%02d" % d, "08:00", "17:00") for d in range(27, 32)] + \
           [_r("2026-08-01", "08:00", "17:00")]
    r = wt.review_rows(rows)
    assert r["weeks"][0]["normalHours"] == 54.0, "the raw span total"
    assert r["weeks"][0]["state"] == wt.INDETERMINATE
    assert not [f for f in r["findings"] if f["code"] == wt.OVER_WEEK]


def test_a_week_over_the_limit_by_more_than_any_break_IS_asserted():
    """Six fourteen-hour spans is 84 hours; even two hours of break a day leaves 72. There is no
    reading of that week that is inside Art. 105."""
    rows = [_r("2026-07-%02d" % d, "06:00", "20:00") for d in range(27, 32)] + \
           [_r("2026-08-01", "06:00", "20:00")]
    r = wt.review_rows(rows)
    assert r["weeks"][0]["state"] == wt.OVER_WEEK
    assert [f for f in r["findings"] if f["code"] == wt.OVER_WEEK]


def test_the_twelve_hour_rest_is_checked_between_consecutive_shifts():
    r = wt.review_rows([_r(MON, "14:00", "22:00"), _r(TUE, "06:00", "14:00")])
    short = [f for f in r["findings"] if f["article"] == "Art. 110"]
    assert short and short[0]["actual"] == 8.0


def test_a_night_shift_across_midnight_is_measured_forwards_not_backwards():
    """22:00 → 06:00 is eight hours. Without the overnight wrap it is minus sixteen, and every rest
    check after it is nonsense."""
    r = wt.review_rows([_r(MON, "22:00", "06:00")])
    assert r["days"][0]["elapsedHours"] == 8.0
    assert r["days"][0]["nightHours"] == 8.0


def test_a_week_with_no_twenty_four_hour_rest_is_found():
    rows = [_r("2026-07-%02d" % d, "08:00", "22:00") for d in range(27, 32)] + \
           [_r("2026-08-01", "08:00", "22:00"), _r("2026-08-02", "08:00", "22:00")]
    r = wt.review_rows(rows)
    assert any(f["article"] == "Art. 111(1)" for f in r["findings"])


def test_a_normal_week_with_the_weekend_off_has_its_weekly_rest():
    """Friday 17:00 to Monday 00:00 is well over 24 consecutive hours."""
    rows = [_r("2026-07-%02d" % d, "08:00", "17:00") for d in range(27, 32)]
    r = wt.review_rows(rows)
    assert not [f for f in r["findings"] if f["article"] == "Art. 111(1)"]
    assert r["weeklyRest"][0]["ok"] is True


def test_an_open_row_is_skipped_and_counted_not_treated_as_compliant():
    r = wt.review_rows([_r(MON, "08:00", None), _r(TUE, "08:00", "17:00")])
    assert r["openRows"] == 1 and len(r["days"]) == 1
    assert "not a compliant one" in r["coverage"]


def test_an_unreadable_row_is_counted_separately():
    r = wt.review_rows([_r(MON, "oops", "17:00")])
    assert r["unreadableRows"] == 1 and r["days"] == []


def test_no_rows_produces_no_findings_rather_than_an_error():
    r = wt.review_rows([])
    assert r["findings"] == [] and r["days"] == [] and r["weeks"] == []


def test_the_night_hours_are_totalled_for_the_period():
    r = wt.review_rows([_r(MON, "22:00", "06:00"), _r(WED, "22:00", "06:00")])
    assert r["nightHours"] == 16.0


# ── what must never be encoded ───────────────────────────────────────────────────────────────────

@pytest.mark.parametrize("phrase", [
    "40 hours a week is the legal maximum",
    "60 overtime hours a month",
    "6 hours a day for arduous or hazardous work, per the Labour Code",
    "The 30-minute break may be split into 15+15",
    "All break time is paid",
    "Night is 21:00–05:00 in the south",
])
def test_the_rejected_claims_are_recorded_with_the_reason_they_were_rejected(phrase):
    """Each of these looks right in a consultancy blog. Writing down why it is wrong is the only
    thing that stops it being added back by somebody who read one."""
    found = [r for r in wt.REJECTED if r["claim"] == phrase]
    assert found and len(found[0]["status"]) > 40


def test_no_six_hour_hazardous_day_appears_anywhere_in_the_limits():
    """2012 Code Art. 104(3), repealed. Citing the Labour Code for it in a pharma client's pack
    would be citing a provision that no longer exists."""
    assert 6.0 not in (wt.limits()["dayHoursDaily"], wt.limits()["dayHoursWeekly"])


def test_the_open_questions_are_carried_rather_than_guessed():
    topics = {u["topic"] for u in wt.UNRESOLVED}
    assert "Day type after midnight" in topics
    assert all(u["action"] for u in wt.UNRESOLVED)
