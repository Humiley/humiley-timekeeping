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


def _pct1(v):
    """A percentage for a SENTENCE, at one decimal. Kept apart from the rounding used for stored
    figures: a warning reading "59.99999999%" is one nobody finishes."""
    return "{:,.1f}".format(_num(v))


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
    # The trade's own BUDGET, from pm_costs. Margin says whether a trade is making money; budget
    # variance says whether it is doing so by spending more than the job was priced to spend. A
    # trade can be comfortably profitable AND well over its budget, and only one of those two
    # numbers ever appears in a project total.
    bbt = {str(k): r2(v) for k, v in (ctx.get("budgetByTrade") or {}).items()}
    trade_rows = []
    for code in sorted(set(vbt) | set(cbt) | set(bbt), key=lambda c: (c == UNALLOCATED, c)):
        tv, tc, tb = vbt.get(code, 0.0), cbt.get(code, 0.0), bbt.get(code)
        tm = r2(tv - tc)
        trade_rows.append({
            "code": code, "label": discipline_label(code),
            "value": tv, "cost": tc, "margin": tm,
            "budget": tb,
            # None, not 0, when the trade carries no budget — "no plan to measure against" and
            # "exactly on plan" are different facts and the screen prints them differently.
            "budgetVariance": (None if tb is None else r2(tb - tc)),
            "overBudget": bool(tb is not None and tc > tb),
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
    over = [t for t in trade_rows if t["overBudget"]]
    if over:
        warnings.append({
            "code": "trade_over_its_budget", "severity": "high",
            "msg": "%s over budget. A trade can be in profit and still be spending more than the "
                   "job was priced to spend, and the margin alone never shows it."
                   % "; ".join("%s is %s" % (t["label"], _vnd(abs(t["budgetVariance"])))
                               for t in over[:4])})
    unbudgeted = [t for t in trade_rows if t["budget"] is None and t["cost"]]
    if unbudgeted:
        warnings.append({
            "code": "trade_spending_with_no_budget", "severity": "medium",
            "msg": "%s carry cost with no budget line behind them, so nothing measures what they "
                   "were meant to spend." % ", ".join(t["label"] for t in unbudgeted[:4])})
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


# ══════════════════════════════════════════════════════════════════════════════════════════════════
#  INTEGRATED CHANGE CONTROL — PMBOK §4.6
# ══════════════════════════════════════════════════════════════════════════════════════════════════
# The portal has held two registers about the same event and never joined them. `pm_changes` is the
# CHANGE REQUEST: what the change is, what it does to scope, cost and time, and whether the business
# accepted it. `pm_qs_variations` is the COMMERCIAL INSTRUMENT: what we charge the client for it.
# A variation could be agreed at ₫980,000,000 with no impact assessment anywhere behind it, and a
# change request could be approved with nobody raising a variation to bill for the work.
#
# THE ONE THING THIS MUST NOT DO IS SYNC THE TWO NUMBERS.
# `pm_changes.impactCost` is what the change COSTS US — it moves the budget, and pmStatusPDF already
# prints it beside the EVM figures. `pm_qs_variations.agreedValue` is what the CLIENT PAYS. They are
# supposed to differ, and the difference is the margin on the variation. Copying one into the other,
# or flagging every gap between them, would turn the module's most useful comparison into noise.
#
# What IS worth saying is when the price is BELOW the cost. That is a variation being built at a
# loss, it is invisible in a project total, and it is the single most common way a contractor gives
# margin away one instruction at a time.

CR_APPROVED = "approved"
CR_REJECTED = "rejected"
CR_PENDING = "pending"


def _cr_decision(c):
    d = _norm(c.get("decision"))
    return d if d in (CR_APPROVED, CR_REJECTED) else CR_PENDING


def change_control(ctx):
    """Reconcile the variation register against the change-request log.

    Reports, never rewrites. Every finding below is a real state a contractor gets into, and the
    right response to each depends on the contract — which is not something this module knows.

    `ctx`: changes (pm_changes), variations (pm_qs_variations), cutoff.
    """
    ctx = ctx or {}
    cutoff = str(ctx.get("cutoff") or "")[:10]
    changes = list(ctx.get("changes") or [])
    raws = list(ctx.get("variations") or [])

    by_no, by_id = {}, {}
    for c in changes:
        no = str(c.get("crNo") or "").strip()
        if no:
            by_no[no.lower()] = c
        if c.get("id"):
            by_id[c.get("id")] = c

    def _cr_for(raw):
        ref = str(raw.get("crNo") or "").strip()
        return by_no.get(ref.lower()) or by_id.get(raw.get("crId")) or (
            by_id.get(ref) if ref else None)

    linked_cr_ids = set()
    unassessed, at_a_loss, against_rejected, ahead_of_decision, rows = [], [], [], [], []

    for raw in raws:
        v = variation_value(raw)
        cr = _cr_for(raw)
        if cr is not None and cr.get("id"):
            linked_cr_ids.add(cr.get("id"))
        row = {
            "id": v["id"], "voNo": v["voNo"], "title": v["title"], "status": v["status"],
            "agreedValue": raw.get("agreedValue"),
            "amount": v["amount"],
            "timeImpactDays": _num(raw.get("timeImpactDays")),
            "crNo": (cr or {}).get("crNo") or str(raw.get("crNo") or "").strip(),
            "crTitle": (cr or {}).get("title") or "",
            "crDecision": _cr_decision(cr) if cr is not None else None,
            "crImpactCost": _rate((cr or {}).get("impactCost")),
            "crImpactDays": _num((cr or {}).get("impactScheduleDays")) if cr is not None else None,
            "linked": cr is not None,
        }
        rows.append(row)

        # A change being BUILT with no impact assessment behind it. `identified` is excluded: that
        # is somebody noticing a possible change, which is exactly when there is nothing to assess
        # yet. From `instructed` on, the work is happening.
        if not row["linked"] and v["status"] in (V_INSTRUCTED, V_MEASURED, V_PRICED,
                                                 V_SUBMITTED, V_AGREED):
            unassessed.append(row)

        if v["status"] == V_AGREED and row["crDecision"] == CR_REJECTED:
            against_rejected.append(row)
        if v["status"] == V_AGREED and row["crDecision"] == CR_PENDING and row["linked"]:
            ahead_of_decision.append(row)

        # Price below cost. Only where BOTH are known and the variation is agreed — a forecast
        # against an estimate is not a loss, it is two guesses.
        if (v["status"] == V_AGREED and v["amount"] is not None
                and row["crImpactCost"] is not None and row["crImpactCost"] > 0
                and v["amount"] < row["crImpactCost"]):
            at_a_loss.append(dict(row, shortfall=r2(row["crImpactCost"] - v["amount"])))

    # An approved change with money on it and nothing being claimed for it. This is the finding that
    # pays for the whole join: the work is authorised, it is being built, and no variation exists to
    # bill it. It is money left on the table and nothing else in the portal can see it.
    unclaimed = []
    for c in changes:
        if _cr_decision(c) != CR_APPROVED:
            continue
        cost = _rate(c.get("impactCost"))
        if not cost or cost <= 0:
            continue
        if c.get("id") in linked_cr_ids:
            continue
        if not _le(c.get("requestedDate") or c.get("date") or "", cutoff):
            continue
        unclaimed.append({"id": c.get("id"), "crNo": c.get("crNo") or "",
                          "title": c.get("title") or "", "impactCost": r2(cost),
                          "impactDays": _num(c.get("impactScheduleDays")),
                          "requestedDate": c.get("requestedDate") or ""})

    # Time that an agreed variation carries and that no approved change request accounts for. The
    # programme has not been told, and an extension of time nobody claimed is an extension nobody
    # gets — which is how liquidated damages arrive on a job that was delayed by the client.
    time_unclaimed = [r for r in rows
                      if r["status"] == V_AGREED and r["timeImpactDays"] > 0
                      and (r["crDecision"] != CR_APPROVED or not (r["crImpactDays"] or 0))]

    warnings = []
    if unassessed:
        warnings.append({
            "code": "variation_without_change_request", "severity": "high",
            "msg": "%d variation(s) are being built with no change request behind them, so nothing "
                   "has assessed what they do to the budget or the programme."
                   % len(unassessed),
            "items": [{"itemNo": r["voNo"], "desc": r["title"]} for r in unassessed[:20]]})
    if unclaimed:
        warnings.append({
            "code": "approved_change_not_claimed", "severity": "high",
            "msg": "%s of APPROVED change has no variation raised against it. The work is "
                   "authorised and nothing is billing for it."
                   % _vnd(sum(c["impactCost"] for c in unclaimed)),
            "items": [{"itemNo": c["crNo"], "desc": c["title"]} for c in unclaimed[:20]]})
    if at_a_loss:
        warnings.append({
            "code": "variation_agreed_below_cost", "severity": "high",
            "msg": "%d variation(s) are agreed BELOW their assessed cost, %s short in total. A "
                   "project margin cannot show this — it is given away one instruction at a time."
                   % (len(at_a_loss), _vnd(sum(r["shortfall"] for r in at_a_loss))),
            "items": [{"itemNo": r["voNo"], "desc": "%s agreed, %s assessed cost"
                       % (_vnd(r["amount"]), _vnd(r["crImpactCost"]))} for r in at_a_loss[:20]]})
    if against_rejected:
        warnings.append({
            "code": "agreed_against_a_rejected_change", "severity": "high",
            "msg": "%d variation(s) are agreed with the client while the change request behind them "
                   "was REJECTED internally." % len(against_rejected),
            "items": [{"itemNo": r["voNo"], "desc": "change request " + (r["crNo"] or "")}
                      for r in against_rejected[:20]]})
    if ahead_of_decision:
        warnings.append({
            "code": "agreed_ahead_of_the_decision", "severity": "medium",
            "msg": "%d variation(s) were agreed with the client before their change request was "
                   "decided." % len(ahead_of_decision),
            "items": [{"itemNo": r["voNo"], "desc": "change request " + (r["crNo"] or "")}
                      for r in ahead_of_decision[:20]]})
    if time_unclaimed:
        warnings.append({
            "code": "time_impact_not_carried", "severity": "medium",
            "msg": "%d agreed variation(s) carry %d day(s) of time impact that no approved change "
                   "request accounts for. An extension of time nobody claimed is one nobody gets."
                   % (len(time_unclaimed), int(sum(r["timeImpactDays"] for r in time_unclaimed))),
            "items": [{"itemNo": r["voNo"],
                       "desc": "%d day(s)" % int(r["timeImpactDays"])} for r in time_unclaimed[:20]]})

    linked = [r for r in rows if r["linked"]]
    return {
        "rows": rows,
        "linkedCount": len(linked),
        "variationCount": len(rows),
        "unassessed": unassessed,
        "unclaimed": unclaimed,
        "unclaimedValue": r2(sum(c["impactCost"] for c in unclaimed)),
        "agreedBelowCost": at_a_loss,
        "shortfall": r2(sum(r["shortfall"] for r in at_a_loss)),
        "againstRejected": against_rejected,
        "aheadOfDecision": ahead_of_decision,
        "timeNotCarried": time_unclaimed,
        "warnings": warnings,
    }


# ══════════════════════════════════════════════════════════════════════════════════════════════════
#  EARNED VALUE FROM MEASUREMENT — PMBOK §7.4
# ══════════════════════════════════════════════════════════════════════════════════════════════════
# The Cost/EVM tab earns value from a percentage that is, at best, a roll-up of deliverable statuses
# and at worst a number somebody typed. On a remeasurement contract there is a far better answer
# sitting in this module: the work has been MEASURED, line by line, against rates in the contract.
# A value-weighted percentage built from that is the strongest evidence of physical progress the
# company has, and `_pmEvm` already grades its evidence — this adds the grade above the top one.
#
# TWO THINGS IT MUST GET RIGHT, and both are easy to get wrong in the flattering direction:
#
#   MATERIALS ON SITE ARE NOT PROGRESS. A pump delivered and paid for is in the gross valuation and
#   is not built into anything. Counting it as physical progress reports a job further ahead than it
#   is, in exactly the month the cash went out — so physical progress is measured works + agreed
#   variations + approved daywork, and materials are excluded by name.
#
#   TWO PROGRESS FIGURES THAT DISAGREE ARE NOT AVERAGED. When the measurement says 61% and the WBS
#   roll-up says 45%, the mean of the two is a number describing nothing. Both are reported, and the
#   gap is the finding: either the programme has not been updated, or work is being measured that
#   the deliverables do not know about.

EV_BASIS_MEASURED = "measured"


def earned_value(ctx):
    """Physical progress from measurement, and the earned value that follows from it.

    `ctx`:
        measured / variations / daywork / materials   the valuation's four parts
        revisedContractSum                            what the job is worth now
        bac                                            budget at completion (OUR cost)
        ac                                             actual cost to date
        independentPct / independentBasis              the other progress figure, for comparison

    Returns `pct: None` rather than a number whenever it cannot be computed. An invented percentage
    here would flow straight into EV, CPI and the project's RAG colour.
    """
    ctx = ctx or {}
    measured = r2(ctx.get("measured"))
    variations = r2(ctx.get("variations"))
    daywork = r2(ctx.get("daywork"))
    materials = r2(ctx.get("materials"))
    physical = r2(measured + variations + daywork)      # materials deliberately absent
    gross = r2(physical + materials)

    revised = _rate(ctx.get("revisedContractSum"))
    pct = round(physical / revised * 100.0, 2) if revised else None

    bac = _rate(ctx.get("bac"))
    ac = _rate(ctx.get("ac"))
    ev = None if (pct is None or bac is None) else r2(bac * pct / 100.0)
    cpi = None if (ev is None or not ac) else round(ev / ac, 4)

    ind = ctx.get("independentPct")
    ind = None if ind in (None, "") else round(_num(ind), 2)
    gap = None if (pct is None or ind is None) else round(pct - ind, 2)

    warnings = []
    if pct is None:
        warnings.append({
            "code": "no_measured_progress", "severity": "medium",
            "msg": "The contract sum is not recorded, so measurement cannot be turned into a "
                   "percentage and earned value still comes from the schedule roll-up."})
    if materials and pct is not None:
        warnings.append({
            "code": "materials_excluded_from_progress", "severity": "low",
            "msg": "%s of materials on site is in the valuation and is NOT counted as progress — "
                   "it is delivered and paid for, not built in. Physical progress is %s of a "
                   "%s gross valuation." % (_vnd(materials), _vnd(physical), _vnd(gross))})
    # 5 points is a real divergence and not rounding. Below that, two methods measuring the same job
    # are agreeing as closely as two methods ever do.
    if gap is not None and abs(gap) >= 5:
        warnings.append({
            "code": "progress_methods_disagree", "severity": "high",
            # The caller names the other source, so the sentence takes it whole rather than
            # wrapping it in words of its own — "the the project's own percent complete roll-up"
            # is what happens when a template assumes it will be handed a single noun.
            "msg": "Measurement says the job is %.1f%% built; %s says %.1f%%. They are %.1f points "
                   "apart. Either the programme has not been updated, or work is being measured "
                   "that the deliverables do not know about — the two are not averaged."
                   % (pct, ctx.get("independentBasis") or "the schedule roll-up", ind, abs(gap))})
    if ev is not None and ac and cpi is not None and cpi < 0.95:
        warnings.append({
            "code": "measured_cpi_below_one", "severity": "high",
            "msg": "Against measured progress the cost performance index is %.2f: %s earned for %s "
                   "spent." % (cpi, _vnd(ev), _vnd(ac))})

    return {
        "physicalToDate": physical,
        "grossToDate": gross,
        "materialsExcluded": materials,
        "revisedContractSum": revised,
        "pct": pct,
        "basis": EV_BASIS_MEASURED,
        "bac": bac, "ac": ac, "ev": ev, "cpi": cpi,
        # Named the way _pmEvm names it, because the screens share one convention: an index is
        # printed through _pmIndexTxt(value, measurable) and NEVER bare. A confident 1.00 with
        # nothing behind it is the failure tests/evm_index_honesty.js exists to stop, and a
        # different-but-equivalent guard of my own would sit outside that check.
        "cpiMeasurable": cpi is not None,
        "independentPct": ind,
        "independentBasis": ctx.get("independentBasis") or "",
        "gap": gap,
        "warnings": warnings,
        # Said in the payload, because the number leaves this module and lands on an EVM screen
        # measured in OUR money: the percentage is value-weighted from the CLIENT's rates, which is
        # what makes it a good measure of physical progress and not a measure of cost.
        "note": "Percent complete is value-weighted from measured quantities at contract rates, "
                "excluding materials on site. Earned value applies it to the budget at completion.",
    }


# ══════════════════════════════════════════════════════════════════════════════════════════════════
#  EXTENSION OF TIME — PMBOK §6.6, and the distinction the whole thing turns on
# ══════════════════════════════════════════════════════════════════════════════════════════════════
# A variation carries `timeImpactDays`. That is a CLAIM FOR TIME. It is not an extension of time.
#
# Only the client GRANTING an extension moves the contract completion date, and until they do, the
# contractor is still liable for finishing on the original one — while building work that cannot be
# finished by then. That gap is the single most expensive thing on a construction contract and it is
# invisible in every register the portal had: the variation register shows the money, the programme
# shows the dates, and nothing put "we have claimed 46 days and been granted 21" on one screen.
#
# It is exactly the same shape as instructed-versus-agreed on the money side, and it is reported the
# same way: the claim is exposure, the grant is a fact, and the difference is named.
#
# LIQUIDATED DAMAGES. Days late multiplied by a rate the contract states, capped where the contract
# states a cap, is ARITHMETIC and is computed. WHETHER those damages are deducted from a payment
# certificate, set off, or claimed separately is a legal position under the contract and is NOT
# computed — see UNRESOLVED. The figure is labelled exposure and never liability.


def _days_between(a, b):
    """Whole days from ISO date a to ISO date b, or None if either is missing or unparseable.

    Deliberately not a fallback to 0: "no dates" and "on time" are different facts, and a 0 here
    would report a project with no programme as finishing exactly on the day.
    """
    import datetime
    try:
        d1 = datetime.date(*[int(x) for x in str(a)[:10].split("-")])
        d2 = datetime.date(*[int(x) for x in str(b)[:10].split("-")])
    except (ValueError, TypeError, AttributeError):
        return None
    return (d2 - d1).days


def _add_days(iso, n):
    import datetime
    try:
        d = datetime.date(*[int(x) for x in str(iso)[:10].split("-")])
    except (ValueError, TypeError, AttributeError):
        return None
    return (d + datetime.timedelta(days=int(n or 0))).isoformat()


def extension_of_time(ctx):
    """What has been claimed, what has been granted, and how late the job is against each.

    `ctx`:
        contractCompletion   the date in the contract (pm_projects.endPlanned)
        forecastCompletion   when the programme now says it finishes
        variations           the register; timeImpactDays is CLAIMED, eotGrantedDays is GRANTED
        changes              approved change requests may also carry granted days
        ldPerDay / ldCap     liquidated damages, only if the contract states them
        cutoff
    """
    ctx = ctx or {}
    cutoff = str(ctx.get("cutoff") or "")[:10]
    original = str(ctx.get("contractCompletion") or "")[:10] or None
    forecast = str(ctx.get("forecastCompletion") or "")[:10] or None

    claimed, granted, rows = 0.0, 0.0, []
    for raw in (ctx.get("variations") or []):
        v = variation_value(raw)
        c_days = _num(raw.get("timeImpactDays"))
        g_days = _num(raw.get("eotGrantedDays"))
        if not c_days and not g_days:
            continue
        # A claim only counts once the variation itself is real work — an idea nobody instructed
        # carries no time either.
        counts = v["status"] in (V_INSTRUCTED, V_MEASURED, V_PRICED, V_SUBMITTED, V_AGREED)
        if counts and _le(raw.get("instructedOn") or v["agreedOn"], cutoff):
            claimed += c_days
        if g_days and _le(raw.get("eotGrantedOn") or "", cutoff):
            granted += g_days
        rows.append({"id": v["id"], "voNo": v["voNo"], "title": v["title"], "status": v["status"],
                     "claimedDays": c_days, "grantedDays": g_days,
                     "eotRef": raw.get("eotRef") or "",
                     "eotGrantedOn": raw.get("eotGrantedOn") or "",
                     "outstandingDays": max(0.0, c_days - g_days)})

    # An approved change request may grant time directly, without a variation behind it.
    for c in (ctx.get("changes") or []):
        if _cr_decision(c) != CR_APPROVED:
            continue
        g = _num(c.get("eotGrantedDays"))
        if g and _le(c.get("eotGrantedOn") or c.get("requestedDate") or "", cutoff):
            granted += g

    revised = _add_days(original, granted) if original else None
    # Delay against the date we are actually contracted to: the ORIGINAL plus what has been GRANTED.
    delay = _days_between(revised, forecast) if (revised and forecast) else None
    delay = max(0, delay) if delay is not None else None
    # And against the original, so the two are visible side by side — the difference between them
    # is precisely what the granted extension is worth.
    delay_vs_original = _days_between(original, forecast) if (original and forecast) else None
    delay_vs_original = max(0, delay_vs_original) if delay_vs_original is not None else None

    ld_rate = _rate(ctx.get("ldPerDay"))
    ld_cap = _rate(ctx.get("ldCap"))
    ld = None
    if ld_rate is not None and ld_rate > 0 and delay:
        ld = r2(ld_rate * delay)
        if ld_cap is not None and ld_cap > 0:
            ld = min(ld, r2(ld_cap))

    outstanding = r2(claimed - granted)
    warnings = []
    if not original:
        warnings.append({
            "code": "no_contract_completion", "severity": "medium",
            "msg": "No contract completion date is recorded, so nothing can say whether this job is "
                   "late or how much extension has been granted against it."})
    if outstanding > 0:
        warnings.append({
            "code": "time_claimed_not_granted", "severity": "high",
            "msg": "%d day(s) of time have been claimed and not granted. Until the client grants "
                   "them the contract completion date has not moved, and the work is being built "
                   "against the original one." % int(outstanding)})
    if delay:
        warnings.append({
            "code": "forecast_past_the_revised_completion", "severity": "high",
            "msg": "The programme forecasts completion %d day(s) after the revised contract date "
                   "of %s.%s" % (delay, revised,
                                 (" Liquidated damages exposure at the contract rate is %s."
                                  % _vnd(ld)) if ld else "")})
    if delay and ld is None:
        warnings.append({
            "code": "no_ld_rate", "severity": "medium",
            "msg": "The job is forecast late and the contract's liquidated damages rate is not "
                   "recorded, so the exposure cannot be put in money."})
    if ld is not None and ld_cap and ld >= r2(ld_cap):
        warnings.append({
            "code": "ld_at_the_cap", "severity": "high",
            "msg": "Liquidated damages exposure has reached the contract cap of %s. Beyond the cap "
                   "further delay costs no more in damages — which is usually the point at which "
                   "the other remedies in the contract become the risk." % _vnd(ld_cap)})

    return {
        "contractCompletion": original,
        "grantedDays": r2(granted),
        "claimedDays": r2(claimed),
        "outstandingDays": outstanding,
        "revisedCompletion": revised,
        "forecastCompletion": forecast,
        "delayDays": delay,
        "delayVsOriginalDays": delay_vs_original,
        "ldPerDay": ld_rate,
        "ldCap": ld_cap,
        "ldExposure": ld,
        "rows": rows,
        "warnings": warnings,
        "note": "Days CLAIMED are a position; days GRANTED are what moved the completion date. "
                "Liquidated damages here are an exposure at the rate the contract states — whether "
                "they are deducted, set off or claimed separately is a term of the contract.",
    }


# ══════════════════════════════════════════════════════════════════════════════════════════════════
#  RESERVE ANALYSIS — PMBOK §11.7
# ══════════════════════════════════════════════════════════════════════════════════════════════════
# The project already holds a contingency reserve and a management reserve, and nothing has ever
# asked the question they exist to answer: IS WHAT IS LEFT STILL ENOUGH FOR THE RISKS STILL OPEN?
#
# The two reserves are not interchangeable and the difference is not cosmetic. CONTINGENCY covers
# identified risks — it is inside the cost baseline and the project manager spends it. MANAGEMENT
# RESERVE covers what nobody identified; it sits OUTSIDE the baseline and is released by the
# sponsor. Drawing management reserve down for a known risk is how a project reports itself covered
# while spending money it was never authorised to spend, so this never draws it down and says so.


def reserves(ctx):
    """What is left in contingency, and whether it still covers the open threats.

    `ctx`:
        contingencyReserve / managementReserve   from the project
        provisions                               known future losses, from the CVR
        variationShortfall                       agreed below assessed cost, from change control
        openThreatEmv                            expected monetary value of open threats
        openThreatCount
    """
    ctx = ctx or {}
    cont = _rate(ctx.get("contingencyReserve"))
    mgmt = _rate(ctx.get("managementReserve"))
    provisions = r2(ctx.get("provisions"))
    shortfall = r2(ctx.get("variationShortfall"))
    drawn = r2(provisions + shortfall)
    remaining = None if cont is None else r2(cont - drawn)
    emv = r2(ctx.get("openThreatEmv"))
    gap = None if remaining is None else r2(emv - remaining)

    warnings = []
    if cont is None or cont <= 0:
        warnings.append({
            "code": "no_contingency", "severity": "medium",
            "msg": "No contingency reserve is recorded on this project, so there is nothing to "
                   "measure the open risks against. Every risk that materialises comes straight "
                   "out of the margin."})
    elif remaining is not None and remaining < 0:
        warnings.append({
            "code": "contingency_exhausted", "severity": "high",
            "msg": "Contingency is exhausted and %s beyond it has been drawn. From here every "
                   "further provision reduces the margin directly." % _vnd(abs(remaining))})
    elif gap is not None and gap > 0:
        warnings.append({
            "code": "contingency_below_open_risk", "severity": "high",
            "msg": "%s of contingency is left against %s of expected value on %d open threat(s) — "
                   "short by %s. That is the reserve question, and it is the one a project total "
                   "never asks." % (_vnd(remaining), _vnd(emv),
                                    int(_num(ctx.get("openThreatCount"))), _vnd(gap))})
    if mgmt and (provisions or shortfall):
        warnings.append({
            "code": "management_reserve_is_not_for_this", "severity": "low",
            "msg": "%s of management reserve is held and is deliberately NOT drawn down here. It "
                   "covers what nobody identified and is released by the sponsor; spending it on a "
                   "known risk reports the project covered with money it was not authorised to "
                   "spend." % _vnd(mgmt)})

    return {
        "contingencyReserve": cont,
        "managementReserve": mgmt,
        "provisions": provisions,
        "variationShortfall": shortfall,
        "drawn": drawn,
        "remaining": remaining,
        "drawnPct": (round(drawn / cont * 100.0, 2) if cont else None),
        "openThreatEmv": emv,
        "openThreatCount": int(_num(ctx.get("openThreatCount"))),
        "shortfallAgainstRisk": (gap if (gap is not None and gap > 0) else 0.0),
        "adequate": (None if remaining is None else remaining >= emv),
        "warnings": warnings,
        "note": "Contingency is inside the cost baseline and covers identified risks. Management "
                "reserve is outside it, covers what nobody identified, and is released by the "
                "sponsor — it is never drawn down by this analysis.",
    }


# ══════════════════════════════════════════════════════════════════════════════════════════════════
#  THE NOTICE CLOCK — the entitlement you lose by being late rather than by being wrong
# ══════════════════════════════════════════════════════════════════════════════════════════════════
# Under almost every standard form, an extension of time must be NOTIFIED within a stated period of
# the delay event becoming apparent. Miss that window and the entitlement is gone — not weakened,
# GONE — however good the claim, however obviously the client caused the delay, however much money
# it costs. FIDIC 20.1 makes it a condition precedent in terms; NEC's early-warning and compensation
# event clocks work the same way; a Vietnamese contract written off either does too.
#
# So the expensive failure here is not a bad claim. It is a good claim submitted on day 31 of a
# 28-day window, and the reason it happens is that nothing anywhere is counting. The variation
# register knows the instruction date, the contract knows the notice period, and until now no screen
# put those two facts together and said "four days left".
#
# This is the same shape as the OSH module's statutory clock: a duty that starts on an EVENT, runs
# in real time, and is worth nothing the day after it expires. It is therefore reported the same
# way — by how many days are LEFT, loudest while there is still time to act.

NOTICE_OK = "given"
NOTICE_DUE = "due"                # not given, still inside the window
NOTICE_URGENT = "urgent"          # not given, and the window is nearly shut
NOTICE_LAPSED = "lapsed"          # not given, window closed — the entitlement is at risk
NOTICE_NO_PERIOD = "no_period"    # the contract's notice period is not recorded

# Inside this many days of the deadline, "due" becomes "urgent". Three working days is the point at
# which a notice still has to be drafted, checked and served, so it is the last moment a warning is
# any use.
NOTICE_URGENT_WITHIN = 5


def notice_position(ctx):
    """Which time claims still have a notice to serve, and how long is left to serve it.

    `ctx`:
        variations     the register — instructedOn starts the clock, noticeGivenOn stops it
        noticeDays     the contract's notice period, in days
        today          the day to measure from (never read from a clock in here)
    """
    ctx = ctx or {}
    today = str(ctx.get("today") or "")[:10]
    period = _num(ctx.get("noticeDays"))
    rows, lapsed, urgent, due = [], [], [], []

    for raw in (ctx.get("variations") or []):
        v = variation_value(raw)
        days = _num(raw.get("timeImpactDays"))
        # A claim for time is what needs notifying. A variation with no time on it has no clock, and
        # one nobody has instructed has no event to count from.
        if not days or v["status"] not in (V_INSTRUCTED, V_MEASURED, V_PRICED, V_SUBMITTED, V_AGREED):
            continue
        event = str(raw.get("instructedOn") or "")[:10]
        given = str(raw.get("noticeGivenOn") or "")[:10]
        deadline = _add_days(event, period) if (event and period) else None
        left = _days_between(today, deadline) if (deadline and today) else None

        if given:
            state = NOTICE_OK
            # Served, but was it served in time? A late notice is a fact about the claim that the
            # client will raise, so it is recorded rather than quietly counted as done.
            late = (_days_between(deadline, given) or 0) > 0 if deadline else False
        elif not period:
            state, late = NOTICE_NO_PERIOD, False
        elif not event:
            # Nothing to count from. Reported as its own state rather than treated as compliant.
            state, late = NOTICE_NO_PERIOD, False
        elif left is None:
            state, late = NOTICE_DUE, False
        elif left < 0:
            state, late = NOTICE_LAPSED, False
        elif left <= NOTICE_URGENT_WITHIN:
            state, late = NOTICE_URGENT, False
        else:
            state, late = NOTICE_DUE, False

        row = {"id": v["id"], "voNo": v["voNo"], "title": v["title"], "status": v["status"],
               "timeImpactDays": days, "instructedOn": event, "noticeGivenOn": given,
               "noticeRef": raw.get("noticeRef") or "", "noticeDue": deadline,
               "daysLeft": left, "state": state, "servedLate": late}
        rows.append(row)
        if state == NOTICE_LAPSED:
            lapsed.append(row)
        elif state == NOTICE_URGENT:
            urgent.append(row)
        elif state == NOTICE_DUE:
            due.append(row)

    warnings = []
    if lapsed:
        warnings.append({
            "code": "notice_period_lapsed", "severity": "high",
            "msg": "%d time claim(s) worth %d day(s) have passed their notice period with no notice "
                   "served. Under most contracts that entitlement is gone — not weakened, gone — "
                   "however good the claim."
                   % (len(lapsed), int(sum(r["timeImpactDays"] for r in lapsed))),
            "items": [{"itemNo": r["voNo"], "desc": "%s — notice was due %s"
                       % (r["title"][:40], r["noticeDue"])} for r in lapsed[:20]]})
    if urgent:
        warnings.append({
            "code": "notice_period_closing", "severity": "high",
            "msg": "%d notice(s) are due within %d day(s). This is the last point at which one can "
                   "still be drafted, checked and served."
                   % (len(urgent), NOTICE_URGENT_WITHIN),
            "items": [{"itemNo": r["voNo"], "desc": "%d day(s) left" % (r["daysLeft"] or 0)}
                      for r in urgent[:20]]})
    served_late = [r for r in rows if r["servedLate"]]
    if served_late:
        warnings.append({
            "code": "notice_served_late", "severity": "medium",
            "msg": "%d notice(s) were served after the contract's period had run. The client can be "
                   "expected to raise that against the claim." % len(served_late),
            "items": [{"itemNo": r["voNo"], "desc": "due %s, served %s"
                       % (r["noticeDue"], r["noticeGivenOn"])} for r in served_late[:20]]})
    if rows and not period:
        warnings.append({
            "code": "no_notice_period", "severity": "medium",
            "msg": "The contract's notice period for extensions of time is not recorded, so nothing "
                   "can say how long is left to serve one. It is a number in the contract and it "
                   "decides whether a good claim survives."})

    return {
        "rows": rows,
        "noticeDays": period or None,
        "lapsed": lapsed, "urgent": urgent, "due": due,
        "servedLate": served_late,
        "atRiskDays": r2(sum(r["timeImpactDays"] for r in lapsed)),
        "warnings": warnings,
        "note": "A notice is a condition precedent under most standard forms. The claim that is "
                "lost is almost never the weak one — it is the good one served on day 31 of a "
                "28-day window.",
    }


# ══════════════════════════════════════════════════════════════════════════════════════════════════
#  THE COMMERCIAL EXPOSURES, IN ONE LIST
# ══════════════════════════════════════════════════════════════════════════════════════════════════
# Every figure below is already computed somewhere on this tab and reviewed by nobody, because it
# lives on a commercial screen rather than on the risk register the project actually walks through
# every week. This gathers them into one shape a person can act on — and deliberately does NOT
# create risk records: a register filled automatically is a register with no owners, and the first
# thing anybody does with one is stop reading it.

EXPOSURE_KINDS = (
    {"code": "quality_at_risk", "label": "Measured work under an open non-conformance",
     "labelVn": "Khối lượng đã đo bóc đang có phiếu không phù hợp",
     "category": "Quality", "why": "A client's quantity surveyor can defend deducting this."},
    {"code": "not_released", "label": "Measured work never released past its inspection",
     "labelVn": "Khối lượng chưa được nghiệm thu qua điểm dừng",
     "category": "Quality", "why": "Claimed against bill lines whose hold point was never signed."},
    {"code": "variation_exposure", "label": "Instructed variation work with no agreed price",
     "labelVn": "Phát sinh đã chỉ thị chưa thống nhất giá",
     "category": "Commercial", "why": "Being built now, and cannot be claimed until it is agreed."},
    {"code": "approved_not_claimed", "label": "Approved change with no variation raised",
     "labelVn": "Thay đổi đã duyệt chưa lập phát sinh",
     "category": "Commercial", "why": "Authorised work that nothing is billing for."},
    {"code": "under_certified", "label": "Claimed and not certified",
     "labelVn": "Đã đề nghị nhưng chưa được xác nhận",
     "category": "Commercial", "why": "The client has certified less than was applied for."},
    {"code": "ld_exposure", "label": "Liquidated damages at the contract rate",
     "labelVn": "Phạt chậm tiến độ theo đơn giá hợp đồng",
     "category": "Schedule", "why": "The programme forecasts completion after the revised date."},
    {"code": "notice_lapsed", "label": "Time entitlement lost to a lapsed notice",
     "labelVn": "Mất quyền gia hạn do quá hạn thông báo",
     "category": "Schedule", "why": "The notice period ran out before a notice was served."},
    {"code": "contingency_short", "label": "Contingency below the open risk",
     "labelVn": "Dự phòng thấp hơn rủi ro đang mở",
     "category": "Commercial", "why": "What is left will not cover the threats already identified."},
)
_EXPOSURE_BY_CODE = {e["code"]: e for e in EXPOSURE_KINDS}


def exposures(ctx):
    """The module's quantified exposures, in one list, biggest first.

    Amounts come from the reports that already computed them — nothing is recalculated here, so a
    figure on this list and the figure on the screen it came from cannot disagree.
    """
    ctx = ctx or {}
    raw = {
        "quality_at_risk": _num(ctx.get("qualityAtRisk")),
        "not_released": _num(ctx.get("notReleased")),
        "variation_exposure": _num(ctx.get("variationExposure")),
        "approved_not_claimed": _num(ctx.get("approvedNotClaimed")),
        "under_certified": _num(ctx.get("underCertified")),
        "ld_exposure": _num(ctx.get("ldExposure")),
        "contingency_short": _num(ctx.get("contingencyShortfall")),
    }
    out = []
    for code, amount in raw.items():
        if amount <= 0:
            continue
        spec = _EXPOSURE_BY_CODE[code]
        out.append({"code": code, "label": spec["label"], "labelVn": spec["labelVn"],
                    "category": spec["category"], "why": spec["why"],
                    "amount": r2(amount), "unit": "money"})

    # Time is an exposure too and is NOT money. It is carried with its own unit rather than priced
    # at some assumed daily cost — a day of delay only becomes money through a rate somebody agreed.
    lapsed_days = _num(ctx.get("noticeLapsedDays"))
    if lapsed_days > 0:
        spec = _EXPOSURE_BY_CODE["notice_lapsed"]
        out.append({"code": "notice_lapsed", "label": spec["label"], "labelVn": spec["labelVn"],
                    "category": spec["category"], "why": spec["why"],
                    "amount": r2(lapsed_days), "unit": "days"})

    out.sort(key=lambda e: (e["unit"] != "money", -e["amount"]))
    return {
        "items": out,
        "moneyTotal": r2(sum(e["amount"] for e in out if e["unit"] == "money")),
        "daysTotal": r2(sum(e["amount"] for e in out if e["unit"] == "days")),
        # Stated, because the sum is a sum of DIFFERENT things: some of it is money a client may
        # deduct, some is money nobody has billed, and they do not add up to a single loss.
        "note": "These are separate exposures, not one number. Some is value a client can defend "
                "deducting, some is work nobody is billing for, and some is time. Adding them "
                "produces a figure that describes no single event.",
    }


# ══════════════════════════════════════════════════════════════════════════════════════════════════
#  THE BACK-TO-BACK POSITION — PMBOK §12.3 Control Procurements
# ══════════════════════════════════════════════════════════════════════════════════════════════════
# A main contractor's money leaves through its subcontractors and arrives from its client, and the
# two are certified by different people a month apart. The portal held both registers — packages in
# pm_procurement, certificates in pm_procurement_payments — and nothing had ever put them beside
# each other, or beside the measure. A certificate did not even record the package it was against.
#
# Four questions, and each one is a way a profitable job runs out of cash:
#
#   1. Have we certified a subcontractor for more than we bought from him? Either somebody varied
#      the subcontract and never wrote it down, or we have over-certified. Both need naming.
#   2. Are we holding the retention the subcontract entitles us to? Retention is the security
#      against defects and against the subcontractor failing. Certified without deducting it, it is
#      gone — and nothing was checking, because the deduction is typed by hand on each certificate.
#   3. Have we certified a trade OUT ahead of measuring it IN? A subcontractor's measure and our
#      own measure of the same physical work should track, with our margin between them. Certified
#      out above valued in means we are paying for work we are not billing.
#   4. Across the job, does what we have certified out sit inside what the client has certified in?
#
# It never restates a certificate. A retention shortfall is REPORTED — the figure the subcontract
# implies against the figure actually deducted — because correcting it here would produce a net
# certified that disagrees with the piece of paper the subcontractor was paid against.

# A certificate that is only SUBMITTED is a subcontractor's claim. It is not our liability, for the
# same reason a submitted application of ours is not the client's. They are counted apart.
SUB_OWED = ("certified", "paid")
SUB_CLAIMED = ("submitted",)

# A subcontract variation. Deliberately a SHORTER lifecycle than our own VARIATION_FLOW: we are the
# employer down this chain, so there is no submit-and-wait — we instruct, and we agree a price.
# Only an AGREED variation changes what the package is worth, for the same reason only an agreed
# client variation enters a valuation. An instructed one is an exposure and is reported as one.
SUBVO_INSTRUCTED = "instructed"
SUBVO_AGREED = "agreed"
SUBVO_REJECTED = "rejected"
SUBVO_STATUSES = (SUBVO_INSTRUCTED, SUBVO_AGREED, SUBVO_REJECTED)


def subcontract_position(ctx):
    """The subcontract commitment, what has been certified against it, and how that sits against
    both our own measure and the client's certificate.

    ctx: packages (pm_procurement), certificates (pm_procurement_payments), subVariations
    (pm_qs_subvo), valueByTrade {code: value we have valued in}, clientCertified (gross certified
    BY the client, or None), retentionFromUs (retention the client is holding), cutoff.
    """
    ctx = ctx or {}
    cutoff = str(ctx.get("cutoff") or "")[:10]
    valued = ctx.get("valueByTrade") or {}
    warn = []

    def w(code, severity, msg, **extra):
        warn.append(dict({"code": code, "severity": severity, "msg": msg}, **extra))

    # ── the packages ─────────────────────────────────────────────────────────────────────────────
    rows, by_no = [], {}
    for p in (ctx.get("packages") or []):
        no = str(p.get("pkgNo") or "").strip()
        r = {"id": p.get("id"), "pkgNo": no, "title": p.get("title") or "",
             "vendor": p.get("vendor") or "", "type": p.get("type") or "",
             "status": p.get("status") or "", "discipline": _disc(p.get("discipline")),
             # `_rate`, not `_num`: a package with no value recorded is not a package worth nil.
             "value": _rate(p.get("value")), "retentionPct": _rate(p.get("retentionPct")),
             "certifiedGross": 0.0, "retentionHeld": 0.0, "certifiedNet": 0.0,
             "paidNet": 0.0, "submitted": 0.0, "certs": 0,
             "variations": 0.0, "variationsPending": 0.0, "variationCount": 0}
        rows.append(r)
        key = _norm(no)
        if not key:
            continue
        if key in by_no:
            w("duplicate_package_no", "medium",
              "Package number %s is on more than one package, so a certificate quoting it cannot "
              "be matched to one of them." % no, pkgNo=no)
        else:
            by_no[key] = r

    # ── the subcontract variations ───────────────────────────────────────────────────────────────
    # Read BEFORE the certificates, because what a package is worth is what decides whether a
    # certificate against it is too big.
    subvo_orphans = []
    for v in (ctx.get("subVariations") or []):
        ref = str(v.get("subVoNo") or "").strip() or "(no number)"
        status = _norm(v.get("status")) or SUBVO_INSTRUCTED
        if status == SUBVO_REJECTED:
            continue
        # An agreed variation is dated by its agreement; an instructed one by the instruction.
        on = v.get("agreedOn") if status == SUBVO_AGREED else v.get("instructedOn")
        if not _le(on, cutoff):
            continue
        # `_rate`, not `_num`: a variation nobody has priced is not a variation worth nil, and
        # adding it at zero would make a package look explained when it is not.
        amt = _rate(v.get("value"))
        r = by_no.get(_norm(v.get("pkgNo")))
        if r is None:
            subvo_orphans.append(ref)
            continue
        if amt is None:
            w("subcontract_variation_unpriced", "high",
              "Subcontract variation %s on %s carries no value, so it cannot change what the "
              "package is worth and cannot explain a certificate against it."
              % (ref, r["pkgNo"] or r["title"]), pkgNo=r["pkgNo"], subVoNo=ref)
            continue
        r["variationCount"] += 1
        if status == SUBVO_AGREED:
            r["variations"] += amt
        else:
            r["variationsPending"] += amt
    if subvo_orphans:
        w("subcontract_variation_no_package", "high",
          "%d subcontract variation(s) name no package in the register, so they change nothing "
          "and explain nothing: %s."
          % (len(subvo_orphans), ", ".join(sorted(subvo_orphans)[:6])), subVoNos=subvo_orphans)

    # ── the certificates ─────────────────────────────────────────────────────────────────────────
    # Orphans are counted in the PROJECT totals and excluded only from the package rows. The money
    # is owed whether or not anybody typed a package number on it, and dropping it from the total
    # would understate the very exposure this report exists to state.
    orphan_gross = orphan_net = orphan_ret = 0.0
    orphans, undated = [], []
    for c in (ctx.get("certificates") or []):
        ref = str(c.get("certNo") or "").strip() or "(no number)"
        if cutoff and not str(c.get("certDate") or "")[:10]:
            undated.append(ref)
            continue
        if not _le(c.get("certDate"), cutoff):
            continue
        status = _norm(c.get("status"))
        gross = _num(c.get("grossClaimed"))
        ret = _num(c.get("retentionDeducted"))
        net = _rate(c.get("netCertified"))
        # The certificate's own arithmetic. Reported, never corrected — the figure the
        # subcontractor was paid against is the one on the paper, whatever it should have been.
        if net is not None and abs(net - (gross - ret)) > 0.5:
            w("certificate_does_not_add_up", "high",
              "Certificate %s states net %s against gross %s less retention %s, which comes to %s."
              % (ref, _vnd(net), _vnd(gross), _vnd(ret), _vnd(gross - ret)), certNo=ref)
        net = net if net is not None else r2(gross - ret)

        key = _norm(c.get("pkgNo"))
        r = by_no.get(key) if key else None
        if r is None:
            if status in SUB_OWED:
                orphan_gross += gross
                orphan_ret += ret
                orphan_net += net
            orphans.append({"certNo": ref, "pkgNo": str(c.get("pkgNo") or "").strip(),
                            "gross": r2(gross), "net": r2(net), "status": c.get("status") or "",
                            # Two different absences, and they are not the same problem: nobody
                            # typed a package, versus somebody typed one that does not exist.
                            "reason": "unknown" if key else "missing"})
            continue
        r["certs"] += 1
        if status in SUB_OWED:
            r["certifiedGross"] += gross
            r["retentionHeld"] += ret
            r["certifiedNet"] += net
            if status == "paid":
                r["paidNet"] += net
        elif status in SUB_CLAIMED:
            r["submitted"] += gross

    if undated:
        w("certificate_no_date", "medium",
          "%d certificate(s) carry no certified date and cannot be shown to fall before %s, so "
          "they are outside this position: %s."
          % (len(undated), cutoff, ", ".join(sorted(undated)[:6])), certNos=sorted(undated))
    for o in orphans:
        if o["reason"] == "missing":
            w("certificate_no_package", "high",
              "Certificate %s for %s names no package, so it cannot be tested against a committed "
              "value or a retention percentage. It is inside the project totals below."
              % (o["certNo"], _vnd(o["gross"])), certNo=o["certNo"])
        else:
            w("certificate_unknown_package", "high",
              "Certificate %s for %s quotes package %s, which is not in the register."
              % (o["certNo"], _vnd(o["gross"]), o["pkgNo"]), certNo=o["certNo"], pkgNo=o["pkgNo"])

    # ── what each package now says ───────────────────────────────────────────────────────────────
    for r in rows:
        for k in ("certifiedGross", "retentionHeld", "certifiedNet", "paidNet", "submitted",
                  "variations", "variationsPending"):
            r[k] = r2(r[k])
        # An unknown commitment plus a variation is still an unknown commitment. Revising from None
        # would turn "nobody recorded what we bought" into a confident figure.
        r["revisedValue"] = (None if r["value"] is None else r2(r["value"] + r["variations"]))
        v = r["revisedValue"]
        # Measured against the REVISED value, which is what the package is now worth.
        r["pctCertified"] = round(r["certifiedGross"] / v * 100.0, 2) if v else None
        r["overBy"] = 0.0
        r["overCertified"] = bool(v and r["certifiedGross"] > v + 0.005)
        if r["overCertified"]:
            r["overBy"] = r2(r["certifiedGross"] - v)
            # The register can finally say WHICH of the two it is — the whole reason it exists.
            if r["variationsPending"] >= r["overBy"] - 0.005 and r["variationsPending"] > 0:
                w("subcontract_over_certified_pending_variation", "high",
                  "%s (%s) is certified %s against %s — %s more, and %s of instructed variations "
                  "are not yet agreed. Agree them and the certificate is covered; do not, and it "
                  "is an over-certification."
                  % (r["pkgNo"] or r["title"], r["vendor"] or "no vendor",
                     _vnd(r["certifiedGross"]), _vnd(v), _vnd(r["overBy"]),
                     _vnd(r["variationsPending"])), pkgNo=r["pkgNo"])
            else:
                w("subcontract_over_certified", "high",
                  "%s (%s) is certified %s against %s including %s of agreed variations — %s more. "
                  "No instructed variation accounts for it: this is an over-certification."
                  % (r["pkgNo"] or r["title"], r["vendor"] or "no vendor",
                     _vnd(r["certifiedGross"]), _vnd(v), _vnd(r["variations"]),
                     _vnd(r["overBy"])), pkgNo=r["pkgNo"])
        elif v is None and (r["certifiedGross"] or r["submitted"]):
            w("subcontract_no_value", "high",
              "%s carries %s of certificates against no committed value, so nothing can say "
              "whether it is over-certified."
              % (r["pkgNo"] or r["title"], _vnd(r["certifiedGross"] or r["submitted"])),
              pkgNo=r["pkgNo"])

        pct = r["retentionPct"]
        # A retention of nil is a contractual fact. A retention nobody recorded is not the same
        # fact, and must not be read as one — with it absent, no shortfall can be computed at all.
        if pct is None:
            r["retentionDue"] = None
            r["retentionShort"] = 0.0
            if r["certifiedGross"]:
                w("subcontract_no_retention_pct", "medium",
                  "%s is certified %s with no retention percentage recorded, so whether the "
                  "security we should be holding is being held cannot be answered."
                  % (r["pkgNo"] or r["title"], _vnd(r["certifiedGross"])), pkgNo=r["pkgNo"])
        else:
            r["retentionDue"] = r2(r["certifiedGross"] * pct / 100.0)
            short = r2(r["retentionDue"] - r["retentionHeld"])
            r["retentionShort"] = short if short > 0.005 else 0.0
            if r["retentionShort"]:
                w("subcontract_retention_short", "high",
                  "%s should be holding %s at %s%% but %s has been deducted — %s of security is "
                  "not being held."
                  % (r["pkgNo"] or r["title"], _vnd(r["retentionDue"]),
                     ("%g" % pct), _vnd(r["retentionHeld"]), _vnd(r["retentionShort"])),
                  pkgNo=r["pkgNo"])

    # ── by trade, against our own measure ────────────────────────────────────────────────────────
    trades, no_trade = {}, []
    for r in rows:
        code = r["discipline"]
        if code == UNALLOCATED and (r["value"] or r["certifiedGross"]):
            no_trade.append(r["pkgNo"] or r["title"])
        d = _DISCIPLINE_BY_CODE.get(code)
        t = trades.setdefault(code, {
            "code": code, "label": d["label"] if d else discipline_label(code),
            "labelVn": d["labelVn"] if d else "Chưa phân bổ", "hex": d["hex"] if d else "#94A3B8",
            "packages": 0, "committed": 0.0, "variations": 0.0, "certifiedOut": 0.0,
            "retentionHeld": 0.0, "noValue": 0})
        t["packages"] += 1
        t["certifiedOut"] += r["certifiedGross"]
        t["retentionHeld"] += r["retentionHeld"]
        t["variations"] += r["variations"]
        if r["value"] is None:
            t["noValue"] += 1
        else:
            t["committed"] += r["value"]

    tr_out = []
    for code in DISCIPLINE_CODES + (UNALLOCATED,):
        if code not in trades:
            continue
        t = trades[code]
        for k in ("committed", "variations", "certifiedOut", "retentionHeld"):
            t[k] = r2(t[k])
        t["revised"] = r2(t["committed"] + t["variations"])
        # UNALLOCATED is forced to None rather than read from `valued`. There is an unallocated row
        # in the bill too, and comparing packages nobody assigned to a trade against bill lines
        # nobody assigned to a trade compares two different absences and reads as a finding.
        t["valuedIn"] = None if code == UNALLOCATED else _rate(valued.get(code))
        t["ahead"] = bool(t["valuedIn"] is not None and t["certifiedOut"] > t["valuedIn"] + 0.005)
        t["aheadBy"] = r2(t["certifiedOut"] - t["valuedIn"]) if t["ahead"] else 0.0
        if t["ahead"]:
            w("certified_out_ahead_of_measure", "high",
              "%s is certified %s to subcontractors against %s measured into our own valuation — "
              "%s more. We are paying for work we are not billing."
              % (t["label"], _vnd(t["certifiedOut"]), _vnd(t["valuedIn"]), _vnd(t["aheadBy"])),
              trade=code)
        tr_out.append(t)
    if no_trade:
        w("package_no_trade", "medium",
          "%d package(s) carry no trade, so they are in the totals but in no trade comparison: %s."
          % (len(no_trade), ", ".join(no_trade[:6])), packages=no_trade)

    # ── the project position ─────────────────────────────────────────────────────────────────────
    committed = r2(sum(r["value"] for r in rows if r["value"] is not None))
    no_value = sum(1 for r in rows if r["value"] is None)
    varied = r2(sum(r["variations"] for r in rows))
    varied_pending = r2(sum(r["variationsPending"] for r in rows))
    cert_gross = r2(sum(r["certifiedGross"] for r in rows) + orphan_gross)
    ret_held = r2(sum(r["retentionHeld"] for r in rows) + orphan_ret)
    cert_net = r2(sum(r["certifiedNet"] for r in rows) + orphan_net)
    paid_net = r2(sum(r["paidNet"] for r in rows))
    submitted = r2(sum(r["submitted"] for r in rows))
    ret_short = r2(sum(r["retentionShort"] for r in rows))

    client = _rate(ctx.get("clientCertified"))
    ret_from_us = _rate(ctx.get("retentionFromUs"))
    if client is None:
        # NOT nil. Nil would say the client has certified nothing, which is a statement about the
        # job; this is a statement about the record, and the two lead to opposite decisions.
        cover = None
        ahead = None
        w("no_client_certificate", "medium",
          "No certificate from the client has been recorded, so what we have certified out cannot "
          "be set against what has been certified in. The position is unknown, not nil.")
    else:
        cover = round(client / cert_gross * 100.0, 2) if cert_gross else None
        ahead = r2(cert_gross - client) if cert_gross > client + 0.005 else 0.0
        if ahead:
            w("certified_out_ahead_of_in", "high",
              "We have certified %s to subcontractors against %s certified to us — %s of this job "
              "is being funded from our own cash."
              % (_vnd(cert_gross), _vnd(client), _vnd(ahead)))

    # A register somebody reads down. The rows arrive in whatever order the store returns them,
    # and a payment position printed in insert order is the same defect the bill had, where a
    # heading rendered below its own items because the screen never sorted what it was given.
    rows.sort(key=lambda r: (not r["pkgNo"], _norm(r["pkgNo"]), _norm(r["title"])))

    return {
        "packages": rows, "trades": tr_out, "orphans": orphans,
        "committed": committed, "packagesWithoutValue": no_value,
        # What we have agreed to pay on top of the packages, and what we have instructed and not
        # yet agreed. The second is an exposure: the work is being done at a price nobody has set.
        "variations": varied, "variationsPending": varied_pending,
        "revisedCommitted": r2(committed + varied),
        "certifiedGross": cert_gross, "retentionHeld": ret_held, "certifiedNet": cert_net,
        "paidNet": paid_net, "outstandingNet": r2(cert_net - paid_net),
        "submittedNotCertified": submitted,
        "retentionShortfall": ret_short,
        "orphanGross": r2(orphan_gross), "orphanCount": len(orphans),
        "clientCertified": client, "coverPct": cover, "certifiedAheadOfClient": ahead,
        # The security position: what we hold from subcontractors against what the client holds
        # from us. Positive means our own retention is more than covered by theirs.
        "retentionFromUs": ret_from_us,
        "retentionNet": (r2(ret_held - ret_from_us) if ret_from_us is not None else None),
        "warnings": warn,
        "cutoff": cutoff,
    }


# ══════════════════════════════════════════════════════════════════════════════════════════════════
#  THE CASH POSITION — what has been certified, what has actually moved, and what is owed
# ══════════════════════════════════════════════════════════════════════════════════════════════════
# A contractor does not fail because a job loses money. It fails because the money leaves before it
# arrives. Every figure this needs already existed and no screen had ever put them on one timeline:
# the client's certificates (with their dates) on one side, the subcontractors' on the other.
#
# The distinction the whole report turns on is CERTIFIED versus PAID. A certificate is a promise
# with a date on it; cash is what is in the account. The valuation series has carried `certifiedOn`
# and `paidOn` since it was built and nothing has ever read the second one.
#
# Two things it refuses to do:
#
#   - It never nets a receivable against a payable and calls the result a cash balance. They fall
#     due on different days to different people, and a positive net has never once stopped a
#     subcontractor suspending for non-payment.
#   - It does not schedule the release of retention. When it comes back depends on practical
#     completion and the defects period, which live in the contract and not in this portal —
#     sales_contract.retention_release() owns that and refuses without those dates.

# A month with no movement is still a month. Printing only the months that had a certificate makes
# a gap look like continuity, and a gap in a contractor's cash-in is the single most important
# thing this report can show.
CASH_MAX_MONTHS = 60


def _month(iso):
    s = str(iso or "")[:7]
    return s if len(s) == 7 and s[4] == "-" else ""


def _month_add(m, n):
    y, mo = int(m[:4]), int(m[5:7])
    t = (y * 12 + mo - 1) + n
    return "%04d-%02d" % (t // 12, t % 12 + 1)


def _month_span(a, b):
    return (int(b[:4]) * 12 + int(b[5:7])) - (int(a[:4]) * 12 + int(a[5:7]))


def cash_flow(ctx):
    """The money in and the money out, on one timeline, with what is owed in each direction.

    ctx: valuations (the series from _qs_series — certifiedGross, certifiedRetention, certifiedOn,
    paidOn, status), subCertificates (pm_procurement_payments), revisedContractSum, certifiedToDate,
    completion (the date the job is due to finish), today, cutoff.
    """
    ctx = ctx or {}
    today = str(ctx.get("today") or "")[:10]
    warn = []

    def w(code, severity, msg, **extra):
        warn.append(dict({"code": code, "severity": severity, "msg": msg}, **extra))

    # ── money IN: the client's certificates ──────────────────────────────────────────────────────
    # A certificate states GROSS TO DATE. The payment it actually generates is the movement since
    # the one before it — adding the gross figures together would count the whole job once a month.
    rows_in, prev_gross, prev_ret = [], 0.0, 0.0
    undated_in = []
    for v in (ctx.get("valuations") or []):
        st = _norm(v.get("status"))
        if st not in (VAL_CERTIFIED, VAL_PAID):
            continue
        gross = _rate(v.get("certifiedGross"))
        if gross is None:
            continue
        # Retention is optional on the record. Absent, the movement is computed on gross alone and
        # the row says so — a retention silently taken as nil would overstate every payment.
        ret = _rate(v.get("certifiedRetention"))
        net_to_date = r2(gross - (ret if ret is not None else 0.0))
        movement = r2(net_to_date - (prev_gross - prev_ret))
        on = str(v.get("certifiedOn") or "")[:10]
        paid_on = str(v.get("paidOn") or "")[:10]
        if not on:
            undated_in.append(v.get("valNo") or v.get("id") or "?")
        rows_in.append({
            "valNo": v.get("valNo") or "", "certifiedOn": on, "paidOn": paid_on,
            "grossToDate": r2(gross), "retentionToDate": (r2(ret) if ret is not None else None),
            "netToDate": net_to_date, "movement": movement,
            "paid": st == VAL_PAID,
            # Certified and not paid is a receivable. Paid with no date is still paid — the date is
            # missing, not the money — so it is counted and the absence is reported separately.
            "receivable": 0.0 if st == VAL_PAID else movement})
        prev_gross, prev_ret = gross, (ret if ret is not None else 0.0)

    if undated_in:
        w("certificate_in_no_date", "medium",
          "%d client certificate(s) carry no certified date, so the money they represent sits in "
          "no month on this timeline: %s." % (len(undated_in), ", ".join(map(str, undated_in[:6]))))
    paid_no_date = [r["valNo"] for r in rows_in if r["paid"] and not r["paidOn"]]
    if paid_no_date:
        w("payment_in_no_date", "medium",
          "%d valuation(s) are marked paid with no payment date. The cash is counted; it simply "
          "lands in no month: %s." % (len(paid_no_date), ", ".join(paid_no_date[:6])))
    no_ret = [r["valNo"] for r in rows_in if r["retentionToDate"] is None]
    if no_ret:
        w("certificate_in_no_retention", "low",
          "%d client certificate(s) do not record the retention held, so their payment is computed "
          "on the gross alone and may be overstated: %s."
          % (len(no_ret), ", ".join(no_ret[:6])))

    # ── money OUT: the subcontractors' certificates ──────────────────────────────────────────────
    # These are per-certificate amounts, not to-date figures, so they add up directly. Opposite
    # shape to the one above, and reading them the same way would be wrong in both directions.
    rows_out, undated_out = [], []
    for c in (ctx.get("subCertificates") or []):
        st = _norm(c.get("status"))
        if st not in SUB_OWED:
            continue
        net = _rate(c.get("netCertified"))
        if net is None:
            net = r2(_num(c.get("grossClaimed")) - _num(c.get("retentionDeducted")))
        on = str(c.get("certDate") or "")[:10]
        if not on:
            undated_out.append(c.get("certNo") or "?")
        rows_out.append({"certNo": c.get("certNo") or "", "pkgNo": c.get("pkgNo") or "",
                         "certifiedOn": on, "paidOn": str(c.get("paidOn") or "")[:10],
                         "net": r2(net), "paid": st == "paid",
                         "payable": 0.0 if st == "paid" else r2(net)})
    out_paid_no_date = [r["certNo"] for r in rows_out if r["paid"] and not r["paidOn"]]
    if out_paid_no_date:
        w("payment_out_no_date", "medium",
          "%d subcontractor certificate(s) are marked paid with no payment date. The cash is "
          "counted; it simply lands in no month: %s."
          % (len(out_paid_no_date), ", ".join(map(str, out_paid_no_date[:6]))))
    if undated_out:
        w("certificate_out_no_date", "medium",
          "%d subcontractor certificate(s) carry no certified date, so what we owe on them sits in "
          "no month: %s." % (len(undated_out), ", ".join(map(str, undated_out[:6]))))

    # ── the timeline ─────────────────────────────────────────────────────────────────────────────
    months = set()
    for r in rows_in:
        for k in ("certifiedOn", "paidOn"):
            if _month(r[k]):
                months.add(_month(r[k]))
    for r in rows_out:
        for k in ("certifiedOn", "paidOn"):
            if _month(r[k]):
                months.add(_month(r[k]))
    periods = []
    if months:
        lo, hi = min(months), max(months)
        span = _month_span(lo, hi)
        if span >= CASH_MAX_MONTHS:
            w("timeline_truncated", "medium",
              "The records span %d months; the timeline shows the first %d from %s."
              % (span + 1, CASH_MAX_MONTHS, lo))
            span = CASH_MAX_MONTHS - 1
        run = 0.0
        for i in range(span + 1):
            m = _month_add(lo, i)
            cert_in = r2(sum(r["movement"] for r in rows_in if _month(r["certifiedOn"]) == m))
            recv = r2(sum(r["movement"] for r in rows_in
                          if r["paid"] and _month(r["paidOn"]) == m))
            cert_out = r2(sum(r["net"] for r in rows_out if _month(r["certifiedOn"]) == m))
            # By the PAYMENT date, never the certificate date. They are different months and
            # the difference is the entire point of this report — the client side has always drawn
            # this distinction and the outgoing side silently did not, so money that left in June
            # was drawn as leaving in April.
            paid_out = r2(sum(r["net"] for r in rows_out
                              if r["paid"] and _month(r["paidOn"]) == m))
            run = r2(run + recv - paid_out)
            periods.append({"period": m, "certifiedIn": cert_in, "receivedIn": recv,
                            "certifiedOut": cert_out, "paidOut": paid_out,
                            # Cash that actually moved, not certificates that were issued.
                            "netCash": r2(recv - paid_out), "cumulativeCash": run})

    receivable = r2(sum(r["receivable"] for r in rows_in))
    payable = r2(sum(r["payable"] for r in rows_out))
    received = r2(sum(r["movement"] for r in rows_in if r["paid"]))
    paid_out_total = r2(sum(r["net"] for r in rows_out if r["paid"]))

    if payable > receivable + 0.005:
        w("owed_out_exceeds_owed_in", "high",
          "We owe subcontractors %s and are owed %s. The difference, %s, has to come from "
          "somewhere else." % (_vnd(payable), _vnd(receivable), _vnd(payable - receivable)))

    # ── the forecast ─────────────────────────────────────────────────────────────────────────────
    # Straight-line, and it says so. Spreading the remaining value evenly is an ASSUMPTION and not
    # a plan — the shape of the real curve lives in the programme, and this module does not read it.
    revised = _rate(ctx.get("revisedContractSum"))
    certified = _rate(ctx.get("certifiedToDate"))
    completion = str(ctx.get("completion") or "")[:10]
    forecast = None
    if not completion:
        w("no_completion_date", "medium",
          "No contract completion date is recorded, so what is left to certify cannot be spread "
          "over anything. The forecast is unavailable, not nil.")
    elif revised is None:
        w("no_contract_sum", "medium",
          "No revised contract sum, so there is no figure to forecast against.")
    else:
        left = r2(revised - (certified or 0.0))
        base = _month(today) or (periods[-1]["period"] if periods else "")
        end = _month(completion)
        n = _month_span(base, end) if (base and end) else 0
        if n <= 0:
            w("completion_passed", "medium",
              "The completion date %s is not in the future, so what is left to certify cannot be "
              "spread over remaining months. %s is still outstanding." % (completion, _vnd(left)))
        elif left <= 0:
            forecast = {"monthsRemaining": n, "remainingValue": left, "perMonth": 0.0,
                        "rows": [], "basis": "nothing left to certify"}
        else:
            per = r2(left / n)
            forecast = {
                "monthsRemaining": n, "remainingValue": left, "perMonth": per,
                "rows": [{"period": _month_add(base, i + 1), "certifiedIn": per}
                         for i in range(n)],
                "basis": "the remaining value spread evenly over the months to completion",
            }
            w("forecast_is_straight_line", "low",
              "The forecast spreads %s evenly over %d month(s) to %s. That is an assumption, not a "
              "plan: it ignores the programme, the retention release and every payment term in the "
              "contract." % (_vnd(left), n, completion))

    return {
        "periods": periods, "certificatesIn": rows_in, "certificatesOut": rows_out,
        "receivable": receivable, "payable": payable,
        "received": received, "paidOut": paid_out_total,
        # Reported side by side and never subtracted into one "cash position": they fall due on
        # different days to different people, and a healthy net has never stopped a subcontractor
        # suspending for non-payment.
        "workingCapitalGap": r2(payable - receivable) if payable > receivable else 0.0,
        "cashToDate": r2(received - paid_out_total),
        "retentionFromUs": _rate(ctx.get("retentionFromUs")),
        "retentionFromSubs": _rate(ctx.get("retentionFromSubs")),
        "forecast": forecast,
        "warnings": warn,
        "note": "Receivable and payable are stated side by side and never netted. They fall due on "
                "different days to different people, and a positive net has never stopped a "
                "subcontractor suspending for non-payment. Retention is shown as held, not "
                "scheduled — when it comes back depends on practical completion and the defects "
                "period, which are in the contract and not in this module.",
    }


# ══════════════════════════════════════════════════════════════════════════════════════════════════
#  MOVING THE PROGRAMME — what a granted extension is allowed to do to the schedule
# ══════════════════════════════════════════════════════════════════════════════════════════════════
# extension_of_time() records the revised completion date and touches nothing else, on purpose: the
# planned finish is what every variance on the job is measured against, and moving it makes a late
# job look on time by rewriting the thing it was late against. The engineering module learned this
# the expensive way — SPI was computed from a live planned date, so moving a slipped date reset it
# to 1.00 with no record that the plan had ever moved.
#
# But an extension the client HAS granted is a real change to the agreed programme, and a schedule
# that never reflects it is a schedule nobody can plan against. Both are true. The reconciliation is
# the one PMBOK §6.6 gives: you may re-plan, but only after the original is frozen where variance
# can still be measured against it.
#
# So this refuses to move anything until a baseline exists, and once it does:
#
#   - Work that is DONE does not move. You cannot delay what has already happened.
#   - Work planned to finish before the delay event does not move — it was never affected.
#   - Every move is DERIVED from the days already applied, so applying twice does not shift twice
#     and the project manager's own re-planning in between is not wiped out.
#
# It computes the moves and returns them. Writing them is the endpoint's job, and it writes only
# what this returns.

# Dated readings are what the site files; progress.py holds the rules for reading them, so
# this module, bi.py and the frontend cannot answer "is it finished" three ways.
import progress

BASELINE_NONE = "no baseline"
HELD_DONE = "already complete"
HELD_NO_DATES = "no planned dates"
HELD_BEFORE_EVENT = "planned to finish before the delay"
HELD_UP_TO_DATE = "already carries the full extension"


def _task_done(t):
    """Has this activity been finished — by ANY of the ways this platform records finishing?

    This module\'s contract is "work that is DONE does not move", and it was asking three questions
    that between them missed the newest answer. An activity driven to 100% through the Master
    Schedule\'s Daily progress table has `pctComplete` untouched (pmDailyEntrySave writes only `log`)
    and `status` untouched (status is DERIVED on every screen and written on none). So the site
    reported the work finished, the portal showed it finished, and this said False — and the
    endpoint above then rewrote the completion date of finished work, on the one path explicitly
    guarded against destroying the record of the plan.

    progress.latest_pct, not accumulated-as-at-today: see its docstring for why the future-dated
    reading is resolved towards LEAVING AN ACTIVITY ALONE. Nothing here reads the clock.
    """
    if str(t.get("actualFinish") or "").strip():
        return True
    if _num(t.get("pctComplete")) >= 100:
        return True
    if progress.latest_pct(t) >= 100:
        return True
    return _norm(t.get("status")) in ("complete", "completed", "done", "closed")


def reschedule_plan(ctx):
    """Which activities a granted extension moves, and where to.

    ctx: tasks (pm_tasks), grantedDays, eventDate (the earliest instruction carrying time impact),
    baselineFrozen (whether the programme has been baselined).
    """
    ctx = ctx or {}
    granted = int(_num(ctx.get("grantedDays")))
    event = str(ctx.get("eventDate") or "")[:10]
    tasks = ctx.get("tasks") or []
    warn = []

    def w(code, severity, msg, **extra):
        warn.append(dict({"code": code, "severity": severity, "msg": msg}, **extra))

    # ── the baseline ─────────────────────────────────────────────────────────────────────────────
    # A task with dates and no baseline is a task whose original plan is about to be lost. This is
    # the ONLY thing that can stop the whole operation, and it stops it rather than proceeding and
    # mentioning it afterwards.
    needs = [t.get("id") for t in tasks
             if (t.get("start") or t.get("finish")) and not t.get("baselineFinish")]
    frozen = bool(ctx.get("baselineFrozen")) and not needs

    moves, held = [], []
    if granted <= 0:
        w("nothing_granted", "medium",
          "No extension has been granted, so there is nothing to move. A claim is not a grant.")
        return {"moves": [], "held": [], "grantedDays": 0, "needsBaseline": needs,
                "baselineFrozen": frozen, "warnings": warn, "eventDate": event}

    for t in tasks:
        tid, name = t.get("id"), t.get("name") or ""
        start, finish = str(t.get("start") or "")[:10], str(t.get("finish") or "")[:10]
        applied = int(_num(t.get("eotShiftApplied")))
        if _task_done(t):
            held.append({"id": tid, "name": name, "reason": HELD_DONE})
            continue
        if not start and not finish:
            held.append({"id": tid, "name": name, "reason": HELD_NO_DATES})
            continue
        # Work planned to finish before the event was never affected by it. Moving it would push
        # completed-on-time activities into the future and make the whole programme unreadable.
        if event and finish and finish < event:
            held.append({"id": tid, "name": name, "reason": HELD_BEFORE_EVENT})
            continue
        delta = granted - applied
        if delta <= 0:
            held.append({"id": tid, "name": name, "reason": HELD_UP_TO_DATE})
            continue
        moves.append({
            "id": tid, "name": name, "days": delta,
            "fromStart": start, "toStart": _add_days(start, delta) if start else "",
            "fromFinish": finish, "toFinish": _add_days(finish, delta) if finish else "",
            "alreadyApplied": applied, "nowApplied": granted})

    if needs:
        w("no_baseline", "high",
          "%d activity(ies) carry planned dates and no baseline. Moving them would destroy the "
          "only record of the plan this job is measured against, so nothing is moved until the "
          "programme is baselined." % len(needs), count=len(needs))
    if not event:
        w("no_delay_event", "medium",
          "No instruction carrying a time impact has a date on it, so nothing can be shown to fall "
          "before the delay. Every unfinished activity is treated as affected.")
    done = [h for h in held if h["reason"] == HELD_DONE]
    if done:
        w("completed_work_not_moved", "low",
          "%d activity(ies) are already complete and are left where they are. You cannot delay "
          "work that has happened." % len(done))
    return {
        "moves": moves if frozen else [],
        "plannedMoves": moves,
        "held": held, "grantedDays": granted, "eventDate": event,
        "needsBaseline": needs, "baselineFrozen": frozen,
        "warnings": warn,
        "note": "The original dates stay in the baseline, where every variance on this job is "
                "measured against them. A revised date beside a frozen baseline is a re-plan; a "
                "revised date on its own is a job that has quietly stopped being late.",
    }


# ══════════════════════════════════════════════════════════════════════════════════════════════════
#  THE COST OF QUALITY — PMBOK §8.1
# ══════════════════════════════════════════════════════════════════════════════════════════════════
# Four categories, and the whole point is the ratio between the first two and the last two:
#
#   PREVENTION   stopping defects happening   — training, method statements, mock-ups, first-offs
#   APPRAISAL    finding them                 — inspection, testing, commissioning, third-party
#   INTERNAL     fixing them before handover  — rework, re-testing, scrapped material, standing time
#   EXTERNAL     fixing them after handover   — call-backs, warranty, damages, a lost client
#
# Money spent on the first two buys down the last two. A job spending nothing on prevention and
# large sums on rework is not a job with bad luck.
#
# ⚠️ THE FIGURE THIS PRODUCES IS ONLY AS GOOD AS THE CLASSIFICATION BEHIND IT, and a cost report
# whose headline is a confident, small number nobody classified is the worst possible outcome: it
# reads as "quality is cheap here". So this reports COVERAGE first — how much of the job's actual
# cost carries a classification at all — and refuses to present ratios as meaningful below it.
#
# The NCR register's own cost is a CROSS-CHECK and is never added to the ledger figure. Two records
# of the same rework, summed, is a number describing an event that happened once.

COQ_PREVENTION = "prevention"
COQ_APPRAISAL = "appraisal"
COQ_INTERNAL = "internal failure"
COQ_EXTERNAL = "external failure"

COQ_CATEGORIES = (
    {"code": COQ_PREVENTION, "label": "Prevention",
     "labelVn": "Phòng ngừa", "hex": "#00B060", "group": "conformance",
     "why": "Stopping defects happening at all: method statements, training, mock-ups, first-off "
            "inspections, samples approved before an order is placed."},
    {"code": COQ_APPRAISAL, "label": "Appraisal",
     "labelVn": "Đánh giá, kiểm tra", "hex": "#3168A8", "group": "conformance",
     "why": "Finding defects: inspection, witness testing, commissioning, third-party "
            "certification, laboratory work, instrument calibration."},
    {"code": COQ_INTERNAL, "label": "Internal failure",
     "labelVn": "Sai hỏng nội bộ", "hex": "#F59E0B", "group": "nonconformance",
     "why": "Putting defects right BEFORE handover: rework, re-testing, scrapped material, "
            "standing time, an activity done twice."},
    {"code": COQ_EXTERNAL, "label": "External failure",
     "labelVn": "Sai hỏng sau bàn giao", "hex": "#EF4444", "group": "nonconformance",
     "why": "Putting defects right AFTER handover: call-backs, warranty work, liquidated damages "
            "for defects, and the client who does not come back."},
)
_COQ_BY_CODE = {c["code"]: c for c in COQ_CATEGORIES}
COQ_CODES = tuple(c["code"] for c in COQ_CATEGORIES)

# Below this share of actual cost carrying a classification, the ratios describe the sample and not
# the job, and saying so is the difference between a measurement and a decoration.
COQ_MEANINGFUL_COVERAGE = 60.0


def _coq_code(v):
    s = _norm(v)
    if s in _COQ_BY_CODE:
        return s
    # The labels people pick in a dropdown, and the shorthand a QS types.
    for c in COQ_CATEGORIES:
        if s == _norm(c["label"]):
            return c["code"]
    if s in ("internal", "rework"):
        return COQ_INTERNAL
    if s in ("external", "warranty", "call-back", "callback"):
        return COQ_EXTERNAL
    return ""


def cost_of_quality(ctx):
    """What quality has cost this job, split the four ways PMBOK §8.1 splits it.

    ctx: costs (pm_costs — `actual` and `coq`), ncrs (pm_quality — `cost`), cutoff.
    """
    ctx = ctx or {}
    cutoff = str(ctx.get("cutoff") or "")[:10]
    warn = []

    def w(code, severity, msg, **extra):
        warn.append(dict({"code": code, "severity": severity, "msg": msg}, **extra))

    # ── from the cost ledger, which is the authority on what things cost ─────────────────────────
    buckets = dict((c, 0.0) for c in COQ_CODES)
    classified = unclassified = undated = 0.0
    unknown_labels = set()
    for c in (ctx.get("costs") or []):
        # `actual` only. A cost line with no actual on it is a commitment, and a commitment has not
        # cost anybody anything yet — the same rule the margin is computed under.
        amt = _num(c.get("actual"))
        if not amt:
            continue
        # An undated line is money that WAS spent. Excluding it — which is the right rule for a
        # measurement, where work claimed in the wrong month moves money — inverts the consequence
        # here: it makes a job with billions booked report a cost of quality of nil. It is counted
        # and the fact that it sits in no period is reported, the same way an orphan certificate is
        # counted in the subcontract totals.
        period = str(c.get("period") or "")[:7]
        if cutoff and period and period > cutoff[:7]:
            continue
        if cutoff and not period:
            undated += amt
        raw = str(c.get("coq") or "").strip()
        code = _coq_code(raw)
        if code:
            buckets[code] += amt
            classified += amt
        else:
            unclassified += amt
            if raw:
                unknown_labels.add(raw)

    total_cost = r2(classified + unclassified)
    coq = r2(sum(buckets.values()))
    conformance = r2(buckets[COQ_PREVENTION] + buckets[COQ_APPRAISAL])
    nonconformance = r2(buckets[COQ_INTERNAL] + buckets[COQ_EXTERNAL])
    coverage = round(classified / total_cost * 100.0, 2) if total_cost else None

    rows = []
    for spec in COQ_CATEGORIES:
        amt = r2(buckets[spec["code"]])
        rows.append(dict(spec, amount=amt,
                         pctOfCoq=(round(amt / coq * 100.0, 2) if coq else None),
                         pctOfCost=(round(amt / total_cost * 100.0, 2) if total_cost else None)))

    if undated:
        w("cost_no_period", "medium",
          "%s of booked cost carries no period, so it cannot be shown to fall before %s. It is "
          "counted here, because it was spent — but this report cannot tell you when."
          % (_vnd(undated), cutoff))
    if unknown_labels:
        w("coq_unknown_class", "medium",
          "%d cost line(s) carry a quality class this module does not recognise, so they are "
          "counted as unclassified: %s."
          % (len(unknown_labels), ", ".join(sorted(unknown_labels)[:6])))

    # ── the coverage statement, which comes before any ratio ─────────────────────────────────────
    meaningful = bool(coverage is not None and coverage >= COQ_MEANINGFUL_COVERAGE)
    if total_cost <= 0:
        w("no_cost_booked", "medium",
          "No actual cost has been booked on this job, so there is nothing to classify and no cost "
          "of quality to report. That is an empty ledger, not a job with no quality cost.")
    elif coverage is not None and coverage < COQ_MEANINGFUL_COVERAGE:
        w("coq_mostly_unclassified", "high",
          "Only %s%% of the %s booked on this job carries a quality classification. The figures "
          "below describe that %s%% and not the job — a small cost of quality here means the "
          "classification is missing, not that quality is cheap."
          % (_pct1(coverage), _vnd(total_cost), _pct1(coverage)))

    # ── the ratio that actually matters ──────────────────────────────────────────────────────────
    # Money on prevention and appraisal buys down failure. A job whose quality spend is nearly all
    # failure is not unlucky; it is paying to fix what it did not pay to prevent.
    failure_share = round(nonconformance / coq * 100.0, 2) if coq else None
    if meaningful and failure_share is not None and failure_share >= 50.0:
        w("failure_cost_dominates", "high",
          "%s%% of what quality has cost on this job was spent putting defects right rather than "
          "preventing or finding them (%s of %s). Money spent on prevention and appraisal buys "
          "this down; nothing else does."
          % (_pct1(failure_share), _vnd(nonconformance), _vnd(coq)))
    if meaningful and buckets[COQ_PREVENTION] <= 0 and nonconformance > 0:
        w("no_prevention_spend", "medium",
          "Nothing on this job is classified as prevention, and %s has been spent on failure. "
          "Either the prevention spend is not being classified, or there is not any."
          % _vnd(nonconformance))
    if buckets[COQ_EXTERNAL] > 0:
        w("external_failure_present", "high",
          "%s of failure cost was incurred AFTER handover. That is the most expensive kind there "
          "is and the only kind the client sees." % _vnd(buckets[COQ_EXTERNAL]))

    # ── the cross-check, which is never added to the figure above ────────────────────────────────
    ncr_cost, ncr_n = 0.0, 0
    for n in (ctx.get("ncrs") or []):
        amt = _rate(n.get("cost"))
        if amt is None:
            continue
        ncr_cost += amt
        ncr_n += 1
    ncr_cost = r2(ncr_cost)
    # Two records of the same rework, added together, is a number describing an event that happened
    # once. They are reported side by side and the gap between them is the finding.
    if ncr_n and nonconformance and abs(ncr_cost - nonconformance) > max(
            1000.0, nonconformance * 0.1):
        w("ncr_cost_disagrees", "medium",
          "The non-conformance register puts the cost of putting defects right at %s; the cost "
          "ledger, at %s. One of the two is incomplete — they are shown side by side and never "
          "added, because both describe the same rework."
          % (_vnd(ncr_cost), _vnd(nonconformance)))

    return {
        "rows": rows,
        "prevention": r2(buckets[COQ_PREVENTION]), "appraisal": r2(buckets[COQ_APPRAISAL]),
        "internalFailure": r2(buckets[COQ_INTERNAL]),
        "externalFailure": r2(buckets[COQ_EXTERNAL]),
        "conformance": conformance, "nonConformance": nonconformance,
        "total": coq, "failureShare": failure_share,
        "classifiedCost": r2(classified), "unclassifiedCost": r2(unclassified),
        "undatedCost": r2(undated),
        "totalCost": total_cost, "coverage": coverage, "meaningful": meaningful,
        "pctOfCost": (round(coq / total_cost * 100.0, 2) if total_cost else None),
        "ncrRegisterCost": ncr_cost if ncr_n else None, "ncrsPriced": ncr_n,
        "warnings": warn,
        "note": "Prevention and appraisal are what a job spends to stop defects and to find them. "
                "Internal and external failure are what it spends because it did not. The ratio "
                "between them is the report; the total on its own says very little. Nothing here "
                "is added to the non-conformance register's own figure — both describe the same "
                "rework, and summing them counts one event twice.",
    }


# ── what this module will not decide ─────────────────────────────────────────────────────────────

UNRESOLVED = (
    "Price fluctuation (rise and fall). A contract with an escalation clause needs its base date "
    "and its published index series. Neither is held anywhere in this portal, and a fabricated "
    "index moves real money on every certificate.",
    "Whether liquidated damages are DEDUCTED from a payment certificate, set off, or claimed "
    "separately. extension_of_time() computes the EXPOSURE — days late at the rate the contract "
    "states, capped where it states a cap, which is arithmetic — and stops there. Which remedy the "
    "employer takes, and when, is a legal position under the contract.",
    "The tax treatment of retention and of materials on site — see sales_contract.vat_ready(), "
    "which refuses for the same reason and names it.",
)
