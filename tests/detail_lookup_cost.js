/* Looking up a master activity must not scan the portfolio.
 *
 * `_pdMasterOf` resolved a detail line's activity with
 *     _pmScopeFor('pm_tasks', pid).find(t => _pdTaskRef(t) === ref)
 * — a full filter over EVERY activity in the whole portfolio, then a linear search of the result,
 * on every single lookup. That is fine if a lookup happens a few times. It does not:
 *
 *   · `_pdOrderKey` calls it once per row PER COMPARISON, so sorting is O(rows x log rows x tasks);
 *   · `_pdGroupOf` calls it once per row again, in the Timeline, the Register, the group filter,
 *     the daily-progress dialog and the roll-up.
 *
 * Measured on a realistic portfolio — 934 activities across 8 projects, 400 detail lines on the big
 * one — ONE `_pdAllRows` did 5,767 whole-array scans and took 83 ms on a fast laptop, and the nine
 * calls a single Schedule render makes came to 51,903 scans and 468 ms. A phone is four to six
 * times slower again. That is the Schedule tab sitting on skeleton loaders, and it is a regression
 * that arrived WITH the ordering fix in #125: the sort it replaced compared two strings and never
 * looked an activity up at all.
 *
 * This file holds two things that are easy to lose separately:
 *   1. the COST — a lookup is a map read, not a scan;
 *   2. the ANSWER — the index resolves to exactly the activity `.find` resolved to, including when
 *      two activities share a reference, and including after the data is reloaded.
 *
 * A test for (1) without (2) would happily certify a fast function that returns the wrong activity.
 *
 *   node tests/detail_lookup_cost.js
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
  const ends = ['\nfunction ', '\nasync function ', '\nconst ', '\nlet ']
    .map(e => src.indexOf(e, i + 10)).filter(x => x > 0);
  return src.slice(i, Math.min.apply(null, ends));
};

/* A portfolio the size of the one that made this visible. */
const PROJECTS = 8, BIG = 'P0';
const TASKS = [];
for (let p = 0; p < PROJECTS; p++) {
  const pid = 'P' + p, n = pid === BIG ? 500 : 62;
  for (let i = 0; i < n; i++) {
    TASKS.push({ id: pid + '-t' + i, projectId: pid,
      wbs: '1.' + ((i % 9) + 1) + '.' + (((i / 9) | 0) % 9 + 1) + '.' + (i % 7 + 1),
      name: 'Activity ' + i });
  }
}
/* The fixture has to CONTAIN the cases the assertions are about, or they pass on nothing.
   A first version of this file generated 400 rows with 400 DISTINCT references, none blank, all on
   one project — so three mutations went undetected: keeping only the LAST row per reference was
   indistinguishable from correct (every group held one row), filing unlinked lines into a group of
   their own never fired (no row had a blank reference), and dropping the project from the cache key
   changed nothing (only one project was ever asked for). Each of those is a real way to report a
   wrong percentage. So, deliberately:
     · references COLLIDE, so a group holds several lines and its cardinality is observable;
     · some lines report against NOTHING;
     · a SECOND project carries detail rows of its own. */
const SECOND = 'P1';
/* References are taken FROM the activities rather than generated alongside them, so every linked
   line resolves to a real activity AND several lines land on the same one. Generating them
   independently produced 400 distinct references for 400 rows — every group held exactly one row,
   which is why "keep only the last row per activity" survived undetected. */
const refsOf = pid => TASKS.filter(t => t.projectId === pid).map(t => t.wbs);
const BIG_REFS = refsOf(BIG).slice(0, 60);
const SECOND_REFS = refsOf(SECOND).slice(0, 12);
const ROWS = [];
for (let i = 0; i < 400; i++) {
  const unfiled = i % 50 === 7;                       // 8 lines reporting against nothing
  ROWS.push({ id: 'd' + i, projectId: BIG,
    taskRef: unfiled ? (i % 100 === 7 ? '' : '   ')   // blank, and whitespace-only
                     : BIG_REFS[i % BIG_REFS.length],
    category: ['HVAC', 'Electrical', 'Plumbing', 'Civil'][i % 4],
    name: 'Detail line ' + i, start: '2026-0' + ((i % 9) + 1) + '-01', log: [] });
}
for (let i = 0; i < 40; i++) {                        // the second project's own lines
  ROWS.push({ id: 's' + i, projectId: SECOND,
    taskRef: SECOND_REFS[i % SECOND_REFS.length],
    category: 'HVAC', name: 'Other project line ' + i, start: '2026-03-01', log: [] });
}

let scans = 0;
const build = () => new Function('TASKS', 'ROWS', 'bump',
  'const _HR = { pm_tasks: TASKS, pm_detail: ROWS };\n' +
  'const _PD_COLL = "pm_detail";\n' +
  'const _pmScopeFor = (c, pid) => { bump(); return (_HR[c] || []).filter(x => x.projectId === pid); };\n' +
  take('function _pmWbsCmp(', '_pmWbsCmp') +
  'let _pdMIdx = { arr: null, pid: null, map: null };\n' +
  take('function _pdMasterIndex(', '_pdMasterIndex') +
  take('function _pdTaskRef(', '_pdTaskRef') +
  take('function _pdMasterOf(', '_pdMasterOf') +
  take('function _pdOrderKey(', '_pdOrderKey') +
  take('function _pdOrderCmp(', '_pdOrderCmp') +
  take('function _pdAllRows(', '_pdAllRows') +
  '\nreturn { _pdAllRows: _pdAllRows, _pdMasterOf: _pdMasterOf,' +
  ' reload: rows => { _HR.pm_tasks = rows; TASKS = rows; } };')(TASKS, ROWS, () => { scans++; });

// ══ the cost ═══════════════════════════════════════════════════════════════════════════════════
console.log('\nA lookup is a map read, not a scan through the portfolio\n');
{
  const API = build();
  scans = 0;
  const out = API._pdAllRows(BIG);
  const onBig = ROWS.filter(r => r.projectId === BIG).length;
  ok('the sort returns every row on this project and none from the other',
     out.length === onBig && out.every(r => r.projectId === BIG),
     'got ' + out.length + ' of ' + onBig);
  ok('and it scans the task list at most twice, not thousands of times',
     scans <= 2,
     'got ' + scans.toLocaleString() + ' whole-array scans for ONE sort. Before the index it was ' +
     '5,767: _pdOrderKey calls _pdMasterOf twice per comparison, and _pdMasterOf filtered every ' +
     'activity in the portfolio each time.');

  scans = 0;
  for (let i = 0; i < 9; i++) API._pdAllRows(BIG);
  ok('nine calls — one render pass — stay in single figures',
     scans <= 9,
     'got ' + scans.toLocaleString() + '. A Schedule render calls this from the Timeline, the ' +
     'Register, the group list, the % column and the daily dialog; before the index that pass ' +
     'cost 51,903 scans and 468 ms on a laptop, several seconds on a phone.');
}

// ══ the answer ═════════════════════════════════════════════════════════════════════════════════
console.log('\nAnd it resolves to the same activity the scan resolved to\n');
{
  const API = build();
  const byRef = {};
  TASKS.filter(t => t.projectId === BIG).forEach(t => {
    const k = String(t.wbs || t.name || '').trim();
    if (k && !(k in byRef)) byRef[k] = t;      // first wins, exactly as .find did
  });
  const sample = ROWS.filter((_r, i) => i % 37 === 0);
  const wrong = sample.filter(r => (API._pdMasterOf(BIG, r) || {}).id !== (byRef[r.taskRef] || {}).id);
  ok('every sampled line resolves to the activity a linear search would have found',
     wrong.length === 0,
     wrong.length + ' of ' + sample.length + ' disagree, e.g. ' + JSON.stringify(wrong[0] || {}));

  ok('a line pointing at nothing still resolves to nothing',
     API._pdMasterOf(BIG, { taskRef: '' }) === null &&
     API._pdMasterOf(BIG, { taskRef: '9.9.9.9' }) === null);

  /* Two activities sharing a reference is a data problem, and the answer must not quietly change
     to the other one just because the lookup got faster. */
  const dupA = { id: 'dup-a', projectId: 'PD', wbs: '7.7', name: 'First' };
  const dupB = { id: 'dup-b', projectId: 'PD', wbs: '7.7', name: 'Second' };
  const D = build();
  D.reload(TASKS.concat([dupA, dupB]));
  ok('where two activities share a reference the FIRST still wins',
     (D._pdMasterOf('PD', { taskRef: '7.7' }) || {}).id === 'dup-a',
     'got ' + JSON.stringify(D._pdMasterOf('PD', { taskRef: '7.7' })));
}

// ══ staleness ══════════════════════════════════════════════════════════════════════════════════
console.log('\nAnd it cannot serve yesterday\'s answer\n');
{
  const API = build();
  ok('before the reload the reference is unknown',
     API._pdMasterOf('PX', { taskRef: '4.4' }) === null);

  /* tkLoadColl assigns `_HR[name] = j.items || []` — a NEW array on every fetch. The index is keyed
     on that array's identity, so a reload can never be answered from the previous one. */
  API.reload(TASKS.concat([{ id: 'new-1', projectId: 'PX', wbs: '4.4', name: 'Added later' }]));
  ok('after a reload replaces the array, the new activity is found',
     (API._pdMasterOf('PX', { taskRef: '4.4' }) || {}).id === 'new-1',
     'the index is keyed on the identity of _HR.pm_tasks, which tkLoadColl replaces wholesale on ' +
     'every fetch; keying it on anything else would let a stale index outlive the data');
}

// ══ the shape, in the source ═══════════════════════════════════════════════════════════════════
console.log('\nThe scan is gone from the source, not merely bypassed\n');
{
  const mo = take('function _pdMasterOf(', '_pdMasterOf');
  ok('_pdMasterOf no longer filters the task list itself',
     !/_pmScopeFor\('pm_tasks'/.test(mo),
     'it still contains a portfolio-wide filter:\n' + mo);
  ok('it reads the index instead', /_pdMasterIndex\(pid\)\.get\(ref\)/.test(mo));
  const mi = take('function _pdMasterIndex(', '_pdMasterIndex');
  ok('the index is keyed on the identity of the task array',
     /_pdMIdx\.arr === arr/.test(mi),
     'without this the index outlives the data it was built from');
  ok('and on the project, so two projects cannot share one index',
     /_pdMIdx\.pid === pid/.test(mi));
  ok('it keeps the FIRST activity for a reference', /if \(k && !map\.has\(k\)\) map\.set\(k, t\);/.test(mi));
}

// ══ the second scan: one group-by instead of one filter+sort per activity ══════════════════════
/* _pdTaskPct did `_pdAllRows(pid).filter(...)`, and _pmTaskPctRoll calls it once per ACTIVITY.
   Indexing the activity lookup above made each of those sorts cheap; it did not stop 500 of them
   happening. Measured at 500 activities against 400 detail lines: 497 ms and 500 full sorts for ONE
   pass of the '%' column, and the Activities table, the Timeline and the roll-up each do that pass. */
console.log('\nThe %-complete column groups once, instead of sorting per activity\n');
{
  let allRows = 0;
  const P = new Function('TASKS', 'ROWS', 'bump',
    'const _HR = { pm_tasks: TASKS, pm_detail: ROWS };\n' +
    'const _PD_COLL = "pm_detail";\n' +
    'let _pdSchedId = "";\n' +
    'function _pmToday(){ return "2026-08-15"; }\n' +
    'function _pmPct(v){ return Math.max(0, Math.min(100, Math.round(+v || 0))); }\n' +
    'function _pmDateDiff(a,b){ return Math.round((Date.parse(b) - Date.parse(a)) / 86400000); }\n' +
    'const _pmScopeFor = (c, pid) => (_HR[c] || []).filter(x => x.projectId === pid);\n' +
    take('function _pmWbsCmp(', '_pmWbsCmp') +
    'let _pdMIdx = { arr: null, pid: null, map: null };\n' +
    take('function _pdMasterIndex(', '_pdMasterIndex') +
    take('function _pdTaskRef(', '_pdTaskRef') +
    take('function _pdMasterOf(', '_pdMasterOf') +
    take('function _pdOrderKey(', '_pdOrderKey') +
    take('function _pdOrderCmp(', '_pdOrderCmp') +
    'const _pdAllRowsReal = ' + take('function _pdAllRows(', '_pdAllRows')
      .replace('function _pdAllRows', 'function') + ';\n' +
    'function _pdAllRows(pid) { bump(); return _pdAllRowsReal(pid); }\n' +
    take('function _pdScheds(', '_pdScheds') + take('function _pdUnfiled(', '_pdUnfiled') +
    take('function _pdCurSched(', '_pdCurSched') + take('function _pdRows(', '_pdRows') +
    take('function _pdLog(', '_pdLog') + take('function _pdQtyPlan(', '_pdQtyPlan') +
    take('function _pdReadPct(', '_pdReadPct') + take('function _pdQtyAt(', '_pdQtyAt') +
    take('function _pdAcc(', '_pdAcc') + take('function _pdWeight(', '_pdWeight') +
    take('function _pdHasPlan(', '_pdHasPlan') + take('function _pdPlanned(', '_pdPlanned') +
    take('function _pdDaily(', '_pdDaily') + take('function _pdRollup(', '_pdRollup') +
    'let _pdRefIdx = { det: null, tsk: null, pid: null, map: null };\n' +
    take('function _pdRowsByRef(', '_pdRowsByRef') +
    take('function _pdTaskPct(', '_pdTaskPct') +
    /* The implementation this replaced, kept verbatim so the two can be COMPARED. A cost test on
       its own would happily bless a fast function returning the wrong percentage. */
    'function _pdTaskPctOld(task, pid) {\n' +
    '  const ref = _pdTaskRef(task); if (!ref) return null;\n' +
    "  const rows = _pdAllRowsReal(pid).filter(r => String(r.taskRef || '').trim() === ref);\n" +
    '  return rows.length ? { pct: Math.round(_pdRollup(rows).acc), n: rows.length } : null;\n' +
    '}\n' +
    '\nreturn { _pdTaskPct: _pdTaskPct, _pdTaskPctOld: _pdTaskPctOld, _pdRowsByRef: _pdRowsByRef,' +
    ' reloadDetail: rs => { _HR.pm_detail = rs; }, reloadTasks: ts => { _HR.pm_tasks = ts; },' +
    ' rows: () => _HR.pm_detail };')(
      TASKS, ROWS.map(r => Object.assign({}, r, { qtyPlan: 100, unit: 'm', weight: 1,
        log: [{ d: '2026-08-01', qty: 40, pct: 40 }] })), () => { allRows++; });

  const mine = TASKS.filter(t => t.projectId === BIG);
  allRows = 0;
  const got = mine.map(t => P._pdTaskPct(t, BIG));
  ok('one pass over every activity sorts the detail rows ONCE',
     allRows === 1,
     'got ' + allRows + ' _pdAllRows calls for ' + mine.length + ' activities. Before the grouping ' +
     'that was one full filter AND sort per activity — 497 ms a pass on a laptop, and three ' +
     'separate screens each make that pass.');

  const want = mine.map(t => P._pdTaskPctOld(t, BIG));
  const differ = got.map((g, i) => [i, g, want[i]])
    .filter(([, g, w]) => JSON.stringify(g) !== JSON.stringify(w));
  ok('and every activity reports exactly the percentage the per-activity filter reported',
     differ.length === 0,
     differ.length + ' of ' + mine.length + ' differ, e.g. activity ' + (differ[0] || [])[0] +
     ': grouped ' + JSON.stringify((differ[0] || [])[1]) +
     ' vs filtered ' + JSON.stringify((differ[0] || [])[2]));
  ok('the sample actually measured something — most activities have detail rows',
     got.filter(Boolean).length > 50,
     'only ' + got.filter(Boolean).length + ' of ' + mine.length + ' returned a percentage, so the ' +
     'comparison above was mostly null === null and proved very little');

  /* The subtle one. Filing today's reading mutates a row IN PLACE — pdDailyEntrySave does
     `r.log = log` without replacing _HR.pm_detail — so a grouping keyed on array identity does not
     rebuild. It must not need to: the map holds the live row objects, and only `taskRef` decides
     membership. If the map had copied the rows, today's reading would be invisible until something
     else happened to invalidate the cache. */
  const live = P.rows().find(r => r.taskRef);
  const before = P._pdTaskPct(TASKS.find(t => _pdRefOf(t) === live.taskRef), BIG);
  live.log = [{ d: '2026-08-01', qty: 40, pct: 40 }, { d: '2026-08-12', qty: 95, pct: 95 }];
  const after = P._pdTaskPct(TASKS.find(t => _pdRefOf(t) === live.taskRef), BIG);
  ok("filing today's reading shows up without the cache being rebuilt",
     before && after && after.pct > before.pct,
     'before ' + JSON.stringify(before) + ' after ' + JSON.stringify(after) + ' — the map must hold ' +
     'the LIVE row objects, not copies, or a site engineer files a reading and the percentage does ' +
     'not move');

  allRows = 0;
  P.reloadDetail(P.rows().slice());          // tkLoadColl replaces the array wholesale
  P._pdTaskPct(mine[0], BIG);
  ok('replacing the detail rows rebuilds the grouping', allRows === 1, 'got ' + allRows);

  allRows = 0;
  P.reloadTasks(TASKS.slice());              // the ORDER inside each group comes from pm_tasks
  P._pdTaskPct(mine[0], BIG);
  ok('and replacing the activities rebuilds it too', allRows === 1,
     'got ' + allRows + ' — the rows come from pm_detail but their order comes from pm_tasks via ' +
     '_pdOrderKey, so a task reload can change the answer even when no detail row moved');

  const groups = P._pdRowsByRef(BIG);
  ok('a line reporting against nothing joins no group',
     !groups.has('') && !groups.has(' ') && !groups.has('   '),
     'keys: ' + JSON.stringify([...groups.keys()].filter(k => !k.trim())));
  ok('and those lines are not swept into some other group either',
     [...groups.values()].every(rs => rs.every(r => String(r.taskRef || '').trim())),
     'an unlinked line inside a group would be counted towards an activity it does not report ' +
     'against — its quantity would inflate that activity\'s percentage');

  /* Two projects must not share one grouping. Asked only ever about one project, a cache key that
     omitted the pid would look perfectly correct. */
  const g2 = P._pdRowsByRef(SECOND);
  ok('a second project gets its OWN grouping, not the first project\'s',
     [...g2.values()].every(rs => rs.every(r => r.projectId === SECOND)),
     'rows from ' + BIG + ' leaked into ' + SECOND + '\'s groups — every percentage on the second ' +
     'project would be computed from the first project\'s site reports');
  const t2 = TASKS.filter(t => t.projectId === SECOND);
  const p2 = t2.map(t => P._pdTaskPct(t, SECOND));
  const p2old = t2.map(t => P._pdTaskPctOld(t, SECOND));
  ok('and reports the same percentages the per-activity filter did there too',
     JSON.stringify(p2) === JSON.stringify(p2old));
}

/* The assertions above are only worth anything if the fixture actually contains the shapes they
   describe. It did not, once: 400 rows with 400 distinct references, none blank, one project — and
   three separate mutations went undetected because the cases simply were not there. Assert the
   fixture, so that can never be true again silently. */
console.log('\nThe fixture contains the cases the assertions are about\n');
{
  const refs = {};
  ROWS.filter(r => r.projectId === BIG && String(r.taskRef || '').trim())
    .forEach(r => { const k = r.taskRef.trim(); refs[k] = (refs[k] || 0) + 1; });
  const shared = Object.values(refs).filter(n => n > 1).length;
  ok('several activities are fed by MORE THAN ONE detail line', shared >= 20,
     'only ' + shared + ' references carry more than one row, so "keep just one row per activity" ' +
     'would be indistinguishable from correct');
  ok('some lines report against nothing',
     ROWS.filter(r => !String(r.taskRef || '').trim()).length >= 5,
     'without these the unlinked branch is never executed and its assertion proves nothing');
  ok('a second project carries detail rows',
     ROWS.filter(r => r.projectId === SECOND).length >= 10,
     'without these a cache key missing the project id looks correct');
}

function _pdRefOf(t) { return String((t && (t.wbs || t.name)) || '').trim(); }

console.log('\n  ' + pass + ' passed, ' + fail + ' failed\n');
process.exit(fail ? 1 : 0);
