"""Assemble the standalone training demo: real UI + client-side API shim + baked data."""
import io, json

html = io.open('templates/index.html', encoding='utf-8').read()
data = io.open('demo_data.json', encoding='utf-8').read().replace('</', '<\\/')

SHIM = r'''<script>
/* ===== Humiley Portal — STANDALONE DEMO API shim (no server, localStorage-backed) ===== */
(function () {
  var EMBED = __DEMO_JSON__;
  var KEY = 'hml_demo_v3';
  var DS; try { DS = JSON.parse(localStorage.getItem(KEY)); } catch (e) {}
  if (!DS || !DS.employees) { DS = EMBED; save(); }
  try { sessionStorage.setItem('hum_role', 'manager'); } catch (e) {}  /* app auto-logs-in as admin on boot */
  function save() { try { localStorage.setItem(KEY, JSON.stringify(DS)); } catch (e) {} }
  window.hmlResetDemo = function () { try { localStorage.removeItem(KEY); } catch (e) {} location.reload(); };
  function J(b, s) { return new Response(JSON.stringify(b), { status: s || 200, headers: { 'Content-Type': 'application/json' } }); }
  function uid(p) { return p + '-' + Math.random().toString(36).slice(2, 9); }
  function demoUser(role) {
    var emps = DS.employees || []; var u;
    if (role === 'manager') u = emps.find(function (e) { return e.role === 'manager'; }) || emps[0];
    else u = emps.find(function (e) { return e.role !== 'manager'; }) || emps[0];
    u = Object.assign({}, u, { role: u && u.role || role });
    if (role === 'manager') u.level = 'admin';
    return u;
  }
  var realFetch = window.fetch ? window.fetch.bind(window) : null;
  window.fetch = function (input, init) {
    init = init || {};
    var url = (typeof input === 'string') ? input : (input && input.url) || '';
    var path = url.replace(/^https?:\/\/[^/]+/, '').split('?')[0];
    var qs = url.split('?')[1] || '';
    var method = (init.method || 'GET').toUpperCase();
    if (path.indexOf('/api/') !== 0) return realFetch ? realFetch(input, init) : Promise.reject('no fetch');
    var body = {}; try { body = init.body ? JSON.parse(init.body) : {}; } catch (e) {}
    var m;
    if (path === '/api/config') return Promise.resolve(J({ demo: true, clientId: '', tenantId: '', mapsKey: '' }));
    if (path === '/api/auth/demo') return Promise.resolve(J({ token: 'demo-' + (body.role || 'manager'), user: demoUser(body.role || 'manager') }));
    if (path === '/api/auth/m365') return Promise.resolve(J({ token: 'demo', user: demoUser('manager') }));
    if (path === '/api/me') return Promise.resolve(J(demoUser('manager')));
    if (path === '/api/portal') return Promise.resolve(J(DS.portal || { announcements: null, holidays: null, learning: null, resources: null }));
    if (path === '/api/employees') { if (method === 'POST') { var ne = Object.assign({ id: uid('emp') }, body); DS.employees.push(ne); save(); return Promise.resolve(J({ id: ne.id, employee: ne })); } return Promise.resolve(J({ employees: DS.employees })); }
    if (path === '/api/attendance') { var arr = DS.attendance || []; var eid = new URLSearchParams(qs).get('emp_id'); return Promise.resolve(J({ attendance: eid ? arr.filter(function (x) { return (x.emp_id || x.empId) == eid; }) : arr })); }
    if (path === '/api/attendance/checkin') { var rec = Object.assign({ id: uid('att') }, body); DS.attendance.push(rec); save(); return Promise.resolve(J({ id: rec.id })); }
    if (path === '/api/attendance/checkout') return Promise.resolve(J({ ok: true }));
    if (path === '/api/leave') { if (method === 'POST') { var nl = Object.assign({ id: uid('lv'), status: 'Pending' }, body); DS.leave.push(nl); save(); return Promise.resolve(J({ item: nl, id: nl.id })); } return Promise.resolve(J({ leave: DS.leave })); }
    if (path === '/api/zones') { if (method === 'POST') { var nz = Object.assign({ id: uid('z') }, body); DS.zones.push(nz); save(); return Promise.resolve(J({ id: nz.id })); } return Promise.resolve(J({ zones: DS.zones })); }
    if (m = path.match(/^\/api\/coll\/([^/]+)\/?(.*)$/)) {
      var name = m[1], iid = m[2]; DS.collections[name] = DS.collections[name] || []; var list = DS.collections[name];
      if (method === 'GET') return Promise.resolve(J({ items: list }));
      if (method === 'POST') { var it = Object.assign({ id: uid(name.slice(0, 3)) }, body); list.push(it); save(); return Promise.resolve(J({ item: it })); }
      if (method === 'PATCH') { var i = list.findIndex(function (x) { return x.id === iid; }); var mg = Object.assign({}, i >= 0 ? list[i] : {}, body, { id: iid }); if (i >= 0) list[i] = mg; else list.push(mg); save(); return Promise.resolve(J({ item: mg })); }
      if (method === 'DELETE') { DS.collections[name] = list.filter(function (x) { return x.id !== iid; }); save(); return Promise.resolve(J({ ok: true })); }
    }
    if (m = path.match(/^\/api\/employees\/([^/]+)$/)) { var id = m[1], i = DS.employees.findIndex(function (e) { return e.id === id; }); if (method === 'PATCH' && i >= 0) { DS.employees[i] = Object.assign({}, DS.employees[i], body); save(); return Promise.resolve(J({ employee: DS.employees[i] })); } if (method === 'DELETE') { DS.employees = DS.employees.filter(function (e) { return e.id !== id; }); save(); return Promise.resolve(J({ ok: true })); } }
    if (m = path.match(/^\/api\/leave\/([^/]+)$/)) { var lid = m[1], i = DS.leave.findIndex(function (x) { return x.id === lid; }); if (i >= 0) { DS.leave[i] = Object.assign({}, DS.leave[i], body); save(); } return Promise.resolve(J({ ok: true, item: i >= 0 ? DS.leave[i] : null })); }
    if (m = path.match(/^\/api\/zones\/([^/]+)$/)) return Promise.resolve(J({ ok: true }));
    return Promise.resolve(J({ ok: true }));
  };
  function addBadge() {
    if (document.getElementById('hml-demo-badge')) return;
    try {
      var b = document.createElement('div');
      b.id = 'hml-demo-badge'; b.textContent = 'DEMO DATA · reset';
      b.title = 'Reset all demo data to the original sample';
      b.onclick = window.hmlResetDemo;
      b.style.cssText = 'position:fixed;bottom:10px;right:10px;z-index:2147483000;background:#205090;color:#fff;font:600 11px/1 -apple-system,sans-serif;padding:7px 11px;border-radius:8px;cursor:pointer;opacity:.9;box-shadow:0 2px 8px rgba(0,0,0,.25)';
      document.body.appendChild(b);
    } catch (e) {}
  }
  function loggedIn() { try { return typeof TK !== 'undefined' && TK.user && !!TK.user.name; } catch (e) { return false; } }
  function _ready(tries) {
    if (loggedIn()) { addBadge(); return; }                                   // app auto-logged-in via saved role
    if ((tries || 0) === 3 && typeof doLogin === 'function') { try { doLogin('manager'); } catch (e) {} }  // fallback
    if ((tries || 0) < 10) setTimeout(function () { _ready((tries || 0) + 1); }, 600); else addBadge();
  }
  window.addEventListener('load', function () { setTimeout(function () { _ready(0); }, 1000); });
})();
</script>
'''
shim = SHIM.replace('__DEMO_JSON__', data)

# inject the shim before the first CDN <script> so fetch is overridden before boot
anchor = '<script src="https://cdnjs.cloudflare.com/ajax/libs/html2canvas/1.4.1/html2canvas.min.js"></script>'
assert html.count(anchor) == 1, "anchor not found"
out = html.replace(anchor, shim + anchor, 1)
out = out.replace('<title>Humiley Group Inc. — People & Workplace Portal</title>',
                  '<title>Humiley Portal — DEMO (training)</title>')
io.open('Humiley-Portal-DEMO.html', 'w', encoding='utf-8').write(out)
print('wrote Humiley-Portal-DEMO.html (%d KB)' % (len(out.encode('utf-8')) // 1024))
