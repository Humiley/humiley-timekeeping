"""Where the labour goes — and the two numbers this must never conflate.

The arithmetic here is easy. What is not easy, and what these tests exist for, is keeping "hands-on
time" and "time since the last sign-off" apart, and keeping "the route declares this serial" apart
from "this cannot be done in parallel". Both pairs look interchangeable and are not, and reporting
either as the other would put a confident wrong number in front of a costing decision.
"""
import ahu_labour as L
import ahu_route as R


SPECS = R.build_route("modular", {})


# ── where a run sits in its own band ─────────────────────────────────────────────────────────────

def test_a_run_past_the_slow_end_is_over():
    p = L.band_position("1 - 4 h / section", 20.0, sections=4)      # band is 4–16 h
    assert p["status"] == L.OVER and p["lo"] == 4.0 and p["hi"] == 16.0


def test_a_run_at_the_quick_end_is_fast():
    assert L.band_position("1 - 4 h / section", 4.0, sections=4)["status"] == L.FAST
    assert L.band_position("1 - 4 h / section", 3.0, sections=4)["status"] == L.FAST


def test_the_top_quarter_of_the_band_reads_as_slow():
    """Inside the band but nearly out of it. Calling that MID hides the station about to tip over."""
    assert L.band_position("1 - 4 h / section", 14.0, sections=4)["status"] == L.SLOW
    assert L.band_position("1 - 4 h / section", 8.0, sections=4)["status"] == L.MID


def test_the_band_scales_with_the_section_count():
    one = L.band_position("1 - 4 h / section", 5.0, sections=1)
    four = L.band_position("1 - 4 h / section", 5.0, sections=4)
    assert one["status"] == L.OVER and four["status"] == L.MID


def test_a_per_section_band_with_no_section_count_is_unknown_not_assumed():
    """THE refusal. Assuming one section would make a five-section unit look five times worse than
    it is, and every per-section station would read OVER on a unit nobody had sized."""
    p = L.band_position("1 - 4 h / section", 12.0, sections=None)
    assert p["status"] == L.UNKNOWN and "per section" in p["why"]


def test_a_step_with_no_band_or_no_measurement_is_unknown():
    assert L.band_position("", 5.0)["status"] == L.UNKNOWN
    assert L.band_position("30 min / AHU", None)["status"] == L.UNKNOWN


def test_the_ratio_is_against_the_slow_end():
    p = L.band_position("1 - 4 h / section", 4.0, sections=4)
    assert p["ratio"] == 0.25          # running at the quick end of a 4x band


# ── touch time ───────────────────────────────────────────────────────────────────────────────────

def test_touch_time_needs_a_start_and_says_nothing_without_one():
    """None, never 0.0. A step nobody started and a step that took no time are different facts, and
    zero for both would hide the first exactly where it matters."""
    assert L.touch_hours({"signatures": [{"ts": "2026-08-21T17:00:00Z"}]}) is None
    assert L.touch_hours({}) is None


def test_touch_time_is_the_gap_between_starting_and_signing():
    s = {"startedAt": "2026-08-21T08:00:00", "signatures": [{"ts": "2026-08-21T11:30:00Z"}]}
    assert L.touch_hours(s) == 3.5


def test_a_signature_before_the_start_is_refused_rather_than_negative():
    s = {"startedAt": "2026-08-21T12:00:00", "signatures": [{"ts": "2026-08-21T09:00:00Z"}]}
    assert L.touch_hours(s) is None


def test_an_unparseable_stamp_does_not_raise_or_guess():
    assert L.touch_hours({"startedAt": "this morning",
                          "signatures": [{"ts": "2026-08-21T11:00:00Z"}]}) is None


# ── per station, across units ────────────────────────────────────────────────────────────────────

def _row(code, hours, sections=4, tact="1 - 4 h / section", source="elapsed", pin="P"):
    return {"code": code, "tact": tact, "hours": hours, "sections": sections,
            "unitId": "u", "pin": pin, "source": source}


def test_a_station_reports_how_often_it_runs_over():
    rows = [_row("WS-04", 20.0), _row("WS-04", 8.0), _row("WS-04", 18.0)]
    g = L.station_performance(rows)[0]
    assert g["n"] == 3 and g["over"] == 2


def test_the_worst_run_is_named_so_somebody_can_go_and_look():
    rows = [_row("WS-04", 20.0, pin="PIN-A"), _row("WS-04", 40.0, pin="PIN-B")]
    g = L.station_performance(rows)[0]
    assert g["worst"]["pin"] == "PIN-B" and g["worst"]["hours"] == 40.0


def test_a_station_judged_on_nothing_says_so_rather_than_looking_fine():
    """A blank cell reads as healthy. This is the station whose every run was unmeasurable."""
    rows = [_row("WS-04", 12.0, sections=None)]
    g = L.station_performance(rows)[0]
    assert g["judged"] == 0 and g["median"] is None and "Not enough" in g["note"]


def test_touch_and_elapsed_measurements_are_not_silently_averaged():
    """A station measured both ways would otherwise produce a number that is neither."""
    rows = [_row("WS-04", 8.0, source="touch"), _row("WS-04", 30.0, source="elapsed")]
    g = L.station_performance(rows)[0]
    assert g["sources"] == ["elapsed", "touch"]


def test_stations_are_ordered_worst_first():
    rows = [_row("WS-01", 2.0, tact="1 - 4 h / section"), _row("WS-04", 15.0)]
    assert L.station_performance(rows)[0]["code"] == "WS-04"


def test_the_recorded_delay_reasons_come_back_commonest_first():
    steps = [{"delayReason": "Waiting for material or a part"},
             {"delayReason": "Rework on this unit"},
             {"delayReason": "Waiting for material or a part"},
             {"delayReason": ""}]
    out = L.delay_causes(steps)
    assert out[0]["reason"] == "Waiting for material or a part" and out[0]["count"] == 2
    assert len(out) == 2


# ── the shape of the route ───────────────────────────────────────────────────────────────────────

def test_a_strictly_serial_route_has_a_critical_path_equal_to_its_total():
    """The finding worth surfacing: stage 5 is a straight chain, so one unit consumes the whole
    49 hours end to end however many people are on it."""
    cp = L.critical_path(SPECS, 4)
    assert cp["criticalPathH"] == cp["totalWorkH"]
    assert cp["serialShare"] == 100


def test_lifting_a_dependency_prices_the_parallel_option():
    p = L.parallel_floor(SPECS, 4, independent=["WS-08"])
    assert p["savedH"] > 0
    assert p["before"] > p["after"]


def test_the_parallel_figure_is_labelled_as_a_question():
    """It is not a claim that a control panel can be built alongside the casing — this module has no
    way to know that. It prices the answer so the conversation starts from a number."""
    p = L.parallel_floor(SPECS, 4, independent=["WS-08"])
    assert "question for the production lead" in p["caveat"]


def test_lifting_nothing_changes_nothing():
    p = L.parallel_floor(SPECS, 4, independent=[])
    assert p["savedH"] == 0


def test_a_route_with_a_dependency_cycle_terminates_rather_than_recursing_forever():
    cyc = [{"code": "A", "after": ["B"], "tact": "1 h / AHU"},
           {"code": "B", "after": ["A"], "tact": "1 h / AHU"}]
    assert L.critical_path(cyc, 1)["totalWorkH"] == 2.0


# ── what a unit costs ────────────────────────────────────────────────────────────────────────────

def test_fixed_labour_does_not_move_with_the_section_count():
    a = L.fixed_vs_variable(SPECS, 1)
    b = L.fixed_vs_variable(SPECS, 12)
    assert a["fixedH"] == b["fixedH"]
    assert b["variableH"] > a["variableH"]


def test_a_small_unit_carries_a_far_larger_share_of_fixed_labour():
    """Why pricing per unit rather than per section loses money on small orders."""
    assert L.fixed_vs_variable(SPECS, 1)["fixedPct"] > 50
    assert L.fixed_vs_variable(SPECS, 12)["fixedPct"] < 20


def test_the_spread_is_the_gap_between_the_two_ends_of_the_sop_bands():
    s = L.spread(SPECS, 4)
    assert s["worstH"] > s["bestH"]
    assert s["spreadPct"] >= 50, "the SOP's own bands are wide; if this drops, the bands changed"


def test_the_spread_names_the_stations_that_cost_the_most_worst_first():
    s = L.spread(SPECS, 4)
    assert s["stations"][0]["code"] == "WS-04"
    assert s["stations"][0]["costH"] == max(x["costH"] for x in s["stations"])


def test_nothing_here_raises_on_empty_input():
    assert L.station_performance(None) == []
    assert L.delay_causes(None) == []
    assert L.critical_path([], 4)["totalWorkH"] == 0.0
    assert L.spread([], 4)["stations"] == []
