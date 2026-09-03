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
  let _msalApp = {}, _account = {};   // signed in to Microsoft; whether they may WRITE is CAN_WRITE
  let _userLevel = 'manager';
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
  /* A fake SharePoint drive, so the tab bar can actually be DRIVEN. Everything above this line
     tests rendering from a state somebody set by hand; the department tabs are different — the
     work is in the resolving (find the folder of that name, or fall back, or say there is none),
     and none of that runs unless there is something to fetch from. */
  let DRIVE = null, RESOLVE = null, POSTED = [];
  function _pmSpToken(){ if (!DRIVE) throw new Error('no token in this harness'); return Promise.resolve('T'); }
  function _pmSpResolve(base){
    if (!DRIVE) throw new Error('no graph in this harness');
    return Promise.resolve(RESOLVE(base));
  }
  async function fetch(url, opts) {
    const u = String(url);
    if (opts && opts.method === 'POST') {          // create folder
      POSTED.push({ url: u, body: JSON.parse(opts.body) });
      return { ok: true, status: 201, json: async () => ({ id: 'NEW' }), text: async () => '' };
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
    return { ok: true, status: 200, json: async () => ({ value: rows }), text: async () => '' };
  }
  function _pmSpCtx(){ return { mode: 'path' }; }
  const _GRAPH = 'https://graph.microsoft.com/v1.0';
  function msalLogin(){}
  function tkConfirm(){ return Promise.resolve(false); }
  function showView(){}
`;

const api = {};
new Function(PRELUDE + src.slice(i, j) + `
  Object.assign(this, {
    _libIsSharePoint: _libIsSharePoint,
    _libFmtSize: _libFmtSize,
    _libState: _libState,
    _libPaintDocs: _libPaintDocs,
    _libTilesHtml: _libTilesHtml,
    tkRenderLibrary: tkRenderLibrary,
    _libMaySee: _libMaySee,
    _libMayOpen: _libMayOpen,
    _libViewLevel: _libViewLevel,
    _libUploadUrl: _libUploadUrl,
    setPortal: function (p) { PORTAL = Object.assign(PORTAL, p); },
    setPeriod: function (v) { PERIOD_OK = v; },
    setFilter: function (k, v) { _crmLF[k] = v; },
    setLevel: function (l) { _userLevel = l; },
    setCanWrite: function (v) { CAN_WRITE = v; },
    mount: function (id) { DOM[id] = { innerHTML: '' }; return DOM[id]; },
    _libTab: _libTab,
    _libSpList: _libSpList,
    _libTabBar: _libTabBar,
    _libDeptUrl: _libDeptUrl,
    setDrive: function (d, resolve) { DRIVE = d; RESOLVE = resolve; POSTED = []; },
    posted: function () { return POSTED; },
    setDepts: function (d) { DEPTS = d; }
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
  api.setFilter('lib-wiki-f', ''); api.setFilter('lib-wiki-kind', '');
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

html = paint(st => { st.items = ROWS; api.setPeriod(false); });
ok('the period control actually filters', /Nothing matches that filter\./.test(html));

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

  api._libTab('wiki', '');
  await new Promise(r => setTimeout(r, 0));
  ok('the bar is General plus every real department',
    tabs().join('|') === 'General|Engineering|Factory|Sales & Tender', tabs().join('|'));
  ok('General lists the company-wide documents', names().indexOf('Employee Handbook.pdf') >= 0);
  ok('...and a folder that is NOT a department stays on General', names().indexOf('Company Policies') >= 0);
  ok('...but a department folder is not listed twice — it has its own tab',
    names().indexOf('Engineering') < 0, names().join('|'));

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

  console.log('\n  ' + passed + ' passed, ' + failed + ' failed');
  process.exit(failed ? 1 : 0);
})();
