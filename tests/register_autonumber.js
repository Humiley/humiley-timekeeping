/* The next record continues the register's own numbering, however far it runs.
 *
 * Two faults, both reported from a live ITP register numbered by hand as 1, 2, 3 … 100:
 *
 *  1. THE COUNTER WRAPPED AT 1000. The number was formatted with `('00' + seq).slice(-3)`, which is
 *     correct to 999 and then truncates: 1000 becomes "000", 1001 becomes "001", 12345 becomes
 *     "345". The thousandth record did not merely look wrong — it was handed a number an earlier
 *     record already had, silently, and nothing downstream enforces uniqueness. Three digits is a
 *     minimum WIDTH, not a maximum value.
 *
 *  2. THE FORMAT CHANGED MID-REGISTER. The app's own convention is PREFIX-TAG-NNN, so pressing Add
 *     on a register reading 87, 88, 90, 92, 95, 99, 100 produced MEG-ITP-101 — which is not the
 *     next number in that sequence by any reading a person would give it. A register that is
 *     already numbered states its convention; the code should read it, not overrule it.
 *
 * Held here for EVERY register that auto-numbers — change requests, risks, issues, RFIs, quality
 * records, packages, ITPs and payment certificates all share `_pmAutoNumber`.
 *
 *   node tests/register_autonumber.js
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

const PID = 'P1';
const build = rows => new Function('ROWS',
  'const _HR = { pm_quality_itp: ROWS, pm_projects: [{ id: "P1", name: "Mega Lifesciences" }] };\n' +
  'const _pmScopeFor = (c, pid) => (_HR[c] || []).filter(x => x.projectId === pid);\n' +
  'function _pmProj(id){ return _HR.pm_projects.find(p => p.id === id); }\n' +
  'function _pmPid(){ return "P1"; }\n' +
  take('const _PM_NUMSPEC', '_PM_NUMSPEC') +
  take('function _pmPrefix3(', '_pmPrefix3') +
  take('function _seqPad3(', '_seqPad3') +
  take('function _pmNumStyle(', '_pmNumStyle') +
  take('function _pmNextSeq(', '_pmNextSeq') +
  take('function _pmAutoNumber(', '_pmAutoNumber') +
  '\nreturn { _pmAutoNumber: _pmAutoNumber, _seqPad3: _seqPad3, _pmNextSeq: _pmNextSeq };')(rows);

/* Add a record to a register holding `existing`, and report the number it is given. */
const nextFor = (existing) => {
  const rows = existing.map((n, i) => ({ id: 'r' + i, projectId: PID, itpNo: String(n) }));
  const API = build(rows);
  const data = { projectId: PID, title: 'New plan' };
  API._pmAutoNumber('pm_quality_itp', data);
  return data.itpNo;
};

// ══ the width ══════════════════════════════════════════════════════════════════════════════════
console.log('\nThree digits is a minimum width, not a ceiling\n');
{
  const API = build([]);
  const pad = API._seqPad3;
  ok('small numbers are still padded to three', pad(1) === '001' && pad(9) === '009' && pad(99) === '099',
     [pad(1), pad(9), pad(99)].join(' '));
  ok('three digits pass through', pad(100) === '100' && pad(999) === '999');
  ok('and FOUR digits are not truncated to three',
     pad(1000) === '1000' && pad(1001) === '1001',
     'got ' + pad(1000) + ' and ' + pad(1001) + " — the old ('00' + n).slice(-3) turned 1000 into " +
     '"000" and handed the thousandth record a number an earlier one already had');
  ok('nor are five, or six',
     pad(12345) === '12345' && pad(100000) === '100000',
     'got ' + pad(12345) + ' and ' + pad(100000));
}

// ══ continuing a register numbered by hand ═════════════════════════════════════════════════════
console.log('\nA register numbered 1, 2, 3 carries on 4, 5, 6\n');
{
  ok('after 1, 2, 3 the next is 4', nextFor([1, 2, 3]) === '4', 'got ' + nextFor([1, 2, 3]));
  ok('after 9 the next is 10, not 010 and not MEG-ITP-010',
     nextFor([1, 9]) === '10', 'got ' + nextFor([1, 9]));
  ok('the reported register — 87, 88, 90, 92, 95, 99, 100 — goes on to 101',
     nextFor([87, 88, 90, 92, 95, 99, 100]) === '101',
     'got ' + nextFor([87, 88, 90, 92, 95, 99, 100]) +
     ' — it used to become MEG-ITP-101, a different format dropped into the middle of a plain ' +
     '1..100 sequence');
  ok('it continues past 999 without wrapping',
     nextFor([998, 999]) === '1000', 'got ' + nextFor([998, 999]));
  ok('and keeps going into six figures',
     nextFor([99999]) === '100000' && nextFor([100000]) === '100001',
     'got ' + nextFor([99999]) + ' and ' + nextFor([100000]));

  ok('it follows the HIGHEST number, not how many records there are',
     nextFor([1, 2, 7]) === '8',
     'got ' + nextFor([1, 2, 7]) + ' — a register with gaps must not reissue a number that has ' +
     'already been used on an issued plan');
  ok('zero padding already in use is kept',
     nextFor(['001', '002']) === '003', 'got ' + nextFor(['001', '002']));
  /* The number must be WIDER than the padding in use, or a truncating slice and a correct one
     return the same string and the assertion proves nothing. '001' sets a padding of three; the
     next number after 999 needs four digits. A first version used ['998','999'], which sets NO
     padding at all (neither starts 0x) — so it never entered the padded branch, and a mutation
     that truncated it survived. */
  ok('and padding widens rather than truncating when the count outgrows it',
     nextFor(['001', '999']) === '1000',
     'got ' + nextFor(['001', '999']) + ' — a padding of three must not clip 1000 to "000"');
}

// ══ the app's own format is untouched where it is the convention ═══════════════════════════════
console.log("\nA register the app numbered keeps the app's format\n");
{
  ok('an empty register starts at MEG-ITP-001',
     nextFor([]) === 'MEG-ITP-001', 'got ' + nextFor([]));
  const rows = ['MEG-ITP-001', 'MEG-ITP-002'].map((n, i) => ({ id: 'r' + i, projectId: PID, itpNo: n }));
  const API = build(rows);
  const d = { projectId: PID }; API._pmAutoNumber('pm_quality_itp', d);
  ok('and carries on MEG-ITP-003', d.itpNo === 'MEG-ITP-003', 'got ' + d.itpNo);

  const big = [{ id: 'a', projectId: PID, itpNo: 'MEG-ITP-999' }];
  const A2 = build(big); const d2 = { projectId: PID }; A2._pmAutoNumber('pm_quality_itp', d2);
  ok('past 999 it becomes MEG-ITP-1000, not MEG-ITP-000',
     d2.itpNo === 'MEG-ITP-1000', 'got ' + d2.itpNo);

  /* A register carrying both shapes has no single convention to continue, so the app's own format
     is the honest answer — inventing a plain number there would be a guess. */
  const mixed = [{ id: 'a', projectId: PID, itpNo: '5' }, { id: 'b', projectId: PID, itpNo: 'MEG-ITP-006' }];
  const A3 = build(mixed); const d3 = { projectId: PID }; A3._pmAutoNumber('pm_quality_itp', d3);
  ok('a mixed register falls back to the app format', d3.itpNo === 'MEG-ITP-007', 'got ' + d3.itpNo);
}

// ══ what must not change ═══════════════════════════════════════════════════════════════════════
console.log('\nWhat the register already holds is never touched\n');
{
  const rows = [{ id: 'a', projectId: PID, itpNo: '99' }];
  const API = build(rows);
  const before = JSON.stringify(rows);
  const d = { projectId: PID }; API._pmAutoNumber('pm_quality_itp', d);
  ok('adding a record does not renumber the existing ones', JSON.stringify(rows) === before,
     'those numbers are on issued, approved plans and on the contractor\'s paperwork');

  const typed = { projectId: PID, itpNo: '250' };
  API._pmAutoNumber('pm_quality_itp', typed);
  ok('a number typed by hand is left exactly as typed', typed.itpNo === '250', 'got ' + typed.itpNo);

  const dupes = [1, 2, 3].map((n, i) => ({ id: 'r' + i, projectId: PID, itpNo: String(n) }))
    .concat([{ id: 'r9', projectId: PID, itpNo: '4' }]);
  const A2 = build(dupes); const d2 = { projectId: PID }; A2._pmAutoNumber('pm_quality_itp', d2);
  ok('the number handed out is not one already in the register',
     !dupes.some(r => r.itpNo === d2.itpNo), 'got ' + d2.itpNo);

  /* A record with no projectId of its own is numbered against the project currently open — that is
     deliberate, and it is how Add works from inside a project workspace. What must not happen is a
     number invented when there is no project at all to number it against. */
  const noProj = new Function('ROWS',
    'const _HR = { pm_quality_itp: ROWS, pm_projects: [] };\n' +
    'const _pmScopeFor = (c, pid) => (_HR[c] || []).filter(x => x.projectId === pid);\n' +
    'function _pmProj(){ return null; }\n' +
    'function _pmPid(){ return ""; }\n' +
    take('const _PM_NUMSPEC', '_PM_NUMSPEC') + take('function _pmPrefix3(', '_pmPrefix3') +
    take('function _seqPad3(', '_seqPad3') + take('function _pmNumStyle(', '_pmNumStyle') +
    take('function _pmNextSeq(', '_pmNextSeq') + take('function _pmAutoNumber(', '_pmAutoNumber') +
    '\nreturn { _pmAutoNumber: _pmAutoNumber };')([]);
  const orphan = {};
  noProj._pmAutoNumber('pm_quality_itp', orphan);
  ok('with no project open at all, no number is invented', !orphan.itpNo,
     'got ' + orphan.itpNo + ' — a number means "the Nth plan on THIS project", and there is no ' +
     'project here for it to be the Nth of');

  const inherited = { title: 'Added from inside the workspace' };
  build([{ id: 'a', projectId: PID, itpNo: '7' }])._pmAutoNumber('pm_quality_itp', inherited);
  ok('but inside a project it is numbered against that project', inherited.itpNo === '8',
     'got ' + inherited.itpNo);
}

// ══ the same wrap lived in three other places ══════════════════════════════════════════════════
/* `('00' + seq).slice(-3)` was copied four times. Fixing only the one that was reported would leave
   three known landmines — including a PAYMENT REQUEST number, where a duplicate is materially worse
   than a duplicate inspection plan. All four now share `_seqPad3`. */
console.log('\nThe other three registers that carried the same wrap\n');
{
  ok('the PMC registers use the shared pad',
     /_pmPrefix3\(pid\) \+ '-' \+ tag \+ '-' \+ _seqPad3\(n\)/.test(src));
  ok('Engineering uses it — DI, DR, CMT, ECN, TQ, TRN, HLD, DEV, RSK',
     /_engPrjCode\(_engProj\(pid\)\)\.slice\(0, 6\) \+ '-' \+ sp\.tag \+ '-' \+ _seqPad3\(seq\)/.test(src));
  ok('so does the drawing document number',
     /\.replace\(\/000\$\/, _seqPad3\(seq\)\)/.test(src));
  ok('and so does the payment request number',
     /return 'PR-' \+ y \+ '-' \+ _seqPad3\(n\);/.test(src),
     'PR-2026-000 would collide with a payment request already raised, and that counter does not ' +
     'reset per year — the scan reads every payment regardless of year');
  ok('no truncating pad is left anywhere',
     !/\('00' \+ (?:seq|n)\)\.slice\(-(?:3|pad)\)/.test(src.replace(/\/\*[\s\S]*?\*\//g, '').replace(/\/\/[^\n]*/g, '')),
     'a surviving copy would fail exactly once, at the thousandth record, and silently');
}

/* One property nobody should have to infer from the code: uniqueness is NOT enforced. Two people
   pressing Add in the same second both read the same highest number and both receive it. Stating it
   here means the next person to look does not mistake the padding fix for a guarantee. */
console.log('\nWhat this does NOT promise\n');
{
  const rows = [{ id: 'a', projectId: PID, itpNo: '5' }];
  const A = build(rows), B = build(rows);
  const d1 = { projectId: PID }, d2 = { projectId: PID };
  A._pmAutoNumber('pm_quality_itp', d1);
  B._pmAutoNumber('pm_quality_itp', d2);
  ok('two people adding at the same moment DO both get the same number',
     d1.itpNo === d2.itpNo && d1.itpNo === '6',
     'got ' + d1.itpNo + ' and ' + d2.itpNo + '. This is a statement of the current behaviour, not ' +
     'an endorsement: closing it needs a counter the server owns, not a better guess in the ' +
     'browser. If this assertion ever fails because uniqueness was added, delete it and say so.');
}

console.log('\n  ' + pass + ' passed, ' + fail + ' failed\n');
process.exit(fail ? 1 : 0);
