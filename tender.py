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
# The same largest-remainder splitter the estimate distributes preliminaries with. A cash
# flow that loses a few dong per month to rounding stops reconciling with its own cost.
from labour_cost import apportion

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

    ("pmFeePct", "Project fees", "Project management fee", 0.0, "% of goods value",
     "PMO, planning, progress reporting, client interface. Charge it or absorb it — but price it."),
    ("pmFeeLump", "Project fees", "Project management fee (fixed)", 0, "VND",
     "A lump sum instead of, or on top of, the percentage above."),
    ("designFeePct", "Project fees", "Design / engineering fee", 0.0, "% of goods value",
     "Shop drawings, calculations, selection, as-builts."),
    ("supervisionPct", "Project fees", "Site supervision", 0.0, "% of goods value",
     "Supervisors and site management for the installation period."),
    ("installPct", "Project fees", "Installation & labour", 0.0, "% of goods value",
     "Where installation is in scope and not already a costed line."),
    ("commissioningPct", "Project fees", "Testing & commissioning", 0.0, "% of goods value",
     "T&C, balancing, validation documentation, handover."),
    ("trainingPct", "Project fees", "Training & handover", 0.0, "% of goods value",
     "Operator training, O&M manuals, as-built dossier."),
    ("sparesPct", "Project fees", "Spare parts & consumables", 0.0, "% of goods value",
     "Commissioning spares and the first-year consumable set."),

    ("escalationPct", "Risk", "Price escalation", 0.0, "% of goods value",
     "For a long lead time or a tender that stays open past its validity."),
    ("contingencyPct", "Risk", "Contingency", 0.0, "% of goods value",
     "What is not yet known. Priced openly here rather than hidden in the mark-up."),
    ("warrantyCostPct", "Risk", "Warranty provision", 0.0, "% of goods value",
     "The cost of honouring the warranty stated in the conditions."),

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

    subtotal = sum(l["net"] for l in lines)
    cogs = sum(l["cogs"] for l in lines)

    # A DISCOUNT IS A PRICE CUT, NOT A LINE ON THE LETTER.
    #
    # It used to be neither applied nor propagated. The quotation printed a discount row and then
    # charged the full grand total — 20% off a 938bn tender moved the printed total by zero — VAT
    # was assessed on the undiscounted base, and every internal number a decision rests on
    # (revenue, gross margin, EBIT, net profit, the cash-flow inflows, the peak funding
    # requirement) was computed as though nothing had been given away. The Excel export was the
    # only surface that came out right, and only because its cell FORMULAS recomputed the total on
    # open; the cached values written beside them carried the same wrong figures as the PDF.
    #
    # Applied PRO RATA across the lines rather than as a lump against the subtotal, because output
    # VAT is per line: a tender mixing 10%-rated goods with a 0%-rated export would otherwise have
    # its VAT relieved on the wrong base. apportion() is the same largest-remainder splitter used
    # for preliminaries and the cash-flow spread, so the parts sum to the whole exactly — a
    # discount that loses a dong to rounding makes the customer's own arithmetic fail to add up.
    disc_pct = _num(tender.get("discountPct"))
    disc_frac = _frac(disc_pct)
    discount = vnd(subtotal * disc_frac)
    if discount and subtotal:
        parts = apportion(discount, {i: l["net"] for i, l in enumerate(lines)})
        for i, l in enumerate(lines):
            cut = parts[i]
            l["discount"] = cut
            l["netAfterDiscount"] = l["net"] - cut
            l["vat"] = vnd(l["netAfterDiscount"] * _frac(l["vatPct"]))
            l["gross"] = l["netAfterDiscount"] + l["vat"]
    else:
        for l in lines:
            l["discount"] = 0
            l["netAfterDiscount"] = l["net"]

    net = subtotal - discount
    vat = sum(l["vat"] for l in lines)
    return {
        "costingType": ctype,
        "lines": lines,
        "lineCount": len(lines),
        "cogs": cogs,
        # `subtotal` is what the lines add up to; `net` is what the customer actually owes before
        # tax. They differ by the discount, and the two must never be confused — `net` is the one
        # that is revenue.
        "subtotal": subtotal,
        "discountPct": round(disc_pct, 4),
        "discount": discount,
        "net": net,
        "vat": vat,
        "gross": net + vat,
        "grossProfit": net - cogs,
        "grossMarginPct": round((net - cogs) / net * 100, 2) if net else 0.0,
        # The effective mark-up actually taken across the whole quotation — the one number that
        # cannot be argued with once discounts have been given line by line.
        "effectiveMarkupPct": round((net - cogs) / cogs * 100, 2) if cogs else 0.0,
    }


PROJECT_FEES = [
    ("pmFeePct", "Project management", "pmFeeLump"),
    ("designFeePct", "Design / engineering", None),
    ("supervisionPct", "Site supervision", None),
    ("installPct", "Installation & labour", None),
    ("commissioningPct", "Testing & commissioning", None),
    ("trainingPct", "Training & handover", None),
    ("sparesPct", "Spare parts & consumables", None),
    ("escalationPct", "Price escalation", None),
    ("contingencyPct", "Contingency", None),
    ("warrantyCostPct", "Warranty provision", None),
]


def project_fees(tender, goods):
    """What it costs to DELIVER the goods, on top of buying them.

    Priced off the goods value, which is the cost of the things themselves — not off the selling
    price, because a fee that moves when the mark-up moves is not a fee, it is more mark-up.

    Every one of these is zero unless somebody sets it. A zero line is left out entirely rather
    than listed at nil: a schedule of ten fees all reading zero teaches a reader to skip the block,
    which is the last thing it should teach them.
    """
    a = assumptions(tender.get("assump"))
    base = _num(goods)
    out = []
    for key, label, lump_key in PROJECT_FEES:
        amount = vnd(base * _frac(a.get(key)))
        lump = vnd(a.get(lump_key)) if lump_key else 0
        if not amount and not lump:
            continue
        out.append({"key": key, "label": label, "pct": _num(a.get(key)),
                    "lump": lump, "amount": amount + lump, "base": base})
    return {"lines": out, "total": sum(l["amount"] for l in out)}


def pnl(quote, tender):
    """Revenue down to net profit, on the rates this tender was priced with.

    Opex percentages are of REVENUE, not of cost — that is how the spreadsheet reads them and how
    a commission is actually paid. CIT applies only to a positive EBIT: a loss-making tender does
    not generate a tax credit anybody can spend.
    """
    a = assumptions(tender.get("assump"))
    rev = quote["net"]
    goods = quote["cogs"]
    fees = project_fees(tender, goods)
    # Delivery costs sit in COGS, not in opex: they are what this job costs, not what the company
    # costs. Putting them below the gross-profit line would flatter every gross margin the business
    # reports and hide the jobs that are only profitable if nobody installs them.
    cogs = goods + fees["total"]
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
        "revenue": rev, "cogs": -cogs, "goodsCost": -goods,
        "projectFees": [{"label": l["label"], "amount": -l["amount"], "pct": l["pct"],
                         "pctRevenue": share(-l["amount"])} for l in fees["lines"]],
        "projectFeesTotal": -fees["total"],
        "grossProfit": gp, "grossMarginPct": share(gp),
        "opex": [{"label": l, "amount": v, "note": n, "pctRevenue": share(v)} for l, v, n in opex],
        "opexTotal": opex_total,
        "ebit": ebit, "ebitMarginPct": share(ebit),
        "cit": cit, "netProfit": net_profit, "netMarginPct": share(net_profit),
        "vatRecoverable": (quote.get("vatRecoverable") or 0),
    }


# ══════════════════════════════════════════════════════════════════════════════
#   5. CASH FLOW — when the money leaves and when it comes back
# ══════════════════════════════════════════════════════════════════════════════

# The S-curves the EPC model spends each cost centre over, transcribed from the workbook rather
# than approximated: civil starts in month 3 and is finished by 12, the cleanroom cannot start
# until the building is closed in month 9, the production lines follow it, and QC and the
# warehouse are fitted out last. Consultant fees and overheads run flat across the job.
#
# Each curve MUST sum to 1. A curve summing to 0.9 does not look wrong on screen — it silently
# forecasts spending 90% of a cost centre and flatters the funding requirement by the rest, which
# is the one number this whole page exists to produce. It is checked, not trusted.
SPEND_CURVES = {
    "CIV": [0, 0, .05, .10, .13, .15, .16, .15, .12, .08, .05, .01],
    "MEP": [0, 0, 0, 0, .04, .06, .10, .13, .15, .16, .14, .10, .08, .04],
    "BUT": [0, 0, 0, 0, 0, .03, .05, .08, .12, .15, .16, .15, .13, .08, .05],
    "CUT": [0, 0, 0, 0, 0, .03, .05, .08, .12, .15, .16, .15, .13, .08, .05],
    "CLR": [0, 0, 0, 0, 0, 0, 0, 0, .05, .10, .13, .16, .16, .14, .12, .08, .04, .02],
    "OSD": [0, 0, 0, 0, 0, 0, 0, 0, 0, .05, .08, .12, .15, .17, .15, .13, .08, .05, .02],
    "PFI": [0, 0, 0, 0, 0, 0, 0, 0, 0, .05, .08, .12, .15, .17, .15, .13, .08, .05, .02],
    "LVP": [0, 0, 0, 0, 0, 0, 0, 0, 0, .05, .08, .12, .15, .17, .15, .13, .08, .05, .02],
    "SVP": [0, 0, 0, 0, 0, 0, 0, 0, 0, .05, .08, .12, .15, .17, .15, .13, .08, .05, .02],
    "QCL": [0] * 12 + [.06, .10, .14, .16, .16, .14, .10, .08, .04, .02],
    "WHS": [0] * 12 + [.06, .10, .14, .16, .16, .14, .10, .08, .04, .02],
    # The workbook's exact figures, not a rounded reading of them: rounding these to two places
    # made the curve sum to 1.01, which would have spent 1% more on consultants than the estimate
    # says they cost.
    "CON": [.039604, .049505, .059406, .059406, .059406, .059406,
            .049505, .049505, .049505, .049505, .049505, .049505,
            .039604, .039604, .039604, .039604, .039604, .039604,
            .029703, .029703, .019802, .019802, .019802, .019802],
}

# Trading has no S-curve worth the name: the goods are bought, they arrive, they are installed.
# Spreading a purchase order over eighteen months would be a picture of a job nobody is doing.
TRADING_CURVE = [.30, .40, .20, .10]

DEFAULT_MILESTONES = [
    {"label": "Signing", "pct": 15, "month": 1},
    {"label": "Design complete", "pct": 25, "month": 6},
    {"label": "Installation", "pct": 30, "month": 14},
    {"label": "Mechanical completion", "pct": 20, "month": 18},
    {"label": "PQ / handover", "pct": 10, "month": 24},
]
DEFAULT_MONTHS = 24


def spread(amount, curve, months):
    """One cost centre's money laid out month by month, reconciling to the whole.

    Rounding 24 fractions of a billion dong independently loses money; the parts are made to sum
    to the total with the same largest-remainder splitter the estimate uses, so the cash flow and
    the cost can never disagree by a rounding error nobody can find.
    """
    curve = [max(0.0, _num(x)) for x in (curve or [])]
    if not curve or not sum(curve):
        return [0] * months
    # A curve longer than the job is COMPRESSED into it, never truncated. Truncating looked
    # harmless and was not: a cleanroom curve that starts in month 9, on a six-month job, fell
    # entirely outside the horizon and quietly dropped its whole cost from the forecast — the one
    # place the money must not go missing. A short job still spends what it spends; it spends it
    # sooner.
    weights = {}
    for i, w in enumerate(curve):
        slot = min(months - 1, int(i * months / len(curve))) if len(curve) > months else i
        weights[slot] = weights.get(slot, 0.0) + w
    parts = apportion(vnd(amount), weights)
    return [parts.get(i, 0) for i in range(months)]


def _curve_for(key, tender, months):
    custom = (tender.get("spendCurves") or {}).get(key)
    if isinstance(custom, list) and any(_num(x) for x in custom):
        return [_num(x) for x in custom]
    if key in SPEND_CURVES:
        return SPEND_CURVES[key]
    return TRADING_CURVE


def cash_flow(tender, quote, rollup=None, master=None):
    """Money out by month, money in by milestone, and the hole in between.

    The number this exists to produce is the PEAK FUNDING REQUIREMENT — the deepest the cumulative
    position goes before the client's payments catch up. A job can be profitable on every line of
    the P&L and still be one the company cannot afford to take, and nothing else in this module
    would say so.
    """
    months = int(_num(tender.get("durationMonths"), DEFAULT_MONTHS)) or DEFAULT_MONTHS
    months = max(1, min(months, 120))
    a = assumptions(tender.get("assump"))
    rows, warnings = [], []

    def add(key, label, amount):
        amount = vnd(amount)
        if not amount:
            return
        curve = _curve_for(key, tender, months)
        total = sum(_num(x) for x in curve)
        if abs(total - 1.0) > 0.01:
            warnings.append("The spend curve for %s adds up to %.0f%%, not 100%% — its cash flow "
                            "has been scaled to the cost so the two still reconcile." % (label, total * 100))
        cells = spread(amount, curve, months)
        assert sum(cells) == amount, "%s cash flow (%d) does not reconcile to its cost (%d)" % (
            label, sum(cells), amount)
        rows.append({"key": key, "label": label, "total": amount, "months": cells})

    if rollup:
        for c in rollup.get("centres", []):
            add(c["costCentre"], c["label"], c["costVnd"])
    elif master:
        add("GOODS", "Goods — landed cost", master.get("landedTotal"))

    fees = project_fees(tender, quote.get("cogs") if quote else 0)
    for f in fees["lines"]:
        add("CON", f["label"], f["amount"])

    contract = _num((quote or {}).get("net"))
    stored = tender.get("milestones")
    miles = [m for m in (stored if isinstance(stored, list) and stored else DEFAULT_MILESTONES)
             if _num(m.get("pct"))]
    pct_total = sum(_num(m.get("pct")) for m in miles)
    if miles and abs(pct_total - 100.0) > 0.01:
        warnings.append("The payment milestones add up to %.1f%% of the contract, not 100%% — "
                        "this forecast collects %s than the quotation is worth."
                        % (pct_total, "less" if pct_total < 100 else "more"))
    inflows = []
    for mm in miles:
        month = max(1, min(int(_num(mm.get("month"), 1)), months))
        cells = [0] * months
        cells[month - 1] = vnd(contract * _frac(mm.get("pct")))
        inflows.append({"label": str(mm.get("label") or ""), "pct": _num(mm.get("pct")),
                        "month": month, "total": cells[month - 1], "months": cells})

    out_m = [sum(r["months"][i] for r in rows) for i in range(months)]
    in_m = [sum(r["months"][i] for r in inflows) for i in range(months)]
    net = [in_m[i] - out_m[i] for i in range(months)]
    cum, run = [], 0
    for v in net:
        run += v
        cum.append(run)
    peak = min(cum) if cum else 0
    return {
        "months": months,
        "outflows": rows, "inflows": inflows,
        "outTotal": sum(out_m), "inTotal": sum(in_m),
        "outByMonth": out_m, "inByMonth": in_m,
        "netByMonth": net, "cumulative": cum,
        # Negative means the company is out of pocket. Reported as a positive requirement because
        # that is how it will be asked for: "how much do we need to fund this job".
        "peakFunding": -peak if peak < 0 else 0,
        "peakMonth": (cum.index(peak) + 1) if cum else 0,
        "closingPosition": cum[-1] if cum else 0,
        "warnings": warnings,
    }


# ══════════════════════════════════════════════════════════════════════════════
#   6. RISK — what it is worth, against what has been set aside for it
# ══════════════════════════════════════════════════════════════════════════════

RISK_BANDS = [(0.05, "Very low"), (0.15, "Low"), (0.30, "Medium"), (0.60, "High"), (1.01, "Very high")]


def risk_band(p):
    p = _frac(p) if _num(p) > 1 else _num(p)
    for edge, label in RISK_BANDS:
        if p <= edge:
            return label
    return "Very high"


def risk_register(risks, tender=None, quote=None):
    """Expected value of each risk, and whether the contingency actually covers the total.

    Probability times impact is arithmetic anybody can do. The judgement this adds is the
    comparison the workbook only hints at: an expected risk value of a million against a
    contingency of four hundred thousand is not a register, it is a warning, and it should say so
    on the same screen rather than in somebody's head.
    """
    out = []
    for r in risks or []:
        p = _num(r.get("probability"))
        p = p / 100.0 if p > 1 else p            # 30 and 0.3 both mean 30%
        impact = vnd(r.get("impact"))
        ev = vnd(impact * p)
        out.append({
            "id": r.get("id"), "code": str(r.get("code") or "").strip(),
            "risk": str(r.get("risk") or r.get("riskEn") or "").strip(),
            "category": str(r.get("category") or "").strip(),
            "owner": str(r.get("owner") or "").strip(),
            "status": str(r.get("status") or "Open").strip(),
            "mitigation": str(r.get("mitigation") or "").strip(),
            "probability": round(p * 100, 2), "band": risk_band(p),
            "impact": impact, "expected": ev,
        })
    out.sort(key=lambda x: -x["expected"])
    open_rows = [r for r in out if r["status"].lower() not in ("closed", "retired")]
    expected = sum(r["expected"] for r in open_rows)
    worst = sum(r["impact"] for r in open_rows)

    contingency = 0
    if tender is not None and quote is not None:
        a = assumptions(tender.get("assump"))
        contingency = vnd(_num(quote.get("cogs")) * _frac(a.get("contingencyPct")))
    return {
        "rows": out, "openCount": len(open_rows),
        "expectedValue": expected, "worstCase": worst,
        "contingency": contingency,
        "shortfall": max(0, expected - contingency),
        # Covered is a fact about two numbers, not an opinion — but it is the fact somebody
        # signing the tender most needs on the screen in front of them.
        "covered": contingency >= expected,
    }


SENSITIVITY_STEPS = [-5.0, 0.0, 5.0, 10.0, 15.0]


def sensitivity(quote, tender, target_margin=12.0):
    """What a cost overrun does to the margin, and at what point the job stops being worth taking.

    Costs are what move on a tender; the price has already been given to the customer. So the
    price is held and the cost is flexed, which is the honest direction — flexing both would let
    an overrun be absorbed by a price rise nobody has agreed to.
    """
    rev = _num(quote.get("net"))
    base = _num(quote.get("cogs")) + project_fees(tender, quote.get("cogs"))["total"]
    rows = []
    for step in SENSITIVITY_STEPS:
        cost = vnd(base * (1.0 + step / 100.0))
        profit = vnd(rev - cost)
        margin = round(profit / rev * 100, 2) if rev else 0.0
        rows.append({"step": step, "cost": cost, "profit": profit, "marginPct": margin,
                     "vsTarget": round(margin - target_margin, 2),
                     "verdict": ("On target" if margin >= target_margin
                                 else ("Thin" if margin > 0 else "Loss-making"))})
    # The overrun that takes the margin to zero: the number to quote when somebody asks how much
    # room there is.
    breakeven = round((rev - base) / base * 100, 2) if base else 0.0
    return {"rows": rows, "targetMarginPct": target_margin, "breakEvenOverrunPct": breakeven}


# ══════════════════════════════════════════════════════════════════════════════
#   4. What a quotation must carry before it may leave the building
# ══════════════════════════════════════════════════════════════════════════════

# The firm's own public details. A quotation with an empty company block is not on anybody's
# letterhead, so these stand in when the portal's company settings have not been filled — the same
# values the Excel template and every other portal PDF already show.
LETTERHEAD = {
    "name": "HUMILEY ENGINEERING & SOLUTIONS",
    "address": "2nd Floor, 68 Nguyen Hue, Sai Gon Ward, HCMC, Vietnam",
    "website": "www.humiley.com", "email": "contact@humiley.com", "phone": "+84 2877776668",
}


_MONTHS = ("January", "February", "March", "April", "May", "June",
           "July", "August", "September", "October", "November", "December")


def _long_date(iso):
    """2026-08-21 -> 21 August 2026. A letter does not date itself in ISO."""
    s = str(iso or "").strip()[:10]
    try:
        y, m, d = (int(x) for x in s.split("-"))
        return "%d %s %d" % (d, _MONTHS[m - 1], y)
    except (ValueError, IndexError):
        return s


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
    # The discount cap was declared as an assumption — "Maximum discount sales may offer without
    # approval" — and referenced by nothing. A control nobody enforces is not a control; it reads
    # like governance in the settings screen while any discount whatsoever went out unremarked.
    a = assumptions(tender.get("assump"))
    cap = _num(a.get("discountCapPct"))
    given = _num(quote.get("discountPct", tender.get("discountPct")))
    if cap and given > cap:
        warnings.append("Discount is %.1f%% — above the %.1f%% sales may give without approval. "
                        "It reduces this quotation by %s VND."
                        % (given, cap, format(quote.get("discount", 0), ",")))
    zero = [l["itemCode"] or l["desc"] for l in quote["lines"] if not l["unitCost"]]
    if zero:
        warnings.append("Priced with no cost behind it: " + ", ".join(str(z) for z in zero[:4])
                        + ("" if len(zero) <= 4 else " and %d more" % (len(zero) - 4)))
    return {"canIssue": not missing, "missing": missing, "warnings": warnings}


# The conditions a quotation goes out under. These are DEFAULTS, not a fixed set: a tender that
# stores its own list replaces them entirely, so a condition can be reworded, dropped, or added to
# — a retention clause, a site-access assumption, an exchange-rate clause — without touching code.
#
# Each default is a sentence with a slot. A sentence whose slot has nothing in it is left out
# rather than printed with a blank or an invented value: "Payment terms are ." on a quotation is
# worse than no sentence about payment at all. The three with no slot always appear.
CONDITIONS_DEFAULT = [
    ("validity", "Validity", "This quotation is valid until {validUntil} and is quoted {incoterm}.",
     ("validUntil",)),
    ("delivery", "Delivery", "Delivery lead time is {leadTime} after receipt of order and deposit.",
     ("leadTime",)),
    ("payment", "Payment", "Payment terms are {paymentTerms}.", ("paymentTerms",)),
    ("warranty", "Warranty", "All equipment is covered by {warranty}.", ("warranty",)),
    ("scope", "Scope", "Scope is strictly as described; any variation requires a written change "
                       "order and a revised quotation.", ()),
    ("currency", "Currency", "All prices are in Vietnamese Dong (VND).", ()),
]


def default_conditions(tender):
    """The standard conditions, with this tender's own particulars filled in."""
    vals = {
        "validUntil": _long_date(tender.get("validUntil")) or "the date stated above",
        "incoterm": str(tender.get("incoterm") or "Ex-Works (EXW)").strip(),
        "leadTime": str(tender.get("leadTime") or "").strip(),
        "paymentTerms": str(tender.get("paymentTerms") or "").strip(),
        "warranty": str(tender.get("warranty") or "").strip(),
    }
    out = []
    for key, label, text, needs in CONDITIONS_DEFAULT:
        if any(not vals.get(n) for n in needs):
            continue
        out.append({"key": key, "label": label, "text": text.format(**vals)})
    return out


def conditions(tender):
    """The conditions actually in force, and whether they are still the standard ones.

    A stored list wins outright. That is the point of storing one: somebody edited the wording,
    added a clause, or removed one that did not apply, and the defaults must not creep back in
    underneath them.
    """
    stored = tender.get("conditions")
    if isinstance(stored, list) and stored:
        out = []
        for i, c in enumerate(stored):
            if not isinstance(c, dict):
                continue
            text = str(c.get("text") or "").strip()
            if not text:
                continue
            out.append({"key": str(c.get("key") or ("c%d" % (i + 1))),
                        "label": str(c.get("label") or "").strip(), "text": text})
        if out:
            return out
    return default_conditions(tender)


def is_default_conditions(tender):
    stored = tender.get("conditions")
    return not (isinstance(stored, list) and any(
        isinstance(c, dict) and str(c.get("text") or "").strip() for c in stored))


def terms_paragraph(tender):
    """The conditions as one paragraph, the way the letterhead states them.

    The template runs them together in prose rather than as a numbered list — a letter, not a
    contract annex. A whole hand-written paragraph still overrides everything, for the tender that
    needs to say something the clause list cannot express.
    """
    if str(tender.get("termsParagraph") or "").strip():
        return tender["termsParagraph"].strip()
    return " ".join(c["text"] for c in conditions(tender))


def document(tender, quote, company=None):
    """The quotation as the customer will read it — shaped as the LETTERHEAD, not as a data table.

    The template is a letter: company block, date and reference, addressee, an RE: line, a
    salutation, a paragraph of context, the priced table, the terms in prose, a closing, and a
    signature. Assembled here rather than in the writers so the preview on screen, the PDF and the
    Excel workbook are three renderings of ONE structure. A preview drawn by different code from
    the export is not a preview of anything.
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
        # `subtotal` and `discount` are carried explicitly so no renderer has to recompute the cut
        # for itself. Every one that did got it wrong in a different way: the PDF printed the
        # discount and then charged the undiscounted grand total; the Excel export wrote correct
        # cell formulas beside incorrect cached values. One authority, four surfaces.
        "totals": {"subtotal": quote["subtotal"], "discount": quote["discount"],
                   "discountPct": quote["discountPct"],
                   "net": quote["net"], "vat": quote["vat"], "gross": quote["gross"],
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

        # ── the letterhead letter ──
        "company": {
            "name": str(company.get("name") or LETTERHEAD["name"]).upper(),
            "address": company.get("address") or LETTERHEAD["address"],
            # The company's own line, not a person's: it goes on every quotation the firm sends.
            "contact": "   ·   ".join(
                x for x in (company.get("website") or LETTERHEAD["website"],
                            company.get("email") or LETTERHEAD["email"],
                            company.get("phone") or LETTERHEAD["phone"]) if x),
        },
        "placeDate": ((tender.get("place") or "Ho Chi Minh City") + ", "
                      + _long_date(tender.get("issueDate"))),
        "salutationTo": tender.get("salutationTo") or "Sir / Madam",
        "salutation": tender.get("salutation") or "Dear Sir / Madam,",
        "subject": (tender.get("subject")
                    or ("Sales Quotation No. " + (tender.get("quoteNo") or "")
                        + (" — " + tender["projectName"] if tender.get("projectName") else ""))),
        "termsParagraph": terms_paragraph(tender),
        "conditions": conditions(tender),
        "conditionsAreDefault": is_default_conditions(tender),
        "closing": tender.get("closingParagraph") or (
            "We trust this proposal meets your requirements and would be glad to clarify any "
            "technical or commercial point."
            + (" We look forward to the opportunity to support the %s." % tender["projectName"]
               if tender.get("projectName") else "")),
        "contactLine": tender.get("contactLine") or (
            "Should you require any clarification, please do not hesitate to contact me directly "
            "on the details below."),
        "signerContact": " ".join(x for x in (
            ("E  " + tender["signerEmail"]) if tender.get("signerEmail") else "",
            ("T  " + tender["signerPhone"]) if tender.get("signerPhone") else "") if x),
        "encl": tender.get("encl") or ("Detailed quotation " + (tender.get("quoteNo") or "")
                                       + " (Excel / PDF)"),
        "discountPct": _num(tender.get("discountPct")),
        "vatPct": a["outputVatPct"],
    }
