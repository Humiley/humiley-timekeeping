"""Which stations generate the rework — from data the floor already records.

Every NCR carries `stepCode` and `disposition`. Nothing aggregated them, so the question that says
where to fix the process had no answer while the answer was being typed in.

The arithmetic is counting. These tests are about the refusals, which is where a report like this
goes wrong and becomes actively harmful:

  * an NCR with no station is NOT spread, defaulted or dropped — it is named and counted
  * an NCR nobody dispositioned is NOT counted as rework
  * no cost and no rate are reported, because neither is recorded
"""
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

import ahu_rework as W   # noqa: E402


def _u(pin, *ncrs):
    return {"unit": {"id": pin, "pin": pin}, "ncr": list(ncrs)}


def _n(step, disp, kind="NCR"):
    return {"stepCode": step, "disposition": disp, "kind": kind}


def _by(out):
    return {g["code"]: g for g in out["stations"]}


# ── the answer it exists to give ────────────────────────────────────────────────────────────────

def test_it_names_the_station_that_generates_the_most_rework():
    units = [_u("P1", _n("WS-04", "Rework"), _n("WS-04", "Rework")),
             _u("P2", _n("WS-02", "Rework"))]
    out = W.summary(units)
    assert out["worstStation"] == "WS-04"
    assert out["stations"][0]["code"] == "WS-04"


def test_repair_counts_as_rework_and_use_as_is_does_not():
    """Both are decisions; only one means the unit was worked on again."""
    units = [_u("P1", _n("WS-04", "Repair"), _n("WS-04", "Use as is"))]
    g = _by(W.summary(units))["WS-04"]
    assert g["rework"] == 1 and g["useAsIs"] == 1 and g["total"] == 2


def test_a_reject_is_counted_separately_from_rework():
    g = _by(W.summary([_u("P1", _n("WS-06", "Reject"))]))["WS-06"]
    assert g["reject"] == 1 and g["rework"] == 0


def test_the_units_affected_are_counted_and_named():
    units = [_u("P1", _n("WS-04", "Rework")), _u("P2", _n("WS-04", "Rework"))]
    g = _by(W.summary(units))["WS-04"]
    assert g["units"] == 2 and g["pins"] == ["P1", "P2"]


def test_two_non_conformances_on_one_unit_are_two_events_but_one_unit():
    units = [_u("P1", _n("WS-04", "Rework"), _n("WS-04", "Rework"))]
    g = _by(W.summary(units))["WS-04"]
    assert g["rework"] == 2 and g["units"] == 1


# ── the refusals ────────────────────────────────────────────────────────────────────────────────

def test_an_ncr_with_no_station_is_named_not_spread_and_not_dropped():
    """THE refusal. Spreading it flatters no station and blames every one; dropping it makes the
    report quieter exactly as the record-keeping gets worse. The count is itself the signal."""
    out = W.summary([_u("P1", _n("", "Rework")), _u("P2", _n("WS-04", "Rework"))])
    assert out["unattributed"] == 1
    assert _by(out)[W.UNATTRIBUTED]["rework"] == 1
    assert _by(out)["WS-04"]["rework"] == 1, "the real station must not absorb the orphan"


def test_the_unattributed_row_never_ranks_among_the_stations():
    """It is a data-quality row, not a station. Ranking it first would read as an accusation of a
    station that does not exist."""
    out = W.summary([_u("P1", _n("", "Rework"), _n("", "Rework"), _n("", "Rework")),
                     _u("P2", _n("WS-04", "Rework"))])
    assert out["stations"][-1]["code"] == W.UNATTRIBUTED
    assert out["worstStation"] == "WS-04", "the worst STATION must be a real one"


def test_an_ncr_nobody_dispositioned_is_not_counted_as_rework():
    """Open, or closed without a decision recorded. Counting it as rework invents the decision;
    hiding it loses the fact that nobody made one."""
    g = _by(W.summary([_u("P1", _n("WS-04", ""))]))["WS-04"]
    assert g["rework"] == 0 and g["undecided"] == 1 and g["total"] == 1


def test_a_punch_item_is_not_a_non_conformance():
    """Snagging. The same rule the aging sweep and the gate checks already apply."""
    out = W.summary([_u("P1", _n("WS-04", "Rework", kind="punch"))])
    assert out["ncrTotal"] == 0 and out["stations"] == []


def test_no_cost_or_rate_is_reported_because_neither_is_recorded():
    """A fabricated rework cost put in front of a pricing decision is worse than an empty column,
    because it will be believed. The note has to say so where the numbers are."""
    out = W.summary([_u("P1", _n("WS-04", "Rework"))])
    assert "cost" not in out and "hours" not in out
    for g in out["stations"]:
        assert "cost" not in g and "hours" not in g and "pct" not in g
    assert "no hours and no money" in out["note"]
    assert "Nor is it a rate" in out["note"]


# ── shape ───────────────────────────────────────────────────────────────────────────────────────

def test_totals_agree_with_the_rows():
    units = [_u("P1", _n("WS-04", "Rework"), _n("WS-02", "Use as is")),
             _u("P2", _n("WS-04", "Reject"))]
    out = W.summary(units)
    assert out["ncrTotal"] == 3 and out["reworkTotal"] == 1
    assert sum(g["total"] for g in out["stations"]) == out["ncrTotal"]


def test_nothing_here_raises_on_empty_input():
    out = W.summary(None)
    assert out["stations"] == [] and out["reworkTotal"] == 0 and out["worstStation"] is None
    assert W.by_station([])["stations"] == []


# ── through the endpoint ────────────────────────────────────────────────────────────────────────

def test_the_kpi_endpoint_reports_where_the_rework_happens(api, tokens):
    """A pure module nothing calls answers nobody's question — the exact gap #173 and #175 closed
    for the other two features."""
    import db
    db.put_collection_item("ahu_orders", {"id": "rw-ord", "poNumber": "PO-RW"})
    db.put_collection_item("ahu_units", {"id": "rw-u1", "orderId": "rw-ord", "pin": "PIN-RW-1",
                                         "family": "modular", "status": "In production"})
    for i, (step, disp) in enumerate([("WS-04", "Rework"), ("WS-04", "Rework"),
                                      ("WS-02", "Use as is"), ("", "Rework")]):
        db.put_collection_item("ahu_ncr", {"id": "rw-n%d" % i, "unitId": "rw-u1", "kind": "NCR",
                                           "stepCode": step, "disposition": disp,
                                           "status": "Closed", "title": "n%d" % i})

    st, r = api("GET", "/api/ahu/kpi", tokens["admin"])
    assert st == 200
    assert "rework" in r, "the KPI screen does not report rework at all"
    rw = r["rework"]
    by = {g["code"]: g for g in rw["stations"]}
    assert by["WS-04"]["rework"] >= 2, by
    assert rw["unattributed"] >= 1, "the NCR with no step was absorbed somewhere"
    assert rw["worstStation"] == "WS-04"
    assert "no hours and no money" in rw["note"]
