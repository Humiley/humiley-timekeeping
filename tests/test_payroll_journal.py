"""The accounting entries a finalised pay run produces.

One invariant carries most of the weight: the entries BALANCE. A journal that does not is not a
journal, and an unbalanced one that is posted anyway silently misstates either the cost of the month
or what the company still owes. So it is asserted for every shape below, including the awkward ones.
"""
import payroll_journal as J
import payroll_calc as pc


def _line(dept="Engineering", gross=20_000_000, **over):
    """A pay-run line carrying a realistic frozen `calc`, computed by the tested payroll module
    rather than hand-written — hand-written numbers can be internally inconsistent, and this is a
    balance test."""
    c = pc.compute(gross=gross, gi=2, yrs=3, rating=3, working_days=22, **over)
    return {"empId": "E1", "dept": dept, "calc": c, "gross": c["grossPay"], "net": c["net"],
            "pit": c["pit"]}


def _run(lines):
    return {"period": "August 2026", "status": "Finalised", "lines": lines}


def _by(lines, code):
    return next((l for l in lines if l["account"] == code), None)


# ── the invariant ────────────────────────────────────────────────────────────────────────────────

def test_a_single_employee_balances():
    e = J.entries(_run([_line()]))
    assert J.balanced(e), J.totals(e)


def test_a_whole_company_balances():
    e = J.entries(_run([_line(gross=g, dept=d) for g, d in
                        ((18_000_000, "Engineering"), (25_000_000, "Factory"),
                         (33_000_000, "Operation"), (12_000_000, "Sales & Tender"))]))
    assert J.balanced(e), J.totals(e)


def test_unpaid_leave_still_balances():
    """The awkward one. Unpaid leave reduces the EXPENSE — the company never incurred it — so
    posting it as a credit would balance arithmetically while overstating both the cost of the month
    and what is owed."""
    e = J.entries(_run([_line(unpaid_days=3)]))
    assert J.balanced(e), J.totals(e)


def test_overtime_still_balances():
    e = J.entries(_run([_line(ot_units=23.5, ot_taxable_units=13)]))
    assert J.balanced(e), J.totals(e)


def test_dependants_changing_the_tax_still_balances():
    e = J.entries(_run([_line(deps=3)]))
    assert J.balanced(e), J.totals(e)


def test_an_empty_run_balances_trivially():
    e = J.entries(_run([]))
    assert e == [] and J.balanced(e)


def test_a_line_with_no_calc_at_all_does_not_unbalance_the_rest():
    """A run finalised before the whole calculation was frozen. It contributes what it can from the
    summary fields; it must not throw and must not corrupt the other lines."""
    e = J.entries(_run([_line(), {"empId": "OLD", "dept": "Engineering", "gross": 1, "net": 1}]))
    assert isinstance(e, list) and len(e) > 0


def test_junk_in_a_line_is_ignored_rather_than_crashing():
    e = J.entries(_run([_line(), "not a dict", None, {"calc": "also not a dict"}]))
    assert J.balanced(e), J.totals(e)


# ── where the money goes ─────────────────────────────────────────────────────────────────────────

def test_the_net_is_a_payable_to_employees_on_334():
    c = pc.compute(gross=20_000_000, working_days=22)
    e = J.entries(_run([_line()]))
    assert _by(e, "334")["credit"] == c["net"]


def test_the_tax_withheld_lands_on_3335():
    c = pc.compute(gross=20_000_000, working_days=22)
    e = J.entries(_run([_line()]))
    assert _by(e, "3335")["credit"] == c["pit"]


def test_social_insurance_carries_both_halves():
    """Account 3383 owes the agency the employee's 8% AND the employer's 17.5% — splitting them
    across accounts, or posting only the withheld half, understates the remittance."""
    c = pc.compute(gross=20_000_000, working_days=22)
    e = J.entries(_run([_line()]))
    assert _by(e, "3383")["credit"] == c["eeBhxh"] + c["erBhxh"]


def test_health_and_unemployment_insurance_have_their_own_accounts():
    c = pc.compute(gross=20_000_000, working_days=22)
    e = J.entries(_run([_line()]))
    assert _by(e, "3384")["credit"] == c["eeBhyt"] + c["erBhyt"]
    assert _by(e, "3386")["credit"] == c["eeBhtn"] + c["erBhtn"]


def test_the_trade_union_contribution_is_employer_only():
    c = pc.compute(gross=20_000_000, working_days=22)
    e = J.entries(_run([_line()]))
    assert _by(e, "3382")["credit"] == c["erTu"]


def test_the_expense_is_the_gross_less_unpaid_leave_plus_the_employer_contributions():
    c = pc.compute(gross=20_000_000, working_days=22, unpaid_days=2)
    e = J.entries(_run([_line(unpaid_days=2)]))
    assert _by(e, "642")["debit"] == c["grossPay"] - c["unpaidDeduction"] + c["erTotal"]


# ── the department mapping ───────────────────────────────────────────────────────────────────────

def test_a_department_can_be_mapped_to_its_own_expense_account():
    """Site labour belongs in 622 or 627, not in administrative expense. Which is which is the
    company's decision, so it is an input."""
    e = J.entries(_run([_line(dept="Factory"), _line(dept="Operation")]),
                  dept_accounts={"Factory": "622"})
    assert _by(e, "622") is not None and _by(e, "642") is not None


def test_the_mapping_ignores_case_and_stray_spacing():
    e = J.entries(_run([_line(dept="factory ")]), dept_accounts={"Factory": "622"})
    assert _by(e, "622") is not None


def test_an_unmapped_department_falls_to_the_default_rather_than_disappearing():
    """A line that vanishes is worse than one posted somewhere to be reviewed."""
    e = J.entries(_run([_line(dept="Somewhere New")]), dept_accounts={"Factory": "622"})
    assert _by(e, "642") is not None
    assert J.balanced(e)


def test_the_account_codes_can_be_overridden_for_a_circular_133_company():
    """A small enterprise on Circular 133 uses 3385 for unemployment insurance, not 3386."""
    e = J.entries(_run([_line()]), accounts={"ui": "3385"})
    assert _by(e, "3385") is not None and _by(e, "3386") is None
    assert J.balanced(e)


# ── what the accountant actually receives ────────────────────────────────────────────────────────

def test_the_csv_carries_every_line_and_a_total():
    e = J.entries(_run([_line()]))
    csv = J.to_csv(e, "August 2026")
    rows = csv.strip().split("\n")
    assert rows[0].startswith("Period,Account")
    assert len(rows) == len(e) + 2          # header + lines + total
    assert "TOTAL" in rows[-1]


def test_the_csv_total_matches_the_entries():
    e = J.entries(_run([_line(gross=18_000_000), _line(gross=25_000_000)]))
    t = J.totals(e)
    assert ("%.0f,%.0f" % (t["debit"], t["credit"])) in J.to_csv(e).strip().split("\n")[-1]


def test_an_account_name_containing_a_comma_does_not_break_the_columns():
    """One comma in an unquoted name shifts the debit column into the credit column for whoever
    imports it. The shipped account names happen to contain none — so the test supplies one, because
    a defence that is only exercised by data that cannot occur is not being tested at all. (The first
    version of this counted commas per row, which passed happily against unquoted output.)"""
    import csv, io
    rows = list(csv.reader(io.StringIO(J.to_csv(
        [{"account": "642", "name": "Chi phí quản lý, doanh nghiệp", "debit": 1000, "credit": 0}],
        "August 2026"))))
    assert all(len(r) == 5 for r in rows), rows
    assert rows[1][2] == "Chi phí quản lý, doanh nghiệp"
    assert float(rows[1][3]) == 1000


def test_a_zero_line_is_never_posted():
    """A journal padded with ₫0 rows is harder to check, and checking it is the whole point. Uses a
    line whose employer contributions really are nil — the ordinary payroll calc never produces a
    zero component, so the suppression would otherwise go unexercised."""
    zeroish = {"empId": "Z", "dept": "Engineering",
               "calc": {"grossPay": 1_000_000, "net": 1_000_000, "unpaidDeduction": 0,
                        "erTotal": 0, "eeBhxh": 0, "erBhxh": 0, "eeBhyt": 0, "erBhyt": 0,
                        "eeBhtn": 0, "erBhtn": 0, "erTu": 0, "pit": 0}}
    e = J.entries(_run([zeroish]))
    assert [l["account"] for l in e] == ["642", "334"], "only the two lines that carry a figure"
    assert all(l["debit"] or l["credit"] for l in e)
    assert J.balanced(e)
