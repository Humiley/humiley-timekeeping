/* Reading the Master Schedule at a chosen depth.
 *
 * Two complaints, one root. A 240-activity programme numbered to 1.4.8.2.1.1.1 could only be read
 * all at once, and it could not even be read: _pmWbsLevel capped at 5, so 1.4.8.2.1, 1.4.8.2.1.1
 * and 1.4.8.2.1.1.1 all reported level 5 and every surface that multiplies by the level drew them
 * at the SAME offset — the hierarchy was invisible on the Timeline, in Activities and in the
 * Daily-progress dialog at once. The cap was doing two jobs: bounding the indent and reporting the
 * depth. Depth is now a fact (capped only at an absurd 12); the indent is a budget priced per
 * surface, which is asserted in tests/schedule_fit.js.
 *
 * On top of that depth, the level control: picking L2 shows levels 1-2 and collapses the rest.
 * What is worth guarding here is not the button — it is that collapsing is a LENS and not a
 * deletion, and that the two tables agree:
 *   - ONE _pmLvlMax for the whole level, so Timeline -> Activities does not silently re-expand;
 *   - the timeline filters INSIDE _schApplyFilter, so "shown / total" counts collapsed rows as
 *     hidden instead of reporting 152 / 152 with a hundred rows out of sight;
 *   - the Detail timeline, which is flat, is never offered a control that would do nothing;
 *   - the bar offers exactly the levels that exist — L1..L7 on a seven-level job, not L9.
 *
 *   node tests/schedule_level_collapse.js
 */
const fs = require('fs');
const path = require('path');

const src = fs.readFileSync(path.join(__dirname, '..', 'templates', 'index.html'), 'utf8');

let pass = 0, fail = 0;
const ok = (n, c, extra) => {
  if (c) { pass++; console.log('  ok    ' + n); }
  else { fail++; console.log('  FAIL  ' + n + (extra ? '\n        ' + extra : '')); }
};
const take = (mark, what, stop) => {
  const i = src.indexOf(mark);
  if (i < 0) { console.error('Could not find ' + what + ' — update the marker, do NOT delete this test.'); process.exit(2); }
  const j = src.indexOf(stop || '\nfunction ', i + 10);
  if (j < 0) { console.error('Could not find the end of ' + what + '.'); process.exit(2); }
  return src.slice(i, j);
};

console.log('\nReading the Master Schedule at a chosen depth\n');

const api = {};
new Function(
  'function _t(s){ return s; } function _t2(en, vn){ return en; }' +
  'function _tkEscA(s){ return String(s == null ? "" : s).replace(/"/g, "&quot;"); }' +
  take('function _pmWbsLevel(', '_pmWbsLevel') +
  take('let _pmLvlMax = 0;', 'the level state', '\nfunction _pmDailyRows') +
  '\nObject.assign(this, { _pmDeepest, _pmLvlBar, _pmWbsLevel,' +
  '  set: n => { _pmLvlMax = n; }, get: () => _pmLvlMax });'
).call(api);
const { _pmDeepest, _pmLvlBar, _pmWbsLevel } = api;

/* ══ 1. the bar offers the levels that exist, and nothing else ══════════════════════════════ */
const deepRows = ['1', '1.4', '1.4.8', '1.4.8.2', '1.4.8.2.1', '1.4.8.2.1.1', '1.4.8.2.1.1.1']
  .map(w => ({ wbs: w }));
ok('_pmDeepest reads the real depth off a WBS code',
   _pmDeepest(deepRows) === 7, 'got ' + _pmDeepest(deepRows));
ok('and off a normalised row that already carries its level',
   _pmDeepest([{ level: 3 }, { level: 5 }, { level: 2 }]) === 5);
ok('an empty set is one level deep, not zero',
   _pmDeepest([]) === 1 && _pmDeepest(null) === 1);

api.set(0);
const bar = _pmLvlBar(7, 7, 7);
ok('a seven-level programme is offered L1 through L7',
   [1, 2, 3, 4, 5, 6, 7].every(n => bar.indexOf('>L' + n + '<') > 0), bar.slice(0, 300));
ok('and not L8 — the bar offers depth that exists, not depth it imagines',
   bar.indexOf('>L8<') < 0);
ok('plus a way back to every level',
   bar.indexOf('>All<') > 0 && /onclick="pmLvlMax\(0\)"/.test(bar));

ok('a FLAT list gets no control at all — there is no hierarchy to collapse',
   _pmLvlBar(1, 5, 5) === '', JSON.stringify(_pmLvlBar(1, 5, 5)).slice(0, 120));

/* ══ 2. it says which depth is being read, and what that hid ════════════════════════════════ */
api.set(3);
const at3 = _pmLvlBar(7, 84, 274);
ok('the chosen level is the one marked active',
   /onclick="pmLvlMax\(3\)"[^>]*background:var\(--navy\)/.test(at3), at3.slice(at3.indexOf('L3') - 240, at3.indexOf('L3') + 10));
ok('and it names what it collapsed away, rather than quietly showing 84 rows',
   at3.indexOf('84 / 274') > 0, at3);
api.set(0);
ok('with All selected there is no count — nothing is hidden to report',
   _pmLvlBar(7, 274, 274).indexOf('/ 274') < 0);
/* The count belongs to whoever has nowhere else to print it. The timeline's chip bar already
   renders "shown / total" one line above the level bar, and it did print the same number twice
   about the same thing until the timeline stopped asking for it. */
api.set(3);
ok('a caller that passes no count gets none',
   !/\d+ \/ \d+/.test(_pmLvlBar(7)), _pmLvlBar(7).slice(-200));
api.set(0);
ok('and the timeline is that caller — its chip bar prints the count one line above',
   /_pmLvlBar\(_deepest\)/.test(take('function _schTimeline(', '_schTimeline', '\nfunction _schCalendar')) &&
   !/_pmLvlBar\(_deepest, /.test(take('function _schTimeline(', '_schTimeline', '\nfunction _schCalendar')));

/* ══ 3. the timeline filters INSIDE the filter pass, so the counter stays honest ════════════ */
const fapi = {};
new Function(
  'let _schFilt = { m: { q: "", k: "all", from: "", to: "" }, d: { q: "", k: "all", from: "", to: "" } };' +
  take('function _schApplyFilter(', '_schApplyFilter') +
  '\nObject.assign(this, { _schApplyFilter });'
).call(fapi);
const rows = [
  { name: 'a', level: 1 }, { name: 'b', level: 2 }, { name: 'c', level: 3 },
  { name: 'd', level: 4 }, { name: 'e', level: 7 }, { name: 'f' },
];
const keep = (max) => fapi._schApplyFilter(rows, 'm', '2026-09-04', max).map(r => r.name).join('');
ok('level 2 keeps levels 1 and 2 and collapses everything below',
   keep(2) === 'abf', 'got ' + keep(2));
ok('level 4 keeps one more', keep(4) === 'abcdf', 'got ' + keep(4));
ok('0 means every level — the way back',
   keep(0) === 'abcdef' && keep(undefined) === 'abcdef');
ok('a row with NO wbs code is never collapsed away — it has no level to be below one',
   keep(1).indexOf('f') >= 0, 'got ' + keep(1));

const tl = take('function _schTimeline(', '_schTimeline', '\nfunction _schCalendar');
ok('the timeline applies the level in the SAME pass as the chips, not before it',
   /rows = _schApplyFilter\(rows, ns, day, o\.levels \? _pmLvlMax : 0\);/.test(tl),
   'pre-filtering the rows would make total equal shown and the counter would report 152 / 152');
ok('so "shown / total" is computed against the unfiltered count',
   /total = rows\.length;/.test(tl) &&
   tl.indexOf('total = rows.length;') < tl.indexOf('rows = _schApplyFilter('),
   'total taken after the filter would make the counter report shown / shown');
ok('and the deepest level is read before the filter, so collapsing to L2 does not shrink the bar '
   + 'to L1 and L2 and strand the reader there',
   tl.indexOf('const _deepest = o.levels ? _pmDeepest(rows) : 1;') <
   tl.indexOf('rows = _schApplyFilter(rows, ns, day, o.levels'));

/* ══ 4. both master tables, one depth; the flat detail timeline, none ═══════════════════════ */
const sched = take('function pmRenderSchedule(', 'pmRenderSchedule', '\nfunction _pmSchedTabBtn');
ok('the MASTER timeline opts into the control',
   /ns: 'm', collapsed: _pmPhCol, levels: true/.test(sched));
const det = take('function _pdTimeline(', '_pdTimeline');
ok('the DETAIL timeline does not — its lines are flat, so the control would do nothing',
   det.indexOf('levels') < 0, det);

ok('Activities filters on the SAME _pmLvlMax the Timeline reads, not a copy of its own',
   /_pmLvlMax \? allTasks\.filter\(t => _pmWbsLevel\(t\.wbs\) <= _pmLvlMax\) : allTasks/.test(sched));
ok('and it renders the same bar, over the same depth',
   /_pmLvlBar\(_actDeep, _actRows\.length, allTasks\.length\)/.test(sched));
ok('the Activities bar is fed the FULL task list for its total, not the filtered one',
   /const _actDeep = _pmDeepest\(allTasks\.map/.test(sched));
ok('the table itself is handed the filtered rows',
   /\], _actRows\), pmMasterWipeBtn/.test(sched));

ok('opening a different project resets the reading depth',
   /_pmGanttCol = \{\}; _pmLvlMax = 0; \}/.test(sched),
   'level 4 on a seven-level job is a nonsense lens on a two-level one');
ok('changing it re-renders rather than mutating the DOM in place',
   /function pmLvlMax\(n\) \{ _pmLvlMax = \+n \|\| 0; _pmReload\(\); \}/.test(src));

/* ══ 5. the Daily-progress dialog indents by the same depth ═════════════════════════════════ */
const dlg = take('function pmDailyEntry(', 'pmDailyEntry', '\nasync function pmDailyEntrySave');
ok('the Daily progress dialog prices its indent as a dialog, not by a bare constant',
   /const pad = 6 \+ _pmWbsIndentPx\(r\.level, 'dialog'\);/.test(dlg),
   'a hardcoded step is how the three surfaces drifted apart in the first place');
ok('and the rows it indents carry a real level',
   /level: _pmWbsLevel\(t\.wbs\),/.test(take('function _pmDailyRows(', '_pmDailyRows')));

console.log('\n' + pass + ' passed, ' + fail + ' failed\n');
process.exit(fail ? 1 : 0);
