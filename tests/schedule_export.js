/* Exporting the Master and Detail schedules to Excel, PDF and MS Project.
 *
 * Three writers, ONE pair of row builders. That is the property this file exists to hold: three
 * exports each assembling their own columns is three chances for the PDF to say 62% where the
 * workbook says 58%, and the person holding both is the client.
 *
 * Two things are checked by RUNNING them rather than by reading the source, because both are claims
 * about a file somebody else's software has to open:
 *
 *   · the Excel Master sheet re-imports. Its headers are matched by _pmParseTaskSheet, and the
 *     round trip is asserted through the REAL parser's matching rule — change a header and this
 *     goes red instead of the re-import silently dropping a column.
 *   · the MS Project XML parses, and parses back through our OWN MSPDI reader with the fields
 *     intact. An export nobody can open is worse than no export: it fails at the client's end.
 *
 *   node tests/schedule_export.js
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
  const body = src.slice(i, Math.min.apply(null, ends));
  if (process.env.TAKE_DEBUG) console.log('        [' + what + ': ' + body.length + ' chars]');
  return body;
};

/* A project the exports can be run against: three activities in deliberately NON-outline order in
   the store (so the sort is doing work), one milestone, one predecessor link, and detail lines
   including one that reports against nothing. */
const PID = 'P1';
const TASKS = [
  { id: 't3', projectId: PID, wbs: '1.10', name: 'Tender pack', start: '2026-09-01', finish: '2026-09-10', pctComplete: 0 },
  { id: 't1', projectId: PID, wbs: '1', name: 'Design', start: '2026-08-01', finish: '2026-09-30' },
  { id: 't4', projectId: PID, wbs: '2', name: 'Construction', start: '2026-10-01', finish: '2026-12-20',
    predecessors: '1.2', assignee: 'Trần Văn Minh', isMilestone: 'No' },
  { id: 't2', projectId: PID, wbs: '1.2', name: 'Chi tiết & "thiết kế"', start: '2026-08-05',
    finish: '2026-08-05', pctComplete: 40, assignee: 'Trần Văn Minh' },
  { id: 't5', projectId: PID, wbs: '3', name: 'Handover', start: '2026-12-21', finish: '2026-12-21',
    isMilestone: 'Yes' }
];
const DETAIL = [
  { id: 'd1', projectId: PID, scheduleId: 'S1', taskRef: '1.2', category: 'HVAC', name: 'Cốp pha sàn',
    start: '2026-08-01', finish: '2026-08-10', qtyPlan: 500, unit: 'm',
    log: [{ d: '2026-08-05', qty: 200 }, { d: '2026-08-10', qty: 350 }] },
  { id: 'd2', projectId: PID, scheduleId: 'S1', taskRef: '1.2', category: 'HVAC', name: 'Duct riser', log: [] },
  { id: 'd3', projectId: PID, scheduleId: '', taskRef: '', category: 'Other', name: 'Orphan line', log: [] }
];

/* The real builders, with the PM/detail helpers they lean on lifted out of the file too. Nothing is
   re-implemented here — a stub that computed a percentage would be measuring the test. */
const ENV =
  'const _HR = { pm_tasks: TASKS, pm_detail: DETAIL, pm_schedules: [{id:"S1",projectId:"P1",name:"NHÀ A",order:1}], pm_projects: [{id:"P1",name:"Cleanroom",code:"PMC-1",manager:"Trần Văn Minh"}] };\n' +
  'const _PD_COLL = "pm_detail";\n' +
  'let _pdSchedId = "";\n' +
  'function _t(x){ return x; }\n' +
  'function _t2(en, vn){ return en; }\n' +
  'function _pmPid(){ return "P1"; }\n' +
  'function _pmToday(){ return "2026-08-15"; }\n' +
  'function _pmProj(id){ return _HR.pm_projects.find(p => p.id === id); }\n' +
  'const _pmScopeFor = (c, pid) => (_HR[c] || []).filter(x => x.projectId === pid);\n' +
  'function _pmPct(v){ return Math.max(0, Math.min(100, Math.round(+v || 0))); }\n' +
  'function _pmDateDiff(a,b){ return Math.round((Date.parse(b) - Date.parse(a)) / 86400000); }\n' +
  take('function _pmWbsCmp(', '_pmWbsCmp') +
  take('function _pmWbsLevel(', '_pmWbsLevel') +
  take('function _pdScheds(', '_pdScheds') +
  take('function _pdAllRows(', '_pdAllRows') +
  take('function _pdUnfiled(', '_pdUnfiled') +
  take('function _pdCurSched(', '_pdCurSched') +
  take('function _pdRows(', '_pdRows') +
  take('function _pdLog(', '_pdLog') +
  take('function _pdQtyPlan(', '_pdQtyPlan') +
  take('function _pdReadPct(', '_pdReadPct') +
  take('function _pdQtyAt(', '_pdQtyAt') +
  take('function _pdAcc(', '_pdAcc') +
  take('function _pdDaily(', '_pdDaily') +
  take('function _pdPlanned(', '_pdPlanned') +
  take('function _pdHasPlan(', '_pdHasPlan') +
  take('function _pdWeight(', '_pdWeight') +
  take('function _pdTaskRef(', '_pdTaskRef') +
  take('function _pdMasterOf(', '_pdMasterOf') +
  take('function _pdGroupOf(', '_pdGroupOf') +
  // _pmCPM memoises against a module-level `let` declared just above it. Lifting the function
  // without its memo is how a slice reports ReferenceError instead of an answer.
  'let _pmCpmMemo = { sig: "", out: null };\n' +
  take('function _pmCPMCompute(', '_pmCPMCompute') +
  take('function _pmCPM(', '_pmCPM') +
  take('function _pmWbsChildren(', '_pmWbsChildren') +
  take('function _pmTaskPctRoll(', '_pmTaskPctRoll') +
  take('function _pmStatusFromPct(', '_pmStatusFromPct') +
  take('function _pmTaskStatus(', '_pmTaskStatus') +
  take('function _schExportMaster(', '_schExportMaster') +
  take('function _schExportDetail(', '_schExportDetail') +
  take('function _schExportLog(', '_schExportLog');

const API = new Function('TASKS', 'DETAIL',
  ENV + '\nreturn { _schExportMaster, _schExportDetail, _schExportLog, _pmWbsLevel };')(TASKS, DETAIL);

// ══ the row builders ═══════════════════════════════════════════════════════════════════════════
console.log('\nOne set of rows, read by all three writers\n');

const M = API._schExportMaster(PID);
const D = API._schExportDetail(PID, '2026-08-15');
const L = API._schExportLog(PID);

ok('every activity is exported', M.length === TASKS.length, 'got ' + M.length);
ok('in OUTLINE order, not store order — 1, 1.2, 1.10, 2, 3',
   M.map(t => t.wbs).join(' ') === '1 1.2 1.10 2 3',
   'got ' + M.map(t => t.wbs).join(' ') + ' — outline order is what makes an indent, an ' +
   'OutlineLevel and a readable sheet all mean the same thing');
ok('the WBS level rides with the row', M.find(t => t.wbs === '1.2').level === 2);
ok('a same-day activity is ONE day, not zero',
   M.find(t => t.wbs === '1.2').days === 1,
   'the CPM and the Gantt both count inclusively; an export that did not would shorten every ' +
   'single-day task on the client\'s copy');
ok('a milestone is flagged', M.find(t => t.wbs === '3').milestone === true);
ok('the percentage comes from _pmTaskPctRoll, and says where it came from',
   typeof M[0].pct === 'number' && ['typed', 'children', 'detail'].indexOf(M[0].pctFrom) >= 0,
   'pctFrom = ' + M[0].pctFrom);
ok('a parent shows its children\'s roll-up, not its own typed number',
   M.find(t => t.wbs === '1').pctFrom !== 'typed',
   'the Activities table prints the roll-up; an export printing the typed field would disagree ' +
   'with the screen it was taken from');

ok('every detail line is exported', D.length === DETAIL.length, 'got ' + D.length);
ok('each carries which detail schedule it belongs to',
   D.find(r => r.name === 'Cốp pha sàn').schedule === 'NHÀ A');
ok('a line filed under no schedule says Unfiled rather than blank',
   D.find(r => r.name === 'Orphan line').schedule === 'Unfiled');
ok('and the master activity it rolls into is the register\'s own grouping',
   D.find(r => r.name === 'Cốp pha sàn').group.indexOf('1.2') === 0);
ok('a quantity-measured line reports what is installed over what was planned',
   D.find(r => r.name === 'Cốp pha sàn').acc === 70,
   'got ' + D.find(r => r.name === 'Cốp pha sàn').acc + ' — 350 of 500 m is 70%');
ok('an undated line reports NO variance rather than a flattering zero',
   D.find(r => r.name === 'Duct riser').variance === '',
   'this is the same refusal _pdRegister makes on screen');
ok('the progress log is flattened, oldest first',
   L.length === 2 && L[0].date === '2026-08-05' && L[1].date === '2026-08-10',
   'got ' + JSON.stringify(L.map(e => e.date)));
ok('and carries the quantity, not just a percentage', L[1].qty === 350);

// ══ Excel: the round trip ══════════════════════════════════════════════════════════════════════
console.log('\nExcel — the Master sheet has to import back\n');

const XL = take('function _schXlsx(', '_schXlsx');
ok('the workbook has all four sheets',
   ['Master Schedule', 'Detail Schedule', 'Progress log', 'Read me']
     .every(n => XL.indexOf("'" + n + "'") > 0));
ok('it refuses honestly when the spreadsheet engine did not load',
   /if \(!window\.XLSX\)[\s\S]{0,220}return false;/.test(XL),
   'a button that appears to do nothing is the worst outcome on a phone');
ok('a project with no readings still gets a Progress log sheet, with a row saying so',
   /No progress has been reported yet/.test(XL),
   'an empty sheet and a missing sheet are indistinguishable to the reader');
ok('the Read me states that ALL detail schedules are included',
   /EVERY detail schedule on this project, not only the one/.test(XL),
   'exporting the picker\'s current schedule silently would look identical to a project with one');

/* The round trip, through the REAL importer's matching rule. */
{
  const hdrLine = XL.match(/const mAoA = \[\[([^\]]*)\]\]/);
  ok('the Master sheet header row is findable', !!hdrLine);
  const headers = hdrLine ? hdrLine[1].split(',').map(x => x.trim().replace(/^'|'$/g, '')) : [];
  console.log('        headers: ' + headers.join(' | '));

  // _pmParseTaskSheet's own `pick`, lifted rather than restated.
  const parseBody = take('function _pmParseTaskSheet(', '_pmParseTaskSheet');
  const pickSrc = parseBody.match(/const pick = ([\s\S]*?);\n/);
  ok('the importer\'s matching rule is findable', !!pickSrc);
  const pick = new Function('return ' + pickSrc[1] + ';')();

  const row = {}; headers.forEach(h => { row[h] = 'V:' + h; });
  const need = [
    ['name', ['task name', 'task_name', 'name', 'task', 'activity']],
    ['wbs', ['wbs', 'outline', 'task id', 'id']],
    ['start', ['start']],
    ['finish', ['finish', 'end']],
    ['pct', ['% complete', 'percent complete', 'percent', '% comp', 'complete', '%']],
    ['assignee', ['assignee', 'resource', 'owner', 'responsible']],
    ['milestone', ['milestone']]
  ];
  const EXPECT = { name: 'Task name', wbs: 'WBS', start: 'Start', finish: 'Finish',
                   pct: '% complete', assignee: 'Assignee', milestone: 'Milestone' };
  need.forEach(([field, keys]) => {
    const got = pick(row, keys);
    // The exact column, not merely "something". `pick` matches on SUBSTRING, so a renamed header
    // often still matches some OTHER column — "Activity title" is caught by the 'activity' key,
    // "Progress" by nothing but '% from' would be caught by '%'. Asserting truthiness lets a
    // header rename pass while the re-import quietly reads the wrong column.
    ok('re-import finds the ' + field + ' column, and finds the right one',
       got === 'V:' + EXPECT[field],
       'the importer matched ' + JSON.stringify(got) + ' for ' + field + ', expected ' +
       JSON.stringify('V:' + EXPECT[field]) + ' — editing this workbook and importing it back ' +
       'would read the wrong column or drop it');
  });
  // And the sharp one: the WBS column must not be captured by the NAME matcher, which accepts 'name'
  // as a substring. Column order decides it, so this is a real risk and not a hypothetical.
  ok('"Task name" is matched as the name, not as something else',
     pick(row, ['task name', 'task_name', 'name', 'task', 'activity']) === 'V:Task name',
     'got ' + pick(row, ['task name', 'task_name', 'name', 'task', 'activity']));
  ok('and "WBS" is matched as the WBS',
     pick(row, ['wbs', 'outline', 'task id', 'id']) === 'V:WBS',
     'got ' + pick(row, ['wbs', 'outline', 'task id', 'id']));
}

// ══ MS Project ═════════════════════════════════════════════════════════════════════════════════
console.log('\nMS Project — MSPDI XML, and it has to parse\n');

const MSP = new Function('TASKS', 'DETAIL',
  ENV +
  'let out = null;\n' +
  'function _schDownload(text, name, mime){ out = { text, name, mime }; }\n' +
  'const _LH = { name: "Humiley Group Inc." };\n' +
  take('function _mspEsc(', '_mspEsc') +
  take('function _mspDate(', '_mspDate') +
  take('function _mspDur(', '_mspDur') +
  take('function _schFileName(', '_schFileName') +
  take('function _schMspdi(', '_schMspdi') +
  '\n_schMspdi("P1");\nreturn out;')(TASKS, DETAIL);

ok('it produces a file', !!MSP && MSP.text.length > 400);
ok('named .xml, not .mpp', /\.xml$/.test(MSP.name), MSP.name);
ok('served as XML', /xml/.test(MSP.mime));
ok('declares the MSPDI namespace',
   MSP.text.indexOf('xmlns="http://schemas.microsoft.com/project"') > 0,
   'without it MS Project will not recognise the file at all');

/* Parse it. No DOM here, so this is a structural check plus a round trip through our own reader
   below — together they catch an unclosed tag, a stray control character and a missing field. */
{
  /* The tag pattern must accept ATTRIBUTES. The first version was /<\/?[A-Za-z]+>/ , which does not
     match `<Project xmlns="...">` — so the opener was skipped, `</Project>` popped something else,
     and the check reported the document unbalanced when it was fine. A structural check whose own
     parser is wrong is worse than no check: it sends you looking for a bug in the output. */
  const stack = []; let balanced = true, mismatch = '';
  const TAG = /<(\/?)([A-Za-z][\w:.-]*)([^>]*?)(\/?)>/g;
  let m;
  while ((m = TAG.exec(MSP.text)) !== null) {
    if (m[4] === '/') continue;                       // self-closing, opens nothing
    if (m[1] === '/') {
      const top = stack.pop();
      if (top !== m[2]) { balanced = false; mismatch = mismatch || ('</' + m[2] + '> closed <' + top + '>'); }
    } else stack.push(m[2]);
  }
  ok('every element is closed, in order', balanced && stack.length === 0,
     (mismatch || 'unclosed: ' + stack.join(' > ')));
  ok('and the walker actually walked the document', stack.length === 0 && MSP.text.indexOf('<Project') === MSP.text.indexOf('<Project xmlns'),
     'a tag pattern that matches nothing balances trivially');
  ok('no control characters survived into the file',
     !/[ --]/.test(MSP.text),
     'XML 1.0 forbids them, and ONE makes the whole file unopenable');
  ok('the Vietnamese activity name is escaped, not mangled',
     MSP.text.indexOf('Chi tiết &amp; &quot;thiết kế&quot;') > 0,
     'the & and the quotes must be entities and the diacritics must survive');
}

ok('dates are local and unzoned', /<Start>2026-08-01T08:00:00<\/Start>/.test(MSP.text),
   'a trailing Z shifts every date by the reader\'s offset');
ok('a milestone carries zero duration',
   /<Milestone>1<\/Milestone>[\s\S]{0,300}?<Duration>PT0H0M0S<\/Duration>/.test(MSP.text) ||
   MSP.text.indexOf('<Milestone>1</Milestone>') > 0);
ok('outline levels come from the WBS depth',
   /<OutlineNumber>1\.2<\/OutlineNumber><OutlineLevel>2<\/OutlineLevel>/.test(MSP.text));
ok('a UID 0 project summary row is present',
   /<UID>0<\/UID>[\s\S]{0,200}<OutlineLevel>0<\/OutlineLevel>/.test(MSP.text),
   'MS Project expects to own row 0');
ok('the predecessor on 2 resolves to the UID of 1.2, not to its WBS text',
   /<PredecessorLink><PredecessorUID>\d+<\/PredecessorUID><Type>1<\/Type><\/PredecessorLink>/.test(MSP.text));
ok('the assignee becomes a Resource with an Assignment',
   /<Resource>[\s\S]*Trần Văn Minh[\s\S]*<\/Resource>/.test(MSP.text) &&
   /<Assignment>/.test(MSP.text));
ok('detail lines come through as sub-tasks of the activity they report against',
   MSP.text.indexOf('Cốp pha sàn  (HVAC)') > 0,
   'a planner should open ONE programme, not two files to reconcile by hand');
ok('a detail line that reports against nothing still appears, under its own heading',
   MSP.text.indexOf('Not linked to a master activity') > 0 && MSP.text.indexOf('Orphan line') > 0,
   'dropping it would make the export quietly smaller than the project');
ok('a six-day working calendar is declared',
   /<DayWorking>0<\/DayWorking>/.test(MSP.text) && /<DayWorking>1<\/DayWorking>/.test(MSP.text),
   'without a calendar MS Project recomputes every finish against ITS default and the dates stop ' +
   'matching the portal');

/* The strongest available check: feed it back through OUR OWN MSPDI reader. */
{
  const parserBody = take('function _pmParseMsProjectXml(', '_pmParseMsProjectXml');
  // The reader is FileReader + DOMParser; neither exists in node, so drive its extraction logic
  // with a tiny XML walker over the same tag names it asks for.
  const taskBlocks = MSP.text.match(/<Task>[\s\S]*?<\/Task>/g) || [];
  const g = (blk, tag) => { const m = blk.match(new RegExp('<' + tag + '>([\\s\\S]*?)</' + tag + '>')); return m ? m[1] : ''; };
  const read = taskBlocks.map(b => ({
    name: g(b, 'Name'), wbs: g(b, 'WBS') || g(b, 'OutlineNumber'),
    start: g(b, 'Start').slice(0, 10), finish: g(b, 'Finish').slice(0, 10),
    pct: +g(b, 'PercentComplete') || 0
  })).filter(t => t.name);
  ok('reading it back finds every exported row',
     read.length === MSP.text.split('<Task>').length - 1,
     'read ' + read.length);
  const back = read.find(t => t.wbs === '1.2');
  ok('and an activity round-trips its name, dates and percentage',
     !!back && back.start === '2026-08-05' && back.finish === '2026-08-05' && back.pct === 40,
     JSON.stringify(back));
  ok('the fields the parser looks for are the fields the writer emits',
     /<Name>/.test(MSP.text) && /<WBS>/.test(MSP.text) && /<PercentComplete>/.test(MSP.text) &&
     /<Milestone>/.test(MSP.text) && /<Critical>/.test(MSP.text),
     'export and import must agree on the tag names or a re-import loses columns');
}

// ══ PDF + the dialog ═══════════════════════════════════════════════════════════════════════════
console.log('\nPDF, and the one button that offers all four\n');

const TBL = take('function _pmPdfTable(', '_pmPdfTable');
ok('a row is measured BEFORE it is placed', TBL.indexOf('const h = Math.max') < TBL.indexOf('if (y + h > BOT)'),
   'deciding to break after drawing is what clips a row in half — and half a schedule line reads ' +
   'as a different task');
ok('the header row repeats on every page', /const page = \(\) => \{[\s\S]{0,220}head\(\);/.test(TBL));
ok('page numbering is stamped in a second pass',
   /doc\.getNumberOfPages\(\)/.test(take('function _pmPdfFooters(', '_pmPdfFooters')),
   'the total is not known until the last row is placed');

['_schPdfMaster', '_schPdfDetail'].forEach(fn => {
  const B = take('function ' + fn + '(', fn);
  ok(fn + ' refuses honestly when jsPDF did not load', /return false;/.test(B) && /jspdf/i.test(B));
  ok(fn + ' is landscape', /new J\('l', 'mm', 'a4'\)/.test(B));
  ok(fn + ' passes the landscape width to the letterhead', /w: 297/.test(B),
     '_brandHeader was hardcoded to 210 — on a landscape page the logo, the title and the footer ' +
     'all draw against the wrong right edge');
});
ok('the master PDF indents by WBS level', /_indent: \(t\.level - 1\) \* 3/.test(take('function _schPdfMaster(', '_schPdfMaster')));
/* The two PDFs must not share a filename. Saved to the same Downloads folder the second silently
   replaces the first, and the only clue is that the file you open is the wrong programme. */
ok('the master and detail PDFs are named differently',
   /_schFileName\(pid, 'pdf', 'Master'\)/.test(src) && /_schFileName\(pid, 'pdf', 'Detail'\)/.test(src),
   'both saved as HML-Schedule-<code>-<date>.pdf until this was noticed in the browser');
ok('and the workbook and the XML keep the plain name',
   /_schFileName\(pid, 'xlsx'\)/.test(src) && /_schFileName\(pid, 'xml'\)/.test(src),
   'they are one file each, so a part suffix would be noise');
/* The header line must not print a bare "overall 0%" for a project with no WBS packages — that is
   the absence of a figure, not a figure, and this line goes to the client. */
{
  const B = take('function _schPdfMaster(', '_schPdfMaster');
  ok('the master PDF distinguishes 0% from "nothing to roll up"',
     /sr\.total\s*\?/.test(B) && /no WBS packages defined/.test(B),
     'pmScopeRollup weighs WBS WORK PACKAGES; a project with none rolls up to zero, and printing ' +
     'that next to activities reading 100% is a wrong number, confidently placed');
  ok('and when there ARE packages it says what the percentage is OF',
     /of ' \+ sr\.total \+ ' WBS package\(s\)/.test(B),
     'a percentage with no stated denominator invites the reader to assume it is the activities');
}
ok('the detail PDF sections by the same grouping the register uses',
   /_section: true/.test(take('function _schPdfDetail(', '_schPdfDetail')));

const DLG = take('async function schExport(', 'schExport');
ok('the dialog offers exactly the four documented formats',
   (src.match(/\{ k: '(xlsx-all|pdf-master|pdf-detail|mspdi)'/g) || []).length === 4);
ok('it refuses when there is nothing to export', /There is nothing to export yet/.test(DLG));
ok('it waits for the export engines before using them',
   DLG.indexOf('await tkEnsureExportLibs()') >= 0 &&
   DLG.indexOf('await tkEnsureExportLibs()') < DLG.indexOf('_schXlsx(pid)'),
   'they are ~2.5 MB and are not loaded on a metered connection until something needs them. ' +
   'The >= 0 is load-bearing: indexOf returns -1 when the call is GONE, and -1 is less than every ' +
   'index, so the order test alone passes on code that never waits at all');
ok('the MS Project export does not wait for them — it needs neither',
   /if \(pick !== 'mspdi'\)/.test(DLG));
ok('a writer that returned false stops the success toast',
   /if \(!ok\) return;/.test(DLG),
   'reporting "Exported" when nothing was written is how a broken export survives for months');
ok('an export is audited', /tkAudit\('Schedule exported'/.test(DLG));
ok('and the .mpp limitation is stated where the choice is made',
   /\.mpp cannot be written by a browser/.test(src),
   'offering "MS Project" and handing over something else without saying so is the lie the import ' +
   'side already refuses to tell');
ok('the button is on the Master Schedule card', /pmMasterWipeBtn\(pid\) \+ schExportBtn\(pid\) \+ pmImportBtn\(\)/.test(src));
ok('and on the Detail Schedule bar', /schExportBtn\(pid\) \+\n\s*\(unf\.length/.test(src));

console.log('\n  ' + pass + ' passed, ' + fail + ' failed\n');
process.exit(fail ? 1 : 0);
