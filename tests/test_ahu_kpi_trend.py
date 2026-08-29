"""Eight numbers with no history cannot say whether anything is improving.

`summary()` reports where the factory is. `monthly()` reports which way it is going, which is the
only question a KPI is any use for.

The arithmetic is a division. What these tests are really about is the three judgements around it,
each of which could plausibly have gone the other way and would have produced a chart that lies:

  * each KPI is filed under ITS OWN event, so recent inspected-but-unshipped units still appear in
    the yield series
  * a month with too few units is LABELLED, not hidden — a gap in a chart reads as "no problem"
  * a unit with no readable date is COUNTED as unbucketed, never silently dropped
"""
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

import ahu_kpi as K   # noqa: E402


def _unit(pin, g4=None, dispatched=None, due=None, failed=False, rework=False):
    steps = []
    if g4:
        steps.append({"code": "G4", "kind": "gate", "status": "Passed", "signedOn": g4})
    if failed:
        steps.append({"code": "T1", "kind": "test", "status": "Failed"})
    return {
        "unit": {"id": pin, "pin": pin},
        "steps": steps,
        "ncr": [{"disposition": "rework"}] if rework else [],
        "dispatch": [{"dispatchedOn": dispatched}] if dispatched else [],
        "order": {"deliveryDate": due} if due else {},
    }


def _by_month(series):
    return {r["month"]: r for r in series}


# ── the series itself ───────────────────────────────────────────────────────────────────────────

def test_yield_is_reported_per_month_oldest_first():
    units = [_unit("A", g4="2026-06-10"), _unit("B", g4="2026-07-11"),
             _unit("C", g4="2026-08-12")]
    out = K.monthly(units)
    assert [r["month"] for r in out["firstPassYield"]] == ["2026-06", "2026-07", "2026-08"]


def test_a_failed_test_costs_that_month_its_pass():
    units = [_unit("A", g4="2026-08-01"), _unit("B", g4="2026-08-02", failed=True)]
    m = _by_month(K.monthly(units)["firstPassYield"])["2026-08"]
    assert m["n"] == 2 and m["good"] == 1 and m["pct"] == 50.0


def test_rework_costs_the_pass_too_even_with_every_step_signed():
    units = [_unit("A", g4="2026-08-01", rework=True)]
    m = _by_month(K.monthly(units)["firstPassYield"])["2026-08"]
    assert m["good"] == 0


def test_delivery_is_filed_under_the_month_it_SHIPPED():
    units = [_unit("A", dispatched="2026-08-20", due="2026-08-31")]
    out = K.monthly(units)
    assert [r["month"] for r in out["onTimeDelivery"]] == ["2026-08"]
    assert out["onTimeDelivery"][0]["good"] == 1


def test_a_late_unit_is_not_counted_on_time():
    units = [_unit("A", dispatched="2026-09-05", due="2026-08-31")]
    assert K.monthly(units)["onTimeDelivery"][0]["good"] == 0


# ── each KPI under its own event ────────────────────────────────────────────────────────────────

def test_a_unit_inspected_but_not_shipped_still_appears_in_the_yield_series():
    """THE bucketing decision. Filing both KPIs under the dispatch date would drop this unit from
    yield entirely — and it is the most recent data, which is the part anyone looks at."""
    out = K.monthly([_unit("A", g4="2026-08-05")])
    assert [r["month"] for r in out["firstPassYield"]] == ["2026-08"]
    assert out["onTimeDelivery"] == [], "an unshipped unit must not appear in delivery"


def test_the_two_series_can_sit_in_different_months_for_one_unit():
    """Inspected in July, shipped in August. Both facts are true and belong in different buckets."""
    out = K.monthly([_unit("A", g4="2026-07-20", dispatched="2026-08-03", due="2026-08-31")])
    assert out["firstPassYield"][0]["month"] == "2026-07"
    assert out["onTimeDelivery"][0]["month"] == "2026-08"


# ── the small-sample label ──────────────────────────────────────────────────────────────────────

def test_a_thin_month_is_shown_with_its_count_and_marked_unreadable():
    """One failure in a month of two is 50%, and next to a month of forty that reads as a collapse.
    The point is kept — a gap in a chart reads as 'no problem' rather than 'no evidence'."""
    out = K.monthly([_unit("A", g4="2026-08-01"), _unit("B", g4="2026-08-02", failed=True)])
    m = _by_month(out["firstPassYield"])["2026-08"]
    assert m["enough"] is False and m["n"] == 2
    assert m["pct"] == 50.0, "the number is still reported, just flagged"


def test_a_month_with_enough_units_reads_as_readable():
    units = [_unit("U%d" % i, g4="2026-08-%02d" % (i + 1)) for i in range(K.MIN_N_TO_READ)]
    m = _by_month(K.monthly(units)["firstPassYield"])["2026-08"]
    assert m["enough"] is True and m["n"] == K.MIN_N_TO_READ


# ── nothing is silently dropped ─────────────────────────────────────────────────────────────────

def test_a_unit_with_an_unreadable_date_is_counted_not_dropped():
    """A trend quietly computed over only the well-dated subset would move whenever the paperwork
    changed, and look like a change in performance."""
    out = K.monthly([_unit("A", g4="last August"),
                     _unit("B", dispatched="whenever", due="2026-08-31")])
    assert out["firstPassYield"] == [] and out["onTimeDelivery"] == []
    assert out["unbucketed"] == {"firstPassYield": 1, "onTimeDelivery": 1}


def test_a_shipped_unit_with_no_contracted_date_counts_in_n_but_never_as_on_time():
    """It shipped, so the month's sample size must include it. There is nothing to measure it
    against, so calling it on time would be inventing the answer."""
    m = K.monthly([_unit("A", dispatched="2026-08-10")])["onTimeDelivery"][0]
    assert m["n"] == 1 and m["good"] == 0


# ── the window, and empty input ─────────────────────────────────────────────────────────────────

def test_only_the_most_recent_months_are_returned():
    units = [_unit("U%d" % i, g4="2026-%02d-05" % (i + 1)) for i in range(9)]
    out = K.monthly(units, months=3)
    assert [r["month"] for r in out["firstPassYield"]] == ["2026-07", "2026-08", "2026-09"]


def test_the_series_ends_where_the_DATA_ends_not_at_a_clock():
    """Pure, like the rest of the module. Trailing empty months would look like a stoppage."""
    out = K.monthly([_unit("A", g4="2026-03-01")], months=12)
    assert [r["month"] for r in out["firstPassYield"]] == ["2026-03"]


def test_nothing_here_raises_on_empty_input():
    out = K.monthly(None)
    assert out["firstPassYield"] == [] and out["onTimeDelivery"] == []
    assert out["unbucketed"] == {"firstPassYield": 0, "onTimeDelivery": 0}


# ── through the endpoint ────────────────────────────────────────────────────────────────────────

def _seed(uid, pin, g4, dispatched, due):
    import db
    db.put_collection_item("ahu_orders", {"id": "trend-ord", "poNumber": "PO-TREND",
                                          "deliveryDate": due})
    db.put_collection_item("ahu_units", {"id": uid, "orderId": "trend-ord", "pin": pin,
                                         "family": "modular", "status": "Dispatched"})
    db.put_collection_item("ahu_steps", {"id": uid + "-G4", "unitId": uid, "code": "G4",
                                         "kind": "gate", "seq": 40, "status": "Passed",
                                         "signedOn": g4})
    db.put_collection_item("ahu_dispatch", {"id": uid + "-d", "unitId": uid,
                                            "dispatchedOn": dispatched})


def test_the_trend_ignores_since_so_it_can_still_compare(api, tokens):
    """`since` scopes the SNAPSHOT — "what did we ship in this window". Applying it to the trend
    would drop the earlier months the trend exists to compare against, answering "is this
    improving?" using only the recent end.
    """
    _seed("trend-old", "PIN-TREND-OLD", "2026-01-10", "2026-01-20", "2026-01-31")
    _seed("trend-new", "PIN-TREND-NEW", "2026-08-10", "2026-08-20", "2026-08-31")

    st, r = api("GET", "/api/ahu/kpi?since=2026-08-01", tokens["admin"])
    assert st == 200
    months = [x["month"] for x in r["trend"]["onTimeDelivery"]]
    assert "2026-01" in months, (
        "the trend was truncated by `since` and can no longer compare: %s" % months)
    assert "2026-08" in months


def test_the_endpoint_returns_a_trend_at_all(api, tokens):
    st, r = api("GET", "/api/ahu/kpi", tokens["admin"])
    assert st == 200
    assert "trend" in r and "firstPassYield" in r["trend"]
    assert r["trend"]["minN"] == K.MIN_N_TO_READ
