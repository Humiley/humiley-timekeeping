/* The Detail Schedule's arithmetic, tested against the code that actually ships.
 *
 * The helpers live inside templates/index.html (no build step, no modules), so this extracts the
 * block between two markers and evaluates it with the handful of PM utilities it depends on stubbed.
 * Extracting rather than copying is the point: a copy would keep passing after the real code drifted.
 *
 *   node tests/detail_schedule_math.js
 */
const fs = require('fs');
const path = require('path');

const src = fs.readFileSync(path.join(__dirname, '..', 'templates', 'index.html'), 'utf8');
const START = 'const _PD_COLL =', END = '/* ── the report table';
const i = src.indexOf(START), j = src.indexOf(END);
if (i < 0 || j < 0 || j <= i) {
  console.error('Could not find the Detail Schedule block in templates/index.html.\n' +
    'If it was renamed, update START/END here — do NOT delete this test.');
  process.exit(2);
}

const PRELUDE = `
  function _pmPct(v){ return Math.max(0, Math.min(100, Math.round(+v || 0))); }
  function _pmDateDiff(a,b){ return Math.round((Date.parse(b) - Date.parse(a)) / 86400000); }
  function _pmToday(){ return '2026-08-15'; }
  function _pmScopeFor(){ return []; }
`;
const api = {};
new Function(PRELUDE + src.slice(i, j) + `
  Object.assign(this, { _pdAcc, _pdDaily, _pdPlanned, _pdWeight, _pdRollup, _pdLog });
`).call(api);
const { _pdAcc, _pdDaily, _pdPlanned, _pdWeight, _pdRollup } = api;

let pass = 0, fail = 0;
const t = (name, got, want) => {
  const ok = JSON.stringify(got) === JSON.stringify(want);
  ok ? pass++ : fail++;
  console.log((ok ? '  ok  ' : '  FAIL') + '  ' + name +
    (ok ? '' : '\n         got ' + JSON.stringify(got) + '  want ' + JSON.stringify(want)));
};

const TODAY = '2026-08-15';

// ── the failure these two columns exist to prevent ───────────────────────────────────────────────
// On paper, "Daily Progress" is whatever was written last time and it never goes back to zero, so a
// stalled item keeps advertising yesterday's effort. Daily is derived from the log, by date.
const idle = { start: '2026-06-21', finish: '2026-09-15', log: [{ d: '2026-08-12', pct: 88 }] };
t('nothing reported today -> daily is 0', _pdDaily(idle, TODAY), 0);
t('...but accumulated still reads 88%', _pdAcc(idle, TODAY), 88);

const live = { start: '2026-08-04', finish: '2026-08-15', log: [{ d: '2026-08-14', pct: 90 }, { d: '2026-08-15', pct: 95 }] };
t('reported today -> daily is the increment', _pdDaily(live, TODAY), 5);
t('reported today -> accumulated is the total', _pdAcc(live, TODAY), 95);
t('asking about an earlier day does not leak the future', _pdAcc(live, '2026-08-14'), 90);
t('before the first reading', _pdAcc(live, '2026-08-01'), 0);

// ── planned: straight line, both ends inclusive ──────────────────────────────────────────────────
const pl = { start: '2026-08-11', finish: '2026-08-25' };
t('planned before start', _pdPlanned(pl, '2026-08-01'), 0);
t('planned on day 1 of 15', _pdPlanned(pl, '2026-08-11'), 7);
t('planned on the finish date is 100', _pdPlanned(pl, '2026-08-25'), 100);
t('planned after finish stays 100', _pdPlanned(pl, '2026-09-01'), 100);

// ── weighting: the reason a roll-up is not an average ────────────────────────────────────────────
const short = { start: '2026-08-14', finish: '2026-08-15', log: [{ d: TODAY, pct: 100 }] };  // 2 days
const long_ = { start: '2026-06-17', finish: '2026-08-15', log: [{ d: TODAY, pct: 0 }] };    // 60 days
t('a finished 2-day item does not drag a 60-day item to 50%',
  Math.round(_pdRollup([short, long_], TODAY).acc), 3);
t('an explicit weight overrides duration', Math.round(_pdRollup([
  { start: '2026-08-14', finish: '2026-08-15', weight: 90, log: [{ d: TODAY, pct: 100 }] },
  { start: '2026-06-17', finish: '2026-08-15', weight: 10, log: [{ d: TODAY, pct: 0 }] }], TODAY).acc), 90);
t('an empty roll-up is zero, never NaN', _pdRollup([], TODAY), { acc: 0, planned: 0, variance: 0, weight: 0 });

// ── this is user data; it arrives malformed ──────────────────────────────────────────────────────
t('no log at all', _pdAcc({ start: '2026-08-01', finish: '2026-08-10' }, TODAY), 0);
t('log is not an array', _pdAcc({ log: 'nonsense' }, TODAY), 0);
t('entries with no date are ignored', _pdAcc({ log: [{ pct: 50 }] }, TODAY), 0);
t('a percentage over 100 is clamped', _pdAcc({ log: [{ d: TODAY, pct: 9999 }] }, TODAY), 100);
t('an item with no dates still has a weight', _pdWeight({}), 1);
t('readings filed out of order are sorted', _pdAcc({ log: [{ d: '2026-08-15', pct: 95 }, { d: '2026-08-10', pct: 40 }] }, TODAY), 95);


// ── the import parser ────────────────────────────────────────────────────────────────────────────
// It decides what gets written, so its REJECTIONS matter as much as its acceptances. A parser that
// quietly drops a malformed line creates a schedule with holes nobody knows about.
const iStart = src.indexOf('const _PD_IMPORT_COLS'), iEnd = src.indexOf('function pdImportPreview');
if (iStart < 0 || iEnd < 0) { console.error('Could not find the import parser block.'); process.exit(2); }
const imp = {};
new Function('function _t(s){return s;}' + src.slice(iStart, iEnd) + '\n Object.assign(this,{_pdImportParse});').call(imp);
const parse = imp._pdImportParse;

const TAB = (a) => a.join('\t');
t('a clean row', parse(TAB(['HVAC Works', 'Install ceiling support', '2026-08-11', '2026-08-25'])).rows.length, 1);
t('a pasted header row is skipped, not imported',
  parse('Category\tReport Items\tStart Date\tFinish Date\n' + TAB(['HVAC', 'X', '2026-08-11', '2026-08-25'])).rows.length, 1);
t('comma-separated also works', parse('HVAC,Install pipe,2026-08-11,2026-08-25').rows.length, 1);
t('blank lines are ignored', parse('\n\n' + TAB(['HVAC', 'X']) + '\n\n').rows.length, 1);

t('a missing item name is rejected', parse(TAB(['HVAC', ''])).bad.length, 1);
t('a missing category is rejected', parse(TAB(['', 'Install pipe'])).bad.length, 1);
t('a bad start date is rejected', parse(TAB(['HVAC', 'X', '11/08/2026', '2026-08-25'])).bad.length, 1);
t('finish before start is rejected', parse(TAB(['HVAC', 'X', '2026-08-25', '2026-08-11'])).bad.length, 1);
t('a negative weight is rejected', parse(TAB(['HVAC', 'X', '2026-08-11', '2026-08-25', '', '', '-5'])).bad.length, 1);
t('a zero weight is rejected', parse(TAB(['HVAC', 'X', '2026-08-11', '2026-08-25', '', '', '0'])).bad.length, 1);
t('dates are optional', parse(TAB(['HVAC', 'X'])).rows.length, 1);
t('a rejected row does not silently vanish',
  parse(TAB(['HVAC', 'X']) + '\n' + TAB(['', 'no category'])).bad[0].line, 2);
t('good and bad rows are separated, not all-or-nothing', (() => {
  const r = parse(TAB(['HVAC', 'Good']) + '\n' + TAB(['', 'Bad']));
  return r.rows.length + '/' + r.bad.length; })(), '1/1');

console.log('\n' + pass + ' passed, ' + fail + ' failed');
process.exit(fail ? 1 : 0);
