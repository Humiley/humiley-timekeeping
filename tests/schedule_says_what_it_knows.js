/* Four schedule readings that were confident about things they had not looked at.
 *
 *  - CPM seeded every early start at project day 0, so an activity connected to nothing still got a
 *    Float figure and could wear the red CP badge. A task's own start date was never read as a
 *    constraint; it was used only to derive a duration.
 *  - A detail line with no dates scored variance 0 and flagged green "On plan" — forever. Undated
 *    lines are routine: the importer writes `start: r.start || ''`.
 *  - Every timeline bar was drawn one day short, because the axis maps a date to the START of that
 *    day, and a same-day item — which is what a milestone is — came out 0% wide and vanished.
 *  - The completion date was read off a reading's raw `pct` while every other consumer resolves the
 *    reading through _pdReadPct, so after a scheduled-quantity revision the early/late verdict
 *    disappeared from a line that had finished.
 *
 *   node tests/schedule_says_what_it_knows.js
 */
const fs = require('fs');
const path = require('path');

const src = fs.readFileSync(path.join(__dirname, '..', 'templates', 'index.html'), 'utf8');

let pass = 0, fail = 0;
const ok = (n, c, extra) => {
  if (c) { pass++; console.log('  ok    ' + n); }
  else { fail++; console.log('  FAIL  ' + n + (extra ? '\n        ' + extra : '')); }
};

const code = src
  .replace(/\/\*[\s\S]*?\*\//g, '')
  .replace(/<!--[\s\S]*?-->/g, '')
  .replace(/(^|[^:])\/\/.*$/gm, '$1');

const take = (mark, what, stop) => {
  const i = src.indexOf(mark);
  if (i < 0) { console.error('Could not find ' + what + ' — update the marker, do NOT delete this test.'); process.exit(2); }
  const j = src.indexOf(stop || '\nfunction ', i + 10);
  if (j < 0) { console.error('Could not find the end of ' + what + '.'); process.exit(2); }
  return src.slice(i, j);
};

console.log('\nA schedule that says what it knows\n');

/* ══ 1. CPM: a start date is a constraint, and an unconnected task is on no path ═════════════ */
const api = {};
new Function(
  'function _pmDateDiff(a,b){ return Math.round((Date.parse(b) - Date.parse(a)) / 86400000); }' +
  take('function _pmCPMCompute(', '_pmCPMCompute') +
  '\nObject.assign(this, { _pmCPMCompute });'
).call(api);
const { _pmCPMCompute } = api;

// Two activities, three months apart, neither connected to anything.
const loose = _pmCPMCompute([
  { id: 'A', wbs: '1', start: '2026-01-01', finish: '2026-01-10' },
  { id: 'B', wbs: '2', start: '2026-04-01', finish: '2026-04-10' },
]);
ok('a task that starts in April does not begin on project day 0',
   loose.map.B.es > 0,
   'es was ' + loose.map.B.es + ' — the whole network was collapsed onto day one');
ok('the offset is the real gap between the two starts',
   loose.map.B.es === 90 && loose.map.A.es === 0);
ok('a task connected to nothing is not reported as being in the network',
   loose.map.A.inNet === false && loose.map.B.inNet === false);
ok('and is therefore never badged critical',
   loose.map.A.critical === false && loose.map.B.critical === false,
   'CP means "on the critical path"; an activity on no path cannot be on that one');

// A real chain: B follows A, C follows B, and D hangs off on its own.
const chain = _pmCPMCompute([
  { id: 'A', wbs: '1', start: '2026-01-01', finish: '2026-01-10' },
  { id: 'B', wbs: '2', start: '2026-01-01', finish: '2026-01-05', predecessors: '1' },
  { id: 'C', wbs: '3', start: '2026-01-01', finish: '2026-01-20', predecessors: '2' },
  { id: 'D', wbs: '4', start: '2026-02-01', finish: '2026-02-02' },
]);
ok('a linked network still computes', chain.hasDeps === true);
ok('successors still follow their predecessor', chain.map.B.es >= chain.map.A.ef);
ok('the chain IS in the network', chain.map.A.inNet && chain.map.B.inNet && chain.map.C.inNet);
ok('the chain is critical and the loose task beside it is not',
   chain.map.C.critical === true && chain.map.D.critical === false,
   'if D is critical here the fix has not taken');
// The whole point of `snet` is the MAX of a predecessor's early finish and the task's own start.
// The first version of this asserted `es === snet` on task D — which has no predecessors, so both
// sides collapse to the same value by construction and the assertion passed on the buggy code too.
// It has to be a task that HAS a predecessor and a start date LATER than that predecessor's finish.
const constrained = _pmCPMCompute([
  { id: 'A', wbs: '1', start: '2026-01-01', finish: '2026-01-10' },
  // E follows A (which finishes on day 9) but is not allowed to start until 1 March — day 59.
  { id: 'E', wbs: '2', start: '2026-03-01', finish: '2026-03-05', predecessors: '1' },
  // F follows A and starts the day after it: here the PREDECESSOR is the binding constraint.
  { id: 'F', wbs: '3', start: '2026-01-02', finish: '2026-01-20', predecessors: '1' },
]);
ok('a start date LATER than the predecessor wins',
   constrained.map.E.es === constrained.map.E.snet && constrained.map.E.es === 59,
   'es was ' + constrained.map.E.es + ', snet ' + constrained.map.E.snet + ' — expected both 59');
ok('and a predecessor LATER than the start date wins',
   constrained.map.F.es === constrained.map.A.ef && constrained.map.F.es > constrained.map.F.snet,
   'es ' + constrained.map.F.es + ', snet ' + constrained.map.F.snet + ', A.ef ' + constrained.map.A.ef);
ok('so the early start is the later of the two, never just one of them',
   constrained.map.E.es === Math.max(constrained.map.E.snet, constrained.map.A.ef) &&
   constrained.map.F.es === Math.max(constrained.map.F.snet, constrained.map.A.ef));

// the Float column reads the flag rather than printing a number for everything
ok('the Float column shows nothing where there is no network position',
   /cpm\.map\[r\.id\] && cpm\.map\[r\.id\]\.inNet/.test(code),
   'a confident "0d" on an unconnected activity is the thing being fixed');
ok('and it says why, where somebody can read it',
   /it is in no network, so it has no float to report/.test(src));

/* ══ 2. an undated line is not "on plan" ════════════════════════════════════════════════════ */
const pd = {};
const PD_START = 'const _PD_COLL =', PD_END = '/* ── the report table';
const a = src.indexOf(PD_START), b = src.indexOf(PD_END);
if (a < 0 || b < 0) { console.error('Could not find the Detail Schedule block.'); process.exit(2); }
new Function(
  'function _pmPct(v){ return Math.max(0, Math.min(100, Math.round(+v || 0))); }' +
  'function _pmDateDiff(a,b){ return Math.round((Date.parse(b) - Date.parse(a)) / 86400000); }' +
  "function _pmToday(){ return '2026-08-15'; }" +
  'function _pmScopeFor(){ return []; }' +
  src.slice(a, b) +
  '\nObject.assign(this, { _pdHasPlan, _pdPlanned, _pdRollup, _pdReadPct, _pdAcc });'
).call(pd);

ok('a row with no dates has no plan', pd._pdHasPlan({ start: '', finish: '' }) === false);
ok('a row with one date has no plan either', pd._pdHasPlan({ start: '2026-08-01', finish: '' }) === false);
ok('a fully dated row does', pd._pdHasPlan({ start: '2026-08-01', finish: '2026-08-30' }) === true);

ok('the status band gives an unplannable row its own verdict',
   /if \(!_pdHasPlan\(r\)\) \{/.test(code) && /k: 'undated'/.test(code));
ok('and it is reached BEFORE the variance verdict',
   code.indexOf("k: 'undated'") < code.indexOf("if (v >= 5) return { k: 'ahead'"),
   'placed after, an undated row falls through to "On plan" exactly as before');
// A row with ONE date is drawn on the timeline as a diamond at that date, so labelling it
// "No dates" beside a mark on the chart was a contradiction the reader had to resolve.
ok('a row with one date is told apart from a row with none',
   /_t\('One date only'\)/.test(code) && /_t\('No dates'\)/.test(code));
ok('and the timeline draws exactly the rows the band calls one-date',
   /const one = r\.start \|\| r\.finish;/.test(code),
   'the band and the chart have to agree about which rows have a position');

// ── the variance columns the undated fix originally stopped short of ─────────────────────────────
ok('the register line variance is gated on the row having a plan',
   /_pdHasPlan\(r\) \? _pdVarColor\(v\) : 'var\(--text-light\)'/.test(code),
   'the register is the table exported to the client');
ok('the register group variance is gated on the roll-up having measured anything',
   /roll\.measured \? _pdVarColor\(roll\.variance\)/.test(code));
ok('and the KPI row is too',
   /all\.measured \? _pdVarColor\(all\.variance\)/.test(code));
ok('the board no longer defaults an unmatched row into the On plan column',
   !/\(COLS\.find\(c => c\.hit\(a, p\)\) \|\| COLS\[2\]\)\.k/.test(code),
   'COLS[2] was On plan — the default WAS the bug');
ok('the board has a column for it',
   /\{ k: 'undated',\s+label: 'No dates'/.test(code));

/* ══ 3. the timeline covers whole days, and a point in time is drawn ════════════════════════ */
ok('the axis runs to the day AFTER the last one',
   /const axEnd = _pmDateAdd\(max, 1\)/.test(code) &&
   /const span = Math\.max\(1, _pmDateDiff\(min, axEnd\)/.test(code));
ok('a bar ends at the END of the day it finishes on',
   /const a = pct\(r\.start\), b = pctEnd\(r\.finish\)/.test(code));
ok('the month band reaches the extended end, so the last month is not clipped',
   /pct\(last > axEnd \? axEnd : last\)/.test(code));
ok('the month loop covers it too',
   /const end = new Date\(\+axEnd\.slice\(0, 4\)/.test(code),
   'stopping at `max` drops the final month when the axis runs past it');
ok('a same-day item is drawn as a mark instead of a zero-width bar',
   /if \(!r\.start \|\| !r\.finish \|\| r\.start === r\.finish\)/.test(code) &&
   /transform:rotate\(45deg\)/.test(code));
ok('a row with only one date still appears',
   /const one = r\.start \|\| r\.finish;/.test(code) && /if \(!one\) return '';/.test(code),
   'it used to return empty for anything missing either date');

/* ══ 4. one way to read a reading ═══════════════════════════════════════════════════════════ */
ok('the completion date resolves the reading the same way everything else does',
   /const doneRow = log\.find\(e => _pdReadPct\(r, e\) >= 100\)/.test(code));
ok('it no longer reads the frozen raw percentage',
   !/const doneRow = log\.find\(e => _pmPct\(e\.pct\) >= 100\)/.test(code));

// and prove the two actually differ, so the fix is not cosmetic.
// The first version of this asserted BOTH were 100 — i.e. that they AGREE — under a name saying they
// disagree, and it could not fail because _pmPct clamps at 100. The case that matters is a revision
// that RAISES the scheduled quantity: the frozen pct still says 100 while the resolved reading does
// not, which is precisely when _pdNorm used to declare a line finished that was not.
const raised = { qtyPlan: 200, log: [{ d: '2026-08-01', qty: 100, pct: 100 }] };
ok('after a quantity revision the raw pct and the resolved one disagree',
   raised.log[0].pct === 100 && pd._pdReadPct(raised, raised.log[0]) === 50,
   'raw ' + raised.log[0].pct + ' vs resolved ' + pd._pdReadPct(raised, raised.log[0]));
const halved = { qtyPlan: 200, log: [{ d: '2026-08-01', qty: 100, pct: 100 }] };
ok('and a revision that DOUBLES the scope makes the resolved reading fall below 100',
   pd._pdReadPct(halved, halved.log[0]) === 50,
   'if these are equal the two readings never differ and the fix changes nothing');

console.log('\n' + pass + ' passed, ' + fail + ' failed\n');
process.exit(fail ? 1 : 0);
