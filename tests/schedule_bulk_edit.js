/* Bulk acts on a schedule: re-file a whole group, delete a whole group, clear a whole programme.
 *
 *   16  A "category" in the Detail Schedule register is NOT r.category — it is the master activity
 *       the lines report against (_pdGroupOf). So the two group controls mean "move all these lines
 *       to a different master activity" and "delete all these lines". Filing 47 lines one dropdown
 *       at a time was the complaint; so was being unable to remove them at all.
 *   17  Clearing the whole Master Schedule, for when the client re-issues the programme.
 *
 * The assertion that matters most in this file is the one about what SURVIVES: clearing the master
 * schedule must not delete a single detail line, and deleting a group must not touch the master
 * activity above it. Both are easy to get wrong in a way nobody notices until the data is gone.
 *
 *   node tests/schedule_bulk_edit.js
 */
const fs = require('fs');
const path = require('path');

const src = fs.readFileSync(path.join(__dirname, '..', 'templates', 'index.html'), 'utf8');

let pass = 0, fail = 0;
const ok = (n, c, extra) => {
  if (c) { pass++; console.log('  ok    ' + n); }
  else { fail++; console.log('  FAIL  ' + n + (extra ? '\n        ' + extra : '')); }
};
/* Slice ONE top-level function.
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

// ══ the bulk writer ═════════════════════════════════════════════════════════════════════════════
console.log('\nDeleting many rows: bounded, and honest about what did not go\n');

const BULK = take('async function _pmBulkDelete(', '_pmBulkDelete');
{
  /* Run it. A fake tkApi refuses two ids, so the two properties under test — the returned count and
     what is left in the local store — are measured rather than read. */
  const mk = n => Array.from({ length: n }, (_, i) => ({ id: 'r' + i }));
  const F = new Function('rows', 'refuse',
    'const _HR = { pm_detail: rows.slice() };\n' +
    'let peak = 0, live = 0;\n' +
    'async function tkApi(p) {\n' +
    '  live++; peak = Math.max(peak, live);\n' +
    '  await new Promise(r => setTimeout(r, 1));\n' +
    '  live--;\n' +
    '  const id = p.split("/").pop();\n' +
    '  if (refuse.indexOf(id) >= 0) { const e = new Error("nope"); e.status = 403; throw e; }\n' +
    '  return {};\n' +
    '}\n' +
    'function _errMsg(e){ return e.message; }\n' +
    BULK + '\n' +
    'return _pmBulkDelete("pm_detail", rows).then(res => ({ res, left: _HR.pm_detail, peak }));');

  return_check(F, mk);
}
function return_check(F, mk) {
  F(mk(10), ['r3', 'r7']).then(o => {
    ok('every row is attempted', o.res.done + o.res.failed.length === 10,
       'done ' + o.res.done + ' + failed ' + o.res.failed.length);
    ok('the refusals are counted, not swallowed', o.res.failed.length === 2,
       'a bulk delete that reports success having removed 8 of 10 hides the two that stayed');
    ok('and each one carries its reason', o.res.failed.every(f => f.why && f.row && f.row.id));
    ok('a row that REFUSED stays in the local store',
       o.left.map(r => r.id).sort().join(',') === 'r3,r7',
       'left: ' + o.left.map(r => r.id).join(',') + ' — dropping it locally would make a row that ' +
       'still exists on the server vanish from the screen');
    ok('the rows that went are gone from it', o.left.length === 2);
    ok('requests are bounded, not 10 at once', o.peak <= 4,
       'peak concurrency was ' + o.peak + '; 400 concurrent DELETEs against a single-process ' +
       'server is a self-inflicted outage');

    F(mk(0), []).then(e => {
      ok('an empty list is not an error', e.res.done === 0 && e.res.failed.length === 0);
      rest();
    });
  });
}

function rest() {
// ══ 16 · the two group controls ════════════════════════════════════════════════════════════════
console.log('\n16 · A group is the master activity, and both controls act on exactly its rows\n');

const GROWS = take('function _pdGroupRows(', '_pdGroupRows');
ok('the group\'s rows are found by asking _pdGroupOf, the same question the renderer asked',
   /_pdRows\(pid\)\.filter\(r => _pdGroupOf\(pid, r\) === cat\)/.test(GROWS),
   'a second definition of "which rows are in this group" would let the number in the dialog and ' +
   'the number on screen disagree');
ok('and from _pdRows, so it cannot reach into another detail schedule',
   /_pdRows\(pid\)/.test(GROWS) && !/_pdAllRows/.test(GROWS),
   '_pdAllRows ignores the schedule picker — a group delete would take rows the user is not looking at');

const REFILE = take('async function pdGroupRefile(', 'pdGroupRefile');
ok('re-filing offers the same activity tree the import and the edit form use',
   /_qaDynOptions\('pm_task_opts'\)/.test(REFILE));
ok('it says so and stops when the project has no master schedule at all',
   /No master activities yet|Master Schedule first/.test(REFILE),
   'an empty dropdown is a dead end with no explanation');
ok('cancelling writes nothing, and that is distinguished from choosing "unassigned"',
   /if \(pick === null\) return;/.test(REFILE),
   "'' is a real answer — it means unassign them — so only null may mean 'they backed out'");
ok('rows already on the target are left alone',
   /already = list\.filter\(r => String\(r\.taskRef \|\| ''\)\.trim\(\) === String\(pick\)\.trim\(\)\)/.test(REFILE) &&
   /todo = list\.filter\(r => String\(r\.taskRef \|\| ''\)\.trim\(\) !== String\(pick\)\.trim\(\)\)/.test(REFILE),
   'so the count in the dialog is the count that will change');
ok('and if none would change it says so instead of writing',
   /if \(!todo\.length\)[\s\S]{0,160}return;/.test(REFILE));
ok('it asks before writing', REFILE.indexOf('tkConfirm(') < REFILE.indexOf("method: 'PATCH'"));
ok('the confirm names both ends of the move', /From: /.test(REFILE) && /To: /.test(REFILE));
ok('and promises that no reported progress changes',
   /No reported quantities or progress are changed/.test(REFILE),
   'this is the whole reason re-filing is safe to do in bulk — say it');
ok('re-filing does NOT ask for a PIN',
   !/_pdPinGate/.test(REFILE),
   'it is reversible — re-file back — and a gate on a reversible act trains people to type the PIN ' +
   'without reading');
ok('the PATCH sends the whole record',
   /Object\.assign\(\{\}, r, \{ taskRef: pick \}\)/.test(REFILE),
   '/api/coll PATCH REPLACES the item');
ok('failures are reported', /bad\.push\(/.test(REFILE) && /bad\.length/.test(REFILE));
ok('and it is audited', /tkAudit\('Detail lines re-filed'/.test(REFILE));

const GDEL = take('async function pdGroupDelete(', 'pdGroupDelete');
ok('deleting a group asks for confirmation', /tkConfirm\(/.test(GDEL));
ok('the dialog states the exact number of lines', /list\.length \+ ' line\(s\) will be deleted/.test(GDEL));
ok('and separately how many carry REPORTED progress',
   /reported = list\.filter\(r => _pdLog\(r\)\.length\)\.length/.test(GDEL),
   'a line nobody has reported against is a plan; a line with readings is a record of what happened ' +
   'on site, and one number for both understates what is being destroyed');
ok('then asks for the signing PIN', /_pdPinGate\(/.test(GDEL));
ok('confirm first, PIN second', GDEL.indexOf('tkConfirm(') < GDEL.indexOf('_pdPinGate('));
ok('and a refused PIN stops it', /if \(!await _pdPinGate\([\s\S]{0,200}\)\) return;/.test(GDEL));
ok('IT DELETES ONLY pm_detail — the master activity is untouched',
   /_pmBulkDelete\(_PD_COLL, list\)/.test(GDEL) && !/pm_tasks/.test(GDEL),
   'deleting the site\'s reporting lines must never remove the contract activity above them');
ok('and the dialog says that out loud', /master activity itself is not touched/.test(GDEL));
ok('the group\'s collapsed flag is cleared when the group is gone',
   /delete _pdCol\[cat\]/.test(GDEL),
   '_pdCol is keyed by the group NAME, so a later group sharing it would render folded shut');
ok('it is audited', /tkAudit\('Detail lines deleted'/.test(GDEL));

// the controls themselves, in the rendered header row
const REG = take('function _pdRegister(', '_pdRegister');
ok('the group header carries Move and Delete',
   /pdGroupRefile\(/.test(REG) && /pdGroupDelete\(/.test(REG));
ok('clicking them does not also collapse the group',
   /onclick="event\.stopPropagation\(\)"/.test(REG),
   'the whole header row is the collapse toggle — without this every click folds the group away ' +
   'underneath the dialog it just opened');
ok('the group name is passed as JSON, so a name with a quote in it survives the attribute',
   /_tkEscA\(JSON\.stringify\(cat\)\)/.test(REG));

// ══ 17 · clearing the master schedule ══════════════════════════════════════════════════════════
console.log('\n17 · Clearing the Master Schedule, and the detail lines that must survive it\n');

const WIPE = take('async function pmMasterWipe(', 'pmMasterWipe');
ok('it deletes pm_tasks', /_pmBulkDelete\('pm_tasks', list/.test(WIPE));
ok('IT DELETES NO DETAIL LINES',
   !/_pmBulkDelete\(_PD_COLL|_pmBulkDelete\('pm_detail'/.test(WIPE),
   'the single most destructive act in the module — the site\'s reported progress must survive it');
ok('it counts the detail lines that will be unlinked, before asking',
   /linked = details\.filter\(r => refs\[String\(r\.taskRef \|\| ''\)\.trim\(\)\]\)\.length/.test(WIPE));
ok('and tells the user those lines are NOT deleted',
   /Those lines are NOT/.test(WIPE));
ok('and that they re-link themselves on a re-import with the same WBS codes',
   /re-link on their own if you import a schedule using the same WBS codes/.test(WIPE),
   'taskRef is matched on the WBS STRING, not an id — this is the difference between a routine ' +
   're-issue and a disaster, so the dialog has to say it');
ok('it also counts the WBS package links that will have to be set again',
   /linkedDeliv = list\.filter\(t => t\.delivId\)\.length/.test(WIPE),
   'that link lives on the ACTIVITY, so unlike taskRef it does NOT come back by itself');
ok('and flags activities carrying a baseline or a signature',
   /signed = list\.filter\(t => t\.signatures \|\| t\.baselineFinish\)\.length/.test(WIPE));
ok('it asks, then asks for the signing PIN',
   WIPE.indexOf('tkConfirm(') < WIPE.indexOf('_pdPinGate(') && /_pdPinGate\(/.test(WIPE));
ok('a refused PIN stops it', /if \(!await _pdPinGate\([\s\S]{0,200}\)\) return;/.test(WIPE));
ok('an empty schedule is refused with a message, not a no-op',
   /if \(!list\.length\)[\s\S]{0,140}return; \}/.test(WIPE));
ok('progress is reported while it runs',
   /_pmBulkDelete\('pm_tasks', list, \(n, tot\)/.test(WIPE),
   'clearing 200 activities is 200 requests — a silent minute reads as a hung page');
ok('it is audited, with the unlink count',
   /tkAudit\('Master schedule cleared'/.test(WIPE) && /detail line\(s\) unlinked/.test(WIPE));

const BTN = take('function pmMasterWipeBtn(', 'pmMasterWipeBtn');
ok('the button is absent when there is nothing to clear',
   /if \(!_pmScopeFor\('pm_tasks', pid\)\.length\) return '';/.test(BTN),
   'a destructive control whose only possible outcome is "there was nothing to do"');
ok('and it is on the Activities card',
   /pmMasterWipeBtn\(pid\) \+ schExportBtn\(pid\) \+ pmImportBtn\(\)/.test(src),
   'next to Export and Import, which are what you press straight afterwards');

console.log('\n  ' + pass + ' passed, ' + fail + ' failed\n');
process.exit(fail ? 1 : 0);
}
