/* Two things a non-manager hit in production, tested against the code that ships.
 *
 * 1. WBS ORDER. The master-activity picker listed bare codes in register order —
 *    1.2.4.4, 1.4.6.3.1, 1.4.6.3.2, 1.3.2, 1.4.6.2 … — with no sort of any kind, and showed
 *    `wbs || name`, so once an activity had a WBS you could never see which activity it was.
 *    String order is not enough: it puts "1.10" before "1.2".
 *
 * 2. A 403 IS NOT A CONNECTION PROBLEM. `pm_costs` is manager-only. Overview and Schedule both
 *    listed it in `need`, so every staff user opening any project met "Could not load this tab —
 *    check your connection and try again", on the tab they land on by default, forever. Retrying
 *    a permission decision never succeeds.
 *
 *   node tests/pm_access_and_wbs.js
 */
const fs = require('fs');
const path = require('path');

const src = fs.readFileSync(path.join(__dirname, '..', 'templates', 'index.html'), 'utf8');

let pass = 0, fail = 0;
const ok = (name, cond, extra) => {
  if (cond) { pass++; console.log('  ok    ' + name); }
  else { fail++; console.log('  FAIL  ' + name + (extra ? '\n        ' + extra : '')); }
};
const eq = (n, got, want) => ok(n, JSON.stringify(got) === JSON.stringify(want),
  'got ' + JSON.stringify(got) + '\n        want ' + JSON.stringify(want));

/* ── extract _wbsCmp from the shipping file ─────────────────────────────────── */
const ci = src.indexOf('function _wbsCmp(');
if (ci < 0) { console.error('_wbsCmp not found — do NOT delete this test, update the marker'); process.exit(2); }
const cend = src.indexOf('\n}', ci) + 2;
const api = {};
new Function(src.slice(ci, cend) + '\nObject.assign(this, { _wbsCmp });').call(api);
const { _wbsCmp } = api;

console.log('\nMaster-activity picker + tab access\n');

/* ── the exact codes from the reported screenshot, in the order shown ───────── */
const REPORTED = ['1.2.4.4', '1.4.6.3.1', '1.4.6.3.2', '1.3.2', '1.4.6.2', '1.4.5.2', '1.4.6.6.2',
  '1.4.4.1.2', '1.4.5', '1.4.6.6.4', '1.4.6.3', '1.4.6.4.2', '1.4.6.4.5', '1.4.4.3', '1.4.4.4.4',
  '1.3.1.3', '1.4.4.1.1', '1.4.6.6.3', '1.2.1'];
const sorted = REPORTED.slice().sort(_wbsCmp);
eq('the reported list sorts into schedule order', sorted,
  ['1.2.1', '1.2.4.4', '1.3.1.3', '1.3.2', '1.4.4.1.1', '1.4.4.1.2', '1.4.4.3', '1.4.4.4.4',
   '1.4.5', '1.4.5.2', '1.4.6.2', '1.4.6.3', '1.4.6.3.1', '1.4.6.3.2', '1.4.6.4.2', '1.4.6.4.5',
   '1.4.6.6.2', '1.4.6.6.3', '1.4.6.6.4']);

/* ── the property a plain string sort cannot have ──────────────────────────── */
eq('1.2 before 1.10 (string order gets this backwards)',
   ['1.10', '1.2', '1.9'].sort(_wbsCmp), ['1.2', '1.9', '1.10']);
ok('and a plain string sort really does disagree',
   JSON.stringify(['1.10', '1.2', '1.9'].sort()) !== JSON.stringify(['1.2', '1.9', '1.10']));
eq('a parent sorts before its own children', ['1.4.5.2', '1.4.5'].sort(_wbsCmp), ['1.4.5', '1.4.5.2']);
eq('deep codes stay under their parent',
   ['1.4.4.4.4', '1.4.4.3'].sort(_wbsCmp), ['1.4.4.3', '1.4.4.4.4']);
eq('numbered activities sort before un-numbered ones',
   ['Mobilisation', '2.1', '10.1'].sort(_wbsCmp), ['2.1', '10.1', 'Mobilisation']);
eq('two un-numbered activities sort by name',
   ['Testing', 'Mobilisation'].sort(_wbsCmp), ['Mobilisation', 'Testing']);
ok('comparator is symmetric', _wbsCmp('1.2', '1.10') < 0 && _wbsCmp('1.10', '1.2') > 0);
ok('equal codes compare equal', _wbsCmp('1.4.4.1', '1.4.4.1') === 0);
[undefined, null, '', '.', '..'].forEach(v => {
  let threw = false;
  try { _wbsCmp(v, '1.1'); _wbsCmp('1.1', v); _wbsCmp(v, v); } catch (e) { threw = true; }
  ok('junk input (' + JSON.stringify(v) + ') does not throw', !threw);
});

/* ── the option source keeps the VALUE and enriches only the LABEL ──────────── */
const optSrc = src.slice(src.indexOf("if (src === 'pm_task_opts') {"), src.indexOf("if (src === 'pm_assignees')"));
ok('the option value is still the bare ref', /v:\s*v\b/.test(optSrc),
   'the stored taskRef must not change — _pdMasterOf matches it by string equality');
ok('the label carries the activity name', /l:\s*\(nm && nm !== v\)/.test(optSrc));
ok('the list is sorted with the WBS comparator', /\.sort\(\(a, b\) => _wbsCmp\(a\.v, b\.v\)\)/.test(optSrc));
ok('duplicates are still collapsed', /seen\[v\]/.test(optSrc));

/* ── _pdMasterOf still matches on the unchanged ref ─────────────────────────── */
ok('_pdTaskRef is unchanged (wbs || name)',
   /function _pdTaskRef\(t\) \{ return String\(\(t && \(t\.wbs \|\| t\.name\)\) \|\| ''\)\.trim\(\); \}/.test(src));
ok('_pdMasterOf still compares _pdTaskRef(t) === ref',
   /_pmScopeFor\('pm_tasks', pid\)\.find\(t => _pdTaskRef\(t\) === ref\)/.test(src));

/* ── the select renderer handles BOTH shapes ───────────────────────────────── */
const selLine = src.split('\n').find(l => l.indexOf("if (f.type === 'select')") >= 0) || '';
ok('the select renderer was found', !!selLine);
ok('renderer reads .v/.l when given an object', /typeof o === 'object'\) \? o\.v : o/.test(selLine));
ok('renderer still accepts a plain string', /: o,/.test(selLine) || /: o;/.test(selLine) || /: o\b/.test(selLine));
ok('the selected-option test compares values, not labels',
   /String\(val\) === String\(_v\)/.test(selLine),
   'comparing val to the LABEL would stop the saved value showing as selected');

/* ── a 403 must not be reported as a connection failure ─────────────────────── */
const tabFn = src.slice(src.indexOf('async function pmTab('), src.indexOf('/* ---------- Overview tab'));
ok('pmTab separates denied from broken', /const _denied = _failed\.filter\(c => \(_COLL_ERR\[c\] \|\| \{\}\)\.status === 403\)/.test(tabFn));
ok('only a real failure shows the retry card', /if \(_broken\.length\) \{/.test(tabFn));
ok('the retry card is no longer gated on _failed.length', !/if \(_failed\.length\) \{/.test(tabFn));
ok('a denied register is named to the user', /_denied\.length/.test(tabFn) && /_PM_COLL_LABEL/.test(tabFn));

/* ── Schedule must not demand a register it never reads ─────────────────────── */
const tabs = src.slice(src.indexOf('const _PM_TABS = ['), src.indexOf('const _PM_CLICK_COLLS'));
const schedLine = tabs.split('\n').find(l => l.indexOf("k: 'schedule'") >= 0) || '';
ok('the schedule tab entry was found', !!schedLine);
ok('schedule no longer requires pm_costs', schedLine.indexOf('pm_costs') < 0, schedLine.trim());
ok('schedule still requires what it does read',
   ['pm_projects', 'pm_tasks', 'pm_detail', 'pm_schedules'].every(c => schedLine.indexOf(c) >= 0));
// and prove the premise: pmRenderSchedule genuinely never touches pm_costs
const schedFn = src.slice(src.indexOf('function pmRenderSchedule('), src.indexOf('function pmRenderCosts('));
ok('pmRenderSchedule really does not read pm_costs', schedFn.indexOf('pm_costs') < 0);

/* ── the denied collection degrades to [] rather than throwing ──────────────── */
ok('_pmScopeFor is null-safe on a denied register',
   /const _pmScopeFor = \(coll, pid\) => \(_HR\[coll\] \|\| \[\]\)/.test(src),
   'if this stops defaulting to [], a denied collection crashes the tab instead of emptying it');

console.log('\n' + pass + ' passed, ' + fail + ' failed\n');
process.exit(fail ? 1 : 0);
