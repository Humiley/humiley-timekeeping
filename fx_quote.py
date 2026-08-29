"""Presenting a quotation in a currency other than the dong.

A Vietnamese contractor quoting an overseas client is regularly asked for the price in USD. Until
now the only answer was to convert it by hand outside the system, which means the figure the
customer receives was never the figure the tender computed.

Four rules, and the first two are the ones that make this safe to print.

THE DONG STAYS THE TRUTH.  Cost, margin, VAT and everything the ledger will ever see remain in VND.
A presentation currency is a VIEW of the same quotation, computed at the end, never a second set of
books. Nothing here feeds `estimating`, `pnl` or the general ledger.

THE LINES MUST ADD UP TO THE TOTAL.  Converting each line on its own and summing gives a total that
differs from the converted total by a few cents — and the customer's finance team adds the column
up. So the TOTAL is converted, then split back across the lines by their dong weight using the same
largest-remainder splitter the discount and the preliminaries already use. The parts sum to the
whole exactly, by construction rather than by luck.

A MISSING RATE IS REFUSED, NEVER DEFAULTED.  A rate defaulting to 1 would print dong figures
labelled USD: ₫2,400,000,000 becomes "USD 2,400,000,000" on a document going to a customer. That is
the single worst failure this module could have, so a rate that is absent, zero or negative raises
rather than guesses.

THE RATE IS STAMPED.  Which rate, on what date, from where. A converted quotation whose rate is not
recorded cannot be checked, cannot be reproduced, and cannot be argued about six months later when
the dong has moved.
"""

from labour_cost import apportion


class FxError(ValueError):
    """A quotation that cannot be honestly presented in the requested currency."""


#: How many decimal places each currency actually has. Getting this wrong is not cosmetic:
#: JPY and VND have no minor unit, so "¥1,234.56" is not a price anybody can pay.
PLACES = {
    "VND": 0, "JPY": 0, "KRW": 0,
    "USD": 2, "EUR": 2, "GBP": 2, "SGD": 2, "AUD": 2, "CNY": 2, "THB": 2, "MYR": 2, "HKD": 2,
}

#: What the customer sees in front of the number.
SYMBOL = {"VND": "₫", "USD": "$", "EUR": "€", "GBP": "£", "JPY": "¥",
          "CNY": "¥", "SGD": "S$", "AUD": "A$", "KRW": "₩", "THB": "฿",
          "MYR": "RM", "HKD": "HK$"}


def _num(v):
    try:
        return float(str(v).replace(",", "").replace(" ", "").replace("₫", "").strip() or 0)
    except (TypeError, ValueError):
        return 0.0


def normalise(code):
    return str(code or "").strip().upper()


def places(code):
    code = normalise(code)
    if code not in PLACES:
        raise FxError("%s is not a currency this quotation can be presented in." % (code or "(blank)"))
    return PLACES[code]


def check(code, rate):
    """The currency and rate, or a refusal saying which one is wrong.

    Separated from `restate` so a screen can ask "may I offer this?" without building a document.
    """
    code = normalise(code)
    if code not in PLACES:
        raise FxError("%s is not a currency this quotation can be presented in. Known: %s."
                      % (code or "(blank)", ", ".join(sorted(PLACES))))
    r = _num(rate)
    if r <= 0:
        raise FxError("A rate of VND per 1 %s is required to present this quotation in %s. "
                      "Without one the dong figures would be printed under a %s label."
                      % (code, code, code))
    return code, r


def to_minor(vnd_amount, rate, dp):
    """VND -> whole minor units of the target currency (cents, or whole yen).

    Integer minor units, not floats: the apportionment below has to be exact, and 0.1 + 0.2 is a
    bad foundation for a number a customer pays against.
    """
    return int(round(_num(vnd_amount) / rate * (10 ** dp)))


def _split(total_minor, weights):
    """Give each line its share of an already-converted total, summing exactly."""
    if not weights:
        return {}
    if total_minor == 0 or sum(max(0.0, _num(w)) for w in weights.values()) <= 0:
        return {k: 0 for k in weights}
    return apportion(total_minor, weights)


def restate(quote, currency, rate, on=None, source=None):
    """The same quotation, in another currency. Returns lines, totals and the stamped rate.

    Money comes back as integer MINOR units alongside the major-unit value, so a renderer can
    format without re-deriving anything and without floating-point drift.
    """
    code, r = check(currency, rate)
    dp = PLACES[code]
    scale = float(10 ** dp)

    lines = list(quote.get("lines") or [])

    # Convert the TOTALS first — these are the numbers the customer checks — then hand the lines
    # their shares of them.
    net_m = to_minor(quote.get("net"), r, dp)
    vat_m = to_minor(quote.get("vat"), r, dp)
    sub_m = to_minor(quote.get("subtotal"), r, dp)
    # Derived, not converted independently: a separately-converted discount can leave
    # subtotal - discount != net by a cent, and that is the one subtraction a reader does by eye.
    disc_m = sub_m - net_m
    gross_m = net_m + vat_m

    net_w = {i: max(0.0, _num(l.get("netAfterDiscount", l.get("net")))) for i, l in enumerate(lines)}
    vat_w = {i: max(0.0, _num(l.get("vat"))) for i, l in enumerate(lines)}
    # A quotation with no VAT anywhere (an export) still has to place a zero on every line rather
    # than dividing by a zero weight.
    if sum(vat_w.values()) <= 0:
        vat_w = {i: 0.0 for i in net_w}
    sub_w = {i: max(0.0, _num(l.get("net"))) for i, l in enumerate(lines)}

    net_parts = _split(net_m, net_w)
    vat_parts = _split(vat_m, vat_w) if vat_m else {i: 0 for i in net_w}
    sub_parts = _split(sub_m, sub_w)

    out = []
    for i, l in enumerate(lines):
        n = dict(l)
        ln_sub = sub_parts.get(i, 0)
        ln_net = net_parts.get(i, 0)
        ln_vat = vat_parts.get(i, 0)
        qty = _num(l.get("qty"))
        n["net"] = ln_sub / scale
        n["discount"] = (ln_sub - ln_net) / scale
        n["netAfterDiscount"] = ln_net / scale
        n["vat"] = ln_vat / scale
        n["gross"] = (ln_net + ln_vat) / scale
        # The unit rate is DERIVED from the line total, so the column the customer multiplies is
        # consistent with the column they add. At this precision qty x unit may not reproduce the
        # line exactly for a fractional quantity; the LINE is the authority, which is the ordinary
        # convention on an international quotation and is stated in the note below.
        n["unitSell"] = (ln_sub / qty / scale) if qty else 0
        n["minor"] = {"net": ln_sub, "netAfterDiscount": ln_net, "vat": ln_vat,
                      "gross": ln_net + ln_vat}
        out.append(n)

    return {
        "currency": code,
        "symbol": SYMBOL.get(code, code),
        "places": dp,
        "rate": r,
        "rateOn": str(on or ""),
        "rateSource": str(source or ""),
        "lines": out,
        "totals": {
            "subtotal": sub_m / scale,
            "discount": disc_m / scale,
            "discountPct": _num(quote.get("discountPct")),
            "net": net_m / scale,
            "vat": vat_m / scale,
            "gross": gross_m / scale,
            "lineCount": len(out),
        },
        # The dong figures the conversion came from, carried alongside so a reader of the record
        # can always get back to what the company actually priced.
        "vnd": {"subtotal": _num(quote.get("subtotal")), "discount": _num(quote.get("discount")),
                "net": _num(quote.get("net")), "vat": _num(quote.get("vat")),
                "gross": _num(quote.get("gross"))},
        "note": ("Priced in VND and presented in %s at %s VND per 1 %s%s. Line totals are the "
                 "authority; unit rates are shown to %d decimal place(s)."
                 % (code, format(int(r), ","), code,
                    (" on " + str(on)) if on else "", dp)),
    }


def exposure(quote, currency, rate, moves=(-10.0, -5.0, 5.0, 10.0)):
    """What quoting in this currency does to the margin if the rate moves before settlement.

    THE commercial point of quoting in a foreign currency, and the part nobody computes by hand.
    The price is fixed in the foreign currency; the COST stays in dong. So a dong that strengthens
    against the quoted currency takes the difference straight out of the margin, and a contractor
    who has not seen that number has taken a position without deciding to.

    Reported as the margin the business would actually achieve, not as an abstract FX delta.
    """
    code, r = check(currency, rate)
    cogs = _num(quote.get("cogs"))
    net_vnd = _num(quote.get("net"))
    if net_vnd <= 0:
        return {"currency": code, "rate": r, "rows": [], "quotedAmount": 0.0}

    quoted = net_vnd / r          # what the customer is committed to pay, in the foreign currency
    rows = []
    for m in (0.0,) + tuple(moves):
        r2 = r * (1 + m / 100.0)
        revenue = quoted * r2      # the same foreign-currency price, settled at a different rate
        margin = revenue - cogs
        rows.append({
            "movePct": m,
            "rate": r2,
            "revenueVnd": revenue,
            "marginVnd": margin,
            "marginPct": (margin / revenue * 100.0) if revenue else None,
        })
    rows.sort(key=lambda x: x["movePct"])
    return {"currency": code, "rate": r, "quotedAmount": quoted, "cogsVnd": cogs, "rows": rows}
