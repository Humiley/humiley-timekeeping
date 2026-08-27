"""The arithmetic a ledger is not allowed to get wrong.

These are pure — no database, no HTTP — because the rules have to be exhaustible. What a ledger
does is small; what it must never do is the long list, and every entry on that list here is a thing
that would produce a WRONG SET OF BOOKS rather than an error message.
"""
import pytest

import gl


PAYROLL = [{"account": "642", "name": "Admin expense", "debit": 100_000_000},
           {"account": "334", "name": "Payable to employees", "credit": 80_000_000},
           {"account": "3383", "name": "Social insurance", "credit": 20_000_000}]


# --- classification ------------------------------------------------------------------------------

def test_the_first_digit_decides_what_an_account_is():
    """Circular 200 numbers by class, so a company can invent 6421 or 33311 and it classifies
    correctly without anybody maintaining a list of every sub-account they will ever open."""
    assert gl.account_class("111")[0] == gl.ASSET
    assert gl.account_class("334")[0] == gl.LIABILITY
    assert gl.account_class("411")[0] == gl.EQUITY
    assert gl.account_class("5113")[0] == gl.INCOME
    assert gl.account_class("6421")[0] == gl.EXPENSE
    assert gl.account_class("711")[0] == gl.INCOME     # other income, not a 5xx
    assert gl.account_class("811")[0] == gl.EXPENSE


def test_an_unknown_account_is_reported_unknown_rather_than_guessed():
    """A mis-classified account silently moves money between the balance sheet and the P&L, which
    is the one error nobody finds by looking at a total."""
    kind, label, side = gl.account_class("ZZZ")
    assert kind is None and label == "Unclassified"


def test_assets_and_expenses_sit_on_the_debit_side():
    assert gl.normal_side("131") == "debit" and gl.normal_side("642") == "debit"
    assert gl.normal_side("331") == "credit" and gl.normal_side("511") == "credit"


def test_only_income_and_expense_belong_to_the_profit_and_loss():
    assert gl.is_pl("511") and gl.is_pl("642") and gl.is_pl("711") and gl.is_pl("811")
    assert not gl.is_pl("111") and not gl.is_pl("331") and not gl.is_pl("411")


# --- the period comes from the document ------------------------------------------------------------

def test_the_period_is_the_documents_month():
    assert gl.period_of("2026-07-31") == "2026-07"
    assert gl.period_of("2026-01-01") == "2026-01"


def test_a_date_that_is_not_a_date_is_refused_rather_than_defaulted():
    """Defaulting to today would file a January invoice in whatever month somebody happened to press
    the button, which moves revenue between periods for no reason at all."""
    for bad in ("", None, "31/07/2026", "2026-13-01", "sometime"):
        with pytest.raises(gl.LedgerError):
            gl.period_of(bad)


# --- lines --------------------------------------------------------------------------------------

def test_a_negative_amount_is_refused():
    """`debit: -500` and `credit: 500` are the same fact, but only one survives a sum grouped by
    side. Negative debits are how a ledger comes to report total debits smaller than its largest
    single debit."""
    with pytest.raises(gl.LedgerError) as e:
        gl.normalise([{"account": "642", "debit": -500}])
    assert "negative" in str(e.value)


def test_a_line_that_is_both_a_debit_and_a_credit_is_refused():
    with pytest.raises(gl.LedgerError):
        gl.normalise([{"account": "642", "debit": 10, "credit": 10}])


def test_a_line_with_no_account_is_refused():
    with pytest.raises(gl.LedgerError) as e:
        gl.normalise([{"debit": 10}])
    assert "nowhere" in str(e.value)


def test_zero_lines_are_dropped_not_posted():
    rows = gl.normalise(PAYROLL + [{"account": "911", "debit": 0, "credit": 0}])
    assert len(rows) == 3


# --- balance ------------------------------------------------------------------------------------

def test_a_balanced_batch_posts():
    b = gl.batch("payrun", "PR-1", "2026-07-31", PAYROLL)
    assert b["period"] == "2026-07" and b["debit"] == b["credit"] == 100_000_000
    assert gl.balanced(b["lines"])


def test_an_imbalance_beyond_rounding_is_refused_and_says_by_how_much():
    with pytest.raises(gl.LedgerError) as e:
        gl.batch("payrun", "PR-1", "2026-07-31",
                 [{"account": "642", "debit": 100_000_000},
                  {"account": "334", "credit": 90_000_000}])
    msg = str(e.value)
    assert "10,000,000" in msg, msg
    assert "has not been posted" in msg


def test_a_rounding_crumb_becomes_a_visible_line_rather_than_a_tolerance():
    """payroll_journal.balanced() forgives one dong because every payslip rounds individually. A
    LEDGER cannot forgive it — a trial balance one dong out is one nobody trusts — so the crumb is
    POSTED to 711/811 where it is a line somebody can add up at year end."""
    b = gl.batch("payrun", "PR-1", "2026-07-31",
                 [{"account": "642", "debit": 100_000_001},
                  {"account": "334", "credit": 100_000_000}])
    assert gl.balanced(b["lines"]), "the batch did not end up balanced"
    crumb = [l for l in b["lines"] if l.get("memo") == "rounding"]
    assert len(crumb) == 1
    assert crumb[0]["account"] == gl.ROUNDING_CREDIT and crumb[0]["credit"] == 1.0


def test_the_crumb_goes_to_the_other_side_when_credits_lead():
    b = gl.batch("payrun", "PR-1", "2026-07-31",
                 [{"account": "642", "debit": 100_000_000},
                  {"account": "334", "credit": 100_000_001}])
    crumb = [l for l in b["lines"] if l.get("memo") == "rounding"][0]
    assert crumb["account"] == gl.ROUNDING_DEBIT and crumb["debit"] == 1.0


def test_an_empty_batch_is_refused():
    with pytest.raises(gl.LedgerError):
        gl.batch("payrun", "PR-1", "2026-07-31", [{"account": "642", "debit": 0}])


# --- provenance ------------------------------------------------------------------------------------

def test_a_posting_must_name_the_document_it_came_from():
    """Without it nothing can ever be traced back, and an unexplained balance is unauditable."""
    with pytest.raises(gl.LedgerError):
        gl.batch("payrun", "", "2026-07-31", PAYROLL)


def test_an_unknown_source_is_refused_rather_than_becoming_a_new_kind_of_document():
    with pytest.raises(gl.LedgerError) as e:
        gl.batch("payrol", "PR-1", "2026-07-31", PAYROLL)     # a typo
    assert "payrun" in str(e.value)


# --- reversal ---------------------------------------------------------------------------------------

def test_a_reversal_flips_the_sides_and_does_not_negate():
    b = gl.batch("payrun", "PR-1", "2026-07-31", PAYROLL)
    r = gl.reversal(b)
    assert r["kind"] == gl.REVERSE
    assert all(l["debit"] >= 0 and l["credit"] >= 0 for l in r["lines"])
    by = {l["account"]: l for l in r["lines"]}
    assert by["642"]["credit"] == 100_000_000 and by["642"]["debit"] == 0
    assert by["334"]["debit"] == 80_000_000


def test_a_reversal_keeps_the_original_period():
    """A January posting reversed in March is a January correction. Dating it March would leave
    January overstated for ever and put a movement in March that never happened there."""
    b = gl.batch("payrun", "PR-1", "2026-01-31", PAYROLL)
    assert gl.reversal(b)["period"] == "2026-01"


def test_a_batch_and_its_reversal_cancel_exactly():
    b = gl.batch("payrun", "PR-1", "2026-07-31", PAYROLL)
    tb = gl.trial_balance(b["lines"] + gl.reversal(b)["lines"])
    assert tb["balanced"]
    assert all(r["balance"] == 0 for r in tb["rows"]), "the reversal did not cancel the posting"


# --- the trial balance ---------------------------------------------------------------------------------

def test_the_trial_balance_balances_when_the_ledger_does():
    tb = gl.trial_balance(gl.batch("payrun", "PR-1", "2026-07-31", PAYROLL)["lines"])
    assert tb["balanced"] and tb["difference"] == 0
    assert tb["debit"] == tb["credit"] == 100_000_000
    assert tb["accounts"] == 3


def test_the_trial_balance_REPORTS_an_imbalance_rather_than_hiding_it():
    """THE test. Everything above stops an unbalanced batch from being created — but a ledger can
    still be out for reasons the batch rules never see: a row written by a future migration, a
    hand-edited database, a source module that grows a bug. The report's job is to SAY SO.

    A check that cannot fail certifies nothing, so this feeds it a ledger that genuinely does not
    balance and requires that it says so — with the size of the gap, because "not balanced" without
    a number tells an accountant nothing about where to look."""
    broken = [{"account": "642", "debit": 100_000_000},
              {"account": "334", "credit": 99_000_000}]      # 1m short — as if a row went missing
    tb = gl.trial_balance(broken)
    assert tb["balanced"] is False, "the trial balance called an unbalanced ledger balanced"
    assert tb["difference"] == 1_000_000
    assert tb["debit"] == 100_000_000 and tb["credit"] == 99_000_000


def test_the_balance_is_shown_on_the_accounts_normal_side():
    """An expense with 10m of debits and 2m of credits is an 8m expense — that is the figure that
    goes on a P&L, not two columns for the reader to net off."""
    tb = gl.trial_balance([{"account": "642", "debit": 10_000_000},
                           {"account": "642", "credit": 2_000_000},
                           {"account": "511", "credit": 8_000_000}])
    by = {r["account"]: r for r in tb["rows"]}
    assert by["642"]["balance"] == 8_000_000 and by["642"]["normalSide"] == "debit"
    assert by["511"]["balance"] == 8_000_000 and by["511"]["normalSide"] == "credit"


def test_an_account_sitting_on_the_wrong_side_is_shown_negative_not_tidied_away():
    """A liability with more debits than credits is a real fact — usually an overpayment or a
    posting to the wrong account — and flipping it into the debit column to look neat is how it
    stops being noticed."""
    tb = gl.trial_balance([{"account": "331", "debit": 5_000_000},
                           {"account": "111", "credit": 5_000_000}])
    by = {r["account"]: r for r in tb["rows"]}
    assert by["331"]["balance"] == -5_000_000


def test_the_gross_totals_are_kept_because_net_balances_alone_cannot_prove_it_balances():
    tb = gl.trial_balance([{"account": "642", "debit": 10}, {"account": "642", "credit": 4},
                           {"account": "334", "credit": 6}])
    assert tb["debit"] == 10 and tb["credit"] == 10        # gross movement
    assert tb["debitBalances"] == tb["creditBalances"] == 6  # netted


def test_an_empty_ledger_balances_and_says_nothing_else():
    tb = gl.trial_balance([])
    assert tb["balanced"] and tb["accounts"] == 0 and tb["debit"] == 0


# --- the bottom line -----------------------------------------------------------------------------------

def test_the_result_is_revenue_less_expenses_and_ignores_the_balance_sheet():
    rows = [{"account": "511", "credit": 100_000_000},      # revenue
            {"account": "632", "debit": 60_000_000},        # cost of sales
            {"account": "642", "debit": 10_000_000},        # admin
            {"account": "131", "debit": 100_000_000},       # a receivable — not a P&L item
            {"account": "334", "credit": 50_000_000}]       # a payable — likewise
    r = gl.result(rows)
    assert r["income"] == 100_000_000
    assert r["expense"] == 70_000_000
    assert r["profit"] == 30_000_000


def test_a_credit_note_reduces_revenue_rather_than_becoming_an_expense():
    r = gl.result([{"account": "511", "credit": 100_000_000},
                   {"account": "511", "debit": 10_000_000}])
    assert r["income"] == 90_000_000 and r["expense"] == 0
