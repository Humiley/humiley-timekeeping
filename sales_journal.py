"""The accounting entries the sell side produces: a certified claim, cash received, a credit note.

The sell side already computes everything correctly — `_certify_application` moves the contract's
balances, refuses to overshoot, and prices the VAT line against a recorded tax point. What it never
did was POST any of it, so revenue and receivables lived only inside the documents that created
them, and "what does this customer owe us in total" could not be answered by adding anything up.

WHAT IS ARITHMETIC HERE AND WHAT IS POLICY

The arithmetic is fixed: a claim creates a receivable equal to the work certified plus its output
VAT, and cash received reduces that receivable. That much is not a matter of opinion, and it is
enforced by tests.

The POLICY is which account each of those lands in, and there the module does what
`payroll_journal.py` does: it carries a documented default and takes an override, because a company
on Circular 133 or with its own sub-accounts uses different numbers and guessing on their behalf
would produce books that look right and are not theirs.

THE TWO TREATMENTS THAT ARE DELIBERATELY NOT ENTRIES

**Advance recovery.** A customer advance was received as cash against account 131, which under
Circular 200 may carry a credit balance for exactly this reason. When a claim recovers part of it,
nothing moves between accounts — the customer simply pays less, so the RECEIPT is smaller. Posting a
recovery entry as well would double-count it.

**Retention.** Retention withheld is still owed; it is owed later. It stays in the receivable, and
the difference between what was certified and what was paid is a genuine open 131 balance that the
retention register already explains. A company that wants retention visible in its own account can
set `retention` in the account map — then, and only then, it moves.

Both are stated here because a reader who does not find an entry for them will otherwise assume one
was forgotten.
"""

import gl

# Circular 200/2014/TT-BTC. Every one of these is overridable through the account map.
ACC = {
    "receivable": "131",     # Phải thu của khách hàng
    "revenue": "511",        # Doanh thu bán hàng và cung cấp dịch vụ
    "outputVat": "3331",     # Thuế GTGT phải nộp
    "bank": "112",           # Tiền gửi ngân hàng
    "cash": "111",           # Tiền mặt
    # A credit note reduces REVENUE by default (a debit to 511), which is what `gl.result` reads as
    # income going down. A company that reports returns and allowances separately sets 5213 here.
    "creditNote": "511",
    # Unset by default: retention stays inside the receivable. See the module docstring.
    "retention": "",
}

NAMES = {
    "131": "Phải thu của khách hàng / Trade receivables",
    "511": "Doanh thu bán hàng và cung cấp dịch vụ / Revenue",
    "5213": "Hàng bán bị trả lại / Sales returns and allowances",
    "3331": "Thuế GTGT phải nộp / Output VAT payable",
    "112": "Tiền gửi ngân hàng / Cash at bank",
    "111": "Tiền mặt / Cash on hand",
    "1388": "Phải thu khác / Other receivables",
}

# Which cash account a receipt lands in. A method nobody recognises goes to the BANK default rather
# than to cash: a mistaken bank entry is found at the next reconciliation, whereas money wrongly in
# 111 has to be found by somebody counting a drawer.
CASH_METHODS = {
    "cash": "cash", "tiền mặt": "cash", "tien mat": "cash",
}


def _n(v):
    try:
        return float(v or 0)
    except (TypeError, ValueError):
        return 0.0


def _acc(accounts, key):
    a = dict(ACC, **(accounts or {}))
    return str(a.get(key) or ACC.get(key) or "").strip()


def _line(code, debit=0.0, credit=0.0, memo=""):
    return {"account": code, "name": NAMES.get(code, ""), "debit": round(_n(debit), 2),
            "credit": round(_n(credit), 2), "memo": memo}


def cash_account(method, accounts=None):
    key = CASH_METHODS.get(str(method or "").strip().lower(), "bank")
    return _acc(accounts, key)


# ── a certified payment application ──────────────────────────────────────────────────────────────

def application_entries(app, accounts=None):
    """A certified claim: the work becomes revenue, and the customer owes it plus VAT.

    Reads the FROZEN certified figures (`certifiedThis`, `vatAmount`) — the claim as it stood when it
    was signed — rather than recomputing from the lines, for the same reason `payroll_journal` reads
    a pay run's frozen `calc`: the journal must describe what was certified, not a second opinion
    about it formed later.
    """
    certified = _n(app.get("certifiedThis"))
    vat = _n(app.get("vatAmount"))
    if certified <= 0:
        raise gl.LedgerError(
            "This claim certifies nothing (%s), so there is no revenue to recognise. A claim worth "
            "zero is a draft somebody signed by accident." % certified)

    ar = _acc(accounts, "receivable")
    lines = [
        _line(ar, debit=certified + vat, memo="claim + output VAT"),
        _line(_acc(accounts, "revenue"), credit=certified, memo="work certified"),
    ]
    if vat:
        lines.append(_line(_acc(accounts, "outputVat"), credit=vat, memo="output VAT"))

    # Only if the company has asked for retention in its own account — see the module docstring.
    ret_acc = _acc(accounts, "retention")
    retention = _n(app.get("retentionThis"))
    if ret_acc and retention > 0:
        lines.append(_line(ret_acc, debit=retention, memo="retention withheld"))
        lines.append(_line(ar, credit=retention, memo="retention out of receivables"))

    return lines


def application_warnings(app):
    """What is true about this claim that an accountant should see BEFORE it posts.

    Not refusals. A claim with an unpriced VAT line is a real claim that was certified; refusing to
    post it would leave the revenue out of the books entirely, which is worse than posting it with
    the gap named.
    """
    out = []
    if not app.get("vatSet"):
        out.append("The VAT on this claim was not priced against a recorded tax point, so the "
                   "output VAT posted here is whatever the claim carried (%s). Confirm it before "
                   "the period is closed." % format(int(_n(app.get("vatAmount"))), ","))
    if _n(app.get("retentionThis")) > 0 and not ACC["retention"]:
        out.append("%s of retention stays inside the receivable, which is where the retention "
                   "register explains it. Set a retention account if it should sit on its own."
                   % format(int(_n(app.get("retentionThis"))), ","))
    return out


# ── cash received ────────────────────────────────────────────────────────────────────────────────

def receipt_entries(receipt, accounts=None):
    """Cash in against the receivable it settles.

    The amount is the RECEIPT's, never the sum of its allocations. The endpoint already refuses a
    receipt whose allocations do not add up to it, so the two agree — and if a future change ever
    breaks that, the ledger should carry what actually arrived in the bank rather than what the
    allocation rows claim.
    """
    amount = _n(receipt.get("amount"))
    if amount <= 0:
        raise gl.LedgerError("A receipt of %s is not money arriving." % amount)
    return [
        _line(cash_account(receipt.get("method"), accounts), debit=amount, memo="cash received"),
        _line(_acc(accounts, "receivable"), credit=amount, memo="settles the customer's account"),
    ]


# ── a credit note ────────────────────────────────────────────────────────────────────────────────

def credit_entries(note, accounts=None):
    """Value given back: revenue down, VAT down, the customer owes less.

    The mirror of a claim, and written as its own entries rather than as `gl.reversal` of one,
    because a credit note is not a correction of a posting — it is a real commercial event with its
    own date, its own document number, and often a different period from the claim it credits.
    """
    value = _n(note.get("creditThis") or note.get("value") or note.get("amount"))
    vat = _n(note.get("vatAmount"))
    if value <= 0:
        raise gl.LedgerError("This credit note credits nothing (%s)." % value)
    lines = [
        _line(_acc(accounts, "creditNote"), debit=value, memo="value credited"),
    ]
    if vat:
        lines.append(_line(_acc(accounts, "outputVat"), debit=vat, memo="output VAT credited"))
    lines.append(_line(_acc(accounts, "receivable"), credit=value + vat,
                       memo="customer owes less"))
    return lines
