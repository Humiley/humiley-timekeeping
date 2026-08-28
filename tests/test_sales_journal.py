"""The entries the sell side makes, and the two treatments that are deliberately NOT entries.

A claim creates a receivable equal to the work certified plus its output VAT; cash received reduces
that receivable. That much is arithmetic and is pinned here. WHICH ACCOUNT each lands in is policy,
carried as a documented default with an override — so the tests check the default is sane and that
the override actually reaches the entries, not that any particular number is universally right.
"""
import pytest

import gl
import sales_journal as sj


CLAIM = {"certifiedThis": 2_000_000_000, "vatAmount": 200_000_000,
         "retentionThis": 100_000_000, "advanceRecovered": 300_000_000,
         "netPayable": 1_600_000_000, "vatSet": True, "appNo": "PA-001"}


# --- a certified claim ----------------------------------------------------------------------------

def test_a_claim_recognises_the_work_and_the_vat_it_carries():
    e = sj.application_entries(CLAIM)
    by = {l["account"]: l for l in e}
    assert by["511"]["credit"] == 2_000_000_000, "revenue is the work certified"
    assert by["3331"]["credit"] == 200_000_000, "output VAT is a liability, not revenue"
    assert by["131"]["debit"] == 2_200_000_000, "the customer owes the work plus its VAT"
    assert gl.balanced(e)


def test_the_advance_recovery_is_not_an_entry():
    """A customer advance came in as cash against 131, which Circular 200 lets carry a credit
    balance for exactly this reason. Recovering it moves nothing between accounts — the customer
    simply pays less, so the RECEIPT is smaller. An entry here would double-count it.

    Pinned because a reader who finds no entry for a 300m recovery will otherwise assume one was
    forgotten and 'fix' it."""
    e = sj.application_entries(CLAIM)
    assert not any(l["memo"] == "advance" for l in e)
    # And the receivable is the FULL claim, not the net payable — the netting is inside 131.
    assert {l["account"]: l["debit"] for l in e}["131"] == 2_200_000_000
    assert gl.balanced(e)


def test_retention_stays_in_the_receivable_by_default():
    """It is still owed; it is owed later. The retention register already explains the open
    balance."""
    e = sj.application_entries(CLAIM)
    assert not any(l["memo"] == "retention withheld" for l in e)
    assert len(e) == 3


def test_retention_moves_only_when_the_company_asks_for_it():
    e = sj.application_entries(CLAIM, {"retention": "1388"})
    by = [l for l in e if l["account"] == "1388"]
    assert by and by[0]["debit"] == 100_000_000
    # …and it comes OUT of the receivable, so nothing is counted twice.
    ar = sum(l["debit"] - l["credit"] for l in e if l["account"] == "131")
    assert ar == 2_100_000_000
    assert gl.balanced(e), "moving retention unbalanced the claim"


def test_a_claim_with_no_vat_omits_the_vat_line_rather_than_posting_a_zero():
    e = sj.application_entries(dict(CLAIM, vatAmount=0))
    assert not any(l["account"] == "3331" for l in e)
    assert gl.balanced(e)


def test_a_claim_that_certifies_nothing_is_refused():
    with pytest.raises(gl.LedgerError) as ex:
        sj.application_entries(dict(CLAIM, certifiedThis=0))
    assert "draft somebody signed by accident" in str(ex.value)


def test_the_company_can_override_every_account():
    e = sj.application_entries(CLAIM, {"receivable": "1311", "revenue": "5112",
                                       "outputVat": "33311"})
    assert {l["account"] for l in e} == {"1311", "5112", "33311"}
    assert gl.balanced(e)


def test_an_unpriced_vat_line_is_a_warning_and_not_a_refusal():
    """The claim was certified; the revenue belongs in the books. Refusing to post it would leave
    the revenue out entirely, which is worse than posting it with the gap named."""
    w = sj.application_warnings(dict(CLAIM, vatSet=False))
    assert any("not priced against a recorded tax point" in x for x in w)
    assert gl.balanced(sj.application_entries(dict(CLAIM, vatSet=False))), "it still posts"


def test_a_priced_claim_with_no_retention_warns_about_nothing():
    assert sj.application_warnings(dict(CLAIM, retentionThis=0)) == []


# --- cash in --------------------------------------------------------------------------------------

def test_a_receipt_moves_cash_against_the_receivable():
    e = sj.receipt_entries({"amount": 1_760_000_000, "method": "Bank transfer"})
    by = {l["account"]: l for l in e}
    assert by["112"]["debit"] == 1_760_000_000
    assert by["131"]["credit"] == 1_760_000_000
    assert gl.balanced(e)


def test_cash_in_hand_and_bank_are_different_accounts():
    assert sj.cash_account("cash") == "111"
    assert sj.cash_account("Tiền mặt") == "111"
    assert sj.cash_account("Bank transfer") == "112"


def test_an_unrecognised_method_goes_to_the_bank_not_to_the_drawer():
    """A mistaken bank entry surfaces at the next reconciliation. Money wrongly in 111 has to be
    found by somebody counting a drawer."""
    for method in ("", None, "Visa", "chuyển khoản", "unknown"):
        assert sj.cash_account(method) == "112", method


def test_a_receipt_of_nothing_is_refused():
    for amount in (0, -1):
        with pytest.raises(gl.LedgerError):
            sj.receipt_entries({"amount": amount})


# --- a credit note --------------------------------------------------------------------------------

def test_a_credit_note_reduces_revenue_and_vat_and_what_is_owed():
    e = sj.credit_entries({"creditThis": 50_000_000, "vatAmount": 5_000_000})
    by = {l["account"]: l for l in e}
    assert by["511"]["debit"] == 50_000_000
    assert by["3331"]["debit"] == 5_000_000
    assert by["131"]["credit"] == 55_000_000
    assert gl.balanced(e)


def test_a_claim_and_a_credit_note_net_correctly_in_the_result():
    rows = sj.application_entries(CLAIM) + sj.credit_entries({"creditThis": 50_000_000,
                                                              "vatAmount": 5_000_000})
    r = gl.result(rows)
    assert r["income"] == 1_950_000_000, "the credit did not reduce revenue"
    assert r["expense"] == 0, "a credit note is not an expense"


def test_a_company_reporting_returns_separately_can_say_so():
    e = sj.credit_entries({"creditThis": 50_000_000}, {"creditNote": "5213"})
    assert any(l["account"] == "5213" and l["debit"] == 50_000_000 for l in e)
    # 5213 is still an income-class account, so the result still reads as revenue coming down.
    assert gl.result(e)["income"] == -50_000_000


def test_a_credit_note_for_nothing_is_refused():
    with pytest.raises(gl.LedgerError):
        sj.credit_entries({"creditThis": 0})


# --- every source balances, on every shape --------------------------------------------------------

@pytest.mark.parametrize("doc,fn", [
    (CLAIM, sj.application_entries),
    (dict(CLAIM, vatAmount=0, retentionThis=0), sj.application_entries),
    ({"amount": 1, "method": "cash"}, sj.receipt_entries),
    ({"creditThis": 7, "vatAmount": 0}, sj.credit_entries),
])
def test_it_balances(doc, fn):
    e = fn(doc)
    assert e and gl.balanced(e), gl.totals(e)
