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
`;
const api = {};
new Function(PRELUDE +
  take('function pmScopeRollup(', 'pmScopeRollup') +
  '\nObject.assign(this, { pmScopeRollup, _HR });').call(api);
const { pmScopeRollup } = api;
const HR = api._HR;

const PID = 'p1';
const setDeliverables = rows => { HR.pm_deliverables = rows.map(r => Object.assign({ projectId: PID }, r)); };

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

/* ── the register it reads is the whole point of this test ──────────────────── */
const rollupSrc = take('function pmScopeRollup(', 'pmScopeRollup');
ok('the project percentage is computed from a register',
   /_pmScopeFor\('pm_(deliverables|tasks)'/.test(rollupSrc), rollupSrc.slice(0, 120));

/* ── LEVEL 2 -> 1: does a master activity reach the project total? ──────────── */
// This is the owner's requirement: "each WBS will contribute all and impact total timeline".
// Recorded here as the CURRENT state so the change is visible in the diff, not asserted as correct.
HR.pm_tasks = [
  { projectId: PID, wbs: '1', name: 'Enabling works', pctComplete: 100, start: '2026-07-01', finish: '2026-07-31' },
  { projectId: PID, wbs: '2', name: 'MEP first fix', pctComplete: 0, start: '2026-08-01', finish: '2026-08-31' },
];
setDeliverables([]);
const withTasksOnly = pmScopeRollup(PID);
ok('CURRENT: master activities alone produce total 0 — they do not reach the project percentage',
   withTasksOnly.total === 0,
   'if this now fails, the roll-up was wired up and this characterization needs rewriting to match');

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
ok('CURRENT: with no deliverables, EV falls back to a TYPED project percentage',
   /sr\.total \? sr\.pctRaw : Math\.max\(0, Math\.min\(100, \+p\.percentComplete \|\| 0\)\)/.test(evm),
   'a project with real site production but no deliverables earns whatever someone typed');
ok('EV multiplies that ratio by BAC', /const ev = bac \* ratio/.test(evm));
ok('CPI and SPI are derived from EV', /cpi = \(ac > 0 && bac > 0\) \? ev \/ ac/.test(evm) && /spi = \(pv > 0 && bac > 0\) \? ev \/ pv/.test(evm));

console.log('\n' + pass + ' passed, ' + fail + ' failed\n');
process.exit(fail ? 1 : 0);
