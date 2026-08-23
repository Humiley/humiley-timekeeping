/* Retiring a work-schedule pattern must stop it being OFFERED and keep it being HONOURED.
 *
 * The Work Schedules register has an Active toggle. It persists — tkToggleSchedActive PATCHes the
 * record and the row re-renders from it — and nothing else in the portal ever looked at the flag.
 * A manager switching "WFH Schedule" off watched the row grey out, and the pattern went on
 * appearing in every employee's Work Schedule dropdown as an assignable option.
 *
 * The fix has two halves and only one of them is safe to change:
 *
 *   STOP OFFERING it   — a new assignment to a pattern somebody retired is exactly what the toggle
 *                        is for. tkFillSchedSelects filters it out.
 *   KEEP HONOURING it  — lateness, rest days and break minutes are all resolved from the pattern BY
 *                        NAME for the people already on it. Dropping that would silently re-judge
 *                        live attendance for the very staff a manager was trying to leave alone.
 *
 * The second half is the one worth guarding, because it is invisible: nothing on screen would look
 * wrong if a future change made _grace_for skip inactive patterns, and a whole shift's lateness
 * would move.
 *
 *   node tests/schedule_retire.js
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

const take = (mark, what) => {
  const i = src.indexOf(mark);
  if (i < 0) { console.error('Could not find ' + what + ' — update the marker, do NOT delete this test.'); process.exit(2); }
  const j = src.indexOf('\nfunction ', i + 10);
  if (j < 0) { console.error('Could not find the end of ' + what + '.'); process.exit(2); }
  return src.slice(i, j);
};

/* A minimal DOM: one <select> whose innerHTML we can read back. Enough to exercise the real
   function rather than assert on its source text. */
function makeSel(prev) {
  const el = {
    innerHTML: '', value: prev || '', _attrs: { 'data-sched-select': '' },
    hasAttribute: k => k in el._attrs,
    querySelectorAll: () => [],
  };
  return el;
}
const F = new Function(
  'const _HR = arguments[0];\n' +
  'const _SCHED_SEED = arguments[1];\n' +
  'const document = arguments[2];\n' +
  'function _crmEsc(v){ return String(v).replace(/&/g,"&amp;").replace(/</g,"&lt;"); }\n' +
  'function _t(v){ return v; }\n' +
  take('function tkFillSchedSelects(', 'tkFillSchedSelects') +
  '\nreturn tkFillSchedSelects;');

const run = (schedules, prev) => {
  const sel = makeSel(prev);
  const doc = { querySelectorAll: () => [sel] };
  F({ schedules }, [{ name: 'Seeded Only' }], doc)();
  return sel;
};

console.log('\nA retired pattern is not offered, and not forgotten\n');

const ACTIVE = { id: 'a', name: 'Standard 08:00 - 17:00', active: true };
const RETIRED = { id: 'b', name: 'WFH Schedule', active: false };
const UNMARKED = { id: 'c', name: 'Morning Shift 06:00 - 14:00' };   // no `active` key at all

// -- the control that did nothing -----------------------------------------------------------------
{
  const sel = run([ACTIVE, RETIRED]);
  ok('an active pattern is offered', sel.innerHTML.indexOf('Standard 08:00 - 17:00') >= 0);
  ok('a RETIRED pattern is not', sel.innerHTML.indexOf('WFH Schedule') < 0,
     'this is the whole finding: the toggle greyed the row and the option stayed');
}
ok('a pattern with no active flag at all is still offered',
   run([UNMARKED]).innerHTML.indexOf('Morning Shift') >= 0,
   'every pattern in production predates the flag; treating absent as retired would empty the list');

// -- but somebody already on it keeps it ----------------------------------------------------------
{
  const sel = run([ACTIVE, RETIRED], 'WFH Schedule');
  ok('an employee already on a retired pattern keeps it on screen',
     sel.innerHTML.indexOf('WFH Schedule') >= 0,
     'losing the option makes the select fall back to blank, and saving that record clears a ' +
     'schedule nobody meant to clear');
  ok('and it is labelled as retired rather than looking ordinary',
     /WFH Schedule — retired/.test(sel.innerHTML));
  ok('and it stays the selected value', /value="WFH Schedule" selected/.test(sel.innerHTML));
}
{
  // The reverse: a name that is not a schedule at all must NOT be re-inserted.
  const sel = run([ACTIVE], 'Deleted Pattern');
  ok('a name belonging to no pattern is not resurrected',
     sel.innerHTML.indexOf('Deleted Pattern') < 0,
     'the re-insertion is for RETIRED patterns, not for any stale string in the field');
}

// -- the seed fallback must not fire when real schedules exist ------------------------------------
ok('the seed list is only a fallback for an EMPTY register',
   run([RETIRED]).innerHTML.indexOf('Seeded Only') < 0,
   'a register holding one retired pattern is not an empty register; falling back would offer ' +
   'demo names that are not this company\'s patterns');
ok('and it does fire when there are no schedules at all',
   run([]).innerHTML.indexOf('Seeded Only') >= 0);

// -- the half that must NOT change ----------------------------------------------------------------
console.log('\nRetiring a pattern does not re-judge the staff already on it\n');
/* Slice to the next definition at the SAME indent. The first version always looked for
   `\n    def ` (a method), so for the MODULE-LEVEL _rest_weekdays_for it ran on for 22,340
   characters and swallowed unrelated employee-status code containing the word "active" — the test
   convicted correct code. Measure what you claim to measure. */
const pyBody = (name) => {
  const i = appPy.indexOf('def ' + name + '(');
  if (i < 0) { console.error('Could not find ' + name + ' in app.py'); process.exit(2); }
  const lineStart = appPy.lastIndexOf('\n', i) + 1;
  const indent = appPy.slice(lineStart, i).length;          // 0 for module level, 4 for a method
  const end = appPy.indexOf('\n' + ' '.repeat(indent) + 'def ', i + 10);
  return appPy.slice(i, end < 0 ? appPy.length : end);
};
[['_grace_for', 'the grace period their lateness is measured with'],
 ['_late_threshold', 'the time after which they are stamped late'],
 ['_rest_weekdays_for', 'which days are rest days for them'],
 ['_break_minutes_for', 'the unpaid break deducted from their hours']].forEach(f => {
  const body = pyBody(f[0]);
  ok(f[0] + ' ignores the active flag — ' + f[1],
     !/\bactive\b/.test(body),
     'a retired pattern must go on deciding this for whoever is assigned to it, or a manager ' +
     'tidying the register silently moves live attendance (body was ' + body.length + ' chars)');
});

// -- and the toggle makes its effect visible immediately ------------------------------------------
{
  const t = take('async function tkToggleSchedActive(', 'tkToggleSchedActive');
  ok('switching the toggle re-fills the dropdowns it now governs',
     /tkFillSchedSelects\(\)/.test(t),
     'otherwise the change is invisible until a reload — which is how a control gets believed to ' +
     'do nothing in the first place');
  ok('and says what it did', /toast\(/.test(t));
  ok('the register states what "off" means, not just greys the row',
     /not offered for new assignments/.test(take('function _tkRenderSchedRows(', '_tkRenderSchedRows')) ||
     /not offered for new assignments/.test(src));
}

console.log('\n  ' + pass + ' passed, ' + fail + ' failed\n');
process.exit(fail ? 1 : 0);
