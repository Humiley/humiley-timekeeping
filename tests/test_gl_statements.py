"""A balance sheet and an income statement, out of the same ledger rows.

The classic way to produce a statement that looks professional and is nonsense is to measure every
account over the same window. A balance-sheet account is CUMULATIVE — everything ever, up to the
date. A profit-and-loss account is a PERIOD. Undistributed profit is what reconciles them, and these
tests spend most of their time on that seam.
"""
import pytest

import gl


def _row(account, debit=0, credit=0, period="2026-06"):
    return {"account": account, "debit": debit, "credit": credit, "period": period, "name": ""}


# May: payroll. June: a claim and the cash for most of it.
PAYROLL_MAY = [
    _row("642", debit=123_500_000, period="2026-05"),
    _row("334", credit=89_500_000, period="2026-05"),
    _row("3383", credit=25_500_000, period="2026-05"),
    _row("3384", credit=4_500_000, period="2026-05"),
    _row("3386", credit=2_000_000, period="2026-05"),
    _row("3382", credit=2_000_000, period="2026-05"),
]
SALES_JUNE = [
    _row("131", debit=2_200_000_000),
    _row("511", credit=2_000_000_000),
    _row("3331", credit=200_000_000),
    _row("112", debit=1_760_000_000),
    _row("131", credit=1_760_000_000),
]
ALL = PAYROLL_MAY + SALES_JUNE


# --- the invariant ---------------------------------------------------------------------------------

def test_the_balance_sheet_balances_on_a_real_month():
    bs = gl.statements(ALL, "2026-06")["balanceSheet"]
    assert bs["assetsTotal"] == 2_200_000_000
    assert bs["liabilitiesTotal"] == 323_500_000
    assert bs["equityTotal"] == 1_876_500_000
    assert bs["fundedTotal"] == bs["assetsTotal"]
    assert bs["balanced"] and bs["difference"] == 0


def test_it_is_NOT_forced_to_balance_and_says_the_gap():
    """THE test. A statement that always balances by construction cannot tell you when your books
    are broken — which is the only time you need it to speak up. Here the ledger is genuinely out by
    a million, and the sheet has to carry that difference rather than absorb it into equity."""
    broken = ALL + [_row("112", debit=1_000_000)]      # cash arriving from nowhere
    bs = gl.statements(broken, "2026-06")["balanceSheet"]
    assert bs["balanced"] is False, "the balance sheet hid an unbalanced ledger"
    assert bs["difference"] == 1_000_000
    assert bs["assetsTotal"] - bs["fundedTotal"] == 1_000_000


def test_every_account_lands_on_exactly_one_side():
    st = gl.statements(ALL, "2026-06")
    bs = st["balanceSheet"]
    placed = ({r["account"] for r in bs["assets"]} | {r["account"] for r in bs["liabilities"]}
              | {r["account"] for r in bs["equity"]})
    # The P&L accounts are NOT on the sheet as themselves — they arrive as undistributed profit.
    assert "511" not in placed and "642" not in placed
    assert {"112", "131"} <= placed
    assert {"334", "3331", "3383"} <= placed


# --- cumulative vs periodic --------------------------------------------------------------------------

def test_balance_sheet_accounts_are_cumulative_and_the_pl_is_not():
    """June's sheet carries May's payroll liabilities — they are still owed. June's income
    statement does not carry May's payroll cost, because that was May's."""
    st = gl.statements(ALL, "2026-06")
    liab = {r["account"]: r["balance"] for r in st["balanceSheet"]["liabilities"]}
    assert liab["334"] == 89_500_000, "May's unpaid salary vanished from June's balance sheet"

    assert st["incomeStatement"]["period"]["expense"] == 0, "May's cost leaked into June"
    assert st["incomeStatement"]["yearToDate"]["expense"] == 123_500_000


def test_the_income_statement_reports_the_period_and_the_year_separately():
    st = gl.statements(ALL, "2026-06")
    assert st["incomeStatement"]["period"]["profit"] == 2_000_000_000
    assert st["incomeStatement"]["yearToDate"]["profit"] == 1_876_500_000


def test_asking_for_an_earlier_month_gives_that_months_position():
    """Not the latest one filtered — the position AS AT that date, which is what a comparative
    column means."""
    st = gl.statements(PAYROLL_MAY, "2026-05")
    bs = st["balanceSheet"]
    assert bs["assetsTotal"] == 0, "no cash or receivable existed in May"
    assert bs["liabilitiesTotal"] == 123_500_000
    assert bs["equityTotal"] == -123_500_000, "a month of cost with no revenue is a loss"
    assert bs["balanced"]


# --- undistributed profit -----------------------------------------------------------------------------

def test_a_prior_year_result_is_shown_apart_from_this_years():
    """A ledger that has never run a year-end close still carries last year's revenue and expense as
    open P&L balances. They belong in equity — but saying so separately is the point: 'we have never
    closed a year' is a fact the reader should see, not one rounded into a single number."""
    rows = [_row("511", credit=500_000_000, period="2025-11"),
            _row("131", debit=500_000_000, period="2025-11")] + ALL
    st = gl.statements(rows, "2026-06")
    assert st["retainedPriorYears"] == 500_000_000
    # Asserted on the NOTE, which is the sentence a reader sees, rather than on the label's casing —
    # a test that breaks when somebody capitalises a word is a test about nothing.
    notes = [r.get("note", "") for r in st["balanceSheet"]["equity"]]
    assert any("no year-end close has been run" in n for n in notes), notes
    assert any("fiscal year beginning" in n for n in notes), notes
    prior = [r for r in st["balanceSheet"]["equity"] if r["balance"] == 500_000_000]
    assert prior and prior[0]["account"] == gl.RETAINED
    # …and the sheet still balances with both in it.
    assert st["balanceSheet"]["balanced"]


def test_with_no_prior_years_there_is_no_prior_year_line():
    st = gl.statements(ALL, "2026-06")
    assert st["retainedPriorYears"] == 0
    assert not any("Prior years" in r["name"] for r in st["balanceSheet"]["equity"])


def test_undistributed_profit_is_marked_as_derived_not_as_a_posted_balance():
    """Nobody posted to 421. It is computed from the P&L rows, and a reader drilling into it would
    otherwise expect to find entries that do not exist."""
    st = gl.statements(ALL, "2026-06")
    derived = [r for r in st["balanceSheet"]["equity"] if r["account"] == gl.RETAINED]
    assert derived and all(r.get("derived") for r in derived)
    assert all(r["debit"] == 0 and r["credit"] == 0 for r in derived)


# --- the fiscal year ------------------------------------------------------------------------------------

def test_the_fiscal_year_defaults_to_the_calendar_year():
    assert gl.fiscal_year_start("2026-06") == "2026-01"
    assert gl.fiscal_year_start("2026-01") == "2026-01"
    assert gl.fiscal_year_start("2026-12") == "2026-01"


def test_a_company_reporting_to_a_foreign_parent_can_start_its_year_elsewhere():
    """April–March, for a subsidiary of a Japanese or Indian parent. Not guessed — passed in."""
    assert gl.fiscal_year_start("2026-06", 4) == "2026-04"
    assert gl.fiscal_year_start("2026-03", 4) == "2025-04", "March belongs to the year before"


def test_the_year_to_date_follows_the_fiscal_year_that_was_asked_for():
    rows = [_row("511", credit=100_000_000, period="2026-02"),
            _row("131", debit=100_000_000, period="2026-02"),
            _row("511", credit=300_000_000, period="2026-06"),
            _row("131", debit=300_000_000, period="2026-06")]
    calendar = gl.statements(rows, "2026-06")["incomeStatement"]["yearToDate"]["income"]
    april = gl.statements(rows, "2026-06", year_start_month=4)["incomeStatement"]["yearToDate"]["income"]
    assert calendar == 400_000_000, "January-start year should include February"
    assert april == 300_000_000, "April-start year must exclude February"


# --- edges ------------------------------------------------------------------------------------------------

def test_an_empty_ledger_produces_an_empty_sheet_that_balances():
    bs = gl.statements([], "2026-06")["balanceSheet"]
    assert bs["assetsTotal"] == 0 and bs["fundedTotal"] == 0 and bs["balanced"]


def test_a_result_account_belongs_to_neither_statement():
    """911 is the closing mechanism itself. Putting it on either statement would double-count the
    thing it exists to move."""
    rows = ALL + [_row("911", debit=1), _row("911", credit=1)]
    st = gl.statements(rows, "2026-06")
    on_sheet = ({r["account"] for r in st["balanceSheet"]["assets"]}
                | {r["account"] for r in st["balanceSheet"]["liabilities"]}
                | {r["account"] for r in st["balanceSheet"]["equity"]})
    assert "911" not in on_sheet
    assert st["balanceSheet"]["balanced"]


def test_a_credit_note_reduces_revenue_on_the_income_statement():
    rows = ALL + [_row("511", debit=50_000_000), _row("131", credit=50_000_000)]
    st = gl.statements(rows, "2026-06")
    assert st["incomeStatement"]["period"]["income"] == 1_950_000_000
    assert st["balanceSheet"]["balanced"]
