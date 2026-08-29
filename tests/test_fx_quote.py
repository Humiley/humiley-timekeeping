"""Presenting a quotation in another currency.

The two failures that would reach a customer are: a document whose lines do not add up to its own
total, and dong figures printed under a USD label. Both get the most tests.
"""
import pytest

import fx_quote as fx


def Q(lines=None, **kw):
    """A quotation in the shape `tender.quotation` returns."""
    lines = lines if lines is not None else [
        {"desc": "A", "qty": 1, "net": 600000000, "netAfterDiscount": 600000000,
         "vat": 60000000, "gross": 660000000},
        {"desc": "B", "qty": 3, "net": 400000000, "netAfterDiscount": 400000000,
         "vat": 40000000, "gross": 440000000},
    ]
    sub = sum(l["net"] for l in lines)
    vat = sum(l["vat"] for l in lines)
    q = {"lines": lines, "subtotal": sub, "discount": 0, "discountPct": 0,
         "net": sub, "vat": vat, "gross": sub + vat, "lineCount": len(lines),
         "cogs": int(sub * 0.7)}
    q.update(kw)
    return q


# ── the lines must add up to the total ───────────────────────────────────────────────────────────

def test_the_lines_sum_EXACTLY_to_the_stated_total():
    """THE rule. The customer's finance team adds the column up; converting each line on its own
    leaves a total that is a few cents adrift from the one printed at the bottom."""
    r = fx.restate(Q(), "USD", 25500)
    assert sum(l["minor"]["gross"] for l in r["lines"]) == \
        round(r["totals"]["gross"] * 100)


def test_the_net_column_sums_to_the_net_total():
    r = fx.restate(Q(), "USD", 25500)
    assert sum(l["minor"]["netAfterDiscount"] for l in r["lines"]) == round(r["totals"]["net"] * 100)


def test_the_vat_column_sums_to_the_vat_total():
    r = fx.restate(Q(), "USD", 25500)
    assert sum(l["minor"]["vat"] for l in r["lines"]) == round(r["totals"]["vat"] * 100)


def test_net_plus_vat_equals_gross_on_every_line_and_on_the_total():
    r = fx.restate(Q(), "USD", 25500)
    for l in r["lines"]:
        assert l["minor"]["netAfterDiscount"] + l["minor"]["vat"] == l["minor"]["gross"]
    t = r["totals"]
    assert round(t["net"] * 100) + round(t["vat"] * 100) == round(t["gross"] * 100)


def test_subtotal_minus_discount_equals_net_after_conversion():
    """The one subtraction a reader does by eye. Converting the discount independently can leave it
    a cent out."""
    q = Q()
    q.update(discount=100000000, discountPct=10, net=q["subtotal"] - 100000000)
    for i, l in enumerate(q["lines"]):
        l["netAfterDiscount"] = l["net"] - (50000000 if i == 0 else 50000000)
    r = fx.restate(q, "USD", 25500)
    t = r["totals"]
    assert round(t["subtotal"] * 100) - round(t["discount"] * 100) == round(t["net"] * 100)


@pytest.mark.parametrize("rate", [25500, 23117, 1, 999999])
def test_the_columns_add_up_at_any_rate(rate):
    """An awkward rate is exactly where a naive per-line conversion drifts."""
    r = fx.restate(Q(), "USD", rate)
    assert sum(l["minor"]["gross"] for l in r["lines"]) == round(r["totals"]["gross"] * 100)


def test_a_many_line_quotation_still_adds_up():
    """Rounding error grows with the line count; two lines can pass by luck."""
    lines = [{"desc": str(i), "qty": 1, "net": 333333333, "netAfterDiscount": 333333333,
              "vat": 33333333, "gross": 366666666} for i in range(37)]
    r = fx.restate(Q(lines), "USD", 25500)
    assert sum(l["minor"]["gross"] for l in r["lines"]) == round(r["totals"]["gross"] * 100)


# ── a missing rate is refused, never defaulted ───────────────────────────────────────────────────

@pytest.mark.parametrize("bad", [0, "0", "", None, -1, "abc"])
def test_a_rate_that_is_not_a_rate_is_refused(bad):
    """Defaulting to 1 would print ₫2,400,000,000 as 'USD 2,400,000,000' on a customer's document.
    That is the worst thing this module could do."""
    with pytest.raises(fx.FxError):
        fx.restate(Q(), "USD", bad)


def test_the_refusal_says_what_is_needed():
    with pytest.raises(fx.FxError) as e:
        fx.restate(Q(), "USD", 0)
    assert "VND per 1 USD" in str(e.value)


@pytest.mark.parametrize("bad", ["", None, "XYZ", "Dollars", "us dollar"])
def test_an_unknown_currency_is_refused(bad):
    """Without knowing its minor unit the module cannot say how to round it."""
    with pytest.raises(fx.FxError):
        fx.restate(Q(), bad, 25500)


def test_the_unknown_currency_refusal_lists_what_it_knows():
    with pytest.raises(fx.FxError) as e:
        fx.restate(Q(), "XYZ", 25500)
    assert "USD" in str(e.value)


# ── the minor unit is not cosmetic ───────────────────────────────────────────────────────────────

def test_a_currency_with_no_minor_unit_gets_whole_numbers():
    """'¥1,234.56' is not a price anybody can pay."""
    r = fx.restate(Q(), "JPY", 170)
    assert r["places"] == 0
    for l in r["lines"]:
        assert float(l["gross"]).is_integer()
    assert float(r["totals"]["gross"]).is_integer()


def test_a_two_decimal_currency_keeps_its_cents():
    r = fx.restate(Q(), "USD", 25500)
    assert r["places"] == 2
    assert round(r["totals"]["gross"] * 100) == r["totals"]["gross"] * 100


def test_the_symbol_travels_with_the_code():
    assert fx.restate(Q(), "USD", 25500)["symbol"] == "$"
    assert fx.restate(Q(), "EUR", 27800)["symbol"] == "€"


# ── the rate is stamped ──────────────────────────────────────────────────────────────────────────

def test_the_rate_the_date_and_the_source_are_recorded():
    """A converted quotation whose rate is not recorded cannot be checked or reproduced."""
    r = fx.restate(Q(), "USD", 25500, on="2026-08-29", source="Vietcombank selling")
    assert r["rate"] == 25500
    assert r["rateOn"] == "2026-08-29"
    assert r["rateSource"] == "Vietcombank selling"
    assert "25,500" in r["note"] and "2026-08-29" in r["note"]


def test_the_dong_figures_are_carried_alongside():
    """So a reader of the record can always get back to what the company actually priced."""
    q = Q()
    r = fx.restate(q, "USD", 25500)
    assert r["vnd"]["gross"] == q["gross"]
    assert r["vnd"]["net"] == q["net"]


def test_the_conversion_does_not_touch_the_quotation_it_was_given():
    """The dong stays the truth — this is a view, not a second set of books."""
    q = Q()
    before = q["gross"]
    fx.restate(q, "USD", 25500)
    assert q["gross"] == before
    assert q["lines"][0]["net"] == 600000000


# ── the unit rate ────────────────────────────────────────────────────────────────────────────────

def test_the_unit_rate_is_derived_from_the_line_total():
    """So the column the customer multiplies is consistent with the column they add."""
    r = fx.restate(Q(), "USD", 25500)
    a = next(l for l in r["lines"] if l["desc"] == "A")
    assert round(a["unitSell"], 2) == round(a["net"], 2)      # qty 1
    b = next(l for l in r["lines"] if l["desc"] == "B")
    assert round(b["unitSell"] * 3, 0) == round(b["net"], 0)   # qty 3


def test_a_line_with_no_quantity_does_not_divide_by_zero():
    lines = [{"desc": "Lump", "qty": 0, "net": 100000000, "netAfterDiscount": 100000000,
              "vat": 0, "gross": 100000000}]
    r = fx.restate(Q(lines), "USD", 25500)
    assert r["lines"][0]["unitSell"] == 0


# ── edges ────────────────────────────────────────────────────────────────────────────────────────

def test_a_quotation_with_no_vat_places_a_zero_on_every_line():
    """An export. A zero VAT weight must not become a division by zero."""
    lines = [{"desc": "A", "qty": 1, "net": 500000000, "netAfterDiscount": 500000000,
              "vat": 0, "gross": 500000000},
             {"desc": "B", "qty": 1, "net": 500000000, "netAfterDiscount": 500000000,
              "vat": 0, "gross": 500000000}]
    r = fx.restate(Q(lines), "USD", 25500)
    assert all(l["vat"] == 0 for l in r["lines"])
    assert r["totals"]["vat"] == 0
    assert sum(l["minor"]["gross"] for l in r["lines"]) == round(r["totals"]["gross"] * 100)


def test_a_quotation_with_no_lines_is_not_a_crash():
    r = fx.restate(Q([]), "USD", 25500)
    assert r["lines"] == [] and r["totals"]["gross"] == 0


def test_check_answers_without_building_a_document():
    assert fx.check("usd", "25,500") == ("USD", 25500.0)
    with pytest.raises(fx.FxError):
        fx.check("USD", 0)


def test_a_lowercase_code_is_accepted():
    assert fx.restate(Q(), "usd", 25500)["currency"] == "USD"


# ── what quoting in a foreign currency actually costs you ────────────────────────────────────────

def test_the_margin_moves_when_the_rate_does():
    """The commercial point. The PRICE is fixed in the foreign currency; the COST stays in dong, so
    a dong that strengthens takes the difference straight out of the margin."""
    e = fx.exposure(Q(), "USD", 25500)
    at = {round(r["movePct"]): r for r in e["rows"]}
    assert at[0]["marginPct"] > at[-10]["marginPct"]
    assert at[10]["marginPct"] > at[0]["marginPct"]


def test_the_unchanged_rate_row_reproduces_the_quotations_own_margin():
    """If the 0% row disagreed with the tender, every other row would be measured from a wrong base."""
    q = Q()
    e = fx.exposure(q, "USD", 25500)
    base = next(r for r in e["rows"] if r["movePct"] == 0)
    expected = (q["net"] - q["cogs"]) / q["net"] * 100
    assert abs(base["marginPct"] - expected) < 0.01


def test_the_amount_the_customer_is_committed_to_is_stated():
    q = Q()
    e = fx.exposure(q, "USD", 25500)
    assert abs(e["quotedAmount"] - q["net"] / 25500) < 0.01


def test_the_rows_come_back_in_rate_order():
    e = fx.exposure(Q(), "USD", 25500)
    assert [r["movePct"] for r in e["rows"]] == sorted(r["movePct"] for r in e["rows"])


def test_exposure_refuses_a_bad_rate_the_same_way():
    with pytest.raises(fx.FxError):
        fx.exposure(Q(), "USD", 0)


def test_a_quotation_priced_at_nothing_has_no_exposure_rather_than_a_divide_by_zero():
    e = fx.exposure(Q([]), "USD", 25500)
    assert e["rows"] == [] and e["quotedAmount"] == 0.0
