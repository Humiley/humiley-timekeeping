/* A payslip has one month on it.
 *
 * It used to have two. The unpaid-leave deduction divided P1+P2 by a hardcoded Mon–Fri 22, while
 * overtime — sixteen lines below, under a comment naming this exact bug — divided by the employee's
 * REAL working days, resolved by the server from their schedule and the public holidays. The fix had
 * been applied to overtime and not to the deduction beside it. A Mon–Sat employee's unpaid day was
 * therefore priced at 1/22 of their month while their overtime hour was priced off 1/26 of it, on a
 * document a Director e-signs and the employee receives as their Art. 95 wage statement.
 *
 * payroll_calc.py — the characterization-locked Python port of this same function — has always used
 * ONE `working_days` for both. So the two implementations of one calculation disagreed, and the one
 * with the defect was the one people actually read.
 *
 *   node tests/payslip_one_month.js
 */
const fs = require('fs');
const path = require('path');

const src = fs.readFileSync(path.join(__dirname, '..', 'templates', 'index.html'), 'utf8');

let pass = 0, fail = 0;
const ok = (n, c, extra) => {
  if (c) { pass++; console.log('  ok    ' + n); }
  else { fail++; console.log('  FAIL  ' + n + (extra ? '\n        ' + extra : '')); }
};

// `stop` matters: slicing to the next `\nfunction ` swept the SI_CAP / PIT constant line in with
// _payGradeIdx, which then collided with the copy injected below — "Identifier 'SI_CAP' has already
// been declared", from a test that had not looked at what it was cutting.
const take = (mark, what, stop) => {
  const i = src.indexOf(mark);
  if (i < 0) { console.error('Could not find ' + what + ' — update the marker, do NOT delete this test.'); process.exit(2); }
  const j = src.indexOf(stop || '\nfunction ', i + 10);
  if (j < 0) { console.error('Could not find the end of ' + what + '.'); process.exit(2); }
  return src.slice(i, j);
};

// Scan CODE, not prose. The comments here quote the old expressions verbatim, as comments
// explaining a fix must; a check that reads its own documentation convicts the documentation.
const code = src
  .replace(/\/\*[\s\S]*?\*\//g, '')
  .replace(/<!--[\s\S]*?-->/g, '')
  .replace(/(^|[^:])\/\/.*$/gm, '$1');

/* ── run the real function, with the REAL constants ─────────────────────────────────────────── */
// Stubbing SI_CAP or the PIT allowances with invented numbers would make every figure below a
// number this test made up. They are lifted from the file under test.
const line = (rx, what) => {
  const m = rx.exec(src);
  if (!m) { console.error('Could not find ' + what + ' — update the marker, do NOT delete this test.'); process.exit(2); }
  return m[0];
};
const api = {};
new Function(
  line(/const SI_CAP = \d+, PIT_SELF = \d+, PIT_DEP = \d+;/, 'the SI cap and PIT allowances') +
  line(/const _PAY_GRADES = \[[\s\S]*?\n\];/, 'the grade table') +
  take('function _payGradeIdx(', '_payGradeIdx', '\nconst SI_CAP') +
  'function _tkDateParts(s) { const m = /^(\\d{4})-(\\d{2})-(\\d{2})/.exec(String(s || "")); ' +
  '  return m ? { y: +m[1], m: +m[2], d: +m[3] } : null; }' +
  take('function _payPit(', '_payPit') +
  take('function _payComputed(', '_payComputed') +
  '\nObject.assign(this, { _payComputed });'
).call(api);
const { _payComputed } = api;

// Title "Engineer" resolves to grade G3, which carries no position allowance, and a start date in
// the current year earns no seniority allowance either — so P1+P2 is basic 65% + responsibility 10%
// and nothing else. The first assertion below checks that, because every figure after it is derived
// from this number: a fixture that is not what the test thinks it is makes the whole file vacuous.
// (The first draft used a 2020 start date and quietly picked up the 5% seniority allowance.)
const EMP = { id: 'E1', name: 'Nguyen Van A', salary: 20000000, title: 'Engineer',
              startDate: new Date().getFullYear() + '-01-01' };
const P1P2 = 20000000 * (0.65 + 0.10);

console.log('\nOne payslip, one month\n');

/* ── the fixture is what this test thinks it is ─────────────────────────────────────────────── */
const probe = _payComputed(EMP, 3, { workingDays: 26, unpaidDays: 0 });
ok('the fixture employee has the P1+P2 this test computes against',
   Math.round(probe.P1 + probe.P2) === Math.round(P1P2),
   'got ' + Math.round(probe.P1 + probe.P2) + ', expected ' + Math.round(P1P2) +
   ' — every figure below is derived from this, so it is checked first');

/* ── the deduction and the overtime read the same month ─────────────────────────────────────── */
const monSat = _payComputed(EMP, 3, { workingDays: 26, unpaidDays: 2 });
ok('an unpaid day is priced off the days the person actually works',
   Math.round(monSat.unpaidDeduction) === Math.round(P1P2 / 26 * 2),
   'got ' + Math.round(monSat.unpaidDeduction) + ', expected ' + Math.round(P1P2 / 26 * 2));

const monFri = _payComputed(EMP, 3, { workingDays: 22, unpaidDays: 2 });
ok('a Mon–Fri month still divides by 22',
   Math.round(monFri.unpaidDeduction) === Math.round(P1P2 / 22 * 2));

ok('the two months give different money (the test can fail)',
   Math.round(monSat.unpaidDeduction) !== Math.round(monFri.unpaidDeduction),
   'if these are equal the divisor is being ignored and every assertion here is vacuous');

// the size of the error, stated: two unpaid days at 1/22 instead of 1/26 of P1+P2
ok('the Mon–Sat employee is no longer over-deducted',
   Math.round(monFri.unpaidDeduction - monSat.unpaidDeduction) ===
     Math.round(P1P2 / 22 * 2 - P1P2 / 26 * 2));

/* ── one divisor, whichever way it arrives ──────────────────────────────────────────────────── */
const withOt = _payComputed(EMP, 3, {
  workingDays: 22,                                  // a caller that has not been updated
  unpaidDays: 2,
  ot: { hours: 8, units: 8 * 1.5, taxableUnits: 8, workingDays: 26 },   // the server's real count
});
ok('the resolved count from the overtime payload wins over a stale Mon–Fri one',
   Math.round(withOt.unpaidDeduction) === Math.round(P1P2 / 26 * 2),
   'got ' + Math.round(withOt.unpaidDeduction));
ok('and the overtime on the SAME payslip is priced off that same month',
   Math.round(withOt.otPay) === Math.round(P1P2 / (26 * 8) * 12),
   'got ' + Math.round(withOt.otPay) + ', expected ' + Math.round(P1P2 / (26 * 8) * 12));

// the property the whole fix exists to guarantee, stated as one comparison
const hourlyFromOt = withOt.otPay / 12;
const dailyFromUnpaid = withOt.unpaidDeduction / 2;
ok('the payslip cannot contradict itself about how long the month is',
   Math.abs(dailyFromUnpaid - hourlyFromOt * 8) < 1,
   'a day off and eight overtime hours are the same fraction of a month; they were not');

/* ── nothing was invented for the ordinary case ─────────────────────────────────────────────── */
const noOpts = _payComputed(EMP, 3);
ok('no unpaid days means no deduction', noOpts.unpaidDeduction === 0);
ok('no overtime means no overtime pay', noOpts.otPay === 0);

/* ── the second divisor is gone from the source, not merely unused ──────────────────────────── */
ok('there is no second day-count variable left to drift',
   !/const otDays\s*=/.test(code),
   '`otDays` was the other half of the disagreement; a spare copy is how it came back');
ok('the overtime hourly rate divides by the one resolved count',
   /const otHourly = \(P1 \+ P2\) \/ Math\.max\(1, workingDays \* 8\)/.test(code));
ok('the unpaid deduction divides by the same one',
   /const unpaidDeduction = \(P1 \+ P2\) \/ workingDays \* unpaidDays/.test(code));

/* ── the divisor reaches the browser for somebody with NO overtime ──────────────────────────── */
ok('the server sends a per-person working-day map', /workingDaysByEmp/.test(code));
ok('the browser keeps it', /_payWDMap\[key\] = r\.workingDaysByEmp/.test(code));
ok('and there is a resolver that falls back only when the map is unreadable',
   /function _payWDFor\(empId, y, m\)/.test(code) && /return n > 0 \? n : _payWD\(y, m\)/.test(code));
ok('invalidating the overtime for a month drops the day map with it',
   /_payOTInvalidate[\s\S]{0,240}delete _payWDMap\[key\]/.test(code),
   'a stale divisor outliving the data it was derived from is the next version of this bug');

// every caller that passes a divisor passes the RESOLVED one
const stale = (code.match(/workingDays: _payWD\(/g) || []);
ok('no caller still passes the raw Mon–Fri count', stale.length === 0,
   stale.length + ' left');
ok('the three payslip callers pass the resolved count',
   (code.match(/workingDays: _payWDFor\(/g) || []).length >= 2 &&
   (code.match(/_payWDFor\(e\.id|_payWDFor\(empId/g) || []).length >= 3);

console.log('\n' + pass + ' passed, ' + fail + ' failed\n');
process.exit(fail ? 1 : 0);
