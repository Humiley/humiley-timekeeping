/* The "employees with no department" panel, driven against the code that ships.
 *
 * It exists because a blank department stopped being harmless: the document bar is organised by
 * department, so a person whose record names none sees no documents at all. The panel's whole job
 * is to tell HR who that reaches — and its whole danger is filling something in on its own.
 *
 * Which department somebody works in is a fact about the company that no code can infer, and a
 * wrong guess silently decides which documents a person may read. So the sharpest assertion here
 * is a negative one: nothing is ever saved for a row the user did not choose.
 *
 *   node tests/dept_gap_panel.js
 */
const fs = require('fs');
const path = require('path');

const src = fs.readFileSync(path.join(__dirname, '..', 'templates', 'index.html'), 'utf8');
const START = '/* ── employees with no department ──';
const END = 'function tkRenderDatabase() {';
const i = src.indexOf(START), j = src.indexOf(END);
if (i < 0 || j < 0 || j <= i) {
  console.error('Could not find the department-gap block in templates/index.html.\n' +
    'If the marker was renamed, update START/END here — do NOT delete this test.');
  process.exit(2);
}

const PRELUDE = `
  const DOM = {};
  const document = { getElementById: function (id) { return DOM[id] || null; } };
  let _DEMO_EMPLOYEES = [];
  let _userLevel = 'management';
  const _LEVELS = ['staff', 'manager', 'management', 'editor', 'admin'];
  function _lvlRank(l){ const i = _LEVELS.indexOf(l); return i < 0 ? 1 : i + 1; }
  function _requireLevel(min){ return _lvlRank(_userLevel) >= _lvlRank(min); }
  function _crmEsc(s){ return String(s == null ? '' : s).replace(/&/g,'&amp;').replace(/</g,'&lt;').replace(/>/g,'&gt;'); }
  function _tkEscA(s){ return String(s == null ? '' : s).replace(/&/g,'&amp;').replace(/"/g,'&quot;'); }
  function _libArg(s){ return String(s == null ? '' : s).replace(/\\\\/g,'\\\\\\\\').replace(/'/g,"\\\\'").replace(/&/g,'&amp;').replace(/"/g,'&quot;'); }
  function _libSameName(a,b){ return String(a==null?'':a).trim().toLowerCase() === String(b==null?'':b).trim().toLowerCase(); }
  function _t(s){ return String(s == null ? '' : s); }
  function _errMsg(e){ return String((e && e.message) || e); }
  function toast(m, k){ TOASTS.push({ m: String(m), k: k || '' }); }
  function tkAudit(){}
  function tkAllDepts(){ return DEPTS; }
  function tkRenderDatabase(){ RENDERS++; _deptGapPaint(); }
  let DEPTS = [], TOASTS = [], RENDERS = 0, PATCHED = [], FAIL_FOR = null;
  async function tkApi(url, opts){
    const id = url.split('/').pop();
    if (FAIL_FOR && id === FAIL_FOR) throw new Error('Manager access required.');
    PATCHED.push({ id: id, body: opts.body, method: opts.method });
    return { ok: true };
  }
`;

const api = {};
new Function(PRELUDE + src.slice(i, j) + `
  Object.assign(this, {
    _deptGapRows: _deptGapRows,
    _deptFillMayEdit: _deptFillMayEdit,
    _deptGapPaint: _deptGapPaint,
    tkDeptFillToggle: tkDeptFillToggle,
    tkDeptFillSet: tkDeptFillSet,
    tkDeptFillAll: tkDeptFillAll,
    tkDeptFillSave: tkDeptFillSave,
    state: function(){ return _deptFill; },
    setEmps: function (e) { _DEMO_EMPLOYEES = e; },
    setDepts: function (d) { DEPTS = d; },
    setLevel: function (l) { _userLevel = l; },
    failFor: function (id) { FAIL_FOR = id; },
    patched: function () { return PATCHED; },
    toasts: function () { return TOASTS; },
    resetIo: function () { PATCHED = []; TOASTS = []; FAIL_FOR = null; },
    mount: function (id) { DOM[id] = { innerHTML: '' }; return DOM[id]; }
  });
`).call(api);

let failed = 0, passed = 0;
function ok(what, cond, extra) {
  if (cond) { passed++; console.log('  ok    ' + what); }
  else { failed++; console.log('  FAIL  ' + what + (extra ? '\n        ' + extra : '')); }
}

const EMPS = [
  { id: 'E1', name: 'Nguyen Van A', title: 'Engineer', email: 'a@x.com', dept: '', status: 'Active' },
  { id: 'E2', name: 'Tran Thi B', title: 'Officer', email: 'b@x.com', dept: 'Factory (FAC)', status: 'Active' },
  { id: 'E3', name: 'Le Van C', title: 'Fitter', email: 'c@x.com', dept: '   ', status: 'Active' },
  { id: 'E4', name: 'Pham Thi D', title: 'Leaver', email: 'd@x.com', dept: '', status: 'Inactive' }
];
api.setEmps(EMPS);
api.setDepts(['Engineering Consultant (ENG)', 'Factory (FAC)', 'Quality Management System (QMS)']);
const el = api.mount('dept-gap-root');

/* ── who is missing ──────────────────────────────────────────────────────────── */
ok('the gap is the ACTIVE employees with no department',
  api._deptGapRows().map(e => e.id).join('|') === 'E1|E3', api._deptGapRows().map(e => e.id).join('|'));
ok('whitespace is not a department', api._deptGapRows().some(e => e.id === 'E3'));
ok('somebody who has one is not in the gap', !api._deptGapRows().some(e => e.id === 'E2'));
/* A leaver with no department is not a problem to solve — chasing HR about somebody who left is
   noise, and noise is how a panel like this gets ignored. */
ok('a leaver is not counted', !api._deptGapRows().some(e => e.id === 'E4'));

api._deptGapPaint();
ok('the panel says how many, and why it matters',
  /2 active employees have no department/.test(el.innerHTML) && /sees none of them/.test(el.innerHTML),
  el.innerHTML.slice(0, 300));
ok('...and names them only once opened', el.innerHTML.indexOf('Nguyen Van A') < 0);
api.tkDeptFillToggle();
ok('opening it lists the people', /Nguyen Van A/.test(el.innerHTML) && /Le Van C/.test(el.innerHTML));
ok('...with every real department offered', /Quality Management System \(QMS\)/.test(el.innerHTML));

/* ── the level the SERVER enforces ───────────────────────────────────────────── */
api.setLevel('manager');
api._deptGapPaint();
ok('a Contributor still sees the gap — knowing what is missing is not a privilege',
  /2 active employees have no department/.test(el.innerHTML));
ok('...but is not offered the editor the API would refuse', !/tkDeptFillToggle/.test(el.innerHTML));
api.setLevel('management');
api._deptGapPaint();

/* ── saving ──────────────────────────────────────────────────────────────────── */
(async function () {
  /* NOTHING is saved for a row nobody chose. This is the assertion that matters: the panel must
     never invent a department, because the wrong one silently decides what a person can read. */
  api.resetIo();
  await api.tkDeptFillSave();
  ok('with nothing chosen it saves nothing at all', api.patched().length === 0);
  ok('...and says so rather than reporting a success', /at least one person/.test((api.toasts()[0] || {}).m || ''),
    JSON.stringify(api.toasts()));

  api.resetIo();
  api.tkDeptFillSet('E1', { value: 'Engineering Consultant (ENG)' });
  await api.tkDeptFillSave();
  ok('one chosen row saves exactly one employee', api.patched().length === 1, JSON.stringify(api.patched()));
  ok('...the right one, with the right department',
    api.patched()[0].id === 'E1' && api.patched()[0].body.dept === 'Engineering Consultant (ENG)',
    JSON.stringify(api.patched()[0]));
  ok('...and never touches the row left blank', !api.patched().some(x => x.id === 'E3'));
  ok('...and the person leaves the gap once saved', !api._deptGapRows().some(e => e.id === 'E1'));

  /* "Set every row at once" is a convenience, not a default: it only fills rows because a human
     picked a value from it. */
  api.resetIo();
  api.tkDeptFillAll({ value: 'Factory (FAC)' });
  await api.tkDeptFillSave();
  ok('set-all fills the remaining rows', api.patched().length === 1 && api.patched()[0].id === 'E3',
    JSON.stringify(api.patched()));
  /* The "— choose —" placeholder is a no-op, not a clear: picking it by accident must not wipe
     selections somebody has just made by hand. Asserted properly — an earlier draft of this line
     ended in `|| true`, which is a check that cannot fail. */
  api.tkDeptFillSet('E3', { value: 'Factory (FAC)' });
  api.tkDeptFillAll({ value: '' });
  ok('...and the blank placeholder changes nothing', api.state().sel['E3'] === 'Factory (FAC)',
    JSON.stringify(api.state().sel));

  /* A partial failure has to name the person. "1 failed" sends HR to look through the whole list. */
  api.setEmps([{ id: 'E9', name: 'Vu Van E', title: 'Tech', email: 'e@x.com', dept: '', status: 'Active' }]);
  api.resetIo();
  api.failFor('E9');
  api.tkDeptFillSet('E9', { value: 'Factory (FAC)' });
  await api.tkDeptFillSave();
  const errs = api.toasts().filter(t => t.k === 'error');
  ok('a failed row is reported BY NAME', errs.length === 1 && /Vu Van E/.test(errs[0].m), JSON.stringify(api.toasts()));
  ok('...and the person stays in the gap', api._deptGapRows().some(e => e.id === 'E9'));

  console.log('\n  ' + passed + ' passed, ' + failed + ' failed');
  process.exit(failed ? 1 : 0);
})();
