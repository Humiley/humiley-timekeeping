"""The AHU production route — the order of the steps, and the limits a reading is judged against.

The whole point of moving AHU-SOP-MASTER-001 out of a docx and into code is that code can refuse.
These tests pin down the two things that make it able to: that the route comes out in the order the
SOP lays down for each product family, and that a check with no reading — or with a limit nobody
can work out — never comes back as a pass.

Figures are the company's own (SOP sections 10.3 and 11.2, and the Design Standards) except the
EN 1886 class thresholds, which are the published ones. See the module docstring.
"""
import os

import pytest

import ahu_route as R


# ── the route, per family ────────────────────────────────────────────────────────────────────────

def test_every_family_builds_a_route():
    for fam in R.FAMILIES:
        assert R.build_route(fam), fam


def test_an_unknown_family_is_refused_rather_than_guessed():
    with pytest.raises(ValueError):
        R.build_route("centrifugal")


@pytest.mark.parametrize("fam", sorted(R.FAMILIES))
def test_every_predecessor_exists_and_comes_earlier(fam):
    """A step pointing at a predecessor that is not in the route can never start."""
    steps = R.build_route(fam)
    pos = {s["code"]: i for i, s in enumerate(steps)}
    for s in steps:
        for a in s.get("after") or []:
            assert a in pos, "%s: %s waits on %s, which is not in the route" % (fam, s["code"], a)
            assert pos[a] < pos[s["code"]], \
                "%s: %s waits on %s, which comes later" % (fam, s["code"], a)


@pytest.mark.parametrize("fam", sorted(R.FAMILIES))
def test_the_stages_come_out_in_order(fam):
    stages = [s["stage"] for s in R.build_route(fam)]
    assert stages == sorted(stages), "%s: the route is not in stage order" % fam


@pytest.mark.parametrize("fam", sorted(R.FAMILIES))
def test_each_gate_is_the_last_step_of_its_stage(fam):
    """A gate that is not last is a gate somebody can walk around."""
    steps = R.build_route(fam)
    for i, s in enumerate(steps):
        if s["kind"] != "gate":
            continue
        later_same_stage = [x for x in steps[i + 1:] if x["stage"] == s["stage"]]
        assert not later_same_stage, \
            "%s: %s is followed by %s in the same stage" % (fam, s["code"], later_same_stage[0]["code"])


def test_a_packaged_unit_has_no_section_joining_step_and_no_joint_inspection():
    """A packaged AHU is built as one piece: WS-07 joins sections it does not have, and IPQC-4
    inspects seals that do not exist. Both must drop out, and WS-08 must still have a predecessor."""
    codes = R.route_codes("packaged")
    assert "WS-07" not in codes
    assert "IPQC-4" not in codes
    ws08 = next(s for s in R.build_route("packaged") if s["code"] == "WS-08")
    assert ws08["after"] == ["WS-06"], ws08["after"]


def test_a_modular_unit_keeps_the_joining_step_and_its_inspection():
    codes = R.route_codes("modular")
    assert "WS-07" in codes and "IPQC-4" in codes


def test_only_a_hygienic_unit_is_particle_tested():
    assert "T13" in R.route_codes("hygienic")
    for fam in ("modular", "packaged", "outdoor"):
        assert "T13" not in R.route_codes(fam), fam


def test_only_an_outdoor_unit_gets_the_ingress_test():
    assert "T-IP" in R.route_codes("outdoor")
    for fam in ("modular", "packaged", "hygienic"):
        assert "T-IP" not in R.route_codes(fam), fam


def test_the_sound_test_is_left_out_unless_it_was_sold():
    assert "T12" not in R.route_codes("modular")
    assert "T12" in R.route_codes("modular", {"sound_test": True})


def test_the_first_workstation_waits_for_the_material_gate():
    """SOP section 5: no stage starts until the previous gate is signed. Without this a unit could
    be cut and framed against material nobody had confirmed was kitted."""
    ws01 = next(s for s in R.build_route("modular") if s["code"] == "WS-01")
    assert ws01["after"] == ["G3"]


def test_the_gates_are_chained_to_each_other():
    steps = {s["code"]: s for s in R.build_route("modular")}
    assert steps["G2"]["after"] == ["G1"]
    assert steps["G3"]["after"] == ["G2"]
    assert "G4" in steps["T1"]["after"]
    assert "G5" in steps["PK-01"]["after"]


def test_the_production_gate_waits_for_every_station_and_hold_point():
    steps = R.build_route("modular")
    g4 = next(s for s in steps if s["code"] == "G4")
    stage5 = {s["code"] for s in steps if s["stage"] == 5 and s["kind"] != "gate"}
    assert stage5 <= set(g4["after"])


def test_a_step_the_project_agreed_to_skip_drops_out():
    assert "T12" not in R.route_codes("modular", {"sound_test": True, "skip": ["T12"]})


def test_every_hold_point_names_the_operation_it_may_not_be_signed_by():
    """IPQC exists so somebody other than the builder looks at the work."""
    for s in R.build_route("modular"):
        if s["kind"] == "ipqc":
            assert s.get("witness_not"), s["code"]
            assert s["sign"] == "qaqc", s["code"]


def test_every_step_carries_the_document_that_governs_it():
    for fam in R.FAMILIES:
        for s in R.build_route(fam):
            assert s.get("forms") or s.get("wi") or s.get("doc") or s.get("std"), \
                "%s: %s has no governing document" % (fam, s["code"])


# ── limits that belong to the unit, not to the process ───────────────────────────────────────────

def test_the_foam_density_band_is_the_one_ipqc_2_actually_states():
    """The design figure and the acceptance band are different things.

    DS-MOD-001 says the panel is designed at 45 kg/m3 and says nothing about tolerance, so this
    module originally invented +/-10% — a band of 40.5 to 49.5 that passed panels at 41 and 49 which
    HML-AHU-IPQC-2-001 rejects. The procedure governing this hold point states 42-48 outright; the
    limit was in the document set the whole time.
    """
    step = next(s for s in R.build_route("modular") if s["code"] == "IPQC-2")
    chk = next(c for c in step["checks"] if c["key"] == "foam_density")
    assert (chk["limit"], chk["limit2"]) == (42.0, 48.0)
    assert "IPQC-2" in chk["src"]

    # The ends of the invented band must now be rejected, which is the whole point.
    assert R.evaluate_check(chk, 41.0)["status"] == R.FAIL
    assert R.evaluate_check(chk, 49.0)["status"] == R.FAIL
    assert R.evaluate_check(chk, 42.0)["status"] == R.PASS
    assert R.evaluate_check(chk, 48.0)["status"] == R.PASS
    assert R.evaluate_check(chk, 45.0)["status"] == R.PASS      # the design figure


def test_the_deflection_limit_comes_from_the_class_the_unit_was_sold_as():
    chk = {"key": "deflection", "op": "<=", "limit_from": "class_D"}
    assert R.resolve_limit(chk, {"classD": "D1"})[0] == 4.0
    assert R.resolve_limit(chk, {"classD": "D2"})[0] == 10.0


def test_a_unit_that_declared_no_class_cannot_be_judged_and_is_not_passed():
    """The dangerous failure: a missing declaration reading as a pass on a CE-facing document."""
    chk = {"key": "deflection", "op": "<=", "limit_from": "class_D"}
    limit, why = R.resolve_limit(chk, {})
    assert limit is None and "declared" in why
    out = R.evaluate_check(chk, 3.0, {})
    assert out["status"] == R.UNDETERMINABLE
    assert out["status"] != R.PASS


def test_the_leakage_limit_follows_the_l_class():
    chk = {"op": "<=", "limit_from": "class_L"}
    assert R.resolve_limit(chk, {"classL": "L1"})[0] == 0.15
    assert R.resolve_limit(chk, {"classL": "L2"})[0] == 0.44


def test_the_coil_test_pressure_is_the_greater_of_25_bar_and_one_and_a_half_times_design():
    chk = {"op": ">=", "limit_from": "coil_test_bar"}
    assert R.resolve_limit(chk, {"coilDesignBar": 10})[0] == 25.0      # 1.5 x 10 = 15, floor wins
    assert R.resolve_limit(chk, {"coilDesignBar": 20})[0] == 30.0      # 1.5 x 20 = 30, design wins


def test_the_coil_floor_still_applies_when_no_design_pressure_was_declared():
    """Unlike a class, this one CAN be answered without a declaration — the SOP states a floor."""
    limit, note = R.resolve_limit({"op": ">=", "limit_from": "coil_test_bar"}, {})
    assert limit == 25.0 and "floor" in note


def test_the_hipot_voltage_follows_the_supply_voltage():
    chk = {"op": ">=", "limit_from": "hipot_v"}
    assert R.resolve_limit(chk, {"voltage": 230})[0] == 1500.0
    assert R.resolve_limit(chk, {"voltage": 400})[0] == 2000.0
    assert R.resolve_limit(chk, {})[0] is None


def test_the_particle_limit_follows_the_cleanroom_class_and_declines_an_unknown_one():
    chk = {"op": "<=", "limit_from": "cleanroom"}
    assert R.resolve_limit(chk, {"cleanroom": "ISO 7"})[0] == 352000.0
    assert R.resolve_limit(chk, {"cleanroom": "ISO 3"})[0] is None


# ── judging a reading ────────────────────────────────────────────────────────────────────────────

def test_a_reading_inside_the_limit_passes_and_one_outside_fails():
    chk = {"key": "squareness", "op": "<=", "limit": 1.0, "unit": "mm/m"}
    assert R.evaluate_check(chk, 0.8)["status"] == R.PASS
    assert R.evaluate_check(chk, 1.4)["status"] == R.FAIL


def test_a_reading_exactly_on_the_limit_passes():
    """`<= 1.0` means 1.0 is acceptable. Off-by-one here rejects good units all day."""
    assert R.evaluate_check({"op": "<=", "limit": 1.0}, 1.0)["status"] == R.PASS
    assert R.evaluate_check({"op": ">=", "limit": 5.0}, 5.0)["status"] == R.PASS


def test_a_blank_reading_is_incomplete_and_never_a_pass():
    chk = {"op": "<=", "limit": 1.0}
    for blank in (None, "", "   "):
        assert R.evaluate_check(chk, blank)["status"] == R.INCOMPLETE


def test_an_unconfirmed_yes_no_check_is_blank_but_an_explicit_no_is_a_failure():
    chk = {"op": "yes"}
    assert R.evaluate_check(chk, None)["status"] == R.INCOMPLETE
    assert R.evaluate_check(chk, "yes")["status"] == R.PASS
    assert R.evaluate_check(chk, "no")["status"] == R.FAIL
    assert R.evaluate_check(chk, False)["status"] == R.FAIL


def test_a_range_check_takes_both_ends():
    chk = {"op": "range", "limit": -3.0, "limit2": 3.0}
    assert R.evaluate_check(chk, 0)["status"] == R.PASS
    assert R.evaluate_check(chk, 3.0)["status"] == R.PASS
    assert R.evaluate_check(chk, 3.1)["status"] == R.FAIL
    assert R.evaluate_check(chk, -3.1)["status"] == R.FAIL


def test_text_that_is_not_a_number_is_incomplete_rather_than_zero():
    """`float('n/a')` raising must not become a 0 that sails under a `<=` limit."""
    assert R.evaluate_check({"op": "<=", "limit": 1.0}, "n/a")["status"] == R.INCOMPLETE


def test_a_note_is_recorded_and_never_judged():
    assert R.evaluate_check({"op": "note"}, "shock indicator not required")["status"] == R.RECORDED


# ── judging a whole step ─────────────────────────────────────────────────────────────────────────

def _ipqc5():
    return next(s for s in R.build_route("modular") if s["code"] == "IPQC-5")


def test_a_step_passes_only_when_every_check_passes():
    step = _ipqc5()
    good = {"continuity": "yes", "megger_mohm": 500, "earth_ohm": 0.05, "polarity": "yes"}
    assert R.evaluate_step(step, good)["status"] == R.PASS


def test_one_failed_check_fails_the_step_even_when_others_are_still_blank():
    """A fail outranks a blank: 'we have not finished checking' must not hide 'this one failed'."""
    step = _ipqc5()
    out = R.evaluate_step(step, {"earth_ohm": 0.9})       # over limit; the rest untouched
    assert out["status"] == R.FAIL
    assert [f["key"] for f in out["failures"]] == ["earth_ohm"]


def test_a_half_filled_step_is_incomplete():
    out = R.evaluate_step(_ipqc5(), {"continuity": "yes"})
    assert out["status"] == R.INCOMPLETE
    assert len(out["open"]) == 3


def test_a_step_with_no_checks_passes_on_its_checks_alone():
    """Whether it may be SIGNED is a separate question — predecessors and authority live in app.py."""
    gate = next(s for s in R.build_route("modular") if s["code"] == "G1")
    assert R.evaluate_step(gate, {})["status"] == R.PASS


def test_an_undeterminable_check_holds_the_step_open_rather_than_passing_it():
    step = next(s for s in R.build_route("modular") if s["code"] == "T2")
    out = R.evaluate_step(step, {"deflection": 2.0}, {})        # no D class declared
    assert out["status"] == R.UNDETERMINABLE


# ── progress and what can start next ─────────────────────────────────────────────────────────────

def test_progress_is_zero_at_the_start_and_a_hundred_when_everything_is_signed():
    steps = R.build_route("modular")
    assert R.route_progress(steps, []) == 0.0
    assert R.route_progress(steps, [s["code"] for s in steps]) == 100.0


def test_a_gate_is_worth_more_than_a_single_operation():
    """Nine stations signed and no gate passed is not 'nearly finished'."""
    steps = R.build_route("modular")
    ops_only = R.route_progress(steps, [s["code"] for s in steps if s["kind"] == "op"])
    assert ops_only < 50.0


def test_only_the_first_gate_can_start_on_a_brand_new_unit():
    steps = R.build_route("modular")
    assert [s["code"] for s in R.next_steps(steps, [])] == ["G1"]


def test_a_station_opens_up_once_its_predecessor_is_signed():
    steps = R.build_route("modular")
    ready = {s["code"] for s in R.next_steps(steps, ["G1", "G2", "G3"])}
    assert "WS-01" in ready
    assert "WS-02" not in ready


def test_blocked_by_names_what_is_actually_missing():
    steps = R.build_route("modular")
    ws02 = next(s for s in steps if s["code"] == "WS-02")
    assert R.blocked_by(ws02, ["G1", "G2", "G3"]) == ["WS-01"]
    assert R.blocked_by(ws02, ["WS-01"]) == []


# ── the standard the factory tests against is the standard the unit was sold against ─────────────

AEROSELECT_STANDARDS = os.path.expanduser(
    "~/Library/CloudStorage/OneDrive-Humiley(2)/Claude Projects/HML-AHU Selection Web App/"
    "packages/calculations/src/standards.ts")


@pytest.mark.skipif(not os.path.exists(AEROSELECT_STANDARDS),
                    reason="AeroSelect checkout not present next to this repo")
def test_en1886_thresholds_match_aeroselect():
    """AeroSelect classifies the unit at selection; this module judges it at test. If the two tables
    drift, a unit is sold as L2 and rejected as L2 — or worse, the other way round."""
    import re
    src = open(AEROSELECT_STANDARDS, encoding="utf-8").read()

    def table(block):
        m = re.search(block + r"\s*:\s*\[(.*?)\]", src, re.S)
        assert m, "could not find %s in AeroSelect standards.ts" % block
        out = {}
        for cls, val in re.findall(r"cls:\s*'([^']+)'\s*,\s*(?:max|min):\s*([\w.]+)", m.group(1)):
            out[cls] = float("inf") if val == "Infinity" else float(val)
        return out

    assert table("strength") == R.EN1886_STRENGTH
    assert table("leakage_neg400") == R.EN1886_LEAK_NEG400
    assert table("leakage_pos700") == R.EN1886_LEAK_POS700
    assert table("thermal_U") == R.EN1886_THERMAL_U
    assert table("bridging_kb") == R.EN1886_BRIDGING


def test_the_sop_discrepancy_is_recorded_rather_than_silently_resolved():
    """SOP section 11.2 puts 4 mm/m at D2; EN 1886 puts it at D1. The published figure is applied,
    and the difference is written down so it gets fixed rather than forgotten."""
    assert R.EN1886_STRENGTH["D1"] == 4.0
    assert R.EN1886_STRENGTH["D2"] == 10.0
    assert any("11.2" in d["where"] for d in R.SOP_DISCREPANCIES)
