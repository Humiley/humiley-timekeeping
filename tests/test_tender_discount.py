"""A discount must be a price cut, not a line on the letter.

157 costing tests passed before this file existed, and the only mention of a discount in any of
them was `"discountPct": 0`. So the whole discount path — the thing sales touches on almost every
tender — was never executed once, and a defect that changed the grand total of every discounted
quotation was invisible to a green suite.

What was actually wrong, all from one cause (the discount was applied by each renderer, or by none):

  · the PDF printed a discount row and then charged the UNDISCOUNTED grand total, so the letter's
    own arithmetic did not add up — subtotal, less a discount, then a total equal to subtotal plus
    VAT;
  · output VAT was assessed on the undiscounted base;
  · pnl() reported revenue, gross margin, EBIT, net profit and CIT as though nothing had been given
    away — 20% off a tender that shows +12.1% net margin actually makes it a LOSS at -5.1%, and
    nothing on any screen said so;
  · cash_flow() billed the customer the undiscounted contract, overstating every inflow and
    understating the peak funding requirement, which is the one number that page exists to produce;
  · the Excel export alone came out right, and only because its cell formulas recompute on open —
    the cached values written beside them carried the same wrong figures as the PDF.
"""
import pytest

import tender


A = tender.assumptions()
LINE = {"qty": 1, "exwUnit": 100000, "currency": "USD", "mfnDutyPct": 10,
        "inlandPct": 0, "originPct": 0, "freightPct": 0, "insurancePct": 0,
        "customsPct": 0, "handlingPct": 0, "localTransPct": 0, "bankPct": 0, "inspectPct": 0}


def _quote(discount_pct=0.0, lines=None, vat_pct=10):
    t = {"costingType": tender.TRADING, "vatPct": vat_pct, "discountPct": discount_pct,
         "imports": lines or [dict(LINE, id="L1", desc="Pump")], "locals": [], "assump": {}}
    m = tender.cost_master(t["imports"], t["locals"], A)
    return t, tender.quotation(t, master=m)


def test_the_grand_total_actually_falls():
    """The defect in one line: 0% and 20% used to produce the same grand total."""
    _, full = _quote(0)
    _, cut = _quote(20)
    assert cut["gross"] < full["gross"], (
        "a 20%% discount left the grand total at %r — the customer is billed the full price under "
        "a letter that says they were given a discount" % cut["gross"])


def test_the_letter_adds_up():
    """subtotal - discount + VAT == grand total. This is the arithmetic the customer checks."""
    for pct in (0, 5, 10, 20, 37.5, 100):
        _, q = _quote(pct)
        assert q["subtotal"] - q["discount"] + q["vat"] == q["gross"], (
            "at %s%%: %d - %d + %d != %d"
            % (pct, q["subtotal"], q["discount"], q["vat"], q["gross"]))


def test_subtotal_is_the_lines_and_net_is_what_is_owed():
    """The two must never be conflated: `net` is revenue, `subtotal` is what the lines add to."""
    _, q = _quote(20)
    assert q["subtotal"] == sum(l["net"] for l in q["lines"])
    assert q["net"] == q["subtotal"] - q["discount"]
    assert q["net"] < q["subtotal"]


def test_vat_is_charged_on_the_discounted_base():
    _, full = _quote(0)
    _, cut = _quote(20)
    assert cut["vat"] == round(cut["net"] * 0.10), \
        "VAT %d is not 10%% of the discounted net %d" % (cut["vat"], cut["net"])
    assert cut["vat"] < full["vat"], "VAT did not fall with the price"


def test_the_discount_reaches_the_pnl():
    """The failure that mattered most: a deal that looks profitable and is not."""
    t0, q0 = _quote(0)
    t20, q20 = _quote(20)
    p0, p20 = tender.pnl(q0, t0), tender.pnl(q20, t20)
    assert p20["revenue"] < p0["revenue"], "P&L revenue ignored the discount"
    assert p20["netProfit"] < p0["netProfit"]
    assert p0["netMarginPct"] > 0 > p20["netMarginPct"], (
        "a 20%% discount should turn this fixture from profit to loss; got %s%% -> %s%%"
        % (p0["netMarginPct"], p20["netMarginPct"]))


def test_the_discount_reaches_the_cash_flow():
    """Inflows are what the customer pays, not what the lines add up to."""
    t0, q0 = _quote(0)
    t20, q20 = _quote(20)
    c0, c20 = tender.cash_flow(t0, q0), tender.cash_flow(t20, q20)
    in0 = sum(sum(i["months"]) for i in c0["inflows"])
    in20 = sum(sum(i["months"]) for i in c20["inflows"])
    assert in20 < in0, "the cash flow billed the undiscounted contract"
    assert c20["peakFunding"] <= c0["peakFunding"], \
        "a discount cannot improve the funding requirement"


def test_the_discount_is_split_pro_rata_so_mixed_vat_rates_stay_right():
    """A lump discount against the subtotal would relieve VAT on the wrong base when a tender
    mixes rated and zero-rated lines — an export beside a domestic supply."""
    lines = [dict(LINE, id="L1", desc="Domestic pump"), dict(LINE, id="L2", desc="Exported skid")]
    t = {"costingType": tender.TRADING, "vatPct": 10, "discountPct": 20,
         "imports": lines, "locals": [], "assump": {}}
    m = tender.cost_master(t["imports"], t["locals"], A)
    q = tender.quotation(t, master=m, overrides=[{"srcId": "L2", "vatPct": 0}])
    by = {l["srcId"]: l for l in q["lines"]}
    assert by["L2"]["vat"] == 0, "the zero-rated line was charged VAT"
    assert by["L1"]["vat"] == round(by["L1"]["netAfterDiscount"] * 0.10)
    assert sum(l["discount"] for l in q["lines"]) == q["discount"], \
        "the pro-rata split lost or invented money"


@pytest.mark.parametrize("pct", [0, 1, 5, 7.5, 10, 20, 33.33, 50, 99, 100])
def test_the_split_sums_exactly_at_every_rate(pct):
    """A discount that loses a dong to rounding makes the customer's arithmetic fail."""
    lines = [dict(LINE, id="L%d" % i, desc="Item %d" % i, exwUnit=1000 + i * 137)
             for i in range(7)]
    t = {"costingType": tender.TRADING, "vatPct": 10, "discountPct": pct,
         "imports": lines, "locals": [], "assump": {}}
    m = tender.cost_master(t["imports"], t["locals"], A)
    q = tender.quotation(t, master=m)
    assert sum(l["discount"] for l in q["lines"]) == q["discount"]
    assert sum(l["netAfterDiscount"] for l in q["lines"]) == q["net"]


def test_a_hundred_percent_discount_is_free_not_negative():
    _, q = _quote(100)
    assert q["net"] == 0
    assert q["vat"] == 0
    assert q["gross"] == 0


def test_no_discount_leaves_everything_exactly_as_before():
    """The change must be inert for the overwhelmingly common case."""
    _, q = _quote(0)
    assert q["discount"] == 0
    assert q["net"] == q["subtotal"]
    assert all(l["discount"] == 0 for l in q["lines"])
    assert all(l["netAfterDiscount"] == l["net"] for l in q["lines"])


def test_the_discount_cap_is_enforced_not_merely_declared():
    """`discountCapPct` was defined as an assumption — 'Maximum discount sales may offer without
    approval' — and referenced by nothing. It read like governance in the settings screen while
    any discount at all went out unremarked."""
    cap = tender.assumptions()["discountCapPct"]
    t_ok, q_ok = _quote(cap)
    t_over, q_over = _quote(cap + 5)
    for t, q in ((t_ok, q_ok), (t_over, q_over)):
        t.update({"quoteNo": "Q1", "client": "X", "clientTaxCode": "1", "issueDate": "2026-01-01",
                  "validUntil": "2026-02-01"})
    at_cap = tender.issue_check(t_ok, q_ok)["warnings"]
    over = tender.issue_check(t_over, q_over)["warnings"]
    assert not any("above the" in w for w in at_cap), "warned at exactly the cap"
    assert any("above the" in w for w in over), \
        "a discount above the cap produced no warning — the control does nothing"


def test_no_renderer_still_recomputes_the_discount_for_itself():
    """`net` became the AFTER-discount figure when the discount moved into quotation(). Any
    renderer still showing `net` as the SUBTOTAL and then deducting the discount underneath would
    present a doubly-discounted letter — the original defect, inverted. The on-screen preview did
    exactly that until this was caught; the expression below is the shape to keep out."""
    import io
    import os
    html = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))),
                        "templates", "index.html")
    src = io.open(html, encoding="utf-8").read()
    assert "discountPct || 0) / 100" not in src, \
        "a renderer is computing the discount itself instead of reading it from the server"


def test_the_document_carries_the_figures_so_no_renderer_recomputes_them():
    """Each renderer that computed the cut for itself got it wrong in a different way."""
    t, q = _quote(20)
    t.update({"quoteNo": "Q1", "client": "X", "clientTaxCode": "1",
              "issueDate": "2026-01-01", "validUntil": "2026-02-01"})
    tot = tender.document(t, q)["totals"]
    for k in ("subtotal", "discount", "discountPct", "net", "vat", "gross"):
        assert k in tot, "document totals omit %r, forcing the renderer to derive it" % k
    assert tot["subtotal"] - tot["discount"] + tot["vat"] == tot["gross"]
