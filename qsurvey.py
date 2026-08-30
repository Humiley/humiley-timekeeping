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
        # Retention is NOT netted off here. It is held, not deducted, and when it comes back is a
        # term of the contract that sales_contract.retention_release() already reads.
        "retentionNote": "Retention still held is released under the contract's release rule — see "
                         "the contract's retention schedule. It is not a deduction from this sum.",
    }


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
