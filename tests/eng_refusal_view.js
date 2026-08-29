/* The refusal-log screen, tested against the code that actually ships.
 *
 * Two different things are checked here, and the second is the reason this file exists.
 *
 * The grouping is arithmetic and can be got wrong quietly: "times" must count refusals while
 * "people" and "records" count distinct ones, because one engineer retrying the same drawing four
 * times is a person stuck, not a rule firing widely — and a screen that reports those as the same
 * number sends a design manager to change a rule that is working.
 *
 * The render is checked because a render that THROWS does not report an error here: it leaves an
 * empty panel. _engGateReadiness shipped that way and the Stages & Gates tab was blank in
 * production for weeks with nobody reporting it, because a blank panel looks like "no data". So
 * engRenderRefusals is actually called, with every helper stubbed, and the HTML it produced is
 * inspected. It is the closest thing to opening the tab that does not need a browser.
 *
 *   node tests/eng_refusal_view.js
 */
const fs = require('fs');
const path = require('path');

const src = fs.readFileSync(path.join(__dirname, '..', 'templates', 'index.html'), 'utf8');
const START = '/* ── ENG REFUSAL LOG ──', END = '/* ── END ENG REFUSAL LOG ── */';
const i = src.indexOf(START), j = src.indexOf(END);
if (i < 0 || j < 0 || j <= i) {
  console.error('Could not find the refusal-log block in templates/index.html.\n' +
    'If the markers were renamed, update START/END here — do NOT delete this test.');
  process.exit(2);
}

/* Everything the block leans on, stubbed so the assertions are about THIS code. The stubs pass
   their content through rather than returning a placeholder, so the HTML that comes out still
   contains the real numbers and the real strings. */
let LAST_HTML = '';
const PRELUDE = `
  let ROWS = [], PROJ = { id: 'p1', code: 'PIL26', name: 'Pilot' };
  function _engProj(){ return PROJ; }
  function _engScopeFor(coll, pid){ return coll === 'eng_refusals' ? ROWS : []; }
  function _engSet(h){ SINK(h); }
  function _engEsc(s){ return String(s == null ? '' : s); }
  function _engFmt(d){ return String(d || '—'); }
  function _engToday(){ return '2026-08-29'; }
  function _engDaysAgo(d){ if(!d) return null; var t=new Date(String(d).slice(0,10)), n=new Date('2026-08-29');
                           return isNaN(t) ? null : Math.round((n-t)/86400000); }
  function _engGuide(k,t,b){ return '<section data-guide="'+k+'">'+t+b+'</section>'; }
  function _engBadge(t,h){ return '<span class="badge">'+t+'</span>'; }
  function _hrKpi(l,v,h){ return '<kpi data-label="'+l+'">'+v+'</kpi>'; }
  function _hrKpiRow(l){ return '<kpirow>'+l.join('')+'</kpirow>'; }
  function _engCard(title, addColl, addLabel, inner, extra){
    if (addColl) throw new Error('the refusal log is server-written — it must never offer an Add button');
    return '<card data-title="'+title+'">'+(extra||'')+inner+'</card>';
  }
  function _engFiltBar(coll, rows, specs){ return '<filters count="'+specs.length+'"></filters>'; }
  function _engFiltApply(coll, rows, specs){ return rows; }
  function _engTable(coll, cols, rows, opts){
    if (!opts || !opts.noActions) throw new Error('a read-only log must not render edit/delete actions');
    return '<table data-coll="'+coll+'" data-cols="'+cols.length+'" data-rows="'+rows.length+'">' +
      rows.map(function(r){ return '<tr>' + cols.map(function(c){
        return '<td>' + (c.render ? c.render(r) : (r[c.k] == null ? '—' : r[c.k])) + '</td>'; }).join('') + '</tr>'; }).join('') +
      '</table>';
  }
  function tkIcon(){ return ''; }
`;

const api = {};
new Function('SINK', PRELUDE + src.slice(i, j) + `
  Object.assign(this, {
    _engRefusalGroups: _engRefusalGroups,
    engRenderRefusals: engRenderRefusals,
    setRows: function (r) { ROWS = r; }
  });
`).call(api, h => { LAST_HTML = h; });
const { _engRefusalGroups, engRenderRefusals, setRows } = api;

let pass = 0, fail = 0;
function t(name, fn) {
  try { fn(); console.log('  ok    ' + name); pass++; }
  catch (e) { console.log('  FAIL  ' + name + '\n        ' + e.message); fail++; }
}
const eq = (a, b, m) => { if (a !== b) throw new Error((m || '') + ' expected ' + JSON.stringify(b) + ', got ' + JSON.stringify(a)); };
const inHtml = (s, m) => { if (LAST_HTML.indexOf(s) < 0) throw new Error((m || 'expected in the output') + ': ' + JSON.stringify(s)); };
const notInHtml = (s, m) => { if (LAST_HTML.indexOf(s) >= 0) throw new Error((m || 'must NOT be in the output') + ': ' + JSON.stringify(s)); };

const R = (o) => Object.assign({
  projectId: 'p1', coll: 'eng_revisions', attempted: 'Issued',
  rule: 'Record who checked this document before issuing it outside the office',
  message: 'Record who checked this document before issuing it outside the office. Nobody is named.',
  recordId: 'r1', recordRef: 'C01', who: 'Alice Engineer',
  at: '2026-08-28 16:40:00', source: 'sign'
}, o);

const render = rows => { setRows(rows); LAST_HTML = ''; engRenderRefusals('p1'); };

console.log('\ngrouping');
t('one rule fired three times is one line counting three', () => {
  const g = _engRefusalGroups([R(), R({ at: '2026-08-27 09:00:00' }), R({ at: '2026-08-26 09:00:00' })]);
  eq(g.length, 1);
  eq(g[0].n, 3);
});
t('the same rule on a different register stays a separate line', () => {
  /* The server keys a refusal on (register, attempted, rule). Merging them would total a gate
     refusal with a drawing refusal under one heading nobody could act on. */
  const g = _engRefusalGroups([R(), R({ coll: 'eng_stages', attempted: 'Passed' })]);
  eq(g.length, 2);
});
t('people and records are DISTINCT counts, times is not', () => {
  /* One engineer retrying the same drawing four times. If all three columns read 4 a manager goes
     looking for a rule that fires widely; the truth is one person stuck on one document. */
  const g = _engRefusalGroups([R(), R(), R(), R()]);
  eq(g[0].n, 4, 'times');
  eq(Object.keys(g[0].who).length, 1, 'people');
  eq(Object.keys(g[0].recs).length, 1, 'records');
});
t('the most-fired rule sorts first', () => {
  const g = _engRefusalGroups([
    R({ coll: 'eng_stages', attempted: 'Passed', rule: 'Rare' }),
    R(), R(), R()]);
  eq(g[0].n, 3);
  eq(g[1].rule, 'Rare');
});
t('the latest time wins as "last"', () => {
  const g = _engRefusalGroups([R({ at: '2026-08-01 10:00:00' }), R({ at: '2026-08-20 10:00:00' })]);
  eq(g[0].last, '2026-08-20 10:00:00');
});

console.log('\nthe screen renders (a render that throws leaves a blank panel, not an error)');
t('an empty log renders and says what zero can mean', () => {
  render([]);
  if (!LAST_HTML) throw new Error('nothing was rendered at all');
  inHtml('Nothing has been refused', 'the empty state');
  inHtml('genuinely rare', 'zero is ambiguous and the screen has to say so');
});
t('a populated log renders both tables', () => {
  render([R(), R({ coll: 'eng_stages', attempted: 'Passed', rule: 'Close the open HOLDs', recordId: 'g1', recordRef: 'H-301', who: 'Bob Lead' })]);
  inHtml('Refusals by rule', 'the by-rule table');
  inHtml('Every refusal, newest first', 'the chronological table');
  inHtml('Alice Engineer', 'the person who was stopped');
  inHtml('H-301', 'the record that was stopped');
});
t('the register name is shown in words, not as a table name', () => {
  render([R({ coll: 'eng_revisions' })]);
  inHtml('Drawing issue');
  notInHtml('eng_revisions', 'a design manager should never be shown the collection name');
});
t('advisory notes are counted and listed apart from refusals', () => {
  /* ENG-PILOT.md is explicit that these are not refusals: nothing was blocked, a gap was recorded.
     Counting them together would inflate the refusal count with entries that stopped nobody. */
  render([R(), R({ source: 'advisory', message: 'Checked by Mechanical Mike, authorised for Mechanical' })]);
  inHtml('<kpi data-label="Refusals recorded">1</kpi>', 'the advisory row must not be counted as a refusal');
  inHtml('<kpi data-label="Advisory notes">1</kpi>');
  inHtml('Advisory notes — recorded, nothing blocked');
});
t('with no advisory rows that table is absent entirely', () => {
  render([R()]);
  notInHtml('nothing blocked', 'an empty advisory table is noise');
});
t('the 14-day window counts recent refusals only', () => {
  render([R({ at: '2026-08-28 10:00:00' }), R({ at: '2026-01-01 10:00:00' })]);
  inHtml('<kpi data-label="Refusals recorded">2</kpi>');
  inHtml('<kpi data-label="In the last 14 days">1</kpi>');
});
t('the screen does not invent an outcome column', () => {
  /* The log cannot know what happened after a refusal. A column for it would be a guess wearing
     the same styling as the facts beside it. */
  render([R()]);
  notInHtml('Outcome');
});

console.log('\n' + pass + ' passed, ' + fail + ' failed');
process.exit(fail ? 1 : 0);
