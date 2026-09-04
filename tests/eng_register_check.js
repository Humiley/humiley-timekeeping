/* The drawing register's self-check, tested against the code that actually ships.
 *
 * The checker lives inside templates/index.html (no build step, no modules), so this extracts the
 * block between two markers and evaluates it with the code tables it depends on stubbed. Extracting
 * rather than copying is the point: a copy would keep passing after the real code drifted.
 *
 *   node tests/eng_register_check.js
 */
const fs = require('fs');
const path = require('path');

const src = fs.readFileSync(path.join(__dirname, '..', 'templates', 'index.html'), 'utf8');
const START = '/* ── ENG REGISTER CHECK ──', END = '/* ── END ENG REGISTER CHECK ── */';
const i = src.indexOf(START), j = src.indexOf(END);
if (i < 0 || j < 0 || j <= i) {
  console.error('Could not find the register-check block in templates/index.html.\n' +
    'If the markers were renamed, update START/END here — do NOT delete this test.');
  process.exit(2);
}

const PRELUDE = `
  const DISC = { Structural: 'ST', Electrical: 'EL', Mechanical: 'ME', Civil: 'CI' };
  const TYPE = { Drawing: 'DWG', 'P&ID': 'PID', Calculation: 'CAL' };
  function _engDiscCode(d){ return DISC[d] || ''; }
  function _engTypeCode(t){ return TYPE[t] || ''; }
  function _engNumFmt(p){ return String((p && p.docNumFormat) || '{PRJ}-{DISC}-{TYPE}-{NNN}'); }
  function _engPrjCode(p){ return String((p && (p.code || p.name)) || 'PRJ').replace(/[^A-Za-z0-9]/g,'').slice(0,10).toUpperCase() || 'PRJ'; }
`;
const api = {};
new Function(PRELUDE + src.slice(i, j) + `
  Object.assign(this, { _engCheckRegister, _ENG_CHK_SEV });
`).call(api);
const { _engCheckRegister } = api;

let pass = 0, fail = 0;
function t(name, fn) {
  try { fn(); console.log('  ok    ' + name); pass++; }
  catch (e) { console.log('  FAIL  ' + name + '\n        ' + e.message); fail++; }
}
const eq = (a, b, m) => { if (a !== b) throw new Error((m || '') + ' expected ' + JSON.stringify(b) + ', got ' + JSON.stringify(a)); };
const has = (found, code, m) => { if (!found.some(f => f.code === code)) throw new Error((m || '') + ' expected a ' + code + ' finding, got [' + found.map(f => f.code).join(', ') + ']'); };
const hasnt = (found, code, m) => { if (found.some(f => f.code === code)) throw new Error((m || '') + ' did NOT expect ' + code); };

const PRJ = { code: 'TST26', revScheme: 'ISO 19650 (P01 / C01)' };
const D = (o) => Object.assign({ id: 'd1', docNo: 'TST26-ST-DWG-001', title: 'A drawing',
                                 discipline: 'Structural', docType: 'Drawing' }, o);
const R = (o) => Object.assign({ id: 'r1', deliverableId: 'd1', rev: 'P01',
                                 issueStatus: 'IFR', status: 'Draft' }, o);

console.log('\nnumbering');
t('a conforming register is silent about numbers', () => {
  const f = _engCheckRegister(PRJ, [D()], [R()]);
  ['NO-NUMBER', 'SHAPE', 'PRJ-CODE', 'DISC-CODE', 'TYPE-CODE', 'DUPLICATE'].forEach(c => hasnt(f, c));
});
t('a missing document number is an error', () => {
  has(_engCheckRegister(PRJ, [D({ docNo: '' })], []), 'NO-NUMBER');
});
t('two deliverables with one number is an error', () => {
  const f = _engCheckRegister(PRJ, [D(), D({ id: 'd2', title: 'Another' })], []);
  has(f, 'DUPLICATE');
  eq(f.filter(x => x.code === 'DUPLICATE').length, 1, 'one finding per duplicated number:');
});
t('duplicate detection ignores case', () => {
  has(_engCheckRegister(PRJ, [D(), D({ id: 'd2', docNo: 'tst26-st-dwg-001' })], []), 'DUPLICATE');
});
t('the wrong number of parts is caught', () => {
  has(_engCheckRegister(PRJ, [D({ docNo: 'TST26-ST-001' })], []), 'SHAPE');
});
t('a discipline that is not in the number is caught', () => {
  has(_engCheckRegister(PRJ, [D({ discipline: 'Electrical' })], []), 'DISC-CODE');
});
t('a type that is not in the number is caught', () => {
  has(_engCheckRegister(PRJ, [D({ docType: 'P&ID' })], []), 'TYPE-CODE');
});
t("a client's own prefix warns rather than errors", () => {
  const f = _engCheckRegister(PRJ, [D({ docNo: 'ACME-ST-DWG-001' })], []);
  has(f, 'PRJ-CODE');
  eq(f.filter(x => x.code === 'PRJ-CODE')[0].sev, 'warn', 'client drawings are normal:');
});

console.log('\nrevisions');
t('a deliverable with no revision is information, not an error', () => {
  const f = _engCheckRegister(PRJ, [D()], []);
  has(f, 'NO-REV');
  eq(f.filter(x => x.code === 'NO-REV')[0].sev, 'info');
});
t('the same revision code twice on one drawing is an error', () => {
  has(_engCheckRegister(PRJ, [D()], [R(), R({ id: 'r2' })]), 'REV-DUPLICATE');
});
t('IFC on a preliminary code is an error', () => {
  const f = _engCheckRegister(PRJ, [D()], [R({ rev: 'P02', issueStatus: 'IFC' })]);
  has(f, 'REV-PRELIM-EXTERNAL');
  eq(f.filter(x => x.code === 'REV-PRELIM-EXTERNAL')[0].sev, 'error');
});
t('IFC on a contractual code is clean', () => {
  hasnt(_engCheckRegister(PRJ, [D()], [R({ rev: 'C01', issueStatus: 'IFC' })]), 'REV-PRELIM-EXTERNAL');
});
t('a contractual code spent on an internal issue warns', () => {
  has(_engCheckRegister(PRJ, [D()], [R({ rev: 'C01', issueStatus: 'IFR' })]), 'REV-CONTRACTUAL-INTERNAL');
});
t('a revision code off the scheme warns', () => {
  has(_engCheckRegister(PRJ, [D()], [R({ rev: 'Rev 3' })]), 'REV-SCHEME');
});
t('the numeric scheme accepts 0, 1, 2', () => {
  const p = { code: 'TST26', revScheme: 'Numeric (0, 1, 2)' };
  hasnt(_engCheckRegister(p, [D()], [R({ rev: '2' })]), 'REV-SCHEME');
});
t('two issued revisions with nothing superseded is an error', () => {
  const f = _engCheckRegister(PRJ, [D()], [
    R({ id: 'r1', rev: 'C01', issueStatus: 'IFC', status: 'Issued', issuedBy: 'A' }),
    R({ id: 'r2', rev: 'C02', issueStatus: 'IFC', status: 'Issued', issuedBy: 'A' })]);
  has(f, 'TWO-CURRENT');
});
t('superseding the earlier one clears it', () => {
  const f = _engCheckRegister(PRJ, [D()], [
    R({ id: 'r1', rev: 'C01', issueStatus: 'IFC', status: 'Superseded', issuedBy: 'A' }),
    R({ id: 'r2', rev: 'C02', issueStatus: 'IFC', status: 'Issued', issuedBy: 'A' })]);
  hasnt(f, 'TWO-CURRENT');
});
t('an issued revision with no reason for issue warns', () => {
  has(_engCheckRegister(PRJ, [D()], [R({ rev: 'C01', status: 'Issued', issuedBy: 'A' })]), 'NO-REASON');
});
t('an issued revision with no file warns', () => {
  has(_engCheckRegister(PRJ, [D()], [R({ rev: 'C01', status: 'Issued', issuedBy: 'A' })]), 'NO-FILE');
});
t('an attached file clears NO-FILE', () => {
  hasnt(_engCheckRegister(PRJ, [D()], [R({ rev: 'C01', status: 'Issued', issuedBy: 'A',
                                           reasonForIssue: 'first issue', attachment: 'x.pdf' })]), 'NO-FILE');
});
t('a revision pointing at nothing is an error', () => {
  has(_engCheckRegister(PRJ, [D()], [R({ id: 'r9', deliverableId: 'gone' })]), 'ORPHAN-REV');
});
t('a blank revision code is an error', () => {
  has(_engCheckRegister(PRJ, [D()], [R({ rev: '' })]), 'REV-BLANK');
});

console.log('\nthe whole thing');
t('an empty register produces nothing', () => {
  eq(_engCheckRegister(PRJ, [], []).length, 0);
});
t('every finding carries a severity the UI knows how to draw', () => {
  const f = _engCheckRegister(PRJ, [D({ docNo: '' }), D({ id: 'd2', docNo: 'X' })], [R({ deliverableId: 'zz' })]);
  if (!f.length) throw new Error('expected findings');
  f.forEach(x => { if (!api._ENG_CHK_SEV[x.sev]) throw new Error('unknown severity ' + x.sev); });
});
t('every finding says what to do about it', () => {
  const f = _engCheckRegister(PRJ, [D({ docNo: '' })], []);
  f.forEach(x => { if (!x.fix && x.sev === 'error') throw new Error(x.code + ' has no remedy'); });
});

console.log('\n' + pass + ' passed, ' + fail + ' failed');
process.exit(fail ? 1 : 0);
