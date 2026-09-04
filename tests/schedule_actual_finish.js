/* The Timeline's delivery column — Master and Detail, one rule.
 *
 * The Schedule Timeline used to print a VARIANCE verdict ("18d late", "-8%") in a column headed
 * Status. What a site meeting actually asks first is simpler: is this finished, and was it on time.
 * That is the Actual finish column, and it has two states — nothing recorded yet, in which case
 * today is read against the planned window (On plan / On progress / Delay), and a date recorded,
 * in which case the date IS the verdict (green on or before the target finish, red after).
 *
 * Both levels render through the SAME _schTimeline, so this is one rule with two adapters, and the
 * things worth guarding are the ones a screenshot would not show:
 *   - dates are compared zero-padded, so the register's legacy '2026-7-5' is not "after" '2026-07-10';
 *   - a row with no dates at all does not get an invented "On progress";
 *   - a recorded date with no target finish is not painted green — there is nothing to be on time for;
 *   - the header, the row cell and the group-row spacer are three separate widths that must agree;
 *   - both adapters supply `actual`, and a TYPED actual finish outranks the progress log.
 *
 *   node tests/schedule_actual_finish.js
 */
const fs = require('fs');
const path = require('path');

const src = fs.readFileSync(path.join(__dirname, '..', 'templates', 'index.html'), 'utf8');

let pass = 0, fail = 0;
const ok = (n, c, extra) => {
  if (c) { pass++; console.log('  ok    ' + n); }
  else { fail++; console.log('  FAIL  ' + n + (extra ? '\n        ' + extra : '')); }
};
const take = (mark, what, stop) => {
  const i = src.indexOf(mark);
  if (i < 0) { console.error('Could not find ' + what + ' — update the marker, do NOT delete this test.'); process.exit(2); }
  const j = src.indexOf(stop || '\nfunction ', i + 10);
  if (j < 0) { console.error('Could not find the end of ' + what + '.'); process.exit(2); }
  return src.slice(i, j);
};

console.log('\nThe Timeline delivery column\n');

/* ══ 1. the rule ════════════════════════════════════════════════════════════════════════════ */
const api = {};
new Function(
  'function _t2(en, vn){ return en; }' +
  take('function tkFmtDate(', 'tkFmtDate') +
  take('function _schActual(', '_schActual') +
  '\nObject.assign(this, { _schActual });'
).call(api);
const { _schActual } = api;

const A = (r, day) => _schActual(r, day || '2026-09-04');
const BLACK = 'var(--text)', BLUE = '#3168A8', RED = '#EF4444', GREEN = '#00B060';

// --- nothing recorded: today against the planned window -----------------------------------
const win = { start: '2026-09-01', finish: '2026-09-30' };
ok('before the start date it reads On plan, in plain text',
   A(win, '2026-08-31').txt === 'On plan' && A(win, '2026-08-31').hex === BLACK,
   JSON.stringify(A(win, '2026-08-31')));
ok('ON the start date it is already running, not still On plan',
   A(win, '2026-09-01').txt === 'On progress' && A(win, '2026-09-01').hex === BLUE);
ok('inside the window it reads On progress, in blue',
   A(win, '2026-09-15').txt === 'On progress' && A(win, '2026-09-15').hex === BLUE);
ok('ON the finish date it is not yet late',
   A(win, '2026-09-30').txt === 'On progress');
ok('past the finish date it reads Delay, in red',
   A(win, '2026-10-01').txt === 'Delay' && A(win, '2026-10-01').hex === RED);

// --- a date recorded: the date IS the verdict ----------------------------------------------
const done = d => A({ start: '2026-09-01', finish: '2026-09-30', actual: d });
ok('an actual finish before the target prints the date in green',
   done('2026-09-20').txt === 'Sep-20' && done('2026-09-20').hex === GREEN,
   JSON.stringify(done('2026-09-20')));
ok('landing exactly ON the target finish is on time, not late',
   done('2026-09-30').hex === GREEN);
ok('one day after the target is late, in red',
   done('2026-10-01').hex === RED && done('2026-10-01').txt === 'Oct-01');
ok('a recorded date outranks where today sits — a line finished early in a window that has since '
   + 'run out still reads green',
   A({ start: '2026-09-01', finish: '2026-09-30', actual: '2026-09-10' }, '2026-11-20').hex === GREEN);

/* ══ 2. the cases the rule as stated does not cover ═════════════════════════════════════════ */
ok('a row with NO dates says so, instead of being called On progress',
   A({}).txt === '—' && A({}).hex !== BLUE,
   JSON.stringify(A({})));
ok('a row with only a start date, not yet reached, is still On plan',
   A({ start: '2026-12-01' }, '2026-09-04').txt === 'On plan');
ok('a row with only a start date, already passed, is On progress and never Delay',
   A({ start: '2026-01-01' }, '2026-09-04').txt === 'On progress');
ok('a recorded date with NO target finish is shown, but not painted green — there is nothing to '
   + 'be on time for',
   A({ actual: '2026-09-20' }).txt === 'Sep-20' && A({ actual: '2026-09-20' }).hex === BLACK,
   JSON.stringify(A({ actual: '2026-09-20' })));

// The exact defect the calendar shipped with: raw string compare puts '2026-7-5' AFTER '2026-07-10'.
ok('a legacy unpadded actual finish five days EARLY is green, not red',
   A({ finish: '2026-07-10', actual: '2026-7-5' }).hex === GREEN,
   'unpadded dates are being compared raw — ' + JSON.stringify(A({ finish: '2026-07-10', actual: '2026-7-5' })));
ok('and an unpadded one that really is late is still red',
   A({ finish: '2026-07-10', actual: '2026-7-25' }).hex === RED);
ok('an unpadded planned finish does not fake a Delay either',
   A({ start: '2026-09-01', finish: '2026-9-30' }, '2026-09-15').txt === 'On progress',
   JSON.stringify(A({ start: '2026-09-01', finish: '2026-9-30' }, '2026-09-15')));
ok('a date shape this cannot read is still shown, in plain text rather than a false verdict',
   A({ finish: '2026-09-30', actual: 'end of September' }).hex === BLACK);

/* ══ 3. the column is wired into the shared kit, once, for both levels ══════════════════════ */
const tl = take('function _schTimeline(', '_schTimeline', '\nfunction _schCalendar');
ok('the header column is Actual finish, not Status',
   /_t\('Actual finish'\)/.test(tl) && !/_t\('Status'\)/.test(tl));
const widths = [
  (tl.match(/width:' \+ (\w+) \+ 'px;text-align:right;white-space:normal/) || [])[1],           // header
  (tl.match(/cell\('<span title="' \+ _tkEscA\(af\.title\)[\s\S]{0,80}?,\s*(\w+),/) || [])[1],  // row
  (tl.match(/'<span style="width:' \+ (\w+) \+ 'px;flex:none"><\/span>'\) \+ '<\/div>'/) || [])[1], // group spacer
];
ok('the header, the row cell and the group-row spacer are all found',
   widths.every(Boolean), JSON.stringify(widths));
ok('and all three take the SAME width — three separate places that shear the columns apart on '
   + 'the group rows the moment one of them is changed alone',
   new Set(widths).size === 1 && widths[0] === 'AFW', JSON.stringify(widths));
ok('that width is sized for the longest label, which is Vietnamese, not English',
   /const AFW = NARROW \? \d+ : (\d+);/.test(tl) && +tl.match(/const AFW = NARROW \? \d+ : (\d+);/)[1] >= 82,
   (tl.match(/const AFW = [^;]+;/) || [])[0]);
ok('and the cell clips rather than spilling across the Dur column when a label is longer still',
   /af\.hex \+ ';font-weight:700;overflow:hidden;text-overflow:ellipsis'/.test(tl));
ok('the row cell reads the rule, not the variance flag',
   /const af = r \? _schActual\(r, day\) : null;/.test(tl) && !/_schFlag\(r, day\)/.test(tl));
ok('_schFlag survives — it is still what the Behind / Slipping / Overdue chips filter on',
   /_schFlag\(r, day\)\.k !== f\.k/.test(src));

/* ══ 4. both adapters supply it, and a typed date outranks the progress log ═════════════════ */
const dapi = {};
new Function(
  'function _pdLog(r){ return r.log || []; }' +
  'function _pdReadPct(r, e){ return +e.pct || 0; }' +
  'function _pdGroupOf(){ return "G"; }' +
  'function _pdWeight(){ return 1; }' +
  'function _pdAcc(){ return 0; }' +
  'function _pdPlanned(){ return 0; }' +
  take('function _pdNorm(', '_pdNorm') +
  '\nObject.assign(this, { _pdNorm });'
).call(dapi);
const norm = (r) => dapi._pdNorm('p1', [r], '2026-09-04')[0];

ok('a detail line with a typed actual finish carries it',
   norm({ id: 'd1', actualFinish: '2026-09-02' }).actual === '2026-09-02');
ok('a line finished through the daily readings supplies the day it hit 100 — a completed line '
   + 'must never print Delay in red',
   norm({ id: 'd2', log: [{ d: '2026-08-20', pct: 60 }, { d: '2026-08-28', pct: 100 }] }).actual === '2026-08-28');
ok('and a typed date OUTRANKS the log — the site knows the date before the log catches up',
   norm({ id: 'd3', actualFinish: '2026-08-25', log: [{ d: '2026-08-28', pct: 100 }] }).actual === '2026-08-25');
ok('an unfinished line offers nothing, so the column falls through to the planned window',
   norm({ id: 'd4', log: [{ d: '2026-08-20', pct: 60 }] }).actual === '');
ok('doneOn is left alone — it is what _schFlag reads for the early / late verdict',
   norm({ id: 'd5', actualFinish: '2026-08-25', log: [{ d: '2026-08-28', pct: 100 }] }).doneOn === '2026-08-28');

const tasks = [{ id: 't1', wbs: '1', name: 'A', start: '2026-09-01', finish: '2026-09-30',
                 actualFinish: '2026-09-12' },
               { id: 't2', wbs: '2', name: 'B', start: '2026-09-01', finish: '2026-09-30' }];
const mapi = {};
new Function(
  'const __tasks = ' + JSON.stringify(tasks) + ';' +
  'function _pmScopeFor(c, pid){ return __tasks; }' +
  'function _pdTaskPct(){ return null; }' +
  'function _pmTaskPctRoll(){ return { pct: 0, from: "typed" }; }' +
  'function _pmDateDiff(a, b){ return Math.round((Date.parse(b) - Date.parse(a)) / 86400000); }' +
  'function _pmWbsLevel(){ return 1; }' +
  'function _pmWbsCmp(){ return 0; }' +
  'function _pdPlanned(){ return 0; }' +
  'function _t(s){ return s; }' +
  take('function _pmTaskNorm(', '_pmTaskNorm') +
  '\nObject.assign(this, { _pmTaskNorm });'
).call(mapi);
const mrows = mapi._pmTaskNorm('p1', '2026-09-04');
ok('a master activity carries its Actual finish into the same column',
   mrows[0].actual === '2026-09-12');
ok('and one without leaves it blank rather than borrowing the planned finish',
   mrows[1].actual === '');

/* ══ 5. the field the detail form was missing ═══════════════════════════════════════════════ */
const spec = take("  pm_detail: {", 'the pm_detail form spec', '\n  pm_comms: {');
ok('the Detail Schedule Item form offers an editable Actual finish date',
   /\{ k: 'actualFinish', label: 'Actual finish', type: 'date' \}/.test(spec), spec.slice(0, 200));
ok('it sits with the other two dates, not at the end of the form',
   spec.indexOf("k: 'actualFinish'") > spec.indexOf("k: 'finish'") &&
   spec.indexOf("k: 'actualFinish'") < spec.indexOf("k: 'qtyPlan'"));

console.log('\n' + pass + ' passed, ' + fail + ' failed\n');
process.exit(fail ? 1 : 0);
