/* The Library board and the two hub document panels, driven against the code that ships.
 *
 * Neither panel can be exercised by opening the app locally: they read SharePoint through
 * Microsoft Graph with the reader's own delegated token, and a development machine has no
 * Microsoft session — so every local check falls into the same "Demo mode" branch and the
 * listing code never runs at all. That is precisely the shape this codebase keeps getting
 * caught by: a render that throws leaves an EMPTY PANEL, and an empty panel reads as "there
 * are no documents" rather than as a failure. _engGateReadiness sat blank in production for
 * weeks that way.
 *
 * So the block is sliced out of templates/index.html, given stubs for everything it leans
 * on, and actually called — with rows that look like what Graph returns.
 *
 * The other half is the claim each state makes. "You are not signed in", "no library is
 * configured" and "this folder is empty" are indistinguishable as a blank list and mean
 * completely different things — only one of them is the reader's to act on. Each is asserted
 * to say its own thing.
 *
 *   node tests/library_docs_panel.js
 */
const fs = require('fs');
const path = require('path');

const src = fs.readFileSync(path.join(__dirname, '..', 'templates', 'index.html'), 'utf8');
const START = '/* ── LIBRARY / WIKI / KNOWLEDGE HUB ──';
const END = '/* ── END LIBRARY / WIKI / KNOWLEDGE HUB ── */';
const i = src.indexOf(START), j = src.indexOf(END);
if (i < 0 || j < 0 || j <= i) {
  console.error('Could not find the library block in templates/index.html.\n' +
    'If the markers were renamed, update START/END here — do NOT delete this test.');
  process.exit(2);
}

/* Stubs pass their content through rather than returning a placeholder, so what comes out
   still contains the real names, the real URLs and the real wording. */
const PRELUDE = `
  const DOM = {};
  const document = { getElementById: function (id) { return DOM[id] || null; } };
  const window = { _TK_PORTAL: {} };
  let _crmLF = {};
  /* A Microsoft session that CAN still renew silently. _libToken asks msal for the token itself
     now (the popup fallback was what broke on Safari), so the stub has to answer that call —
     without it every listing fails as 'reauth' and every assertion below tests the error path. */
  let SILENT_OK = true;
  let _msalApp = { acquireTokenSilent: async function () {
    if (!SILENT_OK) { const e = new Error('interaction_required'); e.errorCode = 'interaction_required'; throw e; }
    return { accessToken: 'T' };
  }, acquireTokenRedirect: function () { REDIRECTED = true; }, getAllAccounts: function () { return [{}]; } };
  let _account = {}, REDIRECTED = false;
  let _userLevel = 'manager';
  let TK = { user: { dept: '' } };
  function DEMO_MODE(){ return false; }
  function _crmEsc(s){ return String(s == null ? '' : s).replace(/&/g,'&amp;').replace(/</g,'&lt;').replace(/>/g,'&gt;'); }
  function _tkEscA(s){ return String(s == null ? '' : s).replace(/&/g,'&amp;').replace(/"/g,'&quot;'); }
  function _crmHref(u){ const v = String(u || '').trim(); return /^https?:\\/\\//i.test(v) ? v : ''; }
  function _t(s){ return String(s == null ? '' : s); }
  function tkIcon(){ return '<icon>'; }
  function tkFmtDate(d){ return String(d || ''); }
  function _crmFiltBar(h){ return '<filterbar>' + h + '</filterbar>'; }
  function _crmFiltSearch(id){ return '<search id="' + id + '">'; }
  function _crmFiltSel(id){ return '<select id="' + id + '">'; }
  function _crmFiltPeriod(id){ return '<period id="' + id + '">'; }
  let PERIOD_OK = true;
  function _inPeriodLF(){ return PERIOD_OK; }
  /* _libVisibleRows moved to _crmInPeriodLF — the one that KEEPS a row with no date rather than
     dropping it. Stubbed separately so a future swap back to _inPeriodLF fails here loudly. */
  function _crmInPeriodLF(){ return PERIOD_OK; }
  /* The pager routes through the Retry-After helper now; a folder open is up to 40 calls. */
  async function _graphFetch(u, o){ return fetch(u, o); }
  function _tkPortalData(){ return PORTAL; }
  let PORTAL = { library: [], wiki: [], learning: [], resources: [] };
  const _LEVELS = ['staff', 'manager', 'management', 'editor', 'admin'];
  const _LEVEL_LABEL = { staff: 'User', manager: 'Contributor', management: 'Approver', editor: 'Editor', admin: 'Admin' };
  function _lvlRank(l){ const i = _LEVELS.indexOf(l); return i < 0 ? 1 : i + 1; }
  let CAN_WRITE = false;
  function _tkCanPublishDocs(){ return CAN_WRITE; }
  let DEPTS = [];
  function tkAllDepts(){ return DEPTS; }
  function tkAudit(){}
  function toast(){}
  function _tkAppScopeApply(){}
  const localStorage = { _d: {}, getItem(k){ return this._d[k] || null; }, setItem(k,v){ this._d[k] = String(v); } };
  /* A fake SharePoint drive, so the tab bar can actually be DRIVEN. Everything above this line
     tests rendering from a state somebody set by hand; the department tabs are different — the
     work is in the resolving (find the folder of that name, or fall back, or say there is none),
     and none of that runs unless there is something to fetch from. */
  let DRIVE = null, RESOLVE = null, POSTED = [], DELAY = {}, FETCH_OVERRIDE = null;
  let SEARCHED = [], SEARCH_ROWS = [];
  function _pmSpToken(){ if (!DRIVE) throw new Error('no token in this harness'); return Promise.resolve('T'); }
  function _pmSpResolve(base){
    if (!DRIVE) throw new Error('no graph in this harness');
    return Promise.resolve(RESOLVE(base));
  }
  async function fetch(url, opts) {
    if (FETCH_OVERRIDE) return FETCH_OVERRIDE(url, opts);
    const u = String(url);
    if (opts && opts.method === 'POST') {          // create folder
      POSTED.push({ url: u, body: JSON.parse(opts.body) });
      return { ok: true, status: 201, json: async () => ({ id: 'NEW' }), text: async () => '' };
    }
    /* A search, so the test can assert WHICH ADDRESS was asked. This is the whole claim of the
       scoped search — the heading is downstream of it. */
    if (u.indexOf("/search(q='") >= 0) {
      SEARCHED.push(u);
      return { ok: true, status: 200, json: async () => ({ value: SEARCH_ROWS }), text: async () => '' };
    }
    /* Parsed by hand rather than by regex: this whole prelude lives inside a template literal,
       and a regex literal carrying slashes does not survive that intact. */
    const after = u.split('/drives/')[1] || '';
    const seg = after.split('?')[0].split('/');
    const drv = seg[0];
    const key = seg[1] === 'items' ? decodeURIComponent(seg[2].split(':')[0]) : 'root';
    if (!drv || seg.indexOf('children') < 0) return { ok: false, status: 404, json: async () => ({}), text: async () => 'no route: ' + u };
    const rows = (DRIVE[drv] || {})[key];
    if (!rows) return { ok: false, status: 404, json: async () => ({}), text: async () => 'no folder ' + key };
    /* A per-folder delay, so a test can make a big department reply AFTER a small one clicked
       later. Without it the generation guard cannot be exercised at all: everything resolves in
       the order it was asked for and the race never happens. */
    const d = DELAY[key] || 0;
    if (d) await new Promise(r => setTimeout(r, d));
    return { ok: true, status: 200, json: async () => ({ value: rows }), text: async () => '' };
  }
  function _pmSpCtx(){ return { mode: 'path' }; }
  const _GRAPH = 'https://graph.microsoft.com/v1.0';
  function msalLogin(){}
  function tkConfirm(){ return Promise.resolve(false); }
  let _currentView = 'wiki';
  function showView(id){ if (id) _currentView = id; }
  const sessionStorage = { _d: {}, getItem(k){ return this._d[k] || null; }, setItem(k,v){ this._d[k] = String(v); }, removeItem(k){ delete this._d[k]; } };
`;

const api = {};
new Function(PRELUDE + src.slice(i, j) + `
  Object.assign(this, {
    _libIsSharePoint: _libIsSharePoint,
    _libFmtSize: _libFmtSize,
    _libState: _libState,
    _libPaintDocs: _libPaintDocs,
    _libBodyHtml: _libBodyHtml,
    _libCountText: _libCountText,
    _libMore: _libMore,
    _libVisibleRows: _libVisibleRows,
    _libTilesHtml: _libTilesHtml,
    tkRenderLibrary: tkRenderLibrary,
    _libMaySee: _libMaySee,
    _libMayOpen: _libMayOpen,
    _libViewLevel: _libViewLevel,
    _libUploadUrl: _libUploadUrl,
    setPortal: function (p) { PORTAL = Object.assign(PORTAL, p); },
    setPeriod: function (v) { PERIOD_OK = v; },
    setFilter: function (k, v) { _crmLF[k] = v; },
    getFilter: function (k) { return _crmLF[k]; },
    setLevel: function (l) { _userLevel = l; },
    setCanWrite: function (v) { CAN_WRITE = v; },
    mount: function (id) { DOM[id] = { innerHTML: '' }; return DOM[id]; },
    el: function (id) { return DOM[id]; },
    _libTab: _libTab,
    _libSpList: _libSpList,
    _libTabBar: _libTabBar,
    _libDeptUrl: _libDeptUrl,
    setDrive: function (d, resolve) { DRIVE = d; RESOLVE = resolve; POSTED = []; DELAY = {}; },
    setDelay: function (k, ms) { DELAY[k] = ms; },
    setFetch: function (f) { FETCH_OVERRIDE = f; },
    searched: function () { return SEARCHED; },
    resetSearched: function () { SEARCHED = []; },
    setSearchRows: function (r) { SEARCH_ROWS = r; },
    _libSpSearch: _libSpSearch,
    _libSearchScope: _libSearchScope,
    _libSpEnter: _libSpEnter,
    setDepts: function (d) { DEPTS = d; },
    _libGraphPage: _libGraphPage,
    _libSortCmp: _libSortCmp,
    _libSpFilter_wiki: _libSpFilter_wiki,
    posted: function () { return POSTED; },
    setDepts: function (d) { DEPTS = d; },
    setMyDept: function (d) { TK.user.dept = d; },
    _libDeptAllowed: _libDeptAllowed,
    _libDeptTabs: _libDeptTabs,
    _libVisibleDepts: _libVisibleDepts,
    _libDeptBoard: _libDeptBoard,
    _libToken: _libToken,
    setSilentOk: function (v) { SILENT_OK = v; },
    redirected: function () { return REDIRECTED; },
    _libReconnect: _libReconnect,
    _libRemember: _libRemember,
    _libResumeAfterReconnect: _libResumeAfterReconnect,
    session: function(){ return sessionStorage._d; },
    currentView: function(){ return _currentView; },
    setCurrentView: function(v){ _currentView = v; },
    _libSetView: _libSetView,
    _libView: _libView,
    _libHubHtml: _libHubHtml,
    tkRenderKnowledge: tkRenderKnowledge
  });
`).call(api);

let failed = 0, passed = 0;
function ok(what, cond, extra) {
  if (cond) { passed++; console.log('  ok    ' + what); }
  else { failed++; console.log('  FAIL  ' + what + (extra ? '\n        ' + extra : '')); }
}

/* ── the document panel ─────────────────────────────────────────────────────── */
const ROWS = [
  { id: 'F1', name: 'Policies', folder: { childCount: 4 }, webUrl: 'https://x.sharepoint.com/Policies', lastModifiedDateTime: '2026-08-01T09:00:00Z' },
  { id: 'D1', name: 'Employee Handbook.pdf', file: {}, size: 2411724, webUrl: 'https://x.sharepoint.com/handbook.pdf', lastModifiedDateTime: '2026-07-15T09:00:00Z' },
  { id: 'D2', name: 'Leave Form.docx', file: {}, size: 51200, webUrl: 'https://x.sharepoint.com/leave.docx', lastModifiedDateTime: '2026-07-20T09:00:00Z' }
];
function paint(mutate) {
  const el = api.mount('lib-docs-wiki');
  const st = api._libState('wiki');
  st.crumbs = []; st.items = null; st.drive = 'drv'; st.loading = false; st.error = ''; st.found = null;
  api.setPeriod(true);
  api.setFilter('lib-wiki-f', ''); api.setFilter('lib-wiki-kind', ''); api.setFilter('lib-wiki-sort', '');
  st.shown = 0;
  if (mutate) mutate(st);
  api._libPaintDocs('wiki');
  return el.innerHTML;
}

let html = paint(st => { st.items = ROWS; });
ok('the folder listing renders every row', /Policies/.test(html) && /Employee Handbook\.pdf/.test(html) && /Leave Form\.docx/.test(html));
ok('folders sort before files', html.indexOf('Policies') < html.indexOf('Employee Handbook.pdf'));
/* A FILE IS AN ANCHOR, not a button calling window.open. Only a real link gives the reader the
   destination on hover, middle-click and ctrl-click, and a right-click menu with "open in new
   tab" and "copy link address" — and target=_blank is what leaves the portal open behind the
   SharePoint viewer they view or download from. A button looks identical and does none of it. */
ok('a file is a real link that opens SharePoint in a new tab',
  /<a class="lib-row" href="https:\/\/x\.sharepoint\.com\/handbook\.pdf" target="_blank" rel="noopener"/.test(html),
  html.slice(html.indexOf('handbook') - 200, html.indexOf('handbook') + 120));
ok('no file row falls back to window.open', !/window\.open/.test(html));
ok('a folder still opens IN PLACE', /_libSpEnter\('wiki','F1'/.test(html));
ok('and a folder can also be opened in SharePoint, in its own tab',
  /<a class="lib-row-ext" href="https:\/\/x\.sharepoint\.com\/Policies" target="_blank" rel="noopener"/.test(html));
ok('a file with no SharePoint address is not a dead link',
  /lib-row-dead/.test(paint(st => { st.items = [{ id: 'N', name: 'orphan.pdf', file: {}, size: 1 }]; })));
ok('a file shows its size', /2\.3 MB/.test(html), api._libFmtSize(2411724));
ok('the toolbar is the standard one, not a hand-rolled filter',
  /<search id="lib-wiki-f">/.test(html) && /<period id="lib-wiki-period">/.test(html));

html = paint(st => { st.items = []; });
ok('an EMPTY folder says it is empty', /This folder is empty\./.test(html));

html = paint(st => { st.items = ROWS; api.setFilter('lib-wiki-f', 'leave'); });
ok('the name filter narrows the list', /Leave Form/.test(html) && !/Employee Handbook/.test(html));
ok('a filter that matches nothing says so, not "empty folder"',
  /Nothing matches that filter\./.test(paint(st => { st.items = ROWS; api.setFilter('lib-wiki-f', 'zzz'); })));

html = paint(st => { st.items = ROWS; api.setFilter('lib-wiki-kind', 'Folders only'); });
ok('the kind filter keeps folders only', /Policies/.test(html) && !/handbook\.pdf/i.test(html));
html = paint(st => { st.items = ROWS; api.setFilter('lib-wiki-kind', 'Files only'); });
ok('the kind filter keeps files only', !/_libSpEnter/.test(html) && /Employee Handbook/.test(html));

/* THIS TEST USED TO ASSERT THE BUG. With the period stub forced false it expected "Nothing
   matches that filter." over a fixture containing the FOLDER "Policies" — i.e. it asserted that
   picking a period deletes the sub-folders, and with them the only route into the sub-tree.
   A folder's own lastModifiedDateTime is not its contents'; judging it by the period is asking a
   question the value cannot answer. Files are filtered; folders stay. */
html = paint(st => { st.items = ROWS; api.setPeriod(false); });
ok('the period control filters the FILES', !/Employee Handbook/.test(html) && !/Leave Form/.test(html));
ok('the period control leaves the folders reachable', /Policies/.test(html));

/* Each failure names ITSELF. This is the assertion that matters most: all four used to be
   expressible as "no rows", and the reader could not tell which had happened. */
const STATES = [
  ['nolink', /No document library is linked yet/],
  ['nothost', /not a SharePoint address/],
  ['demo', /Demo mode/],
  ['nosession', /Sign in to Microsoft 365 to read the documents here/],
  ['graph 403', /SharePoint could not be reached/]
];
STATES.forEach(function (s) {
  const out = paint(st => { st.error = s[0]; });
  ok('"' + s[0] + '" explains itself', s[1].test(out), out.slice(0, 260));
  ok('"' + s[0] + '" is not shown as an empty folder', !/This folder is empty\./.test(out));
});
ok('only the fixable state offers the sign-in button',
  /_libSpConnect\(\)/.test(paint(st => { st.error = 'nosession'; })) &&
  !/_libSpConnect\(\)/.test(paint(st => { st.error = 'nolink'; })));
ok('a failed panel does not offer filters over nothing',
  !/<filterbar>/.test(paint(st => { st.error = 'nosession'; })));

/* A file name is SOMEBODY ELSE'S TEXT: anyone who can upload to the library chooses it, and
   SharePoint accepts both angle brackets and apostrophes in one. The apostrophe is the sharp
   case — the name is interpolated into a JS string inside an onclick attribute, so a bare quote
   ends that string and whatever follows is code. _tkEscA (which escapes & and " only) does not
   stop it, which is exactly how this shipped for an hour. */
html = paint(st => { st.items = [{ id: 'X', name: '<img src=x onerror=alert(1)>.pdf', file: {}, size: 10, webUrl: 'https://x.sharepoint.com/a' }]; });
ok('a file name cannot become markup', !/<img src=x/.test(html) && /&lt;img/.test(html));

/* Run the handler the way a browser would — decode the attribute's entities, then execute the
   JS in it — and watch for two opposite failures at once. `alert` here stands for anything the
   injected half of the name could reach: if the quote escaped the string, it RUNS. And the
   arguments have to arrive intact, because over-escaping is the other bug: "Q3 forecast's.xlsx"
   would then open the wrong folder, or none, and nobody would call that a security fix. */
html = paint(st => { st.items = [{ id: "F'X", name: "foo'+alert(1)+'.pdf", folder: { childCount: 0 }, webUrl: 'https://x.sharepoint.com/f' }]; });
(function () {
  const m = html.match(/onclick="(_libSpEnter[^"]*)"/);
  ok('the folder row carries an onclick at all', !!m, html.slice(html.indexOf('lib-row'), 400));
  if (!m) return;
  const decoded = m[1].replace(/&quot;/g, '"').replace(/&lt;/g, '<').replace(/&gt;/g, '>').replace(/&amp;/g, '&');
  let args = null, fired = false, broke = '';
  /* Caught, not thrown: an unescaped quote can also produce a handler that does not PARSE, and
     in a browser that is not an error anybody sees — the row simply does nothing when clicked.
     Reporting it as a named failure says which of the two happened. */
  try {
    new Function('_libSpEnter', 'alert', decoded)
      .call(null, function () { args = [].slice.call(arguments); }, function () { fired = true; });
  } catch (e) { broke = String(e && e.message); }
  ok('the handler the row emits is valid JavaScript', !broke, broke + '  ←  ' + decoded);
  ok('a quote in a file name cannot execute — the injected call never runs', !fired, decoded);
  ok('and the name still arrives at the handler unchanged',
    !!args && args[0] === 'wiki' && args[1] === "F'X" && args[2] === "foo'+alert(1)+'.pdf", JSON.stringify(args));
})();

/* A search across the library states its scope, so an eight-hit list of "Form.pdf" is usable. */
html = paint(st => {
  st.crumbs = [{ id: 'F1', name: 'Policies' }];
  st.found = { q: 'form', rows: [{ id: 'D2', name: 'Leave Form.docx', file: {}, size: 10, webUrl: 'https://x.sharepoint.com/leave.docx', parentReference: { path: '/drive/root:/Policies/HR' } }] };
});
ok('a whole-library search says that is what it searched', /Results across the whole library/.test(html));
ok('a search hit shows the folder it lives in', /Policies\/HR/.test(html));
ok('a search offers the way back to the folder', /Back to the folder/.test(html));

/* ── the board ──────────────────────────────────────────────────────────────── */
api.setPortal({
  library: [
    { label: 'IT Knowledge Page', url: '', desc: 'IT guides', icon: 'it' },
    { label: 'Training Hub', url: 'https://humileyvietnam.sharepoint.com/sites/TrainingHub', desc: 'Plans', icon: 'training' },
    { label: 'Wiki', url: 'view:wiki', desc: '', icon: 'wiki' }
  ], resources: []
});
const board = api.mount('library-root');
api.tkRenderLibrary();
const b = board.innerHTML;
ok('an external tile is a link that opens a new tab safely',
  /<a class="lib-tile" href="https:\/\/humileyvietnam\.sharepoint\.com\/sites\/TrainingHub" target="_blank" rel="noopener">/.test(b), b.slice(0, 500));
ok('an in-portal tile is a BUTTON, not a link out of the portal',
  /<button type="button" class="lib-tile lib-tile-in" onclick="showView\('wiki'/.test(b));
ok('a tile with no link is still shown, marked as needing one',
  /IT Knowledge Page/.test(b) && /lib-tile-off/.test(b) && /Add the link in HR Admin/.test(b));
ok('a live tile carries no "needs a link" note', (b.match(/lib-tile-off-lbl/g) || []).length === 1);

/* A tile URL comes from a settings form. `javascript:` is not a place. */
api.setPortal({ library: [{ label: 'Bad', url: 'javascript:alert(1)', desc: '', icon: 'link' }] });
api.tkRenderLibrary();
ok('a non-http tile URL is refused, not rendered as a link',
  !/javascript:/.test(board.innerHTML) && /lib-tile-off/.test(board.innerHTML), board.innerHTML.slice(0, 300));

/* ── the level HR puts on a tile ────────────────────────────────────────────── */
api.setPortal({
  library: [
    { label: 'Everyone thing', url: 'https://a.sharepoint.com/1', desc: '', icon: 'link', level: '' },
    { label: 'Approvers only', url: 'https://a.sharepoint.com/2', desc: '', icon: 'link', level: 'management' },
    { label: 'Wiki', url: 'view:wiki', desc: '', icon: 'wiki', level: 'management' },
    { label: 'Knowledge Hub', url: 'view:knowledge', desc: '', icon: 'knowledge', level: '' }
  ], resources: []
});
api.setLevel('manager');
api.tkRenderLibrary();
let lo = board.innerHTML;
ok('a tile above your level is not on your board', /Everyone thing/.test(lo) && !/Approvers only/.test(lo));
ok('and neither is the hub tile it gates', !/>Wiki</.test(lo) && /Knowledge Hub/.test(lo));
ok('the hub page refuses at the same level the tile does',
  api._libMayOpen('wiki') === false && api._libMayOpen('knowledge') === true);

api.setLevel('management');
api.tkRenderLibrary();
lo = board.innerHTML;
ok('at the level itself, both come back', /Approvers only/.test(lo) && />Wiki</.test(lo));
ok('and the page opens', api._libMayOpen('wiki') === true);

/* Blank is the default and must stay the LOOSEST answer. `_lvlRank` returns 1 for anything it does
   not recognise, so a level of "" or "sUpErUsEr" read naively becomes "staff and above" — which is
   nearly harmless — but the same fallback on a MISSING tile would be a rule nobody chose. */
api.setLevel('staff');
ok('an unrecognised level is not a lock',
  api._libMaySee({ level: 'sUpErUsEr' }) === true && api._libMaySee({ level: '' }) === true && api._libMaySee({}) === true);
api.setPortal({ library: [] });
ok('an empty board locks nobody out of a hub',
  api._libMayOpen('wiki') === true && api._libViewLevel('wiki') === '');

/* ── HR updating the files ──────────────────────────────────────────────────── */
api.setCanWrite(false);
html = paint(st => { st.items = ROWS; });
ok('an ordinary reader is offered no Upload button', !/_libUploadPick/.test(html));
ok('and no Replace on a file row', !/_libReplacePick/.test(html));

api.setCanWrite(true);
html = paint(st => { st.items = ROWS; });
ok('HR is offered Upload', /_libUploadPick\('wiki'\)/.test(html));
ok('HR is offered Replace on a FILE', /_libReplacePick\('wiki','D1'/.test(html));
ok('but not on a folder — a folder has no bytes to replace',
  (html.match(/_libReplacePick/g) || []).length === 2, String((html.match(/_libReplacePick/g) || []).length));
ok('Upload is not offered over a panel that failed to load',
  !/_libUploadPick/.test(paint(st => { st.error = 'nosession'; })));

/* Where a new file lands. "The folder you are in" is the whole promise of the button, and getting
   it wrong drops HR's handbook silently into the root of the library instead. */
(function () {
  const st = api._libState('wiki');
  st.drive = 'DRV'; st.baseRef = 'root'; st.rel = 'General/Policies'; st.crumbs = [];
  ok('at the root, an upload addresses the CONFIGURED folder, not the drive root',
    api._libUploadUrl('wiki', 'Handbook.pdf') ===
    'https://graph.microsoft.com/v1.0/drives/DRV/root:/General/Policies/Handbook.pdf',
    api._libUploadUrl('wiki', 'Handbook.pdf'));
  st.crumbs = [{ id: 'SUB1', name: 'HR' }];
  ok('inside a folder, it addresses THAT folder',
    api._libUploadUrl('wiki', 'Handbook.pdf') ===
    'https://graph.microsoft.com/v1.0/drives/DRV/items/SUB1:/Handbook.pdf',
    api._libUploadUrl('wiki', 'Handbook.pdf'));
  ok('a file name with a space or a quote is encoded, not concatenated',
    api._libUploadUrl('wiki', "Q3 forecast's.xlsx").indexOf("Q3%20forecast's.xlsx") > 0 ||
    api._libUploadUrl('wiki', "Q3 forecast's.xlsx").indexOf('Q3%20forecast%27s.xlsx') > 0,
    api._libUploadUrl('wiki', "Q3 forecast's.xlsx"));
  st.crumbs = [];
})();
api.setCanWrite(false);

/* The Graph host check, on its own. */
ok('only sharepoint.com is accepted as a library host',
  api._libIsSharePoint('https://humileyvietnam.sharepoint.com/sites/HRRP') === true &&
  api._libIsSharePoint('https://evil.example.com/sites/HRRP') === false &&
  api._libIsSharePoint('https://notsharepoint.com/x') === false &&
  api._libIsSharePoint('') === false);

/* ── the document bar: General + one tab per department ─────────────────────────
   Driven, not inspected. The rendering is the easy half; the work is in resolving what a tab
   MEANS — find the folder of that name, or use the address HR gave it, or say plainly that the
   department has no folder yet. None of that runs without something to fetch from, which is why
   this section has a fake drive behind it. */
(async function () {
  const el = api.mount('lib-docs-wiki');
  api.setDepts(['Engineering', 'Factory', 'Sales & Tender']);
  api.setCanWrite(false);
  /* Set explicitly, because an earlier section leaves _userLevel on 'staff' and the department
     rule would then correctly hide every tab — a green suite testing the wrong thing. */
  api.setLevel('management');
  api.setMyDept('');
  const ROOT = [
    { id: 'FE', name: 'Engineering', folder: { childCount: 3 }, webUrl: 'https://a.sharepoint.com/E' },
    { id: 'FP', name: 'Company Policies', folder: { childCount: 9 }, webUrl: 'https://a.sharepoint.com/P' },
    { id: 'R1', name: 'Employee Handbook.pdf', file: {}, size: 100, webUrl: 'https://a.sharepoint.com/h.pdf' }
  ];
  api.setDrive({ DRV: { root: ROOT, FE: [{ id: 'E1', name: 'Design Standard.pdf', file: {}, size: 10, webUrl: 'https://a.sharepoint.com/e1' }] } },
    () => ({ driveId: 'DRV', baseRef: 'root', projRel: '' }));

  /* Pull the text out of one class of element. Written as an exec loop rather than String.match,
     because match(/…/g) drops the capture groups and hands back whole matches — which is how the
     first version of this reported every row with a trailing "<" and counted the .tabs CONTAINER
     as a tab. An instrument that lies about what it measured is worse than no instrument. */
  const grab = (cls) => {
    const out = [], re = new RegExp('class="' + cls + '"[^>]*>([^<]*)<', 'g');
    let m;
    while ((m = re.exec(el.innerHTML))) out.push(m[1].replace(/&amp;/g, '&'));
    return out;
  };
  const names = () => grab('lib-row-name');
  const tabs = () => grab('tab(?: active)?');

  /* There is no General tab. Every document reaches a reader through a department, and files
     left loose at the root are not shown at all — untouched in SharePoint, simply not presented
     as a place. The risk in removing it is landing somebody nowhere, so what the bar opens ON
     matters as much as what it contains. */
  api._libTab('wiki', '');
  await new Promise(r => setTimeout(r, 0));
  ok('the bar is one tab per department, with no General',
    tabs().join('|') === 'Engineering|Factory|Sales & Tender', tabs().join('|'));
  ok('the root of the library is never listed',
    names().indexOf('Employee Handbook.pdf') < 0 && names().indexOf('Company Policies') < 0, names().join('|'));
  ok('an unset tab lands on a department rather than nowhere',
    api._libState('wiki').tab === 'Engineering', String(api._libState('wiki').tab));

  /* Whose department it lands on is the point: for most of the company the documents they came
     for are their own, and landing anywhere else makes them choose before they can read. */
  api.setMyDept('Factory');
  api._libState('wiki').tab = '';
  api._libTab('wiki', '');
  await new Promise(r => setTimeout(r, 0));
  ok('...and specifically on the reader\'s OWN department when they have one',
    api._libState('wiki').tab === 'Factory', String(api._libState('wiki').tab));
  api.setMyDept('');

  api._libTab('wiki', 'Engineering');
  await new Promise(r => setTimeout(r, 0));
  ok('a department tab opens the folder of that name', names().join('|') === 'Design Standard.pdf', names().join('|'));
  ok('and the department is the root of the trail, named once',
    /lib-crumb[^>]*>Engineering</.test(el.innerHTML) && !/Library root/.test(el.innerHTML),
    (el.innerHTML.match(/<div class="lib-crumbs">.*?<\/div>/) || [''])[0]);

  api._libTab('wiki', 'Factory');
  await new Promise(r => setTimeout(r, 0));
  ok('a department with no folder says exactly that', /No documents folder for Factory/.test(el.innerHTML));
  ok('...and does not pretend the folder is empty', !/This folder is empty/.test(el.innerHTML));
  ok('...and offers no Create button to somebody who cannot write', !/_libMakeDeptFolder/.test(el.innerHTML));

  api.setCanWrite(true);
  api._libTab('wiki', 'Factory');
  await new Promise(r => setTimeout(r, 0));
  ok('HR is offered the folder that is missing', /_libMakeDeptFolder\('wiki','Factory'\)/.test(el.innerHTML));

  /* A department whose documents live on its own SharePoint site. The override has to WIN, and it
     has to be looked up per hub — the same department's policies and its training material are
     different documents in different libraries. */
  api.setPortal({ deptDocs: [{ hub: 'wiki', dept: 'Factory', url: 'https://other.sharepoint.com/sites/Factory' }] });
  let asked = null;
  api.setDrive({ OTHER: { root: [{ id: 'X1', name: 'Line 2 SOP.pdf', file: {}, size: 10, webUrl: 'https://o/x1' }] } },
    (base) => { asked = base; return { driveId: 'OTHER', baseRef: 'root', projRel: '' }; });
  api._libTab('wiki', 'Factory');
  await new Promise(r => setTimeout(r, 0));
  ok('a department address overrides the folder', names().join('|') === 'Line 2 SOP.pdf', names().join('|'));
  ok('...and it is the address that was resolved', asked === 'https://other.sharepoint.com/sites/Factory', String(asked));
  ok('the override is per hub, not global',
    api._libDeptUrl('wiki', 'Factory') !== '' && api._libDeptUrl('knowledge', 'Factory') === '');
  ok('a department nobody overrode is unaffected', api._libDeptUrl('wiki', 'Engineering') === '');

  /* ── who sees which department ────────────────────────────────────────────────
     General to everyone; your own department always; every other one from Contributor up except
     the Board's; all of it from Approver up — where this portal already puts a Director. */
  api.setPortal({ deptDocs: [], deptTabs: [{ dept: 'Board Management (BM)', board: true }, { dept: 'Quality Management System (QMS)', board: false }] });
  api.setDepts(['Engineering', 'Factory']);

  ok('a department with nobody assigned to it still gets a tab',
    api._libDeptTabs().indexOf('Quality Management System (QMS)') >= 0, api._libDeptTabs().join('|'));

  api.setLevel('staff'); api.setMyDept('Factory');
  ok('an ordinary employee sees General and their OWN department only',
    api._libVisibleDepts().join('|') === 'Factory', api._libVisibleDepts().join('|'));
  ok('...and not another department', api._libDeptAllowed('Engineering') === false);
  ok('...and not the Board', api._libDeptAllowed('Board Management (BM)') === false);

  api.setLevel('manager'); api.setMyDept('Factory');
  ok('a Contributor sees every department except the Board',
    api._libVisibleDepts().join('|') === 'Engineering|Factory|Quality Management System (QMS)',
    api._libVisibleDepts().join('|'));
  ok('...the Board specifically', api._libDeptAllowed('Board Management (BM)') === false);

  api.setLevel('management'); api.setMyDept('Factory');
  ok('an Approver — where a Director title lands — sees all of it',
    api._libDeptAllowed('Board Management (BM)') === true && api._libVisibleDepts().length === 4,
    api._libVisibleDepts().join('|'));
  api.setLevel('admin');
  ok('and so does an Admin', api._libDeptAllowed('Board Management (BM)') === true);

  /* Somebody ON the Board department keeps their own department whatever their level — the rule
     is "your own, always", and a Board member on Contributor must not lose their own documents. */
  api.setLevel('staff'); api.setMyDept('Board Management (BM)');
  ok('a member of the Board department still sees it', api._libDeptAllowed('Board Management (BM)') === true);

  /* A tab nobody was offered must not open by another route either. */
  api.setLevel('staff'); api.setMyDept('Factory');
  const before = api._libState('wiki').tab;
  api._libTab('wiki', 'Engineering');
  ok('and a department that is not offered cannot be opened anyway',
    api._libState('wiki').tab === before, String(api._libState('wiki').tab));

  /* With no General tab there is no way to reach the root at all, which is what makes the Board
     folder unreachable rather than merely unlisted. The old design had to filter it out of
     General by hand; removing the tab removes the whole class of leak — but only if nothing
     still routes there, which is what this checks. */
  api.setDrive({ DRV: { root: [
    { id: 'FB', name: 'Board Management (BM)', folder: { childCount: 2 }, webUrl: 'https://a/b' },
    { id: 'FE', name: 'Engineering', folder: { childCount: 2 }, webUrl: 'https://a/e' },
    { id: 'R1', name: 'Handbook.pdf', file: {}, size: 10, webUrl: 'https://a/h' }
  ], FE: [{ id: 'E9', name: 'Spec.pdf', file: {}, size: 10, webUrl: 'https://a/e9' }] } },
    () => ({ driveId: 'DRV', baseRef: 'root', projRel: '' }));
  api.setLevel('manager'); api.setMyDept('Engineering');
  api._libState('wiki').tab = '';
  api._libTab('wiki', '');
  await new Promise(r => setTimeout(r, 0));
  ok('an empty tab request lands in a department, never at the root',
    api._libState('wiki').tab === 'Engineering' && names().join('|') === 'Spec.pdf', names().join('|'));
  ok('...so the loose root files are not on screen', names().indexOf('Handbook.pdf') < 0, names().join('|'));
  ok('...and neither is the Board folder', names().indexOf('Board Management (BM)') < 0, names().join('|'));

  /* Nobody's department, and nothing they may see: the honest answer is about the ACCOUNT, not
     about the library — "this folder is empty" would be a claim about the company's documents. */
  api.setLevel('staff'); api.setMyDept('');
  api._libState('wiki').tab = '';
  api._libTab('wiki', '');
  await new Promise(r => setTimeout(r, 0));
  ok('an account with no department is told that, not shown an empty folder',
    /No department documents for your account yet/.test(el.innerHTML) && !/This folder is empty/.test(el.innerHTML),
    el.innerHTML.slice(el.innerHTML.indexOf('lib-note'), el.innerHTML.indexOf('lib-note') + 260));
  ok('...and is pointed at HR, who can fix it', /Ask HR to set your department/.test(el.innerHTML));
  ok('...and gets no tab bar to choose from', !/class="tabs"/.test(el.innerHTML));
  api.setLevel('management');

  /* ── the token path that broke in production ──────────────────────────────────
     Two real errors, both from the same cause: the silent renewal is blocked by Safari's
     third-party-cookie rules, and the popup fallback opened after an await so the browser
     refused it (empty_window_error: window.open returned null). The library must ask for a
     RECONNECT instead — and never open a popup of its own accord. */
  api.setSilentOk(false);
  api._libTab('wiki', '');
  await new Promise(r => setTimeout(r, 0));
  ok('a token that cannot renew silently asks the reader to reconnect',
    /Your Microsoft session needs renewing/.test(el.innerHTML), el.innerHTML.slice(0, 300));
  ok('...and offers the redirect, which is the route Safari allows',
    /_libReconnect\(\)/.test(el.innerHTML));
  ok('...and never claims SharePoint was unreachable',
    !/SharePoint could not be reached/.test(el.innerHTML));
  ok('...and no popup is opened without a click', api.redirected() === false);
  api._libReconnect();
  ok('pressing Reconnect is what starts the redirect', api.redirected() === true);
  api.setSilentOk(true);

  /* ── the two views ────────────────────────────────────────────────────────────
     A register of forms reads best as a list and a folder of drawings as cards, and the same
     library is both depending on the folder. The risk in offering two views is that they drift:
     one gains a filter the other lacks, and the count above them agrees with neither. */
  api.setSilentOk(true);
  api.setLevel('management'); api.setMyDept('');
  api.setDepts(['Engineering']); api.setPortal({ deptTabs: [], deptDocs: [] });
  /* Inside a DEPARTMENT, not at the root — there is no root view any more, and a fixture that
     still used one would be testing a screen nobody can reach. */
  api.setDrive({ DRV: {
    root: [{ id: 'FE', name: 'Engineering', folder: { childCount: 3 }, webUrl: 'https://a/e' }],
    FE: [
      { id: 'F1', name: 'Policies', folder: { childCount: 4 }, webUrl: 'https://a/p', lastModifiedDateTime: '2026-08-01T09:00:00Z' },
      { id: 'D1', name: 'Employee Handbook.pdf', file: {}, size: 2411724, webUrl: 'https://a/h.pdf', lastModifiedDateTime: '2026-07-15T09:00:00Z' },
      { id: 'D2', name: 'Leave Form.docx', file: {}, size: 51200, webUrl: 'https://a/l.docx', lastModifiedDateTime: '2026-07-20T09:00:00Z' }
    ]
  } }, () => ({ driveId: 'DRV', baseRef: 'root', projRel: '' }));

  api._libSetView('wiki', 'list');
  api._libTab('wiki', 'Engineering');
  await new Promise(r => setTimeout(r, 0));
  const listNames = names();
  ok('the list view still lists everything', listNames.length === 3, listNames.join('|'));
  ok('the count beside the heading matches what is on screen',
    /id="lib-count-wiki">3 items</.test(el.innerHTML), (el.innerHTML.match(/lib-count-wiki">[^<]*/) || [''])[0]);

  api._libSetView('wiki', 'grid');
  const gridNames = grab('lib-doc-name');   // grab(), not a hand-rolled match: see its comment
  ok('the grid shows exactly the same items as the list',
    gridNames.sort().join('|') === listNames.slice().sort().join('|'), gridNames.join('|') + '  vs  ' + listNames.join('|'));
  ok('a file is still a real link in grid view',
    /<a class="lib-doc" href="https:\/\/a\/h\.pdf" target="_blank" rel="noopener"/.test(el.innerHTML));
  ok('a folder still opens in place in grid view', /_libSpEnter\('wiki','F1'/.test(el.innerHTML));
  ok('the view choice is remembered', api._libView('wiki') === 'grid');

  /* The filter is shared, so it cannot apply to one view and not the other. */
  api.setFilter('lib-wiki-f', 'leave');
  api._libPaintDocs('wiki');
  const gridFiltered = grab('lib-doc-name');
  ok('the filter applies in grid view too', gridFiltered.join('|') === 'Leave Form.docx', gridFiltered.join('|'));
  ok('and the count follows the filter', /id="lib-count-wiki">1 item</.test(el.innerHTML),
    (el.innerHTML.match(/lib-count-wiki">[^<]*/) || [''])[0]);
  api.setFilter('lib-wiki-f', '');
  api._libSetView('wiki', 'list');

  /* ── the masthead ─────────────────────────────────────────────────────────── */
  const hero = api._libHubHtml('wiki');
  ok('the masthead does not repeat the page title above it',
    hero.indexOf('<h2') < 0, hero.slice(0, 200));
  ok('...and still carries both ways out to SharePoint',
    (hero.match(/target="_blank"/g) || []).length === 2, hero);

  /* ── a course shows the progress it always carried ────────────────────────── */
  const kroot = api.mount('knowledge-root');
  api.setPortal({ learning: [
    { name: 'HSE Essentials', meta: 'Required', pct: 100, url: 'https://a/1' },
    { name: 'Project Management', meta: 'In progress', pct: 40, url: 'https://a/2' },
    { name: 'Business English', meta: 'Recommended', url: 'https://a/3' }
  ] });
  api.tkRenderKnowledge();
  ok('a course in progress shows how far it got', /width:40%/.test(kroot.innerHTML));
  ok('a finished course shows as finished', /width:100%/.test(kroot.innerHTML));
  /* 0% and "not tracked" are different claims, and a bar cannot make the second one. */
  ok('a course with no progress recorded gets no bar, not a 0% bar',
    (kroot.innerHTML.match(/lib-prog"/g) || []).length === 2,
    String((kroot.innerHTML.match(/lib-prog"/g) || []).length));

  /* ── getting back what the failure took ──────────────────────────────────────
     Reconnecting reloads the whole app, so without this it returns on the dashboard: the person
     who was three folders deep, hit an expired token and pressed the only button offered loses
     their place AND still has to walk back to find out whether it worked. Recovering the session
     is only half of recovering the failure.

     The saved position is also the one thing here that must NOT be trusted on the way back — it
     was written before the reload, and the level rules are re-read after it. */
  api.setSilentOk(true);
  api.setLevel('management'); api.setMyDept('');
  api.setDepts(['Engineering', 'Factory']);
  api.setPortal({ deptTabs: [{ dept: 'Board Management (BM)', board: true }], deptDocs: [], library: [] });
  api.setDrive({ DRV: {
    root: [{ id: 'FE', name: 'Engineering', folder: { childCount: 1 }, webUrl: 'https://a/e' }],
    FE: [{ id: 'SUB', name: 'Drawings', folder: { childCount: 1 }, webUrl: 'https://a/e/d' }],
    SUB: [{ id: 'D9', name: 'GA-101.pdf', file: {}, size: 10, webUrl: 'https://a/e/d/1' }]
  } }, () => ({ driveId: 'DRV', baseRef: 'root', projRel: '' }));

  api._libTab('wiki', 'Engineering');
  await new Promise(r => setTimeout(r, 0));
  api._libState('wiki').crumbs.push({ id: 'SUB', name: 'Drawings' });

  /* Through _libReconnect, NOT by calling _libRemember directly. Written the lazy way first, and
     deleting the _libRemember call from _libReconnect then broke nothing: the feature would have
     stopped working — reconnect, land on the dashboard — with the suite still green. The button
     is the only way a reader reaches this, so the button is what has to be driven. */
  delete api.session().tkLibReturn;
  api.setCurrentView('wiki');
  api._libReconnect();
  ok('pressing Reconnect remembers the hub, the tab and the folder first',
    /"hub":"wiki"/.test(api.session().tkLibReturn || '') &&
    /"tab":"Engineering"/.test(api.session().tkLibReturn || '') &&
    /"name":"Drawings"/.test(api.session().tkLibReturn || ''),
    String(api.session().tkLibReturn));
  ok('...and only then hands over to Microsoft', api.redirected() === true);

  api.setCurrentView('staff-dashboard');
  api._libState('wiki').tab = ''; api._libState('wiki').crumbs = [];
  const resumed = api._libResumeAfterReconnect();
  await new Promise(r => setTimeout(r, 0));
  ok('...and coming back reopens that hub', resumed === true && api.currentView() === 'wiki', api.currentView());
  ok('...on the department they were in', api._libState('wiki').tab === 'Engineering', String(api._libState('wiki').tab));
  ok('...and back down in the folder they were in',
    api._libState('wiki').crumbs.map(c => c.name).join('/') === 'Engineering/Drawings',
    api._libState('wiki').crumbs.map(c => c.name).join('/'));
  ok('...with that folder\'s documents actually loaded', names().join('|') === 'GA-101.pdf', names().join('|'));
  ok('the saved position is consumed, so a later reload does not jump again',
    !api.session().tkLibReturn && api._libResumeAfterReconnect() === false);

  /* The levels are re-read AFTER the reload, and they may have moved — or the position may have
     been written by an account that is no longer the one signed in. A crumb is a note about where
     somebody was, never a permission to be there. */
  api._libState('wiki').tab = 'Board Management (BM)';
  api._libRemember('wiki');
  api.setLevel('manager');            // Contributor: everything except the Board
  api._libState('wiki').tab = '';
  api._libResumeAfterReconnect();
  await new Promise(r => setTimeout(r, 0));
  /* It used to drop to General. There is no General now, so it must drop to a department this
     reader MAY open — landing on the Board tab would be the bug, and landing nowhere would be a
     different one. */
  ok('a remembered department the reader may no longer open drops to one they can',
    api._libState('wiki').tab !== 'Board Management (BM)' && api._libDeptAllowed(api._libState('wiki').tab),
    String(api._libState('wiki').tab));

  api.setPortal({ library: [{ label: 'Wiki', url: 'view:wiki', level: 'admin' }] });
  api._libState('wiki').tab = '';
  api._libRemember('wiki');
  api.setLevel('staff');
  api.setCurrentView('staff-dashboard');
  ok('and a hub the reader may no longer open is not reopened at all',
    api._libResumeAfterReconnect() === false && api.currentView() === 'staff-dashboard');
  api.setPortal({ library: [] });

  /* Nothing saved, or nonsense saved, must be silent — this runs on every single boot. */
  ok('an ordinary boot resumes nothing', api._libResumeAfterReconnect() === false);
  api.session().tkLibReturn = '{not json';
  ok('unreadable saved state is dropped, not guessed at', api._libResumeAfterReconnect() === false);
  api.session().tkLibReturn = JSON.stringify({ hub: 'nosuchhub', tab: '', crumbs: [] });
  ok('a hub that no longer exists is ignored', api._libResumeAfterReconnect() === false);


  /* ══ A THOUSAND FILES ═══════════════════════════════════════════════════════════════════
     Everything below is about a folder nobody could open comfortably before. The assertions
     count NODES and CALLS, never milliseconds: an idle CI runner hides a regression a phone
     will not, and this repo has already shipped a 4-second page that CI called green. */
  const many = function (n, mk) {
    const out = [];
    for (let i = 0; i < n; i++) out.push(mk(i));
    return out;
  };
  const BIG = many(400, i => ({
    id: 'B' + i, name: 'Drawing-' + (i + 1) + '.pdf', file: {}, size: 1000 + i,
    webUrl: 'https://x.sharepoint.com/b' + i,
    lastModifiedDateTime: '2026-0' + (1 + (i % 9)) + '-01T00:00:00Z'
  }));

  let h = paint(st => { st.items = BIG; });
  const rendered = (h.match(/class="lib-row-name"/g) || []).length;
  ok('a 400-file folder puts 150 rows in the DOM, not 400', rendered === 150, 'rendered ' + rendered);
  /* Assert the FOOTER, not just the digits: "150 / 400" also appears in the count chip, so an
     assertion on the text alone passed with the whole footer deleted — a list that simply stops
     at 150 with no way to see the rest. A mutant found this; the number was never the claim. */
  ok('...and offers the rest rather than just stopping',
    /class="lib-more"/.test(h) && /_libMore\('wiki'\)/.test(h) && /150 \/ 400/.test(h));
  ok('the count chip states both numbers too', /id="lib-count-wiki">150 \/ 400 items</.test(h),
    (h.match(/lib-count-wiki">[^<]*/) || [''])[0]);

  /* The reason this is a button and not a virtual scroller: it has state you can assert. */
  const elBig = api.el('lib-docs-wiki');
  api._libMore('wiki');
  const afterMore = (elBig.innerHTML.match(/class="lib-row-name"/g) || []).length;
  ok('Show more adds exactly one page', afterMore === 300, 'after ' + afterMore);

  /* The subtle one. Miss a reset and a reader who pressed Show more six times in a big folder
     gets 900 rows of the next one painted the moment they change the filter. */
  /* The fixture has to be able to FAIL. 'Drawing-1.' matches 111 rows — under the cap whether or
     not it is reset — so the first version of this test passed with the reset removed. Filter to
     something matching all 400 while st.shown is 300: with the reset it renders 150, without it
     300. A mutant found this too. */
  api.setFilter('lib-wiki-f', 'Drawing-');            // matches all 400; st.shown is 300 from above
  api._libSpFilter_wiki();
  const filtered = (elBig.innerHTML.match(/class="lib-row-name"/g) || []).length;
  ok('changing the filter puts the cap back', filtered === 150, 'rendered ' + filtered);
  ok('and the filter box itself survived that repaint', /id="lib-wiki-f"/.test(elBig.innerHTML));
  api.setFilter('lib-wiki-f', '');

  /* THE CARET FIX CANNOT BE PROVEN IN THIS HARNESS — there is no real focus here, and a test
     that called document.activeElement would be measuring the stub. It was verified in a browser
     by node identity: the <input> survives a filter repaint as the SAME element, and is replaced
     by a full _libPaintDocs. What CAN be held here is the structure that makes it true, so a
     future edit cannot quietly point the filter back at the whole-card repaint. */
  {
    const body = src.slice(src.indexOf('function _libSpFilter_wiki'),
                           src.indexOf('function _libSpFilter_wiki') + 400);
    ok('the filter callbacks repaint the BODY, not the whole card',
      /_libPaintBody/.test(body) && !/_libPaintDocs/.test(body), body.slice(0, 160));
    const bh = src.slice(src.indexOf('function _libBodyHtml'), src.indexOf('function _libCountText'));
    ok('...and the body does not contain the filter toolbar it would destroy',
      !/_crmFiltSearch|_crmFiltBar/.test(bh));
  }

  /* AHU-10 before AHU-2 is wrong the moment a folder holds ten numbered drawings, and this
     company's folders are full of numbered drawings. */
  const NUM = [
    { id: 'n1', name: 'AHU-10.dwg', file: {}, size: 5, webUrl: 'https://x/1' },
    { id: 'n2', name: 'AHU-2.dwg', file: {}, size: 9, webUrl: 'https://x/2' },
    { id: 'n3', name: 'AHU-1.dwg', file: {}, size: 1, webUrl: 'https://x/3' }
  ];
  h = paint(st => { st.items = NUM; });
  ok('names sort in natural order', h.indexOf('AHU-2.dwg') < h.indexOf('AHU-10.dwg'));
  h = paint(st => { st.items = NUM; api.setFilter('lib-wiki-sort', 'Largest first'); });
  ok('largest first sorts by size, not by name', h.indexOf('AHU-2.dwg') < h.indexOf('AHU-1.dwg'));
  api.setFilter('lib-wiki-sort', '');

  /* ── the ceiling tells the truth even when the overflow lands on the LAST page ────────── */
  {
    const stp = api._libState('wiki');
    const page = (from, to, next) => ({
      ok: true, status: 200, text: async () => '',
      json: async () => {
        const v = [];
        for (let i = from; i < to; i++) v.push({ id: 'x' + i, name: 'f' + i + '.pdf', file: {} });
        return next ? { value: v, '@odata.nextLink': next } : { value: v };
      }
    });
    const pages = { u0: page(0, 4500, 'u1'), u1: page(4500, 5100, '') };
    api.setFetch(u => pages[String(u)] || pages.u0);
    const rows = await api._libGraphPage('u0', 'T', stp);
    api.setFetch(null);
    ok('the fetch ceiling caps the list at 5000', rows.length === 5000, 'got ' + rows.length);
    ok('AND SAYS SO when the overflow arrived in the final page', stp.partial === true,
      'partial=' + stp.partial + ' — 100 files would have been dropped in silence');
  }

  /* ── two overlapping listings: the loser must not paint ───────────────────────────────── */
  {
    api.setDrive({ DRV: {
      root: [{ id: 'ENG', name: 'Engineering', folder: { childCount: 2 } },
             { id: 'SAL', name: 'Sales', folder: { childCount: 1 } }],
      ENG: many(200, i => ({ id: 'e' + i, name: 'ENGINEERING-' + i + '.pdf', file: {}, size: 1, webUrl: 'https://x/e' + i })),
      SAL: [{ id: 's1', name: 'SALES-Quote.xlsx', file: {}, size: 1, webUrl: 'https://x/s1' }]
    } }, () => ({ driveId: 'DRV', baseRef: 'root', projRel: '' }));
    api.setDelay('ENG', 60);                  // Engineering is big and slow; Sales returns at once
    api.setDepts(['Engineering', 'Sales']);
    api.setLevel('admin');
    api.mount('lib-docs-wiki');
    const stw = api._libState('wiki');
    stw.crumbs = []; stw.items = null; stw.drive = null; stw.error = ''; stw.found = null;

    const slow = api._libTab('wiki', 'Engineering');   // clicked first
    await new Promise(r => setTimeout(r, 5));
    const fast = api._libTab('wiki', 'Sales');         // clicked a moment later
    await Promise.all([slow, fast]);
    await new Promise(r => setTimeout(r, 150));        // let Engineering's reply land

    const painted = api.el('lib-docs-wiki').innerHTML;
    ok('the department last clicked is the one showing', /SALES-Quote/.test(painted), 'tab=' + stw.tab);
    ok('a superseded listing does not paint its rows under the new heading',
      !/ENGINEERING-0\.pdf/.test(painted),
      'one thousand Engineering files under a highlighted Sales tab is what this prevents');
    ok('...and does not leave a false error banner either', !stw.error, 'error=' + stw.error);
  }


  /* ══ WHICH FOLDER A SEARCH LOOKS IN ═════════════════════════════════════════════════════
     The library is one folder per department and the search ignored that: every query went to
     the drive root, so somebody hunting "checklist" inside Engineering got Sales, HR and Board
     hits mixed in. These tests are about the ADDRESS ASKED, not the wording — the heading is
     downstream of it, and a heading that says "in this folder" over root results is the failure
     mode worth preventing. */
  {
    api.setDrive({ DRV: {
      root: [{ id: 'ENG', name: 'Engineering', folder: { childCount: 2 } }],
      ENG: [{ id: 'e1', name: 'Checklist.pdf', file: {}, size: 1, webUrl: 'https://x/e1' }],
      /* Four levels below Engineering. The point of the fixture: a search hit's folder is NOT a
         child of where the reader is standing, so a pushed crumb would name a path that does not
         exist. The crumbs are only drawn when the listing succeeds, so this folder has to be
         real. */
      DEEP: [{ id: 'd9', name: 'GA-Drawing.dwg', file: {}, size: 1, webUrl: 'https://x/d9' }]
    } }, () => ({ driveId: 'DRV', baseRef: 'root', projRel: '' }));
    api.setDepts(['Engineering']);
    api.setLevel('admin');
    api.setSearchRows([{ id: 'h1', name: 'Checklist.pdf', file: {}, size: 1,
                         webUrl: 'https://x/h1',
                         parentReference: { path: '/drive/root:/Engineering/2026/Project-14/Drawings' } }]);
    api.mount('lib-docs-wiki');
    await api._libTab('wiki', 'Engineering');

    // default — the folder the reader is standing in
    api.resetSearched();
    api.setFilter('lib-wiki-scope', '');
    api.setFilter('lib-wiki-q', 'checklist');
    await api._libSpSearch('wiki');
    ok('by default a search asks the folder the reader is in',
      /\/items\/ENG\/search/.test(api.searched()[0] || ''), api.searched()[0] || '(nothing asked)');
    ok('...and the heading says so', /Results in Engineering/.test(api.el('lib-docs-wiki').innerHTML));

    // the whole library, when asked for
    api.resetSearched();
    api.setFilter('lib-wiki-scope', 'The whole library');
    await api._libSpSearch('wiki');
    ok('choosing the whole library asks the drive root',
      /\/root\/search/.test(api.searched()[0] || ''), api.searched()[0] || '(nothing asked)');
    ok('...and the heading changes with it',
      /Results across the whole library/.test(api.el('lib-docs-wiki').innerHTML));

    /* The two must never disagree. A heading naming a folder over results fetched from root is
       worse than no heading: it is a false statement about where three hits came from. */
    ok('the heading and the address asked always agree',
      /root\/search/.test(api.searched()[0]) &&
      !/Results in /.test(api.el('lib-docs-wiki').innerHTML));

    // a leftover folder filter must not silently narrow a set of results from elsewhere
    api.setFilter('lib-wiki-scope', '');
    api.setFilter('lib-wiki-f', 'zzz-nothing-matches-this');
    await api._libSpSearch('wiki');
    ok('running a search clears the folder filter it would otherwise be narrowed by',
      api.getFilter('lib-wiki-f') === '', 'filter still ' + JSON.stringify(api.getFilter('lib-wiki-f')));
    ok('...so the hit is actually shown', /Checklist\.pdf/.test(api.el('lib-docs-wiki').innerHTML));

    /* Opening a hit's folder cannot push a crumb: the hit lives four levels down, and a trail
       reading "Engineering / Drawings" names a path that does not exist. */
    await api._libSpEnter('wiki', 'DEEP', 'Drawings');
    const crumbs = api._libState('wiki').crumbs;
    ok('a folder opened from a search keeps the real root and elides the rest',
      crumbs.length === 2 && crumbs[0].id === 'ENG' && crumbs[1].jumped === true,
      JSON.stringify(crumbs));
    /* Scoped to the TRAIL, not the panel. The first version of this tested the whole innerHTML
       for an ellipsis — which the "Search files…" placeholder and "Loading…" also contain, so
       deleting the gap entirely still passed. Two mutants lived on that. The crumbs div holds no
       nested div, so slicing to the first </div> is the whole trail and nothing else. */
    const html = api.el('lib-docs-wiki').innerHTML;
    const ci = html.indexOf('class="lib-crumbs"');
    const trail = ci < 0 ? '' : html.slice(ci, html.indexOf('</div>', ci));
    ok('the trail shows a gap rather than inventing the levels between',
      /…/.test(trail), trail.slice(0, 200));
    /* The gap must stay a <span>. As a <button> it is a control that cannot go anywhere — nothing
       here knows what those folders are called. */
    ok('and that gap is not a button that goes nowhere',
      /<span[^>]*>…<\/span>/.test(trail) && (trail.match(/<button/g) || []).length === 2,
      trail.slice(0, 200));
  }

  console.log('\n  ' + passed + ' passed, ' + failed + ' failed');
  process.exit(failed ? 1 : 0);
})();
