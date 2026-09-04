/* The In/Out Log's Date column, tested against the code that actually ships.
 *
 * The log carries one row per punch across many days. Until this column existed every row showed
 * only a clock time, so you could not tell which day a check-in belonged to — and the date filters
 * looked broken because nothing on screen changed visibly when you set one.
 *
 * Two things are easy to get wrong here and both are silent:
 *   - `new Date("2026-08-21")` parses a BARE date as UTC midnight. West of Greenwich that names the
 *     PREVIOUS weekday. Attendance in this app is kept on local dates, so the weekday must be
 *     derived locally or Sunday work is reported as Saturday.
 *   - The table has three full-width rows (header, "Show all", empty state). Add a column and the
 *     colspans must move with it, or the layout silently shears.
 *
 *   node tests/inout_day_column.js
 */
const fs = require('fs');
const path = require('path');

const src = fs.readFileSync(path.join(__dirname, '..', 'templates', 'index.html'), 'utf8');

let pass = 0, fail = 0;
const ok = (name, cond, extra) => {
  if (cond) { pass++; console.log('  ok    ' + name); }
  else { fail++; console.log('  FAIL  ' + name + (extra ? '\n        ' + extra : '')); }
};
const eq = (name, got, want) => ok(name, got === want, 'got ' + JSON.stringify(got) + ', want ' + JSON.stringify(want));

/* ── extract the helper and its one dependency, rather than copying them ─────── */
const START = "const _IO_DOW =";
const END = 'function renderInOutReport() {';
const i = src.indexOf(START), j = src.indexOf(END);
if (i < 0 || j < 0 || j <= i) {
  console.error('Could not find _ioDayCell in templates/index.html.\n' +
    'If it was renamed, update START/END here — do NOT delete this test.');
  process.exit(2);
}
const fmtStart = src.indexOf('function tkFmtDate(');
if (fmtStart < 0) { console.error('tkFmtDate not found'); process.exit(2); }
const fmtEnd = src.indexOf('\n}', fmtStart) + 2;

const PRELUDE = `
  function _crmEsc(s){ return String(s == null ? '' : s)
    .replace(/&/g,'&amp;').replace(/</g,'&lt;').replace(/>/g,'&gt;').replace(/"/g,'&quot;'); }
  function _t(s){ return s; }   // English path; the VN dictionary is covered by vi_duplicate_keys.js
`;
const api = {};
new Function(PRELUDE + src.slice(fmtStart, fmtEnd) + src.slice(i, j) + `
  Object.assign(this, { _ioDayCell, _IO_DOW, tkFmtDate });
`).call(api);
const { _ioDayCell, _IO_DOW } = api;

console.log('\nIn/Out Log — Date column\n');

/* ── the weekday must be the LOCAL one ──────────────────────────────────────── */
// 2026-08-21 is a Friday. 2026-08-22 Saturday, 2026-08-23 Sunday, 2026-08-24 Monday.
const dow = s => {
  const m = _ioDayCell(s).match(/>(Sun|Mon|Tue|Wed|Thu|Fri|Sat)</);
  return m ? m[1] : null;
};
eq('2026-08-21 is a Friday', dow('2026-08-21'), 'Fri');
eq('2026-08-22 is a Saturday', dow('2026-08-22'), 'Sat');
eq('2026-08-23 is a Sunday', dow('2026-08-23'), 'Sun');
eq('2026-08-24 is a Monday', dow('2026-08-24'), 'Mon');
eq('a leap day keeps its weekday', dow('2024-02-29'), 'Thu');
eq('the day before a leap day', dow('2024-02-28'), 'Wed');

// The UTC trap: were the helper to use `new Date(str)`, this date would render as the previous
// weekday in any timezone west of Greenwich. Asserting the mechanism, not just the output.
//
// This assertion FAILED on its first run — against a COMMENT reading "never `new Date(str)`".
// A check that scans prose as if it were code will convict the documentation and acquit the bug,
// so strip comments before matching. (See memory: verification-instrument-traps.)
const helperSrc = src.slice(i, j)
  .replace(/\/\*[\s\S]*?\*\//g, '')     // block comments
  .replace(/(^|[^:])\/\/.*$/gm, '$1');  // line comments, without eating "http://"
ok('helper never parses a bare date string as UTC',
   !/new Date\(\s*(?:v|s|str|[a-z]\w*)\s*\)/.test(helperSrc),
   'found `new Date(<string>)` in _ioDayCell code — that reads a bare date as UTC midnight');
ok('helper builds the Date from local Y/M/D parts',
   /new Date\(\s*y\s*,\s*mo\s*-\s*1\s*,\s*da\s*\)/.test(helperSrc));
ok('helper reads the parts back to catch a rolled-over date',
   /getFullYear\(\)\s*!==\s*y[\s\S]{0,80}getMonth\(\)\s*!==\s*mo\s*-\s*1[\s\S]{0,60}getDate\(\)\s*!==\s*da/.test(helperSrc));

/* ── the date itself is shown, in the app's format ──────────────────────────── */
ok('the formatted date appears in the cell', _ioDayCell('2026-08-21').includes('Aug-21-26'));
ok('a Vietnamese-safe escape is applied', _ioDayCell('2026-08-21').indexOf('<script') === -1);

/* ── weekends are marked, because Art. 98 pays them differently ─────────────── */
const isWknd = s => /var\(--warning\)/.test(_ioDayCell(s));
ok('Saturday is marked as a rest day', isWknd('2026-08-22'));
ok('Sunday is marked as a rest day', isWknd('2026-08-23'));
ok('Friday is NOT marked as a rest day', !isWknd('2026-08-21'));
ok('Monday is NOT marked as a rest day', !isWknd('2026-08-24'));

/* ── junk in, an em dash out — never a crash and never a wrong day ──────────── */
// '2026-13-45' and '2026-02-30' are the rollover cases: the regex accepts them, and a bare
// `new Date(y, m-1, d)` silently turns them into real dates in another month.
[undefined, null, '', '   ', 'not a date', '2026-13-45', '2026-02-30', '2026-00-10', '21/08/2026'].forEach(v => {
  let out;
  try { out = _ioDayCell(v); } catch (e) { out = 'THREW: ' + e.message; }
  ok('unparseable input (' + JSON.stringify(v) + ') yields a dash, not a crash',
     typeof out === 'string' && out.indexOf('THREW') !== 0 && !/(Sun|Mon|Tue|Wed|Thu|Fri|Sat)</.test(out),
     out);
});

/* ── the table's column count agrees across all four places that state it ───── */
const thead = src.match(/<thead><tr>((?:<th[^>]*>[^<]*<\/th>)+)<\/tr><\/thead>\s*\n\s*<tbody id="inout-report-tbody">/);
ok('the In/Out thead was found', !!thead);
if (thead) {
  const headers = (thead[1].match(/<th[^>]*>([^<]*)<\/th>/g) || []).map(h => h.replace(/<[^>]+>/g, ''));
  eq('thead declares 10 columns', headers.length, 10);
  ok('a Date column exists', headers.indexOf('Date') >= 0, headers.join(' | '));
  eq('Date sits between Department and Check-In',
     headers.indexOf('Date') === headers.indexOf('Department') + 1 &&
     headers.indexOf('Check-In') === headers.indexOf('Date') + 1, true);
}

const body = src.slice(src.indexOf('function renderInOutReport() {'));
const fnEnd = body.indexOf('\n/* The Absent tile');
const fn = body.slice(0, fnEnd > 0 ? fnEnd : 9000);
const rowTpl = fn.match(/return `<tr>([\s\S]*?)<\/tr>`;/);
ok('the row template was found', !!rowTpl);
if (rowTpl) {
  const cells = (rowTpl[1].match(/<td/g) || []).length;
  eq('a body row emits 10 cells', cells, 10);
  ok('the row renders the day through the helper', /_ioDayCell\(r\.date\)/.test(rowTpl[1]));
}
eq('the "Show all" row spans 10', /colspan="10"/.test(fn), true);
ok('no colspan="9" survives in the In/Out table', !/colspan="9"/.test(fn));
eq('the empty-state row spans 10', /tkEmptyRow\(10,/.test(fn), true);
ok('no tkEmptyRow(9 survives', !/tkEmptyRow\(9,/.test(fn));

/* ── the date filters this column makes legible must still be applied ───────── */
ok('the exact-date filter is applied', /matchDate\s*=\s*!dateF\s*\|\|\s*r\.date === dateF/.test(fn));
ok('the month filter is applied', /matchMonth\s*=\s*!monthF\s*\|\|\s*\(r\.date\|\|''\)\.slice\(0,\s*7\) === monthF/.test(fn));
ok('the period preset is applied', /_inPeriodLF\(r\.date, 'io-period-f'\)/.test(fn));
ok('rows are sorted newest day first', /_cmpNewest\('date'\)/.test(fn));

console.log('\n' + pass + ' passed, ' + fail + ' failed\n');
process.exit(fail ? 1 : 0);
