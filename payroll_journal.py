"""The accounting entries a finalised pay run produces.

Payroll has always ended at the payslip. What the month costs, what is still owed to whom, and what
has to be remitted to the social insurance agency and the tax office were then re-keyed into the
accounts by hand from a PDF — which is where a month's payroll usually goes wrong, and where it is
hardest to notice that it has.

This turns a signed pay run into double-entry lines against the Vietnamese chart of accounts
(Circular 200/2014/TT-BTC), so the accountant posts what was actually signed rather than what was
transcribed.

  334     Phải trả người lao động — payable to employees (the net, until it is paid)
  3382    Kinh phí công đoàn — trade union funds (employer 2%)
  3383    Bảo hiểm xã hội — social insurance (employee 8% + employer 17.5%)
  3384    Bảo hiểm y tế — health insurance (employee 1.5% + employer 3%)
  3386    Bảo hiểm thất nghiệp — unemployment insurance (employee 1% + employer 1%)
  3335    Thuế thu nhập cá nhân — personal income tax withheld
  1388    Phải thu khác — where a manual deduction settles, by default
  642 …   the expense side, by department

Which expense account a department's payroll lands in is a company decision, not something to infer:
site labour usually belongs in 622 or 627, office salaries in 642, sales in 641. The mapping is an
input with a documented default, and any department not in it falls to the default account rather
than being silently dropped.

The invariant that matters is that the entries BALANCE — total debits equal total credits, for every
input, including the awkward ones. That is what the tests spend most of their time on.
"""

# Circular 200/2014/TT-BTC. Overridable, because a company on Circular 133 uses 3385 for
# unemployment insurance rather than 3386, and its own expense accounts besides.
ACC = {
    "net": "334",
    "union": "3382",
    "si": "3383",
    "hi": "3384",
    "ui": "3386",
    "pit": "3335",
    "expense": "642",          # the default expense account when a department is not mapped
    # A manual deduction is withheld from net pay and has to settle SOMEWHERE. Which account is a
    # company decision, like the expense mapping: a staff loan repayment credits back the receivable
    # (1388), an advance recovery credits 141, a fine is another payable. 1388 is the documented
    # default, not a determination — override it per company, or per deduction line via `acct`.
    "deduction": "1388",
}

ACC_NAMES = {
    "334": "Phải trả người lao động / Payable to employees",
    "3382": "Kinh phí công đoàn / Trade union funds",
    "3383": "Bảo hiểm xã hội / Social insurance",
    "3384": "Bảo hiểm y tế / Health insurance",
    "3386": "Bảo hiểm thất nghiệp / Unemployment insurance",
    "3335": "Thuế thu nhập cá nhân / Personal income tax",
    "642": "Chi phí quản lý doanh nghiệp / Administrative expense",
    "641": "Chi phí bán hàng / Selling expense",
    "627": "Chi phí sản xuất chung / Factory overhead",
    "622": "Chi phí nhân công trực tiếp / Direct labour",
    "1388": "Phải thu khác / Other receivables",
    "141": "Tạm ứng / Advances to employees",
    "3388": "Phải trả, phải nộp khác / Other payables",
}


def _n(v):
    try:
        return float(v or 0)
    except (TypeError, ValueError):
        return 0.0


def _line(calc, key):
    return _n((calc or {}).get(key))


def expense_account(dept, dept_accounts=None, default=None):
    """Which expense account a department's payroll belongs in. Unmapped departments fall to the
    default rather than disappearing — a line that vanishes is worse than one posted to review."""
    if dept_accounts:
        for k, v in dept_accounts.items():
            if str(k or "").strip().lower() == str(dept or "").strip().lower():
                return str(v)
    return str(default or ACC["expense"])


def entries(run, dept_accounts=None, accounts=None, default_expense=None):
    """Double-entry lines for one finalised pay run.

    Reads each line's FROZEN `calc` — the payslip as it stood when the Director signed it — so the
    journal describes the run that was approved rather than a recomputation of it.

    The unpaid-leave deduction reduces the salary EXPENSE rather than appearing as a credit: the
    company never incurred it. Posting it as a credit would balance arithmetically and overstate both
    the cost and the liability.
    """
    acc = dict(ACC, **(accounts or {}))
    debits, credits = {}, {}

    def add(book, code, amount):
        if round(amount, 2) == 0:
            return
        book[code] = book.get(code, 0.0) + amount

    for ln in (run.get("lines") or []):
        if not isinstance(ln, dict):
            continue
        c = ln.get("calc") if isinstance(ln.get("calc"), dict) else ln
        gross = _line(c, "grossPay") or _n(ln.get("gross"))
        unpaid = _line(c, "unpaidDeduction")
        er_total = _line(c, "erTotal") or _n(ln.get("erCost")) - gross if ln.get("erCost") else _line(c, "erTotal")
        ex = expense_account(ln.get("dept"), dept_accounts, default_expense or acc["expense"])

        # The cost of employing them this month: what they earned, less any unpaid leave, plus what
        # the company contributes on top.
        add(debits, ex, gross - unpaid + er_total)

        # …and where it goes.
        add(credits, acc["net"], _line(c, "net") or _n(ln.get("net")))
        add(credits, acc["si"], _line(c, "eeBhxh") + _line(c, "erBhxh"))
        add(credits, acc["hi"], _line(c, "eeBhyt") + _line(c, "erBhyt"))
        add(credits, acc["ui"], _line(c, "eeBhtn") + _line(c, "erBhtn"))
        add(credits, acc["union"], _line(c, "erTu"))
        add(credits, acc["pit"], _line(c, "pit") or _n(ln.get("pit")))

        # A manual deduction — a staff loan repayment, an advance recovery, a fine — is withheld from
        # net pay: `net` is already gross − statutory − PIT − unpaid − extraDedTot. The withheld
        # amount had no account here at all, so every month containing one failed `balanced()` by
        # exactly the deduction: the Journal tab showed "these entries do not balance — do not post
        # them", named nothing, and the accountant could not post the month's payroll.
        #
        # Each deduction line may carry its own `acct`; anything unnamed settles to the default.
        _named = 0.0
        for d in (c.get("extraDeduct") or []):
            if not isinstance(d, dict):
                continue
            amt = _n(d.get("amt"))
            if not amt:
                continue
            add(credits, str(d.get("acct") or acc["deduction"]), amt)
            _named += amt
        # `extraDedTot` is what `net` was actually reduced by, so it — not the list — is what has to
        # be credited for the run to balance. Older runs froze the total without the detail; a run
        # whose lines disagree with its total posts the difference here rather than leaving it as an
        # unexplained banner, so the discrepancy is a line somebody can read.
        _tot = _line(c, "extraDedTot")
        if not _tot:
            _tot = _named
        add(credits, acc["deduction"], round(_tot - _named, 2))

    out = []
    for code, amt in sorted(debits.items()):
        out.append({"account": code, "name": ACC_NAMES.get(code, ""), "debit": round(amt, 2),
                    "credit": 0.0})
    for code, amt in sorted(credits.items()):
        out.append({"account": code, "name": ACC_NAMES.get(code, ""), "debit": 0.0,
                    "credit": round(amt, 2)})
    return out


def totals(lines):
    return {"debit": round(sum(l["debit"] for l in lines), 2),
            "credit": round(sum(l["credit"] for l in lines), 2)}


def balanced(lines, tolerance=1.0):
    """Debits equal credits. The tolerance is one dong: every payslip figure is rounded to the dong
    individually, so a thirty-line run can differ from the sum of its parts by a rounding crumb —
    but only a crumb, and anything larger is a real defect rather than arithmetic dust."""
    t = totals(lines)
    return abs(t["debit"] - t["credit"]) <= tolerance


def to_csv(lines, period=""):
    """What the accountant imports. Kept deliberately plain — account, name, debit, credit — because
    every accounting package reads that and none of them agree on anything richer."""
    rows = ["Period,Account,Account name,Debit,Credit"]
    for l in lines:
        name = str(l.get("name") or "").replace('"', '""')
        rows.append('%s,%s,"%s",%.0f,%.0f'
                    % (period, l["account"], name, l["debit"], l["credit"]))
    t = totals(lines)
    rows.append('%s,,"TOTAL",%.0f,%.0f' % (period, t["debit"], t["credit"]))
    return "\n".join(rows)
