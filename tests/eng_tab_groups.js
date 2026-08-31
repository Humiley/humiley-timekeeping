/* The design workspace's navigation, checked against the code that ships.
 *
 * Twenty-one registers now sit under six process groups. The failure this guards against is
 * specific and silent: a tab whose `g` key does not match any group is filtered out of the tab row
 * and the register becomes unreachable while still existing, still loading, still being written to
 * by anybody who kept a deep link. Nothing errors. The screen just does not offer it.
 *
 * That is the same shape as the Stages & Gates tab that rendered blank in production for weeks —
 * an absence reads as "there is nothing here", never as a bug. So: every tab must land in a real
 * group, and every group must hold at least one tab, or this fails the build.
 *
 * The runtime has a fallback for the same case (_engGroupOf drops a straggler into the last group)
 * so production never loses a register while somebody fixes a typo. The fallback and this test are
 * not redundant: the fallback keeps the register reachable, the test is what makes anyone notice.
 *
 *   node tests/eng_tab_groups.js
 */
const fs = require('fs');
const path = require('path');

const src = fs.readFileSync(path.join(__dirname, '..', 'templates', 'index.html'), 'utf8');
const START = '/* ── ENG TAB NAV ──', END = '/* ── END ENG TAB NAV ── */';
const i = src.indexOf(START), j = src.indexOf(END);
if (i < 0 || j < 0 || j <= i) {
  console.error('Could not find the tab-nav block in templates/index.html.\n' +
    'If the markers were renamed, update START/END here — do NOT delete this test.');
  process.exit(2);
}

/* Stubs. _engIsLead decides whether the restricted tab is offered and _engTabK is which tab is
   open, so both are knobs rather than constants — the group highlight is DERIVED from _engTabK and
   that derivation is most of what is being checked. */
const PRELUDE = `
  let LEAD = true;
  let _engTabK = 'overview';
  let _engCurrentProject = 'p1';
  function _engIsLead(p){ return LEAD; }
  function _engProj(){ return { id: 'p1', code: 'PIL26' }; }
  function _tkEscA(s){ return String(s == null ? '' : s).replace(/"/g, '&quot;'); }
  function tkSkeleton(){ return ''; }
  function showView(){}
  function tkIcon(){ return ''; }
  const sessionStorage = { setItem(){}, getItem(){ return null; } };
  const _HR = {};
  function _engPid(){ return 'p1'; }
  function _engEsc(s){ return String(s == null ? '' : s); }
  function _t(s){ return s; }
  function _engSet(h){ const b = document.getElementById('eng-tab-body'); if (b) b.innerHTML = h; }
  async function _engNeed(names){ (names || []).forEach(function (n) { _HR[n] = []; }); return []; }
`;

const api = {};
new Function(PRELUDE + src.slice(i, j) + `
  Object.assign(this, {
    _ENG_TABS, _ENG_TAB_GROUPS, _engGroupOf, _engGroupTabs, _engActiveGroup, _engTabsFor,
    _engGroupRow, _engTabRow, _engTabBar, engTab,
    setLead: function (v) { LEAD = v; },
    setTab: function (v) { _engTabK = v; }
  });
`).call(api);
const { _ENG_TABS, _ENG_TAB_GROUPS, _engGroupOf, _engGroupTabs, _engActiveGroup,
        _engTabsFor, _engGroupRow, _engTabRow, setLead, setTab } = api;

let pass = 0, fail = 0;
/* Async-aware: the dispatcher tests below await engTab, and a runner that ignored the promise
   would report them all green without ever reaching the assertion. */
const queue = [];
function t(name, fn) {
  queue.push(async () => {
    try { await fn(); console.log('  ok    ' + name); pass++; }
    catch (e) { console.log('  FAIL  ' + name + '\n        ' + e.message); fail++; }
  });
}
function say(s) { queue.push(async () => console.log(s)); }
const eq = (a, b, m) => { if (a !== b) throw new Error((m || '') + ' expected ' + JSON.stringify(b) + ', got ' + JSON.stringify(a)); };
const ok = (c, m) => { if (!c) throw new Error(m || 'expected true'); };

const P = { id: 'p1', code: 'PIL26' };
const GK = _ENG_TAB_GROUPS.map(g => g.k);

say('\nevery register is reachable');
t('there is more than one group and more than one tab', () => {
  /* Guards the guard: if the extraction silently produced empty arrays, every check below would
     pass while examining nothing. */
  ok(_ENG_TABS.length > 10, 'only ' + _ENG_TABS.length + ' tabs were extracted');
  ok(_ENG_TAB_GROUPS.length >= 4, 'only ' + _ENG_TAB_GROUPS.length + ' groups were extracted');
});
t('every tab declares a group that exists', () => {
  const orphans = _ENG_TABS.filter(x => GK.indexOf(x.g) < 0).map(x => x.k + ' (g:' + x.g + ')');
  eq(orphans.join(', '), '', 'these tabs would drop out of the navigation:');
});
t('every group holds at least one tab', () => {
  setLead(true);
  const empty = GK.filter(g => !_engGroupTabs(P, g).length);
  eq(empty.join(', '), '', 'these group pills would render with nothing behind them:');
});
t('the groups partition the tabs — none counted twice, none missed', () => {
  setLead(true);
  const n = GK.reduce((s, g) => s + _engGroupTabs(P, g).length, 0);
  eq(n, _engTabsFor(P).length, 'sum of the groups vs the tab list:');
});

say('\nthe highlighted group is derived from the open tab');
t('each tab lights its own group, all of them', () => {
  setLead(true);
  _engTabsFor(P).forEach(tab => {
    setTab(tab.k);
    eq(_engActiveGroup(P), tab.g, 'tab "' + tab.k + '" lit the wrong pill:');
  });
});
t('an unknown tab key falls back to the first group rather than none', () => {
  setTab('a-tab-that-was-deleted');
  eq(_engActiveGroup(P), GK[0]);
});
t('the tab row shows the open tab, and only its group', () => {
  setLead(true);
  setTab('holds');
  const row = _engTabRow(P);
  ok(row.indexOf('data-k="holds"') >= 0, 'the open tab is missing from its own row');
  _engTabsFor(P).filter(x => x.g !== 'verify')
    .forEach(x => ok(row.indexOf('data-k="' + x.k + '"') < 0, x.k + ' leaked into another group'));
});
t('exactly one pill is marked active', () => {
  setTab('mdr');
  const lit = (_engGroupRow(P).match(/background:var\(--navy\)/g) || []).length;
  eq(lit, 1);
});

say('\nthe restricted tab');
t('a lead is offered the refusal log; somebody else is not', () => {
  setLead(true);
  ok(_engTabsFor(P).some(x => x.k === 'refusals'), 'a lead cannot reach the refusal log');
  setLead(false);
  ok(!_engTabsFor(P).some(x => x.k === 'refusals'), 'a non-lead was offered the refusal log');
});
t('its group does not render an empty pill when it is the only tab hidden', () => {
  /* A pill whose every tab is restricted must not be drawn: clicking it would open nothing. */
  setLead(false);
  const g = _ENG_TABS.find(x => x.k === 'refusals').g;
  const row = _engGroupRow(P);
  const others = _engGroupTabs(P, g).length;
  if (others) ok(row.indexOf('data-g="' + g + '"') >= 0, 'the group still has tabs and should show');
  else ok(row.indexOf('data-g="' + g + '"') < 0, 'an empty group pill was drawn');
  setLead(true);
});

say('\nthe fallback keeps a mis-keyed tab reachable');
t('a tab with a bad group key lands in the last group, not nowhere', () => {
  eq(_engGroupOf({ k: 'x', g: 'not-a-group' }), GK[GK.length - 1]);
  eq(_engGroupOf({ k: 'x' }), GK[GK.length - 1], 'a tab with no group at all');
});

// ── the dispatcher has to PAINT ────────────────────────────────────────────────
//
// engTab used to call the renderer and throw its return value away. Most renderers call _engSet
// themselves; EIGHT of the twenty-one ended `return guide + kpis + tbl` — so Codes & Standards,
// Deviations, Design Risk, Effort & Earned Value, Register Check, IDC Matrix, Holds & Assumptions
// and Awaiting Response painted nothing at all. The body kept whatever the previous tab left in
// it, which is worse than blank: a blank panel reads as "no data", the previous register's table
// under a new heading reads as THIS register's data. Nothing threw, so nothing was ever logged.
//
// Both shapes are exercised here against the real engTab, because a static "does it contain
// _engSet" scan would pass on a dispatcher that painted into the wrong element.

say('\nthe dispatcher paints, whichever way a renderer is written');

async function withBody(fn) {   // async: a sync `finally` removed the DOM before the awaited
                                // engTab ever ran, and the failure read as a bug in the fix
  /* Minimal DOM: the one element engTab writes into, plus the two nav rows it repaints. */
  const nodes = {};
  const mk = id => (nodes[id] = { id: id, innerHTML: '', dataset: {}, style: {}, scrollIntoView() { } });
  ['eng-tab-body', 'eng-grpbar', 'eng-tabbar'].forEach(mk);
  global.document = {
    getElementById: id => nodes[id] || null,
    querySelector: () => null,
    querySelectorAll: () => []
  };
  global.window = global;
  try { return await fn(nodes); } finally { delete global.document; }
}

t('a renderer that RETURNS its html gets painted', async () => {
  await withBody(async nodes => {
    global.engRenderStages = () => '<div id="from-return">standards-shaped renderer</div>';
    setTab('overview');
    await api.engTab('stages');
    if (nodes['eng-tab-body'].innerHTML.indexOf('from-return') < 0) {
      throw new Error('the returned html never reached the page — got ' +
        JSON.stringify(nodes['eng-tab-body'].innerHTML.slice(0, 80)));
    }
  });
});
t('a renderer that calls _engSet still works', async () => {
  await withBody(async nodes => {
    global.engRenderStages = () => { nodes['eng-tab-body'].innerHTML = '<div id="from-set">set</div>'; };
    setTab('overview');
    await api.engTab('stages');
    if (nodes['eng-tab-body'].innerHTML.indexOf('from-set') < 0) throw new Error('_engSet-style renderer stopped painting');
  });
});
t('a renderer that returns nothing leaves the body alone rather than blanking it', async () => {
  await withBody(async nodes => {
    nodes['eng-tab-body'].innerHTML = '<div id="pre">painted by the renderer itself</div>';
    global.engRenderStages = () => undefined;
    setTab('overview');
    await api.engTab('stages');
    if (nodes['eng-tab-body'].innerHTML.indexOf('pre') < 0) throw new Error('an undefined return wiped the body');
  });
});
t('a throwing renderer shows an error instead of a blank panel', async () => {
  await withBody(async nodes => {
    global.engRenderStages = () => { throw new Error('boom'); };
    setTab('overview');
    await api.engTab('stages');
    if (nodes['eng-tab-body'].innerHTML.indexOf('boom') < 0) throw new Error('the error was swallowed');
  });
});

(async () => {
  for (const step of queue) await step();
  console.log('\n' + pass + ' passed, ' + fail + ' failed');
  process.exit(fail ? 1 : 0);
})();
