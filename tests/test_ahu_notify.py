"""Who gets told when production goes wrong, and what the message actually says.

The failure mode these tests exist for is not "the wrong text was sent" — it is "nothing was sent
and nobody could tell". A notification aimed at a name the employee register does not recognise
produces a send count of zero, which is indistinguishable from nobody having push enabled. So the
sharpest tests here are the ones about unresolved recipients and about the message agreeing with
the judgement that triggered it.
"""
import ahu_notify as N
import ahu_route as R


CTX = {"unit": {"id": "u1", "pin": "PIN-2026-0417-01", "qcInspector": "Pham Thi Mai"},
       "order": {"productionLead": "Tran Van Long", "qaManager": "Pham Thi Mai",
                 "salesOwner": "Admin User"}}


# ── choosing the people ──────────────────────────────────────────────────────────────────────────

def test_recipients_come_from_the_unit_and_its_order():
    who = N.recipients(CTX, N.STEP_FAILED_ROLES)
    assert "Pham Thi Mai" in who and "Tran Van Long" in who


def test_one_person_holding_two_roles_is_told_once():
    """Mai is both QC inspector on the unit and QA manager on the order. Two pushes for one event
    is how an alert channel becomes noise."""
    who = N.recipients(CTX, N.STEP_FAILED_ROLES)
    assert [w.lower() for w in who].count("pham thi mai") == 1


def test_sales_hears_about_a_held_gate_but_not_about_a_failed_reading():
    """A held gate can move a delivery date, which is Sales' problem. A single out-of-limit reading
    at a workstation is not, and routing it to them trains them to ignore the ones that are."""
    assert "Admin User" in N.recipients(CTX, N.GATE_HELD_ROLES)
    assert "Admin User" not in N.recipients(CTX, N.STEP_FAILED_ROLES)


def test_a_unit_naming_nobody_produces_no_recipients_rather_than_raising():
    assert N.recipients({"unit": {}, "order": {}}, N.STEP_FAILED_ROLES) == []
    assert N.recipients(None, N.STEP_FAILED_ROLES) == []


def test_a_name_the_register_cannot_match_is_reported_not_swallowed():
    """THE test. If this returned [] the caller would push to one person, get a count of 1, and
    never learn that the second role holder is unreachable."""
    chosen = ["Tran Van Long", "Nguyen Thi Missing"]
    assert N.unresolved(chosen, ["Tran Van Long"]) == ["Nguyen Thi Missing"]


def test_resolution_is_case_insensitive_so_a_match_is_not_reported_as_a_gap():
    assert N.unresolved(["Tran Van Long"], ["tran van long"]) == []


def test_resolving_nobody_reports_everybody_as_a_gap():
    assert N.unresolved(["A Person", "B Person"], []) == ["A Person", "B Person"]


# ── what the message says ────────────────────────────────────────────────────────────────────────

def test_a_failed_step_names_the_unit_and_the_step():
    m = N.step_failed(CTX, {"code": "IPQC-2", "title": "Panel and foam injection"})
    assert "PIN-2026-0417-01" in m["title"]
    assert "IPQC-2" in m["body"] and "Panel and foam injection" in m["body"]
    assert m["event"] == N.FAILED


def test_the_failure_message_repeats_the_evaluator_s_own_words():
    """Composed from evaluate_step's failures, so the alert cannot contradict the decision that
    refused the sign-off. Re-deriving the wording would create a second account of one measurement."""
    check = {"key": "density", "label": "Foam density", "unit": "kg/m3", "op": ">=",
             "limit": R.PANEL_DENSITY_MIN_KGM3}
    judged = R.evaluate_check(check, 38.0)
    assert judged["status"] == R.FAIL
    m = N.step_failed(CTX, {"code": "IPQC-2"}, [judged])
    assert "Foam density" in m["body"]
    assert judged["message"] in m["body"]


def test_a_failure_with_no_readings_still_produces_a_usable_message():
    m = N.step_failed(CTX, {"code": "T3"}, [])
    assert "T3" in m["body"] and m["body"].endswith("PIN-2026-0417-01.")


def test_many_failures_are_truncated_rather_than_sent_whole():
    fails = [{"label": "L%d" % i, "message": "out"} for i in range(6)]
    m = N.step_failed(CTX, {"code": "T3"}, fails)
    assert m["body"].endswith("…")
    assert "L5" not in m["body"]


def test_a_held_gate_carries_the_blockers_that_held_it():
    m = N.gate_held(CTX, {"code": "G4"}, ["IPQC-3 not signed", "2 open NCRs"])
    assert "G4" in m["body"] and "IPQC-3 not signed" in m["body"] and "2 open NCRs" in m["body"]
    assert m["event"] == N.HELD


def test_an_aging_ncr_states_the_threshold_it_was_measured_against():
    """The number in the message is the number that decided to send it — passed in, not re-read."""
    m = N.ncr_aging(CTX, {"id": "n1", "ncrNo": "NCR-004", "description": "Door leaf twisted"}, 9, 5)
    assert "NCR-004" in m["body"] and "9 days" in m["body"] and "threshold 5" in m["body"]
    assert "Door leaf twisted" in m["body"]


def test_every_message_links_to_the_unit_it_is_about():
    for m in (N.step_failed(CTX, {"code": "X"}),
              N.gate_held(CTX, {"code": "G1"}, []),
              N.ncr_aging(CTX, {"id": "n"}, 9, 5)):
        assert m["url"] == "/?ahu=u1"


def test_a_message_about_a_unit_with_no_id_still_links_somewhere_valid():
    m = N.step_failed({"unit": {}, "order": {}}, {"code": "X"})
    assert m["url"] == "/"


def test_the_tag_differs_per_event_so_one_alert_does_not_replace_another():
    """Web Push collapses notifications sharing a tag. A shared tag would mean the second failure of
    the day silently overwrote the first."""
    a = N.step_failed(CTX, {"code": "IPQC-2"})["tag"]
    b = N.step_failed(CTX, {"code": "IPQC-3"})["tag"]
    c = N.gate_held(CTX, {"code": "IPQC-2"}, [])["tag"]
    assert len({a, b, c}) == 3


# ── the threshold ────────────────────────────────────────────────────────────────────────────────

def test_an_absent_or_unreadable_threshold_falls_back_to_the_stated_default():
    for bad in (None, "", "soon", {}, []):
        assert N.aging_threshold(bad) == N.NCR_AGING_DAYS_DEFAULT


def test_a_zero_threshold_is_refused_because_it_would_age_every_ncr_instantly():
    assert N.aging_threshold(0) == N.NCR_AGING_DAYS_DEFAULT
    assert N.aging_threshold(-3) == N.NCR_AGING_DAYS_DEFAULT


def test_a_configured_threshold_is_used():
    assert N.aging_threshold(10) == 10
    assert N.aging_threshold("10") == 10
