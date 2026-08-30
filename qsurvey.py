"""Quantity surveying: what has actually been built, and what it is worth at contract rates.

The portal already holds the two ends of a contractor's money. `est_*` holds what we said the job
would cost when we bid it. `sales_*` holds the contract, the advance, the retention and the cash.
Between them sits the question neither can answer and that a contractor lives or dies by:

    HOW MUCH OF THE JOB IS BUILT THIS MONTH, AND WHAT IS THAT WORTH?

Today that answer lives in a spreadsheet on a quantity surveyor's laptop. The payment application
that goes to the client is typed from it, the cost report to the directors is typed from it, and
nothing checks that the two agree or that either agrees with the contract. This module holds it.

WHAT THIS MODULE IS FOR, AND WHAT IT REFUSES TO BE
--------------------------------------------------
It computes the VALUATION — the gross value of work done to a cut-off date:

    measured works (bill of quantities, at contract rates)
  + agreed variations
  + approved daywork
  + materials on site, not yet built in
  = gross valuation to date
  - gross valuation at the previous cut-off
  = valued this period

It deliberately stops there. Retention and advance recovery are NOT computed here — they are
computed by `sales_contract.application()`, which already holds them, already refuses when a
contract does not state its rules, and is already tested. A second implementation of retention
arithmetic in this file would be a second answer to a question that must have exactly one; the
first month the two disagreed, nobody would know which certificate was right. The valuation figure
this module produces is the `certified_this` that module takes. That is the whole join.

THE RULES THAT DO NOT BEND
--------------------------
1.  A RATE THAT DOES NOT EXIST IS NOT ZERO. An unpriced bill item is reported as unpriced and
    excluded from the total, by name. Pricing it at nil is how a real bill line silently leaves a
    payment application, and the client never asks why they were undercharged.

2.  OVER-MEASUREMENT IS REPORTED, NEVER CLAMPED. Measuring 120 m3 against a billed 100 m3 is either
    a genuine remeasure or a take-off error. Clamping to 100 makes the second one invisible and the
    first one wrong. Both are surfaced; neither is silently corrected.

3.  ONLY AGREED VARIATIONS ARE VALUED. Work instructed but not yet priced or agreed is real
    exposure and is reported as exposure — it is not put in a figure a director signs and a client
    disputes. The same for daywork that has not been signed by the client's representative.

4.  MATERIALS ON SITE LEAVE THE VALUATION WHEN THEY ARE BUILT IN. A pump paid for as material on
    site in March and measured into the works in April is claimed twice unless it drops out. The
    incorporation date does that, and this is the single most common double-count in the trade.

5.  A SUBMITTED VALUATION IS A SNAPSHOT. Once a valuation has left the building, recomputing it
    from today's registers would quietly rewrite what was claimed. Submitted valuations carry their
    own totals and this module reads those, never the live registers.

6.  THE CUT-OFF IS A DATE, NOT "EVERYTHING IN THE REGISTER". A measurement recorded on the 3rd of
    next month against last month's cut-off belongs to next month's valuation.

NOT HANDLED, AND SAID SO RATHER THAN GUESSED
--------------------------------------------
*   Price fluctuation / rise-and-fall formulae. A contract that has them needs its own index series
    and its own base date; inventing one would move real money.
*   VAT. See `sales_contract.vat_ready()`, which refuses for stated reasons.
*   Retention release timing — `sales_contract.retention_release()` holds it.

Pure: no database, no clock, no HTTP. Every date arrives as an ISO string from the caller.
Exercised by tests/test_qs.py.
"""

# ── bill of quantities: what a line IS ───────────────────────────────────────────────────────────
# A bill is not a flat list of priced rows, and treating it as one is the first thing that goes
# wrong. A heading carries no value and must never reach a total. A provisional sum is IN the
# contract value but the work behind it is undefined, so it is expended and adjusted, not measured
# against like an ordinary rate. A prime cost sum behaves the same way.
ITEM = "item"                 # measured work at a rate — the ordinary case
PROVISIONAL = "provisional"   # a sum in the contract for work not yet defined
PC_SUM = "pcsum"              # prime cost — a nominated supply, adjusted against the actual
HEADING = "heading"           # a section title; no quantity, no rate, no value
NOTE = "note"                 # commentary; no value

MEASURED_KINDS = (ITEM,)                      # the kinds valued by quantity x rate
SUM_KINDS = (PROVISIONAL, PC_SUM)             # the kinds valued by expenditure against a sum
VALUED_KINDS = MEASURED_KINDS + SUM_KINDS     # everything that can reach a total
UNVALUED_KINDS = (HEADING, NOTE)

BOQ_KINDS = (
    {"code": ITEM, "label": "Measured item", "labelVn": "Hạng mục đo bóc",
     "note": "Quantity x rate. The ordinary bill line."},
    {"code": PROVISIONAL, "label": "Provisional sum", "labelVn": "Tạm tính",
     "note": "In the contract sum, but the work is not yet defined. Expended and adjusted."},
    {"code": PC_SUM, "label": "Prime cost sum", "labelVn": "Chi phí chỉ định",
     "note": "A nominated supply. Adjusted against what it actually cost."},
    {"code": HEADING, "label": "Section heading", "labelVn": "Tiêu đề",
     "note": "Carries no value and never reaches a total."},
    {"code": NOTE, "label": "Note", "labelVn": "Ghi chú", "note": "Commentary only."},
)

# ── how a variation is valued ────────────────────────────────────────────────────────────────────
# Which of these applies is a term of the contract and a negotiation, never a property this code
# may choose. It is recorded so the basis of every agreed variation can be read back years later,
# which is exactly what is asked for in a final-account dispute.
VB_BOQ_RATE = "boq_rate"        # the work is in the bill — use the billed rate
VB_PRO_RATA = "pro_rata"        # not in the bill, but analogous — a rate derived from a billed one
VB_STAR_RATE = "star_rate"      # no analogue — a new rate built up and agreed
VB_DAYWORK = "daywork"          # not measurable — valued on recorded labour, plant and material
VB_LUMP_SUM = "lump_sum"        # a quoted and accepted lump sum
VB_OMISSION = "omission"        # work taken out — a negative

VARIATION_BASES = (
    {"code": VB_BOQ_RATE, "label": "Bill rate", "labelVn": "Theo đơn giá hợp đồng"},
    {"code": VB_PRO_RATA, "label": "Pro-rata to a bill rate", "labelVn": "Theo tỷ lệ đơn giá"},
    {"code": VB_STAR_RATE, "label": "New (star) rate", "labelVn": "Đơn giá mới"},
    {"code": VB_DAYWORK, "label": "Daywork", "labelVn": "Theo nhật trình"},
    {"code": VB_LUMP_SUM, "label": "Quoted lump sum", "labelVn": "Khoán gọn"},
    {"code": VB_OMISSION, "label": "Omission", "labelVn": "Giảm trừ"},
)

# ── the variation lifecycle ──────────────────────────────────────────────────────────────────────
# Written down so it can be tested, rather than living in an `if` in a click handler. A variation
# that is INSTRUCTED is work we are doing and cannot yet bill; that gap is the exposure the
# commercial dashboard exists to show.
V_IDENTIFIED = "identified"   # we think this is a change; nobody has instructed it yet
V_INSTRUCTED = "instructed"   # the client has instructed it — we are exposed from here
V_MEASURED = "measured"       # quantities taken
V_PRICED = "priced"           # our price is built up
V_SUBMITTED = "submitted"     # our price is with the client
V_AGREED = "agreed"           # agreed — and ONLY now does it enter a valuation
V_REJECTED = "rejected"
V_WITHDRAWN = "withdrawn"

VARIATION_FLOW = {
    V_IDENTIFIED: (V_INSTRUCTED, V_WITHDRAWN),
    V_INSTRUCTED: (V_MEASURED, V_PRICED, V_WITHDRAWN),
    V_MEASURED: (V_PRICED, V_WITHDRAWN),
    V_PRICED: (V_SUBMITTED, V_MEASURED, V_WITHDRAWN),
    V_SUBMITTED: (V_AGREED, V_REJECTED, V_PRICED),
    V_AGREED: (),
    V_REJECTED: (V_PRICED,),      # re-price and go again — the normal way a rejection ends
    V_WITHDRAWN: (),
}
VARIATION_OPEN = (V_IDENTIFIED, V_INSTRUCTED, V_MEASURED, V_PRICED, V_SUBMITTED)
VARIATION_TERMINAL = (V_AGREED, V_REJECTED, V_WITHDRAWN)

# ── the valuation lifecycle ──────────────────────────────────────────────────────────────────────
# DRAFT recomputes from the registers on every open. SUBMITTED and everything after it read the
# snapshot the submission took. That distinction is rule 5 and it is the reason this list exists.
VAL_DRAFT = "draft"
VAL_SUBMITTED = "submitted"     # the payment application has gone to the client
VAL_CERTIFIED = "certified"     # the client has certified an amount (which may not be ours)
VAL_PAID = "paid"
VAL_CANCELLED = "cancelled"

VALUATION_FLOW = {
    VAL_DRAFT: (VAL_SUBMITTED, VAL_CANCELLED),
    VAL_SUBMITTED: (VAL_CERTIFIED, VAL_CANCELLED),
    VAL_CERTIFIED: (VAL_PAID,),
    VAL_PAID: (),
    VAL_CANCELLED: (),
}
VALUATION_LIVE = (VAL_SUBMITTED, VAL_CERTIFIED, VAL_PAID)   # counts towards "certified to date"
VALUATION_FROZEN = (VAL_SUBMITTED, VAL_CERTIFIED, VAL_PAID)  # reads its snapshot, not the registers

# ── daywork ──────────────────────────────────────────────────────────────────────────────────────
DW_DRAFT = "draft"
DW_SIGNED = "signed"        # signed on site by the client's representative — the one that matters
DW_PRICED = "priced"
DW_APPROVED = "approved"    # accepted by the client for payment; ONLY these are valued
DW_REJECTED = "rejected"
DAYWORK_VALUED = (DW_APPROVED,)

# ── materials on site ────────────────────────────────────────────────────────────────────────────
MOS_ON_SITE = "on_site"
MOS_INCORPORATED = "incorporated"   # built in — it is now in the measured works, so it leaves
MOS_REMOVED = "removed"


def _num(v):
    """A number, or 0.0 — for QUANTITIES and PERCENTAGES only, never for a rate.

    Deliberately not used to price anything. A missing rate that becomes 0.0 here is exactly the
    silent failure rule 1 exists to stop, so rates go through `_rate()` instead, which can say
    "there isn't one".
    """
    if v is None or v == "":
        return 0.0
    try:
        return float(str(v).replace(",", "").replace("₫", "").strip())
    except (TypeError, ValueError):
        return 0.0


def _rate(v):
    """A rate, or None meaning THERE IS NO RATE. The distinction is the point.

    `_num` would turn a blank rate into 0.0 and the line would price at nil, total correctly, and
    quietly leave money on the table. Returning None forces every caller to decide what an unpriced
    line means, and every caller here decides the same thing: exclude it and name it.
    """
    if v is None or v == "":
        return None
    try:
        f = float(str(v).replace(",", "").replace("₫", "").strip())
    except (TypeError, ValueError):
        return None
    return f


def r2(v):
    """Round to whole đồng. The currency has no subunit in practice and a certificate is a sentence
    a person signs — 12,345,678.9012 is not a figure anybody checks against a bank advice."""
    return round(_num(v), 2)


def _vnd(n):
    return "₫{:,.0f}".format(_num(n))


def _le(a, b):
    """ISO date a <= b, treating a missing cut-off as "no cut-off" (everything is in).

    Missing DATA is the other way round: a record with no date cannot be shown to fall before the
    cut-off, so it is excluded and reported. A record silently included on the strength of having
    no date is how work gets claimed in the wrong month.
    """
    if not b:
        return True
    if not a:
        return False
    return str(a)[:10] <= str(b)[:10]


# ── the bill ─────────────────────────────────────────────────────────────────────────────────────

def boq_line(item):
    """One bill line, priced. Returns the line with `value`, `priced` and `kind` resolved.

    `value` is None — not 0 — when the line cannot be priced. Every total below skips those and
    counts them, so an unpriced bill is a visible fact rather than a smaller number.
    """
    kind = (item.get("kind") or ITEM).strip().lower()
    if kind not in (VALUED_KINDS + UNVALUED_KINDS):
        kind = ITEM
    out = {
        "id": item.get("id"),
        "section": item.get("section") or "",
        "itemNo": item.get("itemNo") or "",
        "desc": item.get("desc") or item.get("description") or "",
        "unit": item.get("unit") or "",
        "kind": kind,
        "billedQty": _num(item.get("billedQty")),
        "rate": _rate(item.get("rate")),
        "wbsId": item.get("wbsId") or item.get("deliverableId") or "",
    }
    if kind in UNVALUED_KINDS:
        out["value"] = 0.0
        out["priced"] = True          # a heading is not "unpriced" — it has nothing to price
        out["measurable"] = False
        return out
    if kind in SUM_KINDS:
        # A provisional or prime-cost sum is carried as a SUM, not as quantity x rate. Its "rate"
        # field holds the sum itself and a quantity of 1 is implied; a bill that puts the sum in the
        # rate column and leaves quantity blank is the normal shape and must not value at nil.
        amount = out["rate"] if out["rate"] is not None else None
        if amount is not None and out["billedQty"]:
            amount = amount * out["billedQty"]
        out["value"] = None if amount is None else r2(amount)
        out["priced"] = amount is not None
        out["measurable"] = False
        return out
    out["measurable"] = True
    if out["rate"] is None:
        out["value"] = None
        out["priced"] = False
        return out
    out["value"] = r2(out["billedQty"] * out["rate"])
    out["priced"] = True
    return out


def bill_total(items):
    """The bill's own arithmetic: what it adds up to, and what it could not price.

    Returns `unpriced` as a LIST of the lines, not a count. "3 lines could not be priced" sends
    somebody hunting through 400 rows; naming them is the difference between a warning that gets
    fixed and one that gets ignored.
    """
    lines = [boq_line(i) for i in (items or [])]
    priced = [l for l in lines if l["kind"] in VALUED_KINDS and l["priced"]]
    unpriced = [l for l in lines if l["kind"] in VALUED_KINDS and not l["priced"]]
    return {
        "lines": lines,
        "total": r2(sum(l["value"] for l in priced)),
        "measuredTotal": r2(sum(l["value"] for l in priced if l["kind"] in MEASURED_KINDS)),
        "sumsTotal": r2(sum(l["value"] for l in priced if l["kind"] in SUM_KINDS)),
        "count": len([l for l in lines if l["kind"] in VALUED_KINDS]),
        "unpriced": [{"id": l["id"], "itemNo": l["itemNo"], "desc": l["desc"]} for l in unpriced],
    }


# ── measurement ──────────────────────────────────────────────────────────────────────────────────

def measured_to_date(items, measures, cutoff=""):
    """Cumulative measured quantity per bill line, up to and including the cut-off date.

    Every measurement is a dated record against a bill line; "to date" is their sum, never a stored
    running total. A stored total drifts the first time a measurement is corrected, and the
    correction is exactly the case somebody looks back at.
    """
    lines = {l["id"]: l for l in (boq_line(i) for i in (items or [])) if l["id"]}
    qty, orphan, undated = {}, [], 0
    for m in (measures or []):
        bid = m.get("boqItemId")
        if not bid or bid not in lines:
            orphan.append(m.get("id"))
            continue
        d = m.get("date") or m.get("measuredOn") or ""
        if cutoff and not d:
            undated += 1              # rule 6: no date means it cannot be placed in a period
            continue
        if not _le(d, cutoff):
            continue
        qty[bid] = qty.get(bid, 0.0) + _num(m.get("qty"))
    return {"qty": qty, "orphanMeasureIds": orphan, "undatedExcluded": undated}


def measured_value(items, measures, cutoff=""):
    """The measured works, valued at bill rates, to a cut-off.

    Over-measure is rule 2: reported line by line with the excess, and INCLUDED in the value. It is
    included because a remeasurement contract genuinely does pay for the quantity built, and because
    dropping the excess would make the total silently disagree with the take-off it came from.
    Whether the excess is legitimate is a commercial judgement, and the register says so out loud
    rather than deciding on somebody's behalf.
    """
    md = measured_to_date(items, measures, cutoff)
    qty = md["qty"]
    rows, over, unpriced = [], [], []
    total = 0.0
    for i in (items or []):
        l = boq_line(i)
        if l["kind"] not in MEASURED_KINDS or not l["id"]:
            continue
        q = r2(qty.get(l["id"], 0.0))
        if not l["priced"]:
            if q:
                unpriced.append({"id": l["id"], "itemNo": l["itemNo"], "desc": l["desc"], "qty": q})
            continue
        v = r2(q * l["rate"])
        pct = round(q / l["billedQty"] * 100.0, 2) if l["billedQty"] else None
        rows.append({"id": l["id"], "itemNo": l["itemNo"], "desc": l["desc"], "unit": l["unit"],
                     "billedQty": l["billedQty"], "rate": l["rate"], "qtyToDate": q,
                     "value": v, "pct": pct, "wbsId": l["wbsId"]})
        total += v
        if l["billedQty"] and q - l["billedQty"] > 1e-9:
            over.append({"id": l["id"], "itemNo": l["itemNo"], "desc": l["desc"],
                         "billedQty": l["billedQty"], "qtyToDate": q,
                         "excessQty": r2(q - l["billedQty"]),
                         "excessValue": r2((q - l["billedQty"]) * l["rate"])})
    return {"rows": rows, "total": r2(total), "overMeasured": over,
            "measuredButUnpriced": unpriced,
            "orphanMeasureIds": md["orphanMeasureIds"], "undatedExcluded": md["undatedExcluded"]}


# ── variations ───────────────────────────────────────────────────────────────────────────────────

def variation_value(v):
    """What ONE variation is worth, and whether that figure may be valued.

    An agreed variation is worth its agreed sum. Everything before agreement is worth its estimate,
    which is a forecast and is labelled as one — rule 3.
    """
    st = (v.get("status") or V_IDENTIFIED).strip().lower()
    agreed = _rate(v.get("agreedValue"))
    est = _rate(v.get("estimatedValue"))
    basis = (v.get("basis") or "").strip().lower()
    amount = agreed if agreed is not None else est
    if amount is not None and basis == VB_OMISSION:
        amount = -abs(amount)
    return {
        "id": v.get("id"), "voNo": v.get("voNo") or "", "title": v.get("title") or "",
        "status": st, "basis": basis,
        "amount": None if amount is None else r2(amount),
        "isAgreed": st == V_AGREED,
        # An agreed variation with no agreed value is not a variation, it is a gap in the record.
        "agreedButUnpriced": st == V_AGREED and agreed is None,
        "valuable": st == V_AGREED and agreed is not None,
        "pctComplete": max(0.0, min(100.0, _num(v.get("pctComplete", 100)))),
        "instructionRef": v.get("instructionRef") or "",
        "instructedOn": v.get("instructedOn") or "",
        "agreedOn": v.get("agreedOn") or "",
    }


def variations_value(variations, cutoff=""):
    """Agreed variations valued to a cut-off, plus the exposure that is not yet agreed.

    `exposure` is the number that gets a project manager out of bed: work instructed and being
    built, with no agreed price behind it. It is reported beside the valuation and never inside it.
    """
    valued, pending, unpriced = [], [], []
    total = 0.0
    exposure = 0.0
    for raw in (variations or []):
        v = variation_value(raw)
        if v["agreedButUnpriced"]:
            unpriced.append(v)
            continue
        if v["valuable"]:
            # An agreed variation enters the valuation from the date it was agreed. Agreed after the
            # cut-off, it belongs to the next one.
            if not _le(v["agreedOn"] or v["instructedOn"], cutoff):
                pending.append(v)
                continue
            amt = r2(v["amount"] * v["pctComplete"] / 100.0)
            valued.append(dict(v, valuedAmount=amt))
            total += amt
            continue
        if v["status"] in VARIATION_OPEN:
            pending.append(v)
            if v["status"] in (V_INSTRUCTED, V_MEASURED, V_PRICED, V_SUBMITTED) and v["amount"]:
                exposure += v["amount"]
    return {"valued": valued, "total": r2(total), "pending": pending,
            "agreedButUnpriced": unpriced, "exposure": r2(exposure)}


# ── daywork and materials on site ────────────────────────────────────────────────────────────────

def daywork_value(sheets, cutoff=""):
    """Approved daywork to a cut-off. Signed-but-not-approved is exposure, same shape as rule 3."""
    valued, pending = [], []
    total, exposure = 0.0, 0.0
    for s in (sheets or []):
        st = (s.get("status") or DW_DRAFT).strip().lower()
        amt = _rate(s.get("value"))
        row = {"id": s.get("id"), "sheetNo": s.get("sheetNo") or "", "date": s.get("date") or "",
               "desc": s.get("desc") or s.get("description") or "", "status": st,
               "amount": None if amt is None else r2(amt),
               "clientSignedBy": s.get("clientSignedBy") or ""}
        if st in DAYWORK_VALUED and amt is not None and _le(row["date"], cutoff):
            valued.append(row)
            total += amt
        elif st not in (DW_REJECTED,):
            pending.append(row)
            if st == DW_SIGNED and amt:
                exposure += amt
    return {"valued": valued, "total": r2(total), "pending": pending, "exposure": r2(exposure)}


def materials_value(materials, cutoff=""):
    """Materials on site at the cut-off — delivered, paid for, and NOT yet built into the works.

    Rule 4 lives here. A material record whose incorporation date is on or before the cut-off has
    become part of the measured works and drops out; leaving it in claims the same pump twice, once
    as material and once as installed work, and that is the commonest double-count in the trade.
    """
    valued, dropped = [], []
    total = 0.0
    for m in (materials or []):
        st = (m.get("status") or MOS_ON_SITE).strip().lower()
        amt = _rate(m.get("value"))
        inc = m.get("incorporatedDate") or ""
        row = {"id": m.get("id"), "desc": m.get("desc") or m.get("description") or "",
               "invoiceRef": m.get("invoiceRef") or "", "onSiteDate": m.get("onSiteDate") or "",
               "incorporatedDate": inc, "status": st,
               "amount": None if amt is None else r2(amt)}
        if st == MOS_REMOVED or amt is None:
            continue
        if inc and _le(inc, cutoff):
            dropped.append(dict(row, why="built into the works — now in the measured value"))
            continue
        if not _le(row["onSiteDate"], cutoff):
            continue
        # An agreed percentage of invoice value is common (the client does not fund 100% of unfixed
        # material). Absent, it is 100 — an explicit contract term, not a guess: the record holds
        # the invoice value and this is what is claimed against it.
        pct = _num(m.get("claimPct", 100)) or 100.0
        pct = max(0.0, min(100.0, pct))
        row["claimPct"] = pct
        row["claimed"] = r2(amt * pct / 100.0)
        valued.append(row)
        total += row["claimed"]
    return {"valued": valued, "total": r2(total), "droppedAsIncorporated": dropped}


# ── the valuation ────────────────────────────────────────────────────────────────────────────────

def valuation(ctx):
    """The gross value of work done to a cut-off date, built up from its four parts.

    `ctx` is everything this needs and nothing it does not:
        boq          bill lines
        measures     dated measurement records
        variations   the variation register
        daywork      daywork sheets
        materials    materials-on-site records
        cutoff       ISO date; the valuation is "as at" this day
        previous     the gross valuation to date at the PREVIOUS cut-off (a number, from the
                     previous valuation's own snapshot — rule 5 — never recomputed here)
        contractSum  the contract value, for the completeness check

    Returns the build-up, `valuedThisPeriod`, and a `warnings` list. It never refuses: a valuation
    with problems in it is still the valuation, and a QS needs to see the problems next to the
    figure rather than instead of it. What it will not do is hide them.
    """
    ctx = ctx or {}
    cutoff = str(ctx.get("cutoff") or "")[:10]
    bill = bill_total(ctx.get("boq"))
    meas = measured_value(ctx.get("boq"), ctx.get("measures"), cutoff)
    vars_ = variations_value(ctx.get("variations"), cutoff)
    dw = daywork_value(ctx.get("daywork"), cutoff)
    mos = materials_value(ctx.get("materials"), cutoff)
    trades = by_trade(ctx)
    # The quality gate needs the registers another module owns. Absent — an older project, or a
    # caller that did not pass them — it reports nothing rather than reporting nothing WRONG: an
    # empty gate and a clean gate look identical, so `gated` says which this was.
    qgate = quality_gate(ctx)
    qgate["available"] = ctx.get("quality") is not None or ctx.get("itps") is not None

    gross = r2(meas["total"] + vars_["total"] + dw["total"] + mos["total"])
    prev = r2(ctx.get("previous"))
    this = r2(gross - prev)

    contract_sum = _rate(ctx.get("contractSum"))
    # The revised contract sum: what the job is worth now that agreed variations are in it. Measuring
    # % complete against the ORIGINAL sum on a job with ₫800m of agreed variations reports a
    # completion the site has not reached, which is how a job looks fine until the month it doesn't.
    revised = None if contract_sum is None else r2(contract_sum + vars_["total"])
    pct = round(gross / revised * 100.0, 2) if revised else None

    warnings = []
    if bill["unpriced"]:
        warnings.append({
            "code": "unpriced_bill_lines",
            "severity": "high",
            "msg": "%d bill line(s) have no rate, so they are excluded from every total on this "
                   "screen. They are not worth nil — they are not priced." % len(bill["unpriced"]),
            "items": bill["unpriced"][:20]})
    if meas["measuredButUnpriced"]:
        warnings.append({
            "code": "measured_but_unpriced",
            "severity": "high",
            "msg": "%d line(s) have measured quantity against them but no rate, so real work done "
                   "on site is missing from this valuation." % len(meas["measuredButUnpriced"]),
            "items": meas["measuredButUnpriced"][:20]})
    if meas["overMeasured"]:
        warnings.append({
            "code": "over_measured",
            "severity": "medium",
            "msg": "%d line(s) are measured beyond the billed quantity (%s of excess). That is "
                   "either a remeasure the client owes, or a take-off error — it is included in "
                   "the total either way, and somebody has to say which."
                   % (len(meas["overMeasured"]),
                      _vnd(sum(o["excessValue"] for o in meas["overMeasured"]))),
            "items": meas["overMeasured"][:20]})
    if meas["orphanMeasureIds"]:
        warnings.append({
            "code": "orphan_measurements",
            "severity": "high",
            "msg": "%d measurement record(s) point at a bill line that is not in the bill, so the "
                   "quantity they carry is valued nowhere." % len(meas["orphanMeasureIds"])})
    if meas["undatedExcluded"]:
        warnings.append({
            "code": "undated_measurements",
            "severity": "medium",
            "msg": "%d measurement record(s) have no date and cannot be placed in a period, so "
                   "they are excluded from this valuation." % meas["undatedExcluded"]})
    if vars_["agreedButUnpriced"]:
        warnings.append({
            "code": "agreed_variation_unpriced",
            "severity": "high",
            "msg": "%d variation(s) are marked agreed but carry no agreed value, so agreed work is "
                   "not being claimed." % len(vars_["agreedButUnpriced"]),
            "items": [{"id": v["id"], "voNo": v["voNo"], "title": v["title"]}
                      for v in vars_["agreedButUnpriced"][:20]]})
    if vars_["exposure"]:
        warnings.append({
            "code": "variation_exposure",
            "severity": "medium",
            "msg": "%s of instructed variation work is not yet agreed, so it is being built and "
                   "cannot be claimed." % _vnd(vars_["exposure"])})
    if dw["exposure"]:
        warnings.append({
            "code": "daywork_exposure",
            "severity": "medium",
            "msg": "%s of daywork is signed on site but not approved for payment."
                   % _vnd(dw["exposure"])})
    if this < 0:
        warnings.append({
            "code": "negative_period",
            "severity": "high",
            "msg": "This period values at %s — LESS than the previous valuation. That happens when "
                   "a measurement or a variation has been reduced after it was claimed; it is a "
                   "credit against the client, not a claim." % _vnd(this)})
    if revised and gross - revised > 0.005:
        warnings.append({
            "code": "over_contract",
            "severity": "high",
            "msg": "The valuation (%s) exceeds the revised contract sum (%s) by %s. Work is being "
                   "valued that the contract does not yet cover — an agreed variation is missing."
                   % (_vnd(gross), _vnd(revised), _vnd(gross - revised))})
    if qgate["valueAtRisk"]:
        warnings.append({
            "code": "quality_value_at_risk",
            "severity": "high",
            "msg": "%s of measured work sits in a trade carrying an open Major or Critical "
                   "non-conformance. It is being claimed; a client's QS deducts exactly this."
                   % _vnd(qgate["valueAtRisk"]),
            "items": [{"itemNo": t["label"],
                       "desc": "%d open NCR(s): %s"
                               % (t["count"], ", ".join(
                                   (n["refNo"] or n["title"] or "") for n in t["ncrs"][:4]))}
                      for t in qgate["atRisk"][:20]]})
    if qgate["valueNotReleased"]:
        warnings.append({
            "code": "measured_without_inspection",
            "severity": "high",
            "msg": "%s is measured against bill lines that name an inspection and test plan, with "
                   "nothing recording that the work was released past it."
                   % _vnd(qgate["valueNotReleased"]),
            "items": [{"itemNo": u["itemNo"], "desc": u["why"]}
                      for u in qgate["unreleased"][:20]]})
    if trades["unallocatedLines"]:
        warnings.append({
            "code": "lines_without_a_trade",
            "severity": "low",
            "msg": "%d bill line(s) are not allocated to a trade, so they sit outside every "
                   "trade-by-trade figure on this screen." % trades["unallocatedLines"]})
    if not cutoff:
        warnings.append({
            "code": "no_cutoff",
            "severity": "medium",
            "msg": "No cut-off date, so every record in the registers is included regardless of "
                   "when it happened. Set the valuation's cut-off date."})

    return {
        "cutoff": cutoff,
        "build": [
            {"key": "measured", "label": "Measured works at bill rates",
             "labelVn": "Khối lượng đo bóc theo đơn giá", "amount": meas["total"]},
            {"key": "variations", "label": "Agreed variations",
             "labelVn": "Phát sinh đã thống nhất", "amount": vars_["total"]},
            {"key": "daywork", "label": "Approved daywork",
             "labelVn": "Nhật trình đã duyệt", "amount": dw["total"]},
            {"key": "materials", "label": "Materials on site (not yet built in)",
             "labelVn": "Vật tư tại công trường", "amount": mos["total"]},
        ],
        "grossToDate": gross,
        "previousToDate": prev,
        "valuedThisPeriod": this,
        "contractSum": contract_sum,
        "revisedContractSum": revised,
        "pctComplete": pct,
        "bill": bill,
        "measured": meas,
        "variations": vars_,
        "daywork": dw,
        "materials": mos,
        "trades": trades,
        "quality": qgate,
        "warnings": warnings,
        # Said here rather than assumed anywhere: this module stops at the gross figure.
        "next": "This gross valuation is the `certified_this` figure for "
                "sales_contract.application(), which applies retention and advance recovery under "
                "the terms of the contract. Neither is computed here.",
    }


# ── cost value reconciliation ────────────────────────────────────────────────────────────────────

def cvr(ctx):
    """Value earned against cost incurred: is this job making money, and is it making less than it
    was last month?

    The valuation says what the client owes us. `pm_costs` says what the job has cost. The gap is
    the margin, and the reason a CVR is a discipline rather than a subtraction is that neither side
    is complete at the cut-off: work is done that is not yet valued, and cost is incurred that is
    not yet invoiced. Both adjustments are JUDGEMENTS and are entered by a person, never derived —
    a portal that invented an accrual would be inventing the answer.

    `ctx`:
        valueToDate     gross valuation to date
        costToDate      actual cost booked to date
        accruals        cost incurred, not yet invoiced (entered)
        provisions      known future losses: rework, LDs, disputed variations (entered)
        forecastValue   forecast final value at completion (entered)
        forecastCost    forecast final cost at completion (entered)
        previousMargin  last period's margin %, for the trend (or None)
    """
    ctx = ctx or {}
    value = r2(ctx.get("valueToDate"))
    cost = r2(ctx.get("costToDate"))
    accr = r2(ctx.get("accruals"))
    prov = r2(ctx.get("provisions"))
    true_cost = r2(cost + accr + prov)
    margin = r2(value - true_cost)
    margin_pct = round(margin / value * 100.0, 2) if value else None

    fv = _rate(ctx.get("forecastValue"))
    fc = _rate(ctx.get("forecastCost"))
    f_margin = None if (fv is None or fc is None) else r2(fv - fc)
    f_margin_pct = None if (f_margin is None or not fv) else round(f_margin / fv * 100.0, 2)

    # Margin BY TRADE. `valueByTrade` comes from the valuation and `costByTrade` from pm_costs;
    # a trade present in one and not the other is reported, never quietly netted. Cost that nobody
    # allocated to a trade stays UNALLOCATED — spreading it pro-rata would invent an allocation and
    # put one trade's overspend in another trade's margin.
    vbt = {str(k): r2(v) for k, v in (ctx.get("valueByTrade") or {}).items()}
    cbt = {str(k): r2(v) for k, v in (ctx.get("costByTrade") or {}).items()}
    trade_rows = []
    for code in sorted(set(vbt) | set(cbt), key=lambda c: (c == UNALLOCATED, c)):
        tv, tc = vbt.get(code, 0.0), cbt.get(code, 0.0)
        tm = r2(tv - tc)
        trade_rows.append({
            "code": code, "label": discipline_label(code),
            "value": tv, "cost": tc, "margin": tm,
            "marginPct": round(tm / tv * 100.0, 2) if tv else None,
            # Cost booked against a trade with no value is either work not yet measured or work
            # billed to the wrong trade. Both matter and neither is visible in a project total.
            "costWithoutValue": bool(tc and not tv)})

    prev_pct = ctx.get("previousMargin")
    prev_pct = None if prev_pct in (None, "") else round(_num(prev_pct), 2)
    drift = None if (prev_pct is None or margin_pct is None) else round(margin_pct - prev_pct, 2)

    warnings = []
    if not value and cost:
        warnings.append({
            "code": "cost_without_value", "severity": "high",
            "msg": "%s of cost is booked and nothing is valued. Either the measurement has not been "
                   "done, or work is being built that nobody is billing for." % _vnd(cost)})
    if margin < 0:
        warnings.append({
            "code": "loss_making", "severity": "high",
            "msg": "This job is %s behind: it has cost more than it has earned."
                   % _vnd(abs(margin))})
    if drift is not None and drift <= -2:
        warnings.append({
            "code": "margin_eroding", "severity": "high",
            "msg": "Margin has fallen %.2f points since the last reconciliation (%.2f%% to %.2f%%)."
                   % (abs(drift), prev_pct, margin_pct)})
    if f_margin is not None and f_margin < 0:
        warnings.append({
            "code": "forecast_loss", "severity": "high",
            "msg": "The forecast is a %s loss at completion. A loss that is foreseen is provided "
                   "for now, not discovered at the final account." % _vnd(abs(f_margin))})
    if fv is None or fc is None:
        warnings.append({
            "code": "no_forecast", "severity": "medium",
            "msg": "No forecast final value or cost, so this reconciliation says where the job HAS "
                   "been and nothing about where it is going."})
    losing = [t for t in trade_rows if t["margin"] < 0 and t["value"]]
    if losing and margin >= 0:
        # The report this exists for. A job at +17% overall can carry a package at -4%, and the
        # project total is the one number that cannot show it.
        warnings.append({
            "code": "trade_losing_inside_a_profitable_job", "severity": "high",
            "msg": "The job is in profit overall, but %s. A project total cannot show this."
                   % "; ".join("%s is %s behind" % (t["label"], _vnd(abs(t["margin"])))
                               for t in losing[:4])})
    orphan_cost = [t for t in trade_rows if t["costWithoutValue"]]
    if orphan_cost:
        warnings.append({
            "code": "cost_on_a_trade_with_no_value", "severity": "medium",
            "msg": "Cost is booked against %s with nothing valued there — either the measurement "
                   "has not been done, or it is booked to the wrong trade."
                   % ", ".join(t["label"] for t in orphan_cost[:4])})
    if accr == 0 and cost:
        warnings.append({
            "code": "no_accrual", "severity": "low",
            "msg": "No accrual is entered. On a live site there is almost always cost incurred that "
                   "has not been invoiced yet; a nil accrual flatters the margin."})

    return {
        "valueToDate": value, "costToDate": cost, "accruals": accr, "provisions": prov,
        "trueCostToDate": true_cost, "margin": margin, "marginPct": margin_pct,
        "forecastValue": fv, "forecastCost": fc,
        "forecastMargin": f_margin, "forecastMarginPct": f_margin_pct,
        "previousMarginPct": prev_pct, "marginDrift": drift,
        "trades": trade_rows,
        "warnings": warnings,
    }


# ── the final account ────────────────────────────────────────────────────────────────────────────

def final_account(ctx):
    """What the job finally comes to, and what is still owed on it.

        original contract sum
      + agreed variations                (net of omissions)
      +/- provisional and prime cost sum adjustments
      + agreed daywork
      + agreed claims (extension of time, loss and expense)
      = final account sum
      - certified to date
      = balance due on the final certificate

    Everything in it must be AGREED. A final account containing an unagreed figure is not a final
    account, it is a claim, and this refuses to call it one — `agreed` comes back False with the
    reasons listed, and the caller may still print it as a draft.
    """
    ctx = ctx or {}
    original = _rate(ctx.get("contractSum"))
    vars_ = variations_value(ctx.get("variations"), ctx.get("cutoff") or "")
    dw = daywork_value(ctx.get("daywork"), ctx.get("cutoff") or "")
    ps_adj = r2(ctx.get("provisionalAdjustment"))
    claims = r2(ctx.get("agreedClaims"))
    certified = r2(ctx.get("certifiedToDate"))
    comm = commissioning({"tests": ctx.get("commissioning")})

    # Name the record the way a person would name it. Falling through to the row id printed
    # "Variation pm_-778acacb is instructed, not agreed" on the screen a QS uses to chase the
    # things blocking a final account — which tells them nothing they can act on.
    def _vname(v):
        if v["voNo"] and v["title"]:
            return "%s (%s)" % (v["voNo"], v["title"])
        return v["voNo"] or v["title"] or "an unnumbered variation"

    def _dname(d):
        if d["sheetNo"]:
            return "sheet %s" % d["sheetNo"]
        bits = [x for x in (d["date"], (d["desc"] or "")[:60]) if x]
        return ("the sheet dated %s" % " - ".join(bits)) if bits else "an unnumbered daywork sheet"

    blocked = []
    if original is None:
        blocked.append("The original contract sum is not recorded.")
    for v in vars_["pending"]:
        blocked.append("Variation %s is %s, not agreed." % (_vname(v), v["status"]))
    for v in vars_["agreedButUnpriced"]:
        blocked.append("Variation %s is agreed but carries no agreed value." % _vname(v))
    for d in dw["pending"]:
        blocked.append("Daywork %s is %s, not approved." % (_dname(d), d["status"]))
    # The last tranche of a cleanroom contract follows the room passing its tests. A final account
    # that ignores an outstanding classification or a failed filter integrity test is one the client
    # will not sign, so it blocks here rather than being discovered at the signing meeting.
    for t in comm["failed"]:
        blocked.append("%s%s has FAILED."
                       % (t["label"], (" for " + t["area"]) if t["area"] else ""))
    for t in comm["outstanding"]:
        blocked.append("%s%s is %s and gates the final account."
                       % (t["label"], (" for " + t["area"]) if t["area"] else "",
                          t["status"].replace("_", " ")))

    total = None
    if original is not None:
        total = r2(original + vars_["total"] + ps_adj + dw["total"] + claims)

    return {
        "build": [
            {"key": "original", "label": "Original contract sum",
             "labelVn": "Giá trị hợp đồng gốc", "amount": original},
            {"key": "variations", "label": "Agreed variations (net)",
             "labelVn": "Phát sinh đã thống nhất", "amount": vars_["total"]},
            {"key": "provisional", "label": "Provisional / PC sum adjustment",
             "labelVn": "Điều chỉnh tạm tính", "amount": ps_adj},
            {"key": "daywork", "label": "Approved daywork",
             "labelVn": "Nhật trình đã duyệt", "amount": dw["total"]},
            {"key": "claims", "label": "Agreed claims (EOT / loss and expense)",
             "labelVn": "Khiếu nại đã thống nhất", "amount": claims},
        ],
        "finalAccountSum": total,
        "certifiedToDate": certified,
        "balanceDue": None if total is None else r2(total - certified),
        "agreed": not blocked,
        "blockedBy": blocked,
        "commissioning": comm,
        # Retention is NOT netted off here. It is held, not deducted, and when it comes back is a
        # term of the contract that sales_contract.retention_release() already reads.
        "retentionNote": "Retention still held is released under the contract's release rule — see "
                         "the contract's retention schedule. It is not a deduction from this sum.",
    }


# ══════════════════════════════════════════════════════════════════════════════════════════════════
#  THE TRADES — Civil, MEP and Cleanroom
# ══════════════════════════════════════════════════════════════════════════════════════════════════
# A contractor of this shape does not have "a bill". It has a bill per trade, priced by different
# estimators, built by different subcontractors, inspected against different standards and losing
# money independently of each other. "Is this job making money" is the wrong resolution: a job at
# 17% overall can be a cleanroom envelope at 31% carrying an electrical package at -4%, and the
# month you find out is the month the electrical subcontractor asks for a loss-and-expense claim.
#
# The order is the order work happens in, so a bill sorted by trade reads like a programme.
CIVIL = "civil"
ARCHITECTURAL = "architectural"
CLEANROOM = "cleanroom"
HVAC = "hvac"
CLEAN_UTILITIES = "clean_utilities"
PLUMBING = "plumbing"
ELECTRICAL = "electrical"
FIRE = "fire"
CONTROLS = "controls"
COMMISSIONING = "commissioning"
VALIDATION = "validation"
PRELIMINARIES = "preliminaries"

DISCIPLINES = (
    {"code": PRELIMINARIES, "label": "Preliminaries & general",
     "labelVn": "Chi phí chung", "hex": "#64748B",
     "note": "Site establishment, temporary works, supervision, insurances."},
    {"code": CIVIL, "label": "Civil & structural",
     "labelVn": "Xây dựng & kết cấu", "hex": "#8B5CF6",
     "note": "Excavation, foundations, concrete, steelwork, builders' work in connection."},
    {"code": ARCHITECTURAL, "label": "Architectural & finishes",
     "labelVn": "Kiến trúc & hoàn thiện", "hex": "#A855F7",
     "note": "Partitions, doors, ceilings, flooring, painting outside the clean envelope."},
    {"code": CLEANROOM, "label": "Cleanroom envelope",
     "labelVn": "Vỏ phòng sạch", "hex": "#0EA5E9",
     "note": "Wall and ceiling panel systems, coving, view panels, cleanroom doors, pass boxes, "
             "air showers, epoxy and vinyl flooring."},
    {"code": HVAC, "label": "HVAC",
     "labelVn": "Điều hòa & thông gió", "hex": "#3168A8",
     "note": "AHU, ductwork and insulation, dampers, terminal HEPA housings, chilled water, "
             "dust and fume extract."},
    {"code": CLEAN_UTILITIES, "label": "Clean utilities & process piping",
     "labelVn": "Tiện ích sạch & đường ống công nghệ", "hex": "#14B8A6",
     "note": "Compressed air, nitrogen, vacuum, purified water and WFI loops, orbital welding, "
             "passivation."},
    {"code": PLUMBING, "label": "Plumbing & drainage",
     "labelVn": "Cấp thoát nước", "hex": "#0891B2",
     "note": "Domestic water, sanitary and process drainage, sumps, neutralisation."},
    {"code": ELECTRICAL, "label": "Electrical",
     "labelVn": "Điện", "hex": "#F59E0B",
     "note": "LV distribution, small power, lighting, containment, earthing and bonding, UPS."},
    {"code": FIRE, "label": "Fire protection & detection",
     "labelVn": "Phòng cháy chữa cháy", "hex": "#EF4444",
     "note": "Sprinkler, fire alarm, gaseous suppression, smoke control."},
    {"code": CONTROLS, "label": "BMS / EMS & controls",
     "labelVn": "Hệ điều khiển BMS/EMS", "hex": "#6366F1",
     "note": "Building and environmental monitoring, field devices, graphics, alarms, 21 CFR "
             "Part 11 records where the client is GMP."},
    {"code": COMMISSIONING, "label": "Testing & commissioning",
     "labelVn": "Chạy thử & nghiệm thu", "hex": "#00B060",
     "note": "TAB, duct leakage, electrical testing, cause-and-effect, system demonstration."},
    {"code": VALIDATION, "label": "Qualification & validation",
     "labelVn": "Thẩm định & xác nhận", "hex": "#16A34A",
     "note": "Cleanroom classification, DQ/IQ/OQ/PQ, documentation handover."},
)
DISCIPLINE_CODES = tuple(d["code"] for d in DISCIPLINES)
_DISCIPLINE_BY_CODE = {d["code"]: d for d in DISCIPLINES}
UNALLOCATED = "unallocated"
# NOT the same thing, and the difference matters. UNALLOCATED is "nobody set a trade on this bill
# line". UNATTRIBUTED is "this record names a trade, in another module's vocabulary, that does not
# map onto one of ours". Folding the second into the first makes an NCR logged against "MEP" match
# every un-traded bill line on the job — which is how a Critical duct NCR came to report the whole
# contract at risk.
UNATTRIBUTED = "unattributed"

# pm_quality and pm_quality_itp were written before this module and carry their own discipline list.
# The mapping is EXPLICIT and deliberately incomplete: "MEP" covers mechanical, electrical AND
# plumbing, and there is no honest way to turn it into one of them. An unmapped discipline is
# reported as unattributed rather than guessed, because the output of the guess would be a money
# figure somebody acts on.
QUALITY_DISCIPLINE_MAP = {
    "civil": CIVIL,
    "structural": CIVIL,
    "geotechnical": CIVIL,
    "architectural": ARCHITECTURAL,
    "mechanical": HVAC,
    "process / piping": CLEAN_UTILITIES,
    "electrical": ELECTRICAL,
    "hse": PRELIMINARIES,
    "qa/qc": COMMISSIONING,
    "commissioning": COMMISSIONING,
    # "MEP" and "General / Multi" are NOT here. Both name more than one trade, and a valuation is
    # not the place to resolve that by picking the first one.
}


def quality_discipline(v):
    """A pm_quality discipline as one of OUR trades, or UNATTRIBUTED.

    Accepts our own codes too, so a register that starts using them needs no migration.
    """
    c = str(v or "").strip().lower()
    if c in _DISCIPLINE_BY_CODE:
        return c
    return QUALITY_DISCIPLINE_MAP.get(c, UNATTRIBUTED)


def discipline_label(code):
    """The trade's name, or a stated "unallocated" — never a blank column heading.

    A trade nobody set is a real state and it is reported as one. Folding it into the first trade in
    the list, or into "other", would put somebody else's money in a trade's margin.
    """
    d = _DISCIPLINE_BY_CODE.get(str(code or "").strip().lower())
    return d["label"] if d else "Not allocated to a trade"


def _disc(v):
    c = str(v or "").strip().lower()
    return c if c in _DISCIPLINE_BY_CODE else UNALLOCATED


_DISCIPLINE_BY_LABEL = {}
for _d in DISCIPLINES:
    _DISCIPLINE_BY_LABEL[_d["label"].strip().lower()] = _d["code"]
    _DISCIPLINE_BY_LABEL[_d["labelVn"].strip().lower()] = _d["code"]


def discipline_code(v):
    """A trade code from whatever a person typed, or None meaning "that is not a trade".

    Accepts the code, the English name and the Vietnamese name, because a bill exported out of
    Excel is typed by a quantity surveyor and says "HVAC" or "Cleanroom envelope", not "cleanroom".
    Returns None rather than a default: an unrecognised trade is a TYPO, and silently filing it
    under "unallocated" would put the line in the same place as a blank while looking allocated.
    """
    if v is None or str(v).strip() == "":
        return ""
    c = str(v).strip().lower()
    if c in _DISCIPLINE_BY_CODE:
        return c
    return _DISCIPLINE_BY_LABEL.get(c)


def by_trade(ctx):
    """The bill, the measurement and the agreed variations, split by trade.

    This is the report a commercial manager reads first and the one the portal could not produce.
    Each trade carries what it is worth, what is built, and how far through it is — measured against
    its OWN billed value, because 60% of the cleanroom envelope and 60% of the electrical package
    are different amounts of money and a single project percentage hides both.
    """
    ctx = ctx or {}
    cutoff = str(ctx.get("cutoff") or "")[:10]
    items = ctx.get("boq") or []
    meas = measured_value(items, ctx.get("measures"), cutoff)
    measured_by = {r["id"]: r for r in meas["rows"]}
    disc_of = {}
    rows = {}

    def row(code):
        if code not in rows:
            d = _DISCIPLINE_BY_CODE.get(code)
            rows[code] = {"code": code, "label": d["label"] if d else discipline_label(code),
                          "labelVn": d["labelVn"] if d else "Chưa phân bổ",
                          "hex": d["hex"] if d else "#94A3B8",
                          "billed": 0.0, "measured": 0.0, "variations": 0.0,
                          "unpricedLines": 0, "lines": 0}
        return rows[code]

    for i in items:
        line = boq_line(i)
        if line["kind"] in UNVALUED_KINDS or not line["id"]:
            continue
        code = _disc(i.get("discipline"))
        disc_of[line["id"]] = code
        r = row(code)
        r["lines"] += 1
        if line["priced"]:
            r["billed"] += line["value"]
        else:
            r["unpricedLines"] += 1
        m = measured_by.get(line["id"])
        if m:
            r["measured"] += m["value"]

    # A variation belongs to the trade doing the work. Unset, it is UNALLOCATED and says so rather
    # than landing in whichever trade happens to be first.
    for raw in (ctx.get("variations") or []):
        v = variation_value(raw)
        if not v["valuable"] or not _le(v["agreedOn"] or v["instructedOn"], cutoff):
            continue
        row(_disc(raw.get("discipline")))["variations"] += r2(v["amount"] * v["pctComplete"] / 100.0)

    out = []
    for code in DISCIPLINE_CODES + (UNALLOCATED,):
        if code not in rows:
            continue
        r = rows[code]
        r["billed"] = r2(r["billed"])
        r["measured"] = r2(r["measured"])
        r["variations"] = r2(r["variations"])
        r["revised"] = r2(r["billed"] + r["variations"])
        # Against the REVISED trade value, for the same reason the project percentage is: a trade
        # carrying agreed variations is bigger than its bill said.
        r["pct"] = round(r["measured"] / r["revised"] * 100.0, 2) if r["revised"] else None
        out.append(r)
    return {"trades": out,
            "billedTotal": r2(sum(t["billed"] for t in out)),
            "measuredTotal": r2(sum(t["measured"] for t in out)),
            "unallocatedLines": sum(t["lines"] for t in out if t["code"] == UNALLOCATED)}


# ══════════════════════════════════════════════════════════════════════════════════════════════════
#  THE QUALITY GATE — what a client's QS will not certify
# ══════════════════════════════════════════════════════════════════════════════════════════════════
# On a pharma or cleanroom fit-out, payment is gated on quality and not on progress. Work that is
# built, measured and genuinely there is still not payable if it carries an open non-conformance or
# if it was never released past its inspection hold point. The contractor's own QS needs to know
# that BEFORE the application goes out, because the alternative is finding out from the client's
# certificate three weeks later with the cash already spent.
#
# THIS MODULE NEVER DEDUCTS. It reports value AT RISK beside the valuation, in the same place and
# for the same reason variation exposure is reported. Whether to claim it is a commercial decision
# with a contract behind it, and the portal is not entitled to make it. What it is entitled to do is
# make sure nobody submits ₫400m of ductwork against an open Critical NCR without knowing.

# Dispositions that mean the work stays claimable. A CONCESSION is the client accepting what was
# built — the whole point of one — so it is not at risk. Everything else means the work is not yet
# what was bought.
NCR_CONCESSION = "use as is (concession)"
NCR_OPEN_STATUSES = ("open", "in progress")
NCR_AT_RISK_SEVERITIES = ("major", "critical")


def _norm(v):
    return str(v or "").strip().lower()


def quality_gate(ctx):
    """Which measured value is at risk, and which is measured but never released.

    Two mechanisms, at two different resolutions, and the difference is stated rather than blurred:

    BY TRADE — an open NCR carries a discipline. Every open Major or Critical non-conformance puts
    the measured value of ITS TRADE at risk. Coarse, and it needs nobody to have linked anything, so
    it works on the day the register is first used.

    BY LINE — where the quantity surveyor has said so. A bill line naming an `itpRef` is released by
    that inspection and test plan and by nothing else: measurement against it with no inspection
    reference, or against an ITP that is still in draft, is NOT RELEASED. A line naming no ITP is
    not gated at all, because not every bill line has an inspection (nobody witnesses site
    establishment) and inventing a hold point would make the whole gate noise.

    `ctx`: boq, measures, quality (pm_quality), itps (pm_quality_itp), cutoff.
    """
    ctx = ctx or {}
    cutoff = str(ctx.get("cutoff") or "")[:10]
    items = ctx.get("boq") or []
    meas = measured_value(items, ctx.get("measures"), cutoff)
    measured_by = {r["id"]: r for r in meas["rows"]}
    line_of = {}
    for i in items:
        line = boq_line(i)
        if line["id"]:
            line_of[line["id"]] = dict(line, discipline=_disc(i.get("discipline")),
                                       itpRef=str(i.get("itpRef") or "").strip())

    # ── open non-conformances, by trade ──────────────────────────────────────────────────────────
    ncrs = []
    for q in (ctx.get("quality") or []):
        if _norm(q.get("type")) != "ncr":
            continue
        if _norm(q.get("status")) not in NCR_OPEN_STATUSES:
            continue
        # A concession is the client accepting what was built, so it puts nothing at risk — but it
        # is still an OPEN non-conformance and it stays in the register. Dropping it here removed it
        # from the "Open non-conformances" table as well, so a QS reading that table was shown three
        # of the four open NCRs on the job with nothing saying the fourth existed.
        conc = _norm(q.get("disposition")) == NCR_CONCESSION
        ncrs.append({"id": q.get("id"), "refNo": q.get("refNo") or "",
                     "title": q.get("title") or "", "severity": q.get("severity") or "",
                     "discipline": quality_discipline(q.get("discipline")),
                     "rawDiscipline": q.get("discipline") or "",
                     "disposition": q.get("disposition") or "",
                     "concession": conc,
                     "raisedDate": q.get("raisedDate") or "",
                     "atRisk": (not conc)
                               and _norm(q.get("severity")) in NCR_AT_RISK_SEVERITIES})

    measured_by_disc = {}
    for lid, m in measured_by.items():
        d = (line_of.get(lid) or {}).get("discipline", UNALLOCATED)
        measured_by_disc[d] = measured_by_disc.get(d, 0.0) + m["value"]

    at_risk, risk_total = [], 0.0
    # An NCR whose trade could not be attributed must NOT be matched against the un-traded bill
    # lines. They are two different absences and treating them as one produced a confident,
    # completely wrong figure the first time this ran on a real bill.
    unattributed = [n for n in ncrs if n["atRisk"] and n["discipline"] == UNATTRIBUTED]
    for d in sorted({n["discipline"] for n in ncrs
                     if n["atRisk"] and n["discipline"] != UNATTRIBUTED}):
        val = r2(measured_by_disc.get(d, 0.0))
        if not val:
            continue                       # an NCR on a trade with nothing measured risks nothing
        against = [n for n in ncrs if n["discipline"] == d and n["atRisk"]]
        at_risk.append({"discipline": d, "label": discipline_label(d), "measured": val,
                        "ncrs": against, "count": len(against)})
        risk_total += val

    # ── measured but never released ──────────────────────────────────────────────────────────────
    # An ITP releases work only once it is APPROVED. A plan still in draft has not been agreed with
    # the client, so nothing can have been witnessed against it.
    itp_by_no, itp_by_id = {}, {}
    for p in (ctx.get("itps") or []):
        rec = {"id": p.get("id"), "itpNo": p.get("itpNo") or "", "title": p.get("title") or "",
               "status": p.get("status") or "", "approved": _norm(p.get("status")) == "approved"}
        if rec["itpNo"]:
            itp_by_no[rec["itpNo"].strip().lower()] = rec
        if rec["id"]:
            itp_by_id[rec["id"]] = rec

    # Which measurement records carry an inspection reference, per bill line.
    released_qty, total_qty = {}, {}
    for m in (ctx.get("measures") or []):
        lid = m.get("boqItemId")
        if not lid or lid not in line_of:
            continue
        d = m.get("date") or m.get("measuredOn") or ""
        if cutoff and (not d or not _le(d, cutoff)):
            continue
        q = _num(m.get("qty"))
        total_qty[lid] = total_qty.get(lid, 0.0) + q
        if str(m.get("inspectionRef") or "").strip():
            released_qty[lid] = released_qty.get(lid, 0.0) + q

    unreleased, unreleased_total = [], 0.0
    for lid, m in measured_by.items():
        line = line_of.get(lid) or {}
        ref = line.get("itpRef") or ""
        if not ref:
            continue                        # this line is not inspection-gated, and says so
        itp = itp_by_no.get(ref.strip().lower()) or itp_by_id.get(ref)
        tq = total_qty.get(lid, 0.0)
        rq = released_qty.get(lid, 0.0)
        if itp and itp["approved"] and tq and rq >= tq - 1e-9:
            continue                        # fully released against an approved plan
        why = ("the inspection and test plan %s is not on the register" % ref) if not itp else (
            ("%s is %s, not approved — nothing can have been witnessed against it"
             % (itp["itpNo"] or ref, itp["status"] or "not set")) if not itp["approved"] else
            ("%s of %s measured carries no inspection reference"
             % (_qty(tq - rq), _qty(tq))))
        # Value the UNRELEASED part, not the whole line: half a line inspected is half a line at
        # risk, and reporting the lot would make the figure easy to dismiss.
        share = 1.0 if (not tq or not itp or not itp["approved"]) else max(0.0, (tq - rq) / tq)
        val = r2(m["value"] * share)
        unreleased.append({"id": lid, "itemNo": m["itemNo"], "desc": m["desc"],
                           "itpRef": ref, "itpStatus": (itp or {}).get("status") or "",
                           "measured": m["value"], "unreleased": val, "why": why})
        unreleased_total += val

    gated = sum(1 for l in line_of.values() if l.get("itpRef"))
    return {
        "openNcrs": ncrs,
        "unattributedNcrs": unattributed,
        "atRisk": at_risk,
        "valueAtRisk": r2(risk_total),
        "unreleased": unreleased,
        "valueNotReleased": r2(unreleased_total),
        "linesGatedByItp": gated,
        "linesTotal": len(line_of),
        "measuredTotal": meas["total"],
    }


def _qty(n):
    """A quantity in a sentence. 900.0 reads as a defect; 900 reads as a measurement."""
    n = _num(n)
    return ("%d" % n) if abs(n - round(n)) < 1e-9 else ("%.2f" % n)


# ══════════════════════════════════════════════════════════════════════════════════════════════════
#  COMMISSIONING, QUALIFICATION AND THE LAST TEN PER CENT
# ══════════════════════════════════════════════════════════════════════════════════════════════════
# On a cleanroom contract the final tranche of money does not follow the last panel being fixed. It
# follows the ROOM PASSING ITS TESTS: classification, filter integrity, air change rate, pressure
# cascade, recovery. Until those certificates exist the works are not complete however finished they
# look, and a final account that ignores them is a final account the client will not sign.
#
# The standards below are cited so the register states WHAT a test is against rather than only that
# it happened. A test with no acceptance criterion is not a test, it is an opinion.
CT_CLASSIFICATION = "classification"
CT_FILTER_INTEGRITY = "filter_integrity"
CT_AIRFLOW = "airflow"
CT_PRESSURE = "pressure"
CT_RECOVERY = "recovery"
CT_CONTAINMENT = "containment"
CT_VISUALISATION = "visualisation"
CT_TEMP_RH = "temp_rh"
CT_LIGHT_NOISE = "light_noise"
CT_TAB = "tab"
CT_DUCT_LEAKAGE = "duct_leakage"
CT_ELECTRICAL = "electrical_test"
CT_FIRE_CE = "fire_cause_effect"
CT_CLEAN_UTILITY = "clean_utility"
CT_IQ = "iq"
CT_OQ = "oq"
CT_PQ = "pq"

COMMISSIONING_TESTS = (
    {"code": CT_TAB, "label": "Testing, adjusting & balancing (TAB)",
     "labelVn": "Cân chỉnh lưu lượng", "standard": "AABC / NEBB procedural standard",
     "criterion": "Every terminal within the design tolerance stated on the drawings",
     "discipline": HVAC, "cleanroom": False},
    {"code": CT_DUCT_LEAKAGE, "label": "Ductwork leakage test",
     "labelVn": "Thử rò rỉ đường ống gió", "standard": "EN 12237 / EN 1507 (SMACNA equivalent)",
     "criterion": "Leakage within the specified class at the specified test pressure",
     "discipline": HVAC, "cleanroom": False},
    {"code": CT_FILTER_INTEGRITY, "label": "Installed HEPA/ULPA filter leak test (DOP/PAO)",
     "labelVn": "Thử rò rỉ màng lọc HEPA", "standard": "ISO 14644-3:2019 §B.7",
     "criterion": "No downstream leak above the specified penetration",
     "discipline": VALIDATION, "cleanroom": True},
    {"code": CT_AIRFLOW, "label": "Airflow volume / velocity & air change rate",
     "labelVn": "Lưu lượng & số lần trao đổi không khí", "standard": "ISO 14644-3:2019 §B.1",
     "criterion": "Air changes per hour at or above the design figure for the room grade",
     "discipline": VALIDATION, "cleanroom": True},
    {"code": CT_PRESSURE, "label": "Room pressure differential & cascade",
     "labelVn": "Chênh áp giữa các phòng", "standard": "ISO 14644-3:2019 §B.4",
     "criterion": "Cascade in the specified direction, each step within tolerance",
     "discipline": VALIDATION, "cleanroom": True},
    {"code": CT_CLASSIFICATION, "label": "Airborne particle classification",
     "labelVn": "Phân loại độ sạch không khí", "standard": "ISO 14644-1:2015",
     "criterion": "Room achieves its specified ISO class at the specified occupancy state",
     "discipline": VALIDATION, "cleanroom": True},
    {"code": CT_RECOVERY, "label": "Recovery test",
     "labelVn": "Thử phục hồi độ sạch", "standard": "ISO 14644-3:2019 §B.12",
     "criterion": "Return to classification within the specified recovery time",
     "discipline": VALIDATION, "cleanroom": True},
    {"code": CT_CONTAINMENT, "label": "Containment leak / installed system leakage",
     "labelVn": "Thử rò rỉ hệ thống", "standard": "ISO 14644-3:2019 §B.5",
     "criterion": "No ingress above the specified limit at the room boundary",
     "discipline": VALIDATION, "cleanroom": True},
    {"code": CT_VISUALISATION, "label": "Airflow direction & visualisation (smoke study)",
     "labelVn": "Quan sát hướng dòng khí", "standard": "ISO 14644-3:2019 §B.6",
     "criterion": "Airflow moves from clean to less clean with no stagnation at critical points",
     "discipline": VALIDATION, "cleanroom": True},
    {"code": CT_TEMP_RH, "label": "Temperature & relative humidity",
     "labelVn": "Nhiệt độ & độ ẩm", "standard": "ISO 14644-3:2019 §B.9 / §B.10",
     "criterion": "Held within the specified band over the specified period",
     "discipline": HVAC, "cleanroom": True},
    {"code": CT_LIGHT_NOISE, "label": "Lighting level & sound level",
     "labelVn": "Độ rọi & độ ồn", "standard": "ISO 14644-3:2019 §B.11 and the project specification",
     "criterion": "Lux at working plane and dB(A) within the specification",
     "discipline": ELECTRICAL, "cleanroom": False},
    {"code": CT_ELECTRICAL, "label": "Electrical installation testing",
     "labelVn": "Thí nghiệm hệ thống điện", "standard": "IEC 60364-6 (TCVN 9358 equivalent)",
     "criterion": "Continuity, insulation resistance, loop impedance and RCD operation all within "
                  "limits, recorded per circuit",
     "discipline": ELECTRICAL, "cleanroom": False},
    {"code": CT_FIRE_CE, "label": "Fire detection & suppression cause-and-effect",
     "labelVn": "Thử nghiệm liên động PCCC", "standard": "Project cause-and-effect matrix",
     "criterion": "Every input drives its specified outputs, witnessed by the authority where "
                  "required",
     "discipline": FIRE, "cleanroom": False},
    {"code": CT_CLEAN_UTILITY, "label": "Clean utility pressure, purity & passivation",
     "labelVn": "Thử áp & độ tinh khiết tiện ích sạch",
     "standard": "USP <1231> / EP for water; ISO 8573 for compressed air",
     "criterion": "Pressure and leak test passed; purity at every user point within the "
                  "specification; passivation certified",
     "discipline": CLEAN_UTILITIES, "cleanroom": True},
    {"code": CT_IQ, "label": "Installation qualification (IQ)",
     "labelVn": "Thẩm định lắp đặt", "standard": "EU GMP Annex 15 / PIC/S",
     "criterion": "Installed as designed, against approved drawings, with all documentation and "
                  "calibration certificates present",
     "discipline": VALIDATION, "cleanroom": True},
    {"code": CT_OQ, "label": "Operational qualification (OQ)",
     "labelVn": "Thẩm định vận hành", "standard": "EU GMP Annex 15 / PIC/S",
     "criterion": "Operates throughout its specified range, alarms and interlocks demonstrated",
     "discipline": VALIDATION, "cleanroom": True},
    {"code": CT_PQ, "label": "Performance qualification (PQ)",
     "labelVn": "Thẩm định hiệu năng", "standard": "EU GMP Annex 15 / PIC/S",
     "criterion": "Performs to specification over the specified period under production conditions",
     "discipline": VALIDATION, "cleanroom": True},
)
_TEST_BY_CODE = {t["code"]: t for t in COMMISSIONING_TESTS}

CS_NOT_STARTED = "not_started"
CS_IN_PROGRESS = "in_progress"
CS_PASSED = "passed"
CS_WITNESSED = "witnessed"      # passed AND witnessed by the client or their consultant
CS_FAILED = "failed"
CS_NA = "not_applicable"        # a stated decision, never a blank

COMMISSIONING_DONE = (CS_PASSED, CS_WITNESSED, CS_NA)


def commissioning(ctx):
    """The handover test schedule, and what it is holding up.

    Every row is a test against a named standard with a stated acceptance criterion. A row marked
    NOT APPLICABLE is a DECISION and is recorded as one — a blank is not the same thing, and the
    difference is exactly what a GMP client's auditor asks about.
    """
    ctx = ctx or {}
    rows, done, failed, outstanding = [], 0, [], []
    for r in (ctx.get("tests") or []):
        spec = _TEST_BY_CODE.get(_norm(r.get("testCode")))
        st = _norm(r.get("status")) or CS_NOT_STARTED
        row = {
            "id": r.get("id"),
            "testCode": _norm(r.get("testCode")),
            "label": spec["label"] if spec else (r.get("title") or "Unlisted test"),
            "labelVn": spec["labelVn"] if spec else "",
            "standard": r.get("standard") or (spec["standard"] if spec else ""),
            "criterion": r.get("criterion") or (spec["criterion"] if spec else ""),
            "discipline": _disc(r.get("discipline") or (spec["discipline"] if spec else "")),
            "area": r.get("area") or r.get("room") or "",
            "system": r.get("system") or "",
            "status": st,
            "result": r.get("result") or "",
            "testedOn": r.get("testedOn") or "",
            "witnessedBy": r.get("witnessedBy") or "",
            "certRef": r.get("certRef") or "",
            "gatesFinalAccount": r.get("gatesFinalAccount") not in (False, "false", "0", 0),
            "cleanroom": bool(spec["cleanroom"]) if spec else False,
        }
        # A test recorded as passed with no acceptance criterion behind it is an assertion, not a
        # result. Said here rather than silently accepted, because the certificate goes in the
        # handover file and somebody will read it in an audit years from now.
        row["criterionMissing"] = row["status"] in (CS_PASSED, CS_WITNESSED) and not row["criterion"]
        rows.append(row)
        if st in COMMISSIONING_DONE:
            done += 1
        if st == CS_FAILED:
            failed.append(row)
        if st not in COMMISSIONING_DONE and st != CS_FAILED and row["gatesFinalAccount"]:
            # A failure is reported by `failed` and blocks on its own line. Counting it here as
            # well printed it twice in the blocker list, which is the one list where noise costs.
            outstanding.append(row)

    total = len(rows)
    warnings = []
    if failed:
        warnings.append({
            "code": "commissioning_failed", "severity": "high",
            "msg": "%d test(s) have FAILED. Failed work is not complete however finished it looks, "
                   "and the client will not certify against it." % len(failed),
            "items": [{"itemNo": f["certRef"], "desc": "%s — %s" % (f["label"], f["area"] or "")}
                      for f in failed[:20]]})
    if outstanding:
        warnings.append({
            "code": "commissioning_outstanding", "severity": "medium",
            "msg": "%d test(s) that gate the final account are still outstanding." % len(outstanding),
            "items": [{"itemNo": o["area"], "desc": o["label"]} for o in outstanding[:20]]})
    bad_crit = [r for r in rows if r["criterionMissing"]]
    if bad_crit:
        warnings.append({
            "code": "no_acceptance_criterion", "severity": "medium",
            "msg": "%d test(s) are recorded as passed with no acceptance criterion. A pass against "
                   "nothing is an opinion, and it goes in the handover file."
                   % len(bad_crit),
            "items": [{"itemNo": r["certRef"], "desc": r["label"]} for r in bad_crit[:20]]})
    if not total:
        warnings.append({
            "code": "no_commissioning_schedule", "severity": "medium",
            "msg": "No commissioning or qualification tests are scheduled. On a cleanroom contract "
                   "the last tranche of money follows the room passing its tests, not the last "
                   "panel being fixed."})

    return {"rows": rows, "total": total, "done": done,
            "pct": round(done / total * 100.0, 2) if total else None,
            "failed": failed, "outstanding": outstanding, "warnings": warnings}


# ── what this module will not decide ─────────────────────────────────────────────────────────────

UNRESOLVED = (
    "Price fluctuation (rise and fall). A contract with an escalation clause needs its base date "
    "and its published index series. Neither is held anywhere in this portal, and a fabricated "
    "index moves real money on every certificate.",
    "Liquidated damages. Whether LDs are deducted from a certificate or claimed separately is a "
    "term of the contract and a legal position, not arithmetic.",
    "The tax treatment of retention and of materials on site — see sales_contract.vat_ready(), "
    "which refuses for the same reason and names it.",
)
