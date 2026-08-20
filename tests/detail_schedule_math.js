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
  Object.assign(this, { _pdAcc, _pdDaily, _pdPlanned, _pdWeight, _pdRollup, _pdLog, _pdQtyPlan, _pdQtyAt, _pdReadPct });
`).call(api);
const { _pdAcc, _pdDaily, _pdPlanned, _pdWeight, _pdRollup, _pdQtyPlan, _pdQtyAt } = api;

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


// ── quantity-measured progress ───────────────────────────────────────────────────────────────────
// With a scheduled quantity, percent complete stops being a judgement: it is what is installed at
// site over what the schedule says to install. These assert the arithmetic AND the fallbacks,
// because a half-adopted measure is where this kind of thing goes wrong.
const QP = { start: '2026-08-01', finish: '2026-08-31', qtyPlan: 500, unit: 'm' };

t('350 of 500 m is 70%', _pdAcc(Object.assign({}, QP, { log: [{ d: '2026-08-10', pct: 0, qty: 350 }] }), TODAY), 70);
t('the site quantity comes back as measured',
  _pdQtyAt(Object.assign({}, QP, { log: [{ d: '2026-08-10', pct: 0, qty: 350 }] }), TODAY), { q: 350, inferred: false });
t('a quantity beyond the plan is still capped at 100%',
  _pdAcc(Object.assign({}, QP, { log: [{ d: '2026-08-10', pct: 0, qty: 900 }] }), TODAY), 100);
t('the daily figure is the measured increment', _pdDaily(Object.assign({}, QP, {
  log: [{ d: '2026-08-14', pct: 0, qty: 300 }, { d: TODAY, pct: 0, qty: 350 }] }), TODAY), 10);

// mixed history — the reason this decides per READING and not per item
t('readings before a quantity existed keep their percentage', _pdAcc(Object.assign({}, QP, {
  log: [{ d: '2026-08-05', pct: 40 }, { d: '2026-08-10', pct: 0, qty: 350 }] }), '2026-08-05'), 40);
t('...and the measured reading takes over once it arrives', _pdAcc(Object.assign({}, QP, {
  log: [{ d: '2026-08-05', pct: 40 }, { d: '2026-08-10', pct: 0, qty: 350 }] }), TODAY), 70);

// no quantity: the judged path must be untouched
t('no scheduled quantity -> the typed percentage still rules',
  _pdAcc({ start: '2026-08-01', finish: '2026-08-31', log: [{ d: '2026-08-10', pct: 62 }] }, TODAY), 62);
t('a zero or blank quantity is not a quantity', _pdQtyPlan({ qtyPlan: 0 }) + _pdQtyPlan({ qtyPlan: '' }) + _pdQtyPlan({}), 0);
t('a negative scheduled quantity is refused', _pdQtyPlan({ qtyPlan: -50 }), 0);
t('an inferred site figure is flagged as inferred', _pdQtyAt(Object.assign({}, QP, {
  log: [{ d: '2026-08-10', pct: 50 }] }), TODAY), { q: 250, inferred: true });
t('a quantity of exactly zero is a real measurement, not "nothing filed"',
  _pdQtyAt(Object.assign({}, QP, { log: [{ d: '2026-08-10', pct: 0, qty: 0 }] }), TODAY), { q: 0, inferred: false });

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


/* ── the register's HEADER SHAPE ─────────────────────────────────────────────────────────────────
 *
 * Every defect this feature produced was invisible to the checks above: a hidden pane, a header
 * translated only as far as its first text node, a column count that stopped matching its rows.
 * `node --check` cannot see any of it and neither can the arithmetic tests, so the only thing that
 * ever caught them was opening the page — which is not something CI can do.
 *
 * This renders _pdRegister from the shipping file and checks the three properties a person would
 * check by looking: the header spans as many columns as the rows do, the two header rows agree, and
 * no header cell is split into fragments the DOM-walk translator would half-translate.
 */
const REG_START = 'function _pdRegister(', REG_END = '\nfunction _pdKpiRowFor';
const ri = src.indexOf(REG_START);
let rj = src.indexOf('\nfunction ', ri + 10);
if (ri < 0 || rj < 0) {
  console.error('Could not find _pdRegister in templates/index.html — update the markers, do NOT delete this test.');
  process.exit(2);
}
const regStubs = `
  const _PD_COLL = 'pm_detail';
  const _pdCol = {};
  const TK = { user: { role: 'manager' } };
  function _t(s){ return s; }
  function _tkEscA(s){ return String(s).replace(/"/g, '&quot;'); }
  function _pmEsc(s){ return String(s == null ? '' : s); }
  function _pmPct(v){ return Math.max(0, Math.min(100, Math.round(+v || 0))); }
  function tkFmtDate(d){ return String(d || ''); }
  function _pdGroupOf(pid, r){ return r.group; }
  function _pdRollup(rows, day){ return { acc: 50, planned: 40, variance: 10 }; }
  function _pdAcc(){ return 50; } function _pdDaily(){ return 5; } function _pdPlanned(){ return 40; }
  function _pdLog(r){ return r.log || []; }
  function _pdQtyPlan(r){ return +r.qtyPlan || 0; }
  function _pdQtyAt(r){ return { q: +r.qtyAt || 0, inferred: !!r.inferred }; }
  function _pdVarColor(){ return '#000'; } function _pdVarLabel(){ return 'x'; }
  function _pmCard(title, coll, add, table, extra){ return table; }
`;
const reg = {};
new Function(regStubs + src.slice(ri, rj) + '\n Object.assign(this, { _pdRegister });').call(reg);

const ROWS = [
  { id: 'A', group: 'G1', name: 'Duct run', qtyPlan: 240, qtyAt: 96, unit: 'm',
    log: [{ d: '2026-08-15', qty: 96 }], start: '2026-08-01', finish: '2026-08-20' },
  { id: 'B', group: 'G1', name: 'No quantity here', log: [] },
];
const html = reg._pdRegister('P1', ROWS, ['G1'], '2026-08-15');

const spans = (tr) => (tr.match(/<t[hd][^>]*>/g) || [])
  .reduce((n, tag) => n + (+(tag.match(/colspan="(\d+)"/) || [0, 1])[1] || 1), 0);
const between = (s, a, b) => s.slice(s.indexOf(a) + a.length, s.indexOf(b));
const headRows = between(html, '<thead>', '</thead>').split('<tr').slice(1);
const bodyRows = between(html, '<tbody>', '</tbody>').split('<tr').slice(1);

t('the header spans twelve columns', spans(headRows[0]), 12);
t('the second header row fills the nine non-spanning columns', (headRows[1].match(/<th/g) || []).length, 9);
t('every body row spans exactly twelve columns', [...new Set(bodyRows.map(spans))], [12]);
t('no header cell is split by a <br>', /<th[^>]*>[^<]*<br/.test(headRows.join('')), false);
t('the group header carries the measured block rule', /colspan="3"[^>]*border-left/.test(headRows[0]), true);
t('the unit datalist is offered', html.indexOf('<datalist id="pd-units">') > -1, true);
t('a measured line locks its scheduled quantity', html.indexOf('&#128274;') > -1, true);

console.log('\n' + pass + ' passed, ' + fail + ' failed');
process.exit(fail ? 1 : 0);
