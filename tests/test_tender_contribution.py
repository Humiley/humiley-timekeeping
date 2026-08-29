"""Which lines carry the profit.

The rule that gets the most tests is the one about a LOSS-MAKING tender: a share-of-profit
percentage taken against a negative total is not just useless, it inverts — the line losing the most
money would show the largest positive share and read as the best line on the bill.
"""
import tender_contribution as tc


def L(desc, revenue, cost, code=""):
    return {"itemCode": code, "desc": desc, "net": revenue,
            "netAfterDiscount": revenue, "cogs": cost}


def Q(*lines):
    return {"lines": list(lines)}


# ── the basic arithmetic, and that it matches the P&L ────────────────────────────────────────────

def test_profit_is_revenue_less_the_cost_of_that_line():
    c = tc.contribution(Q(L("A", 1000, 600)))
    r = c["rows"][0]
    assert r["revenue"] == 1000 and r["cost"] == 600 and r["profit"] == 400
    assert r["marginPct"] == 40.0


def test_the_totals_are_the_sum_of_the_lines():
    """If they were not, this screen and the P&L would state different profits for one tender."""
    c = tc.contribution(Q(L("A", 1000, 600), L("B", 500, 400)))
    assert c["totalRevenue"] == 1500 and c["totalCost"] == 1000
    assert c["totalProfit"] == 500
    assert round(c["marginPct"], 4) == round(500 / 1500 * 100, 4)


def test_the_discounted_revenue_is_used_not_the_pre_discount_one():
    """`net` is before the discount was apportioned across the lines. Using it would report a
    profit the tender is not making."""
    line = {"itemCode": "", "desc": "A", "net": 1000, "netAfterDiscount": 800, "cogs": 600}
    c = tc.contribution(Q(line))
    assert c["rows"][0]["revenue"] == 800 and c["rows"][0]["profit"] == 200


def test_a_line_with_no_discount_field_falls_back_to_net():
    """Not every engine writes netAfterDiscount when there is no discount."""
    c = tc.contribution(Q({"desc": "A", "net": 1000, "cogs": 600}))
    assert c["rows"][0]["revenue"] == 1000


# ── a line sold below cost ───────────────────────────────────────────────────────────────────────

def test_a_line_priced_below_its_cost_is_named():
    """Invisible in a gross profit that is still positive, and the first thing anybody would want
    to know."""
    c = tc.contribution(Q(L("Good", 1000, 400), L("Bad", 100, 300)))
    assert c["belowCostCount"] == 1
    assert c["belowCost"][0]["desc"] == "Bad"
    assert c["belowCost"][0]["profit"] == -200


def test_a_healthy_tender_reports_none_below_cost():
    c = tc.contribution(Q(L("A", 1000, 400), L("B", 500, 200)))
    assert c["belowCostCount"] == 0 and c["belowCost"] == []


def test_a_line_sold_exactly_at_cost_is_not_flagged_as_below_it():
    """Zero margin is a decision somebody may have taken. Negative is not."""
    c = tc.contribution(Q(L("A", 500, 500)))
    assert c["belowCostCount"] == 0
    assert c["rows"][0]["marginPct"] == 0.0


def test_a_free_line_reports_no_margin_rather_than_zero_margin():
    """0% reads as 'sold at cost'. A line with no revenue at all is a different thing."""
    c = tc.contribution(Q(L("Freebie", 0, 0)))
    assert c["rows"][0]["marginPct"] is None


# ── share of profit is withheld when it would mislead ────────────────────────────────────────────

def test_a_loss_making_tender_withholds_the_shares():
    """THE rule. Against a negative total the line losing MOST would show the largest positive
    share and read as the best line on the bill."""
    c = tc.contribution(Q(L("A", 100, 500), L("B", 100, 200)))
    assert c["totalProfit"] < 0
    assert c["shareMeaningful"] is False
    assert all(r["sharePct"] is None for r in c["rows"])


def test_a_tender_that_exactly_breaks_even_also_withholds_them():
    """Dividing by zero, or by something indistinguishable from it."""
    c = tc.contribution(Q(L("A", 500, 500)))
    assert c["shareMeaningful"] is False
    assert c["rows"][0]["sharePct"] is None


def test_shares_are_given_when_there_is_a_profit_and_they_add_up():
    c = tc.contribution(Q(L("A", 1000, 600), L("B", 1000, 800)))
    assert c["shareMeaningful"] is True
    assert round(sum(r["sharePct"] for r in c["rows"]), 6) == 100.0
    assert round(c["rows"][0]["sharePct"]) == 67      # 400 of 600


# ── concentration ────────────────────────────────────────────────────────────────────────────────

def test_a_bid_whose_profit_sits_in_a_couple_of_lines_is_flagged():
    """A client who negotiates exactly those lines takes the whole margin."""
    lines = [L("Big", 10000, 2000)] + [L("Small %d" % i, 100, 95) for i in range(19)]
    c = tc.contribution(Q(*lines))
    assert c["carriers"] == 1 and c["carriersOf"] == 20
    assert c["concentrated"] is True


def test_an_evenly_spread_bid_is_not_flagged():
    """A completely different commercial position, and the totals look identical."""
    lines = [L("L%d" % i, 1000, 600) for i in range(10)]
    c = tc.contribution(Q(*lines))
    assert c["carriers"] == 8            # 80% of an even spread takes 8 of 10
    assert c["concentrated"] is False


def test_the_carrier_count_stops_as_soon_as_the_share_is_reached():
    c = tc.contribution(Q(L("A", 1000, 100), L("B", 1000, 900), L("C", 1000, 950)))
    # profits 900, 100, 50 — the first alone is 85.7% of 1050
    assert c["carriers"] == 1


def test_a_loss_making_line_does_not_shorten_the_carrier_count():
    """Adding a negative to a running total makes the bid look MORE concentrated than it is."""
    even = [L("L%d" % i, 1000, 600) for i in range(10)]
    c1 = tc.contribution(Q(*even))
    c2 = tc.contribution(Q(*(even + [L("Bad", 10, 500)])))
    assert c2["carriers"] >= c1["carriers"]


def test_concentration_is_not_claimed_for_a_loss_making_tender():
    c = tc.contribution(Q(L("A", 100, 500)))
    assert c["carriers"] == 0 and c["concentrated"] is False


# ── ordering ─────────────────────────────────────────────────────────────────────────────────────

def test_the_biggest_contributor_is_first():
    c = tc.contribution(Q(L("Small", 100, 50), L("Big", 5000, 1000), L("Mid", 1000, 500)))
    assert [r["desc"] for r in c["rows"]] == ["Big", "Mid", "Small"]


def test_the_loss_makers_sink_to_the_bottom():
    c = tc.contribution(Q(L("Bad", 100, 900), L("Good", 1000, 100)))
    assert c["rows"][0]["desc"] == "Good" and c["rows"][-1]["desc"] == "Bad"


def test_the_order_is_deterministic_when_two_lines_contribute_the_same():
    """Otherwise the table reshuffles between two identical loads."""
    a = tc.contribution(Q(L("Zeta", 1000, 600, "Z"), L("Alpha", 1000, 600, "A")))
    b = tc.contribution(Q(L("Alpha", 1000, 600, "A"), L("Zeta", 1000, 600, "Z")))
    assert [r["desc"] for r in a["rows"]] == [r["desc"] for r in b["rows"]]


# ── edges ────────────────────────────────────────────────────────────────────────────────────────

def test_an_empty_quotation_is_not_a_crash():
    for empty in ({}, {"lines": []}, {"lines": None}, None):
        c = tc.contribution(empty)
        assert c["rows"] == [] and c["totalProfit"] == 0
        assert c["marginPct"] is None and c["concentrated"] is False


def test_money_typed_with_separators_is_read_as_money():
    c = tc.contribution(Q({"desc": "A", "netAfterDiscount": "1,000", "cogs": "600"}))
    assert c["rows"][0]["profit"] == 400


def test_a_line_with_no_cost_recorded_shows_the_whole_revenue_as_profit():
    """True, and it is what a missing cost looks like — better shown than silently treated as
    break-even."""
    c = tc.contribution(Q({"desc": "A", "netAfterDiscount": 1000}))
    assert c["rows"][0]["cost"] == 0 and c["rows"][0]["profit"] == 1000
