/* The design dossier's completeness check, tested against the code that ships.
 *
 * The As-Built gate has asked for "Design dossier compiled and indexed" since this module shipped,
 * with nothing to produce one. The dossier is an INDEX — the files live in SharePoint — and its
 * whole value rests on one property: it must never claim a completeness it cannot support.
 *
 * A handover document that prints a tidy index over an open HOLD, an unapproved drawing, or a gate
 * whose carried-forward actions were never closed is worse than no document at all. Somebody signs
 * it, and the gap becomes deniable afterwards. So every check below is a way the design file can
 * be incomplete while looking finished, and each is asserted on its own — a single "is it
 * complete" test would pass while eleven of the twelve checks did nothing.
 *
 *   node tests/eng_dossier.js
 */
const fs = require('fs');
const path = require('path');

const src = fs.readFileSync(path.join(__dirname, '..', 'templates', 'index.html'), 'utf8');
const START = '/* ── ENG DOSSIER ──', END = '/* ── END ENG DOSSIER ── */';
const i = src.indexOf(START), j = src.indexOf(END);
if (i < 0 || j < 0 || j <= i) {
  console.error('Could not find the dossier block in templates/index.html.\n' +
    'If the markers were renamed, update START/END here — do NOT delete this test.');
  process.exit(2);
}

const PRELUDE = `
  function _engInScope(d){ return String(d.creditStatus || '') !== 'Cancelled'; }
  function _engStage(k){ return { label: String(k || 'Stage') }; }
`;
const api = {};
new Function(PRELUDE + src.slice(i, j) + `
  Object.assign(this, { _engDossierAudit });
`).call(api);
const { _engDossierAudit } = api;

let pass = 0, fail = 0;
function t(name, fn) {
  try { fn(); console.log('  ok    ' + name); pass++; }
  catch (e) { console.log('  FAIL  ' + name + '\n        ' + e.message); fail++; }
}
const eq = (a, b, m) => { if (a !== b) throw new Error((m || '') + ' expected ' + JSON.stringify(b) + ', got ' + JSON.stringify(a)); };
const ok = (c, m) => { if (!c) throw new Error(m || 'expected true'); };

/* A commission with nothing wrong with it: one deliverable, issued, checked, issued-by named, and
   one adopted code. Every test below starts here and breaks exactly one thing. */
const CLEAN = () => ({
  deliverables: [{ id: 'd1', docNo: 'X-001', title: 'A drawing' }],
  revisions: [{ deliverableId: 'd1', rev: 'C01', issueStatus: 'IFC', status: 'Issued',
                checkedBy: 'Carol Checker', issuedBy: 'Staff One' }],
  standards: [{ code: 'TCVN 5687', status: 'Adopted' }],
  holds: [], deviations: [], risks: [], stages: [], comments: [], tq: [],
  transmittals: [], inputs: [], reviews: [], changes: []
});
const audit = o => _engDossierAudit('p1', Object.assign(CLEAN(), o || {}));
const hasGap = (a, needle) => a.gaps.some(g => g.text.indexOf(needle) >= 0);

console.log('\nthe baseline: a clean file says so, and says it as a verdict');
t('a complete file is complete', () => {
  const a = audit();
  eq(a.blocking, 0);
  ok(a.complete);
  ok(a.verdict.indexOf('can be described as closed') >= 0, 'the verdict must be stated, not inferred');
});
t('and the verdict names the count when it is not', () => {
  const a = audit({ holds: [{ ref: 'H-1', kind: 'hold', status: 'open' }] });
  ok(!a.complete);
  ok(a.verdict.indexOf('NOT complete') >= 0);
  ok(a.verdict.indexOf('1 finding') >= 0, 'the verdict should carry the number');
});

console.log('\nthe things that stop a design file being closed');
t('a deliverable that was never issued', () => {
  const a = audit({ revisions: [] });
  ok(hasGap(a, 'no issued revision'));
  eq(a.blocking, 1);
});
t('an issued revision with no checker', () => {
  const a = audit({ revisions: [{ deliverableId: 'd1', rev: 'C01', status: 'Issued', issuedBy: 'Staff One' }] });
  ok(hasGap(a, 'no checker recorded'));
});
t('an issued revision nobody is recorded as issuing', () => {
  const a = audit({ revisions: [{ deliverableId: 'd1', rev: 'C01', status: 'Issued', checkedBy: 'Carol' }] });
  ok(hasGap(a, 'nobody recorded as issuing'));
});
t('a deliverable still on hold', () => {
  const c = CLEAN(); c.deliverables[0].hold = 'Yes';
  ok(hasGap(_engDossierAudit('p1', c), 'still marked on hold'));
});
t('an open HOLD on the design', () => {
  ok(hasGap(audit({ holds: [{ ref: 'H-1', kind: 'hold', status: 'open' }] }), 'open HOLD'));
});
t('a departure from a standard never agreed', () => {
  ok(hasGap(audit({ deviations: [{ ref: 'DEV-1' }] }), 'never agreed'));
});
t('a residual risk passed on with nobody told', () => {
  ok(hasGap(audit({ risks: [{ ref: 'R-1', status: 'Transferred' }] }), 'no record of who was told'));
});
t('a gate passed with actions that were never closed', () => {
  /* The subtlest one. "Passed with actions" is the honest form of a pass — but a document saying
     the stage is finished, over an action nobody closed, is an open commitment inside a closed
     file. */
  const a = audit({ stages: [{ stage: 'Detail', gateDecision: 'Passed with actions',
                               gateActions: 'close H-1 before IFC' }] });
  ok(hasGap(a, 'never closed out'));
});
t('and a gate whose actions WERE closed raises nothing', () => {
  const a = audit({ stages: [{ stage: 'Detail', gateDecision: 'Passed with actions',
                               gateActions: 'close H-1', gateActionsClosedOn: '2026-08-01' }] });
  eq(a.blocking, 0);
});
t('a clean pass with no actions raises nothing', () => {
  eq(audit({ stages: [{ stage: 'Detail', gateDecision: 'Passed' }] }).blocking, 0);
});

console.log('\nthings a reader must know that do not by themselves stop handover');
t('open comments are a note, not a blocker', () => {
  const a = audit({ comments: [{ commentNo: 'C-1', status: 'Open' }] });
  ok(hasGap(a, 'still open'));
  eq(a.blocking, 0, 'an open comment must not block the whole file');
  eq(a.notes, 1);
  ok(a.complete, 'and the file can still be described as closed');
});
t('unanswered technical queries are a note', () => {
  const a = audit({ tq: [{ tqNo: 'TQ-1', status: 'Open' }] });
  ok(hasGap(a, 'never answered'));
  eq(a.blocking, 0);
});
t('a transmittal that asked for a response and got none is a note', () => {
  const a = audit({ transmittals: [{ trnNo: 'T-1', responseRequired: 'Yes' }] });
  ok(hasGap(a, 'never got one'));
  eq(a.blocking, 0);
});
t('an unallocated design input is a note', () => {
  ok(hasGap(audit({ inputs: [{ ref: 'IN-1' }] }), 'never allocated'));
});
t('no adopted code at all is a note, and only counted once', () => {
  const a = audit({ standards: [] });
  ok(hasGap(a, 'no code or standard'));
  eq(a.gaps.filter(g => g.text.indexOf('no code or standard') >= 0).length, 1);
});
t('an adopted code raises nothing', () => {
  eq(audit().gaps.filter(g => g.text.indexOf('no code or standard') >= 0).length, 0);
});

console.log('\nscope and counting');
t('a cancelled deliverable is not held against the file', () => {
  const c = CLEAN();
  c.deliverables.push({ id: 'd2', docNo: 'X-002', creditStatus: 'Cancelled' });
  eq(_engDossierAudit('p1', c).blocking, 0, 'a cancelled document needs no issued revision');
});
t('a VOID revision does not count as an issue', () => {
  const a = audit({ revisions: [{ deliverableId: 'd1', rev: 'C01', issueStatus: 'VOID',
                                  status: 'Issued', checkedBy: 'C', issuedBy: 'S' }] });
  ok(hasGap(a, 'no issued revision'), 'a withdrawn drawing is not an issued one');
});
t('a draft revision does not count as an issue either', () => {
  const a = audit({ revisions: [{ deliverableId: 'd1', rev: 'P01', status: 'Draft' }] });
  ok(hasGap(a, 'no issued revision'));
});
t('each gap carries a count and up to six examples', () => {
  const many = Array.from({ length: 9 }, (_, n) => ({ ref: 'H-' + n, kind: 'hold', status: 'open' }));
  const g = audit({ holds: many }).gaps.filter(x => x.text.indexOf('open HOLD') >= 0)[0];
  eq(g.n, 9, 'the count is the whole number');
  eq(g.items.length, 6, 'the examples are capped so the page stays readable');
});
t('a gap with zero occurrences is not listed at all', () => {
  eq(audit().gaps.length, 0, 'an empty file must not print twelve "0 findings" lines');
});
t('the section index lists what the dossier contains', () => {
  const a = audit({ inputs: [{ ref: 'IN-1' }], reviews: [{ reviewNo: 'RV-1' }] });
  const by = {}; a.sections.forEach(s => { by[s.key] = s.n; });
  eq(by.mdr, 1); eq(by.inputs, 1); eq(by.reviews, 1); eq(by.standards, 1);
  eq(by.commission, 1);
});
t('an EMPTY commission is not "complete" — the silent-zero case', () => {
  /* Every other check iterates rows, so a commission with nothing recorded satisfies all of them
     and the first version of this audit declared it COMPLETE. "Nothing is wrong" and "nothing was
     looked at" are the same shape on a page unless one of them is stated.
     The first version of THIS TEST was also worthless — it asserted `!a.complete === false ||
     a.complete`, which is true for every possible input. Both are kept written down because they
     are the same mistake at two levels. */
  const a = _engDossierAudit('p1', { deliverables: [], revisions: [] });
  eq(a.complete, false, 'an empty register was described as a closed design file');
  ok(hasGap(a, 'register is empty'), 'and it says which absence it is objecting to');
  ok(hasGap(a, 'no code or standard'), 'and it still notices there is no adopted code');
});
t('one real deliverable clears the empty-register finding', () => {
  ok(!hasGap(audit(), 'register is empty'));
});

console.log('\n' + pass + ' passed, ' + fail + ' failed');
process.exit(fail ? 1 : 0);
