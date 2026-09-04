/* Workspace tabs that stack independent registers on one scroll, split into pages.
 *
 * Quality carried three (quality register, ITP timeline, ITP register) and Comms & Issues two. On a
 * project with 151 ITPs the timeline alone is 151 rows, so the register beneath it started several
 * screens down and was, in practice, unreachable.
 *
 * The machinery is deliberately ONE implementation shared by both tabs, and that is most of what is
 * worth guarding here, because every failure this pattern has produced in this file came from
 * duplication or from eagerness:
 *   - the Schedule tab's pane list once existed TWICE, and a pane added to only one copy rendered
 *     correctly and was never displayed — every pane hidden, none shown, nothing logged;
 *   - panes built eagerly are parsed, styled and laid out for nothing, and a pane measured while
 *     HIDDEN measures zero, which is how a scroll box gets sized from nothing;
 *   - a stored page that a later render no longer offers leaves every pane hidden and the screen
 *     blank, which looks like a data problem and is not.
 *
 *   node tests/pm_subtabs.js
 */
const fs = require('fs');
const path = require('path');

const src = fs.readFileSync(path.join(__dirname, '..', 'templates', 'index.html'), 'utf8');

let pass = 0, fail = 0;
const ok = (n, c, extra) => {
  if (c) { pass++; console.log('  ok    ' + n); }
  else { fail++; console.log('  FAIL  ' + n + (extra ? '\n        ' + extra : '')); }
};
const take = (mark, what, stop) => {
  const i = src.indexOf(mark);
  if (i < 0) { console.error('Could not find ' + what + ' — update the marker, do NOT delete this test.'); process.exit(2); }
  const j = src.indexOf(stop || '\nfunction ', i + 10);
  if (j < 0) { console.error('Could not find the end of ' + what + '.'); process.exit(2); }
  return src.slice(i, j);
};

console.log('\nWorkspace sub-tabs\n');

/* ══ 1. the bar and its panes ═══════════════════════════════════════════════════════════════ */
const api = {};
new Function(
  'function _t2(en, vn){ return en; }' +
  'function _pmEsc(s){ return String(s == null ? "" : s); }' +
  take('const _PM_SUBTABS = {', 'the sub-tab declarations', '\nfunction pmSubTab') +
  take('function _pmSubTabsHtml(', '_pmSubTabsHtml') +
  '\nObject.assign(this, { _PM_SUBTABS, _pmSubTabsHtml, _pmSubBuild,' +
  '  cur: k => _pmSubTab[k], set: (k, v) => { _pmSubTab[k] = v; } });'
).call(api);
const { _PM_SUBTABS, _pmSubTabsHtml } = api;

const built = [];
const mk = (k) => ({ [k]: () => { built.push(k); return '<i>' + k + '</i>'; } });
const builds = Object.assign({}, ...['register', 'itpsched', 'itp'].map(mk));

api.set('quality', 'register');
built.length = 0;
const html = _pmSubTabsHtml('quality', builds);

ok('every declared pane gets a host element',
   ['register', 'itpsched', 'itp'].every(k => html.indexOf('id="psub-quality-' + k + '"') > 0), html.slice(0, 300));
ok('and a button, each labelled from the declaration',
   html.indexOf('>Quality Register<') > 0 && html.indexOf('>ITP Schedule<') > 0 &&
   html.indexOf('>Inspection & Test Plan<') > 0);
ok('the current page is the active button',
   /id="psubtab-quality-register" class="tab active"/.test(html));
ok('and the only one that is active',
   (html.match(/class="tab active"/g) || []).length === 1);

/* ══ 2. ONLY the visible page is built ══════════════════════════════════════════════════════ */
ok('exactly one pane was rendered, not all three',
   built.length === 1 && built[0] === 'register', built.join(','));
ok('the other two are present but hidden, ready to be filled on demand',
   /id="psub-quality-itpsched" style="display:none"></.test(html) &&
   /id="psub-quality-itp" style="display:none"></.test(html), html);
ok('the visible one is marked built so it is not re-rendered on first click',
   /id="psub-quality-register" data-built="1"/.test(html));

/* ══ 3. a stored page the render no longer offers must not blank the screen ═════════════════ */
api.set('quality', 'a-pane-that-was-renamed');
built.length = 0;
const recovered = _pmSubTabsHtml('quality', builds);
ok('an unknown stored page falls back to the first, rather than hiding every pane',
   api.cur('quality') === 'register' && built.length === 1 &&
   /id="psub-quality-register" data-built="1"/.test(recovered),
   'stored=' + api.cur('quality') + ' built=' + built.join(','));

/* ══ 4. both tabs use the SAME machinery — a second hand-rolled copy is the bug ═════════════ */
ok('Comms & Issues declares its two pages in the same place',
   (_PM_SUBTABS.comms || []).map(p => p[0]).join() === 'log,issues',
   JSON.stringify(_PM_SUBTABS.comms));
const qual = take('function pmRenderQuality(', 'pmRenderQuality');
const comms = take('function pmRenderComms(', 'pmRenderComms');
ok('Quality renders through the shared helper',
   /_pmSubTabsHtml\('quality', \{/.test(qual));
ok('Comms & Issues renders through the same one',
   /_pmSubTabsHtml\('comms', \{ log: buildCommsLog, issues: buildIssueLog \}\)/.test(comms));
ok('there is exactly ONE pane-showing function in the file',
   (src.match(/^function pmSubTab\(/gm) || []).length === 1);
ok('and exactly one declaration of the pane lists',
   (src.match(/^const _PM_SUBTABS = /gm) || []).length === 1);

/* ══ 5. the builds really are thunks, on both tabs ══════════════════════════════════════════ */
const deferred = (n, where) => new RegExp('const ' + n + ' = \\(\\) => _pmCard\\(').test(where);
['buildRegister', 'buildItpTable'].forEach(n =>
  ok(n + ' is deferred, not a string computed on every render', deferred(n, qual), n));
['buildCommsLog', 'buildIssueLog'].forEach(n =>
  ok(n + ' is deferred too', deferred(n, comms), n));

/* ══ 6. the KPI strip describes the TAB, so it stays above the bar ══════════════════════════ */
ok('Quality keeps its KPI row outside the pages — the overdue-NCR count is not something to '
   + 'click for',
   /_pmSet\(kpis \+ _pmSubTabsHtml\('quality'/.test(qual));
ok('and so does Comms & Issues, with its open-issue count',
   /_pmSet\(kpis \+ _pmSubTabsHtml\('comms'/.test(comms));

/* ══ 7. showing a pane re-runs the sizing pass it could not run while hidden ════════════════ */
const swap = take('function pmSubTab(', 'pmSubTab');
ok('a pane is built on first show, never while hidden',
   /if \(host && !host\.dataset\.built && build\)/.test(swap));
ok('and the table-sizing pass is re-run after the swap',
   /_fitTablesSoon\(\)/.test(swap),
   'flipping style.display fires no childList mutation, so nothing else re-measures');
ok('an unknown pane name is refused rather than hiding everything',
   /if \(!panes \|\| !panes\.some\(p => p\[0\] === name\)\) return;/.test(swap));
ok('a build that throws leaves a message in its own pane, not a half-painted tab',
   /catch \(e\) \{ host\.innerHTML =/.test(swap));

console.log('\n' + pass + ' passed, ' + fail + ' failed\n');
process.exit(fail ? 1 : 0);
