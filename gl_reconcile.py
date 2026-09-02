"""Do the registers and the books agree, and if not, what is missing from which?

A trial balance is correct about the entries it has and silent about the ones nobody posted, so
"the books are complete" is precisely the claim it cannot make. The unposted list makes that
checkable one document at a time. This asks the same question from the other end: the operational
registers hold an obligation, the ledger holds an account, and the two should state the same money.

Right now exactly one pair can be compared, because exactly one buy-side accrual exists:

    subcontractor certificates  →  trade payables (331) + retention payable (3388)

Driven by hand against a seeded job the two agreed to the dong once every certificate was posted —
which is the point. They agree when nothing is missing, so a difference is not noise: it is a list
of documents, and this returns that list rather than a number somebody has to go and explain.

WHAT IT DOES NOT DO. It never adjusts either side. A reconciliation that quietly writes a balancing
entry is not a reconciliation; it is a way of never finding out. Nor does it treat "equal" as
"correct" — both sides can be wrong together, and the note says so.

Pure: the caller reads the registers and the ledger and hands both in.
"""


def _n(v):
    try:
        return round(float(str(v or 0).replace(",", "").strip()), 2)
    except (TypeError, ValueError):
        return 0.0


def _r(v):
    return round(_n(v), 2)


# A dong. Both sides round to the dong independently, so a difference smaller than this is the
# rounding, not a missing document.
TOLERANCE = 1.0


def subcontract_reconciliation(ctx):
    """The subcontract obligation as the registers state it, against the accounts that carry it.

    ctx: registerNet / registerRetention / registerGross (from qsurvey.subcontract_position),
    ledgerPayable / ledgerRetention / ledgerCost (balances on 331 / 3388 / the cost account),
    unposted (certificates the ledger has not been given, each {label, amount, blocked}),
    reversedOut (certificates posted and then reversed — out of the books and, because gl_batches
    is UNIQUE on (source, source_id, kind), unable to be posted again),
    settledOut (payments recorded against the payable — see the note on why it matters).
    """
    ctx = ctx or {}
    reg_net, reg_ret = _n(ctx.get("registerNet")), _n(ctx.get("registerRetention"))
    reg_gross = _n(ctx.get("registerGross"))
    led_pay, led_ret = _n(ctx.get("ledgerPayable")), _n(ctx.get("ledgerRetention"))
    led_cost = _n(ctx.get("ledgerCost"))
    unposted = list(ctx.get("unposted") or [])
    unposted_total = _r(sum(_n(u.get("amount")) for u in unposted))
    # Posted once, reversed, and — because gl_batches carries a UNIQUE (source, source_id, kind) —
    # unable to be posted again. Out of the books exactly as a never-posted document is, so it
    # explains the same difference; kept apart because the fix is a manual journal and not a click.
    reversed_out = list(ctx.get("reversedOut") or [])
    reversed_total = _r(sum(_n(u.get("amount")) for u in reversed_out))
    missing_total = _r(unposted_total + reversed_total)
    settled = _n(ctx.get("settledOut"))
    warn = []

    def w(code, severity, msg, **extra):
        warn.append(dict({"code": code, "severity": severity, "msg": msg}, **extra))

    # The payable the ledger carries has had settlements taken OUT of it. The register's figure is
    # everything ever certified. Comparing them raw would report every payment the company has made
    # as a discrepancy, which is the fastest way to make a reconciliation ignored.
    led_pay_gross = _r(led_pay + settled)

    rows = [
        {"code": "gross", "label": "Certified to subcontractors, gross",
         "labelVn": "Đã xác nhận cho thầu phụ, tổng",
         "register": reg_gross, "ledger": led_cost, "account": "cost"},
        {"code": "payable", "label": "Owed to subcontractors, net",
         "labelVn": "Nợ thầu phụ, thuần",
         "register": reg_net, "ledger": led_pay_gross, "account": "331"},
        {"code": "retention", "label": "Retention held from subcontractors",
         "labelVn": "Tiền giữ lại của thầu phụ",
         "register": reg_ret, "ledger": led_ret, "account": "3388"},
    ]
    for r in rows:
        r["difference"] = _r(r["register"] - r["ledger"])
        r["agrees"] = abs(r["difference"]) < TOLERANCE

    diff_total = _r(sum(abs(r["difference"]) for r in rows))
    agrees = all(r["agrees"] for r in rows)

    # The difference EXPLAINED. An unexplained gap and a gap that is exactly the documents nobody
    # posted are different findings with different fixes, and reporting them as one number leaves
    # somebody to work out which they have.
    #
    # Compared on the GROSS row, because the unposted documents are carried at their gross. Tested
    # against the payable row it read as unexplained on the first run: an unposted ₫300,000,000
    # certificate moves the payable by ₫285,000,000 and the retention by ₫15,000,000, and comparing
    # a net difference with a gross total is a basis mismatch that reports a healthy month as a
    # discrepancy. The other two rows follow from the same document, since gross = net + retention
    # on both sides.
    gross_row = rows[0]
    explained = (abs(abs(gross_row["difference"]) - missing_total) < TOLERANCE
                 and missing_total > 0)

    if agrees:
        if unposted or reversed_out:
            # Both sides equal AND documents outstanding means the registers are not counting
            # something they should be — the two errors happen to cancel.
            w("agrees_with_documents_outstanding", "high",
              "The registers and the ledger agree, and %d document(s) worth %s are not in the "
              "books. Two figures that match while something is missing from one of them are two "
              "figures that are wrong together."
              % (len(unposted) + len(reversed_out), _vnd(missing_total)))
    elif explained:
        w("difference_is_unposted", "medium",
          "The %s difference is exactly the %d certificate(s) missing from the books. %s"
          % (_vnd(abs(gross_row["difference"])), len(unposted) + len(reversed_out),
             ("Post them and the two sides meet." if not reversed_out else
              "%d were posted and reversed out, and cannot be posted again — those need a manual "
              "journal, not a click." % len(reversed_out))),
          unposted=[u.get("label") for u in unposted][:10],
          reversedOut=[u.get("label") for u in reversed_out][:10])
    else:
        w("difference_unexplained", "high",
          "The registers and the ledger differ by %s, and the %s missing from the books does not "
          "account for it. One side is recording something the other is not."
          % (_vnd(diff_total), _vnd(missing_total)))

    blocked = [u for u in unposted if str(u.get("blocked") or "").strip()]
    if blocked:
        w("documents_cannot_post", "high",
          "%d certificate(s) cannot be posted at all until they are corrected, so this will not "
          "reconcile by posting alone: %s."
          % (len(blocked), "; ".join(str(u.get("label") or "?") for u in blocked[:4])),
          blocked=[u.get("label") for u in blocked][:10])

    return {
        "rows": rows, "agrees": agrees, "differenceTotal": diff_total,
        "unpostedCount": len(unposted), "unpostedTotal": unposted_total,
        "reversedOutCount": len(reversed_out), "reversedOutTotal": reversed_total,
        "reversedOut": [{"label": u.get("label"), "amount": _n(u.get("amount"))}
                        for u in reversed_out],
        "missingTotal": missing_total,
        "unposted": [{"label": u.get("label"), "amount": _n(u.get("amount")),
                      "blocked": u.get("blocked") or ""} for u in unposted],
        "settledOut": settled,
        "warnings": warn,
        "note": "Nothing here is adjusted. A reconciliation that writes a balancing entry is not a "
                "reconciliation, it is a way of never finding out — the difference is returned as "
                "the documents that cause it. And agreement is not proof: both sides can be wrong "
                "together, which is why outstanding documents are reported even when the totals "
                "match.",
    }


def _vnd(n):
    return "₫{:,.0f}".format(_n(n))
