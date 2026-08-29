/* Is the HTML these two screens emit actually well formed?
 *
 * eng_tab_groups.js and eng_refusal_view.js check LOGIC — which pill is lit, what the counts are.
 * Both would pass just as happily on markup carrying an unclosed <div>, and an unclosed div in a
 * card-based layout swallows everything after it into the card. Nothing throws; the page just
 * looks wrong from that point down. A source-level test cannot see it and neither can a test that
 * only greps the output for strings.
 *
 * So both screens are rendered for every group and every fixture, and a tag stack is run over what
 * comes out. Element ids are checked for uniqueness too: engTab() repaints #eng-grpbar and
 * #eng-tabbar by id on every tab change, so a second node carrying either id would have it
 * repainting the wrong one — which looks like a tab bar that sometimes does not update.
 *
 * This is the nearest thing to opening the page that does not need a browser. It is not a
 * substitute for one: it says the markup nests correctly, not that the result looks right.
 *
 *   node tests/eng_markup.js
 */
const fs = require('fs');
const path = require('path');

const src = fs.readFileSync(path.join(__dirname, '..', 'templates', 'index.html'), 'utf8');

function slice(start, end) {
  const i = src.indexOf(start), j = src.indexOf(end);
  if (i < 0 || j < 0 || j <= i) { console.error('markers missing: ' + start); process.exit(2); }
  return src.slice(i, j);
}

const NAV = slice('/* ── ENG TAB NAV ──', '/* ── END ENG TAB NAV ── */');
const LOG = slice('/* ── ENG REFUSAL LOG ──', '/* ── END ENG REFUSAL LOG ── */');

let SINK = '';
const PRELUDE = `
  let LEAD = true, _engTabK = 'overview', _engCurrentProject = 'p1', ROWS = [];
  const PROJ = { id: 'p1', code: 'PIL26', name: 'Pilot commission' };
  function _engIsLead(){ return LEAD; }
  function _engProj(){ return PROJ; }
  function _engScopeFor(c){ return c === 'eng_refusals' ? ROWS : []; }
  function _engSet(h){ CAPTURE(h); }
  function _engEsc(s){ return String(s == null ? '' : s).replace(/[<>&]/g, ''); }
  function _tkEscA(s){ return String(s == null ? '' : s).replace(/"/g, '&quot;'); }
  function _engFmt(d){ return String(d || '—'); }
  function _engToday(){ return '2026-08-29'; }
  function _engDaysAgo(d){ if(!d) return null; const t=new Date(String(d).slice(0,10));
                           return isNaN(t) ? null : Math.round((new Date('2026-08-29')-t)/86400000); }
  function _engGuide(k,t,b){ return '<section>' + t + b + '</section>'; }
  function _engBadge(t){ return '<span class="badge">' + t + '</span>'; }
  function _hrKpi(l,v){ return '<div class="kpi">' + l + ': ' + v + '</div>'; }
  function _hrKpiRow(l){ return '<div class="kpirow">' + l.join('') + '</div>'; }
  function _engCard(title, addColl, addLabel, inner, extra){
    return '<div class="card"><div class="hdr">' + title + (extra||'') + '</div>' + inner + '</div>';
  }
  function _engFiltBar(){ return '<div class="filters"></div>'; }
  function _engFiltApply(c, rows){ return rows; }
  function _engTable(coll, cols, rows, opts){
    return '<div class="table-wrap"><table><thead><tr>' +
      cols.map(function(c){ return '<th>' + c.label + '</th>'; }).join('') + '</tr></thead><tbody>' +
      rows.map(function(r){ return '<tr>' + cols.map(function(c){
        return '<td>' + (c.render ? c.render(r) : (r[c.k] == null ? '—' : r[c.k])) + '</td>';
      }).join('') + '</tr>'; }).join('') + '</tbody></table></div>';
  }
  function tkSkeleton(){ return ''; }
  function tkIcon(){ return '<svg></svg>'; }
  function showView(){}
  const sessionStorage = { setItem(){}, getItem(){ return null; } };
`;

const api = {};
new Function('CAPTURE', PRELUDE + NAV + LOG + `
  Object.assign(this, { _ENG_TABS, _ENG_TAB_GROUPS, _engTabBar, engRenderRefusals,
    setTab: v => { _engTabK = v; }, setRows: v => { ROWS = v; }, setLead: v => { LEAD = v; } });
`).call(api, h => { SINK = h; });

const VOID = new Set(['br', 'hr', 'img', 'input', 'meta', 'link', 'source', 'path', 'polyline',
  'rect', 'line', 'circle', 'col', 'area', 'base', 'embed', 'track', 'wbr']);

function unbalanced(html) {
  const stack = [];
  const re = /<(\/?)([a-zA-Z][a-zA-Z0-9-]*)((?:"[^"]*"|'[^']*'|[^>"'])*?)(\/?)>/g;
  let m;
  while ((m = re.exec(html))) {
    const close = m[1] === '/', tag = m[2].toLowerCase(), selfClosed = m[4] === '/';
    if (VOID.has(tag) || selfClosed) continue;
    if (!close) { stack.push(tag); continue; }
    if (!stack.length) return 'closing </' + tag + '> with nothing open';
    const top = stack.pop();
    if (top !== tag) return 'closing </' + tag + '> but <' + top + '> was open';
  }
  return stack.length ? 'never closed: <' + stack.join('>, <') + '>' : null;
}

function dupIds(html) {
  const seen = {}, dups = [];
  let m; const re = /\bid="([^"]+)"/g;
  while ((m = re.exec(html))) { if (seen[m[1]]) dups.push(m[1]); seen[m[1]] = 1; }
  return dups;
}

let pass = 0, fail = 0;
function t(name, fn) {
  try { fn(); console.log('  ok    ' + name); pass++; }
  catch (e) { console.log('  FAIL  ' + name + '\n        ' + e.message); fail++; }
}
function wellFormed(label, html) {
  const bad = unbalanced(html);
  if (bad) throw new Error(label + ' — ' + bad);
  const d = dupIds(html);
  if (d.length) throw new Error(label + ' — duplicate id(s): ' + d.join(', '));
  if (html.length < 80) throw new Error(label + ' — suspiciously short (' + html.length + ' chars); nothing was rendered');
}

/* The checker before the checked. A tag stack that never reports a fault would pass this whole
   file on markup shredded beyond use, and the clean result below would mean nothing at all. */
console.log('\nthe checker itself catches what it claims to');
[['<div><span></div></span>', 'closing </div> but <span> was open'],
 ['<div><p>x', 'never closed: <div>, <p>'],
 ['</div>', 'closing </div> with nothing open']
].forEach(([html, want]) => t('detects: ' + want, () => {
  const got = unbalanced(html);
  if (got !== want) throw new Error('expected ' + JSON.stringify(want) + ', got ' + JSON.stringify(got));
}));
t('detects a duplicate id', () => {
  const d = dupIds('<div id="eng-tabbar"></div><div id="eng-tabbar"></div>');
  if (d.join() !== 'eng-tabbar') throw new Error('got ' + JSON.stringify(d));
});
t('does not cry wolf over void and self-closed tags', () => {
  const got = unbalanced('<div><br><img src="x"><svg><path d="M0 0"/></svg></div>');
  if (got) throw new Error('false positive: ' + got);
});

const P = { id: 'p1', code: 'PIL26' };
console.log('\ntab bar markup, every group');
api._ENG_TAB_GROUPS.forEach(g => {
  const first = api._ENG_TABS.find(x => x.g === g.k);
  t(g.k + ' (' + g.label + ')', () => {
    api.setTab(first.k);
    wellFormed('tab bar on ' + g.k, api._engTabBar(P));
  });
});
t('every tab individually', () => {
  api._ENG_TABS.forEach(tab => { api.setTab(tab.k); wellFormed('tab bar on ' + tab.k, api._engTabBar(P)); });
});
t('and with the restricted tab hidden', () => {
  api.setLead(false); api.setTab('changes');
  wellFormed('tab bar, non-lead', api._engTabBar(P));
  api.setLead(true);
});

const R = o => Object.assign({
  projectId: 'p1', coll: 'eng_revisions', attempted: 'Issued',
  rule: 'Record who checked this document before issuing it', message: 'Nobody is named.',
  recordId: 'r1', recordRef: 'C01', who: 'Alice Engineer',
  at: '2026-08-28 16:40:00', source: 'sign'
}, o);

console.log('\nrefusal screen markup');
[['empty log', []],
 ['one refusal', [R()]],
 ['refusals and advisory notes', [R(), R({ source: 'advisory', recordId: 'r2' })]],
 ['a row with missing fields', [R({ recordRef: '', who: '', at: '', message: '' })]],
 ['many rules', [R(), R({ coll: 'eng_stages', attempted: 'Passed', rule: 'Close the open HOLDs' }),
                 R({ coll: 'eng_deviations', attempted: 'Approved', rule: 'Agree the departure' })]]
].forEach(([label, rows]) => {
  t(label, () => { api.setRows(rows); SINK = ''; api.engRenderRefusals('p1'); wellFormed(label, SINK); });
});

console.log('\n' + pass + ' passed, ' + fail + ' failed');
process.exit(fail ? 1 : 0);
