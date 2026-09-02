"""Planned Value, the S-curve and task duration — the numbers the module PRINTS.

Three defects, one theme: the figures were computed from the wrong source.

  * The Planned (PV) line on the cost S-curve was `bac * (i+1) / months.length` — the total budget
    smeared evenly across the calendar. Every project drew the same straight diagonal, on the one
    artifact that goes to the client and the consultant every month, while the budget + period the PM
    had already typed on each cost line was used only for the Actual series.
  * `_pmTimeElapsedPct` read `startPlanned || startBaseline`, so the LIVE dates won. Push the finish
    out two months and SPI resets toward 1.00 — the slip erases itself from the KPI strip, the status
    PDF and the portfolio tile. Meanwhile the S-curve on the same tab anchors to the baseline, so the
    chart and the number contradicted each other.
  * `_pmDerive` stored duration as the EXCLUSIVE date difference while the CPM engine, the Gantt DUR
    column and the weighted roll-up all treat it as inclusive. One network mixed both units, so float
    and the critical path came out wrong — and a typed "10" was silently rewritten to 9.

The functions are lifted out of the single-file frontend and exercised in Node, so these assert the
arithmetic rather than the presence of a line of source.
"""
import json
import os
import re
import shutil
import subprocess
import tempfile

import pytest

IDX = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))),
                   "templates", "index.html")
pytestmark = pytest.mark.skipif(shutil.which("node") is None, reason="node not installed")


def _fn(src, name):
    """Pull one top-level `function name(...) { ... }` out by brace matching."""
    i = src.index("\nfunction %s(" % name) + 1
    depth, j, started = 0, i, False
    while j < len(src):
        if src[j] == "{":
            depth += 1
            started = True
        elif src[j] == "}":
            depth -= 1
            if started and depth == 0:
                return src[i:j + 1]
        j += 1
    raise AssertionError("unterminated function " + name)


def _run(js):
    with open(IDX, encoding="utf-8") as fh:
        src = fh.read()
    harness = "\n".join(_fn(src, n) for n in
                        ("_pmBaseline", "_pmDateDiff", "_pmPhasedPlan", "_pmPlannedTo",
                         "_pmTimeElapsedPct")) + "\n" + js
    p = os.path.join(tempfile.mkdtemp(prefix="tk-evm-"), "t.js")
    with open(p, "w", encoding="utf-8") as fh:
        fh.write(harness)
    r = subprocess.run(["node", p], capture_output=True, text=True)
    assert r.returncode == 0, r.stderr
    return json.loads(r.stdout)


# ── time-phased Planned Value ─────────────────────────────────────────────────────────────────────

def test_the_planned_curve_follows_the_typed_budget_not_a_straight_line():
    """A mobilisation-heavy job: almost nothing planned in month 1, the bulk in month 3."""
    out = _run("""
      const costs = [{budget: 100, period: '2026-01'}, {budget: 200, period: '2026-02'},
                     {budget: 700, period: '2026-03'}];
      const plan = _pmPhasedPlan(costs, 1000);
      console.log(JSON.stringify({
        phased: plan.phased,
        jan: _pmPlannedTo(plan, '2026-01-31'),
        feb: _pmPlannedTo(plan, '2026-02-28'),
        end: _pmPlannedTo(plan, '2026-04-01'),
        linearFeb: 1000 * 2 / 3
      }));
    """)
    assert out["phased"] is True
    assert out["jan"] == pytest.approx(100, abs=4)
    assert out["feb"] == pytest.approx(300, abs=8)
    assert out["end"] == pytest.approx(1000)
    assert out["feb"] < out["linearFeb"] / 2, \
        "the straight line would claim ~667 planned by end-Feb; the real plan says ~300"


def test_a_half_tagged_register_falls_back_instead_of_inflating_spi():
    """Only 40% of the budget carries a period. A partial curve would end below BAC and make SPI look
       BETTER than reality — worse than the honest straight line."""
    out = _run("""
      const costs = [{budget: 400, period: '2026-01'}, {budget: 600}];
      const plan = _pmPhasedPlan(costs, 1000);
      console.log(JSON.stringify({phased: plan.phased, pv: _pmPlannedTo(plan, '2026-06-01')}));
    """)
    assert out["phased"] is False
    assert out["pv"] is None, "an untrusted curve must return null so the caller uses the linear PV"


def test_a_nearly_complete_register_is_scaled_onto_bac():
    """PV totals BAC by definition — a 2% shortfall in tagging must not end the curve 2% low."""
    out = _run("""
      const costs = [{budget: 490, period: '2026-01'}, {budget: 490, period: '2026-02'}];
      const plan = _pmPhasedPlan(costs, 1000);
      console.log(JSON.stringify({phased: plan.phased, end: _pmPlannedTo(plan, '2026-05-01')}));
    """)
    assert out["phased"] is True
    assert out["end"] == pytest.approx(1000), "the phased shape must be scaled onto the approved budget"


def test_pv_creeps_through_the_month_instead_of_stepping():
    out = _run("""
      const plan = _pmPhasedPlan([{budget: 1000, period: '2026-03'}], 1000);
      console.log(JSON.stringify({
        start: _pmPlannedTo(plan, '2026-03-01'), mid: _pmPlannedTo(plan, '2026-03-16'),
        end: _pmPlannedTo(plan, '2026-03-31')
      }));
    """)
    assert out["start"] < out["mid"] < out["end"]
    assert out["mid"] == pytest.approx(516, abs=25)


def test_untagged_or_zero_budget_never_claims_to_be_phased():
    out = _run("""
      console.log(JSON.stringify({
        none: _pmPhasedPlan([], 1000).phased,
        noBac: _pmPhasedPlan([{budget: 500, period: '2026-01'}], 0).phased,
        junkPeriod: _pmPhasedPlan([{budget: 500, period: 'soon'}], 500).phased
      }));
    """)
    assert out == {"none": False, "noBac": False, "junkPeriod": False}


# ── SPI measures against the baseline ─────────────────────────────────────────────────────────────

def test_pushing_the_finish_date_out_no_longer_erases_the_slip():
    """The self-healing schedule. Same project, same day; only the live finish date moves."""
    out = _run("""
      const bl = {start: '2026-01-01', finish: '2026-06-30'};
      const before = _pmTimeElapsedPct({baseline: bl, startPlanned: '2026-01-01', endPlanned: '2026-06-30'});
      const after  = _pmTimeElapsedPct({baseline: bl, startPlanned: '2026-01-01', endPlanned: '2026-12-31'});
      console.log(JSON.stringify({before: before, after: after}));
    """)
    assert out["before"] == out["after"], \
        "elapsed time must be measured against the baseline, so re-typing dates cannot reset SPI"


def test_an_unbaselined_project_behaves_exactly_as_before():
    """Degrading safely matters — most projects have no baseline set."""
    out = _run("""
      const p = {startPlanned: '2026-01-01', endPlanned: '2026-12-31'};
      const t = _pmTimeElapsedPct(p);
      console.log(JSON.stringify({ok: t !== null, inRange: t >= 0 && t <= 1}));
    """)
    assert out == {"ok": True, "inRange": True}


def test_the_flat_baseline_mirrors_are_honoured_too():
    out = _run("""
      const a = _pmTimeElapsedPct({startBaseline: '2026-01-01', endBaseline: '2026-06-30',
                                   startPlanned: '2026-01-01', endPlanned: '2026-12-31'});
      const b = _pmTimeElapsedPct({startPlanned: '2026-01-01', endPlanned: '2026-06-30'});
      console.log(JSON.stringify({same: Math.abs(a - b) < 1e-9}));
    """)
    assert out["same"] is True


# ── duration is inclusive everywhere ──────────────────────────────────────────────────────────────

def test_duration_is_inclusive_of_both_end_days():
    """1–5 Jan is a 5-day task, and a same-day task is 1 day, not 0."""
    out = _run("""
      const dur = (s, f, mile) => { const d = _pmDateDiff(s, f); return d == null ? null : (String(mile) === 'Yes' ? 0 : d + 1); };
      console.log(JSON.stringify({
        fiveDay: dur('2026-01-01', '2026-01-05'), sameDay: dur('2026-01-07', '2026-01-07'),
        milestone: dur('2026-01-07', '2026-01-07', 'Yes')
      }));
    """)
    assert out == {"fiveDay": 5, "sameDay": 1, "milestone": 0}


def test_the_stored_duration_matches_what_the_gantt_prints():
    """The Gantt DUR column and the CPM engine both do `diff + 1`; _pmDerive stored the bare diff, so
       the same task read "10d" on screen and scheduled as 9 in the network."""
    with open(IDX, encoding="utf-8") as fh:
        src = fh.read()
    derive = _fn(src, "_pmDerive")
    assert re.search(r"data\.duration = String\(data\.isMilestone\) === 'Yes' \? 0 : d \+ 1", derive), \
        "_pmDerive must store the inclusive duration"
    gantt = src.count("(_pmDateDiff(t.start, t.finish) || 0) + 1")
    assert gantt >= 1, "the Gantt DUR column convention changed — re-check that the two still agree"


# ── the S-curve actually consumes the phased plan ────────────────────────────────────────────────

def test_the_s_curve_draws_the_phased_plan_when_there_is_one():
    with open(IDX, encoding="utf-8") as fh:
        src = fh.read()
    body = src.split("function pmRenderCosts")[1][:9000]
    assert "_pmPhasedPlan(costs, ev.bac || 0)" in body
    assert "_splan.phased" in body and "_splan.byMonth[m]" in body, \
        "the Planned series must come from the register's own budget × period"
    assert "bac * (i + 1) / scMonths.length" in body, \
        "the even spread must remain as the documented fallback"


def test_evm_uses_the_phased_pv_when_available():
    with open(IDX, encoding="utf-8") as fh:
        src = fh.read()
    # _pmEvm is now a thin memo wrapper; _pmEvmCompute holds the arithmetic. Reading the wrapper
    # would assert nothing about the earned value, while still passing on a green board.
    evm = _fn(src, "_pmEvmCompute")
    assert "_pmPlannedTo(_pmPhasedPlan(costs, bac), _pmToday())" in evm
    assert "phased != null ? phased : (tp != null ? bac * tp : ev)" in evm, \
        "PV must prefer the time-phased plan and fall back to the linear one"
