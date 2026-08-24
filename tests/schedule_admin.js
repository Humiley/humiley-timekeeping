/* Four things the schedule screens could not do, and the one thing they must never start doing.
 *
 *   12  Import Detail Schedule filed nothing. Every pasted row arrived with no master activity, so
 *       a 200-line programme meant opening 200 records to set the same dropdown. One picker for the
 *       batch; a taskRef column in the paste still wins per row, because a spreadsheet naming the
 *       activity line by line is a more specific statement than one choice for everything.
 *   13  A detail schedule could be created and never corrected. Rename and Delete, behind the
 *       signing PIN. DELETING A SCHEDULE MUST DELETE NO TASKS — that is the assertion that matters
 *       here and the one that would be silently easy to break.
 *   14  "Part of master activity" was a flat list of 200 codes. Indented into a tree.
 *   15  Phase had to be typed onto every sub-task by hand. It cascades down the WBS, after asking.
 *
 *   node tests/schedule_admin.js
 */
const fs = require('fs');
const path = require('path');

const src = fs.readFileSync(path.join(__dirname, '..', 'templates', 'index.html'), 'utf8');

let pass = 0, fail = 0;
const ok = (n, c, extra) => {
  if (c) { pass++; console.log('  ok    ' + n); }
  else { fail++; console.log('  FAIL  ' + n + (extra ? '\n        ' + extra : '')); }
};

/* Lift a real function out of the file and RUN it, rather than asserting on its source text.
 *
 * Slice ONE top-level function.
 *
 * The first version ended at the next `\nfunction `, which does not match `\nasync function ` — so
 * lifting `pdGroupRefile` ran straight on through `pdGroupDelete` beneath it, and an assertion that
 * re-filing does NOT ask for a PIN read the PIN gate belonging to the delete. It reported a defect
 * that was not there; the same slice error in the other direction reports SAFETY that is not there.
 * End at whichever comes first, and print the length so an over-wide slice is visible. */
const take = (mark, what) => {
  const i = src.indexOf(mark);
  if (i < 0) { console.error('Could not find ' + what + ' — update the marker, do NOT delete this test.'); process.exit(2); }
  const ends = ['\nfunction ', '\nasync function ', '\nconst ', '\nlet ']
    .map(e => src.indexOf(e, i + 10)).filter(x => x > 0);
  if (!ends.length) { console.error('Could not find the end of ' + what + '.'); process.exit(2); }
  const body = src.slice(i, Math.min.apply(null, ends));
  if (process.env.TAKE_DEBUG) console.log('        [' + what + ': ' + body.length + ' chars]');
  return body;
};

// ══ 14 · the master-activity picker reads as a tree ════════════════════════════════════════════
console.log('\n14 · "Part of master activity" is a tree, not 200 flat codes\n');

/* _qaDynOptions is a huge switch; only the pm_task_opts arm is under test. Rebuild that arm with
 * the REAL _pmWbsLevel and _pmWbsCmp so the indent and the ordering are the shipped ones. */
const OPTS = (() => {
  const i = src.indexOf("if (src === 'pm_task_opts')");
  if (i < 0) { console.error('pm_task_opts arm not found'); process.exit(2); }
  const j = src.indexOf("\n  if (src === '", i + 10);
  const arm = src.slice(i, j < 0 ? i + 4000 : j);
  return new Function('tasks',
    'const _HR = { pm_tasks: tasks };\n' +
    'function _pmPid(){ return "P1"; }\n' +
    'const _pmScopeFor = (c, pid) => (_HR[c] || []).filter(x => x.projectId === pid);\n' +
    take('function _pmWbsCmp(', '_pmWbsCmp') + '\n' +
    take('function _pmWbsLevel(', '_pmWbsLevel') + '\n' +
    'const _wbsCmp = _pmWbsCmp;\n' +
    'const src = "pm_task_opts";\n' +
    arm.replace(/^\s*if \(src === 'pm_task_opts'\) \{/, '{'));
})();

const T = (wbs, name) => ({ id: wbs, projectId: 'P1', wbs: wbs, name: name });
{
  const out = OPTS([T('1.2.3.1', 'Duct riser'), T('1', 'Design'), T('1.2', 'Detailed design'),
                    T('1.10', 'Tender'), T('1.2.3', 'HVAC'), T('2', 'Construction')]);
  const labels = out.map(o => o.l);

  ok('every activity is still offered', out.length === 6,
     'got ' + out.length + ' — an indent that loses rows is worse than no indent');

  ok('outline order first: 1, 1.2, 1.2.3, 1.2.3.1, 1.10, 2',
     out.map(o => o.v).join(' | ') === '1 | 1.2 | 1.2.3 | 1.2.3.1 | 1.10 | 2',
     'got ' + out.map(o => o.v).join(' | ') + ' — an indent only reads as a tree when the rows are ' +
     'in outline order; sorting AFTER indenting would draw a tree that is not one');

  const indent = l => (l.match(/^ */)[0] || '').length;
  ok('a level-1 activity pays no indent', indent(labels[0]) === 0);
  ok('level 2 is indented one step', indent(labels[1]) === 3);
  ok('level 3 is indented two steps', indent(labels[2]) === 6);
  ok('level 4 is indented three steps', indent(labels[3]) === 9);
  ok('a child carries the branch glyph and a level-1 row does not',
     /└/.test(labels[1]) && !/└/.test(labels[0]));

  ok('the VALUE saved is still the bare WBS code, never the decorated label',
     out.every(o => !/[ └]/.test(o.v)),
     'the indent is presentation; writing it into taskRef would file every detail line against a ' +
     'master activity whose code does not exist');

  ok('the name is still on the label', /Detailed design/.test(labels[1]));
}
{
  // 1.10 must NOT be treated as a child of 1.1 — and an activity with no code is level 1.
  const out = OPTS([T('1.1', 'A'), T('1.10', 'B'), { id: 'x', projectId: 'P1', wbs: '', name: 'Uncoded' }]);
  const byV = {}; out.forEach(o => byV[o.v] = o.l);
  ok('1.10 is a sibling of 1.1, not a child of it',
     (byV['1.10'].match(/^ */)[0] || '').length === (byV['1.1'].match(/^ */)[0] || '').length);
  ok('an activity with no WBS code is offered at level 1',
     byV['Uncoded'] !== undefined && !/^ /.test(byV['Uncoded']));
}

// ══ 12 · the import files the rows it creates ══════════════════════════════════════════════════
console.log('\n12 · Import assigns the master activity, instead of leaving 200 rows to open\n');

ok('the import form offers a master-activity picker',
   /id="pd-imp-task"/.test(src),
   'this is the whole request: without it every imported row lands unassigned');
ok('and it is filled from the same tree the edit form uses',
   /id="pd-imp-task"[\s\S]{0,400}_qaDynOptions\('pm_task_opts'\)/.test(src),
   'a second, hand-built list would drift from the one on the edit form');
ok('with an explicit "leave unassigned" choice',
   /id="pd-imp-task"[\s\S]{0,300}leave unassigned/.test(src),
   'a blank first option that means "unassigned" and one that means "you did not answer yet" are ' +
   'indistinguishable; say it');

/* The rule that decides what actually gets written, RUN — and run as the file writes it.
 *
 * The first version of this block declared `return r.taskRef || bulkTask || ''` inside the test and
 * evaluated that. It passed with the precedence in index.html reversed, because it was measuring a
 * string the test itself had written. The expression is now lifted out of the source, so flipping
 * the two operands there flips these three assertions. */
{
  /* Deliberately matches ANY expression in that slot, not the one expected. A regex that only
   * matches the correct rule cannot report an incorrect one — it just stops finding anything, and
   * the failure lands on some unrelated assertion instead of on the behaviour that broke. */
  const m = src.match(/\btaskRef: ([^,]*),\s*unit:/);
  ok('the import has exactly one place that decides a row\'s master activity',
     !!m && (src.match(/\btaskRef: [^,]*,\s*unit:/g) || []).length === 1,
     'two write sites would let the picker work on one path and not the other');
  if (m) {
    console.log('        (rule as written in index.html: ' + m[1] + ')');
    const pick = new Function('r', 'bulkTask', 'return ' + m[1] + ';');
    ok('paste beats the batch picker', pick({ taskRef: '1.2.3' }, '9.9') === '1.2.3',
       'a spreadsheet naming the activity line by line is a more specific statement than one ' +
       'choice made for the whole batch');
    ok('the batch picker fills a row that names nothing', pick({}, '9.9') === '9.9',
       'this is the entire request — without it every imported row lands unassigned');
    ok('neither means unassigned, not the string "undefined"', pick({}, '') === '');
  }
}
ok('the preview shows which activity each row will land under',
   /pdImportPreview[\s\S]{0,2000}r\.taskRef \|\| _bulk/.test(src),
   'the batch choice is invisible until after the import otherwise, which is when it is too late');
ok('the picker re-renders the preview when it changes',
   /id="pd-imp-task" onchange="pdImportPreview\(\)"/.test(src));

// ══ 13 · rename / delete, and the tasks that must survive it ═══════════════════════════════════
console.log('\n13 · A schedule can be corrected — and deleting one deletes no tasks\n');

const bar = take('function _pdSchedBar(', '_pdSchedBar');
ok('the schedule bar offers Rename', /pdSchedRename\(/.test(bar));
ok('and Delete', /pdSchedDelete\(/.test(bar));
ok('neither is offered on "Unfiled", which is not a schedule',
   /cur && cur\.id !== '_unfiled' \?/.test(bar),
   'Unfiled is a bucket for rows that match no schedule — it has no record to rename or delete');

const del = take('async function pdSchedDelete(', 'pdSchedDelete');
const ren = take('async function pdSchedRename(', 'pdSchedRename');

ok('delete asks for the signing PIN', /_pdPinGate\(/.test(del));
ok('rename asks for the signing PIN', /_pdPinGate\(/.test(ren));
ok('the PIN is asked for AFTER the confirm, so a cancelled delete never asks for it',
   del.indexOf('tkConfirm(') < del.indexOf('_pdPinGate('),
   'asking for a PIN and then asking whether they meant it trains people to type the PIN first ' +
   'and read second');
ok('the PIN gate returning false stops the delete',
   /if \(!await _pdPinGate\([\s\S]{0,200}\)\) return;/.test(del),
   'a gate whose answer is not read is decoration');

/* THE assertion. */
ok('DELETE touches pm_schedules and nothing else',
   /\/api\/coll\/pm_schedules\/' \+ id, \{ method: 'DELETE' \}/.test(del) &&
   !/pm_detail/.test(del.replace(/_pdAllRows\(pid\)/g, '')),
   'deleting the heading must never delete the work reported under it');
ok('and it counts the tasks that will be left, before asking',
   /const n = _pdAllRows\(pid\)\.filter\(r => r\.scheduleId === id\)\.length;/.test(del) &&
   del.indexOf('const n =') < del.indexOf('tkConfirm('));
ok('the dialog says the tasks are NOT deleted',
   /are NOT deleted/.test(del),
   '"Delete this schedule?" with 200 lines under it is a question nobody can answer safely');
ok('and says where they go',
   /Unfiled/.test(del));
ok('the deleted schedule stops being the selected one',
   /if \(_pdSchedId === id\) _pdSchedId = '';/.test(del),
   'otherwise the bar shows the first schedule while the state points at a record that is gone');
ok('both acts are written to the audit trail',
   /tkAudit\('Detail schedule deleted'/.test(del) && /tkAudit\('Detail schedule renamed'/.test(ren));
ok('the rename records what the name WAS',
   /was "' \+ \(sc\.name \|\| ''\) \+ '"/.test(ren),
   'an audit line saying only the new name cannot answer "what was this called last month?"');
ok('a rename to the same name writes nothing',
   /if \(!name \|\| name === \(sc\.name \|\| ''\)\) return;/.test(ren));

// ── the PIN gate itself ────────────────────────────────────────────────────────────────────────
const gate = take('async function _pdPinGate(', '_pdPinGate');
ok('the PIN is checked by the SERVER, not compared here',
   /tkApi\('\/api\/esign\/pin'[\s\S]{0,120}action: 'verify'/.test(gate),
   'a client-side comparison would need the PIN in the browser, and could be stepped over in a ' +
   'debugger; the server also locks the PIN after repeated wrong answers');
ok('no PIN enrolled refuses, and says where to set one',
   /if \(!_esignHasPin\(\)\)/.test(gate) && /My Profile/.test(gate),
   'a gate that opens when the lock is missing is not a gate');
ok('a wrong PIN is not reported as an expired session',
   /_no401: true/.test(gate),
   "tkApi's default 401 handling fires a silent re-login and toasts 'Session refreshed' — for a " +
   'typed PIN the truth is "Incorrect PIN"');
ok('and the same fix reached the e-sign modal, which had the bug first',
   /action: 'verify', pin: signAuth\.pin \}, _no401: true \}/.test(src));
ok('the gate returns false on a wrong PIN rather than throwing',
   /catch \(e\) \{[\s\S]{0,200}return false;/.test(gate));
ok('a cancelled prompt is a refusal',
   /if \(!pin\) return false;/.test(gate));

// ══ 15 · phase cascades down the WBS ═══════════════════════════════════════════════════════════
console.log('\n15 · Choosing a phase on 1.2 offers to set 1.2.1, 1.2.2, 1.2.3, 1.2.3.1\n');

const KIDS = new Function('parent', 'tasks',
  take('function _pmWbsKids(', '_pmWbsKids') + '\nreturn _pmWbsKids(parent, tasks);');

{
  const all = [T('1', 'Design'), T('1.2', 'Detail'), T('1.2.1', 'a'), T('1.2.2', 'b'),
               T('1.2.3', 'c'), T('1.2.3.1', 'd'), T('1.20', 'other'), T('1.3', 'e'), T('2', 'f')];
  const k = KIDS(T('1.2', 'Detail'), all).map(x => x.wbs).sort();
  ok('1.2 owns 1.2.1, 1.2.2, 1.2.3 and 1.2.3.1',
     k.join(',') === '1.2.1,1.2.2,1.2.3,1.2.3.1', 'got ' + k.join(','));
  ok('and does NOT own 1.20',
     k.indexOf('1.20') < 0,
     'a bare startsWith would sweep it in, and on a programme numbered past nine that is most of ' +
     'a level');
  ok('nor 1.3, nor 2, nor its own parent 1',
     k.indexOf('1.3') < 0 && k.indexOf('2') < 0 && k.indexOf('1') < 0);
  ok('a parent is never its own child', KIDS(T('1.2', 'x'), all).every(x => x.id !== '1.2'));
  ok('the whole tree below counts, not just the level under it',
     k.indexOf('1.2.3.1') >= 0,
     'the request names 1.2.3.1 explicitly — stopping at direct children would leave the deepest ' +
     'work, which is most of it, still to be typed by hand');
}
ok('an activity with no WBS code has no descendants',
   KIDS({ id: 'x', wbs: '', name: 'Uncoded' }, [T('1.1', 'a'), T('1.1.1', 'b')]).length === 0,
   'a name is not a hierarchy; inferring one from text would file work under a heading nobody chose');
ok('and neither does one whose code is only whitespace',
   KIDS({ id: 'x', wbs: '   ' }, [T('1.1', 'a')]).length === 0);

const casc = take('async function _pmPhaseCascade(', '_pmPhaseCascade');
ok('nothing happens when the phase did not move',
   /if \(!ph \|\| ph === String\(prevPhase == null \? '' : prevPhase\)\.trim\(\)\) return 0;/.test(casc),
   're-saving a parent to fix its dates must not re-stamp a branch somebody has since refined');
ok('nothing happens when no phase was chosen at all',
   /if \(!ph \|\|/.test(casc),
   'blank must not cascade blank over eight deliberate answers');
ok('children already on the new phase are not written',
   /\.filter\(t => String\(t\.phase \|\| ''\)\.trim\(\) !== ph\)/.test(casc),
   'and therefore not counted — the number in the dialog is the number that will change');
ok('it asks before writing',
   casc.indexOf('tkConfirm(') > 0 && casc.indexOf('tkConfirm(') < casc.indexOf("method: 'PATCH'"),
   'this overwrites a value somebody may have set on purpose');
ok('and a refusal writes nothing',
   /if \(!go\) return 0;/.test(casc));
/* The list line, evaluated rather than pattern-matched: it must carry the code, the name and the
 * phase being replaced. "12 sub-tasks will change" is not enough to decide with. */
{
  const line = casc.match(/const list = kids\.slice\(0, SHOW\)\.map\(([\s\S]*?)\)\.join\('\\n'\);/);
  ok('the dialog builds a per-child line', !!line);
  if (line) {
    const row = new Function('_t2', 'return ' + line[1] + ';')((en) => en);
    const withPhase = row({ wbs: '1.2.1', name: 'Duct riser', phase: 'FEED / Basic Design' });
    const without = row({ wbs: '1.2.2', name: 'Grilles', phase: '' });
    ok('each line shows the WBS code', /1\.2\.1/.test(withPhase));
    ok('and the activity name', /Duct riser/.test(withPhase));
    ok('and the phase it is about to lose', /FEED \/ Basic Design/.test(withPhase),
       'this overwrites a value somebody may have set on purpose — show it before replacing it');
    ok('a child with no phase yet says so rather than showing a blank bracket',
       /no phase/.test(without) && !/\(\)/.test(without));
  }
}
ok('a child that failed to save is reported, not swallowed',
   /failed\.push\(/.test(casc) && /failed\.length/.test(casc),
   'a 409 from somebody else\'s concurrent edit must not be reported as a clean cascade');
ok('the PATCH sends the whole record',
   /Object\.assign\(\{\}, t, \{ phase: ph \}\)/.test(casc),
   '/api/coll PATCH REPLACES the item — a partial body would blank every other field on the row');
ok('the cascade is audited',
   /tkAudit\('Task phase cascaded'/.test(casc));
ok('writes go out in bounded batches, not all at once',
   /i \+= 5\)/.test(casc),
   'a 300-line branch would otherwise open 300 concurrent requests');

// ── the hook in the save path ──────────────────────────────────────────────────────────────────
ok('the cascade runs only when EDITING an existing activity',
   /_qaType === 'pm_tasks' && _wasEdit && item/.test(src),
   'a brand-new activity has no sub-tasks yet, and _qaEditId is cleared by closeModal');
ok('the previous phase is captured BEFORE the write',
   src.indexOf('_prevPhase = ex.phase == null') > 0 &&
   src.indexOf('_prevPhase = ex.phase == null') < src.indexOf("_qaType === 'pm_tasks' && _wasEdit"),
   'after the PATCH the old value is gone from every copy we hold, so "did it move?" is unanswerable');
ok('and the question is asked after the form closes',
   src.indexOf("closeModal('quickAddModal')") < src.indexOf("_qaType === 'pm_tasks' && _wasEdit"),
   'a confirm stacked on the form it came from hides the change it is asking about');

console.log('\n  ' + pass + ' passed, ' + fail + ' failed\n');
process.exit(fail ? 1 : 0);
