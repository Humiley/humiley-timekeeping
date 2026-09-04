/* Both S-curves draw the same picture, in one pass over the rows instead of one per point.
 *
 * _pdSCurve called _pdRollup once per plotted date, and _pdRollup asks every row for three things:
 * its weight, its accumulated reading, and its planned position. The first two do not depend on the
 * date at all, and the third only ever moves forward — yet every one was recomputed at every point,
 * including _pdLog's filter + slice + SORT of the row's whole reading history.
 *
 * Measured on the shipping code before this change, 400 detail lines x 120 readings over ~800 days
 * (116 sample points): 46,400 _pdLog() calls, 5,568,000 log entries re-sorted, 321,042 date parses,
 * 261 ms of blocked main thread — for ONE render of the pane that is the default at that level and
 * is rebuilt by every _pmReload(), collapsing a group included.
 *
 * _pmSCurve had the same shape one level up: `total` inside the per-point closure, so both baseline
 * dates of every activity were re-parsed at every point (43.7 ms of a 45.5 ms call), plus a full
 * scan of the activity list per baseline row to find a task by id.
 *
 * THE ONLY THING THAT MATTERS HERE IS THAT THE PICTURE DID NOT CHANGE. A faster curve that draws a
 * different line is not an optimisation, it is a new defect with a good benchmark — so the first
 * and largest section compares the new series against _pdRollup point by point, field by field, on
 * a fixture built to contain every shape that makes them disagree: undated rows, quantity-measured
 * readings, a log out of order, readings after the last plotted point, and rows with no log at all.
 *
 *   node tests/scurve_is_one_pass.js
 */
const fs = require('fs');
const path = require('path');

const src = fs.readFileSync(path.join(__dirname, '..', 'templates', 'index.html'), 'utf8');

let pass = 0, fail = 0;
const ok = (n, c, extra) => {
  if (c) { pass++; console.log('  ok    ' + n); }
  else { fail++; console.log('  FAIL  ' + n + (extra ? '\n        ' + extra : '')); }
};

function take(name) {
  const re = new RegExp('\\n(?:const |let |)(?:async )?function ' + name.replace(/\$/g, '\\$') + '\\s*\\(');
  const i = src.search(re);
  if (i < 0) {
    console.error('could not find ' + name + ' — update the marker, do NOT delete this test.');
    process.exit(2);
  }
  const from = i + 1;
  const ends = ['\nfunction ', '\nasync function ', '\nconst ', '\nlet ', '\n/* ']
    .map(m => src.indexOf(m, from + 10)).filter(x => x > 0);
  return src.slice(from, ends.length ? Math.min.apply(null, ends) : from + 6000);
}

const NEEDED = ['_pdLog', '_pdQtyPlan', '_pdReadPct', '_pdAcc', '_pdHasPlan', '_pdPlanned',
                '_pdWeight', '_pdRollup', '_pdSeries', '_pmDateAdd'];
const PRELUDE = `
  const _pmPct = v => Math.max(0, Math.min(100, Math.round(+v || 0)));
  const _pmDateDiff = (a, b) => { if (!a || !b) return null; const d1 = new Date(a), d2 = new Date(b);
    if (isNaN(d1) || isNaN(d2)) return null; return Math.round((d2 - d1) / 86400000); };
  const _pmToday = () => '2026-09-04';
  let LOGCALLS = 0;
`;
const API = new Function(PRELUDE + NEEDED.map(take).join('\n') +
  // Wrapped AFTER the real bodies are in scope, so every caller below — _pdSeries and _pdRollup
  // alike — goes through the counter. A counter that is declared and never installed reads 0 for
  // both sides, which an inequality would have called a pass.
  '\nconst __log0 = _pdLog; _pdLog = function (r) { LOGCALLS++; return __log0(r); };' +
  '\nreturn { _pdSeries, _pdRollup, _pdLog, _pmDateAdd, logCalls: () => LOGCALLS,' +
  '         resetLogCalls: () => { LOGCALLS = 0; } };')();

/* Source scans read the CODE, never the comments beside it. A comment that quotes the line it
   replaced — "this was `all.filter(t => t.id === r.id)`" — makes a naive scan report the defect it
   is documenting as still present. */
const strip = t => t.replace(/\/\*[\s\S]*?\*\//g, '').replace(/^\s*\/\/.*$/gm, '');

// ══ 1. the new series is the old roll-up, point for point ══════════════════════════════════════
console.log('\nThe curve is unchanged\n');
{
  /* Deliberately awkward. Each of these has broken one version of this code:
     · an undated row      — counts towards ACTUAL but has no planned position
     · a qty-measured row  — _pdReadPct grades per READING, not per row
     · a log out of order  — _pdLog sorts; a cursor that trusted input order would drift
     · a reading in the future relative to the last point
     · a row with no log   — the cursor must not run off the end
     · a row with weight   — ₫ weight beside duration weight */
  const rows = [
    { id: 'a', start: '2026-01-01', finish: '2026-06-30', weight: 500,
      log: [{ d: '2026-03-01', pct: 20 }, { d: '2026-02-01', pct: 10 }, { d: '2026-05-01', pct: 75 }] },
    { id: 'b', start: '2026-02-15', finish: '2026-04-15',
      qtyPlan: 500, log: [{ d: '2026-03-10', qty: 125 }, { d: '2026-04-01', pct: 90 }] },
    { id: 'c', log: [{ d: '2026-03-20', pct: 40 }] },                       // undated
    { id: 'd', start: '2026-01-15', finish: '2026-08-31' },                 // no readings at all
    { id: 'e', start: '2026-05-01', finish: '2026-05-31',
      log: [{ d: '2027-01-01', pct: 100 }] },                               // reading after the curve
    { id: 'f', start: '2026-03-01', finish: '2026-03-01', log: [{ d: '2026-03-01', pct: 55 }] },
  ];
  const days = [];
  for (let i = 0; i <= 400; i += 7) days.push(API._pmDateAdd('2026-01-01', i));

  const fresh = API._pdSeries(rows, days);
  const naive = days.map(d => API._pdRollup(rows, d));
  const FIELDS = ['acc', 'planned', 'variance', 'weight', 'plannedWeight', 'undatedWeight',
                  'undatedPct', 'measured'];
  const bad = [];
  days.forEach((d, i) => FIELDS.forEach(k => {
    const A = fresh[i][k], B = naive[i][k];
    const same = (typeof A === 'number' && typeof B === 'number') ? Math.abs(A - B) < 1e-9 : A === B;
    if (!same) bad.push(d + '.' + k + ': one-pass ' + A + ' vs per-point ' + B);
  }));
  ok('every field of every point matches the per-point roll-up', bad.length === 0,
     bad.slice(0, 6).join('\n        ') + (bad.length > 6 ? '\n        …and ' + (bad.length - 6) + ' more' : ''));
  ok('and the fixture actually exercises the curve (some point is mid-progress)',
     fresh.some(p => p.acc > 0 && p.acc < 100) && fresh.some(p => p.planned > 0 && p.planned < 100),
     'a comparison over an all-zero series would agree about nothing');
  ok('including the undated row, which counts towards actual but not towards plan',
     fresh[fresh.length - 1].undatedWeight > 0 && fresh[fresh.length - 1].plannedWeight > 0);

  // A single point must agree too — the cursor must not need a run-up to be right.
  const one = API._pdSeries(rows, ['2026-04-01'])[0];
  const ref = API._pdRollup(rows, '2026-04-01');
  ok('a series of one point equals the roll-up at that point',
     Math.abs(one.acc - ref.acc) < 1e-9 && Math.abs(one.planned - ref.planned) < 1e-9,
     JSON.stringify(one) + ' vs ' + JSON.stringify(ref));
}

// ══ 2. and it costs one pass, not one per point ════════════════════════════════════════════════
console.log('\nThe reading log is read once per row, whatever the span\n');
{
  const rows = [];
  for (let i = 0; i < 40; i++) {
    const log = [];
    for (let k = 0; k < 30; k++) log.push({ d: API._pmDateAdd('2026-01-01', k * 5), pct: k * 3 });
    rows.push({ id: 'r' + i, start: '2026-01-01', finish: '2026-12-31', log: log });
  }
  const days = [];
  for (let i = 0; i <= 360; i += 7) days.push(API._pmDateAdd('2026-01-01', i));

  API.resetLogCalls();
  API._pdSeries(rows, days);
  const oncePer = API.logCalls();

  API.resetLogCalls();
  days.forEach(d => API._pdRollup(rows, d));
  const perPoint = API.logCalls();

  ok('_pdSeries reads each row\'s log exactly once', oncePer === rows.length,
     'got ' + oncePer + ' _pdLog calls for ' + rows.length + ' rows over ' + days.length + ' points');
  ok('where the per-point roll-up read it once per row PER POINT',
     perPoint === rows.length * days.length,
     'got ' + perPoint + ' — if this is no longer true the comparison below means nothing');
  ok('which is the whole saving, and it grows with the span',
     perPoint / oncePer === days.length,
     'ratio ' + (perPoint / oncePer) + ' over ' + days.length + ' points');
  // Stated as a count, not as milliseconds: seconds depend on the machine, and a 4s regression
  // fits comfortably inside a 10s CI timeout on an idle runner. This is the same reason
  // tests/detail_lookup_cost.js counts collection reads.
  ok('a longer span costs the same number of log reads', (() => {
    const longer = [];
    for (let i = 0; i <= 3600; i += 7) longer.push(API._pmDateAdd('2026-01-01', i));
    API.resetLogCalls(); API._pdSeries(rows, longer);
    return API.logCalls() === rows.length;
  })(), 'ten times the points must still be one read per row');
}

// ══ 3. the source no longer holds the per-point call ═══════════════════════════════════════════
console.log('\nThe point loop does not call the roll-up\n');
{
  const i = src.indexOf('function _pdSCurve(');
  const body = src.slice(i, src.indexOf('\n}', src.indexOf('return \'<div class="card"', i)));
  ok('_pdSCurve builds its dates and asks for the series once',
     /_pdSeries\(rows, days\)/.test(body), body.slice(0, 400));
  ok('and no longer calls _pdRollup inside a loop',
     !/for \([^)]*\)[\s\S]{0,120}_pdRollup\(/.test(strip(body)),
     'a per-point roll-up is back in the loop');
  ok('the "now" figures still come from the real roll-up, not from the series',
     /const now = _pdRollup\(rows, day\);/.test(body),
     'that single call is not per-point and reads today, which may sit before the last point');
}

// ══ 4. the master curve, same shape one level up ═══════════════════════════════════════════════
console.log('\nThe master S-curve parses each baseline date once\n');
{
  const i = src.indexOf('function _pmSCurve(');
  const body = src.slice(i, i + 6000);
  ok('the per-row constant is computed outside the per-point closure',
     /const plan = rows\.map\(/.test(body) && !/const plannedAt = \(d\) => \{[\s\S]{0,400}_pmDateDiff\(r\.start, r\.finish\)/.test(body),
     body.slice(body.indexOf('plannedAt') - 200, body.indexOf('plannedAt') + 400));

  /* The arithmetic must be the same. Reference implementation = the code that was there before,
     verbatim, run against the same rows. */
  const rows = [
    { id: 'x', start: '2026-01-01', finish: '2026-06-30', w: 3 },
    { id: 'y', start: '2026-03-01', finish: '2026-09-30', w: 1 },
    { id: 'z', start: '2026-05-01', finish: '2026-05-01', w: 2 },     // single-day: total === 1
  ];
  const dd = (a, b) => { const d1 = new Date(a), d2 = new Date(b); return Math.round((d2 - d1) / 86400000); };
  const oldPlannedAt = d => {
    let w = 0, acc = 0;
    rows.forEach(r => {
      const rw = +r.w || 1; w += rw;
      const total = (dd(r.start, r.finish) || 0) + 1;
      const done = (dd(r.start, d) || 0) + 1;
      acc += rw * Math.max(0, Math.min(100, total > 0 ? (done / total) * 100 : (d >= r.finish ? 100 : 0)));
    });
    return w ? acc / w : 0;
  };
  // The new one, lifted out of _pmSCurve by executing the two statements the patch introduced.
  const mk = new Function('rows', body.slice(body.indexOf('  const plan = rows.map('),
                                             body.indexOf('  const pts = [];')) +
                          '\nreturn plannedAt;');
  const newPlannedAt = mk(rows);
  const diffs = [];
  for (let i = 0; i <= 330; i += 3) {
    const d = API._pmDateAdd('2026-01-01', i);
    const A = newPlannedAt(d), B = oldPlannedAt(d);
    if (Math.abs(A - B) > 1e-9) diffs.push(d + ': ' + A + ' vs ' + B);
  }
  ok('and produces the identical planned figure at every date', diffs.length === 0,
     diffs.slice(0, 5).join('\n        '));
  ok('the comparison is not vacuous — the curve actually rises',
     newPlannedAt('2026-01-01') < newPlannedAt('2026-05-01') &&
     newPlannedAt('2026-05-01') < newPlannedAt('2026-09-30'));
}

// ══ 5. the id lookup ═══════════════════════════════════════════════════════════════════════════
console.log('\nThe baseline reads the programme through an index\n');
{
  const i = src.indexOf('function _pmSCurve(');
  const body = src.slice(i, i + 6000);
  ok('no full scan of the activity list per baseline row',
     !/all\.filter\(t => t\.id === r\.id\)/.test(strip(body)), 'the per-row scan is back');
  ok('an index is built once', /const byId = new Map\(\);/.test(body));
  ok('and a duplicate id keeps the FIRST, exactly as [0] did',
     /if \(!byId\.has\(t\.id\)\) byId\.set\(t\.id, t\)/.test(body),
     'Map.set alone would keep the LAST, quietly changing which row the curve reads');
}

console.log('\n' + pass + ' passed, ' + fail + ' failed\n');
process.exit(fail ? 1 : 0);
