"""VAT on a progress claim: the rate and the base are FILLED IN, never chosen by this code.

The distinction this module exists to hold, because it is easy to collapse and expensive to get
wrong:

  · WHAT RATE, and VAT ON WHAT, are commercial and tax decisions belonging to the company and its
    accountant. The portal must not invent them — a confident wrong VAT figure goes to a customer
    and into a tax return.
  · ARITHMETIC on a rate somebody has stated is just arithmetic, and refusing to do it helps nobody.

So the earlier behaviour — refuse to state any VAT figure at all — was only half right. It was right
that the portal must not CHOOSE; it was wrong that there was nowhere for a person to choose, which
left a real question permanently unanswerable and a real number permanently missing. This module is
the other half: the choices, named; the arithmetic, once a choice exists; and provenance, so a
figure can always be traced to who set what and where.

Recording a VAT figure is NOT issuing a VAT invoice. The legal original remains the provider's
digitally signed XML under Decree 123/2020 and Circular 78/2021, and nothing here mints one.

Pure — no database, no clock. Exercised by tests/test_vat.py.
"""

# ── the rates ────────────────────────────────────────────────────────────────────────────────────
# Vietnam has run 8% alongside 10% under successive reduction resolutions, 5% applies to some
# supplies, and 0% is exports and export-processing zones. Which one applies to a given job is not
# knowable from anything the portal holds, so all of them are offered and none is default.

RATES = (
    {"rate": 0, "label": "0% — export / EPZ", "labelVn": "0% — xuất khẩu / doanh nghiệp chế xuất"},
    {"rate": 5, "label": "5%", "labelVn": "5%"},
    {"rate": 8, "label": "8%", "labelVn": "8%"},
    {"rate": 10, "label": "10%", "labelVn": "10%"},
)
RATE_VALUES = tuple(r["rate"] for r in RATES)

NOT_APPLICABLE = "na"      # not a VAT supply at all — recorded as a choice, not as a blank

# ── VAT on WHAT ──────────────────────────────────────────────────────────────────────────────────
# The question that actually costs money on a contractor's claim, and the reason a single "VAT rate"
# box is not enough. A claim has two candidate bases and they differ by the advance recovery and the
# retention — on a ₫200m claim with a 30% advance and 5% retention that is a ₫7m difference in the
# tax line, every month.

BASE_CERTIFIED = "certified"   # VAT on the value of work certified this period
BASE_NET = "net"               # VAT on the net payable after recovery and retention

BASES = (
    {"code": BASE_CERTIFIED,
     "label": "The value certified this period",
     "labelVn": "Giá trị nghiệm thu trong kỳ",
     "note": "The work done is the supply. Advance recovery and retention are settlement of the "
             "same supply, not reductions of it. This is the common treatment."},
    {"code": BASE_NET,
     "label": "The net payable after recovery and retention",
     "labelVn": "Số còn phải trả sau khấu trừ tạm ứng và giữ lại",
     "note": "Used where the advance was already invoiced with VAT on receipt, so taxing the "
             "certified value again would tax the same money twice."},
)
BASE_CODES = tuple(b["code"] for b in BASES)

# ── the two tax points that decide the timing ───────────────────────────────────────────────────
# Not the rate, and not the base: WHEN the tax point falls. Both have real money attached and
# neither is answerable from portal data, so both are offered as a choice and neither is defaulted.

TAX_POINTS = {
    "retentionTaxPoint": {
        "question": "Is the retained 5% invoiced at acceptance with the rest of the value, or only "
                    "when it is released at the end of the warranty period?",
        "questionVn": "Phần 5% giữ lại được xuất hoá đơn ngay khi nghiệm thu cùng phần còn lại, hay "
                      "chỉ khi hoàn trả lúc hết bảo hành?",
        "options": (
            {"code": "at_acceptance", "label": "At acceptance, with the rest of the value",
             "labelVn": "Khi nghiệm thu, cùng phần giá trị còn lại"},
            {"code": "at_release", "label": "Only when it is released",
             "labelVn": "Chỉ khi hoàn trả"},
        ),
        "why": "It moves VAT on 5% of every contract, and by up to a year.",
        "whyVn": "Nó ảnh hưởng thuế GTGT của 5% mỗi hợp đồng, và lệch tới cả năm.",
    },
    "advanceTaxPoint": {
        "question": "Does an advance arriving before any acceptance trigger a VAT invoice on "
                    "receipt, or is it a cash record until work is certified?",
        "questionVn": "Khoản tạm ứng nhận trước khi nghiệm thu có phải xuất hoá đơn GTGT ngay khi "
                      "nhận tiền không, hay chỉ ghi nhận tiền cho tới khi nghiệm thu?",
        "options": (
            {"code": "on_receipt", "label": "A VAT invoice on receipt",
             "labelVn": "Xuất hoá đơn GTGT khi nhận tiền"},
            {"code": "on_certification", "label": "A cash record until work is certified",
             "labelVn": "Chỉ ghi nhận tiền cho tới khi nghiệm thu"},
        ),
        "why": "It is the first document raised on nearly every contract.",
        "whyVn": "Đây là chứng từ đầu tiên phát sinh ở gần như mọi hợp đồng.",
    },
}
TAX_POINT_KEYS = tuple(TAX_POINTS.keys())


def _num(v):
    try:
        return float(v)
    except (TypeError, ValueError):
        return 0.0


def r2(v):
    return round(_num(v) + 0.0, 2)


def rate_ok(v):
    """A rate has to be one of the ones that exist, or the explicit 'not a VAT supply'.

    An unrecognised rate is refused rather than clamped: 1.0 typed instead of 10 would otherwise
    produce a plausible, tiny, wrong tax line that nobody notices.
    """
    if str(v).strip().lower() == NOT_APPLICABLE:
        return True
    try:
        return float(v) in [float(x) for x in RATE_VALUES]
    except (TypeError, ValueError):
        return False


def resolve(claim=None, contract=None, settings=None):
    """The rate and base that apply here, and WHERE each came from.

    Three levels, most specific first: this claim, then the contract, then the company default. The
    provenance travels with the answer because "why is this one 8%" is a question somebody asks a
    year later, and "because that claim says so" and "because the company default says so" are
    different answers with different fixes.
    """
    claim, contract, settings = claim or {}, contract or {}, settings or {}
    out = {"rate": None, "base": None, "rateFrom": "", "baseFrom": "", "set": False}
    for src, name in ((claim, "claim"), (contract, "contract"), (settings, "company")):
        if out["rate"] is None and str(src.get("vatRate", "")).strip() != "" and rate_ok(src.get("vatRate")):
            out["rate"], out["rateFrom"] = src.get("vatRate"), name
        if out["base"] is None and str(src.get("vatBase") or "").strip() in BASE_CODES:
            out["base"], out["baseFrom"] = str(src.get("vatBase")).strip(), name
    out["set"] = out["rate"] is not None and out["base"] is not None
    if not out["set"]:
        missing = []
        if out["rate"] is None:
            missing.append("the VAT rate")
        if out["base"] is None:
            missing.append("what the VAT is charged on")
        out["why"] = ("Nobody has recorded %s for this claim, its contract, or the company. Set it "
                      "once in Company settings and every contract inherits it."
                      % " or ".join(missing))
    else:
        out["why"] = "%s on %s, from the %s." % (
            ("Not a VAT supply" if str(out["rate"]).lower() == NOT_APPLICABLE
             else "%.4g%% VAT" % _num(out["rate"])),
            next(b["label"].lower() for b in BASES if b["code"] == out["base"]),
            out["rateFrom"] if out["rateFrom"] == out["baseFrom"]
            else "%s and %s respectively" % (out["rateFrom"], out["baseFrom"]))
    return out


def compute(certified, net_payable, claim=None, contract=None, settings=None):
    """The tax line for one claim, from a rate somebody stated.

    Returns `ok: False` only when nobody has stated one — never because the module disagrees with
    the choice. Choosing is not this code's job; arithmetic is.
    """
    r = resolve(claim, contract, settings)
    out = {"ok": r["set"], "rate": r["rate"], "base": r["base"], "rateFrom": r["rateFrom"],
           "baseFrom": r["baseFrom"], "why": r["why"], "baseAmount": 0.0, "vat": 0.0,
           "gross": r2(net_payable)}
    if not r["set"]:
        return out
    if str(r["rate"]).strip().lower() == NOT_APPLICABLE:
        out.update({"rate": NOT_APPLICABLE, "baseAmount": 0.0, "vat": 0.0,
                    "gross": r2(net_payable),
                    "statement": "Not a VAT supply — no tax charged."})
        return out
    base_amount = r2(certified if r["base"] == BASE_CERTIFIED else net_payable)
    vat = r2(base_amount * _num(r["rate"]) / 100.0)
    out.update({
        "baseAmount": base_amount, "vat": vat, "gross": r2(_num(net_payable) + vat),
        "statement": "%.4g%% VAT on %s = %s; %s payable with tax."
                     % (_num(r["rate"]), _vnd(base_amount), _vnd(vat),
                        _vnd(_num(net_payable) + vat)),
    })
    return out


def _vnd(n):
    return "₫{:,.0f}".format(round(_num(n)))


def on_amount(rate, amount):
    """VAT on a single stated amount — for documents where there is only one possible base.

    A quotation is priced at a total; there is nothing to choose between. The certified-vs-net
    question belongs to a progress claim, where the advance recovery and the retention make the two
    genuinely different, and asking it here would be inventing a decision to make the caller answer.

    Still refuses when no rate has been stated: ok is False, no tax is added, and no `statement` is
    produced — the same rule as compute(), because "0% VAT = ₫0" on a document nobody has priced is
    a claim that nothing is taxable.
    """
    amount = r2(amount)
    out = {"ok": False, "rate": rate, "base": None, "baseAmount": amount, "vat": 0.0,
           "gross": amount}
    if str(rate).strip() == "" or not rate_ok(rate):
        out["why"] = ("No VAT rate is stated on this document, so it is ex-VAT. 8% and 10% have "
                      "both applied in recent periods — the rate is picked, never assumed.")
        return out
    out["ok"] = True
    if str(rate).strip().lower() == NOT_APPLICABLE:
        out.update({"rate": NOT_APPLICABLE, "statement": "Not a VAT supply — no tax charged."})
        return out
    vat = r2(amount * _num(rate) / 100.0)
    out.update({"vat": vat, "gross": r2(amount + vat),
                "statement": "%.4g%% VAT on %s = %s; %s including tax."
                             % (_num(rate), _vnd(amount), _vnd(vat), _vnd(amount + vat))})
    return out


def settings_review(settings=None):
    """What the company has actually recorded, and what is still blank.

    Reported rather than refused. A blank here does not stop anybody working — it stops the VAT
    LINE, which is a smaller and much more honest failure than a whole screen that will not load.
    """
    s = settings or {}
    rate, base = s.get("vatRate", ""), str(s.get("vatBase") or "")
    missing = []
    if str(rate).strip() == "" or not rate_ok(rate):
        missing.append({"key": "vatRate", "label": "Default VAT rate",
                        "labelVn": "Thuế suất GTGT mặc định"})
    if base not in BASE_CODES:
        missing.append({"key": "vatBase", "label": "What VAT is charged on",
                        "labelVn": "Tính thuế GTGT trên"})
    for k in TAX_POINT_KEYS:
        if not str(s.get(k) or "").strip():
            missing.append({"key": k, "label": TAX_POINTS[k]["question"],
                            "labelVn": TAX_POINTS[k]["questionVn"]})
    return {
        "rate": rate, "base": base,
        "retentionTaxPoint": s.get("retentionTaxPoint") or "",
        "advanceTaxPoint": s.get("advanceTaxPoint") or "",
        "complete": not missing, "missing": missing,
        "whoDecides": "Your accountant, in writing. Set it once here and every contract inherits "
                      "it; override on a contract or a single claim where it differs.",
        "why": ("Recorded — claims carry a VAT line." if not missing else
                "%d thing(s) still to record. Claims stay ex-VAT until they are: the portal will "
                "not choose a tax treatment on your behalf, but it will apply the one you choose."
                % len(missing)),
    }


# What this module still refuses to do, and why it is a refusal rather than a gap.
UNRESOLVED = (
    {"topic": "Which rate applies to a given supply",
     "question": "8% and 10% have run alongside each other under successive reduction resolutions, "
                 "and 0% applies to exports and export-processing-zone customers.",
     "why_it_matters": "It is 2% of the contract, on every invoice.",
     "action": "Offered as a choice per company, per contract and per claim. Never defaulted."},
    {"topic": "Whether the portal may issue the invoice",
     "question": "No. A hoá đơn GTGT is the provider's digitally signed XML under Decree 123/2020 "
                 "and Circular 78/2021.",
     "why_it_matters": "Recording a VAT figure and issuing a VAT invoice are different acts.",
     "action": "Enforced as an absence of capability by tests/test_sales_never_claims.py."},
)
