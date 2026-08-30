"""The credit note (giấy báo có / A/R credit memo) — the other document this codebase names and
never had.

    sales_doc.apply:               "A negative claim is a credit note, not a claim."
    sales_contract.application:    "A negative certification is a credit note, not a claim."
    sales_variation.effect:        "raise a credit note against the claim instead."

Three refusals, one destination, and until now the destination did not exist. `doc_number` even
reserved the CN series for it.

WHY IT CANNOT JUST BE A NEGATIVE CLAIM. A progress claim moves four balances at once — certified to
date, the advance recovered out of it, the retention withheld from it, and the net payable. Undoing
it by typing a minus sign moves only the first, and the other three silently drift: retention stays
withheld on work that was credited back, and the advance shows as recovered out of money the
customer no longer owes. Six months later the final account is short and nobody can say why.

So a credit REVERSES PROPORTIONALLY. Credit half a claim and half its retention comes back out of
the held balance, half its advance recovery goes back onto the outstanding advance, and the
customer's balance falls by what is actually left. That is the only version of this that keeps the
final account reconcilable.

WHAT IT IS NOT. It is not a variation: a variation changes what was AGREED, a credit note changes
what was CERTIFIED. And it is not a VAT credit memo — issuing the legal document remains the
e-invoice provider's, under Decree 123/2020 and Circular 78/2021. This records the commercial
credit and the number of the provider's document against it, exactly as the invoice path does.

Pure — no database, no clock. Exercised by tests/test_sales_credit.py.
"""

import sales_doc

DRAFT = sales_doc.DRAFT
ISSUED = sales_doc.ISSUED
APPLIED = "applied"
CANCELLED = sales_doc.CANCELLED

TRANSITIONS = {
    DRAFT: (ISSUED, CANCELLED),
    ISSUED: (APPLIED, CANCELLED),
    APPLIED: (),
    CANCELLED: (),
}

STATUS_LABELS = {
    DRAFT: ("Draft", "Nháp"),
    ISSUED: ("Issued", "Đã phát hành"),
    APPLIED: ("Applied", "Đã áp dụng"),
    CANCELLED: ("Cancelled", "Đã hủy"),
}

# Why a credit is being raised. Recorded because "we credited ₫40,000,000" and "we credited
# ₫40,000,000 because the client rejected the coil section" are different facts at an audit, and
# only the second one prevents it happening again.
REASONS = (
    {"code": "over_certified", "label": "Over-certified in error",
     "labelVn": "Nghiệm thu nhầm vượt giá trị"},
    {"code": "rejected_work", "label": "Work rejected or not accepted",
     "labelVn": "Công việc bị từ chối / không được nghiệm thu"},
    {"code": "descoped", "label": "Scope removed after certification",
     "labelVn": "Cắt giảm phạm vi sau khi đã nghiệm thu"},
    {"code": "pricing", "label": "Pricing corrected", "labelVn": "Điều chỉnh đơn giá"},
    {"code": "goodwill", "label": "Commercial settlement", "labelVn": "Thỏa thuận thương mại"},
)
REASON_CODES = tuple(r["code"] for r in REASONS)


def _num(v):
    try:
        n = float(v)
    except (TypeError, ValueError):
        return 0.0
    return 0.0 if n != n else n


def r2(v):
    return round(_num(v), 2)


def _vnd(n):
    return "₫{:,.0f}".format(round(_num(n)))


def creditable(application):
    """What is left to credit on a claim: what it certified, less what has already been credited."""
    a = application or {}
    return r2(max(0.0, _num(a.get("certifiedThis")) - _num(a.get("creditedAmt"))))


def effect(application, amount):
    """What crediting `amount` off this claim does to every balance it touched.

    Everything is pro rata to the credited fraction, because that is the only apportionment that
    leaves the final account reconcilable. Reversing the certified value while leaving the retention
    and the advance recovery alone is the shape that silently loses money.
    """
    a = application or {}
    certified = r2(a.get("certifiedThis"))
    want = r2(amount)
    left = creditable(a)
    out = {"ok": True, "credit": want, "certifiedThis": certified, "alreadyCredited": r2(a.get("creditedAmt")),
           "creditable": left}
    if (a.get("status") or "") != "certified":
        out.update({"ok": False, "why": "A credit note is raised against a CERTIFIED claim — there "
                                        "is nothing to credit on one that was never signed off."})
        return out
    if want <= 0:
        out.update({"ok": False, "why": "A credit note is for a positive amount. It is already a "
                                        "reduction; a negative one would be a claim."})
        return out
    # BEFORE the creditable check, not after. A claim that certified nothing has nothing left to
    # credit either, so the order decides which reason the user is given — and "already credited in
    # full" would be a confident, wrong explanation of a claim that was never worth anything.
    if certified <= 0:
        out.update({"ok": False, "why": "This claim certified nothing, so there is nothing to credit."})
        return out
    if want - left > 0.005:
        out.update({"ok": False,
                    "why": ("Crediting %s against %s still creditable on this claim."
                            % (_vnd(want), _vnd(left)) if left > 0.005 else
                            "This claim has already been credited in full.")})
        return out

    share = want / certified
    ret_back = r2(_num(a.get("retentionThis")) * share)
    adv_back = r2(_num(a.get("advanceRecovered")) * share)
    net = r2(want - ret_back - adv_back)
    out.update({
        "share": round(share, 6),
        "retentionReleased": ret_back,      # withheld on work now credited — comes back out
        "advanceRestored": adv_back,        # recovered out of money no longer owed — goes back on
        "netCredit": net,                   # what the customer's balance actually falls by
        "statement": "%s credited off %s certified; %s of retention released and %s of advance "
                     "recovery restored, so the customer owes %s less."
                     % (_vnd(want), _vnd(certified), _vnd(ret_back), _vnd(adv_back), _vnd(net)),
    })
    return out


def apply_to(contract, application, amount):
    """The contract and the claim as they stand after the credit — new dicts, never mutated.

    The caller writes the contract under compare-and-swap; a credit that moved the claim but not the
    contract would leave the two disagreeing about how much has been certified, which is the exact
    drift this document exists to prevent.
    """
    e = effect(application, amount)
    if not e["ok"]:
        return e
    c = dict(contract or {})
    a = dict(application or {})
    c["certifiedToDate"] = r2(_num(c.get("certifiedToDate")) - e["credit"])
    c["retentionHeld"] = r2(max(0.0, _num(c.get("retentionHeld")) - e["retentionReleased"]))
    c["advanceOutstanding"] = r2(_num(c.get("advanceOutstanding")) + e["advanceRestored"])
    if c["certifiedToDate"] < -0.005:
        return {"ok": False, "why": "That would take the contract's certified total below zero."}

    # The lines the claim consumed give the credit back proportionally, so each line's open balance
    # is right again and the work can be re-certified if it is redone.
    claims = {str(k): _num(v) for k, v in (a.get("claims") or {}).items()}
    lines, share = [], e["share"]
    for ln in (c.get("lines") or []):
        ln = dict(ln)
        was = claims.get(str(ln.get("uid")), 0.0)
        if was:
            ln["certifiedAmt"] = r2(max(0.0, _num(ln.get("certifiedAmt")) - r2(was * share)))
        lines.append(ln)
    c["lines"] = lines

    a["creditedAmt"] = r2(_num(a.get("creditedAmt")) + e["credit"])
    a["netPayable"] = r2(max(0.0, _num(a.get("netPayable")) - e["netCredit"]))
    a["fullyCredited"] = a["creditedAmt"] >= r2(a.get("certifiedThis")) - 0.005
    e.update({"contract": c, "application": a})
    return e


UNRESOLVED = (
    {"topic": "Whether a credit note reverses the VAT already invoiced",
     "question": "If the original claim was invoiced with VAT, crediting it normally requires the "
                 "provider to issue an adjustment invoice under Decree 123/2020 Art. 19.",
     "why_it_matters": "The commercial credit and the tax credit are two documents, and only one "
                       "of them is this portal's.",
     "action": "The credit records the provider's adjustment-invoice number the same way the "
               "original records its ký hiệu and số. Nothing here issues one."},
)
