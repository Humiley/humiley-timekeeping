/* The baseline comparison, tested against the code that ships.
 *
 * These four functions decide what a design manager is told about the schedule, and every one of
 * them has a way to be confidently wrong:
 *
 *   - planned-against-baseline must use the baseline's DATES with today's SCOPE, or scope growth
 *     silently deflates SPI and sends somebody hunting a schedule problem that is really a scope
 *     problem;
 *   - "dates moved" must not swallow deliverables ADDED since the baseline, or a commission that
 *     doubled in size reports as one whose dates all slipped;
 *   - a deliverable that had no date then and has one now is not a movement, and one that was
 *     cancelled is not still planned;
 *   - and with no baseline at all, every one of them must return "not measured" rather than a
 *     number, because a number here would be read as a finding.
 *
 *   node tests/eng_baseline_drift.js
 */
const fs = require('fs');
const path = require('path');

const src = fs.readFileSync(path.join(__dirname, '..', 'templates', 'index.html'), 'utf8');
const START = '/* ── ENG BASELINE ──', END = '/* ── END ENG BASELINE ── */';
const i = src.indexOf(START), j = src.indexOf(END);
if (i < 0 || j < 0 || j <= i) {
  console.error('Could not find the baseline block in templates/index.html.\n' +
    'If the markers were renamed, update START/END here — do NOT delete this test.');
  process.exit(2);
}

/* _engProgress and _engInScope come from elsewhere in the file; stubbed to something simple and
   predictable so the assertions below are about the baseline maths and nothing else. */
const PRELUDE = `
  function _engToday(){ return '2026-08-29'; }
  function _engInScope(d){ return String(d.creditStatus || '') !== 'Cancelled'; }
  function _engProgress(rows){
    let w = 0, e = 0;
    (rows || []).forEach(function (d) {
      if (!_engInScope(d)) return;
      const ww = Math.max(0, +d.weight || 0) || 1;
      w += ww; e += ww * (+d.credit || 0);
    });
    return { pct: w ? e / w : 0, wsum: w };
  }
`;
const api = {};
new Function(PRELUDE + src.slice(i, j) + `
  Object.assign(this, { _engBaselineOf, _engBaselinePlanned, _engBaselineSpi, _engBaselineDrift });
`).call(api);
const { _engBaselineOf, _engBaselinePlanned, _engBaselineSpi, _engBaselineDrift } = api;

let pass = 0, fail = 0;
function t(name, fn) {
  try { fn(); console.log('  ok    ' + name); pass++; }
  catch (e) { console.log('  FAIL  ' + name + '\n        ' + e.message); fail++; }
}
const eq = (a, b, m) => { if (a !== b) throw new Error((m || '') + ' expected ' + JSON.stringify(b) + ', got ' + JSON.stringify(a)); };
const near = (a, b, m) => { if (a == null || Math.abs(a - b) > 0.01) throw new Error((m || '') + ' expected ~' + b + ', got ' + a); };

const D = (id, planned, o) => Object.assign({ id: id, docNo: id, plannedIssue: planned, weight: 10, credit: 0 }, o || {});
const BL = (lines, o) => Object.assign({ projectId: 'p1', seq: 1, lines: lines }, o || {});
const L = (id, planned) => ({ deliverableId: id, docNo: id, plannedIssue: planned });

console.log('\nwhich baseline governs');
t('the newest, by seq', () => {
  const b = _engBaselineOf('p1', [BL([], { seq: 1 }), BL([], { seq: 3 }), BL([], { seq: 2 })]);
  eq(b.seq, 3);
});
t('only this commission’s', () => {
  const b = _engBaselineOf('p1', [BL([], { seq: 9, projectId: 'other' }), BL([], { seq: 1 })]);
  eq(b.seq, 1);
});
t('none is null, not an empty baseline', () => {
  eq(_engBaselineOf('p1', []), null);
  eq(_engBaselineOf('p1', [BL([], { projectId: 'other' })]), null);
});

console.log('\nplanned against the baseline');
t('two of four dates due, planned is 50%', () => {
  const rows = [D('a', '2026-08-01'), D('b', '2026-08-02'), D('c', '2026-12-01'), D('d', '2026-12-02')];
  const bl = BL([L('a', '2026-08-01'), L('b', '2026-08-02'), L('c', '2026-12-01'), L('d', '2026-12-02')]);
  near(_engBaselinePlanned(rows, bl).pct, 50);
});
t('the BASELINE date decides, not the current one', () => {
  /* The whole feature in one assertion. The date was due in August and has been pushed to
     December; against the baseline it is still due. */
  const rows = [D('a', '2026-12-31')];
  near(_engBaselinePlanned(rows, BL([L('a', '2026-08-01')])).pct, 100, 'moving the date must not un-plan it');
  near(_engBaselinePlanned(rows, BL([L('a', '2026-12-31')])).pct, 0, 'and a genuinely future date is not due');
});
t('a deliverable added since the baseline is excluded from the comparison', () => {
  const rows = [D('a', '2026-08-01'), D('new', '2026-08-01')];
  const p = _engBaselinePlanned(rows, BL([L('a', '2026-08-01')]));
  eq(p.n, 1, 'compared deliverables');
  near(p.pct, 100, 'the added one must not drag the planned figure');
});
t('coverage says how much of today’s register the comparison covers', () => {
  const rows = [D('a', '2026-08-01'), D('new1', '2026-08-01'), D('new2', '2026-08-01')];
  near(_engBaselinePlanned(rows, BL([L('a', '2026-08-01')])).coverage, 1 / 3);
});
t('a deliverable undated at baseline is not planned against', () => {
  const rows = [D('a', '2026-08-01'), D('b', '2026-08-01')];
  const p = _engBaselinePlanned(rows, BL([L('a', '2026-08-01'), L('b', '')]));
  eq(p.n, 2, 'both are in the baseline');
  near(p.pct, 100, 'but only the dated one is measured, and it is due');
});
t('weights come from TODAY, dates from the baseline', () => {
  /* Mixing a baseline denominator with a live numerator is the classic way to make an index that
     cannot be reconciled with anything. */
  const rows = [D('a', '2026-08-01', { weight: 90 }), D('b', '2026-12-01', { weight: 10 })];
  const bl = BL([L('a', '2026-08-01'), L('b', '2026-12-01')]);
  near(_engBaselinePlanned(rows, bl).pct, 90);
});
t('no baseline is "not measured", never a number', () => {
  const rows = [D('a', '2026-08-01')];
  eq(_engBaselinePlanned(rows, null).pct, null);
  eq(_engBaselinePlanned(rows, BL([])).pct, null);
  eq(_engBaselineSpi(rows, null), null);
});
t('a cancelled deliverable is out of the comparison', () => {
  const rows = [D('a', '2026-08-01'), D('b', '2026-08-01', { creditStatus: 'Cancelled' })];
  eq(_engBaselinePlanned(rows, BL([L('a', '2026-08-01'), L('b', '2026-08-01')])).n, 1);
});

console.log('\nSPI against the baseline');
t('earned 50 against planned 100 is 0.50', () => {
  const rows = [D('a', '2026-08-01', { credit: 100 }), D('b', '2026-08-01', { credit: 0 })];
  near(_engBaselineSpi(rows, BL([L('a', '2026-08-01'), L('b', '2026-08-01')])), 0.5);
});
t('and the number moving the dates would have produced is different', () => {
  /* Same work done. Push the outstanding drawing into next year and the live-plan SPI reads 1.00
     while the baseline SPI still reads 0.50 — which is the gap the screen has to show. */
  const rows = [D('a', '2026-08-01', { credit: 100 }), D('b', '2027-06-01', { credit: 0 })];
  near(_engBaselineSpi(rows, BL([L('a', '2026-08-01'), L('b', '2026-08-01')])), 0.5,
    'the baseline must be unmoved by the edit');
});

console.log('\ndates moved, and the four things that are not that');
t('a slipped date is counted with its direction and size', () => {
  const dr = _engBaselineDrift([D('a', '2026-09-30')], BL([L('a', '2026-08-31')]));
  eq(dr.moved.length, 1);
  eq(dr.moved[0].days, 30);
  eq(dr.daysLater, 30);
  eq(dr.daysEarlier, 0);
});
t('a date pulled forward is counted separately, not netted off', () => {
  const dr = _engBaselineDrift([D('a', '2026-09-30'), D('b', '2026-08-01')],
    BL([L('a', '2026-08-31'), L('b', '2026-08-31')]));
  eq(dr.daysLater, 30);
  eq(dr.daysEarlier, 30);
  eq(dr.moved.length, 2, 'netting these to zero would report a stable plan');
});
t('an unchanged date is not a movement', () => {
  eq(_engBaselineDrift([D('a', '2026-08-31')], BL([L('a', '2026-08-31')])).moved.length, 0);
});
t('added since the baseline is scope, not slippage', () => {
  const dr = _engBaselineDrift([D('a', '2026-08-31'), D('new', '2026-10-01')], BL([L('a', '2026-08-31')]));
  eq(dr.moved.length, 0);
  eq(dr.added.length, 1);
  eq(dr.added[0].d.id, 'new');
});
t('undated then, dated now, is planning — not a moved date', () => {
  const dr = _engBaselineDrift([D('a', '2026-10-01')], BL([L('a', '')]));
  eq(dr.moved.length, 0);
  eq(dr.dated.length, 1);
});
t('dated then, undated now, is a date REMOVED and says so', () => {
  const dr = _engBaselineDrift([D('a', '')], BL([L('a', '2026-10-01')]));
  eq(dr.moved.length, 0);
  eq(dr.undated.length, 1, 'deleting a date must not read as "no change"');
});
t('gone from the register is reported as gone', () => {
  const dr = _engBaselineDrift([], BL([L('a', '2026-10-01')]));
  eq(dr.gone.length, 1);
});
t('cancelled counts as gone, not as still planned', () => {
  const dr = _engBaselineDrift([D('a', '2026-10-01', { creditStatus: 'Cancelled' })],
    BL([L('a', '2026-10-01')]));
  eq(dr.gone.length, 1, 'a cancelled deliverable left in the plan is work nobody will ever do');
  eq(dr.moved.length, 0);
});
t('the biggest slip sorts first', () => {
  const dr = _engBaselineDrift(
    [D('a', '2026-09-05'), D('b', '2026-11-30'), D('c', '2026-09-10')],
    BL([L('a', '2026-09-01'), L('b', '2026-09-01'), L('c', '2026-09-01')]));
  eq(dr.moved[0].d.id, 'b');
});
t('no baseline yields empty lists, not a crash', () => {
  const dr = _engBaselineDrift([D('a', '2026-09-05')], null);
  eq(dr.moved.length, 0); eq(dr.added.length, 0); eq(dr.gone.length, 0);
});
t('an unparseable date is not counted as a movement', () => {
  const dr = _engBaselineDrift([D('a', 'not a date')], BL([L('a', '2026-09-01')]));
  eq(dr.moved.length, 0, 'NaN days would print as "NaN days later"');
});

console.log('\n' + pass + ' passed, ' + fail + ' failed');
process.exit(fail ? 1 : 0);
