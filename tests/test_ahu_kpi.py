"""The SOP's own KPIs, computed from signed production data.

Two things these pin down.

The class ACHIEVED is not the same question as pass/fail. A casing sold as L1 and measured at 0.30
fails its contract and achieves L2 — the unit is a warranty problem and the line is performing to
L2, and a pass/fail figure answers neither. The KPI asks which class was achieved, so the reading is
classified rather than judged.

And three of the eight cannot be computed at all. They must say so, loudly, rather than report a
flattering zero for something nothing measures — which would make the dashboard the exact defect the
rest of this module exists to prevent.
"""
import ahu_kpi as K
import ahu_route as R


def unit(pin="PIN-1", **over):
    u = {"unit": {"pin": pin, "classD": "D2", "classL": "L2"}, "steps": [], "ncr": [],
         "dispatch": [], "order": {}}
    u.update(over)
    return u


def step(code, status="Passed", kind="test", **readings):
    return {"code": code, "status": status, "kind": kind, "readings": readings}


def g4(status="Passed"):
    return {"code": "G4", "status": status, "kind": "gate"}


# ── classifying a measurement ────────────────────────────────────────────────────────────────────

def test_a_leakage_reading_is_classified_into_the_class_it_achieves():
    assert K.classify(0.10, R.EN1886_LEAK_NEG400) == "L1"
    assert K.classify(0.15, R.EN1886_LEAK_NEG400) == "L1"      # exactly on the threshold
    assert K.classify(0.30, R.EN1886_LEAK_NEG400) == "L2"
    assert K.classify(1.00, R.EN1886_LEAK_NEG400) == "L3"


def test_a_reading_worse_than_every_class_achieves_none_rather_than_the_worst():
    """Reporting a 5.0 l/(s.m2) casing as L3 would flatter it. It achieved no class."""
    assert K.classify(5.0, R.EN1886_LEAK_NEG400) is None


def test_a_deflection_reading_is_classified_too():
    assert K.classify(3.0, R.EN1886_STRENGTH) == "D1"
    assert K.classify(8.0, R.EN1886_STRENGTH) == "D2"


def test_no_reading_classifies_to_nothing():
    assert K.classify(None, R.EN1886_STRENGTH) is None
    assert K.classify("n/a", R.EN1886_STRENGTH) is None


def test_meets_or_better_understands_that_l1_beats_l2():
    t = R.EN1886_LEAK_NEG400
    assert K.meets_or_better("L1", "L2", t) is True
    assert K.meets_or_better("L2", "L2", t) is True
    assert K.meets_or_better("L3", "L2", t) is False
    assert K.meets_or_better(None, "L2", t) is None


# ── the class-achieved KPI ───────────────────────────────────────────────────────────────────────

def test_the_class_achieved_is_reported_even_when_the_unit_failed_its_own_target():
    """The commercially important case, and the reason this is not a pass/fail count."""
    u = unit()
    u["unit"]["classL"] = "L1"
    u["steps"] = [step("T3", leak_neg400=0.30)]
    out = K.casing_class_achieved([u])
    assert out["L"]["classes"] == {"L2": 1}       # achieved L2
    assert out["L"]["meets_target"] == 0          # and missed the L1 it was sold as


def test_an_unsigned_reading_does_not_count():
    """An unsigned reading is a number somebody typed, not a result."""
    u = unit()
    u["steps"] = [step("T3", status="Pending", leak_neg400=0.10)]
    assert K.casing_class_achieved([u])["L"]["n"] == 0


def test_a_unit_meeting_its_target_is_counted_as_meeting_it():
    u = unit()
    u["steps"] = [step("T2", deflection=3.0), step("T3", leak_neg400=0.40)]
    out = K.casing_class_achieved([u])
    assert out["D"]["meets_target"] == 1          # D1 achieved against a D2 target
    assert out["L"]["meets_target"] == 1          # L2 achieved against a L2 target


# ── First-Pass Yield ─────────────────────────────────────────────────────────────────────────────

def test_fpy_counts_only_units_that_have_reached_qc():
    """A unit still in production has not had the chance to pass or fail."""
    assert K.first_pass_yield([unit()])["n"] == 0
    assert K.first_pass_yield([unit(steps=[g4()])])["n"] == 1


def test_a_clean_unit_is_first_pass():
    out = K.first_pass_yield([unit(steps=[g4(), step("T3", leak_neg400=0.1)])])
    assert (out["n"], out["passed"], out["pct"]) == (1, 1, 100.0)


def test_a_failed_hold_point_costs_first_pass_yield():
    u = unit(steps=[g4(), step("IPQC-1", status="Failed", kind="ipqc")])
    out = K.first_pass_yield([u])
    assert (out["n"], out["passed"]) == (1, 0)


def test_rework_costs_first_pass_yield_even_when_every_step_ended_up_signed():
    """The definition is 'without rework' — a unit reworked into compliance is not first-pass."""
    u = unit(steps=[g4()], ncr=[{"disposition": "Rework", "status": "Closed"}])
    assert K.first_pass_yield([u])["passed"] == 0


def test_a_use_as_is_disposition_does_not_count_as_rework():
    u = unit(steps=[g4()], ncr=[{"disposition": "Use as is", "status": "Closed"}])
    assert K.first_pass_yield([u])["passed"] == 1


def test_fpy_is_none_rather_than_zero_when_nothing_has_reached_qc():
    """0% would read as catastrophic; None reads as 'no data', which is the truth."""
    assert K.first_pass_yield([unit()])["pct"] is None


# ── On-Time Delivery ─────────────────────────────────────────────────────────────────────────────

def test_a_unit_shipped_before_its_due_date_is_on_time():
    u = unit(order={"deliveryDate": "2026-09-30"},
             dispatch=[{"dispatchedOn": "2026-09-28"}])
    out = K.on_time_delivery([u])
    assert (out["n"], out["onTime"], out["pct"]) == (1, 1, 100.0)


def test_shipping_exactly_on_the_due_date_is_on_time():
    u = unit(order={"deliveryDate": "2026-09-30"}, dispatch=[{"dispatchedOn": "2026-09-30"}])
    assert K.on_time_delivery([u])["onTime"] == 1


def test_a_late_unit_is_named_not_just_counted():
    u = unit(pin="PIN-LATE", order={"deliveryDate": "2026-09-30"},
             dispatch=[{"dispatchedOn": "2026-10-05"}])
    out = K.on_time_delivery([u])
    assert out["onTime"] == 0
    assert out["late"][0]["pin"] == "PIN-LATE"


def test_an_unshipped_unit_is_not_counted_as_late():
    """Counting work in progress as late would report a figure about the future."""
    u = unit(order={"deliveryDate": "2020-01-01"})
    assert K.on_time_delivery([u])["n"] == 0


# ── the three that cannot be computed ────────────────────────────────────────────────────────────

def test_the_kpis_nothing_measures_say_so_instead_of_reporting_zero():
    """The worst possible version of this dashboard would show 100% for a class nobody tests."""
    s = K.summary([])
    unmeasured = {k["kpi"]: k for k in s["kpis"] if k.get("status") == K.NOT_MEASURED}
    assert "Thermal Bridging Class" in unmeasured
    assert "Thermal Transmittance" in unmeasured
    assert "Customer Complaints" in unmeasured
    for k in unmeasured.values():
        assert k["why"], "a NOT_MEASURED KPI must say why"
        assert "pct" not in k and "met" not in k


def test_every_sop_kpi_is_present_and_carries_its_target_and_owner():
    s = K.summary([])
    assert len(s["kpis"]) == 8
    for k in s["kpis"]:
        assert k["kpi"] and k["target"] and k["owner"]


def test_the_unmeasured_ones_are_excluded_from_the_roll_up():
    s = K.summary([])
    assert s["computed"] + s["notMeasured"] == len(s["kpis"])
    assert s["notMeasured"] >= 3


def test_ltir_is_computed_when_the_exposure_hours_are_supplied():
    s = K.summary([], incidents=[{"severity": "Lost time"}], worked_hours=500_000)
    ltir = next(k for k in s["kpis"] if "Lost-Time" in k["kpi"])
    assert ltir["value"] == 2.0                       # 1 incident per 500k hours
    assert ltir["met"] is False


def test_ltir_without_exposure_hours_refuses_rather_than_showing_a_count():
    s = K.summary([], incidents=[{"severity": "Lost time"}])
    ltir = next(k for k in s["kpis"] if "Lost-Time" in k["kpi"])
    assert ltir["status"] == K.NOT_MEASURED
    assert "worked-hours" in ltir["why"]


def test_there_is_no_single_invented_overall_score():
    """Averaging three unrelated ratios would produce a number the SOP does not define."""
    s = K.summary([])
    assert "score" not in s and "overall" not in s
