"""What each day was — and the only honest way to count an absence.

Every absence figure in this portal counted attendance rows with status 'absent'. No production
path has ever written that value, so every one of them was structurally zero: not "nobody was
absent" but "this number cannot be anything else". An absence is the ABSENCE of a record, so it has
to be derived from the days the company expected somebody to work.

The tests that matter here are the ones that stop the new number being wrong in the OTHER direction
— reporting somebody absent on their own rest day, on a public holiday, or while on approved leave.
"""
import attendance_days as ad

MON = "2026-08-03"   # Monday
TUE = "2026-08-04"
WED = "2026-08-05"
SAT = "2026-08-08"
SUN = "2026-08-09"
EMP = {"id": "E1", "name": "Nguyễn Văn A", "dept": "Engineering"}


def _row(date, cin="08:00", cout="17:00", status="on-time", **kw):
    return dict({"date": date, "clock_in": cin, "clock_out": cout, "status": status,
                 "hrs": "9h 00m"}, **kw)


def _sheet(rows=(), frm=MON, to=WED, **kw):
    return ad.timesheet(EMP, list(rows), frm, to, **kw)


# ── the window ───────────────────────────────────────────────────────────────────────────────────

def test_the_window_is_inclusive_at_both_ends():
    assert len(ad.days_between(MON, WED)) == 3


def test_a_backwards_or_unusable_window_is_empty_rather_than_a_guess():
    for a, b in ((WED, MON), ("", MON), (MON, "oops"), (None, None)):
        assert ad.days_between(a, b) == [], (a, b)


# ── a record beats every explanation ─────────────────────────────────────────────────────────────

def test_a_day_with_a_record_is_worked():
    s = _sheet([_row(MON)], frm=MON, to=MON)
    assert s["counts"][ad.WORKED] == 1 and s["worked"] == 1


def test_a_late_record_is_still_a_day_worked():
    s = _sheet([_row(MON, status="late")], frm=MON, to=MON)
    assert s["counts"][ad.LATE] == 1
    assert s["worked"] == 1, "late is how they arrived, not whether they came"


def test_working_ON_a_public_holiday_is_recorded_as_worked_not_as_a_holiday():
    """Saying 'holiday' because the calendar says so would erase a day owed 300% under Art. 98."""
    s = _sheet([_row(MON)], frm=MON, to=MON, holidays=[MON])
    assert s["counts"][ad.WORKED] == 1 and s["counts"][ad.HOLIDAY] == 0


def test_working_on_a_rest_day_is_recorded_as_worked():
    s = ad.timesheet(EMP, [_row(SUN)], SUN, SUN, rest_weekdays=(5, 6))
    assert s["counts"][ad.WORKED] == 1 and s["counts"][ad.REST] == 0


# ── absent is the LAST resort ────────────────────────────────────────────────────────────────────

def test_a_working_day_with_no_record_and_no_explanation_is_absent():
    s = _sheet([], frm=MON, to=MON)
    assert s["counts"][ad.ABSENT] == 1


def test_a_rest_day_is_never_an_absence():
    """Reporting somebody absent on their own Sunday is the kind of number that reaches an
    appraisal. It has to be impossible, not merely unlikely."""
    s = ad.timesheet(EMP, [], SAT, SUN, rest_weekdays=(5, 6))
    assert s["counts"][ad.ABSENT] == 0 and s["counts"][ad.REST] == 2


def test_a_public_holiday_is_never_an_absence():
    s = _sheet([], frm=MON, to=MON, holidays=[MON])
    assert s["counts"][ad.ABSENT] == 0 and s["counts"][ad.HOLIDAY] == 1


def test_approved_leave_is_never_an_absence():
    s = _sheet([], frm=MON, to=WED,
               leave_rows=[{"start": MON, "end": WED, "status": "approved"}])
    assert s["counts"][ad.ABSENT] == 0 and s["counts"][ad.LEAVE] == 3


def test_a_PENDING_leave_request_does_not_excuse_an_absence():
    """A request nobody has answered is a question, not an explanation. Treating it as one would
    let an absence be excused by asking."""
    s = _sheet([], frm=MON, to=MON,
               leave_rows=[{"start": MON, "end": MON, "status": "pending"}])
    assert s["counts"][ad.ABSENT] == 1 and s["counts"][ad.LEAVE] == 0


def test_a_rejected_leave_request_does_not_excuse_one_either():
    s = _sheet([], frm=MON, to=MON,
               leave_rows=[{"start": MON, "end": MON, "status": "rejected"}])
    assert s["counts"][ad.ABSENT] == 1


def test_leave_dates_reads_the_field_names_this_codebase_actually_uses():
    for a, b in (("start", "end"), ("from", "to"), ("startDate", "endDate")):
        got = ad.leave_dates([{a: MON, b: TUE, "status": "approved"}])
        assert got == {MON, TUE}, (a, b)


def test_a_single_day_leave_with_no_end_date_still_covers_that_day():
    assert ad.leave_dates([{"start": MON, "status": "approved"}]) == {MON}


def test_a_backwards_leave_range_is_read_the_way_it_was_meant():
    assert ad.leave_dates([{"start": WED, "end": MON, "status": "approved"}]) == {MON, TUE, WED}


# ── the timesheet, which is also the Decree 145 record ───────────────────────────────────────────

def test_it_carries_the_times_hours_overtime_and_place_for_every_day():
    s = _sheet([_row(MON, ot_hours=2, ot_status="approved", loc="Site A", project="P1")],
               frm=MON, to=MON)
    d = s["days"][0]
    assert (d["clockIn"], d["clockOut"], d["hrs"]) == ("08:00", "17:00", "9h 00m")
    assert d["otHours"] == 2 and d["otStatus"] == "approved"
    assert d["location"] == "Site A" and d["project"] == "P1"


def test_an_open_row_is_flagged_and_is_not_yet_a_worked_day_total():
    """It is also the shape a forgotten check-out leaves behind."""
    s = _sheet([_row(MON, cout=None)], frm=MON, to=MON)
    assert s["days"][0]["open"] is True
    assert s["openRows"] == 1


def test_expected_days_are_the_ones_the_company_asked_for():
    """Rest days and holidays are not 'expected' — dividing by them would understate attendance."""
    s = ad.timesheet(EMP, [_row(MON)], MON, SUN, rest_weekdays=(5, 6), holidays=[TUE])
    assert s["expected"] == 1 + s["counts"][ad.ABSENT]
    assert s["counts"][ad.REST] == 2 and s["counts"][ad.HOLIDAY] == 1


def test_the_statement_names_the_absence_against_what_was_expected():
    s = ad.timesheet(EMP, [_row(MON)], MON, WED, rest_weekdays=())
    assert "1 day(s) worked" in s["statement"]
    assert "2 absent with no explanation" in s["statement"]
    assert "2 of 3 expected working day(s)" in s["statement"]


def test_a_clean_period_says_nothing_alarming():
    s = ad.timesheet(EMP, [_row(MON), _row(TUE), _row(WED)], MON, WED)
    assert s["statement"] == "3 day(s) worked."


# ── a day that has not happened is not an absence ────────────────────────────────────────────────

def test_days_after_today_are_left_out_of_the_record():
    """Asking for the whole of August on the 5th used to report the rest of the month as absence —
    23 accusations for a month nobody has worked yet."""
    s = ad.timesheet(EMP, [], MON, SUN, rest_weekdays=(), today=TUE)
    assert [d["date"] for d in s["days"]] == [MON, TUE]
    assert s["counts"][ad.ABSENT] == 2


def test_the_record_says_what_it_actually_covers():
    s = ad.timesheet(EMP, [], MON, SUN, rest_weekdays=(), today=TUE)
    assert s["covers"] == MON + " → " + TUE
    assert s["to"] == SUN, "what was asked for is still reported, so the gap is visible"


def test_a_record_dated_in_the_future_is_kept_rather_than_hidden():
    """A row is evidence. Dropping it because the date looks wrong would conceal it."""
    s = ad.timesheet(EMP, [_row(SUN)], MON, SUN, rest_weekdays=(), today=TUE)
    assert [d["date"] for d in s["days"]] == [MON, TUE, SUN]
    assert s["counts"][ad.WORKED] == 1


def test_with_no_today_given_nothing_is_truncated():
    """The pure function must not invent a clock — the caller owns the company's time zone."""
    assert len(ad.timesheet(EMP, [], MON, SUN, rest_weekdays=())["days"]) == 7


# ── the company view ─────────────────────────────────────────────────────────────────────────────

def test_the_review_totals_across_people_and_names_who_was_absent():
    a = ad.timesheet({"id": "A", "name": "A"}, [], MON, WED, rest_weekdays=())
    b = ad.timesheet({"id": "B", "name": "B"}, [_row(MON)], MON, WED, rest_weekdays=())
    r = ad.review([a, b])
    assert r["absentDays"] == 5
    assert [p["empId"] for p in r["absentPeople"]] == ["A", "B"]
    assert r["absentPeople"][0]["days"] == 3


def test_nobody_absent_leaves_the_list_empty_rather_than_zeroed_rows():
    r = ad.review([ad.timesheet(EMP, [_row(MON)], MON, MON)])
    assert r["absentDays"] == 0 and r["absentPeople"] == []


def test_the_review_explains_where_the_number_comes_from_in_both_languages():
    r = ad.review([])
    assert "derived from the register, not stored on it" in r["basis"]
    assert r["basisVn"] and any(ord(c) > 127 for c in r["basisVn"])
