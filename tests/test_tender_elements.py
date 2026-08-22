"""What the money is spent ON, and what it costs per unit.

A tender could say what each LINE costs and what each COST CENTRE costs, and could not answer the
question a commercial manager actually asks: how much of this job is labour? Labour is the exposure
that moves when a programme slips; imported material is the exposure that moves when the dong does;
subcontract is exposure somebody else is carrying. Three different risks wearing the same total.

And a total cannot be sanity-checked. A billion-dong total looks like any other billion-dong total.
The check an estimator actually applies is "is this the right price per square metre" against the
last three jobs — which needs a rate, so a tender with no benchmark quantity can only be checked by
whoever remembers the last one.
"""
import pytest

import tender


A = tender.assumptions()
BOM = [{"costCentre": "CIV", "qty": 1, "unitCostUsd": 400000},
       {"costCentre": "MEP", "qty": 1, "unitCostUsd": 300000},
       {"costCentre": "CLR", "qty": 1, "unitCostUsd": 120000},
       {"costCentre": "CUT", "qty": 1, "unitCostUsd": 90000, "element": "plant"},
       {"costCentre": "CON", "qty": 1, "unitCostUsd": 40000}]
PKGS = [{"id": "1", "code": "WP-00", "name": "PM", "durationMonths": 12,
         "daysDIR": 10, "daysADM": 24, "travelPeople": 1, "travelTrips": 4, "travelNights": 2}]
IMP = {"qty": 1, "exwUnit": 100000, "currency": "USD", "mfnDutyPct": 10, "sctPct": 5}


def _epc(**kw):
    t = dict({"costingType": tender.EPC, "vatPct": 10, "assump": {}}, **kw)
    r = tender.bom_rollup(BOM, A)
    return t, tender.quotation(t, rollup=r), r


def _services(**kw):
    t = dict({"costingType": tender.SERVICES, "vatPct": 10, "assump": {}}, **kw)
    r = tender.services_rollup(PKGS, A)
    return t, tender.quotation(t, rollup=r), r


def _trading(**kw):
    t = dict({"costingType": tender.TRADING, "vatPct": 10, "assump": {},
              "imports": [dict(IMP, id="L1", desc="Pump")],
              "locals": [{"id": "L2", "desc": "Steel", "qty": 1, "unitPrice": 250_000_000}]}, **kw)
    m = tender.cost_master(t["imports"], t["locals"], A)
    return t, tender.quotation(t, master=m), m


# --- the invariant ------------------------------------------------------------------------------

@pytest.mark.parametrize("build", ["epc", "services", "trading"])
def test_the_elements_account_for_the_whole_cost_base(build):
    """Every dong is in exactly one element. A breakdown that does not add up to the total is a
    breakdown of something else."""
    t, q, x = {"epc": _epc, "services": _services, "trading": _trading}[build]()
    el = tender.cost_elements(t, master=x if build == "trading" else None,
                              rollup=None if build == "trading" else x)
    assert el["total"] == q["cogs"]
    assert sum(r["amount"] for r in el["rows"]) == el["total"]


def test_percentages_are_of_the_cost_base_not_the_selling_price():
    """A percentage that moves when the mark-up moves answers a different question every time
    somebody edits the margin."""
    t, q, r = _epc()
    el = tender.cost_elements(t, rollup=r)
    for row in el["rows"]:
        assert row["pct"] == pytest.approx(row["amount"] / q["cogs"] * 100, abs=0.01)
    assert sum(r_["pct"] for r_ in el["rows"]) == pytest.approx(100.0, abs=0.05)


# --- the vocabulary is shared, not restated ------------------------------------------------------

def test_the_element_names_come_from_the_estimating_module():
    """A tender priced as a BoQ and one priced as a bill of materials must answer "what is our
    labour exposure" in the same words, or the answers cannot be added across a portfolio."""
    import estimating
    assert tender.ELEMENTS == (estimating.MATERIAL, estimating.LABOUR,
                               estimating.PLANT, estimating.SUBCONTRACT)


# --- where the element comes from ----------------------------------------------------------------

def test_a_bom_line_can_name_its_own_element():
    t, _q, r = _epc()
    el = tender.cost_elements(t, rollup=r)
    plant = [x for x in el["rows"] if x["key"] == "plant"]
    assert plant and plant[0]["amount"] == tender.vnd(90000 * A["fxUsd"])


def test_a_line_without_one_inherits_its_cost_centre_default():
    """Defaulting everything to material would report a plant with no labour and no subcontract in
    it — not a cautious guess, a wrong answer."""
    assert tender.line_element({"costCentre": "CIV"}) == "subcontract"
    assert tender.line_element({"costCentre": "CON"}) == "labour"
    assert tender.line_element({"costCentre": "QCL"}) == "material"


def test_an_explicit_element_beats_the_centre_default():
    assert tender.line_element({"costCentre": "CIV", "element": "labour"}) == "labour"


def test_an_unknown_element_falls_back_rather_than_inventing_a_category():
    assert tender.line_element({"costCentre": "CIV", "element": "wishes"}) == "subcontract"


# --- derived where the engine already knows ------------------------------------------------------

def test_services_is_labour_and_travel_without_anyone_typing_it():
    """Days times a rate IS labour. Asking somebody to re-declare that would be a data-entry tax on
    a fact already in the model, and a second place for it to be wrong."""
    t, q, r = _services()
    el = tender.cost_elements(t, rollup=r)
    keys = {x["key"] for x in el["rows"]}
    assert keys == {"labour", "expenses"}
    assert el["labourPct"] > 50


def test_trading_separates_duty_and_freight_from_the_goods():
    """Folding them into "material" would report an equipment exposure that is really freight and
    tax — and a portfolio roll-up would then double-count them."""
    t, q, m = _trading()
    el = tender.cost_elements(t, master=m)
    keys = {x["key"] for x in el["rows"]}
    assert "duty" in keys and "logistics" in keys and "material" in keys
    assert "duty" not in tender.ELEMENTS and "logistics" not in tender.ELEMENTS


def test_locally_bought_goods_carry_no_duty_or_freight():
    t, q, m = _trading()
    el = tender.cost_elements(t, master=m)
    material = next(x for x in el["rows"] if x["key"] == "material")
    assert material["amount"] > 250_000_000, "the local purchase is missing from material"


def test_the_two_exposures_a_manager_asks_for_by_name_are_lifted_out():
    t, q, r = _epc()
    el = tender.cost_elements(t, rollup=r)
    assert el["subcontractPct"] > 50, "this fixture is mostly subcontract"
    assert el["labourPct"] > 0


# --- benchmarks -----------------------------------------------------------------------------------

def test_a_benchmark_turns_a_total_into_a_rate():
    t, q, r = _epc(benchmarkQty=4800, benchmarkUnit="m2")
    bm = tender.benchmarks(t, q, tender.cost_elements(t, rollup=r))
    assert bm["available"]
    cost = next(x for x in bm["rows"] if x["label"] == "Cost per m2")
    assert cost["value"] == tender.vnd(q["cogs"] / 4800)
    price = next(x for x in bm["rows"] if x["label"] == "Price per m2")
    assert price["value"] > cost["value"]


def test_each_element_also_gets_a_rate():
    """"Our labour is 212,500 per m2" is comparable with the last job; "our labour is 1.02bn" is
    not."""
    t, q, r = _epc(benchmarkQty=4800, benchmarkUnit="m2")
    labels = [x["label"] for x in tender.benchmarks(t, q, tender.cost_elements(t, rollup=r))["rows"]]
    assert any("Labour per m2" == l for l in labels)


def test_no_quantity_means_no_benchmark_rather_than_a_division_by_zero():
    t, q, r = _epc()
    bm = tender.benchmarks(t, q, tender.cost_elements(t, rollup=r))
    assert bm["available"] is False and bm["rows"] == []


def test_a_unit_without_a_quantity_is_not_a_benchmark():
    t, q, r = _epc(benchmarkUnit="m2")
    assert tender.benchmarks(t, q, tender.cost_elements(t, rollup=r))["available"] is False


def test_a_negative_quantity_is_refused_not_divided_by():
    t, q, r = _epc(benchmarkQty=-100, benchmarkUnit="m2")
    assert tender.benchmarks(t, q, tender.cost_elements(t, rollup=r))["available"] is False


def test_an_empty_tender_has_no_elements_rather_than_a_zero_row_for_each():
    t = {"costingType": tender.EPC, "vatPct": 10, "assump": {}}
    r = tender.bom_rollup([], A)
    el = tender.cost_elements(t, rollup=r)
    assert el["rows"] == [] and el["total"] == 0
    assert el["labourPct"] == 0
