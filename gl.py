"""The general ledger — the one place the company's money actually lands.

Every money module in this platform was complete except for its last inch. Payroll computes the
month, refuses to emit an unbalanced journal, blocks a run that would pay somebody twice — and then
hands the entries to a screen. Sales raises an invoice, collects a receipt, tracks retention. A pay
run and an invoice are both, at the end, a set of double-entry lines, and until now nothing kept
them. So the company's real books lived in an accountant's separate file, re-keyed by hand, and no
question that spans two modules — what did this project actually cost, what do we owe in total, is
this month's payroll in the accounts yet — could be answered from the system at all.

This module holds the RULES. It stores nothing (`db.gl_post` does that) and it has no opinion about
who is allowed to post (`app.py` does that). What it owns is the arithmetic that must never bend.

THE FIVE THINGS THAT DO NOT BEND

1. **A batch is the unit.** One source document produces one batch, and a batch posts whole or not
   at all. A half-posted pay run is worse than an unposted one: it balances against nothing, and the
   person who finds it six weeks later cannot tell which half is missing.

2. **It balances exactly, or it is refused.** Not warned about — refused. A ledger that accepts an
   imbalance produces a trial balance that does not balance, and from that moment nobody trusts any
   number in it. See `balance_to()` for the one case where a difference is allowed to exist, and
   what happens to it.

3. **The period comes from the DOCUMENT, not from today.** A January invoice posted in February
   belongs to January. Dating it by the posting run would move revenue between months for no reason
   other than when somebody got round to it.

4. **A closed period refuses postings.** It does not quietly redirect them into the next open month —
   that would misstate two periods instead of one and leave no trace of either.

5. **Nothing is ever edited or deleted.** A wrong posting is corrected by a REVERSAL that points back
   at it, so the mistake and the correction are both visible. This is the same rule the tender
   revisions and the finalised pay run already follow.
"""

# ── The Vietnamese chart of accounts, by class ───────────────────────────────────────────────────
#
# Circular 200/2014/TT-BTC numbers accounts by class, and the FIRST DIGIT decides what an account is
# and which side it normally sits on. That is all a trial balance needs to know; it is not a full
# chart, and it deliberately does not try to be one — a company adds its own sub-accounts (33311,
# 6421) and they classify correctly on their first digit without anybody maintaining a list.
ASSET, LIABILITY, EQUITY, INCOME, EXPENSE, RESULT = (
    "asset", "liability", "equity", "income", "expense", "result")

CLASSES = {
    "1": (ASSET, "Tài sản ngắn hạn / Current assets", "debit"),
    "2": (ASSET, "Tài sản dài hạn / Long-term assets", "debit"),
    "3": (LIABILITY, "Nợ phải trả / Liabilities", "credit"),
    "4": (EQUITY, "Vốn chủ sở hữu / Owner's equity", "credit"),
    "5": (INCOME, "Doanh thu / Revenue", "credit"),
    "6": (EXPENSE, "Chi phí sản xuất, kinh doanh / Operating expenses", "debit"),
    "7": (INCOME, "Thu nhập khác / Other income", "credit"),
    "8": (EXPENSE, "Chi phí khác / Other expenses", "debit"),
    "9": (RESULT, "Xác định kết quả kinh doanh / Determination of results", "debit"),
}

# Where a rounding crumb goes. 811 is "other expenses" and 711 "other income"; a difference of a few
# dong is genuinely one or the other, and putting it in a named account means somebody can see how
# much of it there has been. Silently absorbing it into the largest line would be invisible.
ROUNDING_DEBIT = "811"
ROUNDING_CREDIT = "711"

# The sources that may post. Named rather than free text, so a typo becomes an error instead of a
# fifth kind of document nobody can find again.
PAYRUN, INVOICE, CREDIT_NOTE, RECEIPT, PAYMENT, PURCHASE, MANUAL = (
    "payrun", "invoice", "creditNote", "receipt", "payment", "purchase", "manual")
SOURCES = {
    PAYRUN: "Payroll",
    INVOICE: "Sales invoice",
    CREDIT_NOTE: "Credit note",
    RECEIPT: "Customer receipt",
    PAYMENT: "Payment",
    PURCHASE: "Purchase",
    MANUAL: "Manual journal",
}

POST, REVERSE = "post", "reverse"

# One dong. Every payslip figure is rounded to the dong individually, so a thirty-line run can differ
# from the sum of its parts by arithmetic dust. Larger than this is a defect, not dust.
TOLERANCE = 1.0


class LedgerError(ValueError):
    """A posting that must not happen. Carries a sentence a person can act on, because every one of
    these reaches somebody who is trying to close a month."""


def _n(v):
    try:
        return float(v or 0)
    except (TypeError, ValueError):
        return 0.0


def _r(v):
    return round(_n(v) + 0.0, 2)


# ── Classification ───────────────────────────────────────────────────────────────────────────────

def account_class(code):
    """What kind of account this is, from its first digit. Unknown codes are reported as unknown
    rather than guessed into a class — a mis-classified account silently moves money between the
    balance sheet and the P&L."""
    c = str(code or "").strip()
    return CLASSES.get(c[:1], (None, "Unclassified", "debit"))


def normal_side(code):
    return account_class(code)[2]


def is_pl(code):
    """Does this account belong to the profit and loss rather than the balance sheet?"""
    return account_class(code)[0] in (INCOME, EXPENSE)


# ── Periods ──────────────────────────────────────────────────────────────────────────────────────

def period_of(date_str):
    """`YYYY-MM` from a date. The document's own date decides its period — see rule 3."""
    s = str(date_str or "").strip()
    if len(s) >= 7 and s[4] == "-":
        month = s[5:7]
        if s[:4].isdigit() and month.isdigit() and 1 <= int(month) <= 12:
            return s[:7]
    raise LedgerError(
        "'%s' is not a date this ledger can file. A posting needs a real document date, because the "
        "date decides which month it lands in." % (date_str,))


def period_valid(period):
    try:
        return period_of(str(period or "") + "-01") == str(period or "").strip()
    except LedgerError:
        return False


# ── A batch ──────────────────────────────────────────────────────────────────────────────────────

def normalise(lines):
    """One clean shape for entries arriving from six different modules.

    Each line ends as {account, name, debit, credit}. Two things are refused outright rather than
    tidied, because both mean the caller has computed something it did not intend:

    A line carrying BOTH a debit and a credit. That is two entries wearing one row, and every report
    that groups by account would show the account twice with the halves in the wrong places.

    A NEGATIVE amount. `debit: -500` and `credit: 500` are the same fact, but only one of them
    survives a sum grouped by side. Negative debits are how a ledger comes to have a "total debits"
    figure that is smaller than the largest single debit in it.
    """
    out = []
    for i, ln in enumerate(lines or []):
        if not isinstance(ln, dict):
            raise LedgerError("Entry %d is not a line." % (i + 1))
        code = str(ln.get("account") or "").strip()
        if not code:
            raise LedgerError("Entry %d has no account code. Money cannot post to nowhere." % (i + 1))
        debit, credit = _r(ln.get("debit")), _r(ln.get("credit"))
        if debit < 0 or credit < 0:
            raise LedgerError(
                "Entry %d (account %s) carries a negative amount. A reduction is the other side of "
                "the entry, not a minus sign — post it as the opposite of debit and credit."
                % (i + 1, code))
        if debit and credit:
            raise LedgerError(
                "Entry %d (account %s) is both a debit and a credit. That is two entries in one row."
                % (i + 1, code))
        if not debit and not credit:
            continue        # a zero line carries no information; dropping it is not a loss
        out.append({"account": code,
                    "name": str(ln.get("name") or "").strip(),
                    "debit": debit, "credit": credit,
                    "memo": str(ln.get("memo") or "").strip()})
    return out


def totals(lines):
    return {"debit": _r(sum(_n(l.get("debit")) for l in lines or [])),
            "credit": _r(sum(_n(l.get("credit")) for l in lines or []))}


def difference(lines):
    t = totals(lines)
    return _r(t["debit"] - t["credit"])


def balanced(lines):
    """EXACTLY. Not within a tolerance — see `balance_to`, which is where the tolerance lives and
    where the crumb it forgives becomes a visible line rather than a silent gap."""
    return difference(lines) == 0


def balance_to(lines, debit_account=ROUNDING_DEBIT, credit_account=ROUNDING_CREDIT,
               tolerance=TOLERANCE):
    """Close a rounding crumb with a real line, or refuse.

    `payroll_journal.balanced()` allows one dong of drift because each payslip rounds individually.
    A LEDGER cannot: a trial balance that is one dong out is a trial balance nobody trusts, and the
    difference compounds every month it is tolerated.

    So the crumb is not tolerated — it is POSTED, to 811 or 711, where it is a line somebody can add
    up at year end and ask about. Anything beyond the tolerance is a real defect in the source and is
    refused here rather than smuggled into an expense account, which is exactly how a genuine error
    becomes permanently invisible.
    """
    rows = normalise(lines)
    diff = difference(rows)
    if diff == 0:
        return rows
    if abs(diff) > tolerance:
        raise LedgerError(
            "These entries are out by %s. Debits total %s and credits total %s. A difference this "
            "size is an error in the document, not rounding, so it has not been posted — the source "
            "has to be corrected first."
            % (_fmt(abs(diff)), _fmt(totals(rows)["debit"]), _fmt(totals(rows)["credit"])))
    # Debits exceed credits → the balancing line is a credit, and vice versa.
    if diff > 0:
        rows.append({"account": credit_account, "name": "Chênh lệch làm tròn / Rounding",
                     "debit": 0.0, "credit": abs(diff), "memo": "rounding"})
    else:
        rows.append({"account": debit_account, "name": "Chênh lệch làm tròn / Rounding",
                     "debit": abs(diff), "credit": 0.0, "memo": "rounding"})
    return rows


def _fmt(v):
    return format(int(round(_n(v))), ",")


def batch(source, source_id, date, lines, memo="", actor="", kind=POST, allow_rounding=True):
    """Everything a posting needs, validated, before anything touches the database.

    Deliberately pure: `db.gl_post` does the writing and enforces the things only the database can
    know (is this period closed, has this document already posted). Splitting it that way means the
    rules can be tested exhaustively without a database, and the database cannot be written to
    except through rules that have already run.
    """
    src = str(source or "").strip()
    if src not in SOURCES:
        raise LedgerError("'%s' is not a source this ledger accepts. Known sources: %s."
                          % (src, ", ".join(sorted(SOURCES))))
    sid = str(source_id or "").strip()
    if not sid:
        raise LedgerError("A posting must name the document it came from, or nothing can ever be "
                          "traced back to it.")
    if kind not in (POST, REVERSE):
        raise LedgerError("A batch is either a posting or a reversal.")
    period = period_of(date)
    rows = balance_to(lines) if allow_rounding else normalise(lines)
    if not rows:
        raise LedgerError("There is nothing to post: every line is zero.")
    if not balanced(rows):
        t = totals(rows)
        raise LedgerError("These entries do not balance — debits %s, credits %s."
                          % (_fmt(t["debit"]), _fmt(t["credit"])))
    t = totals(rows)
    return {
        "source": src, "sourceId": sid, "kind": kind,
        "date": str(date).strip()[:10], "period": period,
        "memo": str(memo or "").strip(), "actor": str(actor or "").strip(),
        "lines": rows, "debit": t["debit"], "credit": t["credit"],
        "lineCount": len(rows),
    }


def reversal(posted, date=None, memo=""):
    """The contra of a batch, for correcting a posting that should not have been made.

    Debits become credits and credits become debits — the amounts are NOT negated, for the reason
    `normalise` refuses negatives. The reversal keeps the ORIGINAL period by default: a January
    posting reversed in March is a January correction, and dating it March would leave January
    overstated for ever while March carries a movement that never happened there.
    """
    if not isinstance(posted, dict) or not posted.get("lines"):
        raise LedgerError("There is no batch here to reverse.")
    flipped = [{"account": l["account"], "name": l.get("name", ""),
                "debit": _r(l.get("credit")), "credit": _r(l.get("debit")),
                "memo": "reversal"}
               for l in posted["lines"]]
    return batch(posted["source"], posted["sourceId"],
                 date or posted.get("date") or (posted.get("period", "") + "-01"),
                 flipped,
                 memo=memo or ("Reversal of %s %s" % (SOURCES.get(posted["source"], posted["source"]),
                                                      posted["sourceId"])),
                 actor=posted.get("actor", ""), kind=REVERSE, allow_rounding=False)


# ── The trial balance ────────────────────────────────────────────────────────────────────────────

def trial_balance(rows):
    """Every account, its movements, and the one number that says whether to believe any of it.

    Presented on the account's NORMAL side: an expense account with 10m of debits and 2m of credits
    shows a debit balance of 8m, not both figures, because that is the number that goes on a P&L.
    The gross debit and credit totals are kept too — they are what proves the ledger balances, and
    the net balances alone would not.
    """
    acc = {}
    for r in rows or []:
        code = str(r.get("account") or "").strip()
        if not code:
            continue
        a = acc.setdefault(code, {"account": code, "name": str(r.get("name") or "").strip(),
                                  "debit": 0.0, "credit": 0.0})
        a["debit"] += _n(r.get("debit"))
        a["credit"] += _n(r.get("credit"))
        if not a["name"] and r.get("name"):
            a["name"] = str(r["name"]).strip()

    out = []
    for code in sorted(acc):
        a = acc[code]
        a["debit"], a["credit"] = _r(a["debit"]), _r(a["credit"])
        net = _r(a["debit"] - a["credit"])
        kind, label, side = account_class(code)
        a["class"] = kind
        a["classLabel"] = label
        a["normalSide"] = side
        # The balance, on its normal side. A liability with more debits than credits is a NEGATIVE
        # credit balance and is shown as such rather than flipped to the debit column — an account
        # sitting on the wrong side is a fact worth seeing, not one worth tidying away.
        a["balance"] = net if side == "debit" else _r(-net)
        a["debitBalance"] = net if net > 0 else 0.0
        a["creditBalance"] = _r(-net) if net < 0 else 0.0
        out.append(a)

    t = totals(rows or [])
    return {
        "rows": out,
        "accounts": len(out),
        "debit": t["debit"],
        "credit": t["credit"],
        "difference": _r(t["debit"] - t["credit"]),
        # The whole point of the report. A trial balance that does not balance means something got
        # into the ledger that should not have, and every figure downstream of it is suspect.
        "balanced": _r(t["debit"] - t["credit"]) == 0,
        "debitBalances": _r(sum(a["debitBalance"] for a in out)),
        "creditBalances": _r(sum(a["creditBalance"] for a in out)),
    }


def result(rows):
    """Revenue less expenses over the rows given — the P&L bottom line, with no accruals of its own.

    Kept small on purpose. A real income statement needs a presentation order and comparatives; this
    answers the one question a trial balance cannot ("did we make money this month") and refuses to
    imply more than it knows.
    """
    income = expense = 0.0
    for r in rows or []:
        code = str(r.get("account") or "").strip()
        kind = account_class(code)[0]
        if kind == INCOME:
            income += _n(r.get("credit")) - _n(r.get("debit"))
        elif kind == EXPENSE:
            expense += _n(r.get("debit")) - _n(r.get("credit"))
    return {"income": _r(income), "expense": _r(expense), "profit": _r(income - expense)}
