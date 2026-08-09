"""The contract, and the two mechanisms a contractor this size loses money through quietly.

A distributor's order is simple: they ship it, they invoice it, they get paid. A contractor's is not.
Between "the customer accepted the quotation" and "the cash arrived" sit two moving balances that
this portal has never held anywhere, and that live today in somebody's spreadsheet or head:

  TẠM ỨNG — the advance. Typically 30% arrives before any work is done. It is NOT revenue and NOT a
  payment on account: it is money owed back, recovered a slice at a time out of each progress claim
  until the balance reaches zero. Treated as a payment, it silently makes the first claims look paid
  and the final settlement short.

  GIỮ LẠI BẢO HÀNH — retention. Typically 5% of everything certified is withheld by the customer as
  security, and released after the warranty period. It is NOT a discount and NOT unearned: the work
  is done and billed at full value, and part of the payment is held back. Netted off as a discount,
  the contract's value quietly shrinks by 5% and nobody notices until the release is due and there
  is no record of what is owed.

So a progress claim is never just "the work certified this period". It is:

    certified this period
      − advance recovered      (a slice of the tạm ứng, so it winds down as the job progresses)
      − retention withheld     (up to the cap, released later)
      = net payable now

This module holds that arithmetic, which is certain. It deliberately does NOT hold the TAX
treatment, which is not: whether retention is invoiced at acceptance or at warranty end, and whether
an advance triggers a VAT invoice on receipt, are Vietnamese tax questions with real money attached
and no answer this code is entitled to invent. `vat_ready()` refuses, by name, until somebody has
written the answer down. See UNRESOLVED.

Pure — no database, no clock. Exercised by tests/test_sales_contract.py.
"""

# ── how retention comes back ─────────────────────────────────────────────────────────────────────
# The two shapes a Vietnamese construction/M&E contract actually uses. Which one applies is a term
# of the contract, not a property of the world, so it is stored per contract and never defaulted.
REL_WARRANTY_END = "warranty_end"          # the whole 5% at the end of the warranty period
REL_HALF_AT_COMPLETION = "half_at_completion"   # half at practical completion, half at warranty end

RELEASE_RULES = (
    {"code": REL_WARRANTY_END, "label": "All of it at the end of the warranty period",
     "labelVn": "Toàn bộ khi hết thời hạn bảo hành"},
    {"code": REL_HALF_AT_COMPLETION, "label": "Half at practical completion, half at warranty end",
     "labelVn": "Một nửa khi nghiệm thu, một nửa khi hết bảo hành"},
)

# ── how the advance is recovered ─────────────────────────────────────────────────────────────────
REC_PRORATA = "prorata"        # recover the advance % out of every claim, so it clears with the job
REC_FROM_PCT = "from_pct"      # recover nothing until X% complete, then recover faster
REC_MANUAL = "manual"          # the site team decides each time; the balance is still tracked

RECOVERY_RULES = (
    {"code": REC_PRORATA, "label": "A fixed share of every claim",
     "labelVn": "Khấu trừ theo tỷ lệ ở mỗi đợt",
     "note": "The advance clears at the same pace as the work. The usual shape."},
    {"code": REC_FROM_PCT, "label": "Nothing until a set % complete, then recover",
     "labelVn": "Chưa khấu trừ đến khi đạt tỷ lệ, sau đó khấu trừ",
     "note": "Leaves the contractor cash for mobilisation; recovers harder later."},
    {"code": REC_MANUAL, "label": "Decided per claim",
     "labelVn": "Quyết định theo từng đợt",
     "note": "The balance is still tracked and must still reach zero."},
)


def _vnd(n):
    """The statement is a sentence a person signs, so the figures in it are đồng, not floats.

    "277225000.00 payable" is a number nobody can read at a glance and nobody can check against a
    bank advice; ₫277,225,000 is. Whole đồng — the currency has no subunit in practice.
    """
    return "\u20ab{:,.0f}".format(round(_num(n)))


def _num(v):
    try:
        n = float(v)
    except (TypeError, ValueError):
        return 0.0
    return 0.0 if n != n else n


def _pct(v):
    return max(0.0, min(100.0, _num(v)))


def r2(v):
    return round(_num(v) + 0.0, 2)


# ── the terms, normalised ────────────────────────────────────────────────────────────────────────

def terms(c):
    """The commercial terms of a contract, with nothing invented.

    A missing advance or retention percentage is ZERO — that is a real and common contract shape —
    but a missing RULE is not defaulted, because "how is the advance recovered" and "when does
    retention come back" change who owes what and are the contract's to state, not ours.
    """
    c = c or {}
    return {
        "value": r2(c.get("value")),
        "advancePct": _pct(c.get("advancePct")),
        "retentionPct": _pct(c.get("retentionPct")),
        "retentionCapPct": _pct(c.get("retentionCapPct") or c.get("retentionPct")),
        "warrantyMonths": int(_num(c.get("warrantyMonths"))),
        "releaseRule": str(c.get("releaseRule") or "") or None,
        "recoveryRule": str(c.get("recoveryRule") or "") or None,
        "recoveryFromPct": _pct(c.get("recoveryFromPct")),
    }


def advance_amount(c):
    """What the advance is worth on this contract."""
    t = terms(c)
    return r2(t["value"] * t["advancePct"] / 100.0)


def retention_cap(c):
    """The most that will ever be held back. Retention is a percentage of each claim UP TO a ceiling
    — without the ceiling a contract that overruns keeps withholding past what was agreed."""
    t = terms(c)
    return r2(t["value"] * t["retentionCapPct"] / 100.0)


# ── one progress claim ───────────────────────────────────────────────────────────────────────────

def application(c, certified_this, state=None):
    """What is actually payable on this claim, and what the running balances become.

    `state` carries where the contract had got to: certifiedToDate, advanceOutstanding,
    retentionHeld. Everything is derived from those and never from a stored "net" that could drift.

    Refuses rather than guesses when a rule is missing: a claim computed on an invented recovery
    rule is a number somebody signs and the customer disputes.
    """
    t = terms(c)
    st = state or {}
    certified_prev = r2(st.get("certifiedToDate"))
    adv_out = r2(st.get("advanceOutstanding", advance_amount(c)))
    ret_held = r2(st.get("retentionHeld"))
    this = r2(certified_this)

    if this < 0:
        return {"ok": False, "why": "A negative certification is a credit note, not a claim."}
    if t["value"] and certified_prev + this - t["value"] > 0.005:
        return {"ok": False,
                "why": "Certifying %.2f would take the contract to %.2f against a value of %.2f. "
                       "Raise a variation first, or certify less."
                       % (this, certified_prev + this, t["value"])}
    if t["advancePct"] and not t["recoveryRule"]:
        return {"ok": False, "why": "This contract has a %.4g%% advance but no recovery rule. How "
                                    "the advance winds down is a term of the contract, not "
                                    "something the portal may choose." % t["advancePct"]}
    if t["retentionPct"] and not t["releaseRule"]:
        return {"ok": False, "why": "This contract withholds %.4g%% retention but does not say when "
                                    "it comes back. That is a term of the contract."
                                    % t["retentionPct"]}

    # Retention: a share of THIS claim, never taking the total past the cap.
    cap = retention_cap(c)
    ret_this = r2(this * t["retentionPct"] / 100.0)
    if ret_held + ret_this > cap:
        ret_this = r2(max(0.0, cap - ret_held))

    # Advance recovery: a share of this claim, never more than is still outstanding.
    pct_complete = (certified_prev + this) / t["value"] * 100.0 if t["value"] else 0.0
    if t["recoveryRule"] == REC_PRORATA:
        rec = r2(this * t["advancePct"] / 100.0)
    elif t["recoveryRule"] == REC_FROM_PCT:
        rec = r2(this * t["advancePct"] / 100.0) if pct_complete >= t["recoveryFromPct"] else 0.0
    else:                                   # manual — the caller says, the balance still binds
        rec = r2(st.get("recoverNow"))
    rec = r2(min(rec, adv_out))
    if rec < 0:
        return {"ok": False, "why": "A negative advance recovery would increase the advance."}

    net = r2(this - rec - ret_this)
    # A claim whose deductions exceed it is arithmetic nobody meant, and paying a negative is not a
    # thing that happens — it means the recovery rule and the claim size disagree.
    if net < -0.005:
        return {"ok": False,
                "why": "Deductions (%.2f recovery + %.2f retention) exceed the %.2f certified. "
                       "Reduce the recovery on this claim." % (rec, ret_this, this)}

    return {
        "ok": True,
        "certifiedThis": this,
        "certifiedToDate": r2(certified_prev + this),
        "advanceRecovered": rec,
        "advanceOutstanding": r2(adv_out - rec),
        "retentionThis": ret_this,
        "retentionHeld": r2(ret_held + ret_this),
        "retentionCap": cap,
        "netPayable": r2(max(0.0, net)),
        "pctComplete": round(pct_complete, 2),
        "statement": "%s certified, less %s advance recovery and %s retention = %s payable."
                     % (_vnd(this), _vnd(rec), _vnd(ret_this), _vnd(max(0.0, net))),
        # Stated, never assumed: this is the commercial arithmetic only.
        "taxNote": "Amounts are exclusive of VAT. What is invoiced, and when, depends on the tax "
                   "treatment of the advance and of retention — see vat_ready().",
    }


def final_settlement(c, state=None):
    """What is left at the end: the retention still held, and any advance never recovered.

    An advance that never cleared is money the customer has already paid for work; leaving it out of
    the closing statement is how it is quietly written off.
    """
    t = terms(c)
    st = state or {}
    adv_out = r2(st.get("advanceOutstanding", advance_amount(c)))
    ret_held = r2(st.get("retentionHeld"))
    certified = r2(st.get("certifiedToDate"))
    issues = []
    if adv_out > 0.005:
        issues.append("%s of the advance was never recovered — it is owed back." % _vnd(adv_out))
    if t["value"] and abs(certified - t["value"]) > 0.005:
        issues.append("%s certified against a contract value of %s." % (_vnd(certified), _vnd(t["value"])))
    return {
        "retentionToRelease": ret_held, "advanceOutstanding": adv_out,
        "certifiedToDate": certified, "contractValue": t["value"],
        "releaseRule": t["releaseRule"], "warrantyMonths": t["warrantyMonths"],
        "clean": not issues, "issues": issues,
        "why": "Retention of %s to release%s." % (_vnd(ret_held), "" if not issues else "; " + " ".join(issues)),
    }



# ── when the retention actually comes back ───────────────────────────────────────────────────────
# The single most-forgotten receivable a contractor has. It is withheld a slice at a time over a
# year of claims, and then falls due once, quietly, twelve months after everybody stopped thinking
# about the job. Nothing chases it, because nothing knows when it is due.

INDETERMINATE = "indeterminate"


def _add_months(iso, months):
    """The same day, n months on — clamped to the end of a shorter month.

    31 January + 1 month is 28 February, not 3 March. A warranty that ends on a date that does not
    exist has to land somewhere, and landing early would make a release look due before it is.
    """
    try:
        y, m, d = (int(x) for x in str(iso)[:10].split("-"))
    except (ValueError, TypeError):
        return ""
    m0 = (m - 1) + int(months or 0)
    y2, m2 = y + m0 // 12, m0 % 12 + 1
    last = [31, 29 if (y2 % 4 == 0 and (y2 % 100 != 0 or y2 % 400 == 0)) else 28,
            31, 30, 31, 30, 31, 31, 30, 31, 30, 31][m2 - 1]
    return "%04d-%02d-%02d" % (y2, m2, min(d, last))


def retention_release(c, state=None, today=""):
    """When each slice of the retention falls due, and how much of it is still being held.

    Refuses rather than guesses, in two places that matter:

      · with no release rule, nothing can be said — that is a term of the contract.
      · with no ACCEPTANCE DATE, the clock has not started. A warranty period runs from the works
        being accepted, not from the contract being signed or the last claim being certified, and
        computing a due date off any of those would put a real receivable on a wrong day. The
        honest output is "record the acceptance date", not a date nobody agreed to.
    """
    t = terms(c)
    st = state or {}
    held = r2(st.get("retentionHeld", (c or {}).get("retentionHeld")))
    released = r2(st.get("retentionReleased", (c or {}).get("retentionReleased")))
    outstanding = r2(max(0.0, held - released))
    accepted = str((c or {}).get("acceptedOn") or "")[:10]
    out = {"retentionHeld": held, "retentionReleased": released, "outstanding": outstanding,
           "acceptedOn": accepted, "releaseRule": t["releaseRule"],
           "warrantyMonths": t["warrantyMonths"], "tranches": [], "dueNow": 0.0, "status": "ok"}
    if outstanding <= 0.005:
        out["why"] = "No retention is being held on this contract."
        return out
    if not t["releaseRule"]:
        out["status"] = INDETERMINATE
        out["why"] = ("%s is being held and the contract does not say when it comes back. Record "
                      "the release rule." % _vnd(outstanding))
        return out
    if not accepted:
        out["status"] = INDETERMINATE
        out["why"] = ("%s is being held, but the warranty clock starts at ACCEPTANCE and no "
                      "acceptance date is recorded. Nothing is due until the works were accepted — "
                      "record the date rather than dating this off the contract or the last claim."
                      % _vnd(outstanding))
        return out

    if t["releaseRule"] == REL_HALF_AT_COMPLETION:
        parts = [("At practical completion", accepted, r2(held / 2.0)),
                 ("At the end of the warranty period",
                  _add_months(accepted, t["warrantyMonths"]), r2(held - r2(held / 2.0)))]
    else:
        parts = [("At the end of the warranty period",
                  _add_months(accepted, t["warrantyMonths"]), held)]

    # Releases are applied to the earliest tranche first: the customer pays back in order, and
    # spreading a part-release evenly would make a later tranche look partly settled before its
    # own date and hide the fact that the first one is short.
    left = released
    cutoff = str(today or "")[:10]
    for label, due, amount in parts:
        applied = min(left, amount)
        left = r2(left - applied)
        still = r2(amount - applied)
        overdue = bool(cutoff and due and due < cutoff and still > 0.005)
        out["tranches"].append({"label": label, "dueOn": due, "amount": amount,
                                "released": applied, "outstanding": still, "overdue": overdue,
                                "due": bool(cutoff and due and due <= cutoff and still > 0.005)})
    out["dueNow"] = r2(sum(x["outstanding"] for x in out["tranches"] if x["due"]))
    out["why"] = ("%s of retention outstanding; %s of it is due back now."
                  % (_vnd(outstanding), _vnd(out["dueNow"])))
    return out


# ── the part this module refuses to compute ─────────────────────────────────────────────────────

TAX_KEYS = ("retentionTaxPoint", "advanceTaxPoint")


def vat_ready(c, company_settings=None):
    """Can a VAT figure be stated for this contract? Usually not, and it says exactly why.

    Two Vietnamese tax questions decide it, both with real money attached and neither answerable
    from the data the portal holds:

      · is the retained 5% invoiced at acceptance with the rest of the value, or only when it is
        released at the end of the warranty period?
      · does an advance arriving before any acceptance trigger a VAT invoice on receipt, or is it
        only a cash record until work is certified?

    Guessing either one produces a confident, wrong number on a document that goes to a customer and
    into a tax return. So the computation REFUSES and names the missing answer, in the same shape as
    the working-time module: an unsettled rule is data somebody must supply, never a default.
    """
    src = dict(company_settings or {})
    src.update({k: v for k, v in (c or {}).items() if k in TAX_KEYS and v})
    missing = [k for k in TAX_KEYS if not str(src.get(k) or "").strip()]
    labels = {"retentionTaxPoint": "when retention is invoiced (at acceptance, or at release)",
              "advanceTaxPoint": "whether an advance triggers a VAT invoice on receipt"}
    return {
        "ready": not missing,
        "missing": [{"key": k, "question": labels[k]} for k in missing],
        "why": ("The tax treatment is recorded, so a VAT figure can be stated." if not missing else
                "No VAT figure can be stated for this contract until somebody records " +
                " and ".join(labels[k] for k in missing) +
                ". These are tax questions with money attached; the portal must not choose them."),
        "whoDecides": "Your accountant, in writing. Record it in Company settings so every contract "
                      "inherits it, or on the contract where it differs.",
    }


UNRESOLVED = (
    {"topic": "The retention tax point",
     "question": "Is the retained 5% invoiced at acceptance with the rest of the value, or only when "
                 "it is released at the end of the warranty period?",
     "why_it_matters": "It moves VAT on 5% of every contract, and by up to a year.",
     "action": "Blocks any VAT figure on a contract until recorded. vat_ready() names it."},
    {"topic": "VAT on an advance",
     "question": "Does a 30% tạm ứng arriving before any acceptance trigger a VAT invoice on "
                 "receipt, or is it a cash record until work is certified?",
     "why_it_matters": "It is the first document raised on nearly every contract.",
     "action": "Same. Recorded per company, overridable per contract."},
    {"topic": "Whether unrecovered advance is written off or chased",
     "question": "At final settlement, an advance that never cleared is money already paid for work "
                 "not done.",
     "why_it_matters": "It is invisible today, which is how it gets written off by accident.",
     "action": "final_settlement() reports it as an issue rather than netting it away silently."},
)
