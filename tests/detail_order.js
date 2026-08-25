/* One order for the whole Detail Schedule, and one press to fold it.
 *
 * `_pdAllRows` sorted on `category` — the TRADE NAME — alphabetically. Where two master activities
 * share a trade the WBS codes therefore ran in whatever order their names happened to fall in, which
 * on a real programme put 1.4.4.4.4 above 1.4.4.4.3. The group headings were built by walking those
 * rows and taking each new group as it appeared, so they inherited the same wrong order — and the
 * Daily-progress dialog headed its sections with the trade instead of the activity, so a person
 * filing today's numbers read a different list in a different sequence from the one they had just
 * been looking at.
 *
 * The property this file holds: Timeline, Register, Daily progress and the exports all read ONE
 * ordering. Four surfaces each sorting for themselves is four chances to disagree about what comes
 * first, and the disagreement is only visible to whoever is holding two of them.
 *
 *   node tests/detail_order.js
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

/* The real thing, run. The activities are deliberately stored out of order and two of them share a
   trade — the exact shape that produced the reported bug. */
const PID = 'P1';
const TASKS = [
  { id: 'a', projectId: PID, wbs: '1.4.4.4.4', name: 'Zone 4' },
  { id: 'b', projectId: PID, wbs: '1.10',      name: 'Tender' },
  { id: 'c', projectId: PID, wbs: '1.4.4.4.3', name: 'Zone 3' },
  { id: 'd', projectId: PID, wbs: '1.2',       name: 'Design' }
];
const R = (id, ref, cat, name, start) =>
  ({ id: id, projectId: PID, taskRef: ref, category: cat, name: name, start: start || '', log: [] });
const ROWS = [
  R('r1', '1.4.4.4.4', 'HVAC', 'Zone 4 duct'),
  R('r2', '1.2',       'Zebra', 'Design pack'),          // trade sorts LAST alphabetically
  R('r3', '1.4.4.4.3', 'HVAC', 'Zone 3 slab'),
  R('r4', '1.10',      'Alpha', 'Tender doc'),           // trade sorts FIRST alphabetically
  R('r5', '',          'HVAC', 'Not linked to anything'),
  R('r6', '1.4.4.4.3', 'HVAC', 'Zone 3 beam', '2026-01-01')
];

const API = new Function('TASKS', 'ROWS',
  'const _HR = { pm_tasks: TASKS, pm_detail: ROWS, pm_schedules: [], pm_projects: [{id:"P1"}] };\n' +
  'const _PD_COLL = "pm_detail";\n' +
  'let _pdSchedId = "";\n' +
  'let _pdCol = {};\n' +
  'function _t(x){ return x; }\n' +
  'function _t2(en, vn){ return en; }\n' +
  'function _tkEscA(v){ return String(v == null ? "" : v).replace(/&/g,"&amp;").replace(/"/g,"&quot;"); }\n' +
  'function _pmReload(){ }\n' +
  'const _pmScopeFor = (c, pid) => (_HR[c] || []).filter(x => x.projectId === pid);\n' +
  take('function _pmWbsCmp(', '_pmWbsCmp') +
  take('function _pdTaskRef(', '_pdTaskRef') +
  /* The index _pdMasterOf now reads. It replaced a full `_pmScopeFor('pm_tasks', pid).find(...)`
     per lookup, which _pdOrderKey performed twice per comparison — on a real programme that was
     5,767 whole-array scans for ONE sort. The ordering assertions below are what prove the index
     resolves to the same activity the scan did, so it is lifted here rather than stubbed. */
  'let _pdMIdx = { arr: null, pid: null, map: null };\n' +
  take('function _pdMasterIndex(', '_pdMasterIndex') +
  take('function _pdMasterOf(', '_pdMasterOf') +
  take('function _pdGroupOf(', '_pdGroupOf') +
  take('function _pdOrderKey(', '_pdOrderKey') +
  take('function _pdOrderCmp(', '_pdOrderCmp') +
  take('function _pdAllRows(', '_pdAllRows') +
  take('function _pdCats(', '_pdCats') +
  take('function _pdScheds(', '_pdScheds') +
  take('function _pdUnfiled(', '_pdUnfiled') +
  take('function _pdCurSched(', '_pdCurSched') +
  take('function _pdRows(', '_pdRows') +
  take('function pdToggleCat(', 'pdToggleCat') +
  take('function _pdAllCollapsed(', '_pdAllCollapsed') +
  take('function pdCollapseAll(', 'pdCollapseAll') +
  take('function pdCollapseAllBtn(', 'pdCollapseAllBtn') +
  '\nreturn { _pdAllRows, _pdCats, _pdRows, _pdGroupOf, _pdAllCollapsed, pdCollapseAll,' +
  ' pdCollapseAllBtn, pdToggleCat, col: () => _pdCol };')(TASKS, ROWS);

// ══ the order ══════════════════════════════════════════════════════════════════════════════════
console.log('\nAscending by the master activity\'s WBS — everywhere\n');

const rows = API._pdAllRows(PID);
const cats = API._pdCats(PID, rows);

ok('every row is still there', rows.length === ROWS.length, 'got ' + rows.length);
/* OUTLINE order, not text order: under `1.` the children run 2, 4…, 10, so 1.10 comes after
   1.4.4.4.4 and not straight after 1.2. My first expectation here read them as text and was wrong
   about the code — the same numeric rule the Master Schedule already uses. */
ok('groups run in outline order: 1.2, 1.4.4.4.3, 1.4.4.4.4, 1.10, then the unlinked',
   cats.map(c => c.split(' ')[0]).join(' | ') ===
     '1.2 | 1.4.4.4.3 | 1.4.4.4.4 | 1.10 | Not',
   'got ' + cats.join(' | '));
ok('1.4.4.4.3 comes BEFORE 1.4.4.4.4 — the reported bug',
   cats.findIndex(c => c.indexOf('1.4.4.4.3') === 0) < cats.findIndex(c => c.indexOf('1.4.4.4.4') === 0),
   'they share a trade, so an alphabetical sort on the trade name left their order to chance');
ok('and 1.2 comes before 1.10, which a text sort gets wrong',
   cats.findIndex(c => c.indexOf('1.2') === 0) < cats.findIndex(c => c.indexOf('1.10') === 0));
ok('the trade name no longer decides the order',
   cats.findIndex(c => c.indexOf('1.10') === 0) > 0,
   'its trade is "Alpha"; sorting on the trade would put it first');

ok('a line that reports against nothing sorts LAST',
   rows[rows.length - 1].id === 'r5',
   'got ' + rows[rows.length - 1].id + ' — it is the exception the register surfaces separately, ' +
   'and burying it mid-list hides it');
ok('rows inside one group stay together',
   rows.filter(r => r.taskRef === '1.4.4.4.3').length === 2 &&
   Math.abs(rows.findIndex(r => r.id === 'r3') - rows.findIndex(r => r.id === 'r6')) === 1);
ok('and within a group a dated line leads an undated one',
   rows.findIndex(r => r.id === 'r6') < rows.findIndex(r => r.id === 'r3'),
   "r6 starts 2026-01-01 and r3 has no date; '' sorts before every real date, so without a guard " +
   'the lines nobody has scheduled led every section');

/* The headings must be DERIVED from the rows, not sorted separately — otherwise a heading can
   appear above rows that belong to a different group. */
ok('the heading list is derived from the row order',
   /\(rows \|\| \[\]\)\.forEach\(r => \{ const c = _pdGroupOf\(pid, r\); if \(out\.indexOf\(c\) < 0\) out\.push\(c\); \}\);/
     .test(take('function _pdCats(', '_pdCats')),
   'two independent sorts drift, and the way they drift is a heading over the wrong rows');
ok('and the view uses that helper rather than rebuilding the list inline',
   /const cats = _pdCats\(pid, rows\);/.test(src) &&
   !/const cats = \[\]; rows\.forEach/.test(src));

// ══ everything reads the one order ═════════════════════════════════════════════════════════════
console.log('\nTimeline, Register, Daily progress and the exports agree\n');

ok('the Timeline groups by _pdGroupOf, off _pdRows',
   /group: _pdGroupOf\(pid, r\)/.test(take('function _pdNorm(', '_pdNorm')));
ok('the Register groups by _pdGroupOf too',
   /_pdGroupOf\(pid, r\) === cat/.test(take('function _pdRegister(', '_pdRegister')));
{
  const DE = take('function pdDailyEntry(', 'pdDailyEntry');
  ok('the Daily-progress dialog heads its sections with the ACTIVITY, not the trade',
     /const cat = _pdGroupOf\(pid, r\);/.test(DE) && !/const cat = r\.category \|\| 'Uncategorised';/.test(DE),
     'it used to head them with r.category, so the person filing numbers read a different list in ' +
     'a different sequence from the one they had just been looking at');
  ok('it still walks _pdRows, so it inherits the one order', /const rows = _pdRows\(pid\)/.test(DE));
  ok('and the trade is still shown on the row, where it identifies rather than orders',
     /r\.category \? '<div style="font-size:10\.5px/.test(DE),
     'moving it out of the heading must not lose it — two lines can share a name across trades');
}
ok('the export sorts by the same WBS comparator',
   /_pmWbsCmp\(a\.taskRef, b\.taskRef\)/.test(take('function _schExportDetail(', '_schExportDetail')));

// ══ expand / collapse all ══════════════════════════════════════════════════════════════════════
console.log('\nOne press folds the lot\n');

ok('nothing is collapsed to begin with', API._pdAllCollapsed(PID) === false);
API.pdCollapseAll(PID);
ok('one press closes every group', API._pdAllCollapsed(PID) === true,
   JSON.stringify(API.col()));
ok('and the next press opens them all again',
   (API.pdCollapseAll(PID), API._pdAllCollapsed(PID) === false),
   JSON.stringify(API.col()));

ok('the button says what it will DO, not what the state is',
   /Collapse all/.test(API.pdCollapseAllBtn(PID)),
   'everything is open, so the press must offer to close');
API.pdCollapseAll(PID);
ok('and flips once everything is shut', /Expand all/.test(API.pdCollapseAllBtn(PID)));
API.pdCollapseAll(PID);

/* The decision comes from the groups on screen, never from a remembered flag — otherwise opening
   one group by hand leaves the button offering the wrong thing. */
API.pdToggleCat(cats[0]);
ok('opening one group by hand still leaves the button offering "Collapse all"',
   /Collapse all/.test(API.pdCollapseAllBtn(PID)),
   'a toggle that flips a stored boolean gets out of step the moment somebody uses the per-group ' +
   'control beside it');
API.pdToggleCat(cats[0]);

ok('with fewer than two groups the button is absent',
   API.pdCollapseAllBtn('NO-SUCH-PROJECT') === '',
   'one group is already the whole list; a control whose press changes nothing is noise');
ok('it appears on the Register', /pdCollapseAllBtn\(pid\) \+\n\s*'<button class="btn btn-emerald btn-sm" onclick="pdDailyEntry/.test(src));
ok('and on the Timeline', /actions: pdCollapseAllBtn\(pid\) \+/.test(src));

console.log('\n  ' + pass + ' passed, ' + fail + ' failed\n');
process.exit(fail ? 1 : 0);
