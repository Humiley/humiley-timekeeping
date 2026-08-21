"""Capacity, load and elapsed time — reading the tact times the route already carried.

SOP section 6.7 names the rolling 8-week load chart as the control against promising a delivery
date the floor cannot meet. These tests pin the two things that make such a chart trustworthy: that
it books the PESSIMISTIC end of every tact band, and that it refuses to guess a section count rather
than quietly understating the floor's commitment.
"""
import ahu_capacity as C


# ── parsing the SOP's tact strings ───────────────────────────────────────────────────────────────

def test_a_range_in_minutes_becomes_hours():
    t = C.parse_tact("20 - 60 min / panel set")
    assert (t["lo"], t["hi"], t["per"]) == (round(20 / 60, 3), 1.0, "panel set")


def test_a_range_in_hours_stays_hours():
    t = C.parse_tact("1 - 4 h / section")
    assert (t["lo"], t["hi"], t["per"]) == (1.0, 4.0, "section")


def test_a_single_figure_per_ahu():
    t = C.parse_tact("30 min / AHU")
    assert (t["lo"], t["hi"], t["per"]) == (0.5, 0.5, "ahu")


def test_the_two_material_form_books_the_slower_material():
    """'30 min cure (PU) / 15 min (rockwool)' — the slash separates MATERIALS, not a unit of work.
    Booking the faster one would under-book the floor."""
    t = C.parse_tact("30 min cure (PU) / 15 min (rockwool)")
    assert t["hi"] == 0.5
    assert t["per"] is None


def test_an_unparseable_tact_returns_nothing_rather_than_zero():
    assert C.parse_tact("as required") is None
    assert C.parse_tact("") is None
    assert C.parse_tact(None) is None


# ── hours for one unit ───────────────────────────────────────────────────────────────────────────

def test_a_unit_with_no_section_count_reports_the_per_section_stations_as_unknown():
    """The failure that matters. Assuming one section understates a five-section unit's frame and
    assembly time by a factor of five, and understating capacity is how the date gets promised."""
    h = C.unit_hours({"family": "modular"})
    assert h["unknown"], "per-section stations must be reported, not defaulted"
    assert any("section count" in v for v in h["unknown"].values())
    # WS-08 and WS-09 are quoted per AHU, so they are still known.
    assert "WS-08" in h["stations"] and "WS-09" in h["stations"]


def test_a_unit_with_a_section_count_multiplies_the_per_section_stations():
    one = C.unit_hours({"family": "modular", "sectionCount": 1})
    five = C.unit_hours({"family": "modular", "sectionCount": 5})
    assert not one["unknown"] and not five["unknown"]
    # WS-02 is 30-90 min per section: 1.5 h at one section, 7.5 h at five.
    assert one["stations"]["WS-02"] == 1.5
    assert five["stations"]["WS-02"] == 7.5
    assert five["total"] > one["total"]


def test_the_upper_end_of_the_band_is_booked():
    """A capacity chart answers 'can we take this on'. Answering from the optimistic end of every
    band is how a plan becomes a promise nobody keeps."""
    h = C.unit_hours({"family": "modular", "sectionCount": 1})
    assert h["stations"]["WS-07"] == 8.0          # "3 - 8 h / AHU"


def test_signed_stations_drop_out_of_the_remaining_load():
    steps = [{"code": "WS-01", "status": "Complete"}, {"code": "WS-02", "status": "Complete"}]
    full = C.unit_hours({"family": "modular", "sectionCount": 2})
    left = C.unit_hours({"family": "modular", "sectionCount": 2}, steps)
    assert "WS-02" not in left["stations"]
    assert left["total"] < full["total"]


def test_a_unit_whose_family_cannot_be_built_reports_it_rather_than_raising():
    h = C.unit_hours({"family": "kappa"})
    assert h["total"] == 0.0 and "route" in h["unknown"]


# ── the rolling chart ────────────────────────────────────────────────────────────────────────────

def _u(pin, due, sections=3, steps=None):
    return {"unit": {"pin": pin, "family": "modular", "sectionCount": sections},
            "steps": steps or [], "order": {"deliveryDate": due}}


def test_the_chart_covers_the_requested_horizon_starting_on_a_monday():
    c = C.load_by_week([], today="2026-08-21", weeks=8)
    assert len(c["weeks"]) == 8
    assert c["weeks"][0]["week"] == "2026-08-17"      # the Monday of that week


def test_work_is_spread_across_the_weeks_up_to_the_delivery_date():
    c = C.load_by_week([_u("P1", "2026-09-11")], today="2026-08-21", weeks=8)
    loaded = [w for w in c["weeks"] if w["hours"] > 0]
    assert len(loaded) == 4                            # 17 Aug through 7 Sep inclusive
    assert abs(sum(w["hours"] for w in loaded) - C.unit_hours(
        {"family": "modular", "sectionCount": 3})["total"]) < 0.2


def test_an_overdue_unit_is_named_rather_than_smeared_across_the_horizon():
    c = C.load_by_week([_u("P-LATE", "2026-08-01")], today="2026-08-21")
    assert c["overdue"][0]["pin"] == "P-LATE"
    assert all(w["hours"] == 0 for w in c["weeks"])


def test_a_unit_with_no_delivery_date_is_listed_separately():
    c = C.load_by_week([_u("P-NODATE", None)], today="2026-08-21")
    assert c["undated"][0]["pin"] == "P-NODATE"


def test_units_whose_hours_cannot_be_known_are_surfaced_on_the_chart():
    u = _u("P-NOSECT", "2026-09-11", sections=None)
    c = C.load_by_week([u], today="2026-08-21")
    assert "P-NOSECT" in c["unknown"]


def test_without_a_configured_capacity_the_chart_gives_hours_and_no_verdict():
    """A chart drawn against an invented capacity looks exactly like one drawn against a real
    capacity, and the whole point is to support a commitment."""
    c = C.against_capacity(C.load_by_week([], today="2026-08-21"), None)
    assert c["capacity"] is None and "No weekly capacity" in c["note"]
    assert "over" not in c["weeks"][0]


def test_with_a_capacity_each_week_is_marked_over_or_under():
    c = C.load_by_week([_u("P1", "2026-08-28", sections=8)], today="2026-08-21")
    c = C.against_capacity(c, 10.0)
    assert c["weeks"][0]["over"] is True
    assert c["weeks"][0]["utilisation"] > 100
    assert c["weeks"][7]["over"] is False


# ── elapsed between sign-offs ────────────────────────────────────────────────────────────────────

def _sig(ts):
    return [{"name": "Op", "ts": ts}]


def test_elapsed_is_measured_between_consecutive_signoffs():
    steps = [
        {"code": "WS-01", "seq": 1, "kind": "op", "tact": "20 - 60 min / panel set",
         "signatures": _sig("2026-08-21T08:00:00Z")},
        {"code": "WS-02", "seq": 2, "kind": "op", "tact": "30 - 90 min / section",
         "signatures": _sig("2026-08-21T11:00:00Z")},
    ]
    out = C.elapsed_between_signoffs({"sectionCount": 1}, steps)
    assert out[0]["code"] == "WS-02" and out[0]["elapsedH"] == 3.0


def test_a_step_over_its_tact_band_is_flagged():
    steps = [
        {"code": "WS-01", "seq": 1, "kind": "op", "tact": "30 min / AHU",
         "signatures": _sig("2026-08-21T08:00:00Z")},
        {"code": "WS-09", "seq": 2, "kind": "op", "tact": "30 min / AHU",
         "signatures": _sig("2026-08-21T14:00:00Z")},
    ]
    out = C.elapsed_between_signoffs({}, steps)
    assert out[0]["overTact"] is True                  # 6 h against a 0.5 h tact


def test_a_per_section_tact_with_no_section_count_says_so_rather_than_flagging():
    steps = [
        {"code": "WS-01", "seq": 1, "kind": "op", "tact": "30 min / AHU",
         "signatures": _sig("2026-08-21T08:00:00Z")},
        {"code": "WS-02", "seq": 2, "kind": "op", "tact": "30 - 90 min / section",
         "signatures": _sig("2026-08-21T09:00:00Z")},
    ]
    out = C.elapsed_between_signoffs({}, steps)
    assert out[0]["tactHiH"] is None
    assert "section count" in out[0]["note"]


def test_an_unsigned_step_contributes_nothing():
    steps = [{"code": "WS-01", "seq": 1, "kind": "op", "tact": "30 min / AHU", "signatures": []}]
    assert C.elapsed_between_signoffs({}, steps) == []


def test_the_measure_is_named_honestly():
    """It includes queueing and overnight. Calling it a cycle time would be a lie about the number."""
    assert "SIGNED" in C.cycle_note() and "STARTED" in C.cycle_note()
