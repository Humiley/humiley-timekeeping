/* Manager view and Reports must reach the SAME verdict about the same punch.
 *
 * They did not. Reports read the stamp the check-in screen wrote; the Manager view re-derived a
 * verdict geometrically from stored coordinates — measuring to the NEAREST zone and ignoring GPS
 * accuracy, neither of which is how the punch was judged. So the two screens disagreed in both
 * directions, and the manager's screen is the one with a "Mark Legitimate" button on it.
 *
 * Why it survived every test and every demo: db.py's generate_attendance is the only writer of the
 * literal 'Out of Zone', and its INSERT carries no lat/lon. So the label branch fired only on SEEDED
 * rows and the geometry branch only on REAL ones — the two functions agree on fabricated data and
 * disagree only in production. The previous tests had no lat/lon in their fixtures and so never
 * entered the branch that was wrong.
 *
 * EVERY case below therefore carries lat/lon. A fixture without coordinates cannot fail this test.
 *
 *   node tests/gps_anomaly_one_verdict.js
 */
const fs = require('fs');
const path = require('path');

const src = fs.readFileSync(path.join(__dirname, '..', 'templates', 'index.html'), 'utf8');

let pass = 0, fail = 0;
const ok = (n, c, extra) => {
  if (c) { pass++; console.log('  ok    ' + n); }
  else { fail++; console.log('  FAIL  ' + n + (extra ? '\n        ' + extra : '')); }
};

const take = (mark, what) => {
  const i = src.indexOf(mark);
  if (i < 0) { console.error('Could not find ' + what + ' — update the marker, do NOT delete this test.'); process.exit(2); }
  const j = src.indexOf('\nfunction ', i + 10);
  if (j < 0) { console.error('Could not find the end of ' + what + '.'); process.exit(2); }
  return src.slice(i, j);
};

console.log('\nOne GPS verdict, on both screens\n');

/* A stand-in for the real geofence lookup. It returns a zone the punch is INSIDE, which is the
   trap: under the old code that alone was enough to clear a punch stamped "away from site". */
const PRELUDE = `
  function _mgrNearestZone(lat, lon) {
    if (lat == null || lon == null) return null;
    return { zone: { name: 'Another Site', radius: 200 }, dist: 40 };   // inside, on purpose
  }
`;

const fn = new Function(PRELUDE +
  take('function _attGpsState(', '_attGpsState') +
  take('function _attIsAnomaly(', '_attIsAnomaly') +
  take('function _mgrIsAnomaly(', '_mgrIsAnomaly') +
  '\nreturn { _attGpsState, _attIsAnomaly, _mgrIsAnomaly };')();

const COORDS = { lat: 10.7769, lon: 106.7009 };          // every row has a fix — see the header
const row = (loc) => Object.assign({ loc: loc }, COORDS);

// ── the stamp parser ────────────────────────────────────────────────────────────────────────────
const STATES = [
  ['HQ Tower (away from site)', 'out'],
  ['Out of Zone', 'out'],                                 // seed-only literal, still honoured
  ['HQ Tower (GPS unverified)', 'unverified'],
  ['HQ Tower', 'in'],
  ['', 'none'],
];
STATES.forEach(([loc, want]) => {
  ok('"' + (loc || '(empty)') + '" reads as ' + want, fn._attGpsState(row(loc)) === want,
     'got ' + fn._attGpsState(row(loc)));
});

// ── the two screens agree, on rows that DO carry a fix ──────────────────────────────────────────
STATES.forEach(([loc]) => {
  const r = row(loc);
  const a = fn._attIsAnomaly(r), m = fn._mgrIsAnomaly(r).bad;
  ok('both screens agree on "' + (loc || '(empty)') + '"', a === m,
     'Reports=' + a + ' Manager=' + m + ' — the two screens are telling a manager different things');
});

// ── the exact disagreements that motivated this ─────────────────────────────────────────────────
/* 1. Stamped "away from site" — the app TOLD the worker it would be recorded that way — while the
      coordinates sit inside a different zone. The old geometric test cleared it. */
const awayButNearAnother = row('HQ Tower (away from site)');
ok('a punch stamped "away from site" is an anomaly even when it sits inside ANOTHER zone',
   fn._mgrIsAnomaly(awayButNearAnother).bad === true,
   'the manager view cleared a punch the worker was told was away from site');

/* 2. Stamped in-zone: check-in was accuracy-aware and said "You are at HQ Tower". Geometry that
      ignores accuracy would call the same punch an anomaly. */
const insideByAccuracy = row('HQ Tower');
ok('a punch the app told the worker was fine is NOT flagged',
   fn._mgrIsAnomaly(insideByAccuracy).bad === false,
   'the manager view flagged a punch the check-in screen had blessed');

// ── "we could not tell" is not a finding about a person ─────────────────────────────────────────
const unverified = row('HQ Tower (GPS unverified)');
ok('GPS unverified is not an anomaly on Reports', fn._attIsAnomaly(unverified) === false);
ok('GPS unverified is not an anomaly on the Manager view', fn._mgrIsAnomaly(unverified).bad === false);
ok('GPS unverified is still reported as its own state, not silently folded into "in"',
   fn._mgrIsAnomaly(unverified).state === 'unverified');

// ── the contract the callers depend on ──────────────────────────────────────────────────────────
const withFix = fn._mgrIsAnomaly(row('HQ Tower (away from site)'));
ok('_mgrIsAnomaly still returns `near` for the alert card', !!withFix.near && withFix.near.zone.name === 'Another Site');
ok('_mgrIsAnomaly still returns a boolean `bad`', typeof withFix.bad === 'boolean');
const noFix = fn._mgrIsAnomaly({ loc: 'HQ Tower (away from site)' });
ok('a row with no coordinates still gets a verdict', noFix.bad === true && noFix.near === null);

// ── the re-test must not creep back ─────────────────────────────────────────────────────────────
const mgrSrc = take('function _mgrIsAnomaly(', '_mgrIsAnomaly');
const body = mgrSrc.slice(mgrSrc.indexOf('{'));
ok('_mgrIsAnomaly does not compare a distance to a radius',
   !/\.dist\s*>/.test(body) && !/>\s*rad\b/.test(body),
   'the geometric re-test is back — it asks a question the punch was never judged by');

console.log('\n  ' + pass + ' passed, ' + fail + ' failed\n');
process.exit(fail ? 1 : 0);
