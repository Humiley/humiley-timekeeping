"""A won tender becomes the budget the job is measured against.

Pricing a job and controlling it were two disconnected halves. `estimating.budget_lines` hands a
BoQ estimate to a project as its baseline; nothing did the same for the three engines in `tender`.
A trading deal, a turnkey plant or a consultancy engagement could be priced to the dong, won, and
then spent against nothing at all — so what it actually cost was never compared with what it was
said to cost. Cost control is a COMPARISON; without a baseline in the project there is no
comparison, only a second number arriving later with nothing to sit beside.

Each engine hands over the structure it was priced in, because that is the structure the job is
controlled in. A budget in some other shape has to be re-mapped by hand every month, which is the
same as not having one.
"""
import pytest

import tender


A = tender.assumptions()
IMP = {"qty": 1, "exwUnit": 100000, "currency": "USD", "mfnDutyPct": 10, "sctPct": 5}
BOM = [{"costCentre": c, "qty": 1, "unitCostUsd": v}
       for c, v in (("CIV", 400000), ("MEP", 300000), ("CLR", 120000), ("CON", 40000))]
PKGS = [{"id": "1", "code": "WP-00", "name": "PM & kick-off", "durationMonths": 12,
         "daysDIR": 10, "daysADM": 24, "travelPeople": 1, "travelTrips": 4, "travelNights": 2},
        {"id": "2", "code": "WP-01", "name": "Facility assessment", "durationMonths": 2,
         "daysSME": 12, "daysENG": 18, "travelPeople": 2, "travelTrips": 2, "travelNights": 4}]


def _trading(assump=None):
    t = {"costingType": tender.TRADING, "vatPct": 10, "assump": assump or {},
         "imports": [dict(IMP, id="L1", desc="Pump"), dict(IMP, id="L2", desc="Valve", exwUnit=4000)],
         "locals": [{"id": "L3", "desc": "Local steel", "qty": 1, "unitPrice": 250_000_000}]}
    m = tender.cost_master(t["imports"], t["locals"], A)
    return t, tender.quotation(t, master=m), m


def _epc(assump=None):
    t = {"costingType": tender.EPC, "vatPct": 10, "assump": assump or {}}
    r = tender.bom_rollup(BOM, A)
    return t, tender.quotation(t, rollup=r), r


def _services(assump=None):
    t = {"costingType": tender.SERVICES, "vatPct": 10, "assump": assump or {}}
    r = tender.services_rollup(PKGS, A)
    return t, tender.quotation(t, rollup=r), r


# --- the invariant that makes a budget worth having -------------------------------------------

def test_trading_budget_reconciles_to_the_cost_base():
    t, q, m = _trading()
    b = tender.budget_lines(t, q, master=m)
    assert b["total"] == q["cogs"]


def test_epc_budget_reconciles_to_the_cost_base():
    t, q, r = _epc()
    b = tender.budget_lines(t, q, rollup=r)
    assert b["total"] == q["cogs"]


def test_services_budget_reconciles_to_the_cost_base():
    t, q, r = _services()
    b = tender.budget_lines(t, q, rollup=r)
    assert b["total"] == q["cogs"]


def test_project_fees_are_budgeted_and_still_reconcile():
    """PM, commissioning and contingency are delivery cost, so the job must be funded for them.
    They are also each separately controllable, so each is its own line."""
    fees = {"pmFeePct": 3, "commissioningPct": 2, "contingencyPct": 5}
    t, q, r = _epc(fees)
    b = tender.budget_lines(t, q, rollup=r)
    notes = " ".join(l["note"] for l in b["lines"])
    assert "Project management 3%" in notes
    assert "Testing & commissioning 2%" in notes
    assert "Contingency 5%" in notes
    expected = q["cogs"] + tender.project_fees(t, q["cogs"])["total"]
    assert abs(b["total"] - expected) <= len(b["lines"])


# --- what must NOT be handed over --------------------------------------------------------------

def test_profit_is_never_budgeted():
    """A project that spends its profit has not stayed within budget — it has consumed the reason
    the job was taken."""
    for build in (_trading, _epc, _services):
        t, q, x = build()
        b = tender.budget_lines(t, q, master=x if t["costingType"] == tender.TRADING else None,
                                rollup=None if t["costingType"] == tender.TRADING else x)
        assert b["total"] < q["net"], "%s budgeted the selling price" % t["costingType"]
        assert b["excludesProfit"] > 0


def test_recoverable_import_vat_is_not_budgeted():
    """It is a receivable from the state, not a cost of the job. Budgeting it would show the
    project overspending by the VAT on every import and then mysteriously recovering it."""
    t, q, m = _trading()
    b = tender.budget_lines(t, q, master=m)
    assert m["vatRecoverable"] > 0, "fixture has no recoverable VAT to exclude"
    assert b["total"] == q["cogs"]
    notes = " ".join(l["note"].lower() for l in b["lines"])
    assert "recoverable" not in notes
    assert b["excludesRecoverableVat"] == m["vatRecoverable"]


# --- each engine hands over its own control structure ------------------------------------------

def test_trading_splits_the_customs_chain_by_who_gets_paid():
    """One "landed cost" line would be a number nobody can chase. Goods go to the supplier,
    freight to the forwarder, duty to customs, clearance to the broker."""
    t, q, m = _trading()
    notes = [l["note"] for l in tender.budget_lines(t, q, master=m)["lines"]]
    for expect in ("Goods — EXW supplier price", "Freight, insurance and origin charges",
                   "Import duty", "Special consumption tax", "Customs clearance"):
        assert any(expect in n for n in notes), "missing %r" % expect


def test_trading_keeps_locally_bought_goods_separate_from_imports():
    t, q, m = _trading()
    lines = tender.budget_lines(t, q, master=m)["lines"]
    local = [l for l in lines if "Vietnam" in l["note"]]
    assert len(local) == 1 and local[0]["amount"] == 250_000_000


def test_epc_budgets_one_line_per_cost_centre():
    """Civil, MEP and the cleanroom are what the site reports against and what the schedule is
    built from."""
    t, q, r = _epc()
    lines = tender.budget_lines(t, q, rollup=r)["lines"]
    codes = [l["note"].split(" ")[0] for l in lines]
    assert "CIV" in codes and "MEP" in codes and "CLR" in codes


def test_services_budgets_labour_and_expenses_separately_per_package():
    """A package is what gets delivered, invoiced and argued about; and consultant time overruns
    for different reasons than travel does."""
    t, q, r = _services()
    lines = tender.budget_lines(t, q, rollup=r)["lines"]
    labour = [l for l in lines if l["category"] == "Labor"]
    expenses = [l for l in lines if "travel & expenses" in l["note"]]
    assert len(labour) == 2 and len(expenses) == 2
    assert "consultant days" in labour[0]["note"]


def test_a_cost_centre_the_client_declined_is_not_budgeted():
    """The configurator drops it from the quotation; budgeting it would fund work nobody is
    doing and then report an underspend for not doing it."""
    t = {"costingType": tender.EPC, "vatPct": 10, "assump": {}}
    bom = BOM + [{"costCentre": "OSD", "qty": 1, "unitCostUsd": 500000}]
    r = tender.bom_rollup(bom, A, {"OSD": {"include": False}})
    b = tender.budget_lines(t, tender.quotation(t, rollup=r), rollup=r)
    assert not any("OSD" in l["note"] for l in b["lines"])


# --- categories the project side already understands --------------------------------------------

def test_every_line_carries_a_category_the_project_budget_uses():
    """pm_costs groups by category. A category the project has never heard of lands in a bucket
    nobody looks at."""
    known = {"Material", "Labor", "Equipment", "Subcontract", "Overhead", "Logistics",
             "Duty & tax", "Other"}
    for build in (_trading, _epc, _services):
        t, q, x = build()
        b = tender.budget_lines(t, q, master=x if t["costingType"] == tender.TRADING else None,
                                rollup=None if t["costingType"] == tender.TRADING else x)
        for l in b["lines"]:
            assert l["category"] in known, "unknown category %r" % l["category"]


def test_a_line_excluded_from_the_quotation_is_not_budgeted():
    """If it is not being sold it is not being bought. Budgeting it would fund a purchase nobody
    is making and then report an underspend for not making it.

    This is the defect the full suite caught and a targeted run did not: the budget summed the
    cost master while the quote summed only what it sells, the two disagreed by the excluded
    line, and the reconciliation assert took the whole tender summary down with a 500.
    """
    t, _q, m = _trading()
    full = tender.budget_lines(t, tender.quotation(t, master=m), master=m)
    cut = tender.quotation(t, master=m, overrides=[{"srcId": "L1", "exclude": True}])
    less = tender.budget_lines(t, cut, master=m)
    assert less["total"] < full["total"], "the excluded line was budgeted anyway"
    assert less["total"] == cut["cogs"], "budget and quotation disagree about what the job carries"


def test_an_empty_tender_budgets_nothing_rather_than_raising():
    t = {"costingType": tender.EPC, "vatPct": 10, "assump": {}}
    r = tender.bom_rollup([], A)
    b = tender.budget_lines(t, tender.quotation(t, rollup=r), rollup=r)
    assert b["lines"] == [] and b["total"] == 0
