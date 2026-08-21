/* The Reports page period control, tested against the code that ships.
 *
 * It was decorative. `#rpt-period` had exactly two references in 40,000 lines — a <select> with
 * three hardcoded months and NO onchange, and a comment. Nothing read its value. So every tab
 * reported all-time figures underneath a control naming a month, and the Leave card's title was
 * the literal string "Leave Requests — May 2026" over rows dated July.
 *
 * That is worse than having no control: it does not merely fail to filter, it states a scope the
 * numbers do not have, and somebody reports those numbers to a client.
 *
 *   node tests/reports_period_filter.js
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
  return src.slice(i, j < 0 ? i + 3000 : j);
};

// _RPT_PERIOD_F is a module-scope const the extracted functions close over. Read it out of the
// source rather than hardcoding it here, so renaming the filter id cannot leave this test asserting
// against a key the app no longer uses.
const FID = (src.match(/const _RPT_PERIOD_F = '([^']+)'/) || [])[1];
if (!FID) { console.error('_RPT_PERIOD_F not found — update this test, do NOT delete it.'); process.exit(2); }

const PRELUDE = `
  const _RPT_PERIOD_F = ${JSON.stringify(FID)};
  var _crmLF = {};
  function _isoDay(v) { const m = String(v || '').match(/^(\\d{4})-(\\d{2})-(\\d{2})/); return m ? m[0] : ''; }
  function _t(s) { return s; }
  function tkFmtDate(v) { return String(v || ''); }
`;
const api = {};
new Function(PRELUDE +
  take('function _inPeriod(', '_inPeriod') +
  take('function _inPeriodLF(', '_inPeriodLF') +
  take('function _rptPeriodLabel(', '_rptPeriodLabel') +
  take('function _rptInPeriod(', '_rptInPeriod') +
  '\nObject.assign(this, { _rptInPeriod, _rptPeriodLabel, _crmLF });').call(api);
const { _rptInPeriod, _rptPeriodLabel } = api;
const LF = api._crmLF;
const F = FID;
ok('the filter id matches the one the app uses', F === 'rpt-period-f', F);
const setPeriod = (p, from, to) => { LF[F] = p || ''; LF[F + '-from'] = from || ''; LF[F + '-to'] = to || ''; };

const iso = d => d.getFullYear() + '-' + String(d.getMonth() + 1).padStart(2, '0') + '-' + String(d.getDate()).padStart(2, '0');
const TODAY = iso(new Date());
const thisYear = new Date().getFullYear();

console.log('\nReports period filter\n');

/* ── All time keeps everything, which is what an unset control must mean ────── */
setPeriod('');
ok('All time keeps a dated row', _rptInPeriod('2019-01-01'));
ok('All time keeps an undated row', _rptInPeriod(''));
ok('All time keeps a null date', _rptInPeriod(null));

/* ── an undated row is KEPT, never silently dropped ─────────────────────────── */
setPeriod('This month');
ok('an undated row survives a period filter rather than vanishing', _rptInPeriod(''),
   'dropping it would shrink a total on a technicality; an undated record is a data problem to fix');
ok('a null date survives too', _rptInPeriod(null));
ok('an unparseable date survives too', _rptInPeriod('not a date'));

/* ── the window actually excludes ───────────────────────────────────────────── */
setPeriod('Today');
ok("Today keeps today's row", _rptInPeriod(TODAY));
ok('Today excludes a row from 2019', !_rptInPeriod('2019-06-01'));

setPeriod('This year');
ok('This year keeps a row from this year', _rptInPeriod(thisYear + '-03-14'));
ok('This year excludes last year', !_rptInPeriod((thisYear - 1) + '-03-14'));

setPeriod('Custom range…', thisYear + '-01-01', thisYear + '-01-31');
ok('a custom range keeps a row inside it', _rptInPeriod(thisYear + '-01-15'));
ok('a custom range excludes a row after it', !_rptInPeriod(thisYear + '-02-15'));
ok('a custom range excludes a row before it', !_rptInPeriod((thisYear - 1) + '-12-31'));
setPeriod('Custom range…', '', '');
ok('a custom range not yet picked does not blank the table', _rptInPeriod(thisYear + '-05-05'));

/* ── the label states the real scope, and says nothing when there is none ───── */
setPeriod('');
ok('All time adds no label (silence beats noise)', _rptPeriodLabel() === '', JSON.stringify(_rptPeriodLabel()));
setPeriod('This month');
ok('a chosen preset is named in the label', /This month/.test(_rptPeriodLabel()), _rptPeriodLabel());
setPeriod('Custom range…', '2026-01-01', '2026-01-31');
ok('a custom range shows its bounds', /2026-01-01/.test(_rptPeriodLabel()) && /2026-01-31/.test(_rptPeriodLabel()), _rptPeriodLabel());

/* ── the decorative control is gone for good ────────────────────────────────── */
// Scan CODE, not prose. The first version of these three assertions failed against this file's own
// comments — which describe the old markup verbatim, as comments explaining a fix must. A check
// that reads documentation as if it were code convicts the documentation and acquits the bug.
// (Third time today; see memory: verification-instrument-traps.)
const code = src
  .replace(/\/\*[\s\S]*?\*\//g, '')          // block comments (HTML + JS)
  .replace(/<!--[\s\S]*?-->/g, '')           // HTML comments
  .replace(/(^|[^:])\/\/.*$/gm, '$1');       // line comments, without eating "http://"
ok('the dead <select id="rpt-period"> is gone',
   !/<select[^>]*id="rpt-period"[\s>]/.test(code),
   'note the trailing [\\s>]: id="rpt-period-f" and id="rpt-period-slot" are the NEW controls and must not match');
ok('no hardcoded "May 2026" option survives', !/<option value="May 2026">/.test(code));
ok('the Leave title no longer hardcodes a month', !/Leave Requests — May 2026/.test(code));
ok('and the translation for that dead title is gone too',
   !/"Leave Requests — May 2026"\s*:/.test(src),
   'an orphaned _VI pair whose English key no longer exists can never fire again');
ok('a period slot exists on the page', /id="rpt-period-slot"/.test(src));
ok('the slot is filled with the portal-standard control',
   /_crmFiltPeriod\(_RPT_PERIOD_F, '_rptPeriodChanged'\)/.test(src));
ok('changing the period re-renders the active tab', /function _rptPeriodChanged\(\)/.test(src) && /switchReportTab\(_rptTabK, el\)/.test(src));
ok('switchReportTab records which tab is active', /_rptTabK = tab;/.test(src));

/* ── the tabs actually apply it ─────────────────────────────────────────────── */
const leave = take('function renderLeaveReport(', 'renderLeaveReport');
ok('Leave filters its rows by the period', /_rptInPeriod\(l\.startDate\)/.test(leave));
ok('Leave KPI tiles count the filtered rows, not everything', /set\('lr-total', rows\.length\)/.test(leave));
ok('Leave labels the period it is showing', /lr-period-label/.test(leave));

const att = take('function _renderRptAttendance(', '_renderRptAttendance');
ok('Attendance filters its rows by the period', /_rptInPeriod\(r\.date\)/.test(att));

/* ── and it stops naming an approver it does not know ───────────────────────── */
ok('the approver column no longer invents "Manager"',
   !/\? 'Manager' : '—'/.test(leave),
   'printing "Manager" for an unknown approver states a fact the record does not contain');
ok('the approver column falls back to a dash', /_crmEsc\(l\.approvedBy \|\| '—'\)/.test(leave));

console.log('\n' + pass + ' passed, ' + fail + ' failed\n');
process.exit(fail ? 1 : 0);
