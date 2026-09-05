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
  // Read out of the tab entry rather than matched as one frozen string: the list grows (drawings
  // were the sixth), and an assertion that has to be retyped every time one is added is an
  // assertion somebody eventually retypes without checking.
  const tab = (src.match(/\{ k: 'accept',[\s\S]*?\] \},/) || [''])[0];
  ok('it declares every register it reads',
     ['pm_projects', 'pm_settings', 'pm_acc', 'pm_acc_items', 'pm_acc_plans', 'pm_acc_forms',
      'pm_acc_defects', 'pm_acc_drawings'].every(c => tab.indexOf("'" + c + "'") > 0),
     'a tab that does not declare `need` renders an empty register and calls it empty — ' + tab.slice(0, 200));
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

// ══ 6 · the drawing mark-up: three ways it lost work, and one it printed the wrong thing ═══════
console.log('\nThe drawing mark-up saves what was drawn, and prints what was saved\n');
{
  const write = take('async function _accDrawWrite(', '_accDrawWrite');
  ok('the new _rev is taken back off the write',
     /if \(saved && saved\._rev != null\) row\._rev = saved\._rev;/.test(write),
     'tkApi turns a PATCH\'s _rev into an If-Match, so a row held open across two saves sends the ' +
     'version it was loaded at — every mark after the first 409d and silently vanished');
  ok('a save asked for during a save is queued, not dropped',
     /_accDraw\.again = true; return;/.test(write) &&
     /if \(_accDraw\.again\) \{ _accDraw\.again = false; _accDrawWrite\(\); \}/.test(write),
     '"if (saving) return" lost the marks drawn during the round trip, while the status still ' +
     'said saved from an earlier one');
  ok('a refused write re-reads rather than pushing the stale marks back',
     /_accDraw\.again = false; *\/\/ the re-read is now the truth/.test(write));
  ok('the raster is never echoed back on a shapes save',
     /if \(!body\.image\) delete body\.image;/.test(write),
     'the row in hand may have come from a read that stripped the image — sending it as it stands ' +
     'blanks the drawing');

  const printFn = take('async function accPrint(', 'accPrint');
  ok('printing re-reads EVERY drawing, not only the ones missing a raster',
     /const all = _accView\.drawings \|\| \[\];/.test(printFn) &&
     /if \(Array\.isArray\(full\.shapes\)\) r\.shapes = full\.shapes;/.test(printFn),
     'fetching only imageless rows printed the mark-up as it stood when the dossier was opened — ' +
     'on the sheet a client and a consultant sign');

  const sheet = take('function _accSheetDrawing(', '_accSheetDrawing');
  ok('a drawing that did not load prints a reason, never an empty frame',
     /did not load/.test(sheet),
     'a blank box on a numbered sheet reads as a drawing with nothing on it');
  ok('the sheet reuses the editor\'s renderer',
     /_accShapesSvg\(row\.shapes \|\| \[\], false\)/.test(sheet),
     'a second print-only renderer is how the screen and the paper come to disagree');

  // Marks are stored in the drawing's own pixels, so the panel's numbers have to be scaled.
  const down = take('function accDrawDown(', 'accDrawDown');
  ok('stroke and text size are scaled to the drawing\'s resolution',
     /sw: Math\.max\(1, _accDraw\.sw \* k\)/.test(down) && /fs: Math\.round\(_accDraw\.fs \* k\)/.test(down),
     'a stroke of 3 on a 2200px sheet shown at 330px is under half a screen pixel — invisible');
  const toShape = take('function _accDragToShape(', '_accDragToShape');
  ok('and so is the "that was a tap, not a drag" threshold',
     /far < 6 \* _accK\(\)/.test(toShape),
     'six drawing pixels on a 2200px sheet is a fifth of a screen pixel, so the test never fired');

  // Picking a tool must not repaint the dossier.
  const tool = take('function accDrawTool(', 'accDrawTool');
  ok('choosing a tool restyles the toolbar instead of repainting the detail',
     /data-acctool/.test(tool) && tool.indexOf('_accPaintDetail(') < 0,
     'repainting threw the <img> away and re-decoded the drawing on every tap, resetting scroll');

  const save = take('function _accDrawSave(', '_accDrawSave');
  ok('the thumbnail strip is kept in step with the editor',
     /mirror\.shapes = shapes;/.test(save),
     '_accView.drawings is a different object — without this the strip said "0 marks" beside a ' +
     'drawing covered in them');
}

// ══ 7 · what the module stores, and what it deliberately does not ══════════════════════════════
console.log('\nThe mark-up is data, and the dimension tool does not invent a measurement\n');
{
  const dim = take('function _accDimSvg(', '_accDimSvg');
  ok('a dimension prints the typed label and nothing computed',
     /String\(s\.label == null \? '' : s\.label\)/.test(dim) && !/Math\.sqrt[^;]*toFixed/.test(dim),
     'the app does not know the drawing\'s scale; a number that looked like millimetres and was ' +
     'not would be worse than none, on a sheet somebody signs');

  const svgFn = take('function _accShapeSvg(', '_accShapeSvg');
  ok('text is escaped before it goes into the SVG',
     /_accE\(s\.t \|\| ''\)/.test(svgFn));
  ok('every tool in the palette has a renderer',
     ['hl', 'box', 'cloud', 'arr', 'line', 'pen', 'text', 'dim']
       .every(k => svgFn.indexOf("case '" + k + "'") > 0),
     'a tool that draws nothing looks like a broken pointer, not a missing case');
  ok('an unknown kind renders nothing rather than throwing',
     /default:\s*\n\s*return '';/.test(svgFn),
     'one bad row must not take the whole drawing down');
}


// ══ 8 · the library at 97 forms, and the adoption step ═════════════════════════════════════════
console.log('\nA library this size is searched, not scrolled — and adopting is not copying\n');
{
  const tab = take('function _accFormsTab(', '_accFormsTab');
  ok('the discipline column carries counts, so the size of each is visible before clicking',
     /lines \+ ' ' \+ _t2\('lines'/.test(tab) && /rows\.length/.test(tab),
     'ten forms is a list; ninety-seven under one heading is a scroll');
  ok('the list is filtered by a search box',
     /_accFold\(\[f\.code, f\.vi, f\.en, f\.standard\]/.test(tab),
     'finding PP-EL-205 by eye is the slowest part of compiling a dossier');
  ok('the search is accent- and case-insensitive',
     /normalize\('NFD'\)/.test(take('function _accFold(', '_accFold')),
     'the library is written in Vietnamese and searched on whatever keyboard is to hand');
  ok('a form shows which of the three states it is in',
     /_t\('adopted'\)/.test(tab) && /_t\('project draft'\)/.test(tab) && /_t\('template'\)/.test(tab),
     'shipped template, project draft and adopted are three different things to sign against');
  ok('and who reviewed it, once one has',
     /f\.adoptedBy/.test(tab));

  const repaint = take('function _accRepaintFormList(', '_accRepaintFormList');
  ok('the search swaps the list by ID rather than by DOM position',
     /getElementById\('acc-form-list'\)/.test(repaint),
     'the first version reached for it structurally and matched the wrong node once a KPI strip ' +
     'appeared above the card — the box then filtered nothing, silently');
  ok('…and falls back to a full repaint rather than doing nothing',
     (repaint.match(/_accRepaint\(\); return;/g) || []).length >= 2);

  const adopt = take('async function accFormAdopt(', 'accFormAdopt');
  ok('copying a template in never marks it adopted',
     /adopted: false, origin: 'copied'/.test(adopt),
     'copying is not reviewing; treating them as one act lets a project mark a hundred forms ' +
     'adopted in an afternoon with nobody having read one');
  const approve = take('async function accFormApprove(', 'accFormApprove');
  ok('adopting is a separate, confirmed act that records who and when',
     /adopted: true/.test(approve) && /adoptedBy/.test(approve) && /adoptedOn/.test(approve) &&
     /await tkConfirm/.test(approve));
}

// ══ 9 · stages and evidence ════════════════════════════════════════════════════════════════════
console.log('\nWhere in the build it sits, and what has to be with it\n');
{
  const stages = take('function _accStagesFor(', '_accStagesFor');
  ok('the stage list is filtered to the discipline',
     /\(x\.disc \|\| \[\]\)\.indexOf\(d\) >= 0/.test(stages),
     'an electrician should not scroll past foundations to find first fix');
  ok('…and falls back to every stage rather than none',
     /return mine\.length \? mine : all;/.test(stages),
     'an empty dropdown is unfillable, which is worse than an over-long one');

  const changed = take('function _accNewStageChanged(', '_accNewStageChanged');
  ok('choosing a concealed stage says so at the moment it is chosen',
     /st\.covered/.test(changed) && /covered up/.test(changed),
     'a concealed work acceptance is the only kind that cannot be redone');

  const ev = take('function _accEvidenceCard(', '_accEvidenceCard');
  ok('the dossier says what documents have to travel with the minute',
     /evidence_vi : t\.evidence_en/.test(ev),
     'the commonest reason a dossier comes back is a missing attachment, not a failed inspection');
  ok('and who has to attend',
     /attends_vi : t\.attends_en/.test(ev));
  ok('the notice period is labelled as a convention, not a rule',
     /a convention, not a legal requirement/.test(ev),
     'it is in no article; presenting it as law is the same error as citing a withdrawn standard');
  ok('the card is absent when the type carries no evidence list',
     /if \(!ev\.length\) return '';/.test(ev),
     'an empty panel headed "what has to be with this minute" reads as "nothing does"');

  ok('the stage reaches the server on compose and on save',
     /stage: g\('stage'\)/.test(src) && /'standardRef', 'stage', 'jobDescription'/.test(src));
}


// ══ 10 · the coverage screen: a number is only drawn when it means something ═══════════════════
console.log('\nCoverage draws a percentage only when the percentage is true\n');
{
  const tab = take('function _accCoverTab(', '_accCoverTab');
  ok('every figure comes from the server, none is recomputed here',
     /_ACCCOV/.test(tab) && tab.indexOf('.filter(') < 0,
     'this number ends up in a progress report; a second implementation would eventually disagree ' +
     'with the server and nobody could say which was right');
  ok('the trust banner decides whether bars are drawn at all',
     /const showBars = tr\.level === 'full' \|\| tr\.level === 'partial';/.test(tab),
     'a coverage bar over a register where nothing is linked is a picture of an assumption');
  ok('and the banner is rendered before anything else on the screen',
     tab.indexOf('const banner') < tab.indexOf('const kpis'));

  const reg = take('function _accCovRegister(', '_accCovRegister');
  ok('with bars suppressed, the screen SAYS why rather than showing nothing',
     /the most confident thing on this screen and the least true/.test(reg));
  ok('outstanding rows sort above finished ones, overdue above those',
     /const rank = r => \(r\.overdue \? 0/.test(reg),
     'sorting by number makes somebody scroll past everything finished to find what is not');

  const load = take('async function _accCovLoad(', '_accCovLoad');
  ok('coverage is refetched when the project changes',
     /_ACCCOV\._pid === pid/.test(load),
     'a cached figure from another project is the worst kind of wrong number');

  const exp = take('function accCovExport(', 'accCovExport');
  ok('the trust line travels with the CSV export',
     /\(c\.trust \|\| \{\}\)\.en/.test(exp) && /\(c\.trust \|\| \{\}\)\.vi/.test(exp),
     'a CSV of coverage without its error bar, in the format most likely to be pasted into a report');

  const links = take('function _accCovLinks(', '_accCovLinks');
  ok('the link screen says suggestions are never applied on their own',
     /nothing is linked until you say so/.test(links));
  ok('…and when it can suggest nothing it says to link by hand rather than guessing',
     /refuses to do/.test(links));
  ok('a suggestion shows the REASON it is offered',
     /the dossier quotes this ITP number/.test(links) &&
     /only one ITP has this title/.test(links));
  ok('and flags an ITP that already carries a dossier',
     /alreadyLinkedElsewhere/.test(links),
     'legitimate after a re-inspection, but the person confirming should see it rather than ' +
     'discover it');

  const stages = take('function _accCovStages(', '_accCovStages');
  ok('every stage is listed, including the empty ones',
     /\(c\.stages \|\| \[\]\)\.map/.test(stages),
     'a stage missing from the list reads as a stage with no work in it');
  ok('dossiers naming no stage, or an unknown one, are reported rather than dropped',
     /c\.stageNotStated/.test(stages) && /c\.stageUnknown/.test(stages),
     'a row that vanishes from a coverage screen is the worst kind of missing');
  ok('concealed stages are marked on this screen too',
     /_t\('concealed'\)/.test(stages));
}


// ══ 11 · the completion dossier index: counted and declared must not look the same ═════════════
console.log('\nThe index shows what the register holds and what somebody merely said\n');
{
  const tab = take('function _accIndexTab(', '_accIndexTab');
  ok('a counted row shows HOW MANY records stand behind it',
     /record\(s\) in the register/.test(tab),
     'a bare tick would make "the register contains 47 of these" and "somebody said so" identical');
  ok('a declared row shows WHOSE word it is, and when',
     /r\.declaredBy/.test(tab) && /r\.declaredOn/.test(tab));
  ok('a counted row offers no way to tick it by hand',
     /cannot be ticked by hand/.test(tab) && /_t\('automatic'\)/.test(tab),
     'if it could be ticked, the index would report a dossier the register cannot produce');
  ok('the two totals are reported separately, never added',
     /_t\('Counted from the registers'\)/.test(tab) && /_t\('Declared by a person'\)/.test(tab));
  ok('an empty register says so rather than rendering blank',
     /nothing in the register yet/.test(tab) && /nobody has confirmed this/.test(tab),
     'a blank cell reads as "not applicable" — the two states must be distinguishable');
  ok('optional rows say they are optional',
     /_t\('only where it applies'\)/.test(tab),
     'reporting Điều 23 stage acceptance as a gap puts work on a list nobody can clear');

  const dec = take('async function accIdxDeclare(', 'accIdxDeclare');
  ok('confirming a row says out loud that it is an attestation',
     /this is an attestation, not a tick/.test(dec));
  ok('withdrawing warns that the name comes off',
     /Your name comes off it/.test(dec));

  const na = take('async function accIdxApplies(', 'accIdxApplies');
  ok('striking a row off asks why, and abandons if nothing is given',
     /if \(!why\) return;/.test(na),
     'an item struck off the completion dossier with no reason is the one an auditor asks about');

  const exp = take('function accIdxExport(', 'accIdxExport');
  ok('the export marks each row counted or declared',
     /'counted' : 'declared'/.test(exp),
     'a list of ticks pasted into a report has lost the half that says which is evidence');
  ok('and carries the verdict in both languages',
     /\(ix\.verdict \|\| \{\}\)\.en/.test(exp) && /\(ix\.verdict \|\| \{\}\)\.vi/.test(exp));

  const pr = take('function accIdxPrint(', 'accIdxPrint');
  ok('the printed sheet quotes the article it comes from',
     /Phụ lục VIb/.test(pr) && /Điều 26/.test(pr));
  ok('…and prints the counted-vs-declared distinction rather than a column of ticks',
     /counted from the registers/.test(pr) && /not verified by the system/.test(pr));
  ok('a quantity is printed for counted rows and a reference for declared ones',
     /r\.count \? r\.count \+ ' bộ \/ sets'/.test(pr));

  const sig = take('function _accIdxSigBlocks(', '_accIdxSigBlocks');
  ok('the index is signed by the three parties that hand the dossier over',
     /Compiled by/.test(sig) && /Supervision consultant/.test(sig) && /Client/.test(sig),
     'not the same list as an acceptance minute — the designer does not certify a bound set they ' +
     'did not assemble');
}

console.log('\n' + pass + ' passed, ' + fail + ' failed\n');
process.exit(fail ? 1 : 0);
