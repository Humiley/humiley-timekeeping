/* Numbers that were about nothing, and a screen that spoke the wrong language about the wrong rule.
 *
 * Reports → Attendance:
 *   - "GPS Anomalies" counted `r.loc === 'Out of Zone'`. The only line in the repo that writes that
 *     literal is seed data (db.py); production writes '<zone> (away from site)'. The KPI read 0
 *     forever, on live data, in a card headed GPS Anomalies.
 *   - "Total Hours Worked" had its own span arithmetic WITHOUT the overnight wrap, so a 21:00→05:00
 *     shift scored −960 minutes, was dropped by an `if (d > 0)` guard, and contributed zero — while
 *     the same row, one tab away, showed 8h.
 *   - "Late Arrivals by Department" drew six bars for departments this company does not have,
 *     at heights like 3.4, whenever there were no late arrivals.
 *   - The Payroll tab priced employees with no salary at their grade MID-POINT — the exact thing
 *     the payslip screen and all three pay-run buttons refuse by name — dropped anybody whose
 *     computation threw, ignored the period control above it, and called the result "Net paid".
 *
 * Check In:
 *   - The whole GPS state machine was hardcoded English, on the one line a Vietnamese fitter reads
 *     before every punch.
 *   - It said "Check-in is not allowed here." That was false: nothing client-side or server-side
 *     enforces it. The punch goes through and is stamped 'away from site'.
 *   - A 3-second upgrade decided whether to fire by regex-testing the on-screen ENGLISH text, so
 *     translating the sentence it matched would have silently killed it.
 *
 *   node tests/reports_and_checkin_honesty.js
 */
const fs = require('fs');
const path = require('path');

const src = fs.readFileSync(path.join(__dirname, '..', 'templates', 'index.html'), 'utf8');
const appPy = fs.readFileSync(path.join(__dirname, '..', 'app.py'), 'utf8');

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

console.log('\nReports that read the data, and a Check In screen that tells the truth\n');

/* ══ the two shared helpers, executed ═══════════════════════════════════════════════════════ */
const api = {};
new Function(
  take('function _attMinutes(', '_attMinutes') +
  // _attIsAnomaly delegates to the shared stamp parser now — the Manager view reads the same one,
  // which is the whole point. Without it here the sandbox throws ReferenceError.
  take('function _attGpsState(', '_attGpsState') +
  take('function _attIsAnomaly(', '_attIsAnomaly') +
  '\nObject.assign(this, { _attMinutes, _attIsAnomaly });'
).call(api);
const { _attMinutes, _attIsAnomaly } = api;

// The first version of this file ran _attIsAnomaly in a sandbox where _mgrIsAnomaly did not exist,
// while the helper preferred a geometric re-test whenever the row carried lat/lon — which EVERY
// production row does. So the five assertions below all took a branch live data never takes, and
// certified rules that were false in production. The helper no longer has that branch; these rows
// carry a fix to prove it, because a fixture without one could not tell the difference.
const WITH_FIX = { lat: 10.8231, lon: 106.6297 };

ok('a normal day is counted', _attMinutes({ in: '08:00', out: '17:30' }) === 570);
ok('an overnight shift is 8 hours, not zero',
   _attMinutes({ in: '21:00', out: '05:00' }) === 480,
   'got ' + _attMinutes({ in: '21:00', out: '05:00' }));
ok('a shift still open returns null rather than a number',
   _attMinutes({ in: '08:00', out: '' }) === null);
ok('a malformed punch returns null rather than NaN',
   _attMinutes({ in: 'nonsense', out: '17:00' }) === null);
ok('the Attendance tab uses it', /att\.forEach\(r => \{ const d = _attMinutes\(r\);/.test(code));
ok('and the In/Out tab shares the same one, rather than keeping a copy',
   /const _mins = _attMinutes;/.test(code),
   'two copies of one span is how these two tabs came to disagree about the same row');
ok('no unshared span arithmetic is left on the Attendance tab',
   !/const d = \(oh \* 60 \+ om\) - \(ih \* 60 \+ im\); if \(d > 0\) mins \+= d;/.test(code));

/* ── the anomaly test matches what the product actually writes ─────────────────────────────── */
// Every one of these carries a GPS fix, so they exercise the path a real punch takes.
ok('a punch away from site counts',
   _attIsAnomaly(Object.assign({ loc: 'HQ Tower (away from site)' }, WITH_FIX)) === true);
ok('the seed label still counts, case-insensitively',
   _attIsAnomaly(Object.assign({ loc: 'out of zone' }, WITH_FIX)) === true);
ok('a punch inside the zone does not',
   _attIsAnomaly(Object.assign({ loc: 'HQ Tower' }, WITH_FIX)) === false);
ok('a GPS-unverified punch is not an anomaly',
   _attIsAnomaly(Object.assign({ loc: 'HQ Tower (GPS unverified)' }, WITH_FIX)) === false,
   '"we could not tell" and "they were somewhere else" are different findings');
ok('a row with no location is not an anomaly', _attIsAnomaly(Object.assign({}, WITH_FIX)) === false);
ok('the verdict does not change when a fix is present',
   _attIsAnomaly({ loc: 'HQ Tower (GPS unverified)' }) ===
   _attIsAnomaly(Object.assign({ loc: 'HQ Tower (GPS unverified)' }, WITH_FIX)),
   'a helper that answers differently with and without lat/lon is answering two questions');
// Comment-stripped: the comment explaining WHY _mgrIsAnomaly was removed names it, and the first
// version of this assertion convicted that comment. Third time this trap has appeared in this pass.
ok('and the helper no longer re-decides the geofence itself',
   !/_mgrIsAnomaly/.test(take('function _attIsAnomaly(', '_attIsAnomaly')
     .replace(/\/\*[\s\S]*?\*\//g, '').replace(/(^|[^:])\/\/.*$/gm, '$1')),
   '_mgrIsAnomaly measures to the NEAREST zone and ignores accuracy — a different question from ' +
   'the one the check-in screen answered and stamped into the row');
ok('the KPI calls it', /const anom = att\.filter\(_attIsAnomaly\)\.length;/.test(code));
ok('and no longer compares against the seed literal',
   !/\(r\.loc \|\| ''\) === 'Out of Zone'/.test(code));

// the label the check-in path really writes, so this test is anchored to production, not to itself
ok('the check-in path writes " (away from site)" — the string the test above matches',
   /' \(away from site\)'/.test(code),
   'if this changes, _attIsAnomaly must change with it');

/* ══ the department chart invents nothing ═══════════════════════════════════════════════════ */
// Scoped to the chart function. 'HRBP' and 'Proposal' are real strings elsewhere in the app (the
// HR hub heading, a CRM deal stage), so a file-wide search would convict them for a defect that
// lives in one function — and would pass or fail for reasons unrelated to this fix.
const dept = take('function _initDeptChart(', '_initDeptChart')
  .replace(/\/\*[\s\S]*?\*\//g, '').replace(/(^|[^:])\/\/.*$/gm, '$1');
ok('the chart invents no department names',
   !/'Project Mgmt'|'HRBP'|'Field Svcs'|'Proposal'/.test(dept));
ok('and no fabricated counts', !/\[2\.1, 3\.4, 1\.2, 1\.8, 4\.2, 2\.6\]/.test(dept));
ok('its labels come only from the data',
   /const dKeys = Object\.keys\(lateByDept\)\.sort/.test(dept) &&
   /const dVals = dKeys\.map\(d => lateByDept\[d\]\);/.test(dept));
ok('an empty chart says so instead', /No late arrivals in this period\./.test(src));
ok('the empty state does not destroy the canvas the next render looks up',
   /insertAdjacentHTML\('beforeend',\s*\n?\s*'<div data-dept-empty/.test(code) ||
   /_host\.insertAdjacentHTML\('beforeend'/.test(code),
   'overwriting the host innerHTML deletes <canvas id="deptChart"> and the chart never returns');
ok('and it is removed again once there is data', /if \(_prevEmpty\) _prevEmpty\.remove\(\);/.test(code));

/* ══ the payroll report ═════════════════════════════════════════════════════════════════════ */
// Comment-stripped, for the same reason the file-wide `code` is: the fix's own comment quotes the
// old `catch (x) {}` verbatim, and the first version of the assertion below convicted that comment.
const pr = take('async function tkRenderPayrollReport(', 'tkRenderPayrollReport')
  .replace(/\/\*[\s\S]*?\*\//g, '').replace(/(^|[^:])\/\/.*$/gm, '$1');
ok('an employee with no salary on record is excluded from the totals',
   /if \(c\.salaryMissing\) \{ noSalary\.push\(/.test(pr),
   'the grade mid-point is a band preview, not this person’s pay');
ok('and is NAMED, not silently dropped',
   /employee\(s\) have no salary on record and are NOT in these totals/.test(src));
ok('an employee who cannot be costed is counted rather than swallowed',
   /catch \(x\) \{ failed\+\+; return; \}/.test(pr));
ok('there is no bare catch left on this path', !/catch \(x\) \{\}/.test(pr));
ok('the report prefers the FINALISED pay run for the period',
   /const fromRuns = runs\.length > 0;/.test(pr) && /\/final\/i\.test\(String\(r\.status/.test(pr));
ok('a person in two runs for one period is counted once AND named',
   /if \(seen\.has\(key\)\) \{ dupes\.push\(/.test(pr),
   'the first version dropped the second line silently — the journal refuses this outright, so a ' +
   'report that cannot refuse has to say it happened');
ok('and the banner points at the journal that does refuse it',
   /The payroll journal refuses this rather than choosing which run wins/.test(src));
ok('it reads the period control it sits under',
   /_rptInPeriod\(_payRunMonthISO\(r\.period\)/.test(pr));
// The qualification lives in the BANNER, not in the tile label: 'Net paid' and 'Headcount' both
// have _VI entries, and replacing them with 'Net (computed)' / 'People paid' quietly un-translated
// two tiles for a Vietnamese reader. A banner can carry a sentence; a tile label cannot.
ok('the tile labels keep the ones that already had translations',
   /_hrKpi\('Headcount', fromRuns \? people\.size : headcount/.test(pr) &&
   /_hrKpi\('Net paid', _PAY_FMT\(net\)/.test(pr));
ok('and the banner is what distinguishes a signed run from a recomputation',
   /_t\('Signed pay runs'\)/.test(pr) && /_t\('Cost model, not a payroll'\)/.test(pr));
ok('a period covered by runs that do not cover the company says so',
   /_t\('Not the whole company'\)/.test(pr),
   'one individual pay run used to flip the whole company report onto its figures');
ok('the model path says so in a banner', /Cost model, not a payroll/.test(src));
ok('the heading carries the period', /_t\('Payroll'\) \+ \(per \? _crmEsc\(per\)/.test(pr));
ok('and so does the exported PDF title', /const _pdfTitle = \('PAYROLL REPORT'/.test(pr));
ok('the company-total row counts who is actually in the totals',
   /COMPANY TOTAL<\/td><td style="text-align:right;font-weight:700">' \+ \(fromRuns \? people\.size : headcount\)/.test(pr),
   'it used to print emps.length beside a total that excluded some of them');
ok('and a person paid in three months counts once, not three times',
   /people\.add\(String\(l\.empId \|\| l\.name \|\| ''\)\)/.test(pr),
   'the de-dup key is period|empId, so with the default All-time period a payslip count is ' +
   'multiplied by the number of finalised months');

// ── the legacy line shape ────────────────────────────────────────────────────────────────────────
ok('a pay-run line is normalised before it is read',
   /const c = _payRunLineCalc\(l\);/.test(pr));
ok('and the normaliser knows the pre-snapshot shape',
   /function _payRunLineCalc\(l\)/.test(code) && /grossPay: \+x\.gross \|\| 0/.test(code),
   'runs finalised before 2026-08-06 store gross/erCost/ee, not grossPay/employerCost/eeBhxh — ' +
   'reading calc names off one produced ₫0 under a banner saying "exactly as signed"');
ok('a line whose breakdown was never stored is disclosed, not silently zeroed',
   /line\(s\) predate the frozen-payslip snapshot/.test(src));

// ── the banner tints have to be real colours ─────────────────────────────────────────────────────
ok('the banner resolves its colour through _tintHex',
   /const _note = \(color, html\) => \{ const hex = _tintHex\(color\);/.test(code),
   'background:var(--emerald)22 substitutes at token level and the declaration is DROPPED — ' +
   'verified in the browser: it computes to rgba(0,0,0,0)');
ok('and _tintHex never returns a var()',
   /function _tintHex\(color\)/.test(code) && !/return c;\s*\/\/ var/.test(code));
ok('the KPI colour table covers the tokens callers actually pass',
   /'var\(--danger\)': '#EF4444'/.test(code) && /'var\(--text-light\)': '#5C6470'/.test(code),
   'the unmeasured CPI/SPI tiles pass var(--text-light) and rendered with no tint at all');

/* ══ Check In: the language, and the claim ══════════════════════════════════════════════════ */
const gps = take('function tkVerifySelectedZone(', 'tkVerifySelectedZone');
ok('the in-zone message is translated', /_t2\('You can check in now\.', 'Bạn c\xf3 thể chấm c\xf4ng v\xe0o ngay\.'\)/.test(gps));
ok('the out-of-zone message is translated', /_t2\('You are not at', 'Bạn kh\xf4ng ở'\)/.test(gps));
ok('the too-coarse message is translated', /_t2\('Location not precise enough to confirm'/.test(gps));
ok('"Checking your location" is translated', /_t2\('Checking your location…'/.test(gps));
ok('the blocked-permission message is translated', /_t2\('Location is blocked', /.test(code));
ok('the no-fix message is translated', /_t2\('Could not get a GPS fix in time/.test(code));
ok('the overtime check-out toast is translated', /_t2\('Checked out at ', 'Đ\xe3 chấm c\xf4ng ra l\xfac '\) \+ t \+ _t2\(' · overtime '/.test(code));
ok('"Select a location first" is translated', /_t2\('Select a location first', /.test(code));

ok('the screen no longer claims the punch is refused',
   !/Check-in is not allowed here/.test(src),
   'nothing in the client or the server enforced it');
ok('it says what actually happens instead',
   /You can still check in — it will be recorded as away from site\./.test(src));
ok('…and that matches the label the punch is stamped with', /' \(away from site\)'/.test(code));
ok('the server still does not gate on the geofence, so the new wording is the true one',
   !/geofence|within the zone|zone_radius/i.test(appPy.slice(appPy.indexOf('def _checkin('),
                                                             appPy.indexOf('def _checkin(') + 3000)),
   'if a server-side check is ever added, this wording has to change with it');

/* ── the timing upgrade reads state, not English ───────────────────────────────────────────── */
ok('the 3-second upgrade tests a phase flag',
   /status\.dataset\.phase === 'locating'/.test(code));
ok('and no longer regex-matches the on-screen text',
   !/\/Checking\|locating\/i\.test\(status\.textContent\)/.test(code),
   'it worked only while that sentence had no translation — which this commit gives it');
ok('the flag is set where the sentence is written',
   /status\.dataset\.phase = 'locating';/.test(code));

/* ── and no new _VI keys were needed, so nothing can shadow an existing one ─────────────────── */
const viStart = src.indexOf('const _VI = {');
const viEnd = src.indexOf('\n};', viStart);
const vi = viStart > 0 ? src.slice(viStart, viEnd) : '';
ok('the _VI table was not touched by this change',
   vi.indexOf('You can check in now.') < 0 && vi.indexOf('Checking your location') < 0,
   '_VI is one shared object where a later duplicate key silently wins; _t2 is inline and cannot');

console.log('\n' + pass + ' passed, ' + fail + ' failed\n');
process.exit(fail ? 1 : 0);
