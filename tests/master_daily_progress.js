/* Daily progress on the Master Schedule, and the two locks that make it honest.
 *
 *   · a PARENT is not the reporter's to type — it is the weighted average of its sub-tasks
 *   · a sub-task the site reports against in the DETAIL SCHEDULE is not theirs either
 *   · everything else is
 *
 * THE INVARIANT THIS FILE EXISTS FOR. The arithmetic already lived in _pmTaskPctRollWalk before any
 * of this: children > detail > typed. The new part is _pmDailyLock, which decides whether the entry
 * table offers somebody an input. The two are separate functions and they MUST agree.
 *
 * If _pmDailyLock said "editable" where the roll-up reads children, the number a person filed would
 * be accepted, stored, and then silently never shown — no error, no empty state, just a percentage
 * that refuses to move for reasons nothing on screen explains. That is the exact defect this feature
 * exists to prevent, so the first test runs BOTH over the same tree and holds them together.
 *
 *   node tests/master_daily_progress.js
 */
const fs = require('fs');
const path = require('path');

const src = fs.readFileSync(path.join(__dirname, '..', 'templates', 'index.html'), 'utf8');

let pass = 0, fail = 0;
const ok = (n, c, extra) => {
  if (c) { pass++; console.log('  ok    ' + n); }
  else { fail++; console.log('  FAIL  ' + n + (extra ? '\n        ' + extra : '')); }
};

/* The real bodies, lifted out of the page. Each runs to the next top-level declaration or block
   comment, which is how every other test in this repo slices this file. */
function take(name) {
  const re = new RegExp('\\n(?:const |)(?:async )?function ' + name.replace(/\$/g, '\\$') + '\\s*\\(');
  const i = src.search(re);
  if (i < 0) {
    console.error('could not find ' + name + ' — update the marker, do NOT delete this test.');
    process.exit(2);
  }
  const from = i + 1;
  const ends = ['\nfunction ', '\nasync function ', '\nconst ', '\n/* ']
    .map(m => src.indexOf(m, from + 10)).filter(x => x > 0);
  return src.slice(from, ends.length ? Math.min.apply(null, ends) : from + 4000);
}

const NEEDED = ['_pmLeafPct', '_pmDailyLock', '_pmTaskPctRollWalk', '_pmWbsChildIndex',
                '_pmWbsChildren', '_pdLog', '_pdAcc', '_pdReadPct'];
const bodies = NEEDED.map(take).join('\n');

/* Stubs for the leaves of the dependency tree, so the functions under test are the REAL ones and
   everything they lean on is simple and visible here. */
const PRELUDE = `
  const _pmPct = v => { const n = Math.round(+v || 0); return n < 0 ? 0 : (n > 100 ? 100 : n); };
  const _pdQtyPlan = () => 0;                       // master activities carry no quantity plan
  const _pmToday = () => TODAY;
  const _pdWeight = t => (t && +t.w) || 1;
  const _pdTaskPct = (t, pid) => DETAIL[(t && (t.wbs || t.name)) || ''] || null;
  // The index caches on the identity of the array handed in; the WeakMap it caches into is declared
  // beside _pmWbsChildIndex in the page, outside the function body this test lifts.
  const _pmWbsKidIdx = new WeakMap();
`;
const build = (todayVal, detail) => new Function('TODAY', 'DETAIL', PRELUDE + bodies +
  '\nreturn { leaf: _pmLeafPct, lock: _pmDailyLock, roll: _pmTaskPctRollWalk };')(todayVal, detail);

const TODAY = '2026-09-04';

// ══ 1. the lock and the roll-up agree, over a real tree ════════════════════════════════════════
console.log('\nThe lock and the arithmetic never disagree\n');
{
  const tasks = [
    { id: 'a', wbs: '1', name: 'Concept' },                        // parent of 1.1, 1.2
    { id: 'b', wbs: '1.1', name: 'Legal', pctComplete: 40 },       // leaf, no detail  -> editable
    { id: 'c', wbs: '1.2', name: 'Survey' },                       // parent of 1.2.1
    { id: 'd', wbs: '1.2.1', name: 'Topo', pctComplete: 10 },      // leaf, HAS detail -> locked
    { id: 'e', wbs: '2', name: 'Design', pctComplete: 25 },        // leaf, no detail  -> editable
    { id: 'f', wbs: '1.10', name: 'Tenth', pctComplete: 90 },      // NOT a child of 1.1
    // BOTH a parent AND reported against in detail. Only the ORDER of the two checks decides this
    // one, so without it a lock that asked about detail first would agree with the roll-up on every
    // other row and be wrong here — silently, on exactly the activity where two sources disagree.
    { id: 'g', wbs: '3', name: 'Fit-out' },
    { id: 'h', wbs: '3.1', name: 'Ceilings', pctComplete: 80 },
  ];
  const M = build(TODAY, { '1.2.1': { pct: 70, n: 3 }, '3': { pct: 5, n: 9 } });

  const expect = { a: 'children', b: null, c: 'children', d: 'detail', e: null, f: null,
                   g: 'children', h: null };
  let agree = 0, bad = [];
  tasks.forEach(t => {
    const lock = M.lock(t, tasks, 'P1');
    const from = M.roll(t, tasks, 'P1', 0).from;
    if (lock !== expect[t.id]) bad.push(t.wbs + ': lock=' + lock + ' expected ' + expect[t.id]);
    // the two must describe the same thing
    const rollLocked = from === 'children' || from === 'detail';
    if (rollLocked !== !!lock) bad.push(t.wbs + ': lock=' + lock + ' but the roll-up reads ' + from);
    else agree++;
  });
  ok('every activity is locked exactly when the roll-up ignores what was typed',
     bad.length === 0, bad.join('\n        '));
  ok('and all eight were actually compared', agree === 8, 'compared ' + agree);

  ok('a parent that is ALSO reported in detail follows its children',
     M.roll(tasks[6], tasks, 'P1', 0).pct === 80 && M.roll(tasks[6], tasks, 'P1', 0).from === 'children',
     'got ' + JSON.stringify(M.roll(tasks[6], tasks, 'P1', 0)) + ' — the sub-tasks are the finer ' +
     'record, and the detail lines under a parent are already counted through them');

  ok('1.10 is not treated as a child of 1.1', M.lock(tasks[1], tasks, 'P1') === null,
     'WBS is compared segment-wise, not as a string prefix — 1.10 belongs to 1, not to 1.1');
}

// ══ 2. a parent is the average of its sub-tasks ════════════════════════════════════════════════
console.log('\nA parent is its sub-tasks, weighted\n');
{
  const tasks = [
    { id: 'p', wbs: '1', name: 'Phase' },
    { id: 'x', wbs: '1.1', name: 'A', pctComplete: 100, w: 1 },
    { id: 'y', wbs: '1.2', name: 'B', pctComplete: 0, w: 1 },
  ];
  const M = build(TODAY, {});
  ok('equal weights give the plain average', M.roll(tasks[0], tasks, 'P1', 0).pct === 50,
     'got ' + M.roll(tasks[0], tasks, 'P1', 0).pct);

  tasks[2].w = 3;                                   // B is three times the work
  ok('and a heavier sub-task pulls it down', M.roll(tasks[0], tasks, 'P1', 0).pct === 25,
     'got ' + M.roll(tasks[0], tasks, 'P1', 0).pct + ' — the roll-up must weight, not just average');

  ok('typing on the parent changes nothing',
     (tasks[0].pctComplete = 99, M.roll(tasks[0], tasks, 'P1', 0).pct === 25),
     'a parent that answers to a typed figure is the bug the lock exists to make visible');
}

// ══ 3. the detail schedule wins over a typed figure, but only when it has rows ═════════════════
console.log('\nThe Detail Schedule wins — when it has something to say\n');
{
  const t = { id: 'd', wbs: '3.1', name: 'Ductwork', pctComplete: 20 };
  const tasks = [t];

  const withRows = build(TODAY, { '3.1': { pct: 65, n: 4 } });
  ok('a reported activity takes the site\'s number', withRows.roll(t, tasks, 'P1', 0).pct === 65);
  ok('and is locked', withRows.lock(t, tasks, 'P1') === 'detail');

  /* _pdTaskPct returns NULL when no detail line points at the activity — so an activity that COULD
     be reported in detail, but has not been yet, stays the planner's to fill in. Locking it would
     pin it at 0% with no way to move it and nothing on screen saying why. */
  const noRows = build(TODAY, {});
  ok('an activity with no detail lines yet is still editable',
     noRows.lock(t, tasks, 'P1') === null);
  ok('and keeps its typed figure until the site reports', noRows.roll(t, tasks, 'P1', 0).pct === 20);
}

// ══ 4. the daily log is what a leaf is worth ═══════════════════════════════════════════════════
console.log('\nA leaf is worth its latest reading\n');
{
  const M = build(TODAY, {});
  ok('no log falls back to the typed figure',
     M.leaf({ pctComplete: 30 }).pct === 30 && M.leaf({ pctComplete: 30 }).from === 'typed');

  const logged = { pctComplete: 30, log: [
    { d: '2026-09-01', pct: 10 }, { d: '2026-09-04', pct: 55 }, { d: '2026-09-02', pct: 40 }] };
  ok('a log overrides it', M.leaf(logged).pct === 55 && M.leaf(logged).from === 'daily',
     'got ' + JSON.stringify(M.leaf(logged)));
  ok('and out-of-order entries still read chronologically', M.leaf(logged).pct === 55,
     '_pdLog sorts by date, so filing a correction for an earlier day must not become "now"');

  const future = { pctComplete: 30, log: [{ d: '2026-09-01', pct: 10 }, { d: '2027-01-01', pct: 99 }] };
  ok('a reading dated in the future is not counted as today', M.leaf(future).pct === 10,
     'got ' + M.leaf(future).pct);
}

// ══ 5. the table offers an input only where there is one to offer ══════════════════════════════
console.log('\nThe table only offers an input where a figure is the reporter\'s\n');
{
  const entry = take('pmDailyEntry');
  ok('a locked row renders no input', /r\.lock\s*\n?\s*\?\s*'<span/.test(entry.replace(/\s+/g, ' ')) ||
     /r\.lock[\s\S]{0,80}\?[\s\S]{0,40}<span/.test(entry),
     'the ternary that chooses between a span and an input is the whole lock in the UI');
  ok('and an unlocked row does', /class="form-control pm-e"/.test(entry));
  ok('the reason is shown, not implied',
     /from sub-tasks/.test(entry) && /from Detail Schedule/.test(entry),
     'a greyed row with no explanation sends somebody looking for the field that is missing');
  ok('locked rows are listed, not hidden', !/if \(r\.lock\) return;/.test(entry),
     'a parent absent from the list reads as a gap in the schedule');

  const save = take('pmDailyEntrySave');
  ok('save reads only the editable inputs', /querySelectorAll\('\.pm-e'\)/.test(save));
  ok('it files against pm_tasks', /\/api\/coll\/pm_tasks\//.test(save));
  ok('it keeps one reading per day', /filter\(e => String\(e\.d\) !== day\)/.test(save),
     'filing twice in a day must correct the day, not append a second reading to it');
  ok('an unchanged row files nothing',
     /String\(i\.value\)\.trim\(\) !== String\(i\.dataset\.was\)\.trim\(\)/.test(save));
  ok('a failed row is named', /failed\.push\(\(r\.name \|\| r\.id\)/.test(save),
     '"3 of 5 saved" says something is wrong and nothing about which activity to go back to');
  ok('a partial save is a dialog, not a toast', /tkAlert\(\{ title: _t\('Some progress was not filed'\)/.test(save),
     'a green "Filed" over a partial save sends somebody home believing the report was complete');
  ok('and the filing is audited', /tkAudit\('Master progress filed'/.test(save));
  /* The rows are updated in place and _pmLeafPct reads r.log on every call, so the screen only
     needs re-rendering. Re-downloading pm_tasks after every daily report would be a full collection
     fetch for figures the page can already recompute. */
  ok('the screen re-renders without re-downloading the collection',
     /_pmReload\(\);/.test(save) && !/tkLoadColl\('pm_tasks'/.test(save));
}

// ══ 6. the button ══════════════════════════════════════════════════════════════════════════════
console.log('\nAnd it is reachable\n');
{
  ok('the Master Timeline offers Daily progress', /onclick="pmDailyEntry\(/.test(src));
  const detailView = src.slice(src.indexOf("_pmSchedBuild['d-timeline']"), src.indexOf("_pmSchedBuild['d-timeline']") + 200);
  ok('and the Detail Timeline is left alone', !/pmDailyEntry/.test(detailView),
     'the detail schedule already has pdDailyEntry; two buttons filing to different collections ' +
     'from the same screen is a way to file against the wrong one');
}

console.log('\n  ' + pass + ' passed, ' + fail + ' failed\n');
process.exit(fail ? 1 : 0);
