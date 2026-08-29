"""Cash out: the entries a paid payment request makes, and the limitation it has to admit.

The portal has no purchase-invoice step, so a payment request is the first record of a cost and
expense is recognised WHEN THE MONEY LEAVES. That is cash-basis on the buy side while the sell side
recognises revenue on certification, and the difference is stated in the module rather than left for
somebody to discover from a balance sheet with no payables on it.
"""
import pytest

import gl
import purchase_journal as pj


def _pay(amount=500_000_000, category="Operating expense", method="Bank transfer",
         payee="Acme Co", slip="data:image/png;base64,x", **kw):
    return dict({"amount": amount, "category": category, "method": method, "payee": payee,
                 "bankSlip": slip, "reqNo": "PAY-001", "paidOn": "2026-07-15"}, **kw)


# --- the entry ------------------------------------------------------------------------------------

def test_a_paid_payment_debits_the_cost_and_credits_the_bank():
    e = pj.entries(_pay())
    by = {l["account"]: l for l in e}
    assert by["642"]["debit"] == 500_000_000
    assert by["112"]["credit"] == 500_000_000
    assert gl.balanced(e)


def test_cash_and_bank_are_different_accounts():
    assert pj.cash_account("cash") == "111"
    assert pj.cash_account("Tiền mặt") == "111"
    assert pj.cash_account("Bank transfer") == "112"


def test_an_unrecognised_method_is_treated_as_a_bank_payment():
    """A mistaken bank entry surfaces at the next reconciliation. Money wrongly recorded as cash has
    to be found by somebody counting a drawer."""
    for m in ("", None, "Visa", "chuyển khoản", "wire"):
        assert pj.cash_account(m) == "112", m


def test_a_payment_for_nothing_is_refused():
    for amount in (0, -1):
        with pytest.raises(gl.LedgerError):
            pj.entries(_pay(amount=amount))


# --- the category map ------------------------------------------------------------------------------

@pytest.mark.parametrize("category,account", [
    ("Operating expense", "642"),
    ("Purchase — Goods", "156"),
    ("Purchase — Service", "642"),
    ("Subcontractor", "627"),
    ("Marketing", "641"),
    ("Tax / Statutory", "3339"),
    ("Final settlement", "334"),
])
def test_every_category_the_form_offers_has_an_account(category, account):
    """A category the map does not cover posts to a fallback and warns — which is right for a
    category somebody invents later, and wrong as a way to ship the twelve that already exist."""
    code, mapped = pj.expense_account(category)
    assert mapped is True, category
    assert code == account


def test_an_unmapped_category_posts_to_review_and_NAMES_itself():
    """A line that vanishes is worse than one posted to review — the same reasoning payroll uses for
    an unmapped department. But it must say which category, or a thirteenth one added to the form
    lands in 642 and nobody ever finds out."""
    p = _pay(category="Cryptocurrency")
    code, mapped = pj.expense_account("Cryptocurrency")
    assert mapped is False and code == pj.FALLBACK
    w = pj.warnings(p)
    assert any("Cryptocurrency" in x and "for review" in x for x in w), w
    assert gl.balanced(pj.entries(p)), "it still posts"


def test_a_missing_category_is_treated_the_same_as_an_unknown_one():
    w = pj.warnings(_pay(category=""))
    assert any("no category" in x for x in w), w


def test_the_company_can_override_any_category():
    """Some defaults are genuinely contestable for a contractor — subcontract in 627 against 632,
    freight in 641 against capitalised into 156. That is why they are a setting."""
    code, mapped = pj.expense_account("Subcontractor", {"Subcontractor": "632"})
    assert code == "632" and mapped is True
    e = pj.entries(_pay(category="Subcontractor"), {"Subcontractor": "632"})
    assert any(l["account"] == "632" for l in e)
    assert gl.balanced(e)


def test_the_fallback_itself_can_be_overridden():
    code, mapped = pj.expense_account("Something new", {"fallback": "1388"})
    assert code == "1388" and mapped is False, "still unmapped — just parked somewhere else"


def test_the_cash_accounts_can_be_overridden():
    assert pj.cash_account("cash", {"cash": "1111"}) == "1111"
    assert pj.cash_account("Bank transfer", {"bank": "1121"}) == "1121"


# --- the warnings that are really disclosures --------------------------------------------------------

def test_goods_bought_for_resale_say_that_cost_of_sales_is_understated():
    """156 is stock, not expense. Nothing in the portal records the sale that moves it to 632, so
    saying so is the difference between a limitation and a silent error."""
    w = pj.warnings(_pay(category="Purchase — Goods"))
    assert any("cost of sales will be understated" in x for x in w), w


def test_a_final_settlement_says_what_happens_with_no_accrual():
    """It clears 334, but nothing accrued it — so 334 goes debit until something does. The balance
    sheet already shows an account on the wrong side in red; this explains why."""
    w = pj.warnings(_pay(category="Final settlement"))
    assert any("debit balance" in x for x in w), w


def test_a_payment_with_no_bank_slip_is_flagged_but_still_posts():
    """Marking a payment paid REQUIRES a slip, so a record without one was imported or predates that
    rule. The money still left the bank; refusing to record it would put the ledger further from the
    truth, not closer."""
    p = _pay(slip="")
    assert any("No bank slip" in x for x in pj.warnings(p))
    assert gl.balanced(pj.entries(p))


def test_a_clean_ordinary_payment_warns_about_nothing():
    assert pj.warnings(_pay()) == []


# --- it balances, on every category ------------------------------------------------------------------

def test_it_balances_for_every_category_in_the_map():
    for category in list(pj.CATEGORY_ACC) + ["Something nobody has invented yet"]:
        e = pj.entries(_pay(category=category))
        assert gl.balanced(e), (category, gl.totals(e))
        assert len(e) == 2
