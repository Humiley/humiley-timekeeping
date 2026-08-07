"""Headcount and turnover over time.

The arithmetic here looks trivial and is not. Three near-misses were caught by running real dates
through it rather than by reasoning about it, and each one is a test below: a first-of-the-month
joiner counted twice, a month-end leaver carried into a month they had already left, and a person
who joined and left inside the same month.

The invariant everything rests on: **carriedForward = opening + joiners − leavers**, and one month's
carriedForward is the next month's opening. If that chain holds across a set of awkward dates, the
headcount history is right; if it does not, no amount of correct-looking totals rescues it.
"""
import workforce as wf


def _p(pid, start, end=None, dept="Engineering", status=None):
    r = {"id": pid, "name": pid, "startDate": start, "dept": dept}
    if end:
        r["endDate"] = end
    if status:
        r["status"] = status
    return r


# ── who counts, on which day ─────────────────────────────────────────────────────────────────────

def test_somebody_is_employed_on_their_last_working_day():
    """Counting them out on the 31st makes the month's closing headcount disagree with the payroll
    that paid them that month."""
    p = _p("A", "2026-01-01", "2026-08-31")
    assert wf.employed_on(p, "2026-08-31") is True
    assert wf.employed_on(p, "2026-09-01") is False


def test_somebody_is_employed_from_their_first_day_and_not_before():
    p = _p("A", "2026-08-10")
    assert wf.employed_on(p, "2026-08-09") is False
    assert wf.employed_on(p, "2026-08-10") is True


def test_an_inactive_record_with_no_end_date_is_treated_as_gone():
    """They left at some unknown time. Carrying them as present is the flattering error, which makes
    it the dangerous one — every historical headcount would be inflated."""
    assert wf.employed_on(_p("A", "2020-01-01", status="Inactive"), "2026-08-01") is False
    assert wf.employed_on(_p("A", "2020-01-01", status="Active"), "2026-08-01") is True


def test_a_record_with_no_start_date_is_reported_not_silently_dropped():
    bad = wf.unusable([{"id": "X", "name": "No Start"}, _p("A", "2026-01-01")])
    assert len(bad) == 1 and bad[0]["empId"] == "X"
    assert "cannot be placed" in bad[0]["why"]


def test_a_last_day_before_the_start_date_is_reported():
    bad = wf.unusable([_p("X", "2026-08-01", "2026-07-01")])
    assert len(bad) == 1 and "before their start date" in bad[0]["why"]


# ── the invariant ────────────────────────────────────────────────────────────────────────────────

AWKWARD = [
    _p("steady", "2020-01-01"),                          # here throughout
    _p("monthEndLeaver", "2025-06-01", "2026-08-31"),    # leaves ON a month end
    _p("firstDayJoiner", "2026-07-01"),                  # starts ON a month start
    _p("sameMonth", "2026-09-02", "2026-09-20"),         # joins and leaves inside one month
    _p("midMonthLeaver", "2026-01-05", "2026-10-14"),    # leaves mid-month
]


def test_the_chain_holds_across_every_awkward_date():
    """carriedForward = opening + joiners − leavers, and it becomes the next month's opening."""
    rows = wf.series(AWKWARD, "2026-06", "2026-12")
    assert rows
    prev = None
    for r in rows:
        assert r["balances"] is True, r
        assert r["carriedForward"] == r["opening"] + r["joiners"] - r["leavers"], r
        if prev is not None:
            assert r["opening"] == prev, "month %s did not open where %s closed" % (r["ym"], prev)
        prev = r["carriedForward"]


def test_a_first_of_the_month_joiner_is_not_also_counted_in_the_opening():
    """The first near-miss: counting the opening on the 1st puts them in both."""
    rows = {r["ym"]: r for r in wf.series([_p("A", "2026-07-01")], "2026-07", "2026-07")}
    assert rows["2026-07"]["opening"] == 0 and rows["2026-07"]["joiners"] == 1


def test_a_month_end_leaver_is_not_carried_into_the_next_month():
    """The second: taking the previous month's CLOSING as this month's opening would carry them in,
    because they are employed on the 31st."""
    rows = {r["ym"]: r for r in wf.series([_p("A", "2020-01-01", "2026-08-31")], "2026-08", "2026-09")}
    assert rows["2026-08"]["closing"] == 1, "on the payroll in August"
    assert rows["2026-08"]["carriedForward"] == 0
    assert rows["2026-09"]["opening"] == 0


def test_somebody_who_joins_and_leaves_in_one_month_appears_as_both_and_changes_nothing():
    rows = {r["ym"]: r for r in wf.series([_p("A", "2026-09-02", "2026-09-20")], "2026-09", "2026-09")}
    r = rows["2026-09"]
    assert r["joiners"] == 1 and r["leavers"] == 1
    assert r["opening"] == 0 and r["carriedForward"] == 0
    assert r["closing"] == 0, "they had already gone by the month end"


def test_the_names_are_carried_so_a_number_can_be_challenged():
    rows = {r["ym"]: r for r in wf.series([_p("Newbie", "2026-08-03")], "2026-08", "2026-08")}
    assert rows["2026-08"]["joinerNames"] == ["Newbie"]


# ── turnover ─────────────────────────────────────────────────────────────────────────────────────

def test_turnover_is_leavers_over_average_headcount_and_says_so():
    """On a small company the denominator moves the answer by half a point, so it is named."""
    s = wf.summary([_p("A", "2020-01-01"), _p("B", "2020-01-01"), _p("C", "2020-01-01", "2026-08-31")],
                   "2026-08", "2026-08")
    assert s["leavers"] == 1
    assert s["avgHeadcount"] == 3.0
    assert s["turnoverPct"] == 33.3
    assert "average headcount" in s["turnoverBasis"]


def test_the_period_rate_is_not_the_mean_of_the_monthly_rates():
    """Averaging percentages computed on different denominators is not a rate. Two leavers out of a
    ~2-person average across two months is 100%, not the mean of 0% and 200%."""
    people = [_p("A", "2020-01-01"), _p("B", "2020-01-01", "2026-09-30")]
    s = wf.summary(people, "2026-08", "2026-09")
    monthly = [r["turnoverPct"] for r in s["months"]]
    assert s["turnoverPct"] != round(sum(monthly) / len(monthly), 1)
    assert s["turnoverPct"] == 50.0


def test_nobody_employed_at_all_is_zero_rather_than_a_division_by_zero():
    s = wf.summary([], "2026-01", "2026-03")
    assert s["turnoverPct"] == 0.0 and s["headcountNow"] == 0 and s["months"]


# ── tenure and shape ─────────────────────────────────────────────────────────────────────────────

def test_tenure_is_the_median_not_the_mean():
    """One twenty-year founder drags a mean somewhere no actual employee sits."""
    people = [_p("founder", "2006-01-01"), _p("a", "2025-08-01"),
              _p("b", "2025-08-01"), _p("c", "2025-08-01")]
    s = wf.summary(people, "2026-08", "2026-08", as_of="2026-08-31")
    assert 11 < s["medianTenureMonths"] < 14, s["medianTenureMonths"]


def test_the_departments_are_counted_biggest_first():
    s = wf.summary([_p("a", "2020-01-01", dept="Factory"), _p("b", "2020-01-01", dept="Factory"),
                    _p("c", "2020-01-01", dept="Sales")], "2026-08", "2026-08")
    assert [d["dept"] for d in s["byDept"]] == ["Factory", "Sales"]
    assert s["byDept"][0]["headcount"] == 2


def test_a_backwards_or_nonsense_window_returns_nothing_rather_than_guessing():
    assert wf.months_between("2026-09", "2026-06") == []
    assert wf.months_between("banana", "2026-06") == []
    assert wf.month_end("2026-13") is None
    assert wf.month_row([], "nope") is None


def test_february_in_a_leap_year_is_twenty_nine_days():
    assert wf.month_end("2024-02").day == 29
    assert wf.month_end("2026-02").day == 28


def test_the_denominator_is_the_average_across_the_window_not_the_closing_headcount():
    """A single-month test cannot tell these apart — the average and the closing coincide. On a
    shrinking team they diverge, and dividing by the closing flatters or inflates the rate depending
    on which way the headcount moved. A mutation run proved the earlier test was blind to it."""
    people = [_p("a", "2020-01-01"), _p("b", "2020-01-01"), _p("c", "2020-01-01"),
              _p("d", "2020-01-01", "2026-07-31"), _p("e", "2020-01-01", "2026-08-31")]
    s = wf.summary(people, "2026-07", "2026-09")
    closing_last = s["months"][-1]["closing"]
    assert closing_last == 3
    assert s["leavers"] == 2
    assert s["avgHeadcount"] != float(closing_last), "the two denominators must actually differ here"
    assert s["turnoverPct"] == round(2 * 100.0 / s["avgHeadcount"], 1)
    assert s["turnoverPct"] != round(2 * 100.0 / closing_last, 1)


def test_the_balances_flag_can_actually_fail(monkeypatch):
    """`balances` is what the report shows when a month does not add up. Every other test asserts it
    is True, which a hardcoded True also satisfies — the same blind spot the labour-cost
    reconciliation had. So break the count on purpose and confirm the month reports itself as
    unbalanced rather than merely being wrong."""
    real = wf.headcount_at
    monkeypatch.setattr(wf, "headcount_at", lambda people, when: real(people, when) + 1)
    r = wf.month_row([_p("a", "2020-01-01")], "2026-08")
    assert r["balances"] is False
