/* The export engines warm up after sign-in, never on the login screen.
 *
 * Measured on production: xlsx 309 KB, jsPDF 113 KB, pdf.js 87 KB, the PDF font 55 KB and
 * html2canvas 45 KB — 609 KB — all started at DOMContentLoaded while the login overlay was still
 * up and TK.token was null. That is 609 KB fetched for a person who cannot reach a single feature
 * that uses them, who may never sign in on this device, and whose sign-in redirect was competing
 * with them for bandwidth on the way in.
 *
 * The warm-up itself is a good idea and none of its reasoning changes: an export that has to fetch
 * 609 KB when you click it feels broken, and a real session gets the engines long before anyone
 * opens one. What changed is when it is allowed to start.
 *
 * THE THING THAT MUST NOT BREAK: tkEnsureExportLibs() is the on-demand path that every export
 * already awaits, and it must keep working whether or not the warm-up ever ran. Gating the warm-up
 * is a scheduling change; it must never become a dependency. This file checks both halves.
 *
 *   node tests/export_libs_wait_for_a_session.js
 */
const fs = require('fs');
const path = require('path');

const src = fs.readFileSync(path.join(__dirname, '..', 'templates', 'index.html'), 'utf8');

let pass = 0, fail = 0;
const ok = (n, c, extra) => {
  if (c) { pass++; console.log('  ok    ' + n); }
  else { fail++; console.log('  FAIL  ' + n + (extra ? '\n        ' + extra : '')); }
};

/* Lift the whole prefetch IIFE and run it against a stand-in window, so these assertions are about
   what the code DOES, not what it looks like. */
const at = src.indexOf('  const HEAVY = [');
if (at < 0) { console.error('could not find the export-libs block — update the marker, do NOT delete this test.'); process.exit(2); }
const end = src.indexOf('})();', at);
const BLOCK = src.slice(at, end);

function run({ token = null, saveData = false } = {}) {
  const store = {};
  if (token) store['tk_token'] = token;
  const appended = [];
  const loadEvents = [];
  const idle = [];
  const timers = [];
  const listeners = {};
  const win = {
    localStorage: { getItem: k => (k in store ? store[k] : null), setItem: (k, v) => { store[k] = v; } },
    sessionStorage: { getItem: () => null },
    navigator: { connection: { saveData } },
    requestIdleCallback: (fn) => idle.push(fn),
    addEventListener: (ev, fn) => { (listeners[ev] = listeners[ev] || []).push(fn); if (ev === 'load') loadEvents.push(fn); },
    removeEventListener: () => {},
    setTimeout: (fn, ms) => { timers.push({ fn, ms }); return timers.length; },
    Promise,
  };
  const doc = {
    head: { appendChild: (el) => { appended.push(el.src); setTimeout0(el); } },
    createElement: () => ({ set src(v) { this._src = v; }, get src() { return this._src; } }),
  };
  function setTimeout0() {}
  const fn = new Function('window', 'document', 'localStorage', 'sessionStorage', 'navigator',
                          'requestIdleCallback', 'setTimeout', 'Promise',
                          BLOCK + '\n; return { win: window };');
  fn(win, doc, win.localStorage, win.sessionStorage, win.navigator,
     win.requestIdleCallback, win.setTimeout, Promise);
  return { win, appended, loadEvents, idle, timers, listeners, fireLoad: () => loadEvents.forEach(f => f()) };
}

// ══ 1. logged out: nothing starts ══════════════════════════════════════════════════════════════
console.log('\nOn the login screen, nothing is fetched\n');
{
  const r = run({ token: null });
  r.fireLoad();
  ok('no idle prefetch is scheduled while there is no session',
     r.idle.length === 0 && r.timers.length === 0,
     'idle=' + r.idle.length + ' timers=' + r.timers.length +
     ' — 609 KB of export engines for someone who has not signed in');
  ok('and nothing was appended to the document',
     r.appended.length === 0, 'appended: ' + r.appended.join(', '));
  /* The save-data branch registers interaction listeners. Logged out it must not even do that — a
     click on the Sign in button would otherwise pull all 609 KB during the redirect. */
  const rs = run({ token: null, saveData: true });
  rs.fireLoad();
  ok('not even the metered-connection interaction listeners',
     !(rs.listeners.pointerdown || rs.listeners.keydown),
     'a pointerdown listener on the login screen fires on the Sign in button itself');
}

// ══ 2. signed in: the warm-up behaves exactly as it did ════════════════════════════════════════
console.log('\nWith a session, the warm-up is unchanged\n');
{
  const r = run({ token: 'abc' });
  r.fireLoad();
  ok('a returning user still gets the idle prefetch', r.idle.length === 1,
     'idle callbacks scheduled: ' + r.idle.length);

  const rs = run({ token: 'abc', saveData: true });
  rs.fireLoad();
  ok('and a metered connection still defers to first interaction',
     !!(rs.listeners.pointerdown && rs.listeners.keydown) && rs.timers.length === 1,
     'listeners=' + Object.keys(rs.listeners).join(',') + ' timers=' + rs.timers.length);
}

// ══ 3. a first sign-in does not have to wait for the next page load ════════════════════════════
console.log('\nA fresh sign-in warms them without a reload\n');
{
  const r = run({ token: null });
  r.fireLoad();
  ok('the scheduler is exposed for the login path to call',
     typeof r.win.tkWarmExportLibs === 'function');
  r.win.tkWarmExportLibs();
  ok('and calling it starts the warm-up', r.idle.length === 1,
     'idle=' + r.idle.length);
  r.win.tkWarmExportLibs();
  r.win.tkWarmExportLibs();
  ok('calling it again is harmless', r.idle.length === 1,
     'scheduled ' + r.idle.length + ' times — a re-login must not stack duplicate prefetches');

  /* Both login functions have to call it, or one of the two ways in leaves a first-time user cold
     until they reload. */
  const logins = ['async function tkLoginDemo(role) {', 'async function tkLoginM365(accessToken) {'];
  logins.forEach(sig => {
    const i = src.indexOf(sig);
    const body = i < 0 ? '' : src.slice(i, src.indexOf('\n}', i));
    ok(sig.replace(/async function | *\(.*/g, '') + ' warms the engines after storing the token',
       /tkWarmExportLibs\(\)/.test(body),
       'body:\n' + body.slice(0, 300));
  });
}

// ══ 4. the on-demand path is untouched ═════════════════════════════════════════════════════════
console.log('\nAn export still works whether or not the warm-up ran\n');
{
  const r = run({ token: null });
  r.fireLoad();
  ok('tkEnsureExportLibs is still exposed with no session',
     typeof r.win.tkEnsureExportLibs === 'function',
     'this is the path every export awaits — gating the WARM-UP must never gate the LOAD');
  const p = r.win.tkEnsureExportLibs();
  ok('and calling it loads the engines immediately, logged out or not',
     r.appended.length === 5,
     'appended ' + r.appended.length + ' scripts: ' + r.appended.join(', '));
  ok('it still returns a promise to await',
     p && typeof p.then === 'function',
     'a caller doing `await tkEnsureExportLibs()` on a promise-less return continues with nothing ' +
     'loaded — that is the bug that silently dropped attached PDFs on mobile');
}

console.log('\n  ' + pass + ' passed, ' + fail + ' failed\n');
process.exit(fail ? 1 : 0);
