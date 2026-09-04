# -*- coding: utf-8 -*-
"""The two server-side readers that never learnt about daily readings.

The Master Schedule's Daily progress table files dated readings into a master activity's `log`. It
writes nothing else: `pctComplete` is left alone, and `status` is derived on every screen and
written on none. Two Python modules were asking about progress in ways that could not see that.

  1. qsurvey.reschedule_plan — the extension-of-time engine, whose stated contract is "work that is
     DONE does not move". `_task_done` asked about actualFinish, pctComplete and status. An activity
     the site had reported finished answered False, landed in `plan["moves"]`, and the endpoint
     rewrote its start and finish. Completed work pushed into the future, on the one path in this
     module explicitly guarded against destroying the record of the plan.

  2. bi.py — the Power BI feed. `activities_dim` exported `typedPct` and nothing else, and the
     progress fact table was fed pm_detail alone. A project run WITHOUT a detail schedule — exactly
     the case the master-level table exists for — exported 0% for every activity and an empty
     history: a flat line at zero in Power BI beside a portal drawing the real curve.

Neither was a hard failure. Both produced a confident, wrong, printable number, which is the shape
this codebase keeps finding. Both were confirmed by RUNNING the shipping functions before being
fixed, and the numbers in these tests are the ones those runs produced.

    python3 -m pytest tests/test_server_reads_daily_progress.py -q
"""
import bi
import db
import progress
import qsurvey


def _task(**kw):
    t = {"id": "T", "name": "Piling", "projectId": "P1", "wbs": "1",
         "start": "2026-03-01", "finish": "2026-04-30", "baselineFinish": "2026-04-30",
         "pctComplete": 0, "status": "In progress"}
    t.update(kw)
    return t


def _plan(tasks, granted=30, event="2026-03-15"):
    return qsurvey.reschedule_plan({"tasks": tasks, "grantedDays": granted,
                                    "eventDate": event, "baselineFrozen": True})


# ══ 1. the extension of time ═══════════════════════════════════════════════════════════════════
def test_an_activity_the_site_reported_finished_is_not_moved():
    """The finding. Before the fix this activity's finish was rewritten 2026-04-30 -> 2026-05-30."""
    t = _task(id="T1", log=[{"d": "2026-04-25", "pct": 100, "by": "Site"}])
    plan = _plan([t])
    assert [m["id"] for m in plan["moves"]] == [], \
        "an activity reported 100%% on site was moved to %s" % (plan["moves"][0]["toFinish"],)
    assert {h["id"]: h["reason"] for h in plan["held"]} == {"T1": qsurvey.HELD_DONE}


def test_the_older_ways_of_finishing_still_count():
    """Not a replacement — an addition. Each of these was already understood and must stay so."""
    for kw in ({"pctComplete": 100}, {"status": "Completed"}, {"actualFinish": "2026-04-25"},
               {"status": "closed"}):
        t = _task(id="X", **kw)
        assert qsurvey._task_done(t), kw


def test_an_unfinished_activity_still_moves():
    """The half a careless fix breaks. Holding everything with a log would quietly stop the engine
    extending the work an extension is FOR."""
    t = _task(id="T5", log=[{"d": "2026-04-25", "pct": 40, "by": "Site"}])
    plan = _plan([t])
    assert [m["id"] for m in plan["moves"]] == ["T5"]
    assert plan["moves"][0]["toFinish"] == "2026-05-30"


def test_a_measured_reading_counts_as_the_measurement_it_is():
    """read_pct grades per READING: 500 of 500 m of pipe is 100%, whatever `pct` says beside it."""
    t = _task(id="Q", qtyPlan=500, log=[{"d": "2026-04-25", "pct": 0, "qty": 500}])
    assert qsurvey._task_done(t)
    assert not qsurvey._task_done(_task(id="Q2", qtyPlan=500,
                                        log=[{"d": "2026-04-25", "pct": 0, "qty": 250}]))


def test_the_verdict_does_not_come_from_the_clock():
    """A reading dated in the future is a typing error, not a prediction — and the two ways of
    reading it are not symmetric. Treating it as done LEAVES THE ACTIVITY ALONE, which is visible
    and reversible; treating it as unreported rewrites the completion date of finished work, which
    is silent. Also keeps this test's answer independent of the day it runs on."""
    t = _task(id="F", log=[{"d": "2099-01-01", "pct": 100}])
    assert qsurvey._task_done(t)


def test_a_malformed_log_is_not_an_exception():
    for bad in (None, "yesterday", [], [{"pct": 100}], [{"d": None, "pct": 100}], {"d": "x"}):
        assert qsurvey._task_done(_task(id="B", log=bad)) is False, bad


def test_the_engine_still_refuses_without_a_baseline():
    """Nothing above this guard was weakened: the whole operation still stops when moving an
    activity would destroy the only record of its plan."""
    t = _task(id="N", baselineFinish="", log=[{"d": "2026-04-25", "pct": 40}])
    plan = _plan([t])
    assert plan["needsBaseline"] == ["N"] and plan["moves"] == []


# ══ 2. the Power BI feed ═══════════════════════════════════════════════════════════════════════
def test_the_activity_dimension_carries_what_the_site_reported():
    rows = {r["taskId"]: r for r in bi.activities_dim([
        _task(id="A", log=[{"d": "2026-04-01", "pct": 65}]),
        _task(id="B", pctComplete=40),
    ])}
    assert rows["A"]["reportedPct"] == 65 and rows["A"]["typedPct"] == 0
    assert rows["B"]["typedPct"] == 40 and rows["B"]["reportedPct"] == 0
    assert rows["A"]["readings"] == 1 and rows["A"]["lastReadingDate"] == "2026-04-01"


def test_zero_because_nobody_asked_is_distinguishable_from_zero_because_nothing_happened():
    """The reason `readings` is a column. A model that plots reportedPct without it charts an
    activity nobody has ever been asked about as one that has made no progress."""
    rows = {r["taskId"]: r for r in bi.activities_dim([
        _task(id="NEVER"),
        _task(id="ZERO", log=[{"d": "2026-04-01", "pct": 0}]),
    ])}
    assert rows["NEVER"]["reportedPct"] == rows["ZERO"]["reportedPct"] == 0
    assert rows["NEVER"]["readings"] == 0 and rows["ZERO"]["readings"] == 1


def test_the_new_columns_are_in_the_csv_header():
    """Power BI reads the CSV. A column the writer does not name is a column nobody receives."""
    for c in ("reportedPct", "readings", "lastReadingDate"):
        assert c in bi.ACTIVITY_COLS
    assert "source" in bi.PROGRESS_COLS
    head = bi.to_csv([], bi.PROGRESS_COLS).decode("utf-8").splitlines()[0]
    assert "source" in head


# ── which activities may speak, and the double count that rule prevents ─────────────────────────
def _tree():
    tasks = [
        _task(id="A", wbs="1", name="Piling", log=[{"d": "2026-04-01", "pct": 60}]),
        _task(id="B", wbs="2", name="Ductwork", log=[{"d": "2026-04-01", "pct": 50}]),
        _task(id="C", wbs="3", name="Fit-out", log=[{"d": "2026-04-01", "pct": 90}]),
        _task(id="C1", wbs="3.1", name="Ceilings", log=[{"d": "2026-04-01", "pct": 30}]),
        _task(id="D", wbs="4", name="Commissioning"),
    ]
    details = [{"id": "d1", "projectId": "P1", "name": "Duct run E", "taskRef": "2",
                "start": "2026-03-01", "finish": "2026-04-30",
                "log": [{"d": "2026-04-01", "pct": 80}]}]
    return tasks, details


def test_only_the_activities_nothing_else_speaks_for_are_included():
    tasks, details = _tree()
    got = {t["id"] for t in bi.master_progress_items(tasks, details)}
    assert got == {"A", "C1"}, (
        "A has readings and nothing beneath it; C1 likewise. "
        "B is fed by a detail line, C is a summary of C1, D has no readings. got %s" % (got,))


def test_an_activity_fed_by_detail_lines_is_not_counted_twice():
    """The failure this selection exists to prevent, and one this repo has had before in the
    subcontract ledger: two rows for one piece of work, summed."""
    tasks, details = _tree()
    rows = bi.progress_fact(details + bi.master_progress_items(tasks, details),
                            {"id": "P1", "name": "Tower"}, "2026-04-01", "2026-04-01")
    ids = sorted(r["itemId"] for r in rows)
    assert ids == ["A", "C1", "d1"], ids
    assert sorted(r["masterRef"] for r in rows) == ["1", "2", "3.1"], \
        "one row per unit of work, each naming the master activity it belongs to"


def test_each_row_says_which_level_it_came_from():
    tasks, details = _tree()
    rows = bi.progress_fact(details + bi.master_progress_items(tasks, details),
                            {"id": "P1"}, "2026-04-01", "2026-04-01")
    assert {r["itemId"]: r["source"] for r in rows} == {
        "d1": "detail", "A": "master", "C1": "master"}


def test_the_weighted_rollup_is_right_across_both_levels():
    """SUM(weightedAccum)/SUM(weight) is the roll-up at every grain — the column the fact table
    exists to make correct. Equal durations here, so it is an average that can be checked by hand:
    detail line 80, A 60, C1 30."""
    tasks, details = _tree()
    rows = [r for r in bi.progress_fact(details + bi.master_progress_items(tasks, details),
                                        {"id": "P1"}, "2026-04-01", "2026-04-01")]
    wa = sum(r["weightedAccum"] for r in rows)
    w = sum(r["weight"] for r in rows)
    assert w > 0 and round(wa / w, 6) == round((80 + 60 + 30) / 3.0, 6)


def test_a_project_with_no_detail_schedule_still_has_a_history():
    """The case the master-level table exists for, and the one that exported nothing."""
    tasks = [_task(id="A", wbs="1", log=[{"d": "2026-03-05", "pct": 20},
                                         {"d": "2026-04-01", "pct": 60}])]
    rows = bi.progress_fact(bi.master_progress_items(tasks, []), {"id": "P1"},
                            "2026-03-04", "2026-04-02")
    assert rows, "an empty fact table is a flat line at zero in Power BI"
    by_day = {r["date"]: r["accumulatedPct"] for r in rows}
    assert by_day["2026-03-04"] == 0 and by_day["2026-03-05"] == 20
    assert by_day["2026-03-31"] == 20, "carried forward between readings, not interpolated"
    assert by_day["2026-04-01"] == 60 and by_day["2026-04-02"] == 60


# ── and the endpoint is actually wired to it ────────────────────────────────────────────────────
def test_the_live_endpoint_serves_both_levels(api, tokens):
    """Through the real route, not the functions underneath it.

    Every assertion above passes bi.master_progress_items into bi.progress_fact by hand, so all of
    them stayed green when `_bi_ep` was reverted to feeding pm_detail alone — the fix was correct,
    fully tested, and not connected to anything. A mutation run found it; this test is what closes
    it. `_bi_guard` lets a signed-in manager read the feed, so no BI key is needed here."""
    made = []
    try:
        p = db.put_collection_item("pm_projects", {"id": "ZZ-BI-FEED", "name": "ZZ BI Feed"})
        made.append(("pm_projects", p["id"]))
        t = db.put_collection_item("pm_tasks", {
            "projectId": "ZZ-BI-FEED", "wbs": "1", "name": "Piling",
            "start": "2026-03-01", "finish": "2026-04-30",
            "log": [{"d": "2026-03-05", "pct": 20}, {"d": "2026-04-01", "pct": 60}]})
        made.append(("pm_tasks", t["id"]))

        st, b = api("GET", "/api/bi/progress?project=ZZ-BI-FEED&from=2026-03-04&to=2026-04-02",
                    tokens["mgr"])
        assert st == 200, b
        rows = [r for r in b["rows"] if r["itemId"] == t["id"]]
        assert rows, ("the master activity reached no row of the feed — a project with no detail "
                      "schedule exports a flat line at zero. columns=%s rowCount=%s"
                      % (b.get("columns"), b.get("rowCount")))
        assert {r["source"] for r in rows} == {"master"}
        by_day = {r["date"]: r["accumulatedPct"] for r in rows}
        assert by_day["2026-03-04"] == 0 and by_day["2026-03-05"] == 20 and by_day["2026-04-01"] == 60

        st2, b2 = api("GET", "/api/bi/activities?project=ZZ-BI-FEED", tokens["mgr"])
        assert st2 == 200, b2
        dim = [r for r in b2["rows"] if r["taskId"] == t["id"]][0]
        assert dim["reportedPct"] == 60 and dim["readings"] == 2
        assert "reportedPct" in b2["columns"]
    finally:
        for coll, iid in reversed(made):
            try:
                db.delete_collection_item(coll, iid)
            except Exception:
                pass


# ══ 3. one home for the rules ══════════════════════════════════════════════════════════════════
def test_the_reading_rules_have_exactly_one_implementation_on_the_server():
    """bi.py's copy was the second (the frontend has the first). qsurvey.py needing the same
    question was the moment to stop, not to write a third — payroll_calc.py already carries a
    standing obligation to track a frontend function, and one of those is enough."""
    assert bi.accumulated_at is progress.accumulated_at
    assert bi.clean_log is progress.clean_log and bi.read_pct is progress.read_pct
    assert bi.qty_plan is progress.qty_plan
    src = open(qsurvey.__file__, encoding="utf-8").read()
    assert "import progress" in src
    for spelling in ("def clean_log", "def read_pct", "def accumulated_at"):
        assert spelling not in src, "qsurvey has grown its own copy of %r" % spelling


def test_the_helpers_kept_their_public_names():
    """Every existing caller and test says bi.accumulated_at. The move was to stop a third copy,
    not to rename anything."""
    it = {"qtyPlan": 500, "log": [{"d": "2026-04-01", "pct": 10},
                                  {"d": "2026-04-05", "pct": 0, "qty": 250}]}
    assert bi.accumulated_at(it, "2026-04-02") == 10
    assert bi.accumulated_at(it, "2026-04-05") == 50
    assert progress.latest_pct(it) == 50 and progress.last_reading_date(it) == "2026-04-05"
