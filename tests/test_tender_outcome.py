"""Win/loss: the two rates that disagree, and the exclusions that must stay visible.

A hit rate is a number people plan capacity against, so the tests that matter here are the ones
about what is COUNTED — a denominator that quietly changed is how a rate comes to describe a sample
nobody chose.
"""
import tender_outcome as out


def T(status, value=0, reason="", client="Acme", ctype="trading", **kw):
    d = {"status": status, "quotedPrice": value, "outcomeReason": reason,
         "client": client, "costingType": ctype, "decidedOn": "2026-05-01"}
    d.update(kw)
    return d


# ── by count is not by value ─────────────────────────────────────────────────────────────────────

def test_the_two_rates_are_reported_together_and_can_disagree_wildly():
    """THE finding. Nine small wins and one large loss: 90% by count, 15% by value. A business that
    reads only the first plans a year it does not have the work for."""
    rows = [T(out.WON, 100) for _ in range(9)] + [T(out.LOST, 5000)]
    r = out.hit_rate(rows)
    assert round(r["byCount"]) == 90
    assert round(r["byValue"]) == 15
    assert r["byCount"] != r["byValue"]


def test_by_value_uses_money_not_headcount():
    rows = [T(out.WON, 300), T(out.LOST, 100)]
    r = out.hit_rate(rows)
    assert r["byCount"] == 50.0
    assert r["byValue"] == 75.0
    assert r["wonValue"] == 300 and r["decidedValue"] == 400


# ── what is excluded, and the fact that it says so ───────────────────────────────────────────────

def test_a_cancelled_tender_is_not_a_loss():
    """The client shelved the project. Nobody beat us; counting it measures the weather."""
    rows = [T(out.WON, 100), T(out.CANCELLED, 900)]
    r = out.hit_rate(rows)
    assert r["decided"] == 1 and r["byCount"] == 100.0
    assert r["byValue"] == 100.0
    assert r["cancelledExcluded"] == 1


def test_the_exclusion_is_reported_not_silent():
    """A denominator that shrank without saying so is the defect, not the exclusion itself."""
    rows = [T(out.WON, 100)] + [T(out.CANCELLED, 100) for _ in range(3)]
    assert out.hit_rate(rows)["cancelledExcluded"] == 3


def test_an_undecided_tender_is_in_neither_side():
    rows = [T(out.WON, 100), T("Draft", 900), T("Submitted", 900)]
    r = out.hit_rate(rows)
    assert r["decided"] == 1 and r["byCount"] == 100.0


def test_a_decided_tender_with_no_price_is_counted_but_flagged():
    """It belongs in the by-count rate. Letting it into the by-value denominator as zero would read
    as a pricing problem instead of a missing number."""
    rows = [T(out.WON, 100), T(out.LOST, 0)]
    r = out.hit_rate(rows)
    assert r["decided"] == 2 and r["byCount"] == 50.0
    assert r["byValue"] == 100.0                 # the priced tenders alone
    assert r["unpricedExcludedFromValue"] == 1


def test_nothing_decided_is_not_a_zero_percent_hit_rate():
    """Zero would read as 'we lose everything'. There is no rate yet."""
    r = out.hit_rate([T("Draft", 100), T("Submitted", 200)])
    assert r["byCount"] is None and r["byValue"] is None
    assert r["decided"] == 0


def test_an_empty_register_does_not_divide_by_zero():
    r = out.hit_rate([])
    assert r["byCount"] is None and r["byValue"] is None and r["decided"] == 0


# ── a decision needs a reason ────────────────────────────────────────────────────────────────────

def test_a_loss_with_no_reason_is_refused():
    miss = out.decision_check(T(out.LOST, 100, reason=""))
    assert any("why" in m.lower() for m in miss), miss


def test_a_win_needs_one_too():
    """Knowing why we win is how a company repeats it."""
    assert out.decision_check(T(out.WON, 100, reason=""))


def test_a_reason_off_the_list_is_refused():
    """Free text cannot be counted, and the point is to say 'four of the last six on lead time'."""
    miss = out.decision_check(T(out.LOST, 100, reason="they didn't like us"))
    assert any("from the list" in m for m in miss), miss


def test_a_good_reason_passes():
    assert out.decision_check(T(out.LOST, 100, reason="Delivery / lead time")) == []


def test_the_decision_date_is_required():
    t = T(out.LOST, 100, reason="Price")
    t["decidedOn"] = ""
    assert any("date" in m.lower() for m in out.decision_check(t))


def test_a_draft_is_not_asked_for_a_reason():
    """The rule applies to an outcome, not to every save."""
    assert out.decision_check(T("Draft", 100, reason="")) == []
    assert out.decision_check(T("Submitted", 100, reason="")) == []


def test_a_cancelled_tender_is_not_asked_for_a_reason_either():
    """It has no outcome the estimating team owns."""
    assert out.decision_check(T(out.CANCELLED, 100, reason="")) == []


# ── the price gap is measured, never invented ────────────────────────────────────────────────────

def test_the_gap_is_none_when_nobody_knows_the_winning_price():
    assert out.price_gap(T(out.LOST, 1000)) is None
    assert out.price_gap(T(out.LOST, 1000, winningPrice=0)) is None


def test_the_gap_is_a_share_of_the_price_that_won():
    t = T(out.LOST, 1100, winningPrice=1000)
    assert round(out.price_gap(t), 1) == 10.0


def test_being_cheaper_and_still_losing_shows_a_negative_gap():
    """It happens, and it is the most informative loss there is — it was not the price."""
    t = T(out.LOST, 900, winningPrice=1000)
    assert round(out.price_gap(t), 1) == -10.0


def test_the_average_gap_states_how_many_it_knows():
    rows = [T(out.LOST, 1100, "Price", winningPrice=1000),
            T(out.LOST, 1200, "Price", winningPrice=1000),
            T(out.LOST, 5000, "Price")]                     # nobody found out
    g = out.gaps(rows)
    assert g["known"] == 2 and g["lost"] == 3
    assert round(g["avgPct"], 1) == 15.0                    # NOT diluted by the unknown one
    assert round(g["worstPct"], 1) == 20.0


def test_no_known_gaps_is_not_a_gap_of_zero():
    g = out.gaps([T(out.LOST, 5000, "Price")])
    assert g["avgPct"] is None and g["known"] == 0


# ── grouping ─────────────────────────────────────────────────────────────────────────────────────

def test_losses_are_grouped_by_reason_commonest_first():
    rows = [T(out.LOST, 100, "Price"), T(out.LOST, 100, "Price"),
            T(out.LOST, 100, "Delivery / lead time"), T(out.WON, 100, "Price")]
    r = out.by_reason(rows)
    assert r[0]["reason"] == "Price" and r[0]["count"] == 2      # the win is not in here
    assert r[1]["reason"] == "Delivery / lead time"


def test_a_win_reason_never_lands_in_the_loss_table():
    """Otherwise 'Price' means both 'we were too expensive' and 'we were the cheapest'."""
    rows = [T(out.WON, 100, "Price")]
    assert out.by_reason(rows) == []


def test_a_loss_with_no_reason_recorded_is_shown_as_such():
    """Historic rows predate the rule. Dropping them would understate the losses."""
    r = out.by_reason([T(out.LOST, 100, "")])
    assert r[0]["reason"] == "(not recorded)" and r[0]["count"] == 1


def test_customers_are_rated_the_same_way_the_whole_set_is():
    rows = [T(out.WON, 300, "Price", client="Acme"),
            T(out.LOST, 100, "Price", client="Acme"),
            T(out.LOST, 500, "Price", client="Beta")]
    by = {x["key"]: x for x in out.by_customer(rows)}
    assert by["Acme"]["byCount"] == 50.0 and by["Acme"]["byValue"] == 75.0
    assert by["Beta"]["byCount"] == 0.0


def test_the_biggest_sample_heads_the_table():
    """A 100% rate off one tender is not the headline."""
    rows = [T(out.WON, 10, "Price", client="Tiny")] + \
           [T(out.LOST, 100, "Price", client="Big") for _ in range(4)]
    assert out.by_customer(rows)[0]["key"] == "Big"


def test_grouping_ignores_undecided_tenders():
    rows = [T("Draft", 900, client="Ghost"), T(out.WON, 100, "Price", client="Acme")]
    assert [x["key"] for x in out.by_customer(rows)] == ["Acme"]


def test_the_summary_carries_every_table_the_screen_draws():
    s = out.summary([T(out.WON, 100, "Price"), T(out.LOST, 200, "Payment terms")])
    for k in ("hit", "lossReasons", "byCustomer", "byCostingType", "priceGap", "reasons"):
        assert k in s, k
    assert s["reasons"] == list(out.REASONS)


def test_money_written_with_separators_still_counts():
    """The money fields are typed with thousand separators by the form."""
    r = out.hit_rate([T(out.WON, "1,000,000"), T(out.LOST, "1,000,000")])
    assert r["decidedValue"] == 2000000
