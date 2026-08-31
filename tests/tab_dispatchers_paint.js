/* Every tab dispatcher in the app must paint what its renderer returns.
 *
 * This is a whole-app guard for the bug that took eight design tabs off the screen. A renderer may
 * paint itself (`_engSet(...)`) or return its html (`return guide + kpis + tbl`); both shapes are
 * written in this file, in every module, and for a long time only one of them worked. engTab
 * called the renderer and discarded the result, so Codes & Standards, Deviations, Design Risk,
 * Effort & Earned Value, Register Check, IDC Matrix, Holds & Assumptions and Awaiting Response
 * painted nothing — the body kept the PREVIOUS tab's content, which is worse than blank, because
 * the previous register's table under a new heading reads as this register's data.
 *
 * Nothing threw. Nothing logged. The only reason it was found is that somebody asked whether
 * anything in the module was built but unreachable.
 *
 * There are three dispatchers — pmTab, engTab, estTab — and the same mistake is available in each.
 * This asserts the invariant on all of them by DRIVING them: a fake renderer that returns a string
 * must reach the page. A static "does the source contain innerHTML" scan would pass on a
 * dispatcher that painted into the wrong element.
 *
 *   node tests/tab_dispatchers_paint.js
 */
const fs = require('fs');
const path = require('path');

const src = fs.readFileSync(path.join(__dirname, '..', 'templates', 'index.html'), 'utf8');

/* Each dispatcher: how to find it, what it paints into, and a tab key that exists in its table. */
const DISPATCHERS = [
  { name: 'pmTab', body: 'pm-tab-body', bar: 'pm-tabbar',
    fnOf: /\{ k: '([a-z]+)'[^}]*fn: '(pmRender[A-Za-z0-9_]+)'/ },
  { name: 'engTab', body: 'eng-tab-body', bar: 'eng-tabbar',
    fnOf: /\{ k: '([a-z]+)', g: '[a-z]+'[^}]*fn: '(engRender[A-Za-z0-9_]+)'/ },
  { name: 'estTab', body: 'est-tab-body', bar: 'est-tabbar',
    fnOf: /\{ k: '([a-z0-9]+)'[^}]*fn: '((?:est|tnd)[A-Za-z0-9_]+)'/ }
];

/* AWAITED. The first version of this runner called fn() and counted the test passed before the
   promise inside it resolved — engTab is async, so its assertion ran after the tally and its
   rejection was swallowed. Mutation-tested at the time: all three dispatchers were broken in turn
   and the suite reported "3 passed" every time. A guard that cannot fail is worse than no guard,
   and this one was two minutes from being committed. */
let pass = 0, fail = 0;
const queue = [];
function t(name, fn) {
  queue.push(async () => {
    try { await fn(); console.log('  ok    ' + name); pass++; }
    catch (e) { console.log('  FAIL  ' + name + '\n        ' + e.message); fail++; }
  });
}

/* The source of each dispatcher function, from `function NAME(` to its closing brace at column 0. */
function bodyOf(name) {
  const m = new RegExp('^(?:async )?function ' + name + '\\(', 'm').exec(src);
  if (!m) throw new Error('dispatcher ' + name + ' not found in index.html');
  const end = src.indexOf('\n}', m.index);
  return src.slice(m.index, end + 2);
}

console.log('\nevery dispatcher paints a returned string');
DISPATCHERS.forEach(d => {
  t(d.name, () => {
    const fnm = d.fnOf.exec(src);
    if (!fnm) throw new Error('could not find a tab entry for ' + d.name);
    const [, tabKey, renderer] = fnm;

    const nodes = {};
    const mk = id => (nodes[id] = { id: id, innerHTML: '', dataset: {}, style: {}, scrollIntoView() { } });
    [d.body, d.bar, 'eng-grpbar'].forEach(mk);

    /* Enough of the app for the dispatcher to reach its renderer and nothing more. Anything it
       needs that is missing throws, and the test says which — a stub that silently returns
       undefined would let a dispatcher "pass" by never getting as far as painting. */
    const PRELUDE = `
      const document = {
        getElementById: id => NODES[id] || null,
        querySelector: () => null,
        querySelectorAll: () => ({ forEach() {} })
      };
      const window = { ${renderer}: () => '<div id="painted-by-return">x</div>' };
      let _pmTabK = '${tabKey}', _engTabK = '${tabKey}', _estTabK = '${tabKey}';
      let _pmCurrentProject = 'p1', _engCurrentProject = 'p1';
      const _HR = {};
      function _pmPid(){ return 'p1'; } function _engPid(){ return 'p1'; }
      function _pmProj(){ return { id: 'p1' }; } function _engProj(){ return { id: 'p1' }; }
      function _pmEsc(s){ return String(s||''); } function _engEsc(s){ return String(s||''); }
      function _estEsc(s){ return String(s||''); }
      function _engIsLead(){ return true; }
      function _t(s){ return s; }
      function tkSkeleton(){ return ''; }
      function _tkEscA(s){ return String(s||''); }
      function tkIcon(){ return ''; }
      function _estSet(h){ const b = document.getElementById('${d.body}'); if (b) b.innerHTML = h; }
      function _engSet(h){ const b = document.getElementById('${d.body}'); if (b) b.innerHTML = h; }
      function _pmSet(h){ const b = document.getElementById('${d.body}'); if (b) b.innerHTML = h; }
      async function _pmNeed(){ return []; } async function _engNeed(){ return []; }
      function _tndTabs(){ return [{ k: '${tabKey}', label: 'T', fn: '${renderer}' }]; }
      function _engGroupRow(){ return ''; } function _engTabRow(){ return ''; }
      function _engActiveGroup(){ return 'plan'; }
      function _engGroupTabs(){ return []; } function _engTabsFor(){ return _ENG_TABS || []; }
      function _engGroupOf(){ return 'plan'; }
    `;
    const need = [];
    if (d.name === 'engTab') need.push(src.slice(src.indexOf('const _ENG_TABS = ['),
                                                 src.indexOf('function _engTabsFor')));
    if (d.name === 'pmTab') need.push(src.slice(src.indexOf('const _PM_TABS = ['),
                                                src.indexOf('\n];', src.indexOf('const _PM_TABS = [')) + 3));

    const run = new Function('NODES', PRELUDE + need.join('\n') + '\n' + bodyOf(d.name) +
      '\n; return ' + d.name + '("' + tabKey + '");');
    return Promise.resolve(run(nodes)).then(() => {
      const got = nodes[d.body].innerHTML;
      /* Empty means the dispatcher never reached the renderer at all — a missing stub swallowed by
         its own try/catch. That is a broken TEST, not a broken dispatcher, and saying so is the
         difference between fixing the harness and "fixing" working code. */
      if (!got) {
        throw new Error(d.name + ' painted nothing at all. Either the dispatcher discarded the ' +
          'return, or this harness is missing something it needs and its catch swallowed the ' +
          'error. Check the stubs before changing the dispatcher.');
      }
      if (got.indexOf('painted-by-return') < 0) {
        throw new Error(d.name + ' discarded the html its renderer returned — the tab would show ' +
          'the PREVIOUS tab\'s content. Capture the return value and paint it, as engTab does. ' +
          'Body was ' + JSON.stringify(got.slice(0, 80)));
      }
    });
  });
});

(async () => {
  for (const step of queue) await step();
  console.log('\n' + pass + ' passed, ' + fail + ' failed');
  process.exit(fail ? 1 : 0);
})();
