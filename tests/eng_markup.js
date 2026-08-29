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
const BASE = slice('/* ── ENG BASELINE ──', '/* ── END ENG BASELINE ── */');
const PANEL = slice('/* ── ENG BASELINE PANEL ──', '/* ── END ENG BASELINE PANEL ── */');

let SINK = '';
const PRELUDE = `
  let LEAD = true, _engTabK = 'overview', _engCurrentProject = 'p1', ROWS = [];
  const PROJ = { id: 'p1', code: 'PIL26', name: 'Pilot commission' };
  function _engIsLead(){ return LEAD; }
  function _engProj(){ return PROJ; }
  function _engScopeFor(c){ return c === 'eng_refusals' ? ROWS : (c === 'eng_deliverables' ? DELS : []); }
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
  const _HR = { eng_baselines: [] };
  let DELS = [];
  function _engInScope(d){ return String(d.creditStatus || '') !== 'Cancelled'; }
  function _engProgress(rows){
    let w = 0, e = 0;
    (rows || []).forEach(function (d) {
      if (!_engInScope(d)) return;
      const ww = Math.max(0, +d.weight || 0) || 1; w += ww; e += ww * (+d.credit || 0);
    });
    return { pct: w ? e / w : 0, wsum: w };
  }
  function _engSpi(){ return 0.93; }
  function _engTile(l, v, hex, sub){ return '<div class="tile">' + l + ': ' + v + (sub ? ' (' + sub + ')' : '') + '</div>'; }
  function _engTiles(list){ return '<div class="tiles">' + list.join('') + '</div>'; }
  function _t(s){ return s; }
`;

const api = {};
new Function('CAPTURE', PRELUDE + NAV + LOG + BASE + PANEL + `
  Object.assign(this, { _ENG_TABS, _ENG_TAB_GROUPS, _engTabBar, engRenderRefusals,
    _engBaselinePanel,
    setTab: v => { _engTabK = v; }, setRows: v => { ROWS = v; }, setLead: v => { LEAD = v; },
    setDels: v => { DELS = v; }, setBaselines: v => { _HR.eng_baselines = v; } });
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

console.log('\nbaseline panel markup');
const BD = (id, planned, o) => Object.assign({ id: id, docNo: id, title: 'Doc ' + id,
  plannedIssue: planned, weight: 10, credit: 0 }, o || {});
const BBL = (lines, o) => Object.assign({ projectId: 'p1', seq: 1, stage: 'Detail',
  takenOn: '2026-08-12', takenBy: 'Staff One', lines: lines }, o || {});
const BL_ = (id, planned) => ({ deliverableId: id, docNo: id, plannedIssue: planned });

[['no baseline at all', [BD('a', '2026-09-01')], []],
 ['a baseline with nothing moved', [BD('a', '2026-09-01')], [BBL([BL_('a', '2026-09-01')])]],
 ['dates moved both ways', [BD('a', '2026-11-30'), BD('b', '2026-08-01')],
  [BBL([BL_('a', '2026-09-01'), BL_('b', '2026-09-01')])]],
 ['scope added, scope gone, dates removed',
  [BD('a', ''), BD('new', '2026-10-01')],
  [BBL([BL_('a', '2026-09-01'), BL_('vanished', '2026-09-01')])]],
 ['more than five moved, so the table truncates',
  Array.from({ length: 8 }, (_, n) => BD('d' + n, '2026-12-0' + (n + 1))),
  [BBL(Array.from({ length: 8 }, (_, n) => BL_('d' + n, '2026-09-01')))]],
 ['a cancelled deliverable in the baseline',
  [BD('a', '2026-09-01', { creditStatus: 'Cancelled' })], [BBL([BL_('a', '2026-09-01')])]],
 ['the newest of three baselines governs', [BD('a', '2026-09-01')],
  [BBL([BL_('a', '2026-01-01')], { seq: 1 }), BBL([BL_('a', '2026-09-01')], { seq: 3 }),
   BBL([BL_('a', '2026-05-01')], { seq: 2 })]]
].forEach(([label, dels, bls]) => {
  t(label, () => {
    api.setDels(dels); api.setBaselines(bls);
    wellFormed(label, api._engBaselinePanel('p1'));
  });
});
t('and for somebody who cannot take one', () => {
  api.setLead(false);
  api.setDels([BD('a', '2026-09-01')]); api.setBaselines([]);
  wellFormed('no-baseline panel, non-lead', api._engBaselinePanel('p1'));
  api.setLead(true);
});

console.log('\n' + pass + ' passed, ' + fail + ' failed');
process.exit(fail ? 1 : 0);
