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
const ROWS = [];
for (let i = 0; i < 400; i++) {
  ROWS.push({ id: 'd' + i, projectId: BIG,
    taskRef: '1.' + ((i % 9) + 1) + '.' + (((i / 9) | 0) % 9 + 1) + '.' + (i % 7 + 1),
    category: ['HVAC', 'Electrical', 'Plumbing', 'Civil'][i % 4],
    name: 'Detail line ' + i, start: '2026-0' + ((i % 9) + 1) + '-01', log: [] });
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
  ok('the sort still returns every row', out.length === ROWS.length, 'got ' + out.length);
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

console.log('\n  ' + pass + ' passed, ' + fail + ' failed\n');
process.exit(fail ? 1 : 0);
