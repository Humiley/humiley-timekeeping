"""What a job will cost us, and what we should therefore charge for it.

The portal could already price a quotation, budget a project, buy the materials and, since
`labour_cost`, say what a finished job actually cost in people. What it could never do is the
step that comes before all of them: build a tender price up from its parts. The budget in
"Budget vs Actual" was a number somebody typed, so the comparison was actual against an opinion.

An estimate here is a bill of quantities whose rates are BUILT, not guessed:

    material + labour hours + plant + subcontract   →  direct cost per unit
    × quantity                                       →  direct cost of the line
    + site overhead (preliminaries), distributed     →  what the job costs on site
    + company overhead %                             →  what it costs the company
    + risk %                                         →  the cost base
    + profit                                         →  the selling price

Four things in that chain are easy to get wrong, and each one is encoded here rather than left
to whoever is holding the spreadsheet:

**Headings carry no money.** A bill of quantities is a tree — sections, notes and priced items.
Only items carry value. `sales_doc` already learned this on the selling side; the same rule has
to hold here or a section total counts its own children twice.

**Mark-up is not margin.** Adding 20% to cost does not give a 20% margin, it gives 16.7%. That
single confusion is the most expensive arithmetic error in contracting, so the basis is a stored
field with two honest options, and the ACHIEVED margin is computed and reported either way. You
cannot use this module and not be told what margin you are actually taking.

**Some rates are built and some are typed.** During a tender there is never time to build every
line up, and that is fine — but a total that silently mixes the two is not. Every line carries
its basis, and every roll-up says how much of the money underneath it was actually built up.
`labour_cost` made the same promise about recorded-vs-allocated hours for the same reason.

**Distributing preliminaries must reconcile.** Spreading a site-overhead lump across 300 lines in
integer dong loses money to flooring unless it is done deliberately, so the split is largest-
remainder and the parts are asserted to sum to the whole. `labour_cost.apportion` already does
exactly this, so it is imported rather than written twice.

Nothing in this module reads or writes anything. It takes rows and returns numbers, which is what
makes it testable and what makes it the single authority: the browser draws these figures, it
never derives them. That is deliberate — `payroll_calc` exists because the same arithmetic was
once written twice, in two languages, and drifted.
"""

from labour_cost import apportion

# ── Line kinds ────────────────────────────────────────────────────────────────
SECTION = "section"      # a heading. Carries no money of its own.
ITEM = "item"            # a priced line.
NOTE = "note"            # prose. Carries no money and no quantity.
LINE_KINDS = (SECTION, ITEM, NOTE)

# ── Resource kinds — the four things a construction rate is made of ───────────
MATERIAL = "material"
LABOUR = "labour"
PLANT = "plant"
SUBCONTRACT = "subcontract"
RESOURCE_KINDS = (MATERIAL, LABOUR, PLANT, SUBCONTRACT)

# ── How a line's rate came to be ──────────────────────────────────────────────
BUILT = "built-up"       # from resources, so it can be defended line by line
ENTERED = "entered"      # a number somebody typed. Legitimate, but it must say so.

# ── How profit is applied ─────────────────────────────────────────────────────
MARKUP = "markup"        # price = cost x (1 + p)      — p% ON the cost
MARGIN = "margin"        # price = cost / (1 - p)      — p% OF the price
PROFIT_BASES = (MARKUP, MARGIN)


def _num(v, default=0.0):
    """A number, or the default. Blank cells and stray text must not become NaN."""
    try:
        n = float(v)
    except (TypeError, ValueError):
        return default
    if n != n or n in (float("inf"), float("-inf")):
        return default
    return n


def vnd(v):
    """Dong are integers. Half-up, because half-even surprises accountants.

    Rounding once, here, is the point: every figure this module returns is already whole dong,
    so nothing downstream has to decide again and disagree.
    """
    n = _num(v)
    return int(n + 0.5) if n >= 0 else -int(-n + 0.5)


def _pct(v):
    """A percentage as a fraction. 12.5 -> 0.125. Negative percentages are allowed
    (a discount is a negative mark-up) but not silently infinite ones."""
    return _num(v) / 100.0


# ══════════════════════════════════════════════════════════════════════════════
#   1. The rate — what one unit of work costs us
# ══════════════════════════════════════════════════════════════════════════════

def resource_cost(r):
    """What one resource line contributes to the cost of ONE unit of the work.

    quantity per unit x unit cost, plus waste. Waste is allowed on any kind, not only material:
    a labour allowance for rework is the same arithmetic and pretending otherwise just pushes it
    into a fudged unit cost where nobody can see it.
    """
    qty = _num(r.get("qtyPer"))
    cost = _num(r.get("unitCost"))
    waste = _pct(r.get("wastePct"))
    return qty * cost * (1.0 + waste)


def build_up(resources):
    """The cost of one unit, and where it came from.

    Returns whole dong per unit plus the split by resource kind — which is not decoration: it is
    what feeds the material take-off, the labour hours and the project budget categories later.
    """
    by_kind = {k: 0.0 for k in RESOURCE_KINDS}
    hours = 0.0
    for r in resources or []:
        kind = str(r.get("kind") or MATERIAL).strip().lower()
        if kind not in RESOURCE_KINDS:
            kind = MATERIAL
        by_kind[kind] += resource_cost(r)
        if kind == LABOUR:
            # Hours are the one physical quantity in the build-up, and the only one that can be
            # checked against what the timesheets later say. Worth carrying separately.
            hours += _num(r.get("qtyPer")) * (1.0 + _pct(r.get("wastePct")))
    return {
        "unitCost": vnd(sum(by_kind.values())),
        "byKind": {k: vnd(v) for k, v in by_kind.items()},
        "hoursPerUnit": round(hours, 4),
        "resourceCount": len(resources or []),
    }


def price_item(item, resources):
    """One priced line: its direct cost, and whether that cost was built or typed.

    An item with resources is built up from them. An item without falls back to the rate somebody
    entered — which is a normal thing to do under tender pressure, and is recorded as such so that
    no total can quietly imply more rigour than it has.
    """
    qty = _num(item.get("qty"))
    res = list(resources or [])
    if res:
        b = build_up(res)
        basis = BUILT
        unit_cost = b["unitCost"]
        by_kind = b["byKind"]
        hours_per_unit = b["hoursPerUnit"]
    else:
        basis = ENTERED
        unit_cost = vnd(item.get("unitCost"))
        # A typed rate cannot be split by kind — saying it is 100% material would be a lie that
        # then flows into the take-off and the project budget. It is carried as unallocated.
        by_kind = {k: 0 for k in RESOURCE_KINDS}
        hours_per_unit = 0.0
    return {
        "id": item.get("id"),
        "basis": basis,
        "qty": qty,
        "unitCost": unit_cost,
        "directCost": vnd(unit_cost * qty),
        "byKind": {k: vnd(v * qty) for k, v in by_kind.items()},
        "hours": round(hours_per_unit * qty, 3),
        "unallocated": vnd(unit_cost * qty) if basis == ENTERED else 0,
    }


# ══════════════════════════════════════════════════════════════════════════════
#   2. The estimate — direct cost to selling price
# ══════════════════════════════════════════════════════════════════════════════

def priced_items(items):
    """Only the lines that carry money. Sections and notes are structure, not value."""
    return [i for i in (items or []) if str(i.get("kind") or ITEM).strip().lower() == ITEM]


def apply_profit(cost_base, pct, basis):
    """Turn a cost into a price, and be explicit about which of the two things was meant.

    A 20% MARK-UP on 100 is 120, and the margin taken is 16.7%.
    A 20% MARGIN on 100 is 125, and the mark-up applied is 25%.

    Both are legitimate; confusing them is what loses the money. A margin of 100% or more has no
    finite price, so it is refused rather than clamped — a silently capped margin would be a wrong
    number wearing a right one's clothes.
    """
    base = _num(cost_base)
    p = _pct(pct)
    b = str(basis or MARKUP).strip().lower()
    if b == MARGIN:
        if p >= 1.0:
            raise ValueError(
                "A margin of %g%% cannot be priced — margin is a share OF the selling price, so "
                "100%% or more has no finite answer. Use a mark-up if you meant %g%% ON the cost."
                % (_num(pct), _num(pct)))
        return vnd(base / (1.0 - p))
    return vnd(base * (1.0 + p))


def achieved_margin(price, cost_base):
    """The share of the selling price that is not cost. Reported always, whichever basis was used,
    because this is the number the business actually lives on."""
    p = _num(price)
    if p <= 0:
        return 0.0
    return round((p - _num(cost_base)) / p * 100.0, 2)


def summarise(items, resources_by_item=None, markups=None):
    """The whole estimate: every line costed, the mark-ups applied, the price out the other end.

    `markups` carries the commercial decisions:
        siteOverhead   lump sum for preliminaries (site office, supervision, temporary works, HSE)
        overheadPct    company overhead, on direct + preliminaries
        riskPct        contingency, on direct + preliminaries + overhead
        profitPct      profit
        profitBasis    'markup' (on cost) or 'margin' (of price)

    The order matters and is fixed here so two people pricing the same job get the same answer.
    """
    resources_by_item = resources_by_item or {}
    markups = markups or {}

    lines = []
    for it in priced_items(items):
        lines.append(price_item(it, resources_by_item.get(it.get("id")) or []))

    direct = sum(l["directCost"] for l in lines)
    by_kind = {k: sum(l["byKind"][k] for l in lines) for k in RESOURCE_KINDS}
    unallocated = sum(l["unallocated"] for l in lines)
    hours = round(sum(l["hours"] for l in lines), 3)

    # Preliminaries are a cost of the job, not of any one line — but they have to land on the
    # lines or a unit-rate contract cannot be priced at all. Pro-rata to direct cost, in whole
    # dong, summing exactly to the lump.
    site_overhead = vnd(markups.get("siteOverhead"))
    weights = {l["id"]: l["directCost"] for l in lines}
    prelim_share = apportion(site_overhead, weights) if site_overhead and direct > 0 else {}
    if prelim_share:
        assert sum(prelim_share.values()) == site_overhead, "preliminaries did not reconcile"

    on_site = direct + site_overhead
    overhead = vnd(on_site * _pct(markups.get("overheadPct")))
    risk = vnd((on_site + overhead) * _pct(markups.get("riskPct")))
    cost_base = on_site + overhead + risk

    price = apply_profit(cost_base, markups.get("profitPct"), markups.get("profitBasis"))
    profit = price - cost_base

    # How much of this estimate is defensible line by line, and how much is somebody's judgement.
    # A tender that is 90% built up is a different object from one that is 10% built up, and the
    # person signing it is entitled to know which they are holding before they sign.
    built = direct - unallocated
    return {
        "lineCount": len(lines),
        "lines": {l["id"]: l for l in lines},
        "prelimShare": prelim_share,
        "directCost": direct,
        "byKind": by_kind,
        "hours": hours,
        "siteOverhead": site_overhead,
        "onSiteCost": on_site,
        "overhead": overhead,
        "risk": risk,
        "costBase": cost_base,
        "profit": profit,
        "price": price,
        "profitBasis": str(markups.get("profitBasis") or MARKUP).strip().lower(),
        "profitPct": _num(markups.get("profitPct")),
        "achievedMarginPct": achieved_margin(price, cost_base),
        "builtUpCost": built,
        "enteredCost": unallocated,
        "builtUpPct": round(built / direct * 100.0, 1) if direct > 0 else 0.0,
    }


def line_prices(items, resources_by_item=None, markups=None):
    """The selling rate of each line — direct cost plus its share of everything above it.

    A unit-rate contract is signed on these, not on the estimate total, so they have to reconcile:
    the priced lines are asserted to sum back to the estimate price. Mark-ups are distributed on
    the same pro-rata basis as preliminaries, which keeps a cheap line cheap.
    """
    s = summarise(items, resources_by_item, markups)
    lines = s["lines"]
    if not lines:
        return {"lines": {}, "total": 0}
    # Everything above direct cost — preliminaries, overhead, risk and profit — spread on cost.
    above = s["price"] - s["directCost"]
    weights = {lid: l["directCost"] for lid, l in lines.items()}
    if sum(weights.values()) <= 0:
        # Every line is zero-cost (a fully provisional bill). Spread evenly rather than lose it.
        weights = {lid: 1 for lid in lines}
    share = apportion(above, weights)
    out = {}
    for lid, l in lines.items():
        amount = l["directCost"] + share.get(lid, 0)
        qty = l["qty"]
        out[lid] = {
            "directCost": l["directCost"],
            "onCost": share.get(lid, 0),
            "amount": amount,
            # The rate is derived from the amount, never the other way round: rate x qty must not
            # be a third number that disagrees with both.
            "rate": vnd(amount / qty) if qty else amount,
            "basis": l["basis"],
        }
    total = sum(o["amount"] for o in out.values())
    assert total == s["price"], "priced lines (%d) do not sum to the estimate price (%d)" % (total, s["price"])
    return {"lines": out, "total": total}


# ══════════════════════════════════════════════════════════════════════════════
#   3. What the estimate hands to the rest of the business
# ══════════════════════════════════════════════════════════════════════════════

def take_off(items, resources_by_item=None):
    """Every material the job needs, gathered across the whole bill.

    This is the estimate's answer to "what do we have to buy", and it is the same list procurement
    would otherwise rebuild by hand from the drawings. Grouped by material code where there is one,
    else by description and unit — two lines calling the same thing by the same name are one
    purchase.
    """
    resources_by_item = resources_by_item or {}
    out = {}
    for it in priced_items(items):
        qty = _num(it.get("qty"))
        for r in resources_by_item.get(it.get("id")) or []:
            if str(r.get("kind") or "").strip().lower() != MATERIAL:
                continue
            key = (str(r.get("code") or "").strip().upper()
                   or (str(r.get("desc") or "").strip().lower() + "|" + str(r.get("unit") or "").strip().lower()))
            need = _num(r.get("qtyPer")) * qty * (1.0 + _pct(r.get("wastePct")))
            row = out.setdefault(key, {
                "code": str(r.get("code") or "").strip(),
                "desc": str(r.get("desc") or "").strip(),
                "unit": str(r.get("unit") or "").strip(),
                "qty": 0.0, "cost": 0, "lines": 0,
            })
            row["qty"] += need
            row["cost"] += vnd(need * _num(r.get("unitCost")))
            row["lines"] += 1
    for row in out.values():
        row["qty"] = round(row["qty"], 4)
    return sorted(out.values(), key=lambda r: -r["cost"])


def labour_take_off(items, resources_by_item=None):
    """Hours by trade — the estimate's promise about how long the job takes in people.

    Kept separate from the material take-off because it is checked against something different:
    `labour_cost` can later say what the trade actually cost per hour on a finished job, and the
    two numbers side by side are how next year's estimate stops being a guess.
    """
    resources_by_item = resources_by_item or {}
    out = {}
    for it in priced_items(items):
        qty = _num(it.get("qty"))
        for r in resources_by_item.get(it.get("id")) or []:
            if str(r.get("kind") or "").strip().lower() != LABOUR:
                continue
            trade = str(r.get("desc") or "Labour").strip() or "Labour"
            hours = _num(r.get("qtyPer")) * qty * (1.0 + _pct(r.get("wastePct")))
            row = out.setdefault(trade, {"trade": trade, "hours": 0.0, "cost": 0})
            row["hours"] += hours
            row["cost"] += vnd(hours * _num(r.get("unitCost")))
    for row in out.values():
        row["hours"] = round(row["hours"], 2)
        row["rate"] = vnd(row["cost"] / row["hours"]) if row["hours"] else 0
    return sorted(out.values(), key=lambda r: -r["cost"])


# The estimate's resource kinds and the project budget's cost categories are the same four things
# under different names. Mapping them here, once, is what lets a won tender become a budget
# without anybody retyping it — and what stops the two from drifting apart later.
BUDGET_CATEGORY = {
    MATERIAL: "Material",
    LABOUR: "Labor",
    PLANT: "Equipment",
    SUBCONTRACT: "Subcontract",
}


def budget_lines(items, resources_by_item=None, markups=None):
    """The estimate as a project budget: one line per cost category, plus overheads.

    This is the handover. A won tender becomes the baseline the job is then measured against, so
    what is handed over is the COST BASE — direct cost, preliminaries, overhead and risk. Profit
    is deliberately not budgeted: a project that spends its profit has not stayed within budget,
    it has consumed the reason the job was taken.

    A line whose rate was typed rather than built cannot be attributed to a category without
    inventing where the money goes, so it is handed over as its own honest line.
    """
    s = summarise(items, resources_by_item, markups)
    out = []
    for kind in RESOURCE_KINDS:
        amount = s["byKind"][kind]
        if amount:
            out.append({"category": BUDGET_CATEGORY[kind], "amount": amount,
                        "note": "From estimate build-up"})
    if s["enteredCost"]:
        out.append({"category": "Other", "amount": s["enteredCost"],
                    "note": "Lines priced by entered rate — not attributed to a cost category"})
    if s["siteOverhead"]:
        out.append({"category": "Overhead", "amount": s["siteOverhead"],
                    "note": "Preliminaries / site overhead"})
    if s["overhead"]:
        out.append({"category": "Overhead", "amount": s["overhead"],
                    "note": "Company overhead %g%%" % _num((markups or {}).get("overheadPct"))})
    if s["risk"]:
        out.append({"category": "Overhead", "amount": s["risk"],
                    "note": "Risk / contingency %g%%" % _num((markups or {}).get("riskPct"))})
    total = sum(l["amount"] for l in out)
    assert total == s["costBase"], "budget lines (%d) do not sum to the cost base (%d)" % (total, s["costBase"])
    return {"lines": out, "total": total, "excludesProfit": s["profit"]}


# ══════════════════════════════════════════════════════════════════════════════
#   4. The rate library
# ══════════════════════════════════════════════════════════════════════════════

def snapshot(rate):
    """What gets copied into an estimate when a library rate is used.

    A COPY, always. An estimate that referenced the library live would silently reprice itself
    every time somebody updated a supplier quote, so a tender reopened six months later would no
    longer be the tender that was submitted. The same reason `eng_revisions` freeze when they are
    signed and a finalised pay run is immutable: a document that can change after it left the
    building is not a record of anything.
    """
    return {
        "code": str(rate.get("code") or "").strip(),
        "desc": str(rate.get("desc") or rate.get("name") or "").strip(),
        "unit": str(rate.get("unit") or "").strip(),
        "unitCost": vnd(rate.get("unitCost")),
        "kind": str(rate.get("kind") or MATERIAL).strip().lower(),
        "rateId": rate.get("id"),
        "ratePricedOn": str(rate.get("effectiveFrom") or "").strip(),
        "rateSource": str(rate.get("source") or "").strip(),
    }


def stale_rates(resources, library, today=None):
    """Library rates that have moved since the estimate copied them.

    The snapshot rule above is right, and it has a cost: nobody is told when the market has moved.
    This is the other half — a plain list of what changed and by how much, so re-pricing is a
    decision somebody makes rather than something that happens to them.
    """
    by_id = {r.get("id"): r for r in (library or []) if r.get("id")}
    out = []
    for r in resources or []:
        lib = by_id.get(r.get("rateId"))
        if not lib:
            continue
        was, now = vnd(r.get("unitCost")), vnd(lib.get("unitCost"))
        if was == now:
            continue
        out.append({
            "rateId": lib.get("id"),
            "code": str(lib.get("code") or "").strip(),
            "desc": str(lib.get("desc") or lib.get("name") or "").strip(),
            "estimatedAt": was,
            "libraryNow": now,
            "deltaPct": round((now - was) / was * 100.0, 1) if was else None,
        })
    return out
