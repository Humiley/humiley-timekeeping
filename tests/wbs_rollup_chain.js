/* The WBS roll-up chain, tested against the code that ships.
 *
 * The owner's requirement: sub-items contribute to their detail-schedule WBS, that links to the
 * master-schedule WBS, and each master WBS contributes to the project total and its timeline.
 *
 * This file starts as a CHARACTERIZATION of what the chain does today, so that any change to the
 * project percentage — which multiplies into EV, and from EV into CPI, SPI and EAC on live client
 * projects — can be stated precisely instead of guessed at.
 *
 *   node tests/wbs_rollup_chain.js
 */
const fs = require('fs');
const path = require('path');

const src = fs.readFileSync(path.join(__dirname, '..', 'templates', 'index.html'), 'utf8');

let pass = 0, fail = 0;
const ok = (n, c, extra) => {
  if (c) { pass++; console.log('  ok    ' + n); }
  else { fail++; console.log('  FAIL  ' + n + (extra ? '\n        ' + extra : '')); }
};
const near = (n, got, want, tol) => ok(n, Math.abs(got - want) <= (tol == null ? 1e-9 : tol),
  'got ' + got + ', want ' + want);

/* ── pull the real functions out of the shipping file ───────────────────────── */
const take = (mark, what) => {
  const i = src.indexOf(mark);
  if (i < 0) { console.error('Could not find ' + what + ' — update the marker, do NOT delete this test.'); process.exit(2); }
  const j = src.indexOf('\nfunction ', i + 10);
  return src.slice(i, j < 0 ? i + 4000 : j);
};

const PRELUDE = `
  var _HR = { pm_deliverables: [], pm_tasks: [], pm_detail: [], pm_costs: [] };
  function _pmScopeFor(coll, pid) { return (_HR[coll] || []).filter(x => x.projectId === pid); }
  function _pmPct(v) { return Math.max(0, Math.min(100, Math.round(+v || 0))); }
  function _pmDateDiff(a, b) { return Math.round((Date.parse(b) - Date.parse(a)) / 86400000); }
  function _pmToday() { return '2026-08-21'; }
  function _pdTaskPct(t, pid) { return global._pdTaskPct ? global._pdTaskPct(t, pid) : null; }
`;
const api = {};
new Function(PRELUDE +
  take('function _pmActivityPct(', '_pmActivityPct') +
  take('function _pmTaskWeight(', '_pmTaskWeight') +
  take('function pmWbsRollup(', 'pmWbsRollup') +
  take('function pmScopeRollup(', 'pmScopeRollup') +
  '\nObject.assign(this, { pmScopeRollup, pmWbsRollup, _pmActivityPct, _pmTaskWeight, _HR });').call(api);
const { pmScopeRollup, pmWbsRollup, _pmActivityPct, _pmTaskWeight } = api;
const HR = api._HR;

const PID = 'p1';
const setDeliverables = rows => { HR.pm_deliverables = rows.map(r => Object.assign({ projectId: PID }, r)); };
const setTasks = rows => { HR.pm_tasks = rows.map(r => Object.assign({ projectId: PID }, r)); };
// _pdTaskPct is the detail roll-up; stub it so this file tests the LEVELS ABOVE it. Its own maths
// is covered by detail_schedule_math.js against the real code.
let DETAIL = {};                       // taskRef/wbs -> { pct, n }
api._pdTaskPct = undefined;
global._pdTaskPct = t => DETAIL[(t && (t.wbs || t.name)) || ''] || null;

console.log('\nWBS roll-up chain\n');

/* ── LEVEL 1: the project percentage, as computed today ─────────────────────── */
setDeliverables([]);
ok('no deliverables -> total 0 (the caller must decide what that means)', pmScopeRollup(PID).total === 0);

setDeliverables([{ percentComplete: 50, weight: 1 }]);
near('one deliverable at 50% -> 50', pmScopeRollup(PID).pctRaw, 50);

setDeliverables([{ percentComplete: 100, weight: 1 }, { percentComplete: 0, weight: 1 }]);
near('two equal deliverables, one done -> 50', pmScopeRollup(PID).pctRaw, 50);

setDeliverables([{ percentComplete: 100, weight: 3 }, { percentComplete: 0, weight: 1 }]);
near('weight 3 vs 1 -> 75, not 50', pmScopeRollup(PID).pctRaw, 75);

setDeliverables([{ percentComplete: 100 }, { percentComplete: 0 }]);
near('a missing weight counts as 1', pmScopeRollup(PID).pctRaw, 50);

setDeliverables([{ percentComplete: 100, weight: 0 }, { percentComplete: 0, weight: 0 }]);
near('weight 0 is treated as 1, so the row still counts', pmScopeRollup(PID).pctRaw, 50);
ok('a zero-weight set never divides by zero', isFinite(pmScopeRollup(PID).pctRaw));

setDeliverables([{ percentComplete: 250 }, { percentComplete: -80 }]);
const clamped = pmScopeRollup(PID).pctRaw;
ok('out-of-range percentages are clamped, not trusted', clamped >= 0 && clamped <= 100, String(clamped));

setDeliverables([{ percentComplete: 100, status: 'Accepted' }, { percentComplete: 40 }]);
ok('accepted deliverables are counted separately', pmScopeRollup(PID).accepted === 1);

/* ── the registers it reads are the whole point of this test ────────────────── */
const rollupSrc = take('function pmWbsRollup(', 'pmWbsRollup');
ok('the roll-up reads the WBS spine', /_pmScopeFor\('pm_deliverables', pid\)/.test(rollupSrc));
ok('the roll-up also reads the master schedule', /_pmScopeFor\('pm_tasks', pid\)/.test(rollupSrc),
   'this is the link the owner asked for: activities must reach the project total');
// pmScopeRollup keeps its name and shape so all eight existing call sites inherit the chain
// without being edited. Assert the delegation, or a future edit could quietly fork the two.
ok('pmScopeRollup delegates to pmWbsRollup rather than duplicating it',
   /function pmScopeRollup\(pid\) \{ return pmWbsRollup\(pid\); \}/.test(src));
{
  const callers = (src.match(/pmScopeRollup\(/g) || []).length;
  ok('the existing call sites still use pmScopeRollup', callers >= 8,
     'found ' + callers + ' — if this drops, some caller was rewired and may have missed the chain');
}

/* ── LEVEL 2 -> 1: does a master activity reach the project total? ──────────── */
// This is the owner's requirement: "each WBS will contribute all and impact total timeline".
// Recorded here as the CURRENT state so the change is visible in the diff, not asserted as correct.
// An UNLINKED activity must still contribute nothing — the link is what grants it scope weight.
setTasks([
  { wbs: '1', name: 'Enabling works', pctComplete: 100, start: '2026-07-01', finish: '2026-07-31' },
  { wbs: '2', name: 'MEP first fix', pctComplete: 0, start: '2026-08-01', finish: '2026-08-31' },
]);
setDeliverables([]);
ok('activities with no deliverable to deliver into contribute nothing', pmScopeRollup(PID).total === 0);
ok('and they are counted in the open, not hidden', pmWbsRollup(PID).unlinkedActivities === 2);

// A deliverable with NO linked activity keeps its typed percentage, bit-for-bit as before.
setDeliverables([{ id: 'D1', percentComplete: 40, weight: 1 }]);
setTasks([]);
near('an unlinked deliverable still reports its typed figure', pmScopeRollup(PID).pctRaw, 40);
ok('and is reported as typed, not derived', pmWbsRollup(PID).derived === 0 && pmWbsRollup(PID).typed === 1);

// THE OWNER'S REQUIREMENT: a linked activity moves its work package, which moves the project.
setDeliverables([{ id: 'D1', percentComplete: 0, weight: 1 }]);
setTasks([{ wbs: '1', name: 'Enabling', delivId: 'D1', pctComplete: 80, start: '2026-07-01', finish: '2026-07-10' }]);
near('a linked activity at 80% drives its deliverable to 80', pmScopeRollup(PID).pctRaw, 80);
ok('the deliverable is reported as derived', pmWbsRollup(PID).derived === 1);
ok('the typed 0 on the deliverable is overridden by the schedule', pmScopeRollup(PID).pctRaw !== 0);

// Two activities under one package, weighted by their span — not averaged.
setDeliverables([{ id: 'D1', percentComplete: 0, weight: 1 }]);
setTasks([
  { wbs: '1', delivId: 'D1', pctComplete: 100, start: '2026-07-01', finish: '2026-07-30' },  // 30d
  { wbs: '2', delivId: 'D1', pctComplete: 0, start: '2026-08-01', finish: '2026-08-10' },    // 10d
]);
near('two activities roll up by span, not by count', pmScopeRollup(PID).pctRaw, 75, 0.6);

// Mixed project: one derived package, one typed. Both count, at their own weights.
setDeliverables([{ id: 'D1', percentComplete: 0, weight: 1 }, { id: 'D2', percentComplete: 50, weight: 1 }]);
setTasks([{ wbs: '1', delivId: 'D1', pctComplete: 100, start: '2026-07-01', finish: '2026-07-10' }]);
near('a mixed project blends derived and typed packages', pmScopeRollup(PID).pctRaw, 75);
ok('and says how many of each', pmWbsRollup(PID).derived === 1 && pmWbsRollup(PID).typed === 1);

// A measured sub-item beats a typed activity percentage — the site's own report wins.
DETAIL = { '1': { pct: 25, n: 3 } };
setDeliverables([{ id: 'D1', percentComplete: 0, weight: 1 }]);
setTasks([{ wbs: '1', delivId: 'D1', pctComplete: 90, start: '2026-07-01', finish: '2026-07-10' }]);
near('measured sub-items override the typed activity figure', pmScopeRollup(PID).pctRaw, 25);
ok('and the basis says so', _pmActivityPct({ wbs: '1', pctComplete: 90 }, PID).basis === 'measured');
DETAIL = {};

// An actual finish date is stronger evidence than a stale typed number.
ok('an actual finish reads 100 regardless of a stale typed value',
   _pmActivityPct({ wbs: 'x', pctComplete: 20, actualFinish: '2026-07-09' }, PID).pct === 100);
ok('and is labelled complete', _pmActivityPct({ wbs: 'x', actualFinish: '2026-07-09' }, PID).basis === 'complete');
ok('a plain estimate is labelled typed', _pmActivityPct({ wbs: 'x', pctComplete: 30 }, PID).basis === 'typed');

// Weight must not be _pmCPMCompute's network duration — tuning the CPM would re-price progress.
ok('an explicit weight wins', _pmTaskWeight({ weight: 7, start: '2026-07-01', finish: '2026-07-30' }) === 7);
ok('otherwise the inclusive span is used', _pmTaskWeight({ start: '2026-07-01', finish: '2026-07-10' }) === 10);
ok('a dateless activity still counts as 1, never 0', _pmTaskWeight({}) === 1);
ok('the roll-up never reads t.duration',
   !/_pmTaskWeight[\s\S]{0,400}\bt\.duration\b/.test(src),
   'duration is CPM network duration; conflating them makes CPM tuning silently re-price progress');

// zero-weight activities must not divide by zero
setDeliverables([{ id: 'D1', percentComplete: 0, weight: 1 }]);
setTasks([{ wbs: '1', delivId: 'D1', pctComplete: 50 }, { wbs: '2', delivId: 'D1', pctComplete: 100 }]);
ok('dateless linked activities produce a finite figure', isFinite(pmScopeRollup(PID).pctRaw));

// a dangling delivId points at nothing and must not silently become scope
setDeliverables([{ id: 'D1', percentComplete: 60, weight: 1 }]);
setTasks([{ wbs: '9', delivId: 'GONE', pctComplete: 100, start: '2026-07-01', finish: '2026-07-10' }]);
near('an activity pointing at a deleted deliverable changes nothing', pmScopeRollup(PID).pctRaw, 60);

// Unlinked activities are collected under the key '', so a deliverable whose own id is falsy would
// absorb all of them and have its typed figure overridden by work nobody assigned to it. Found by
// a mutation that SURVIVED: with real ids the two readings agree exactly (20 vs 20), and only a
// blank deliverable id makes them diverge (60 vs 100). The surviving mutation was not a defect —
// it pointed at one.
setDeliverables([{ id: '', percentComplete: 60, weight: 1 }]);
setTasks([{ wbs: '9', pctComplete: 100, start: '2026-07-01', finish: '2026-07-10' }]);   // no delivId
near('a deliverable with a blank id does not absorb unlinked activities', pmScopeRollup(PID).pctRaw, 60);
setDeliverables([{ percentComplete: 60, weight: 1 }]);                                   // id undefined
setTasks([{ wbs: '9', pctComplete: 100, start: '2026-07-01', finish: '2026-07-10' }]);
near('nor does one with no id at all', pmScopeRollup(PID).pctRaw, 60);

setDeliverables([]); setTasks([]);

/* ── LEVEL 3 -> 2: ALL sub-items must reach their master activity ───────────── */
ok('the detail -> master roll-up helper exists', /function _pdTaskPct\(task, pid\)/.test(src));
ok('it matches detail rows by the master ref', /String\(r\.taskRef \|\| ''\)\.trim\(\) === ref/.test(src));
ok('it weights them rather than averaging', /_pdRollup\(rows\)\.acc/.test(src));

// The owner's requirement is that ALL sub-items contribute to their master WBS. _pdRows() narrows
// to the detail schedule currently selected in the chip bar, so an activity fed from two schedules
// reported only the half on screen — and its percentage CHANGED when the user clicked the other
// chip. A number that depends on which tab you last touched is not a measurement.
{
  const fn = take('function _pdTaskPct(', '_pdTaskPct');
  ok('the master roll-up reads ALL detail rows for the project',
     /_pdAllRows\(pid\)\.filter/.test(fn),
     'must be _pdAllRows — _pdRows() is scoped to the selected detail schedule');
  ok('it does NOT read the selected-schedule view',
     !/_pdRows\(pid\)\.filter/.test(fn),
     'reading _pdRows makes an activity percentage depend on which chip is showing');
}
// and prove the premise: _pdRows really is narrowed, so the distinction above is not imaginary
{
  const rowsFn = take('function _pdRows(', '_pdRows');
  ok('_pdRows really does narrow to the selected schedule',
     /all\.filter\(r => r\.scheduleId === cur\.id\)/.test(rowsFn),
     'if this stops being true the assertion above is guarding nothing');
}

/* ── the EV fallback, which is where a typed number can become money ────────── */
const evm = take('function _pmEvm(', '_pmEvm');
ok('EV takes its ratio from the scope roll-up', /const sr = pmScopeRollup\(p\.id\)/.test(evm));
ok('EV multiplies that ratio by BAC', /const ev = bac \* ratio/.test(evm));
ok('CPI is derived from EV', /cpi = \(ac > 0 && bac > 0\) \? ev \/ ac/.test(evm));

// SPI returned a confident 1.00 — "perfectly on schedule" — with nothing to measure: no baseline
// and no phased cost register means pv === ev, so the ratio is 1 by construction. The number is
// unchanged for callers that only render it; the flag lets a screen decline to assert instead.
ok('SPI carries whether it could be measured at all', /spiMeasurable/.test(evm),
   'a 1.00 nobody can distinguish from a real on-schedule reading is the silent-zero shape');
// (the stronger form of this assertion lives below, after the EAC block — the original tested
//  `pv > 0`, which turned out to be the symptom rather than the cause)
ok('EV reports which basis produced it', /evBasis:/.test(evm),
   'schedule-derived, deliverable-typed and project-typed are three different claims');

/* ── a forecast needs earned value, or it is not a forecast ─────────────────── */
// `const eac = (bac > 0 && cpi > 0) ? bac / cpi : ac;` fell through to AC when ev === 0, because a
// zero EV makes CPI zero. A ₫1B project that had spent ₫200M and recorded no progress reported
// "Forecast ₫200M · Variance +₫800M · To Complete ₫0" — it will finish for what has been spent,
// with nothing left to spend, and the positive VAC reads as an underspend. Type 10% and the same
// project reads EAC ₫2B / VAC −₫1B. These print on the Status, Progress and Closeout PDFs.
ok('EAC is not computed without earned value', /const eacMeasurable = ev > 0 && ac > 0 && bac > 0/.test(evm));
ok('EAC never falls back to AC', !/\? bac \/ cpi : ac;/.test(evm),
   'falling back to AC asserts the job finishes for what has already been spent');
ok('EAC is null when it cannot be computed', /const eac = eacMeasurable \? bac \/ cpi : null/.test(evm));
ok('VAC follows EAC into null', /vac: eacMeasurable \? bac - eac : null/.test(evm));
ok('ETC follows EAC into null', /etc: eacMeasurable \? eac - ac : null/.test(evm));
// every place that prints it must handle the null rather than rendering "₫0" or "NaN"
{
  const cost = take('function pmRenderCosts(', 'pmRenderCosts');
  ok('the Cost/EVM tiles print an em dash for a null forecast', /r\[1\] == null \? '—'/.test(cost));
  ok('and say why there is no forecast', /eacMeasurable \? '' :/.test(cost));
}
ok('the Status PDF declines instead of asserting',
   /eacMeasurable \? _pmMoney\(ev\.eac\) : 'not computable/.test(src));
ok('the client-headed progress report declines too',
   /eacMeasurable\n?\s*\? \(_pmMoney\(ev\.eac\)/.test(src) || /eacMeasurable$/m.test(src));
ok('the Closeout PDF declines too', /\['Final CPI', ev\.eacMeasurable \?/.test(src));

/* ── and the SPI guard must test the CAUSE, not the symptom ─────────────────── */
// The first version tested `pv > 0`. PV falls back to EV when there is no baseline and no phased
// plan, so that was GUARANTEED true whenever ev > 0 — the flag was true in exactly the case it was
// written to catch, and could only be false when the ratio was 0/0 anyway.
ok('spiMeasurable requires PV to be derived independently of EV',
   /const pvIndependent = \(phased != null\) \|\| \(tp != null\)/.test(evm),
   'testing pv > 0 tests the symptom; the question is whether PV came from anywhere but EV');
ok('and spiMeasurable is built on that', /const spiMeasurable = pvIndependent &&/.test(evm));
ok('the old symptom-only test is gone', !/const spiMeasurable = pv > 0 && bac > 0 && ev > 0/.test(evm));

console.log('\n' + pass + ' passed, ' + fail + ' failed\n');
process.exit(fail ? 1 : 0);
