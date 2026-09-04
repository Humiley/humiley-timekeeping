"""Labour cost per project: the money must reconcile, and every number must say where it came from.

Two failure modes matter more than any arithmetic detail. The first is losing money to rounding when
one person's month is split across projects — invisible per payslip, material across a year. The
second is presenting an estimate as a fact: a contractor pricing the next tender off an allocation
percentage they believed was a timesheet is worse off than one with no number at all.
"""
import labour_cost as lc


# ── the split must not lose or invent money ──────────────────────────────────────────────────────

def test_a_three_way_split_of_an_awkward_number_still_sums_to_the_whole():
    """100 / 3 in integer dong is where naive rounding quietly drops a unit every month."""
    out = lc.apportion(100, {"A": 1, "B": 1, "C": 1})
    assert sum(out.values()) == 100
    assert sorted(out.values()) == [33, 33, 34]


def test_it_reconciles_across_a_spread_of_totals_and_weights():
    for total in (1, 7, 99, 100, 12_345_678, 20_000_001):
        for weights in ({"A": 1, "B": 2}, {"A": 1, "B": 1, "C": 1},
                        {"A": 0.1, "B": 0.2, "C": 0.7}, {"A": 3, "B": 3, "C": 3, "D": 1}):
            out = lc.apportion(total, weights)
            assert sum(out.values()) == total, (total, weights, out)


def test_the_leftover_goes_to_whoever_the_flooring_robbed_most():
    out = lc.apportion(10, {"A": 1, "B": 1, "C": 8})
    assert out == {"A": 1, "B": 1, "C": 8}
    out = lc.apportion(7, {"big": 6, "small": 1})
    assert sum(out.values()) == 7 and out["big"] == 6


def test_the_split_is_the_same_every_time_it_is_run():
    """Ties broken by key, not by dict ordering — a report that moves ₫1 between projects on each
    refresh destroys confidence in all of it."""
    w = {"P3": 1, "P1": 1, "P2": 1}
    assert lc.apportion(100, w) == lc.apportion(100, dict(reversed(list(w.items()))))


def test_nothing_to_split_across_is_not_a_crash():
    assert lc.apportion(500, {}) == {}
    assert lc.apportion(500, {"A": 0, "B": 0}) == {}
    assert lc.apportion(0, {"A": 1}) == {"A": 0}


# ── a fact always beats an estimate ──────────────────────────────────────────────────────────────

def _days(*projects):
    return [{"date": "2026-08-%02d" % (i + 1), "project": p} for i, p in enumerate(projects)]


def test_recorded_days_win_outright_over_the_allocation():
    """They were on site at the cleanroom job all month. The register still says they are half on
    something else. The register is not what happened."""
    out = lc.split_person(10_000_000, days=_days("CLEANROOM", "CLEANROOM"),
                          allocations=[{"projectId": "OTHER", "allocationPct": 50}])
    assert out["lines"] == {"CLEANROOM": 10_000_000}
    assert out["basis"]["CLEANROOM"] == lc.RECORDED


def test_with_no_attendance_at_all_the_allocation_is_used_and_labelled_as_such():
    out = lc.split_person(9_000_000, days=[],
                          allocations=[{"projectId": "A", "allocationPct": 60},
                                       {"projectId": "B", "allocationPct": 40}])
    assert out["lines"] == {"A": 5_400_000, "B": 3_600_000}
    assert set(out["basis"].values()) == {lc.ALLOCATED}


def test_days_recorded_against_no_project_are_not_folded_into_the_ones_that_were():
    """The trap: 2 days on the cleanroom job and 18 days unrecorded must not report a month of
    cleanroom labour. That is the number somebody prices the next tender from."""
    out = lc.split_person(2_000_000, days=_days("CLEANROOM", "CLEANROOM", *[""] * 18))
    assert out["lines"]["CLEANROOM"] == 200_000, "2 of 20 days, not the whole month"
    assert out["lines"][lc.UNASSIGNED] == 1_800_000
    assert sum(out["lines"].values()) == 2_000_000


def test_the_unrecorded_remainder_falls_back_to_the_allocation_when_there_is_one():
    out = lc.split_person(2_000_000, days=_days("CLEANROOM", *[""] * 9),
                          allocations=[{"projectId": "OFFICE", "allocationPct": 100}])
    assert out["lines"]["CLEANROOM"] == 200_000
    assert out["lines"]["OFFICE"] == 1_800_000
    assert out["basis"]["CLEANROOM"] == lc.RECORDED
    assert out["basis"]["OFFICE"] == lc.ALLOCATED


def test_a_project_fed_by_both_a_fact_and_an_estimate_is_reported_as_an_estimate():
    """Half of it is real and half is guessed; a reader told "recorded" would over-trust it."""
    out = lc.split_person(1_000_000, days=_days("A", *[""] * 9),
                          allocations=[{"projectId": "A", "allocationPct": 100}])
    assert out["lines"]["A"] == 1_000_000
    assert out["basis"]["A"] == lc.ALLOCATED


def test_being_named_on_a_project_with_no_percentage_means_on_it_not_on_it_for_nothing():
    out = lc.split_person(1_000_000, days=[],
                          allocations=[{"projectId": "A"}, {"projectId": "B"}])
    assert out["lines"] == {"A": 500_000, "B": 500_000}


def test_somebody_with_neither_days_nor_an_allocation_is_visibly_unattributed():
    out = lc.split_person(5_000_000, days=[], allocations=[])
    assert out["lines"] == {lc.UNASSIGNED: 5_000_000}


def test_a_person_who_costs_nothing_produces_no_lines():
    assert lc.split_person(0, days=_days("A"))["lines"] == {}


# ── the report ───────────────────────────────────────────────────────────────────────────────────

def _person(eid, cost, days=None, allocs=None):
    return {"empId": eid, "name": eid, "dept": "Engineering", "cost": cost,
            "costBasis": "signed pay run", "days": days or [], "allocations": allocs or []}


def test_every_dong_of_everybody_lands_on_exactly_one_line():
    r = lc.report([
        _person("A", 10_000_000, _days("P1", "P1", "P2")),
        _person("B", 7_777_777, [], [{"projectId": "P1", "allocationPct": 70},
                                     {"projectId": "P2", "allocationPct": 30}]),
        _person("C", 3_000_003),
    ])
    assert r["total"] == 20_777_780
    assert r["booked"] == r["total"]
    assert r["reconciles"] is True
    assert sum(p["cost"] for p in r["people"]) == r["total"]


def test_the_report_says_how_much_of_it_is_fact_rather_than_estimate():
    r = lc.report([_person("A", 1_000_000, _days("P1")),
                   _person("B", 1_000_000, [], [{"projectId": "P2", "allocationPct": 100}])])
    by = {x["projectId"]: x for x in r["projects"]}
    assert by["P1"]["basis"] == lc.RECORDED
    assert by["P2"]["basis"] == lc.ALLOCATED
    assert r["recordedShare"] == 50.0


def test_work_attributed_to_nothing_is_its_own_line_and_named_in_plain_words():
    r = lc.report([_person("A", 4_000_000)])
    row = [x for x in r["projects"] if x["projectId"] == lc.UNASSIGNED][0]
    assert row["name"] == "Not attributed to a project"
    assert r["unattributed"] == 4_000_000


def test_projects_are_named_where_a_name_is_known():
    r = lc.report([_person("A", 1_000, _days("PRJ-7"))], project_names={"PRJ-7": "Cleanroom Phase 2"})
    assert r["projects"][0]["name"] == "Cleanroom Phase 2"


def test_the_biggest_project_comes_first():
    r = lc.report([_person("A", 1_000_000, _days("SMALL")),
                   _person("B", 9_000_000, _days("BIG"))])
    assert [p["projectId"] for p in r["projects"]][:2] == ["BIG", "SMALL"]


def test_an_empty_month_reports_zero_rather_than_failing():
    r = lc.report([])
    assert r["total"] == 0 and r["projects"] == [] and r["reconciles"] is True


def test_junk_costs_do_not_poison_the_arithmetic():
    r = lc.report([_person("A", None), _person("B", "not a number"), _person("C", 1_000)])
    assert r["total"] == 1_000 and r["reconciles"] is True


def test_the_reconciliation_flag_can_actually_fail(monkeypatch):
    """The guard exists to catch a bug in the splitter, so it has to be provable that it WOULD.

    Every earlier test asserts reconciles is True — which a hardcoded `True` also satisfies, and a
    mutation run proved exactly that. The flag is what the report prints as "every dong is
    attributed to exactly one line", directly above numbers somebody prices a tender from; a claim
    that cannot be false is not a check, it is decoration. So: make the splitter lose money on
    purpose and confirm the report refuses to vouch for itself."""
    real = lc.split_person

    def _lossy(cost, days=None, allocations=None):
        out = real(cost, days, allocations)
        for k in out["lines"]:
            out["lines"][k] -= 1          # a dong evaporates on every line
        return out

    monkeypatch.setattr(lc, "split_person", _lossy)
    r = lc.report([_person("A", 1_000_000, _days("P1"))])
    assert r["reconciles"] is False, "money went missing and the report said it had not"
    assert r["booked"] < r["total"]
