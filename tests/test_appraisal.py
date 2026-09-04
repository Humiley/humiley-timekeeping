"""Appraisal cycles, and which rating is allowed to move somebody's pay.

The feature is the cycle. The defect underneath it is that payroll took whichever review record came
last in the list — any cycle, any date, finished or not — and a rating swings the KPI component from
0× to 1.5×. So the tests that matter most are the ones about which rating governs a month, and each
of them describes a way somebody could have been paid on a number that was never a decision.
"""
import appraisal as ap


def _cycle(cid, name, status, frm, to, parts=None, due=None):
    return {"id": cid, "name": name, "status": status, "periodFrom": frm, "periodTo": to,
            "dueDate": due, "participants": parts or []}


def _rev(cid, eid, status="Completed", rating=4):
    return {"cycleId": cid, "empId": eid, "status": status, "rating": rating}


def _emp(eid, start, end=None, dept="Engineering", salary=20_000_000, mgr="mgr@humiley.com"):
    e = {"id": eid, "name": eid, "startDate": start, "dept": dept, "salary": salary,
         "managerEmail": mgr}
    if end:
        e["endDate"] = end
    return e


# ── which rating governs a month ─────────────────────────────────────────────────────────────────

CLOSED_2025 = _cycle("C1", "Annual 2025", ap.CLOSED, "2025-01-01", "2025-12-31")
OPEN_2026 = _cycle("C2", "Annual 2026", ap.OPEN, "2026-01-01", "2026-12-31")


def test_a_completed_review_in_a_closed_cycle_governs_its_own_period():
    r, why = ap.governing_rating([CLOSED_2025], [_rev("C1", "E1", rating=5)], "E1", "2025-06")
    assert r == 5 and "completed" in why


def test_an_unfinished_review_never_sets_pay():
    """Somebody's half-written self-assessment is not a decision about their pay."""
    r, why = ap.governing_rating([CLOSED_2025], [_rev("C1", "E1", status="Self-assessment", rating=5)],
                                 "E1", "2025-06")
    assert r == ap.NEUTRAL_RATING and "never completed" in why


def test_an_open_cycle_governs_nothing_however_good_the_rating_in_it():
    """The exact shape of the old bug: a draft 5 in this year's open round outranking everything."""
    cycles = [CLOSED_2025, OPEN_2026]
    reviews = [_rev("C1", "E1", rating=2), _rev("C2", "E1", status="In review", rating=5)]
    r, why = ap.governing_rating(cycles, reviews, "E1", "2026-06")
    assert r == 2, "the closed 2025 rating still governs 2026 until 2026 closes"
    assert "Annual 2025" in why


def test_a_rating_applies_forward_not_backward():
    """A 2025 appraisal cannot reach back into 2024 — nobody had been appraised yet."""
    r, why = ap.governing_rating([CLOSED_2025], [_rev("C1", "E1", rating=5)], "E1", "2024-06")
    assert r == ap.NEUTRAL_RATING and "No closed appraisal cycle" in why


def test_the_most_recent_closed_cycle_governs_a_month_after_all_of_them():
    older = _cycle("C0", "Annual 2024", ap.CLOSED, "2024-01-01", "2024-12-31")
    reviews = [_rev("C0", "E1", rating=1), _rev("C1", "E1", rating=5)]
    r, why = ap.governing_rating([older, CLOSED_2025], reviews, "E1", "2026-03")
    assert r == 5 and "Annual 2025" in why


def test_a_covering_cycle_beats_a_merely_earlier_one():
    older = _cycle("C0", "Annual 2024", ap.CLOSED, "2024-01-01", "2024-12-31")
    reviews = [_rev("C0", "E1", rating=1), _rev("C1", "E1", rating=5)]
    r, _ = ap.governing_rating([older, CLOSED_2025], reviews, "E1", "2025-07")
    assert r == 5


def test_somebody_never_appraised_gets_the_neutral_rating_and_it_says_so():
    """Neutral pays the KPI target exactly. Guessing pays them more or less than they earned."""
    r, why = ap.governing_rating([CLOSED_2025], [_rev("C1", "OTHER", rating=5)], "E1", "2025-06")
    assert r == ap.NEUTRAL_RATING and "not appraised" in why


def test_a_rating_outside_one_to_five_is_refused_rather_than_clamped():
    """A 7 in the box is a typo. Paying somebody on it, or silently reading it as a 5, are both
    worse than falling back to neutral."""
    assert ap.clamp_rating(7) is None and ap.clamp_rating(0) is None
    assert ap.clamp_rating("banana") is None and ap.clamp_rating(None) is None
    assert ap.clamp_rating(4.5) == 4.5
    r, why = ap.governing_rating([CLOSED_2025], [_rev("C1", "E1", rating=99)], "E1", "2025-06")
    assert r == ap.NEUTRAL_RATING and "no usable rating" in why


def test_the_reason_always_comes_back_with_the_number():
    """"3 from a real appraisal" and "3 because nothing was found" are different facts, and only one
    survives being questioned by the person being paid."""
    for cycles, reviews in (([], []), ([CLOSED_2025], []),
                            ([CLOSED_2025], [_rev("C1", "E1", rating=4)])):
        r, why = ap.governing_rating(cycles, reviews, "E1", "2025-06")
        assert why and isinstance(why, str)


# ── who is in a cycle ────────────────────────────────────────────────────────────────────────────

def test_somebody_who_joined_near_the_end_has_nothing_to_be_appraised_on():
    out = ap.eligible([_emp("new", "2025-11-15"), _emp("old", "2020-01-01")],
                      "2025-01-01", "2025-12-31")
    assert [r["empId"] for r in out["included"]] == ["old"]
    assert out["excluded"][0]["empId"] == "new" and "minimum" in out["excluded"][0]["why"]


def test_the_people_left_out_are_returned_not_dropped():
    """Opening a cycle has to show who it deliberately excluded, or the exclusion is invisible."""
    out = ap.eligible([_emp("noStart", None), _emp("gone", "2020-01-01", "2024-06-30")],
                      "2025-01-01", "2025-12-31")
    whys = {r["empId"]: r["why"] for r in out["excluded"]}
    assert "No start date" in whys["noStart"]
    assert "Left before" in whys["gone"]


def test_somebody_who_left_mid_period_is_still_appraised_for_the_part_they_worked():
    out = ap.eligible([_emp("leaver", "2020-01-01", "2025-09-30")], "2025-01-01", "2025-12-31")
    assert [r["empId"] for r in out["included"]] == ["leaver"]


# ── how far along ────────────────────────────────────────────────────────────────────────────────

PARTS = [{"empId": "A", "name": "A", "dept": "Eng", "managerEmail": "m1@x"},
         {"empId": "B", "name": "B", "dept": "Eng", "managerEmail": "m1@x"},
         {"empId": "C", "name": "C", "dept": "Ops", "managerEmail": "m2@x"}]


def test_completion_is_against_the_frozen_list_not_whoever_is_here_now():
    """Recomputing eligibility on read means a leaver drops out of the denominator and completion
    climbs to 100% without anybody finishing anything."""
    cy = _cycle("C1", "Annual", ap.OPEN, "2025-01-01", "2025-12-31", parts=PARTS)
    st = ap.state(cy, [_rev("C1", "A")])
    assert st["participants"] == 3 and st["done"] == 1
    assert st["pct"] == 33.3


def test_a_status_that_is_not_a_known_done_state_counts_as_not_finished():
    cy = _cycle("C1", "Annual", ap.OPEN, "2025-01-01", "2025-12-31", parts=PARTS)
    st = ap.state(cy, [_rev("C1", "A", status="Compleeted")])
    assert st["done"] == 0, "a typo must never read as finished"


def test_who_is_holding_it_up_is_grouped_by_the_manager_who_owes_it():
    """A flat list of thirty names is not actionable; "these two are yours" is."""
    cy = _cycle("C1", "Annual", ap.OPEN, "2025-01-01", "2025-12-31", parts=PARTS)
    st = ap.state(cy, [])
    top = st["chase"][0]
    assert top["manager"] == "m1@x" and sorted(top["waitingOn"]) == ["A", "B"]


def test_a_cycle_is_only_overdue_while_it_is_open():
    parts = PARTS
    late_open = _cycle("C1", "A", ap.OPEN, "2025-01-01", "2025-12-31", parts, due="2026-01-31")
    late_closed = _cycle("C2", "A", ap.CLOSED, "2025-01-01", "2025-12-31", parts, due="2026-01-31")
    assert ap.state(late_open, [], today="2026-03-01")["overdue"] is True
    assert ap.state(late_closed, [], today="2026-03-01")["overdue"] is False


def test_an_implausible_rating_spread_is_called_out_before_it_becomes_money():
    d = ap.distribution([{"rating": 5}] * 6)
    assert d["flags"], "six out of six on the top rating should not pass without comment"
    assert any("not taken seriously" in f or "meaningless" in f for f in d["flags"])


def test_a_credible_spread_is_not_nagged_about():
    d = ap.distribution([{"rating": r} for r in (2, 3, 3, 4, 4, 5)])
    assert d["flags"] == []
    assert d["mean"] == 3.5 and d["n"] == 6


# ── salary proposals ─────────────────────────────────────────────────────────────────────────────

def _row(eid, rating, done=True):
    return {"empId": eid, "name": eid, "rating": rating, "done": done}


def test_a_rating_becomes_a_proposed_increase_and_nothing_is_applied():
    emps = [_emp("A", "2020-01-01", salary=20_000_000)]
    p = ap.proposals([_row("A", 5)], emps)
    assert p["rows"][0]["increase"] == 2_000_000 and p["rows"][0]["proposed"] == 22_000_000
    assert emps[0]["salary"] == 20_000_000, "the employee record must be untouched"


def test_an_unfinished_review_proposes_nothing_and_says_why():
    p = ap.proposals([_row("A", 5, done=False)], [_emp("A", "2020-01-01")])
    assert p["rows"][0]["increase"] == 0 and "No completed rating" in p["rows"][0]["why"]


def test_a_budget_cap_scales_everybody_by_the_same_factor():
    """The alternative is somebody quietly cutting the bottom of the list, which is how a review
    round becomes a rumour."""
    emps = [_emp(x, "2020-01-01", salary=10_000_000) for x in ("A", "B")]
    uncapped = ap.proposals([_row("A", 5), _row("B", 5)], emps)
    assert uncapped["increasePct"] == 10.0
    capped = ap.proposals([_row("A", 5), _row("B", 5)], emps, budget_pct=5)
    assert capped["capped"] is True
    assert capped["increasePct"] <= 5.01
    assert capped["rows"][0]["increase"] == capped["rows"][1]["increase"], "scaled evenly"


def test_a_budget_that_is_not_binding_leaves_the_matrix_alone():
    emps = [_emp("A", "2020-01-01", salary=10_000_000)]
    p = ap.proposals([_row("A", 3)], emps, budget_pct=50)
    assert p["capped"] is False and p["rows"][0]["pct"] == 4.0


def test_somebody_with_no_salary_on_record_is_not_given_an_increase_from_nothing():
    p = ap.proposals([_row("A", 5)], [_emp("A", "2020-01-01", salary=0)])
    assert p["rows"][0]["increase"] == 0 and "no salary on record" in p["rows"][0]["why"]


def test_a_round_with_no_downside_is_flagged_even_when_nobody_is_on_the_top_rating():
    """The six-fives case trips BOTH flags, so it cannot tell them apart — a mutation run deleted
    the no-downside check and the test still passed on the top-heavy one. This spread trips only the
    first: nobody below the midpoint, but nowhere near half on a 5."""
    d = ap.distribution([{"rating": r} for r in (3, 3, 3, 4, 4, 3)])
    assert d["flags"], "nobody below the midpoint should not pass without comment"
    assert any("no downside" in f for f in d["flags"])
    assert not any("half the team" in f for f in d["flags"]), "the top-heavy flag must NOT fire here"
