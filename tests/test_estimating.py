"""Building a tender price: the arithmetic that decides whether a job makes money.

Four things are tested harder than the rest, because they are the four ways an estimate lies.

A heading that carries money double-counts its own children. A "20% margin" applied as a mark-up
takes 16.7% and nobody notices until the year-end accounts. Preliminaries spread across 300 lines
in integer dong lose money to flooring. And a total that mixes built-up rates with typed ones
implies a rigour it does not have.
"""
import pytest

import estimating as est


# ── a small, complete bill to price ──────────────────────────────────────────────────────────────

def _bill():
    return [
        {"id": "s1", "kind": est.SECTION, "desc": "Ductwork"},
        {"id": "a", "kind": est.ITEM, "desc": "Galvanised duct", "unit": "m2", "qty": 100},
        {"id": "n1", "kind": est.NOTE, "desc": "Rates exclude fire dampers"},
        {"id": "b", "kind": est.ITEM, "desc": "Insulation", "unit": "m2", "qty": 50},
    ]


def _resources():
    return {
        "a": [
            {"kind": est.MATERIAL, "code": "GI-1.0", "desc": "GI sheet 1.0mm", "unit": "kg",
             "qtyPer": 8, "unitCost": 25000, "wastePct": 10},
            {"kind": est.LABOUR, "desc": "Sheet metal worker", "unit": "hour",
             "qtyPer": 0.5, "unitCost": 60000},
        ],
        "b": [
            {"kind": est.MATERIAL, "code": "INS-25", "desc": "Rockwool 25mm", "unit": "m2",
             "qtyPer": 1.05, "unitCost": 90000},
            {"kind": est.LABOUR, "desc": "Insulator", "unit": "hour",
             "qtyPer": 0.25, "unitCost": 55000},
        ],
    }


# ── 1. structure carries no money ────────────────────────────────────────────────────────────────

def test_headings_and_notes_are_not_priced():
    """A section total that included itself would double-count everything beneath it."""
    assert [i["id"] for i in est.priced_items(_bill())] == ["a", "b"]


def test_a_bill_of_nothing_but_headings_prices_to_zero_rather_than_failing():
    s = est.summarise([{"id": "s", "kind": est.SECTION, "desc": "Preliminaries"}], {}, {})
    assert s["directCost"] == 0 and s["price"] == 0 and s["lineCount"] == 0


# ── 2. the rate is built, and waste is part of it ────────────────────────────────────────────────

def test_a_unit_rate_is_the_sum_of_its_resources_including_waste():
    # 8kg x 25,000 x 1.10 = 220,000 material; 0.5h x 60,000 = 30,000 labour.
    b = est.build_up(_resources()["a"])
    assert b["byKind"][est.MATERIAL] == 220_000
    assert b["byKind"][est.LABOUR] == 30_000
    assert b["unitCost"] == 250_000
    assert b["hoursPerUnit"] == 0.5


def test_waste_on_labour_counts_as_hours_too():
    """An allowance for rework is hours somebody will actually work, not a fudged rate."""
    b = est.build_up([{"kind": est.LABOUR, "desc": "Fitter", "qtyPer": 1, "unitCost": 50_000,
                       "wastePct": 20}])
    assert b["hoursPerUnit"] == 1.2
    assert b["unitCost"] == 60_000


# ── 3. built vs entered — the total must say which it is ─────────────────────────────────────────

def test_a_line_with_no_build_up_uses_the_entered_rate_and_says_so():
    line = est.price_item({"id": "x", "kind": est.ITEM, "qty": 10, "unitCost": 1_000}, [])
    assert line["basis"] == est.ENTERED
    assert line["directCost"] == 10_000
    assert line["unallocated"] == 10_000
    # It must NOT claim to be material — that lie would flow into the take-off and the budget.
    assert sum(line["byKind"].values()) == 0


def test_the_summary_reports_how_much_of_the_money_was_actually_built_up():
    items = _bill() + [{"id": "c", "kind": est.ITEM, "qty": 1, "unitCost": 25_000_000}]
    s = est.summarise(items, _resources(), {})
    # 25,000,000 + 4,062,500 built = 29,062,500 direct, of which the typed line is 25,000,000.
    assert s["enteredCost"] == 25_000_000
    assert s["builtUpCost"] == s["directCost"] - 25_000_000
    assert 0 < s["builtUpPct"] < 100


# ── 4. mark-up is not margin ─────────────────────────────────────────────────────────────────────

def test_twenty_percent_markup_is_not_a_twenty_percent_margin():
    """The most expensive arithmetic mistake in contracting, encoded so it cannot be made."""
    price = est.apply_profit(100, 20, est.MARKUP)
    assert price == 120
    assert est.achieved_margin(price, 100) == pytest.approx(16.67, abs=0.01)


def test_a_twenty_percent_margin_prices_higher_and_actually_takes_twenty():
    price = est.apply_profit(100, 20, est.MARGIN)
    assert price == 125
    assert est.achieved_margin(price, 100) == 20.0


def test_a_margin_of_a_hundred_percent_is_refused_rather_than_clamped():
    """There is no finite price. A capped answer would be a wrong number wearing a right one's
    clothes, so it raises and says which basis the user probably meant."""
    with pytest.raises(ValueError) as e:
        est.apply_profit(100, 100, est.MARGIN)
    assert "mark-up" in str(e.value)


def test_the_achieved_margin_is_reported_whichever_basis_was_used():
    s = est.summarise(_bill(), _resources(), {"profitPct": 20, "profitBasis": est.MARKUP})
    assert s["achievedMarginPct"] == pytest.approx(16.67, abs=0.01)
    assert s["profitBasis"] == est.MARKUP


# ── 5. the mark-up chain, in the order the trade applies it ──────────────────────────────────────

def test_overhead_risk_and_profit_compound_in_a_fixed_order():
    items = [{"id": "a", "kind": est.ITEM, "qty": 1, "unitCost": 1_000_000}]
    s = est.summarise(items, {}, {"siteOverhead": 200_000, "overheadPct": 10, "riskPct": 5,
                                  "profitPct": 10, "profitBasis": est.MARKUP})
    assert s["directCost"] == 1_000_000
    assert s["onSiteCost"] == 1_200_000            # + preliminaries
    assert s["overhead"] == 120_000                # 10% of 1,200,000
    assert s["risk"] == 66_000                     # 5% of 1,320,000
    assert s["costBase"] == 1_386_000
    assert s["price"] == 1_524_600                 # + 10% mark-up
    assert s["profit"] == 138_600


# ── 6. preliminaries must reconcile to the dong ──────────────────────────────────────────────────

def test_preliminaries_spread_across_lines_sum_exactly_to_the_lump():
    items = [{"id": str(i), "kind": est.ITEM, "qty": 1, "unitCost": 333} for i in range(7)]
    s = est.summarise(items, {}, {"siteOverhead": 100})
    assert sum(s["prelimShare"].values()) == 100


def test_a_line_with_no_cost_gets_no_share_of_the_preliminaries():
    items = [{"id": "a", "kind": est.ITEM, "qty": 1, "unitCost": 1_000_000},
             {"id": "b", "kind": est.ITEM, "qty": 0, "unitCost": 0}]
    s = est.summarise(items, {}, {"siteOverhead": 50_000})
    assert s["prelimShare"]["a"] == 50_000
    assert s["prelimShare"].get("b", 0) == 0


# ── 7. the priced lines must add back up to the price ────────────────────────────────────────────

def test_priced_lines_sum_exactly_to_the_estimate_price():
    """A unit-rate contract is signed on the line rates, not the total. If they disagree, the
    contract and the tender are two different documents."""
    lp = est.line_prices(_bill(), _resources(),
                         {"siteOverhead": 1_234_567, "overheadPct": 7.5, "riskPct": 3.25,
                          "profitPct": 12, "profitBasis": est.MARGIN})
    s = est.summarise(_bill(), _resources(),
                      {"siteOverhead": 1_234_567, "overheadPct": 7.5, "riskPct": 3.25,
                       "profitPct": 12, "profitBasis": est.MARGIN})
    assert lp["total"] == s["price"]
    assert sum(l["amount"] for l in lp["lines"].values()) == s["price"]


def test_a_line_rate_times_its_quantity_does_not_become_a_third_disagreeing_number():
    lp = est.line_prices([{"id": "a", "kind": est.ITEM, "qty": 3, "unitCost": 1_000}], {},
                         {"profitPct": 10, "profitBasis": est.MARKUP})
    a = lp["lines"]["a"]
    assert a["rate"] == est.vnd(a["amount"] / 3)


def test_a_wholly_provisional_bill_still_spreads_its_markups_rather_than_losing_them():
    lp = est.line_prices([{"id": "a", "kind": est.ITEM, "qty": 1, "unitCost": 0},
                          {"id": "b", "kind": est.ITEM, "qty": 1, "unitCost": 0}], {},
                         {"siteOverhead": 1_000_001})
    assert lp["total"] == 1_000_001


# ── 8. what the estimate hands on ────────────────────────────────────────────────────────────────

def test_the_take_off_gathers_the_same_material_from_every_line_it_appears_on():
    items = [{"id": "a", "kind": est.ITEM, "qty": 10}, {"id": "b", "kind": est.ITEM, "qty": 5}]
    res = {
        "a": [{"kind": est.MATERIAL, "code": "GI-1.0", "desc": "GI sheet", "unit": "kg",
               "qtyPer": 2, "unitCost": 25_000}],
        "b": [{"kind": est.MATERIAL, "code": "gi-1.0", "desc": "GI sheet", "unit": "kg",
               "qtyPer": 4, "unitCost": 25_000}],
    }
    rows = est.take_off(items, res)
    assert len(rows) == 1                      # one purchase, not two, despite the case difference
    assert rows[0]["qty"] == 40                # 10x2 + 5x4
    assert rows[0]["lines"] == 2


def test_the_take_off_buys_the_waste_too():
    rows = est.take_off([{"id": "a", "kind": est.ITEM, "qty": 100}],
                        {"a": [{"kind": est.MATERIAL, "desc": "Sheet", "unit": "kg",
                                "qtyPer": 1, "unitCost": 1_000, "wastePct": 10}]})
    assert rows[0]["qty"] == 110


def test_labour_take_off_reports_hours_and_the_blended_rate_per_trade():
    rows = est.labour_take_off(_bill(), _resources())
    trades = {r["trade"]: r for r in rows}
    assert trades["Sheet metal worker"]["hours"] == 50      # 100 m2 x 0.5h
    assert trades["Sheet metal worker"]["rate"] == 60_000


def test_the_project_budget_is_the_cost_base_and_deliberately_excludes_profit():
    """A job that spends its profit has not stayed within budget — it has eaten the reason the
    job was taken."""
    mk = {"siteOverhead": 500_000, "overheadPct": 10, "riskPct": 5, "profitPct": 15,
          "profitBasis": est.MARKUP}
    b = est.budget_lines(_bill(), _resources(), mk)
    s = est.summarise(_bill(), _resources(), mk)
    assert b["total"] == s["costBase"]
    assert b["total"] < s["price"]
    assert b["excludesProfit"] == s["profit"]


def test_budget_categories_match_the_ones_the_project_module_already_uses():
    b = est.budget_lines(_bill(), _resources(), {"siteOverhead": 1})
    cats = {l["category"] for l in b["lines"]}
    assert cats <= {"Labor", "Material", "Subcontract", "Equipment", "Overhead", "Other"}


def test_a_typed_rate_reaches_the_budget_as_its_own_line_rather_than_being_invented_into_a_category():
    b = est.budget_lines([{"id": "x", "kind": est.ITEM, "qty": 1, "unitCost": 9_000_000}], {}, {})
    other = [l for l in b["lines"] if l["category"] == "Other"]
    assert other and other[0]["amount"] == 9_000_000
    assert "entered rate" in other[0]["note"]


# ── 9. the rate library is copied, never referenced ──────────────────────────────────────────────

def test_using_a_library_rate_copies_it_so_a_submitted_tender_cannot_reprice_itself():
    lib = {"id": "r1", "code": "GI-1.0", "desc": "GI sheet 1.0mm", "unit": "kg",
           "unitCost": 25_000, "kind": est.MATERIAL, "effectiveFrom": "2026-01-01",
           "source": "Hoa Phat quote"}
    snap = est.snapshot(lib)
    lib["unitCost"] = 31_000                       # the market moves
    assert snap["unitCost"] == 25_000              # the tender does not
    assert snap["rateId"] == "r1" and snap["ratePricedOn"] == "2026-01-01"


def test_but_the_drift_is_surfaced_so_repricing_is_a_decision_not_an_accident():
    lib = [{"id": "r1", "code": "GI-1.0", "desc": "GI sheet", "unitCost": 31_000}]
    used = [{"rateId": "r1", "unitCost": 25_000}]
    drift = est.stale_rates(used, lib)
    assert len(drift) == 1
    assert drift[0]["estimatedAt"] == 25_000 and drift[0]["libraryNow"] == 31_000
    assert drift[0]["deltaPct"] == 24.0


def test_a_rate_that_has_not_moved_is_not_reported_as_drift():
    assert est.stale_rates([{"rateId": "r1", "unitCost": 25_000}],
                           [{"id": "r1", "unitCost": 25_000}]) == []


# ── 10. rubbish in must not become NaN out ───────────────────────────────────────────────────────

def test_blank_and_junk_cells_price_as_zero_rather_than_poisoning_the_total():
    items = [{"id": "a", "kind": est.ITEM, "qty": "", "unitCost": None},
             {"id": "b", "kind": est.ITEM, "qty": "abc", "unitCost": "1,000"},
             {"id": "c", "kind": est.ITEM, "qty": 2, "unitCost": 500}]
    s = est.summarise(items, {}, {"profitPct": 10})
    assert s["directCost"] == 1_000
    assert s["price"] == 1_100
