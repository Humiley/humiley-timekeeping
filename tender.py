"""The two costing models Humiley actually tenders with, and the quotation they produce.

`estimating` prices work built from resources — the right model for installation, where a rate is
material plus labour plus plant. It is the wrong model for the two things this company tenders
most, and both were living in spreadsheets:

  **TRADING** — a product bought abroad and sold in Vietnam. Nothing is "built"; the cost is a
  customs chain. EXW, plus the international leg, gives CIF; CIF converts at today's rate; duty,
  special consumption tax and VAT land on the converted value in that order because each is
  assessed on the running total including the one before it; then the local charges. What comes
  out is the landed cost, and the only honest basis for a selling price.

  **EPC** — a turnkey plant. Cost is a bill of materials per cost centre (civil, MEP, black and
  clean utilities, cleanroom, each production line, QC lab, warehouse), every line carrying its
  own mark-up because a cleanroom and a concrete slab do not earn the same margin. Production
  lines scale, and a line switched off must leave the quotation entirely.

Both end in the same place: a quotation document. That is modelled here once, so the PDF the
customer receives and the figures the company keeps cannot disagree.

Four things are encoded because getting them wrong is expensive and quiet:

**Vietnamese import tax is a cascade, not a sum.** Duty is on CIF. Special consumption tax is on
CIF plus duty. VAT is on CIF plus duty plus SCT. Applying all three to CIF understates the tax on
a dutiable item by millions of dong and the error grows with the duty rate.

**Import VAT is recoverable and must never enter the cost.** It is a receivable from the state,
not a cost of the goods. A landed cost carrying 10% VAT prices the company out of its own market.
It is computed, reported, and deliberately excluded from the landed total.

**An FTA rate only applies if the certificate exists.** The preferential duty is a fact about a
piece of paper, not about the goods. With no C/O form the MFN rate applies, whatever was typed in
the FTA column.

**Mark-up is not margin.** Inherited from `estimating` rather than restated, along with its rule
that the achieved margin is always reported.
"""

import estimating
from estimating import vnd, MARKUP, MARGIN, apply_profit, achieved_margin

TRADING = "trading"
EPC = "epc"
COSTING_TYPES = (TRADING, EPC)

IMPORT = "import"
LOCAL = "local"


def _num(v, default=0.0):
    try:
        n = float(str(v).replace(",", "").strip()) if isinstance(v, str) else float(v)
    except (TypeError, ValueError):
        return default
    if n != n or n in (float("inf"), float("-inf")):
        return default
    return n


def _frac(v):
    """A percentage as a fraction. 5 -> 0.05. Every rate in this module is a PERCENTAGE.

    This was first written to accept either — a fraction like 0.05 or a percentage like 5 — by
    treating anything under 1 as already a fraction. That heuristic is wrong and it is wrong
    silently: an origin charge of 0.5% and a mark-up of 50% are both "0.5", and the rule read the
    first as the second. A 0.3% marine insurance premium became 30% of cargo value, and a 0.5%
    bank charge became half the revenue, which is enough to turn a profitable tender into a loss
    on screen with nothing visibly wrong.

    There is no clever way to tell those two apart, so the ambiguity is removed instead of
    resolved: the field is a percent, it holds a percent. The workbooks stored fractions, but this
    is not a copy of a workbook cell — it is the platform's own storage, and it gets to be
    unambiguous. Sub-1 rates (0.3% insurance, 0.5% customs) are the common case here, which is
    exactly why the heuristic could not be allowed to stand.
    """
    return _num(v) / 100.0


# ══════════════════════════════════════════════════════════════════════════════
#   The master assumptions — one place, as the workbook has one sheet
# ══════════════════════════════════════════════════════════════════════════════

ASSUMPTIONS = [
    # (key, group, label, default, unit, note)
    ("fxUsd", "FX", "USD to VND", 25500, "VND/USD", "Vietcombank selling rate. Update before each quote."),
    ("fxEur", "FX", "EUR to VND", 27800, "VND/EUR", "For European suppliers."),
    ("fxCny", "FX", "CNY to VND", 3550, "VND/CNY", "For China suppliers."),
    ("fxJpy", "FX", "JPY to VND", 170, "VND/JPY", "For Japan suppliers."),

    ("inlandPct", "EXW to CIF", "Inland origin (factory to port)", 1.0, "% of EXW", "Trucking from supplier factory to origin port."),
    ("originPct", "EXW to CIF", "Origin charges (THC, doc)", 0.5, "% of EXW", "Origin terminal handling and documentation."),
    ("freightPct", "EXW to CIF", "International freight", 5.0, "% of EXW", "Sea or air freight, typically 3-8% of cargo value."),
    ("insurancePct", "EXW to CIF", "Insurance", 0.3, "% of EXW", "Marine cargo insurance, typically 0.1-0.3%."),

    ("customsPct", "Local charges", "Customs clearance", 0.5, "% of CIF", "Customs broker fee, often 0.3-0.5% of CIF."),
    ("handlingPct", "Local charges", "Local handling (port THC/CFS)", 0.5, "% of CIF", "Destination terminal handling."),
    ("localTransPct", "Local charges", "Local transport (port to site)", 1.0, "% of CIF", "Trucking from destination port to site."),
    ("bankPct", "Local charges", "Bank charges (TT/LC)", 0.3, "% of CIF", "TT around 0.2-0.3%, LC around 0.8-1.0%."),
    ("inspectPct", "Local charges", "Inspection / SGS", 0.5, "% of CIF", "If pre-shipment or on-site inspection is required."),

    ("dutyPct", "Tax", "Default import duty", 5.0, "%", "Used when the HS code is not in the tariff. Override per line."),
    ("importVatPct", "Tax", "Default import VAT", 10.0, "%", "RECOVERABLE — never part of the landed cost."),
    ("localVatPct", "Tax", "Default local VAT", 10.0, "%", "Local supplier VAT-invoice rate. Also recoverable."),
    ("outputVatPct", "Tax", "Output VAT (sales)", 10.0, "%", "Standard goods 10%. Reduced 5%/8% where applicable."),
    ("citPct", "Tax", "Corporate income tax", 20.0, "%", "Vietnam standard CIT rate."),

    ("markupPct", "Pricing", "Default mark-up on landed cost", 25.0, "%", "Override per line on the quotation."),
    ("discountCapPct", "Pricing", "Discount cap", 10.0, "%", "Maximum discount sales may offer without approval."),

    ("commPct", "Opex", "Sales commission", 2.0, "% of revenue", "Paid to sales upon collection."),
    ("financePct", "Opex", "Bank / finance charges", 0.5, "% of revenue", "Project-level financing cost."),
    ("adminLump", "Opex", "Salary and admin allocation", 30000000, "VND", "Lump sum allocated to this tender."),
    ("warrantyPct", "Opex", "Logistics / warranty reserve", 1.5, "% of revenue", "Provision for after-sales and returns."),
]
ASSUMPTION_DEFAULTS = {k: d for k, _g, _l, d, _u, _n in ASSUMPTIONS}


def assumptions(stored=None):
    """The rates this tender prices with — the stored value where there is one, else the default.

    A missing assumption must not silently become zero. A zero FX rate would price every imported
    item at nothing and the quotation would still add up.
    """
    stored = stored or {}
    out = {}
    for k, _g, _l, default, _u, _n in ASSUMPTIONS:
        v = stored.get(k)
        out[k] = default if v in (None, "") else _num(v, default)
    return out


# ══════════════════════════════════════════════════════════════════════════════
#   1. TRADING — the customs chain
# ══════════════════════════════════════════════════════════════════════════════

def effective_duty(line, a):
    """The duty rate that will actually be charged, and why.

    An FTA rate is a fact about a certificate of origin, not about the goods. Form E, EUR.1, AK,
    AJ, RCEP, CPTPP — each is a document that must exist and be valid at clearance. Without one,
    the MFN rate applies no matter what preferential rate somebody typed in hope.
    """
    co = str(line.get("coForm") or "").strip()
    has_co = bool(co) and co.lower() not in ("none", "no", "n/a", "-")
    if has_co and line.get("ftaDutyPct") not in (None, ""):
        return _frac(line.get("ftaDutyPct")), "FTA (" + co + ")"
    mfn = line.get("mfnDutyPct")
    if mfn in (None, ""):
        return _frac(a["dutyPct"]), "default (HS code not priced)"
    return _frac(mfn), "MFN"


def landed_line(line, a):
    """One imported line, EXW through to landed cost.

    The order of the three taxes is the point. Vietnamese import tax cascades: duty on CIF, SCT on
    CIF plus duty, VAT on CIF plus duty plus SCT. Assessing all three on CIF understates the tax
    and the gap widens with the duty rate.
    """
    qty = _num(line.get("qty"))
    exw_unit = _num(line.get("exwUnit"))
    exw = exw_unit * qty

    # Stage 1 — the international leg, still in the supplier's currency.
    legs = (_frac(line.get("inlandPct", a["inlandPct"])) + _frac(line.get("originPct", a["originPct"]))
            + _frac(line.get("freightPct", a["freightPct"])) + _frac(line.get("insurancePct", a["insurancePct"])))
    cif_fx = exw * (1.0 + legs)

    # Stage 2 — into dong at the rate for THIS supplier's currency.
    cur = str(line.get("currency") or "USD").strip().upper()
    fx = _num(line.get("fx")) or _num(a.get("fx" + cur.title(), 0)) or _num(a["fxUsd"])
    cif = vnd(cif_fx * fx)

    # Stage 3 — the cascade.
    duty_rate, duty_basis = effective_duty(line, a)
    duty = vnd(cif * duty_rate)
    sct_rate = _frac(line.get("sctPct"))
    sct = vnd((cif + duty) * sct_rate)
    vat_rate = _frac(line.get("vatPct", a["importVatPct"]))
    # RECOVERABLE. Reported so the cash need is visible, never added to the cost of the goods.
    vat = vnd((cif + duty + sct) * vat_rate)

    # Stage 4 — local charges, all assessed on CIF.
    charges = {}
    for key, akey in (("customs", "customsPct"), ("handling", "handlingPct"),
                      ("localTrans", "localTransPct"), ("bank", "bankPct"), ("inspect", "inspectPct")):
        charges[key] = vnd(cif * _frac(line.get(akey, a[akey])))

    landed = cif + duty + sct + sum(charges.values())
    return {
        "id": line.get("id"), "source": IMPORT,
        "itemCode": str(line.get("itemCode") or "").strip(),
        "hsCode": str(line.get("hsCode") or "").strip(),
        "desc": str(line.get("desc") or "").strip(),
        "unit": str(line.get("unit") or "").strip(),
        "origin": str(line.get("origin") or "").strip(),
        "supplier": str(line.get("supplier") or "").strip(),
        "qty": qty, "currency": cur, "fx": fx,
        "exwUnit": exw_unit, "exwTotal": round(exw, 2), "cifFx": round(cif_fx, 2),
        "cif": cif,
        "dutyRate": round(duty_rate * 100, 4), "dutyBasis": duty_basis, "duty": duty,
        "sctRate": round(sct_rate * 100, 4), "sct": sct,
        "vatRate": round(vat_rate * 100, 4), "vatRecoverable": vat,
        "charges": charges, "chargesTotal": sum(charges.values()),
        "landed": landed,
        "unitLanded": vnd(landed / qty) if qty else landed,
    }


def local_line(line, a):
    """One line bought in Vietnam. No customs chain — but transport and handling are still cost,
    and the supplier's VAT is still recoverable and still not part of it."""
    qty = _num(line.get("qty"))
    unit = _num(line.get("unitPrice"))
    net = vnd(unit * qty)
    vat_rate = _frac(line.get("vatPct", a["localVatPct"]))
    vat = vnd(net * vat_rate)
    trans = vnd(net * _frac(line.get("transPct")))
    handling = vnd(net * _frac(line.get("handlingPct")))
    total = net + trans + handling
    return {
        "id": line.get("id"), "source": LOCAL,
        "itemCode": str(line.get("itemCode") or "").strip(),
        "hsCode": "",
        "desc": str(line.get("desc") or "").strip(),
        "unit": str(line.get("unit") or "").strip(),
        "origin": "Vietnam",
        "supplier": str(line.get("supplier") or "").strip(),
        "qty": qty, "currency": "VND", "fx": 1,
        "netExVat": net,
        "vatRate": round(vat_rate * 100, 4), "vatRecoverable": vat,
        "transport": trans, "handling": handling,
        "landed": total,
        "unitLanded": vnd(total / qty) if qty else total,
    }


def cost_master(imports, locals_, a):
    """Both sources consolidated into one lookup, which is what the quotation prices from.

    Item codes must be unique across the two: if the same code appears as both an import and a
    local buy, a quotation line referring to it would silently take whichever came first. Rather
    than pick, the clash is returned so somebody can fix it.
    """
    rows = [landed_line(l, a) for l in (imports or [])] + [local_line(l, a) for l in (locals_ or [])]
    seen, clashes = {}, []
    for r in rows:
        code = r["itemCode"].upper()
        if not code:
            continue
        if code in seen and seen[code]["source"] != r["source"]:
            clashes.append(r["itemCode"])
        seen.setdefault(code, r)
    return {
        "rows": rows,
        "byCode": seen,
        "duplicateCodes": sorted(set(clashes)),
        "landedTotal": sum(r["landed"] for r in rows),
        "vatRecoverable": sum(r["vatRecoverable"] for r in rows),
        "importTotal": sum(r["landed"] for r in rows if r["source"] == IMPORT),
        "localTotal": sum(r["landed"] for r in rows if r["source"] == LOCAL),
    }


# ══════════════════════════════════════════════════════════════════════════════
#   2. EPC — a bill of materials per cost centre
# ══════════════════════════════════════════════════════════════════════════════

COST_CENTRES = [
    ("CIV", "Civil & Structural Works", 12.0),
    ("MEP", "MEP — Mechanical, Electrical, Plumbing", 12.0),
    ("BUT", "Black Utilities", 15.0),
    ("CUT", "Clean Utilities", 15.0),
    ("CLR", "Cleanroom", 15.0),
    ("OSD", "Line 1 — Oral Solid Dosage", 20.0),
    ("PFI", "Line 2 — Powder Filling / Injectables", 20.0),
    ("LVP", "Line 3 — Large Volume Parenterals", 20.0),
    ("SVP", "Line 4 — Small Volume Parenterals", 20.0),
    ("QCL", "QC Laboratory", 18.0),
    ("WHS", "Warehouse", 15.0),
    ("CON", "Professional & Consultant Fees", 10.0),
]
CENTRE_LABEL = {k: l for k, l, _m in COST_CENTRES}
CENTRE_MARKUP = {k: m for k, _l, m in COST_CENTRES}
# The production lines are the ones a configurator switches on and off; the rest of the plant is
# built whatever is made in it.
OPTIONAL_CENTRES = ("OSD", "PFI", "LVP", "SVP")


def bom_line(line, a, scale=1.0):
    """One BOM line: cost, its own mark-up, sell, margin — in USD and dong.

    Scale is the configurator's capacity factor. It multiplies quantity, not cost, because that is
    what it means: half a line is half the equipment, at the same unit price.
    """
    qty = _num(line.get("qty")) * _num(scale, 1.0)
    unit = _num(line.get("unitCostUsd"))
    cost = qty * unit
    centre = str(line.get("costCentre") or "").strip().upper()
    mk = line.get("markupPct")
    mk = CENTRE_MARKUP.get(centre, 12.0) if mk in (None, "") else _num(mk)
    sell = cost * (1.0 + _frac(mk))
    fx = _num(a["fxUsd"])
    return {
        "id": line.get("id"),
        "costCentre": centre,
        "code": str(line.get("code") or "").strip(),
        "descEn": str(line.get("descEn") or line.get("desc") or "").strip(),
        "descVn": str(line.get("descVn") or "").strip(),
        "spec": str(line.get("spec") or "").strip(),
        "unit": str(line.get("unit") or "").strip(),
        "origin": str(line.get("origin") or "").strip(),
        "qty": round(qty, 4), "unitCostUsd": unit,
        "costUsd": round(cost, 2), "markupPct": round(_num(mk), 4),
        "sellUsd": round(sell, 2), "marginUsd": round(sell - cost, 2),
        "marginPct": round((sell - cost) / sell * 100, 2) if sell else 0.0,
        "costVnd": vnd(cost * fx), "sellVnd": vnd(sell * fx),
    }


def bom_rollup(lines, a, config=None):
    """Every cost centre, costed and priced — and the ones switched off left out entirely.

    A production line that is off must not appear anywhere: not in the total, not as a zero row in
    the customer's quotation. A zero line in a tender document reads as "we forgot to price this".
    """
    config = config or {}
    centres, priced = {}, []
    for ln in lines or []:
        centre = str(ln.get("costCentre") or "").strip().upper()
        cfg = config.get(centre) or {}
        if centre in OPTIONAL_CENTRES and not cfg.get("include", True):
            continue
        row = bom_line(ln, a, cfg.get("scale", 1.0))
        priced.append(row)
        c = centres.setdefault(centre, {"costCentre": centre, "label": CENTRE_LABEL.get(centre, centre),
                                        "lines": 0, "costUsd": 0.0, "sellUsd": 0.0,
                                        "costVnd": 0, "sellVnd": 0,
                                        "scale": _num(cfg.get("scale", 1.0), 1.0),
                                        "optional": centre in OPTIONAL_CENTRES})
        c["lines"] += 1
        c["costUsd"] += row["costUsd"]; c["sellUsd"] += row["sellUsd"]
        c["costVnd"] += row["costVnd"]; c["sellVnd"] += row["sellVnd"]
    for c in centres.values():
        c["costUsd"] = round(c["costUsd"], 2); c["sellUsd"] = round(c["sellUsd"], 2)
        c["marginUsd"] = round(c["sellUsd"] - c["costUsd"], 2)
        c["marginPct"] = round(c["marginUsd"] / c["sellUsd"] * 100, 2) if c["sellUsd"] else 0.0
        c["markupPct"] = round(c["marginUsd"] / c["costUsd"] * 100, 2) if c["costUsd"] else 0.0
    order = {k: i for i, (k, _l, _m) in enumerate(COST_CENTRES)}
    rows = sorted(centres.values(), key=lambda c: order.get(c["costCentre"], 99))
    return {
        "lines": priced,
        "centres": rows,
        "costUsd": round(sum(c["costUsd"] for c in rows), 2),
        "sellUsd": round(sum(c["sellUsd"] for c in rows), 2),
        "costVnd": sum(c["costVnd"] for c in rows),
        "sellVnd": sum(c["sellVnd"] for c in rows),
        "excludedCentres": sorted(k for k in OPTIONAL_CENTRES
                                  if not (config.get(k) or {}).get("include", True)),
    }


# ══════════════════════════════════════════════════════════════════════════════
#   3. The quotation — one document model, whichever engine priced it
# ══════════════════════════════════════════════════════════════════════════════

def quote_line(src, override, a):
    """One customer-facing line: cost from the engine, mark-up and VAT from the quotation.

    The customer never sees the cost. It is carried here because the margin has to be reported
    beside the price at the moment somebody decides to send it.
    """
    unit_cost = _num(src.get("unitLanded", src.get("unitCostVnd")))
    qty = _num(override.get("qty", src.get("qty")))
    mk = override.get("markupPct")
    mk = _num(a["markupPct"]) if mk in (None, "") else _num(mk)
    vat = override.get("vatPct")
    vat = _num(a["outputVatPct"]) if vat in (None, "") else _num(vat)
    unit_sell = vnd(unit_cost * (1.0 + _frac(mk)))
    net = vnd(unit_sell * qty)
    return {
        "srcId": src.get("id"),
        "itemCode": src.get("itemCode") or "",
        "hsCode": src.get("hsCode") or "",
        "desc": str(override.get("desc") or src.get("desc") or "").strip(),
        "unit": src.get("unit") or "",
        "qty": qty,
        "unitCost": vnd(unit_cost),
        "markupPct": round(_num(mk), 4),
        "unitSell": unit_sell,
        "net": net,
        "vatPct": round(_num(vat), 4),
        "vat": vnd(net * _frac(vat)),
        "gross": net + vnd(net * _frac(vat)),
        "cogs": vnd(unit_cost * qty),
    }


def quotation(tender, master=None, rollup=None, overrides=None):
    """The document, and the commercial truth behind it.

    Trading quotes line by line from the cost master. EPC quotes one line per cost centre, because
    a customer buying a plant is not shown 900 bolts — but the margin reported here is still the
    margin on the bolts.
    """
    a = assumptions(tender.get("assump"))
    ctype = str(tender.get("costingType") or TRADING).strip().lower()
    ov = {str(o.get("srcId")): o for o in (overrides or [])}
    lines = []

    if ctype == EPC:
        for c in (rollup or {}).get("centres", []):
            o = ov.get(c["costCentre"]) or {}
            vat = o.get("vatPct")
            vat = _num(a["outputVatPct"]) if vat in (None, "") else _num(vat)
            net = c["sellVnd"]
            lines.append({
                "srcId": c["costCentre"], "itemCode": c["costCentre"], "hsCode": "",
                "desc": str(o.get("desc") or c["label"]).strip(),
                "unit": "lot", "qty": 1,
                "unitCost": c["costVnd"], "markupPct": c["markupPct"],
                "unitSell": net, "net": net,
                "vatPct": round(vat, 4), "vat": vnd(net * _frac(vat)),
                "gross": net + vnd(net * _frac(vat)), "cogs": c["costVnd"],
            })
    else:
        for src in (master or {}).get("rows", []):
            o = ov.get(str(src.get("id"))) or {}
            if o.get("exclude"):
                continue
            lines.append(quote_line(src, o, a))

    net = sum(l["net"] for l in lines)
    vat = sum(l["vat"] for l in lines)
    cogs = sum(l["cogs"] for l in lines)
    return {
        "costingType": ctype,
        "lines": lines,
        "lineCount": len(lines),
        "cogs": cogs,
        "net": net,
        "vat": vat,
        "gross": net + vat,
        "grossProfit": net - cogs,
        "grossMarginPct": round((net - cogs) / net * 100, 2) if net else 0.0,
        # The effective mark-up actually taken across the whole quotation — the one number that
        # cannot be argued with once discounts have been given line by line.
        "effectiveMarkupPct": round((net - cogs) / cogs * 100, 2) if cogs else 0.0,
    }


def pnl(quote, tender):
    """Revenue down to net profit, on the rates this tender was priced with.

    Opex percentages are of REVENUE, not of cost — that is how the spreadsheet reads them and how
    a commission is actually paid. CIT applies only to a positive EBIT: a loss-making tender does
    not generate a tax credit anybody can spend.
    """
    a = assumptions(tender.get("assump"))
    rev = quote["net"]
    cogs = quote["cogs"]
    gp = rev - cogs
    opex = [
        ("Sales commission", -vnd(rev * _frac(a["commPct"])), "Revenue x commission %"),
        ("Bank / finance charges", -vnd(rev * _frac(a["financePct"])), "Revenue x bank %"),
        ("Salary & admin allocation", -vnd(a["adminLump"]), "Lump sum"),
        ("Logistics / warranty reserve", -vnd(rev * _frac(a["warrantyPct"])), "Revenue x warranty %"),
    ]
    opex_total = sum(v for _l, v, _n in opex)
    ebit = gp + opex_total
    cit = -vnd(max(ebit, 0) * _frac(a["citPct"]))
    net_profit = ebit + cit
    def share(v):
        return round(v / rev * 100, 2) if rev else 0.0
    return {
        "revenue": rev, "cogs": -cogs, "grossProfit": gp, "grossMarginPct": share(gp),
        "opex": [{"label": l, "amount": v, "note": n, "pctRevenue": share(v)} for l, v, n in opex],
        "opexTotal": opex_total,
        "ebit": ebit, "ebitMarginPct": share(ebit),
        "cit": cit, "netProfit": net_profit, "netMarginPct": share(net_profit),
        "vatRecoverable": (quote.get("vatRecoverable") or 0),
    }


# ══════════════════════════════════════════════════════════════════════════════
#   4. What a quotation must carry before it may leave the building
# ══════════════════════════════════════════════════════════════════════════════

TERMS_DEFAULT = [
    ("Currency", "All prices are in Vietnamese Dong (VND) unless otherwise stated."),
    ("VAT", "VAT (output) is shown separately per line at the rate stated."),
    ("Validity", "This quotation is valid for 30 days from the issue date."),
    ("Delivery", "DDP customer site, Vietnam (Incoterms 2020). Lead time 6-8 weeks for imported items."),
    ("Payment", "30% advance via T/T upon order, 70% before delivery to site."),
    ("Warranty", "12 months from commissioning, parts and labour included."),
    ("Force majeure", "Delivery times are subject to force majeure; the FX clause applies if the rate moves more than 3% from the quotation date."),
    ("Title & risk", "Title transfers upon full payment; risk transfers upon delivery acceptance."),
    ("Dispute", "Governed by the laws of Vietnam; disputes resolved at VIAC, Ho Chi Minh City."),
]

# What must be present before a quotation is a document rather than a draft. Each of these has a
# consequence if it is missing: no validity date is an open-ended price, no tax code is an invoice
# the customer's accounts cannot process, no payment terms is an argument in ninety days.
REQUIRED_TO_ISSUE = [
    ("quoteNo", "Quotation number"),
    ("client", "Customer name"),
    ("clientTaxCode", "Customer tax code"),
    ("issueDate", "Issue date"),
    ("validUntil", "Valid until"),
]


def issue_check(tender, quote):
    """What still has to be filled in, and what is merely worth a second look.

    Blocking and advisory are kept apart on purpose. A quotation with no validity date should not
    be sent. A quotation at 4% margin might be exactly right — that is a decision, not an error,
    and the module's job is to make sure it is a decision somebody took knowingly.
    """
    missing = [label for key, label in REQUIRED_TO_ISSUE if not str(tender.get(key) or "").strip()]
    warnings = []
    if not quote["lineCount"]:
        missing.append("At least one priced line")
    if quote["lineCount"] and quote["grossMarginPct"] < 10:
        warnings.append("Gross margin is %.1f%% — below the 10%% the business normally needs."
                        % quote["grossMarginPct"])
    if quote.get("net") and not quote.get("vat"):
        warnings.append("No output VAT on any line. Correct for an export or an exempt supply, "
                        "wrong for a domestic sale of goods.")
    zero = [l["itemCode"] or l["desc"] for l in quote["lines"] if not l["unitCost"]]
    if zero:
        warnings.append("Priced with no cost behind it: " + ", ".join(str(z) for z in zero[:4])
                        + ("" if len(zero) <= 4 else " and %d more" % (len(zero) - 4)))
    return {"canIssue": not missing, "missing": missing, "warnings": warnings}


def document(tender, quote, company=None):
    """The quotation as the customer will read it: header, lines, totals, terms, signatures.

    Assembled here rather than in the PDF writer so the preview on screen and the PDF that is sent
    are built from one structure. A preview that is drawn by different code from the export is not
    a preview of anything.
    """
    a = assumptions(tender.get("assump"))
    company = company or {}
    terms = tender.get("terms") if isinstance(tender.get("terms"), list) and tender.get("terms") else None
    return {
        "quoteNo": tender.get("quoteNo") or tender.get("estNo") or "",
        "issueDate": tender.get("issueDate") or "",
        "validUntil": tender.get("validUntil") or "",
        "validityDays": _num(tender.get("validityDays"), 30),
        "client": {
            "name": tender.get("client") or "",
            "address": tender.get("clientAddress") or "",
            "taxCode": tender.get("clientTaxCode") or "",
            "attn": tender.get("clientAttn") or "",
            "contact": tender.get("clientContact") or "",
        },
        "project": {
            "name": tender.get("projectName") or tender.get("title") or "",
            "code": tender.get("projectCode") or "",
            "site": tender.get("site") or "",
        },
        "intro": tender.get("intro") or ("Dear Valued Customer, thank you for the opportunity to quote. "
                                         "We are pleased to submit the following pricing proposal for your "
                                         "project. Please find item details below."),
        "currency": "VND",
        "lines": [{k: v for k, v in l.items() if k not in ("unitCost", "cogs", "markupPct")}
                  for l in quote["lines"]],   # the customer's copy carries no cost and no mark-up
        "totals": {"net": quote["net"], "vat": quote["vat"], "gross": quote["gross"],
                   "lineCount": quote["lineCount"]},
        "amountInWords": tender.get("amountInWords") or "",
        "terms": terms or [{"label": l, "text": t} for l, t in TERMS_DEFAULT],
        "bank": {
            "beneficiary": company.get("name") or tender.get("bankBeneficiary") or "",
            "bank": tender.get("bankName") or "",
            "account": tender.get("bankAccount") or "",
            "swift": tender.get("bankSwift") or "",
        },
        "signatures": [
            {"role": "Prepared by", "title": tender.get("preparedByTitle") or "Sales Representative",
             "name": tender.get("preparedBy") or ""},
            {"role": "Approved by", "title": tender.get("approvedByTitle") or "Humiley Project Manager",
             "name": tender.get("approvedBy") or ""},
            {"role": "Customer acceptance", "title": "Authorised signatory & seal", "name": ""},
        ],
        "outputVatPct": a["outputVatPct"],
    }
