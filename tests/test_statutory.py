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

def test_the_two_caps_are_different_figures_and_both_are_computed_not_hardcoded():
    assert st.si_hi_cap() == 46_800_000                 # 20 x 2,340,000
    assert st.ui_cap("I") == 99_200_000                 # 20 x 4,960,000
    assert st.ui_cap("IV") == 69_000_000                # 20 x 3,450,000
    assert st.si_hi_cap(base_salary=3_000_000) == 60_000_000, "a decree revision is a parameter"


def test_somebody_under_both_caps_shows_no_variance_at_all():
    r = st.contributions([_line(p1=20_000_000)])
    assert r["variance"] == 0 and r["affected"] == []
    assert r["rows"][0]["capNote"] == ""


def test_somebody_between_the_caps_has_had_unemployment_insurance_under_withheld():
    """The finding. On a base of 60,000,000 the portal capped BHTN at 46,800,000; the law caps it at
    99,200,000 in Region I, so BHTN was due on the whole 60,000,000."""
    r = st.contributions([_line(p1=60_000_000)])
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
    r = st.contributions([_line(p1=60_000_000)])
    row = r["rows"][0]
    for k in ("eeBhxh", "eeBhyt", "erBhxh", "erBhyt", "union"):
        assert row["required"][k] == row["withheld"][k], k
    assert row["required"]["eeBhtn"] != row["withheld"]["eeBhtn"]
    assert row["required"]["erBhtn"] != row["withheld"]["erBhtn"]


def test_somebody_above_both_caps_is_capped_on_both_and_says_so():
    r = st.contributions([_line(p1=120_000_000)])
    row = r["rows"][0]
    assert row["baseSiHi"] == 46_800_000 and row["baseUi"] == 99_200_000
    assert "above both caps" in row["capNote"]


def test_the_region_changes_the_unemployment_cap():
    reg1 = st.contributions([_line(p1=80_000_000)], region="I")
    reg4 = st.contributions([_line(p1=80_000_000)], region="IV")
    assert reg1["rows"][0]["baseUi"] == 80_000_000, "under the Region I cap"
    assert reg4["rows"][0]["baseUi"] == 69_000_000, "capped in Region IV"


def test_what_was_withheld_is_reported_untouched():
    """Already paid to the authority. This module reports; it does not rewrite a filed number."""
    r = st.contributions([_line(p1=60_000_000)])
    assert r["totals"]["eeBhtn"] == 468_000, "the withheld total is what payroll actually took"


def test_the_legal_basis_of_each_cap_comes_back_with_the_numbers():
    r = st.contributions([_line()], region="I")
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
    r = st.contributions([])
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
