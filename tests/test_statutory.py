"""Statutory returns, and the contribution cap the portal has been getting wrong.

The point of these outputs is that a declaration must agree with the payslips it came from, so
everything is read out of a signed run rather than recomputed. The one place that is deliberately
NOT reconciled is the cap: BHXH/BHYT cap at 20x the base salary and BHTN at 20x the REGIONAL minimum
wage, and the portal applies the lower figure to all three. What was withheld has already been paid
to the authority, so this reports both and changes neither.
"""
import statutory as st


def _line(eid="E1", name="A", p1=20_000_000, p2=0, **calc):
    c = {"P1": p1, "P2": p2, "siBase": min(p1 + p2, 46_800_000)}
    base = c["siBase"]
    c.update({"eeBhxh": base * 0.08, "eeBhyt": base * 0.015, "eeBhtn": base * 0.01,
              "erBhxh": base * 0.175, "erBhyt": base * 0.03, "erBhtn": base * 0.01,
              "erTu": base * 0.02, "si": base * 0.105, "pit": 0, "grossPay": p1 + p2,
              "net": p1 + p2})
    c.update(calc)
    return {"empId": eid, "name": name, "dept": "Engineering", "calc": c}


# ── the caps ─────────────────────────────────────────────────────────────────────────────────────

DAY = "2025-01-01"          # inside Decree 73/2024 and Decree 74/2024, so the figures below hold


def test_the_two_caps_are_different_figures_and_both_come_from_the_day():
    assert st.si_hi_cap(on_date=DAY) == 46_800_000      # 20 x 2,340,000
    assert st.ui_cap("I", DAY) == 99_200_000            # 20 x 4,960,000
    assert st.ui_cap("IV", DAY) == 69_000_000           # 20 x 3,450,000
    assert st.si_hi_cap(base_salary=3_000_000) == 60_000_000, "a company figure still wins"


def test_somebody_under_both_caps_shows_no_variance_at_all():
    r = st.contributions(on_date=DAY, lines=[_line(p1=20_000_000)])
    assert r["variance"] == 0 and r["affected"] == []
    assert r["rows"][0]["capNote"] == ""


def test_somebody_between_the_caps_has_had_unemployment_insurance_under_withheld():
    """The finding. On a base of 60,000,000 the portal capped BHTN at 46,800,000; the law caps it at
    99,200,000 in Region I, so BHTN was due on the whole 60,000,000."""
    r = st.contributions(on_date=DAY, lines=[_line(p1=60_000_000)])
    row = r["rows"][0]
    assert row["baseSiHi"] == 46_800_000
    assert row["baseUi"] == 60_000_000
    assert row["withheld"]["eeBhtn"] == 468_000          # 1% of the wrong cap
    assert row["required"]["eeBhtn"] == 600_000          # 1% of the real base
    assert row["variance"] > 0
    assert "unemployment insurance" in row["capNote"]


def test_only_the_unemployment_fund_moves_the_rest_agree():
    """BHXH and BHYT were capped correctly, so the variance must come from BHTN alone — otherwise
    the report is accusing payroll of something it did not do."""
    r = st.contributions(on_date=DAY, lines=[_line(p1=60_000_000)])
    row = r["rows"][0]
    for k in ("eeBhxh", "eeBhyt", "erBhxh", "erBhyt", "union"):
        assert row["required"][k] == row["withheld"][k], k
    assert row["required"]["eeBhtn"] != row["withheld"]["eeBhtn"]
    assert row["required"]["erBhtn"] != row["withheld"]["erBhtn"]


def test_somebody_above_both_caps_is_capped_on_both_and_says_so():
    r = st.contributions(on_date=DAY, lines=[_line(p1=120_000_000)])
    row = r["rows"][0]
    assert row["baseSiHi"] == 46_800_000 and row["baseUi"] == 99_200_000
    assert "above both caps" in row["capNote"]


def test_the_region_changes_the_unemployment_cap():
    reg1 = st.contributions(on_date=DAY, lines=[_line(p1=80_000_000)], region="I")
    reg4 = st.contributions(on_date=DAY, lines=[_line(p1=80_000_000)], region="IV")
    assert reg1["rows"][0]["baseUi"] == 80_000_000, "under the Region I cap"
    assert reg4["rows"][0]["baseUi"] == 69_000_000, "capped in Region IV"


def test_what_was_withheld_is_reported_untouched():
    """Already paid to the authority. This module reports; it does not rewrite a filed number."""
    r = st.contributions(on_date=DAY, lines=[_line(p1=60_000_000)])
    assert r["totals"]["eeBhtn"] == 468_000, "the withheld total is what payroll actually took"


def test_the_legal_basis_of_each_cap_comes_back_with_the_numbers():
    r = st.contributions(on_date=DAY, lines=[_line()], region="I")
    assert "BHXH and BHYT" in r["capBasis"] and "BHTN" in r["capBasis"]
    assert "Region I" in r["capBasis"]


def test_the_totals_add_up_across_a_mixed_payroll():
    lines = [_line("E1", "A", 20_000_000), _line("E2", "B", 60_000_000),
             _line("E3", "C", 8_000_000)]
    r = st.contributions(lines)
    assert r["totals"]["employee"] == sum(x["withheld"]["eeBhxh"] + x["withheld"]["eeBhyt"] +
                                          x["withheld"]["eeBhtn"] for x in r["rows"])
    assert r["totals"]["employer"] == sum(x["withheld"]["erBhxh"] + x["withheld"]["erBhyt"] +
                                          x["withheld"]["erBhtn"] for x in r["rows"])
    assert len(r["affected"]) == 1 and r["affected"][0]["empId"] == "E2"


def test_the_worst_variance_is_listed_first_so_it_is_not_buried():
    lines = [_line("small", "small", 20_000_000), _line("big", "big", 90_000_000)]
    r = st.contributions(lines)
    assert r["rows"][0]["empId"] == "big"


def test_an_empty_run_produces_an_empty_return_rather_than_failing():
    r = st.contributions(on_date=DAY, lines=[])
    assert r["rows"] == [] and r["variance"] == 0 and r["totals"]["employee"] == 0


# ── PIT ──────────────────────────────────────────────────────────────────────────────────────────

def test_the_pit_schedule_totals_what_was_withheld():
    lines = [_line("E1", "A", pit=1_500_000), _line("E2", "B", pit=0)]
    p = st.pit_summary(lines)
    assert p["total"] == 1_500_000 and p["people"] == 2 and p["taxed"] == 1


def test_nil_pit_is_explained_rather_than_looking_like_a_gap():
    p = st.pit_summary([_line(pit=0)])
    assert "below the personal and dependant deductions" in p["note"]


# ── labour usage report ──────────────────────────────────────────────────────────────────────────

def _emp(eid, start, end=None, gender="Male", etype="Full Time", dept="Engineering"):
    e = {"id": eid, "name": eid, "startDate": start, "gender": gender,
         "employmentType": etype, "dept": dept}
    if end:
        e["endDate"] = end
    return e


def test_the_headcount_is_taken_at_the_reporting_date_not_today():
    """Re-running last June's return has to reproduce last June's return."""
    people = [_emp("a", "2020-01-01"), _emp("b", "2026-08-01")]
    r = st.labour_report(people, "2026-06-01")
    assert r["total"] == 1, "b had not joined by the reporting date"


def test_the_return_carries_the_split_the_form_asks_for():
    people = [_emp("a", "2020-01-01", gender="Female"),
              _emp("b", "2020-01-01", gender="Male", etype="Part Time"),
              _emp("c", "2020-01-01", gender="Female", dept="Factory")]
    r = st.labour_report(people, "2026-06-01")
    assert r["total"] == 3 and r["female"] == 2 and r["male"] == 1
    assert {x["type"] for x in r["byType"]} == {"Full Time", "Part Time"}
    assert r["byDept"][0]["count"] == 2


def test_a_leaver_is_out_of_the_return_from_the_day_after_their_last_day():
    people = [_emp("a", "2020-01-01", end="2026-05-31")]
    assert st.labour_report(people, "2026-05-31")["total"] == 1
    assert st.labour_report(people, "2026-06-01")["total"] == 0


def test_somebody_who_cannot_be_placed_in_time_is_reported_not_silently_omitted():
    r = st.labour_report([_emp("x", None)], "2026-06-01")
    assert r["total"] == 0 and r["unusable"] and "No start date" in r["unusable"][0]["why"]


def test_the_filing_deadlines_are_stated_on_the_return():
    r = st.labour_report([], "2026-06-01")
    assert "5 June" in r["basis"] and "5 December" in r["basis"]
    assert "Art. 4" in r["basis"]


# ── the caps are effective-dated, and neither is a constant ──────────────────────────────────────

def test_a_return_is_capped_by_the_decree_in_force_for_ITS_period():
    """The base salary sat here as one literal used as a default argument, evaluated at import. A
    June 2024 return was therefore measured against the figure that took effect in July."""
    assert st.si_hi_cap(on_date="2024-06-30") == 36_000_000     # 20 x 1,800,000, Decree 24/2023
    assert st.si_hi_cap(on_date="2024-07-01") == 46_800_000     # 20 x 2,340,000, Decree 73/2024


def test_every_recorded_decree_is_reachable_and_says_which_one_it_is():
    for frm, decree, amount in st.BASE_SALARY_SCHEDULE:
        b = st.base_salary_at(frm)
        assert b["amount"] == amount and b["decree"] == decree
        assert b["inForceFrom"] == frm
        assert decree in b["basis"] and "mức lương cơ sở" in b["basis"]


def test_the_day_before_a_decree_gets_the_one_it_replaced():
    ordered = sorted(st.BASE_SALARY_SCHEDULE)
    for i in range(1, len(ordered)):
        frm = ordered[i][0]
        import datetime
        prev_day = (datetime.date.fromisoformat(frm) - datetime.timedelta(days=1)).isoformat()
        assert st.base_salary_at(prev_day)["amount"] == ordered[i - 1][2]


def test_a_day_before_every_recorded_decree_is_refused_rather_than_guessed():
    assert st.base_salary_at("2010-01-01") is None
    assert st.si_hi_cap(on_date="2010-01-01") is None


def test_no_day_at_all_gives_no_cap_and_never_the_newest_figure():
    """A pure module has no clock, and inventing one is how a 2025 payslip gets measured by a 2026
    decree. A cap computed from nothing is indistinguishable on screen from one somebody chose."""
    assert st.si_hi_cap() is None
    assert st.ui_cap("I") is None
    assert st.base_salary_at("") is None and st.base_salary_at(None) is None


def test_a_company_figure_still_wins_over_the_decree():
    """A company told a different figure by its social insurance office uses it — this module is
    not the authority on that."""
    assert st.si_hi_cap(base_salary=3_000_000, on_date="2024-06-30") == 60_000_000
    assert st.ui_cap("I", "2024-06-30", region_min=6_000_000) == 120_000_000


# ── the second copy that went stale ──────────────────────────────────────────────────────────────

def test_the_unemployment_cap_is_read_from_the_module_that_owns_the_minimum_wage():
    """This file kept its OWN copy of the regional minimum wage. It went stale exactly as a copy
    does: min_wage carried Decree 293/2025 from 1 January 2026 (Region I ₫5,310,000) while this
    file still said ₫4,960,000, so every 2026 return capped BHTN at ₫99,200,000 instead of
    ₫106,200,000 — confidently, with nothing to notice it."""
    import min_wage
    assert not hasattr(st, "REGION_MIN_WAGE"), "the second copy is back"
    for region in min_wage.REGIONS:
        for day in ("2025-01-01", "2026-09-01"):
            floor = min_wage.at(region, day)
            assert st.ui_cap(region, day) == st.CAP_MULTIPLE * floor["monthly"], (region, day)


def test_the_2026_unemployment_cap_is_the_one_the_2026_decree_sets():
    assert st.ui_cap("I", "2026-09-01") == 106_200_000
    assert st.ui_cap("I", "2025-12-31") == 99_200_000


def test_an_unknown_region_is_refused_rather_than_defaulted():
    """Defaulting would put a whole workforce against the cheapest or the dearest floor."""
    assert st.ui_cap("IX", "2025-01-01") is None


# ── what the return says about its own basis ─────────────────────────────────────────────────────

def test_the_return_names_the_decree_behind_each_cap():
    """A cap on a filed return with no decree beside it is a number nobody can check a year later."""
    r = st.contributions(on_date=DAY, lines=[_line(p1=20_000_000)], region="I")
    assert r["baseSalary"] == 2_340_000
    assert "Decree 73/2024" in r["baseSalaryBasis"]
    assert r["regionMinWage"] == 4_960_000
    assert "Decree 74/2024" in r["regionMinWageBasis"]
    assert r["onDate"] == DAY
    assert "2,340,000" in r["capBasis"] and "4,960,000" in r["capBasis"]


def test_a_company_supplied_figure_says_it_came_from_the_company():
    r = st.contributions(on_date=DAY, lines=[_line(p1=20_000_000)], base_salary=3_000_000)
    assert r["baseSalary"] == 3_000_000
    assert r["baseSalaryBasis"] == "supplied by the company"


def test_an_unresolvable_cap_is_named_and_not_left_to_be_inferred_from_a_null():
    """An uncapped contribution is not the same fact as one capped at a chosen figure, and on a
    filed return the difference is money."""
    r = st.contributions(lines=[_line(p1=200_000_000)])
    assert r["capSiHi"] is None and r["capUi"] is None
    assert len(r["notes"]) >= 2
    assert any("UNCAPPED" in n for n in r["notes"])
    assert any("not a filing figure" in n for n in r["notes"])
    assert "not established" in r["capBasis"]


def test_the_notes_list_is_present_even_when_there_is_nothing_to_say():
    """A caller that forgets to render it renders an empty list, not a hidden refusal."""
    r = st.contributions(on_date=DAY, lines=[_line(p1=20_000_000)])
    assert r["notes"] == []


# ── the change this module declines to encode ────────────────────────────────────────────────────

def test_a_period_from_july_2025_carries_the_reference_level_caveat():
    """The Social Insurance Law 2024 moves the BHXH/BHYT ceiling off the base salary and onto a
    reference level. Encoding a figure nobody here has verified would move real money on a filed
    return — the same reason min_wage declines to assert the 7% vocational uplift as law."""
    r = st.contributions(on_date="2025-07-01", lines=[_line(p1=20_000_000)])
    assert any("mức tham chiếu" in n for n in r["notes"])
    assert any("your accountant" in n for n in r["notes"])


def test_a_period_before_it_does_not():
    r = st.contributions(on_date="2025-06-30", lines=[_line(p1=20_000_000)])
    assert not any("tham chiếu" in n for n in r["notes"])


def test_the_schedule_is_sorted_and_not_merely_written_in_the_right_order():
    """A mutation run caught this: the table happens to be newest-first, so reading it in FILE
    order gave the same answers and the sort was never exercised. The next person to add a decree
    will append it at the bottom, which is the natural instinct and the wrong order."""
    import random
    orig = st.BASE_SALARY_SCHEDULE
    try:
        shuffled = list(orig)
        random.Random(7).shuffle(shuffled)
        st.BASE_SALARY_SCHEDULE = tuple(shuffled)
        assert st.base_salary_at("2024-07-01")["amount"] == 2_340_000
        assert st.base_salary_at("2024-06-30")["amount"] == 1_800_000
        assert st.base_salary_at("2020-01-01")["amount"] == 1_490_000
    finally:
        st.BASE_SALARY_SCHEDULE = orig
    assert st.BASE_SALARY_SCHEDULE is orig


def test_a_new_decree_appended_at_the_bottom_still_governs_its_own_period():
    orig = st.BASE_SALARY_SCHEDULE
    try:
        st.BASE_SALARY_SCHEDULE = orig + (("2027-07-01", "A future decree", 2_700_000),)
        assert st.base_salary_at("2027-07-01")["amount"] == 2_700_000
        assert st.base_salary_at("2027-06-30")["amount"] == 2_340_000
    finally:
        st.BASE_SALARY_SCHEDULE = orig


# ── the return is dated by its own period ────────────────────────────────────────────────────────

def test_the_endpoint_dates_the_return_by_the_period_and_never_by_today():
    """A return refiled next year must produce the same figures. Dated by the day somebody pressed
    the button, a 2025 return recomputed in 2027 would be capped by a 2027 decree — the same
    failure the module-level constant caused, moved to the caller."""
    import io as _io
    src = _io.open("app.py", encoding="utf-8").read()
    i = src.index("contrib = statutory.contributions(")
    body = src[i - 1400:i + 300]
    assert 'on_date = ym + "-01"' in body, "the period does not decide the decree"
    assert "on_date=on_date" in body
    assert "_now_iso()" not in body.split('on_date =')[1][:200], \
        "the return is dated by the clock, not by the month it declares"


def test_the_endpoint_no_longer_falls_back_to_a_module_constant():
    import io as _io
    src = _io.open("app.py", encoding="utf-8").read()
    assert "statutory.BASE_SALARY" not in src, "the constant is back"
    i = src.index('db.get_setting("portal_baseSalary"')
    assert "or 0) or None" in src[i:i + 120], \
        "an unset company figure must be None so the decree decides, not 0"
