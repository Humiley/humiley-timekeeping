/* The acceptance dossier's browser half: the three things that were WRONG when it was first run.
 *
 * acceptance.py is exercised by tests/test_acceptance.py and the routes by
 * tests/test_acceptance_api.py. What neither can see is the code that draws the screen and the
 * printed sheet, and all three defects below were found by opening it rather than by reading it:
 *
 *   1. the printed minute took its Vietnamese title from _accLbl(), which returns whichever
 *      language the OPERATOR'S UI is in — so an English session printed
 *      "BIÊN BẢN NGHIỆM THU ACCEPTANCE OF CONSTRUCTION WORK" on the line that has to be
 *      Vietnamese. The sheet is bilingual by construction; its language is a property of the
 *      DOCUMENT, not of the person printing it;
 *   2. the "Compile a dossier" dialog defaulted the acceptance TYPE to whatever was first in the
 *      catalogue — Điều 12 incoming materials — when the overwhelming majority of dossiers on any
 *      project are Điều 21 construction work. That field decides which article the minute cites,
 *      who signs it and what must already be accepted underneath it, so getting it wrong silently
 *      produces a register that reads as a chain nobody actually walked;
 *   3. the checklist-library CSV import is the one place a contractor's real library arrives, and
 *      a split(',') would shred every Vietnamese line that contains a comma — silently, into a
 *      library that looks imported.
 *
 *   node tests/acceptance_screens.js
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
  if (i < 0) {
    console.error('Could not find ' + what + ' — update the marker, do NOT delete this test.');
    process.exit(2);
  }
  const ends = ['\nfunction ', '\nasync function ', '\nconst ', '\nlet ']
    .map(e => src.indexOf(e, i + 10)).filter(x => x > 0);
  return src.slice(i, Math.min.apply(null, ends));
};

// ══ 1 · the printed sheet's language is the document's, not the operator's ══════════════════════
console.log('\nThe printed minute is bilingual whatever language the app is in\n');
{
  const minute = take('function _accSheetMinute(', '_accSheetMinute');
  ok('the title line comes from the type\'s own vi/en, not from _accLbl',
     /_accSheetHead\(v, String\(t\.vi \|\|[^)]*\), String\(t\.en/.test(minute),
     'an English session printed the English title on the Vietnamese line');
  // Comments stripped first. The comment above the fix NAMES the function it stopped calling, so
  // a plain substring search reports the bug still present in the code that fixed it — the same
  // shape as a check that passes on something it never looked at, pointed the other way.
  const minuteCode = minute.replace(/\/\*[\s\S]*?\*\//g, '');
  ok('_accLbl is not CALLED anywhere on the minute sheet',
     minuteCode.indexOf('_accLbl(') < 0,
     '_accLbl picks the UI language — on a printed form that is never the right answer');

  // The signature blocks carry both languages for the same reason.
  const sig = take('function _accSigBlocks(', '_accSigBlocks');
  ok('every signature block prints the party in both languages',
     /_accE\(p\.vi\)/.test(sig) && /_accE\(p\.en\)/.test(sig));
  ok('and the role line under it is the Vietnamese one the form carries',
     /_accE\(p\.role_vi\)/.test(sig));
}

// ══ 2 · the field that decides which article the minute cites ═══════════════════════════════════
console.log('\nThe kind of acceptance does not default to whatever is first in the catalogue\n');
{
  const dlg = take('async function accNewDossier(', 'accNewDossier');
  ok('it defaults to Điều 21 construction work',
     /\? 'material' : 'work'/.test(dlg) || /'work'\s*\)/.test(dlg),
     'the first entry in the catalogue is Điều 12 incoming materials, which almost no dossier is');
  ok('…except for the incoming-materials discipline, which identifies itself',
     /=== 'OSM'/.test(dlg));
  ok('and a caller-supplied type still wins',
     /preset && preset\.accType/.test(dlg));
  ok('an unknown type is not forced onto the select',
     /\[\.\.\.e\.options\]\.some\(o => o\.value === want\)/.test(dlg),
     'assigning an absent value silently leaves the select on its first option — the bug again');
}

// ══ 3 · the CSV a contractor's library actually arrives as ══════════════════════════════════════
console.log('\nThe checklist import survives a real Excel export\n');
{
  const parse = new Function(
    take('function _accCsvRows(', '_accCsvRows') +
    take('function _accParseFormsCsv(', '_accParseFormsCsv') +
    '\nreturn { rows: _accCsvRows, forms: _accParseFormsCsv };')();

  const CSV = '﻿code,discipline,form_vi,form_en,standard,item_vi,item_en,method,criteria\r\n' +
    'PP-EL-401,ELE,"Lắp đặt tủ điện, thanh cái","Installation of switchboard, busbar",TCVN 7447,' +
      '"Vị trí, cao độ đúng bản vẽ","Position and level as drawing",Đo,±10 mm\r\n' +
    'PP-EL-401,ELE,,,,"Mô men siết bu lông đạt yêu cầu","Bolt torque as specified",Cờ lê lực,Nhà sản xuất\r\n' +
    'PP-FF-201,FF,"Thử áp lực đường ống","Pipework pressure test",TCVN 7336,' +
      '"Giữ áp 2 giờ không tụt","Hold pressure 2h with no drop",Thí nghiệm,TCVN 7336\r\n';

  const forms = parse.forms(CSV);
  ok('rows group into one form per code', forms.length === 2, 'got ' + forms.length);
  ok('a form collects every line that names it',
     forms[0].items.length === 2, JSON.stringify(forms[0].items.length));
  ok('a quoted comma stays inside its field',
     forms[0].vi === 'Lắp đặt tủ điện, thanh cái',
     'got ' + JSON.stringify(forms[0].vi) + ' — split(",") would have shredded it');
  ok('and inside a checklist line too',
     forms[0].items[0].vi === 'Vị trí, cao độ đúng bản vẽ',
     'got ' + JSON.stringify(forms[0].items[0].vi));
  ok('the BOM Excel writes is stripped from the first header',
     forms[0].code === 'PP-EL-401',
     'got ' + JSON.stringify(forms[0].code) + ' — an un-stripped BOM makes the "code" column unfindable');
  ok('CRLF does not leave a stray \\r on the last column',
     forms[0].items[0].criteria === '±10 mm',
     'got ' + JSON.stringify(forms[0].items[0].criteria));
  ok('a second form is read independently',
     forms[1].code === 'PP-FF-201' && forms[1].items.length === 1);

  let threw = '';
  try { parse.forms('a,b,c\r\n1,2,3\r\n'); } catch (e) { threw = e.message; }
  ok('a CSV without the columns it needs SAYS SO rather than importing nothing',
     /missing the "code" column/.test(threw),
     'a silent empty import is how a half-loaded library is discovered at an inspection');

  ok('an empty file yields no forms rather than throwing',
     parse.forms('').length === 0);
}

// ══ 4 · the browser's result reading agrees with the server's ═══════════════════════════════════
console.log('\nA checklist result is read the same way on both sides\n');
{
  const res = new Function(take('function _accRes(', '_accRes') + '\nreturn _accRes;')();
  ['Đạt', 'dat', 'Pass', 'P', 'ok', 'YES'].forEach(v =>
    ok('"' + v + '" reads as pass', res(v) === 'pass'));
  ['Không đạt', 'khong dat', 'K.Đạt', 'Fail', 'KĐ'].forEach(v =>
    ok('"' + v + '" reads as fail', res(v) === 'fail'));
  ['', '?', 'see note', 'xyz', null, undefined].forEach(v =>
    ok(JSON.stringify(v) + ' reads as pending, never pass', res(v) === 'pending',
       'an unreadable cell must not close a checklist line'));

  const prog = new Function(
    take('function _accRes(', '_accRes') +
    take('function _accProgress(', '_accProgress') +
    take('function _accResultOf(', '_accResultOf') +
    '\nreturn { p: _accProgress, r: _accResultOf };')();
  const p = prog.p([{ result: 'Đạt' }, { result: 'Đạt' }, { result: 'N/A' }, { result: 'N/A' }]);
  ok('progress is measured against the APPLICABLE lines', p.pct === 100,
     'got ' + p.pct + '% — counting N/A lines as work outstanding teaches people to ignore the number');
  ok('a failed line beats unchecked ones',
     prog.r([{ result: 'Fail' }, {}, {}]) === 'fail',
     'reporting "not checked" lets a failure hide behind an incomplete form');
  ok('an empty checklist is pending, not pass', prog.r([]) === 'pending');
}

// ══ 5 · the tab is wired the way the rest of the workspace is ══════════════════════════════════
console.log('\nThe tab is registered where a project workspace looks for it\n');
{
  ok('the Acceptance tab exists in _PM_TABS',
     /\{ k: 'accept', label: 'Acceptance', fn: 'pmRenderAcceptance'/.test(src));
  ok('it asks for the five registers it reads',
     /'pm_acc', 'pm_acc_items', 'pm_acc_plans', 'pm_acc_forms', 'pm_acc_defects'\] \}/.test(src),
     'a tab that does not declare `need` renders an empty register and calls it empty');
  ok('every sub-tab names a function that exists',
     /const _ACC_TABS = \[/.test(src) &&
     ['_accBoard', '_accPlanTab', '_accRegTab', '_accFormsTab', '_accSetupTab']
       .every(f => src.indexOf('function ' + f + '(') > 0));
  ok('the accept button is gated on the SERVER\'s verdict, not a locally recomputed one',
     /const gated = next && next\[0\] === 'Accepted' && v\.canAccept === false;/.test(src),
     'two implementations of one gate disagree eventually, and people believe the green one');
  const signCard = take('function _accSignCard(', '_accSignCard');
  ok('…and recording a FAILED inspection is never gated',
     /accSign\(\\?'Rejected\\?'\)/.test(signCard) && !/gated[\s\S]{0,120}Rejected/.test(signCard),
     'refusing to record a failure is the one refusal that stops people using the register');
}

console.log('\n' + pass + ' passed, ' + fail + ' failed\n');
process.exit(fail ? 1 : 0);
