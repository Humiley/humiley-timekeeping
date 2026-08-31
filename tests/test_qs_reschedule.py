"""Moving the programme for an extension the client has actually granted.

extension_of_time() records the revised completion date and touches nothing else, on purpose: the
planned finish is what every variance on the job is measured against, and moving it makes a late
job look on time by rewriting the thing it was late against. The engineering module learned that
the expensive way — SPI came from a live planned date, so moving a slipped date reset it to 1.00
with no record the plan had ever moved.

But an extension the client HAS granted is a real change to the agreed programme, and a schedule
that never reflects it is one nobody can plan against. The reconciliation is the one PMBOK §6.6
gives: re-plan, but only after the original is frozen where variance can still see it.
"""
import io

import pytest

import qsurvey as qs


def _t(**kw):
    return dict({"id": "t1", "name": "Install AHU-01", "start": "2026-06-01",
                 "finish": "2026-06-30", "baselineStart": "2026-06-01",
                 "baselineFinish": "2026-06-30", "pctComplete": 40,
                 "status": "In progress"}, **kw)


def _p(**kw):
    return qs.reschedule_plan(dict({"tasks": [_t()], "grantedDays": 18,
                                    "eventDate": "2026-05-01",
                                    "baselineFrozen": True}, **kw))


def _codes(r):
    return {w["code"] for w in r["warnings"]}


def _held(r, tid="t1"):
    return next((h for h in r["held"] if h["id"] == tid), None)


# ── the baseline comes first, always ─────────────────────────────────────────────────────────────

def test_nothing_moves_while_an_activity_has_dates_and_no_baseline():
    """The only condition that stops the whole operation, and it stops it rather than proceeding
    and mentioning it afterwards. Moving these would destroy the only record of the agreed plan."""
    r = _p(tasks=[_t(baselineStart="", baselineFinish="")])
    assert r["moves"] == []
    assert r["needsBaseline"] == ["t1"]
    assert r["baselineFrozen"] is False
    w = [x for x in r["warnings"] if x["code"] == "no_baseline"][0]
    assert w["severity"] == "high" and "destroy" in w["msg"]


def test_the_move_it_would_have_made_is_still_reported_so_it_can_be_previewed():
    """Refusing without saying what was refused makes the fix invisible."""
    r = _p(tasks=[_t(baselineFinish="")])
    assert r["moves"] == []
    assert [m["id"] for m in r["plannedMoves"]] == ["t1"]


def test_with_a_baseline_in_place_the_activity_moves_by_the_granted_days():
    r = _p()
    m = r["moves"][0]
    assert m["days"] == 18
    assert m["fromStart"] == "2026-06-01" and m["toStart"] == "2026-06-19"
    assert m["fromFinish"] == "2026-06-30" and m["toFinish"] == "2026-07-18"


def test_the_baseline_dates_are_never_among_the_things_it_moves():
    """The whole point. A move that also moved the baseline would be a job that quietly stopped
    being late."""
    m = _p()["moves"][0]
    assert "baselineStart" not in m and "baselineFinish" not in m
    assert "toBaselineFinish" not in m


# ── what does not move ───────────────────────────────────────────────────────────────────────────

def test_work_that_is_finished_does_not_move():
    """You cannot delay what has already happened, and pushing completed activities into the future
    makes the whole programme unreadable."""
    for done in ({"actualFinish": "2026-05-20"}, {"pctComplete": 100},
                 {"status": "Complete"}, {"status": "Done"}):
        r = _p(tasks=[_t(**done)])
        assert r["moves"] == [], done
        assert _held(r)["reason"] == qs.HELD_DONE
    assert "completed_work_not_moved" in _codes(_p(tasks=[_t(pctComplete=100)]))


def test_work_planned_to_finish_before_the_delay_was_never_affected_by_it():
    r = _p(tasks=[_t(start="2026-03-01", finish="2026-03-31")])
    assert r["moves"] == []
    assert _held(r)["reason"] == qs.HELD_BEFORE_EVENT


def test_work_spanning_the_delay_does_move():
    r = _p(tasks=[_t(start="2026-04-01", finish="2026-06-30")])
    assert r["moves"][0]["toFinish"] == "2026-07-18"


def test_an_activity_with_no_dates_cannot_be_moved_and_says_so():
    r = _p(tasks=[_t(start="", finish="", baselineStart="", baselineFinish="")])
    assert r["moves"] == [] and r["needsBaseline"] == []
    assert _held(r)["reason"] == qs.HELD_NO_DATES


def test_with_no_dated_delay_event_every_unfinished_activity_is_treated_as_affected():
    """Nothing can be shown to fall before a delay that has no date. Saying so beats silently
    treating the whole programme as unaffected, which would move nothing at all."""
    r = _p(eventDate="", tasks=[_t(start="2026-03-01", finish="2026-03-31")])
    assert len(r["moves"]) == 1
    assert "no_delay_event" in _codes(r)


# ── applying it twice ────────────────────────────────────────────────────────────────────────────

def test_applying_the_same_extension_twice_moves_nothing_the_second_time():
    """The shift is derived from what has already been applied, not added to the live date."""
    r = _p(tasks=[_t(eotShiftApplied=18)])
    assert r["moves"] == []
    assert _held(r)["reason"] == qs.HELD_UP_TO_DATE


def test_a_further_grant_moves_only_the_additional_days():
    """Not the whole new total. Shifting by 25 when 18 are already in would compound it."""
    r = _p(grantedDays=25, tasks=[_t(eotShiftApplied=18)])
    m = r["moves"][0]
    assert m["days"] == 7
    assert m["toFinish"] == "2026-07-07"
    assert m["nowApplied"] == 25


def test_the_project_managers_own_replanning_between_grants_is_not_wiped_out():
    """The shift is applied to the LIVE date, not recomputed from the baseline. Recomputing would
    silently undo every re-plan made for reasons that have nothing to do with the extension."""
    r = _p(grantedDays=25, tasks=[_t(start="2026-08-01", finish="2026-08-20",
                                     eotShiftApplied=18)])
    m = r["moves"][0]
    # BOTH ends. A mutation run caught this test asserting only the finish: a version that
    # recomputed the START from the baseline slipped straight through it, which is a check
    # examining half of what it claims to.
    assert m["toStart"] == "2026-08-08", "the start was recomputed from the baseline"
    assert m["toFinish"] == "2026-08-27"
    assert m["fromStart"] == "2026-08-01", "the move is measured from the LIVE date"


def test_nothing_granted_moves_nothing_and_says_a_claim_is_not_a_grant():
    r = _p(grantedDays=0)
    assert r["moves"] == [] and r["held"] == []
    w = [x for x in r["warnings"] if x["code"] == "nothing_granted"][0]
    assert "claim is not a grant" in w["msg"]


def test_the_payload_says_what_a_revised_date_without_a_baseline_would_mean():
    assert "quietly stopped being late" in _p()["note"]


# ── the endpoint ─────────────────────────────────────────────────────────────────────────────────

def _app():
    return io.open("app.py", encoding="utf-8").read()


def _ep():
    src = _app()
    return src[src.index("def _qs_eot_ep("):src.index("def _qs_cvr_ep(")]


def test_the_planned_finish_is_still_never_written():
    """Everything else in this pass exists so that this stays true."""
    body = _ep()
    for forbidden in ('upd["endPlanned"]', 'upd["endBaseline"]'):
        assert forbidden not in body, "_qs_eot_ep writes %s — it must not" % forbidden


def test_the_programme_only_moves_when_it_is_asked_to():
    """A QS recording the revised completion date has not asked for the schedule to be rewritten."""
    body = _ep()
    assert 'if body.get("reschedule"):' in body
    i = body.index('if body.get("reschedule"):')
    assert 'db.put_collection_item("pm_tasks"' not in body[:i], "tasks moved unconditionally"


def test_the_endpoint_refuses_rather_than_baselining_on_its_own_initiative():
    """Freezing a baseline is a decision about what this job will be measured against for the rest
    of its life. It is not a side effect of pressing a button labelled something else."""
    body = _ep()
    assert 'if not body.get("freezeBaseline"):' in body
    assert "return self._err(" in body[body.index('if not body.get("freezeBaseline"):'):][:400]


def test_an_existing_baseline_is_never_written_over():
    src = _app()
    i = src.index("def _qs_baseline_tasks(")
    body = src[i:src.index("def _qs_eot_ep(", i)]
    assert 'if t.get("baselineFinish")' in body and "continue" in body


def test_the_tasks_that_move_are_the_ones_the_plan_returned_and_no_others():
    """The endpoint writes what the pure function decided. A second, hand-rolled loop over the
    tasks is how the rule on screen and the rule in the engine start disagreeing."""
    body = _ep()
    assert 'for mv in plan["moves"]:' in body
    seg = body[body.index('for mv in plan["moves"]:'):]
    seg = seg[:seg.index("resched =")]
    assert 'eotShiftApplied=mv["nowApplied"]' in seg
    assert 'mv["toStart"]' in seg and 'mv["toFinish"]' in seg


def test_the_delay_event_ignores_a_variation_nobody_instructed():
    """An identified or withdrawn variation is not an instruction, so it never dated a delay."""
    src = _app()
    i = src.index("def _qs_delay_event(")
    body = src[i:src.index("def _qs_baseline_tasks(", i)]
    assert "qsurvey.V_IDENTIFIED" in body and "qsurvey.V_WITHDRAWN" in body
    assert 'qsurvey._num(v.get("timeImpactDays")) > 0' in body


# ── the screen ───────────────────────────────────────────────────────────────────────────────────

def _html():
    return io.open("templates/index.html", encoding="utf-8").read()


def test_moving_the_programme_is_asked_as_a_second_and_separate_decision():
    """Recording a date changes what the contract says. Rescheduling changes what everybody works
    to. Rolling them into one confirm makes the second happen by accident."""
    html = _html()
    assert "async function qsRescheduleOffer(" in html
    i = html.index("async function qsApplyEot(")
    body = html[i:html.index("async function qsRescheduleOffer(", i)]
    assert "qsRescheduleOffer(e)" in body
    j = body.index("_qsPost('/api/qs/eot'")
    assert "reschedule" not in body[:j], "the first call must not reschedule"


def test_the_second_confirm_says_the_baseline_is_frozen_first():
    """Freezing a baseline decides what this job is measured against for the rest of its life. A
    button that does it silently is a button nobody consented to press."""
    html = _html()
    i = html.index("async function qsRescheduleOffer(")
    body = html[i:html.index("\n}", i)]
    assert "frozen into a baseline" in body
    assert "freezeBaseline: true" in body
    assert "already complete stays where it is" in body


def test_the_baseline_is_shown_where_it_cannot_be_typed_over():
    """`readonly: true` is not something the generic form renderer understands, so a baseline field
    on the form would look protected and be fully editable. A baseline anybody can retype is not a
    baseline."""
    html = _html()
    i = html.index("pm_tasks: { title: ")
    form = html[i:html.index("pm_detail: { title: ", i)]
    assert "baselineFinish" not in form, "the baseline is editable on the task form"
    assert "label: 'Baseline finish'" in html, "and it is not shown anywhere either"


def test_an_activity_with_no_baseline_prints_a_dash_and_not_todays_date():
    """"No baseline" and "a baseline of today" are different facts."""
    html = _html()
    i = html.index("label: 'Baseline finish'")
    body = html[i:i + 900]
    assert "if (!r.baselineFinish) return" in body
    assert "—" in body
