"""The supplier as one record with one identity — and the bank account that identity owns.

The customer side already has this (`account.py`): a record per legal entity, a tax code, duplicate
detection, and a merge that leaves a tombstone. The buy side has nothing. A payment request carries
`payeeCompany`, `payeeMst`, `bankName`, `bankAcc`, `bankHolder` and `bankBranch` as FREE TEXT, typed
again on every single payment. Two consequences, and the second is the reason this could not wait:

**"How much have we paid this supplier" has no answer.** Not a hard one — no answer at all. "Acme
Co" and "Acme Co." are two suppliers forever, and now that payments post to the ledger, cost cannot
be attributed to a counterparty either.

**Nothing compares this payment's bank account to the one used last time.** Invoice-redirection
fraud — an email saying "our bank details have changed", often from a genuine but compromised
mailbox — is among the most common frauds against a company this size, and the whole defence is
being able to notice. A supplier master holds the account that has been paid before; a payment
naming a different one is a question somebody has to answer BEFORE the money leaves, not a
discovery afterwards.

WHAT THIS REUSES RATHER THAN REBUILDS
=====================================
Identity is identity: `account.fold_name`, `normalise_mst`, `check_mst`, `duplicate_groups` and
`resolve_name` are imported, not copied. A second implementation of "are these the same company"
would drift from the first, and this codebase has already paid for that once — the tender revision
diff and its on-screen twin were keyed differently and disagreed about what a price change was.

WHAT IS GENUINELY DIFFERENT ABOUT A SUPPLIER
============================================
A customer is identified so documents can be linked. A supplier is identified so MONEY CAN BE SENT,
which puts the bank account inside the identity rather than beside it — see `bank_key` and
`bank_verdict`.
"""

import account

# Re-exported so a caller never has to decide which module's copy to use. There is one.
fold_name = account.fold_name
normalise_mst = account.normalise_mst
check_mst = account.check_mst
resolve_name = account.resolve_name
duplicate_groups = account.duplicate_groups

# Where a supplier's name and bank details are typed today, on every payment.
PAY_FIELDS = ("payeeCompany", "payeeMst", "bankName", "bankAcc", "bankHolder", "bankBranch")

# The verdicts `bank_verdict` returns. Named so a caller cannot invent a sixth by typo.
FIRST_TIME = "first"        # no account on file yet — this one becomes the known account
MATCHES = "matches"         # the same account as last time
CHANGED = "changed"         # a DIFFERENT account: the one that has to be asked about
INCOMPLETE = "incomplete"   # the payment carries no account to compare
UNKNOWN_SUPPLIER = "unknown"


def _s(v):
    return str(v or "").strip()


def digits(v):
    """Just the digits. Bank accounts are written '0123 4567 8901', '0123-4567-8901' and
    '0123456789 01' by three different people meaning the same account."""
    return "".join(c for c in _s(v) if c.isdigit())


def bank_key(rec):
    """The identity of a bank account: the number's digits plus the folded bank name.

    The NUMBER alone is not enough — the same digits at two banks are two accounts — and the name
    alone is obviously not enough. The holder name is deliberately NOT part of the key: it is
    frequently abbreviated, transliterated or typed in a different case, and a key that changes when
    somebody writes "CTY TNHH" instead of "CONG TY TNHH" would cry wolf on every second payment,
    which is how a real warning gets ignored.
    """
    acc = digits(rec.get("bankAcc"))
    if not acc:
        return ""
    return acc + "@" + (fold_name(rec.get("bankName")) or "?")


def bank_verdict(supplier, payment):
    """Is this payment going to the account this supplier is known by?

    Returns {status, known, offered, message}. It NEVER blocks: the answer belongs to a person who
    can ring the supplier on a number they already had, and a system that refuses would just be
    worked around. What it must do is make the change impossible to miss.
    """
    offered = bank_key(payment or {})
    if not supplier:
        return {"status": UNKNOWN_SUPPLIER, "known": "", "offered": offered,
                "message": "This payment is not linked to a supplier record, so its bank account "
                           "cannot be compared with anything. Link it to a supplier first."}
    known = bank_key(supplier or {})
    if not offered:
        return {"status": INCOMPLETE, "known": known, "offered": "",
                "message": "This payment carries no bank account, so there is nothing to compare."}
    if not known:
        return {"status": FIRST_TIME, "known": "", "offered": offered,
                "message": "First payment to this supplier: %s at %s becomes the account on file. "
                           "Check it against something the supplier gave you directly — not against "
                           "the email that asked for it."
                           % (_s(payment.get("bankAcc")), _s(payment.get("bankName")) or "?")}
    if known == offered:
        return {"status": MATCHES, "known": known, "offered": offered,
                "message": "Same account as last time."}
    return {"status": CHANGED, "known": known, "offered": offered,
            "message": "THE BANK ACCOUNT HAS CHANGED. On file: %s at %s. On this payment: %s at %s. "
                       "A changed account is the shape of invoice-redirection fraud — confirm it by "
                       "ringing a number you already had for this supplier, never one from the "
                       "email or the invoice that asked for the change."
                       % (_s(supplier.get("bankAcc")), _s(supplier.get("bankName")) or "?",
                          _s(payment.get("bankAcc")), _s(payment.get("bankName")) or "?")}


def from_payment(payment):
    """The supplier record a payment is implicitly describing — what a backfill would create."""
    return {
        "name": _s(payment.get("payeeCompany")) or _s(payment.get("payee")),
        "mst": normalise_mst(payment.get("payeeMst")),
        "bankName": _s(payment.get("bankName")),
        "bankAcc": _s(payment.get("bankAcc")),
        "bankHolder": _s(payment.get("bankHolder")),
        "bankBranch": _s(payment.get("bankBranch")),
    }


def backfill_plan(payments, suppliers):
    """What linking the existing payments to supplier records would do, before it does it.

    Three buckets, and the middle one is the point: a name that resolves to exactly one supplier is
    linked, a name that matches nothing becomes a proposed new record, and a name that could be two
    suppliers is left ALONE with its candidates listed. Replacing free text with a confident wrong
    join is worse than the free text — the free text at least looks uncertain.
    """
    link, create, ambiguous = [], {}, []
    for p in (payments or []):
        if _s(p.get("supplierId")):
            continue
        name = _s(p.get("payeeCompany")) or _s(p.get("payee"))
        if not name:
            continue
        r = resolve_name(name, suppliers)
        if r["status"] in ("exact", "folded") and r.get("accountId"):
            link.append({"paymentId": p.get("id"), "reqNo": p.get("reqNo"),
                         "name": name, "supplierId": r["accountId"]})
        elif r["status"] == "ambiguous":
            ambiguous.append({"paymentId": p.get("id"), "reqNo": p.get("reqNo"),
                              "name": name, "candidates": r.get("candidates") or []})
        else:
            key = fold_name(name) or name
            prev = create.get(key)
            if prev is None:
                create[key] = dict(from_payment(p), payments=1)
            else:
                prev["payments"] += 1
                # Keep the first bank details seen, but notice when the payments disagree — that is
                # either two suppliers wearing one name, or an account that changed at some point.
                if bank_key(from_payment(p)) and bank_key(prev) and \
                        bank_key(from_payment(p)) != bank_key(prev):
                    prev["bankConflict"] = True
    return {"link": link,
            "create": sorted(create.values(), key=lambda c: -c["payments"]),
            "ambiguous": ambiguous,
            "counts": {"link": len(link), "create": len(create), "ambiguous": len(ambiguous)}}


def spend_by_supplier(payments, suppliers, statuses=("paid",)):
    """What each supplier has actually been paid — the question that had no answer.

    Counts only the statuses asked for; `paid` by default, because an approved request is a
    commitment and not money that has left. Payments with no supplier link are returned separately
    rather than dropped, so the total on screen can never quietly exclude them.
    """
    by_id = {s.get("id"): s for s in (suppliers or []) if s.get("id")}
    rows, unlinked, unlinked_total = {}, 0, 0.0
    want = {str(s).strip().lower() for s in statuses}
    for p in (payments or []):
        if str(p.get("status") or "").strip().lower() not in want:
            continue
        try:
            amt = float(p.get("amount") or 0)
        except (TypeError, ValueError):
            amt = 0.0
        sid = _s(p.get("supplierId"))
        if not sid or sid not in by_id:
            unlinked += 1
            unlinked_total += amt
            continue
        r = rows.setdefault(sid, {"supplierId": sid, "name": by_id[sid].get("name") or "",
                                  "mst": by_id[sid].get("mst") or "", "payments": 0, "total": 0.0})
        r["payments"] += 1
        r["total"] += amt
    for r in rows.values():
        r["total"] = round(r["total"], 2)
    return {"rows": sorted(rows.values(), key=lambda r: -r["total"]),
            "unlinkedPayments": unlinked,
            "unlinkedTotal": round(unlinked_total, 2),
            # Stated rather than implied: a spend report that silently omits a third of the payments
            # is worse than one that says it is incomplete.
            "complete": unlinked == 0}
