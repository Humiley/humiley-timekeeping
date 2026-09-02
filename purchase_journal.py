"""The entries a PAID payment request makes — the last money flow in the portal that ended nowhere.

A payment request in this portal is already a serious document: three levels of approval, an
e-signature to disburse, and a bank slip refused-if-missing as proof of payment. What it never did
was reach the accounts, so cash going out was the one side of the business the ledger could not see.

ONE LIMITATION, STATED RATHER THAN HIDDEN
=========================================
The portal has no purchase-invoice step. Nothing books a supplier invoice as a payable when it
arrives; a payment request IS the first record of the cost. So expense here is recognised **when the
money leaves**, not when the invoice was received:

    Dr  expense (by category)          Cr  bank / cash

That is cash-basis for the buy side, and it is a real difference from the sell side, where a claim
recognises revenue on certification. It is written here so nobody reads the balance sheet believing
accounts payable is complete — there is no 331 balance because nothing accrues one. When a purchase
invoice register exists, this becomes `Dr 331` and the accrual carries the expense instead.

WHICH ACCOUNT A CATEGORY BELONGS IN IS THE ACCOUNTANT'S DECISION
================================================================
The map below is a documented default over Circular 200, overridable through
`portal_purchaseAccounts` — the same shape as `portal_payrollAccounts` and `portal_salesAccounts`.
Some of these are genuinely contestable for a contractor: whether subcontract cost sits in 627 or
632, whether freight is 641 or capitalised into 156. Those are marked, and every category that
falls through to the default is NAMED in a warning rather than posted quietly, so a thirteenth
category added to the form later cannot land somewhere nobody chose.
"""

import gl

# The default expense account per payment category. Keys are the exact strings the payment form
# offers (`_PAY_CATS` in the page) plus `Final settlement`, which the offboarding path raises.
CATEGORY_ACC = {
    "Operating expense": "642",       # Chi phí quản lý doanh nghiệp
    "Purchase — Goods": "156",        # Hàng hóa — stock, not an expense until it is sold
    "Purchase — Service": "642",
    "Utilities": "642",               # a company with cost centres may prefer 6427 / 627
    "Rent / Lease": "642",
    "Repair / Maintenance": "642",    # 627 if the plant being repaired is production
    "Logistics / Freight": "641",     # CONTESTABLE: freight-in is often capitalised into 156
    "Subcontractor": "627",           # CONTESTABLE: many contractors use 632 or 154
    # Settling a subcontract certificate that has ALREADY accrued. It clears the payable that
    # subcontract_journal credited; it does not recognise the cost, because the certificate did
    # that when the obligation arose. Chosen by a person: no field links a payment request to a
    # certificate, and guessing here debits the wrong account for real money.
    "Subcontract settlement": "331",
    "Marketing": "641",               # Chi phí bán hàng
    "Travel-related": "642",
    "Tax / Statutory": "3339",        # Thuế khác — which tax matters, so this is usually overridden
    "Other": "642",
    # A final settlement is employee compensation. Paying it should CLEAR the payroll liability —
    # see the note in `warnings()` about what happens when nothing accrued it.
    "Final settlement": "334",
}

# Where an unrecognised category goes. Not nowhere: a line that vanishes is worse than one posted to
# review — the same reasoning payroll_journal uses for an unmapped department.
FALLBACK = "642"

NAMES = {
    "111": "Tiền mặt / Cash on hand",
    "112": "Tiền gửi ngân hàng / Cash at bank",
    "156": "Hàng hóa / Merchandise inventory",
    "331": "Phải trả cho người bán / Trade payables",
    "334": "Phải trả người lao động / Payable to employees",
    "3339": "Thuế khác / Other taxes",
    "627": "Chi phí sản xuất chung / Factory overhead",
    "632": "Giá vốn hàng bán / Cost of goods sold",
    "641": "Chi phí bán hàng / Selling expense",
    "642": "Chi phí quản lý doanh nghiệp / Administrative expense",
}

# Which side the money left from. Anything unrecognised is treated as a BANK payment: a mistaken
# bank entry surfaces at the next reconciliation, whereas money wrongly recorded as cash has to be
# found by somebody counting a drawer.
CASH_METHODS = ("cash", "tiền mặt", "tien mat")


def _n(v):
    try:
        return float(v or 0)
    except (TypeError, ValueError):
        return 0.0


def _line(code, debit=0.0, credit=0.0, memo=""):
    return {"account": code, "name": NAMES.get(code, ""), "debit": round(_n(debit), 2),
            "credit": round(_n(credit), 2), "memo": memo}


def cash_account(method, accounts=None):
    a = dict(accounts or {})
    key = "cash" if str(method or "").strip().lower() in CASH_METHODS else "bank"
    return str(a.get(key) or ("111" if key == "cash" else "112"))


def expense_account(category, accounts=None):
    """The account this category's cost belongs in, and whether it was actually mapped.

    Returns (code, mapped). `mapped` is False when the category is not in the map at all — the
    caller turns that into a warning naming the category, so a new one added to the form cannot
    land in the default silently.
    """
    cat = str(category or "").strip()
    overrides = dict(accounts or {})
    if cat in overrides:
        return str(overrides[cat]), True
    if cat in CATEGORY_ACC:
        return str(CATEGORY_ACC[cat]), True
    return str(overrides.get("fallback") or FALLBACK), False


def entries(payment, accounts=None):
    """Money out: the cost recognised, and the account it left from."""
    amount = _n(payment.get("amount"))
    if amount <= 0:
        raise gl.LedgerError(
            "This payment is for %s, so there is nothing to post. A request worth nothing is a "
            "draft somebody disbursed by accident." % amount)
    acc, _mapped = expense_account(payment.get("category"), accounts)
    return [
        _line(acc, debit=amount, memo=str(payment.get("category") or "payment")),
        _line(cash_account(payment.get("method"), accounts), credit=amount,
              memo="paid to %s" % (str(payment.get("payee") or "").strip() or "payee")),
    ]


def warnings(payment, accounts=None):
    """What an accountant should see before this posts. None of these block it — the money has
    already left the bank, and refusing to record that would leave the ledger further from the
    truth, not closer."""
    out = []
    cat = str(payment.get("category") or "").strip()
    acc, mapped = expense_account(cat, accounts)
    if not mapped:
        out.append("'%s' is not in the purchase account map, so it has been posted to %s for "
                   "review. Map it before the period is closed."
                   % (cat or "(no category)", acc))
    if cat == "Final settlement":
        out.append("A final settlement clears the payable to the employee (334). Nothing in the "
                   "portal accrues it first, so until a settlement is booked as a liability this "
                   "leaves 334 with a debit balance — which the balance sheet shows in red rather "
                   "than tidying away.")
    if cat == "Subcontract settlement":
        out.append("This clears the payable a subcontractor's certificate accrued (331). It does "
                   "NOT recognise cost — the certificate did that. If no certificate was posted "
                   "for this work, 331 goes into debit and the cost is missing from the accounts "
                   "entirely; the balance sheet shows that in red rather than tidying it away.")
    if cat == "Purchase — Goods":
        out.append("Goods bought for resale are posted to stock (156), not to expense. They reach "
                   "the profit and loss when they are sold, which nothing in the portal records "
                   "yet — so cost of sales will be understated until it does.")
    if not str(payment.get("bankSlip") or "").strip():
        out.append("No bank slip is attached to this payment. Marking it paid requires one, so a "
                   "record without it was either imported or predates that rule.")
    return out
