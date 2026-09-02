"""The entries a subcontractor payment certificate makes — the accrual purchase_journal said was
missing.

purchase_journal recognises buy-side cost when the money LEAVES, and says why in its own docstring:

    "Nothing books a supplier invoice as a payable when it arrives; a payment request IS the first
     record of the cost... there is no 331 balance because nothing accrues one. When a purchase
     invoice register exists, this becomes `Dr 331` and the accrual carries the expense instead."

A subcontractor payment certificate is that document. A QS values what a subcontractor has built,
deducts the retention the subcontract entitles us to hold, and certifies the balance. From that
moment the company owes it — weeks before anybody presses a button in the bank. The obligation is
the event, and the ledger could not see it: the back-to-back position reports billions payable that
appear nowhere in the trial balance.

WHAT IT POSTS
=============
    Dr  Subcontract cost         gross certified
        Cr  Trade payables               net certified
        Cr  Retention payable            retention deducted

Retention is separated from the ordinary payable on purpose. It is owed to the subcontractor and it
is NOT due — half of it typically waits for practical completion and the rest for the end of the
defects period. A balance sheet that shows it inside 331 states that the company owes it now.

WHAT IT WILL NOT DO
===================
It refuses a certificate whose own three figures do not add up. gross - retention must equal the net
somebody signed; where it does not, one of the three is wrong and posting any two of them puts a
number in the books that appears on no piece of paper. `qsurvey.subcontract_position()` reports the
same disagreement without correcting it, for the same reason.

It does not post the SETTLEMENT. Money leaving the bank is already a payment request — three
approvals, an e-signature, a bank slip — and inventing a second route for the same cash would
double-count it. What paying a certificate must do instead is clear this accrual rather than
recognise the cost again, and that is a category on the payment: "Subcontract settlement", mapped to
331 in purchase_journal. It is chosen by a person, because no field links the two documents and a
guess here debits the wrong account for real money.

WHICH ACCOUNT IS THE ACCOUNTANT'S DECISION
==========================================
The defaults below are documented over Circular 200 and overridable through
`portal_subcontractAccounts` — the same shape as portal_purchaseAccounts and portal_salesAccounts.
Both are genuinely contestable for a contractor and both are marked.
"""

import gl

# CONTESTABLE: 627 (chi phí sản xuất chung) is where most Vietnamese contractors put subcontract
# cost on a job in progress. A company running full construction-contract accounting uses 154, and
# one that expenses straight to cost of sales uses 632. All three are defensible; the map is
# overridable and the default is stated rather than assumed.
COST_ACC = "627"

# CONTESTABLE: retention held FROM a subcontractor is a payable that is not yet due. 3388 (phải
# trả, phải nộp khác) keeps it out of ordinary trade payables so the balance sheet does not claim
# the company owes it today. A company preferring a 331 sub-account (3312) overrides this.
RETENTION_ACC = "3388"

PAYABLE_ACC = "331"

NAMES = {
    "154": "Chi phí SXKD dở dang / Work in progress",
    "331": "Phải trả cho người bán / Trade payables",
    "3388": "Phải trả, phải nộp khác / Other payables",
    "627": "Chi phí sản xuất chung / Contract overhead",
    "632": "Giá vốn hàng bán / Cost of sales",
}

# A certificate the subcontractor has merely submitted is his claim, not our liability — the same
# rule the sell side applies to an uncertified application. Only these accrue.
POSTABLE = ("certified", "paid")

# A dong. The three figures on a certificate are typed by hand and rounded to the dong; larger than
# this is somebody's arithmetic, not rounding.
TOLERANCE = 1.0


def _n(v):
    try:
        return float(str(v or 0).replace(",", "").strip())
    except (TypeError, ValueError):
        return 0.0


def _acc(key, default, accounts):
    acc = (accounts or {}).get(key)
    acc = str(acc or "").strip()
    return (acc, True) if acc else (default, False)


def cost_account(discipline, accounts=None):
    """The account this trade's cost belongs in.

    A contractor with sub-accounts per trade (6271 civil, 6272 mechanical) sets them here and the
    ledger classifies them correctly on their first digit without anybody maintaining a list.
    """
    by_trade = (accounts or {}).get("byTrade") or {}
    code = str(discipline or "").strip().lower()
    if isinstance(by_trade, dict) and by_trade.get(code):
        return str(by_trade[code]).strip(), True
    return _acc("cost", COST_ACC, accounts)


def retention_account(accounts=None):
    return _acc("retention", RETENTION_ACC, accounts)


def payable_account(accounts=None):
    return _acc("payable", PAYABLE_ACC, accounts)


def _line(account, debit=0.0, credit=0.0, memo=""):
    return {"account": str(account), "debit": round(_n(debit), 2),
            "credit": round(_n(credit), 2), "memo": memo,
            "name": NAMES.get(str(account), "")}


def check(cert):
    """Why this certificate cannot post, or "" if it can.

    Separated from `entries` so the unposted list can say what is wrong with a document without
    trying to build it — a screen that reports "could not post" and not why sends somebody to the
    accountant with no question to ask.
    """
    gross = _n(cert.get("grossClaimed"))
    ret = _n(cert.get("retentionDeducted"))
    net_raw = str(cert.get("netCertified") or "").strip()
    if gross <= 0:
        return ("This certificate is for nothing. A certificate worth nil records no obligation, "
                "and posting it would put an empty document in the books.")
    if ret < 0:
        return ("The retention on this certificate is negative. Releasing retention is a smaller "
                "figure held, not a negative deduction.")
    if ret > gross + TOLERANCE:
        return ("This certificate deducts more retention (%s) than it certifies (%s), so the "
                "subcontractor is owed a negative amount." % (_fmt(ret), _fmt(gross)))
    if net_raw:
        net = _n(net_raw)
        if abs(net - (gross - ret)) > TOLERANCE:
            return ("This certificate does not add up: %s gross less %s retention is %s, and it "
                    "states a net of %s. One of the three is wrong, and posting any two of them "
                    "puts a figure in the books that appears on no piece of paper."
                    % (_fmt(gross), _fmt(ret), _fmt(gross - ret), _fmt(net)))
    return ""


def _fmt(n):
    return "{:,.0f}".format(_n(n))


def entries(cert, accounts=None):
    """The obligation this certificate creates: the cost incurred, and to whom it is owed."""
    why = check(cert)
    if why:
        raise gl.LedgerError(why)
    gross = round(_n(cert.get("grossClaimed")), 2)
    ret = round(_n(cert.get("retentionDeducted")), 2)
    # The net is DERIVED here and not read, because `check` has already refused every certificate
    # where the stated net disagrees with these two. Reading it as well would give two sources for
    # one figure and a rounding crumb between them.
    net = round(gross - ret, 2)
    who = str(cert.get("vendor") or "").strip() or "subcontractor"
    ref = str(cert.get("certNo") or "").strip() or "certificate"
    pkg = str(cert.get("pkgNo") or "").strip()

    acc, _ = cost_account(cert.get("discipline"), accounts)
    out = [_line(acc, debit=gross,
                 memo=("%s %s" % (pkg, ref)).strip() if pkg else ref)]
    if net > 0:
        out.append(_line(payable_account(accounts)[0], credit=net, memo="due to %s" % who))
    if ret > 0:
        out.append(_line(retention_account(accounts)[0], credit=ret,
                         memo="retention held from %s" % who))
    return out


def warnings(cert, accounts=None):
    """What an accountant should see before this posts. None of these block it — the obligation is
    real whether or not the record around it is tidy, and refusing to book a liability the company
    has genuinely incurred leaves the balance sheet further from the truth, not closer."""
    out = []
    _cost, mapped = cost_account(cert.get("discipline"), accounts)
    if not mapped:
        out.append("Subcontract cost is posted to %s by default. Whether it belongs in 627, 154 or "
                   "632 is your decision — set portal_subcontractAccounts before the period closes."
                   % COST_ACC)
    ret_acc, ret_mapped = retention_account(accounts)
    if _n(cert.get("retentionDeducted")) > 0 and not ret_mapped:
        out.append("Retention is held in %s, apart from trade payables, because it is owed and not "
                   "due. A company preferring a 331 sub-account should set one." % ret_acc)
    if not str(cert.get("pkgNo") or "").strip():
        out.append("This certificate names no package, so the cost lands in the default account "
                   "rather than the trade's own, and nothing ties it to what was bought.")
    if not str(cert.get("discipline") or "").strip():
        out.append("No trade is recorded against this certificate, so a per-trade account map "
                   "cannot be applied to it.")
    if str(cert.get("status") or "").strip().lower() == "paid":
        out.append("This certificate is already marked paid. Posting it books the obligation it "
                   "created; the cash leaving is a separate entry, and it must use the "
                   "'Subcontract settlement' category so it clears this payable instead of "
                   "recognising the cost a second time.")
    return out


# ── what this module will not do ─────────────────────────────────────────────────────────────────

UNPOSTED = (
    "pm_costs. The project cost register is a MANAGEMENT record of the same money these "
    "certificates and the payment requests already carry — on a seeded job its lines are literally "
    "'HVAC subcontract' and 'Panel system supply and install', the same packages. Posting it as "
    "well would count every one of them twice, and a ledger that double-counts is worse than one "
    "that is incomplete: an incomplete ledger is silent, a double-counted one is confidently "
    "wrong. Cost reaches the books through the documents that created the obligation.",
    "The settlement of a certificate. Money leaving the bank is a payment request, with three "
    "approvals and a bank slip; a second route for the same cash would double-count it. Paying a "
    "certificate uses the 'Subcontract settlement' category, which debits the payable this accrual "
    "credited instead of recognising the cost again.",
)
