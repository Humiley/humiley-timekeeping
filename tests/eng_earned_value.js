/* Design effort against design progress, tested against the code that ships.
 *
 * The unit trap is the whole point. A weight of 40 might be forty manhours or forty points of
 * relative size. EV/AC is a cost index only in the first case; in the second it is a ratio of
 * unlike things that renders as a confident 0.8 and means nothing. These tests exist mostly to
 * prove the function REFUSES in that case rather than obliging.
 *
 *   node tests/eng_earned_value.js
 */
const fs = require('fs');
const path = require('path');

const src = fs.readFileSync(path.join(__dirname, '..', 'templates', 'index.html'), 'utf8');
const START = '/* ── ENG EARNED VALUE ──', END = '/* ── END ENG EARNED VALUE ── */';
const i = src.indexOf(START), j = src.indexOf(END);
if (i < 0 || j < 0 || j <= i) {
  console.error('Could not find the earned-value block in templates/index.html.\n' +
    'If the markers were renamed, update START/END here — do NOT delete this test.');
  process.exit(2);
}
const PRELUDE = `
  const _ENG_CREDIT = [
    { k: 'Not started', pct: 0 }, { k: 'In progress', pct: 30 }, { k: 'Internal review', pct: 65 },
    { k: 'Issued', pct: 90 }, { k: 'Approved', pct: 100 }
  ];
`;
const api = {};
new Function(PRELUDE + src.slice(i, j) + `Object.assign(this, { _engEV });`).call(api);
const { _engEV } = api;

let pass = 0, fail = 0;
function t(name, fn) {
  try { fn(); console.log('  ok    ' + name); pass++; }
  catch (e) { console.log('  FAIL  ' + name + '\n        ' + e.message); fail++; }
}
const eq = (a, b, m) => { if (a !== b) throw new Error((m || '') + ' expected ' + JSON.stringify(b) + ', got ' + JSON.stringify(a)); };
const near = (a, b, m) => { if (a == null || Math.abs(a - b) > 1e-9) throw new Error((m || '') + ' expected ~' + b + ', got ' + a); };

const HOURS = { weightUnit: 'Manhours' };
const POINTS = { weightUnit: 'Points' };
const TODAY = '2026-08-22';
const D = (o) => Object.assign({ id: 'd1', weight: 100, creditStatus: 'Not started' }, o);
const L = (o) => Object.assign({ id: 'l1', deliverableId: 'd1', hours: 10 }, o);

console.log('\nthe arithmetic');
t('earned value is weight times the rule of credit', () => {
  const r = _engEV(HOURS, [D({ creditStatus: 'Internal review' })], [], TODAY);
  near(r.ev, 65, 'EV:'); near(r.bac, 100, 'BAC:');
});
t('a missing weight counts as one, never as zero', () => {
  const r = _engEV(HOURS, [D({ weight: undefined, creditStatus: 'Approved' })], [], TODAY);
  near(r.bac, 1); near(r.ev, 1);
});
t('a nonsense weight does not poison the total', () => {
  const r = _engEV(HOURS, [D({ weight: 'abc', creditStatus: 'Approved' })], [], TODAY);
  near(r.bac, 1);
});
t('actual cost is the hours booked', () => {
  const r = _engEV(HOURS, [D()], [L({ hours: 10 }), L({ id: 'l2', hours: 5.5 })], TODAY);
  near(r.ac, 15.5);
});
t('planned value steps at the planned issue date', () => {
  const past = _engEV(HOURS, [D({ plannedIssue: '2026-08-01' })], [], TODAY);
  const future = _engEV(HOURS, [D({ plannedIssue: '2026-12-01' })], [], TODAY);
  near(past.pv, 100, 'due already:'); near(future.pv, 0, 'not due yet:');
});
t('SPI is earned over planned', () => {
  const r = _engEV(HOURS, [D({ plannedIssue: '2026-08-01', creditStatus: 'Internal review' })], [], TODAY);
  near(r.spi, 0.65);
});

console.log('\nthe unit trap');
t('CPI is refused when the weights are not hours', () => {
  const r = _engEV(POINTS, [D({ creditStatus: 'Approved' })], [L({ hours: 50 })], TODAY);
  eq(r.cpi, null, 'points cannot divide into hours:');
  if (!/unit/i.test(r.whyNoCpi)) throw new Error('the reason should name the unit problem, got: ' + r.whyNoCpi);
});
t('CPI is refused when the commission says nothing about units', () => {
  const r = _engEV({}, [D({ creditStatus: 'Approved' })], [L({ hours: 50 })], TODAY);
  eq(r.cpi, null, 'silence is not permission:');
});
t('CPI is computed when the weights ARE hours', () => {
  const r = _engEV(HOURS, [D({ weight: 100, creditStatus: 'Approved' })], [L({ hours: 80 })], TODAY);
  near(r.cpi, 1.25, 'earned 100h for 80h spent:');
});
t('CPI is refused rather than infinite when nothing was booked', () => {
  const r = _engEV(HOURS, [D({ creditStatus: 'Approved' })], [], TODAY);
  eq(r.cpi, null); if (!r.whyNoCpi) throw new Error('should say why');
});
t('CPI is refused rather than zero when nothing was earned', () => {
  const r = _engEV(HOURS, [D()], [L({ hours: 40 })], TODAY);
  eq(r.cpi, null, '0/40 would render as a confident 0.00:');
});
t('SPI survives points, because it is weight over weight', () => {
  const r = _engEV(POINTS, [D({ plannedIssue: '2026-08-01', creditStatus: 'Approved' })], [], TODAY);
  near(r.spi, 1);
});
t('SPI is null rather than a divide by zero when nothing is due', () => {
  eq(_engEV(HOURS, [D({ plannedIssue: '2026-12-01' })], [], TODAY).spi, null);
});

console.log('\nwhat it surfaces');
t('hours booked to nothing are counted and reported', () => {
  const r = _engEV(HOURS, [D()], [L({ deliverableId: '', hours: 12 })], TODAY);
  near(r.unbooked, 12);
});
t('a deliverable well past its earned hours is flagged', () => {
  const r = _engEV(HOURS, [D({ weight: 100, creditStatus: 'In progress' })], [L({ hours: 90 })], TODAY);
  eq(r.over.length, 1, '30h earned against 90h spent:');
});
t('a finished deliverable is not flagged however long it took', () => {
  const r = _engEV(HOURS, [D({ weight: 100, creditStatus: 'Approved' })], [L({ hours: 300 })], TODAY);
  eq(r.over.length, 0, 'the overrun is history once it is done:');
});
t('overrun is not guessed at when the unit is points', () => {
  const r = _engEV(POINTS, [D({ weight: 100, creditStatus: 'In progress' })], [L({ hours: 900 })], TODAY);
  eq(r.over.length, 0);
});
t('an empty commission produces zeros and no indices', () => {
  const r = _engEV(HOURS, [], [], TODAY);
  near(r.bac, 0); near(r.ev, 0); near(r.ac, 0); eq(r.spi, null); eq(r.cpi, null);
});

console.log('\n' + pass + ' passed, ' + fail + ' failed');
process.exit(fail ? 1 : 0);
