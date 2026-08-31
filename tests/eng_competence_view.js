/* The competence register's screen, tested against the code that ships.
 *
 * The rules for this register shipped WITHOUT a screen: no form, no tab, no renderer. Nobody could
 * record a single authorisation, so the competence checks could never fire on real work and the
 * "checked by" on every drawing stayed a name with nothing behind it. The register existed in
 * app.py, in its tests, and nowhere a person could reach.
 *
 * Two things are asserted here, and the second matters more than the feature.
 *
 * The GAP FINDER has to separate two findings that need different actions: a checker with no
 * record at all, and a checker authorised for a different discipline. Folding them together would
 * tell a design manager to "sort out competence" without saying whether the record is too narrow
 * or the wrong person checked the drawing.
 *
 * And the screen must never present a gap as a blocker. The server deliberately does NOT refuse an
 * issue over a missing competence record — records lag reality in a small office, and stopping
 * real work over an administrative gap is how a register gets routed around. A screen that shouts
 * would undo that decision without changing a line of the rule.
 *
 *   node tests/eng_competence_view.js
 */
const fs = require('fs');
const path = require('path');

const src = fs.readFileSync(path.join(__dirname, '..', 'templates', 'index.html'), 'utf8');
const START = '/* ── ENG COMPETENCE ──', END = '/* ── END ENG COMPETENCE ── */';
const i = src.indexOf(START), j = src.indexOf(END);
if (i < 0 || j < 0 || j <= i) {
  console.error('Could not find the competence block in templates/index.html.\n' +
    'If the markers were renamed, update START/END here — do NOT delete this test.');
  process.exit(2);
}

/* Declared INSIDE the harness scope, not out here: the setters assign to them from within the
   evaluated block, and reading one before any setter ran threw "LEAD is not defined" from the
   first test that rendered a row — which read as a bug in the screen. */
const PRELUDE = `
  let COMPS = [], REVS = [], DELS = [], LEAD = true, ME = 'Dept Manager';
  function _engProj(){ return { id: 'p1', code: 'PIL26', designManager: 'Dept Manager' }; }
  function _engScopeFor(c){ return c === 'eng_competence' ? COMPS
                          : c === 'eng_revisions' ? REVS
                          : c === 'eng_deliverables' ? DELS : []; }
  function _engIsLead(){ return LEAD; }
  function _engIsMe(n){ return String(n || '').trim().toLowerCase() === ME.toLowerCase(); }
  function _engToday(){ return '2026-08-31'; }
  function _engEsc(s){ return String(s == null ? '' : s).replace(/[<>]/g, ''); }
  function _engFmt(d){ return String(d || '—'); }
  function _engGuide(k,t,b){ return '<section>' + t + b + '</section>'; }
  function _engBadge(t){ return '<span class="badge">' + t + '</span>'; }
  function _hrKpi(l,v){ return '<kpi data-label="' + l + '">' + v + '</kpi>'; }
  function _hrKpiRow(l){ return '<kpirow>' + l.join('') + '</kpirow>'; }
  function _engCard(title, addColl, addLabel, inner){ return '<card data-add="' + (addColl||'') + '">' + title + inner + '</card>'; }
  function _engFiltBar(){ return ''; }
  function _engFiltApply(c, rows){ return rows; }
  function _engTable(coll, cols, rows, opts){
    return '<table data-rows="' + rows.length + '">' + rows.map(function (r) {
      return '<tr>' + cols.map(function (c) {
        return '<td>' + (c.render ? c.render(r) : (r[c.k] == null ? '—' : r[c.k])) + '</td>';
      }).join('') + '</tr>'; }).join('') + (rows.length ? '' : '<empty>' + opts.empty + '</empty>') + '</table>';
  }
  function _engFileCell(){ return ''; }
  function tkIcon(){ return ''; }
`;
const api = {};
new Function(PRELUDE + src.slice(i, j) + `
  Object.assign(this, {
    _engCompetenceGaps, engRenderCompetence,
    set: function (c, r, d) { COMPS = c || []; REVS = r || []; DELS = d || []; },
    setLead: function (v) { LEAD = v; }, setMe: function (v) { ME = v; }
  });
`).call(api);
const { _engCompetenceGaps, engRenderCompetence, set, setLead, setMe } = api;

let pass = 0, fail = 0;
function t(name, fn) {
  try { fn(); console.log('  ok    ' + name); pass++; }
  catch (e) { console.log('  FAIL  ' + name + '\n        ' + e.message); fail++; }
}
const eq = (a, b, m) => { if (a !== b) throw new Error((m || '') + ' expected ' + JSON.stringify(b) + ', got ' + JSON.stringify(a)); };
const ok = (c, m) => { if (!c) throw new Error(m || 'expected true'); };

const C = (person, scope, o) => Object.assign({ id: 'c-' + person + scope, person: person, scope: scope, status: 'Authorised', basis: 'years of it' }, o || {});
const D = (id, disc) => ({ id: id, docNo: id, discipline: disc });
const R = (delId, who) => ({ deliverableId: delId, rev: 'C01', checkedBy: who });

console.log('\nthe gap finder separates two different problems');
t('a checker with no record at all', () => {
  const g = _engCompetenceGaps([R('d1', 'Nobody Recorded')], [D('d1', 'Electrical')], []);
  eq(g.none.length, 1);
  eq(g.none[0].person, 'Nobody Recorded');
  eq(g.wrong.length, 0);
});
t('a checker authorised for ANOTHER discipline is a different finding', () => {
  const g = _engCompetenceGaps([R('d1', 'Mechanical Mike')], [D('d1', 'Electrical')],
    [C('Mechanical Mike', 'Mechanical')]);
  eq(g.none.length, 0, 'they do have a record — it is the wrong one');
  eq(g.wrong.length, 1);
  eq(g.wrong[0].held.join(), 'Mechanical');
});
t('a properly authorised checker raises nothing', () => {
  const g = _engCompetenceGaps([R('d1', 'Electrical Ellen')], [D('d1', 'Electrical')],
    [C('Electrical Ellen', 'Electrical')]);
  eq(g.none.length + g.wrong.length, 0);
});
t('a PROPOSED record does not count as an authorisation', () => {
  /* Somebody proposed for a discipline has not been granted it. Counting a proposal would let the
     gap close itself by being asked about. */
  const g = _engCompetenceGaps([R('d1', 'Pending Pete')], [D('d1', 'Electrical')],
    [C('Pending Pete', 'Electrical', { status: 'Proposed' })]);
  eq(g.none.length, 1);
});
t('a WITHDRAWN authorisation stops covering', () => {
  const g = _engCompetenceGaps([R('d1', 'Was Ok')], [D('d1', 'Electrical')],
    [C('Was Ok', 'Electrical', { status: 'Withdrawn' })]);
  eq(g.none.length, 1);
});
t('somebody authorised for several disciplines is covered on each', () => {
  const comps = [C('Multi Mary', 'Electrical'), C('Multi Mary', 'Mechanical')];
  const g = _engCompetenceGaps(
    [R('d1', 'Multi Mary'), R('d2', 'Multi Mary')],
    [D('d1', 'Electrical'), D('d2', 'Mechanical')], comps);
  eq(g.none.length + g.wrong.length, 0);
});
t('the same person on the same discipline is listed once, not once per drawing', () => {
  const g = _engCompetenceGaps(
    [R('d1', 'Busy Ben'), R('d2', 'Busy Ben'), R('d3', 'Busy Ben')],
    [D('d1', 'Electrical'), D('d2', 'Electrical'), D('d3', 'Electrical')], []);
  eq(g.none.length, 1, 'a checker who signed thirty drawings is one gap, not thirty rows');
});
t('but the same person on two disciplines is two findings', () => {
  const g = _engCompetenceGaps([R('d1', 'Busy Ben'), R('d2', 'Busy Ben')],
    [D('d1', 'Electrical'), D('d2', 'Civil')], []);
  eq(g.none.length, 2);
});
t('a revision with no checker recorded is not a competence gap', () => {
  /* That is the CHECKER rule's business — refused at issue. Reporting it here as well would put
     the same problem in two registers with two different remedies. */
  eq(_engCompetenceGaps([R('d1', '')], [D('d1', 'Electrical')], []).none.length, 0);
});
t('a revision whose deliverable is missing does not crash', () => {
  const g = _engCompetenceGaps([R('gone', 'Someone')], [], []);
  eq(g.none.length, 1);
  eq(g.none[0].discipline, '');
});

console.log('\nthe screen');
t('it renders with nothing recorded, and says what that means', () => {
  set([], [], []);
  const h = engRenderCompetence('p1');
  ok(h.length > 200, 'nothing rendered');
  ok(h.indexOf('has no second half') >= 0, 'the empty state should say why the register matters');
});
t('the gap panel appears only when there is a gap', () => {
  set([], [], []);
  ok(engRenderCompetence('p1').indexOf('does not cover') < 0, 'an empty gap panel is noise');
  set([], [R('d1', 'Nobody')], [D('d1', 'Electrical')]);
  ok(engRenderCompetence('p1').indexOf('does not cover') >= 0);
});
t('the gap panel says plainly that nothing was blocked', () => {
  /* The server does not refuse over a competence gap, on purpose. A screen that implied otherwise
     would undo that decision without changing the rule. */
  set([], [R('d1', 'Nobody')], [D('d1', 'Electrical')]);
  const h = engRenderCompetence('p1');
  ok(h.indexOf('Nothing here was blocked') >= 0, 'the non-rule has to be visible on the screen');
});
t('the counts are separate and correct', () => {
  set([C('A', 'Electrical'), C('B', 'Civil', { status: 'Proposed' }),
       C('C', 'Mechanical', { validUntil: '2020-01-01' })],
      [R('d1', 'Ghost')], [D('d1', 'Electrical')]);
  const h = engRenderCompetence('p1');
  ok(h.indexOf('<kpi data-label="Authorised">2</kpi>') >= 0, 'authorised count');
  ok(h.indexOf('<kpi data-label="Awaiting authorisation">1</kpi>') >= 0);
  ok(h.indexOf('<kpi data-label="Checkers with no record">1</kpi>') >= 0);
  ok(h.indexOf('<kpi data-label="Expired">1</kpi>') >= 0);
});
t('a lead is offered the authorise button', () => {
  setLead(true); setMe('Dept Manager');
  set([C('Someone Else', 'Electrical', { status: 'Proposed', authorisedBy: '' })], [], []);
  ok(engRenderCompetence('p1').indexOf('engCompetenceSign') >= 0);
});
t('nobody is offered it for THEIR OWN record', () => {
  /* Granted, never claimed — and the screen must not even offer the click. */
  setLead(true); setMe('Self Signer');
  set([C('Self Signer', 'Electrical', { status: 'Proposed', authorisedBy: '' })], [], []);
  const h = engRenderCompetence('p1');
  ok(h.indexOf('engCompetenceSign') < 0, 'the button was offered on the caller’s own record');
  ok(h.indexOf('not yours to grant') >= 0);
});
t('a non-lead is not offered it at all', () => {
  setLead(false); setMe('Dept Manager');
  set([C('Someone Else', 'Electrical', { status: 'Proposed', authorisedBy: '' })], [], []);
  ok(engRenderCompetence('p1').indexOf('engCompetenceSign') < 0);
  setLead(true);
});
t('an authorised row shows who granted it instead of a button', () => {
  set([C('Granted Gina', 'Electrical', { authorisedBy: 'Dept Manager', authorisedOn: '2026-08-01' })], [], []);
  const h = engRenderCompetence('p1');
  ok(h.indexOf('Dept Manager') >= 0);
  ok(h.indexOf('engCompetenceSign') < 0, 'an already-granted record must not offer to grant again');
});

console.log('\n' + pass + ' passed, ' + fail + ' failed');
process.exit(fail ? 1 : 0);
