/* Rolling a WBS up must not re-scan the schedule once per activity.
 *
 * `_pmWbsChildren` re-filtered the WHOLE activity array on every call, and `_pmTaskPctRoll` calls it
 * once per activity and again for every node it recurses into — so one pass of the '%' column over a
 * project was O(activities^2). Measured on 12 projects x 400 activities: 34,260 calls scanning
 * 13.7M task records, 395.6 ms of client CPU per render of the Projects list, and the Schedule ->
 * Master -> Activities tab pays it three times over (the Completed KPI, the '%' column and the
 * Status column each roll every activity up from nothing).
 *
 * This file holds the two things that are easy to lose separately:
 *   1. the COST — children are a map read, and the map is built once per array;
 *   2. the ANSWER — the index returns exactly the set the filter returned, in the same order,
 *      including the cases a prefix match gets wrong.
 *
 * (2) is the one that matters. `1.1` is a string prefix of `1.10` and is NOT its parent; a `1.2.3.1`
 * belongs to `1.2.3` and must never be counted against `1.2` as well. An index that got either wrong
 * would report a WRONG PERCENTAGE, quickly — and a cost test alone would certify it as fixed.
 *
 *   node tests/wbs_children_cost.js
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

/* A real multi-level WBS, with every shape that has ever been got wrong:
   a 5-level branch, `1.1` beside `1.10`, a duplicated code, an orphan whose parent does not exist,
   an activity with no WBS at all, and a chain deeper than the depth-12 guard. */
const CODES = ['1', '1.1', '1.1.1', '1.1.1.1', '1.1.1.1.1', '1.1.2', '1.2', '1.2.3', '1.2.3.1',
  '1.9', '1.10', '1.10.1', '1.11', '2', '2.1', '2.1', '2.1.1', '3', '', '   ',
  '7.7.7', '7.7.7.1'];
let deep = '9';
for (let i = 0; i < 15; i++) { CODES.push(deep); deep += '.4'; }
while (CODES.length < 400) CODES.push('5.' + CODES.length + '.1');

const PID = 'P1';
const TASKS = CODES.map((c, i) => ({ id: 't' + i, projectId: PID, wbs: c, name: 'Activity ' + i,
  pctComplete: (i * 7) % 101, weight: (i % 5) ? 0 : (i + 1) * 1000,
  start: '2026-03-0' + ((i % 9) + 1), finish: '2026-04-0' + ((i % 9) + 1) }));

/* Instrumented so a scan is COUNTABLE: both the shape the old code used (filter) and the shape the
   index uses (forEach) bump the same counters. */
let scans = 0, records = 0;
function watched(rows) {
  const a = rows.slice();
  ['filter', 'forEach'].forEach(m => {
    a[m] = function (f) { scans++; records += this.length; return Array.prototype[m].call(this, f); };
  });
  return a;
}

const API = new Function(
  'const _PD_COLL = "pm_detail";\n' +
  'const _HR = { pm_tasks: [], pm_detail: [], pm_deliverables: [], pm_costs: [] };\n' +
  'function _pmPct(v) { return Math.max(0, Math.min(100, Math.round(+v || 0))); }\n' +
  // leaves of the log helpers above: a master activity carries no quantity plan, and the day is
  // fixed so a reading dated 'today' means the same thing on every run.
  'function _pdQtyPlan() { return 0; }\n' +
  'function _pmToday() { return "2026-09-04"; }\n' +
  'function _pmDateDiff(a, b) { return Math.round((Date.parse(b) - Date.parse(a)) / 86400000); }\n' +
  'function _pdTaskPct() { return null; }\n' +
  // Lifted with the state they read: an index in a module-level WeakMap, and a pass-scoped memo.
  // A slice without them reports ReferenceError instead of an answer.
  take('let _pmMemo = null;', '_pmMemo') +
  take('function _pmMemoNow(', '_pmMemoNow') +
  take('function _pmMemoDrop(', '_pmMemoDrop') +
  take('function _pmMemoKeys(', '_pmMemoKeys') +
  take('const _pmWbsKidIdx = ', '_pmWbsKidIdx') +
  take('function _pmWbsChildIndex(', '_pmWbsChildIndex') +
  take('function _pmWbsChildren(', '_pmWbsChildren') +
  take('function _pdWeight(', '_pdWeight') +
  take('function _pmTaskPctRoll(', '_pmTaskPctRoll') +
  /* _pmTaskPctRollWalk asks _pmLeafPct what a leaf is worth — daily readings first, the typed
     figure otherwise — so the harness has to lift it and the log helpers it leans on. */
  take('function _pdReadPct(', '_pdReadPct') +
  take('function _pdLog(', '_pdLog') +
  take('function _pdAcc(', '_pdAcc') +
  take('function _pmLeafPct(', '_pmLeafPct') +
  take('function _pmTaskPctRollWalk(', '_pmTaskPctRollWalk') +
  '\nreturn { _pmWbsChildren, _pmTaskPctRoll, _pmMemoDrop };')();

/* The predicate this replaced, written out here rather than referred to. If the index and this
   disagree on ANY node, a percentage on a live project moved. */
const byFilter = (task, all) => {
  const w = String((task && task.wbs) || '').trim();
  if (!w) return [];
  const depth = w.split('.').length;
  return all.filter(t => {
    const c = String(t.wbs || '').trim();
    return c && c !== w && c.indexOf(w + '.') === 0 && c.split('.').length === depth + 1;
  });
};

// ══ the answer ═════════════════════════════════════════════════════════════════════════════════
console.log('\nThe index returns the set the filter returned — same members, same order\n');
{
  let differs = 0, firstBad = '';
  TASKS.forEach(t => {
    const a = byFilter(t, TASKS).map(x => x.id).join(',');
    const b = (API._pmWbsChildren(t, TASKS) || []).map(x => x.id).join(',');
    if (a !== b && !differs++) firstBad = 'wbs "' + t.wbs + '": filter [' + a + '] index [' + b + ']';
  });
  ok('every activity resolves to the same children as a full re-filter', differs === 0,
     differs + ' of ' + TASKS.length + ' disagree — first: ' + firstBad);

  const kids = w => (API._pmWbsChildren(TASKS.find(t => t.wbs === w), TASKS) || []).map(t => t.wbs);
  // The two that a prefix match gets wrong, named so a regression says WHICH rule broke.
  ok('"1.10" is not a child of "1.1" — a string prefix is not a parent',
     kids('1.1').indexOf('1.10') < 0 && kids('1').indexOf('1.10') >= 0,
     'children of 1.1: [' + kids('1.1') + ']');
  ok('a grandchild belongs to its parent only, never also to its grandparent',
     kids('1.2').join() === '1.2.3' && kids('1.2.3').join() === '1.2.3.1');
  ok('duplicated codes both appear, in array order', kids('2').join() === '2.1,2.1');
  ok('an orphan still owns its own children', kids('7.7.7').join() === '7.7.7.1');
  ok('an activity with no WBS has no children, and does not adopt the whole schedule',
     API._pmWbsChildren({ wbs: '' }, TASKS).length === 0 &&
     API._pmWbsChildren({ wbs: '   ' }, TASKS).length === 0);
  ok('a five-level branch is walked to the bottom', kids('1.1.1.1').join() === '1.1.1.1.1');
}

// ══ the cost ═══════════════════════════════════════════════════════════════════════════════════
console.log('\nAnd it costs one pass over the array, not one per activity\n');
{
  const W = watched(TASKS);
  scans = 0; records = 0;
  W.forEach(t => API._pmTaskPctRoll(t, W, PID));
  // `W.forEach` itself is one of the counted calls, hence the +1.
  ok('one pass of the % column builds the index once', scans <= 2,
     'got ' + scans + ' whole-array passes for ' + W.length + ' activities. Before the index this ' +
     'was one filter per call — 34,260 calls across a 12-project portfolio.');
  ok('and reads each activity a constant number of times, not once per activity',
     records <= W.length * 3,
     'read ' + records.toLocaleString() + ' task records for ' + W.length + ' activities. ' +
     'O(activities^2) on this fixture is ' + (W.length * W.length).toLocaleString() + '.');

  // The Activities tab asks three times per activity. That must not cost three passes.
  API._pmMemoDrop();
  const W2 = watched(TASKS);
  scans = 0; records = 0;
  W2.forEach(t => API._pmTaskPctRoll(t, W2, PID));
  W2.forEach(t => API._pmTaskPctRoll(t, W2, PID));
  W2.forEach(t => API._pmTaskPctRoll(t, W2, PID));
  ok('three passes over the same array still build one index', scans <= 4,
     'got ' + scans + '. The Completed KPI, the % column and the Status column each roll every ' +
     'activity up; the index is keyed on the identity of the array they share.');
}

// ══ the memo may not outlive the render ════════════════════════════════════════════════════════
console.log('\nAnd the roll-up memo lasts exactly one synchronous pass\n');
(async () => {
  const cache = take('function _pmMemoNow(', '_pmMemoNow');
  ok('the cache is dropped by a microtask queued when it is created',
     /Promise\.resolve\(\)\.then\(_pmMemoDrop\)/.test(cache),
     'array identity cannot see an in-place field edit (pdDailyEntrySave does `r.log = log`), so ' +
     'a memo that outlived the render would serve a percentage from before the entry was saved');

  const t = TASKS.find(x => x.wbs === '3');       // a leaf: its own typed number, no children
  const first = API._pmTaskPctRoll(t, TASKS, PID).pct;
  t.pctComplete = (first + 40) % 101;             // an IN-PLACE edit: no array is replaced
  ok('within one pass the answer is stable', API._pmTaskPctRoll(t, TASKS, PID).pct === first);
  await null;                                     // the render pass ends
  ok('and the next pass sees the edit', API._pmTaskPctRoll(t, TASKS, PID).pct === t.pctComplete,
     'got ' + API._pmTaskPctRoll(t, TASKS, PID).pct + ', want ' + t.pctComplete +
     ' — a stale roll-up that shows LESS than the data says is the worst outcome available here');

  console.log('\n  ' + pass + ' passed, ' + fail + ' failed\n');
  process.exit(fail ? 1 : 0);
})();