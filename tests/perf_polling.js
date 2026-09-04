/* What the app does when nobody is touching it.
 *
 * "The loading is slow" turned out to be four separate things, none of them the network:
 *
 *  1. tkBootstrap kicked off a background fetch of the WHOLE attendance history — the biggest and
 *     fastest-growing table here — and _armManagerPoll calls tkBootstrap every 30 seconds. So the
 *     one fetch that exists specifically to happen once ran forever. Measured at rest with no
 *     interaction: /api/attendance appeared 4x in 91s where every other endpoint appeared twice.
 *  2. tkLoadColl's fetch had no deadline. Callers paint a skeleton and await it, so a request the
 *     network accepts and never answers leaves the shimmer on screen for as long as the tab is
 *     open — no error, no Retry, nothing logged. That is what a Schedule tab full of skeleton
 *     bars is.
 *  3. Every focus change cost /api/config + /api/build, throttled only by _onAppResume's 3s
 *     app-switch guard. On a phone the on-screen keyboard flips focus.
 *  4. The manager poll fetched employees + attendance + leave + zones on every screen, while only
 *     five views draw any of it.
 *
 * These are behavioural tests: the real functions are lifted out of index.html and run against
 * fakes. Where a property is structural rather than behavioural (two lists that must agree) it is
 * read out of the source and COMPARED, never asserted twice by hand.
 *
 *   node tests/perf_polling.js
 */
const fs = require('fs');
const path = require('path');

const src = fs.readFileSync(path.join(__dirname, '..', 'templates', 'index.html'), 'utf8');

let pass = 0, fail = 0;
const ok = (n, c, extra) => {
  if (c) { pass++; console.log('  ok    ' + n); }
  else { fail++; console.log('  FAIL  ' + n + (extra ? '\n        ' + extra : '')); }
};
/* Lift one top-level declaration. Stops at the first of the four things that can start the next
   one — a `take` that only knew about `\nfunction ` once swallowed the declaration after it and an
   assertion then read the wrong body while still reporting green. */
const take = (mark, what) => {
  const i = src.indexOf(mark);
  if (i < 0) { console.error('Could not find ' + what + ' — update the marker, do NOT delete this test.'); process.exit(2); }
  const ends = ['\nfunction ', '\nasync function ', '\nconst ', '\nlet ']
    .map(e => src.indexOf(e, i + 10)).filter(x => x > 0);
  if (!ends.length) { console.error('Could not find the end of ' + what); process.exit(2); }
  return src.slice(i, Math.min.apply(null, ends));
};
const num = (decl, what) => {
  const m = src.match(new RegExp(decl + '\\s*=\\s*(\\d+)'));
  if (!m) { console.error('Could not read ' + what); process.exit(2); }
  return +m[1];
};
/* One whole top-level statement, matched by its opening text. `take` stops at the NEXT top-level
   declaration, which is right for a function body and wrong for a bare `let` — asked for the
   comment above `let _attHydratedFor` it returned the comment and nothing else, and the harness
   then built a module with no tkBootstrap in it. */
const line = (mark, what) => {
  const i = src.indexOf(mark);
  if (i < 0) { console.error('Could not find ' + what + ' — update the marker, do NOT delete this test.'); process.exit(2); }
  const j = src.indexOf('\n', i);
  const stmt = src.slice(i, j).replace(/\s*\/\/.*$/, '');     // a trailing line comment is not the statement
  if (j < 0 || !/;$/.test(stmt)) {
    console.error(what + ' is no longer a single statement: ' + JSON.stringify(src.slice(i, i + 120)));
    process.exit(2);
  }
  return stmt + '\n';
};

// ══ 1. the attendance history hydrates once, not every 30 seconds ══════════════════════════════
async function hydrateOnce() {
  console.log('\nThe whole attendance history is pulled once per account, not every poll tick\n');
  const calls = [];
  const API = new Function('calls',
    'let _DEMO_EMPLOYEES, _DEMO_ATTENDANCE, _DEMO_LEAVE, _DEMO_ZONES;\n' +
    'const _HR = { schedules: [{ id: 1 }] };\n' +
    'const TK = { user: { id: "u1" } };\n' +
    'const window = {};\n' +   // no requestIdleCallback -> the setTimeout branch
    'function setTimeout(fn) { fn(); return 0; }\n' +
    'function tkApi(p) {\n' +
    '  calls.push(p);\n' +
    '  if (p.indexOf("/api/employees") === 0) return Promise.resolve({ employees: [] });\n' +
    '  if (p.indexOf("/api/attendance") === 0) return Promise.resolve({ attendance: [] });\n' +
    '  if (p.indexOf("/api/leave") === 0) return Promise.resolve({ leave: [] });\n' +
    '  if (p.indexOf("/api/zones") === 0) return Promise.resolve({ zones: [] });\n' +
    '  return Promise.resolve({});\n' +
    '}\n' +
    'function _tkPaintUserAva(){} function _tkMergeAttendance(){}\n' +
    'function tkFillDeptSelects(){} function tkFillSchedSelects(){}\n' +
    'function tkLoadColl(){ return Promise.resolve([]); }\n' +
    line('let _attHydratedFor', 'the hydrate guard') +
    take('async function tkBootstrap(', 'tkBootstrap') +
    '\nreturn { tkBootstrap: tkBootstrap, who: function (v) { TK.user = { id: v }; } };')(calls);

  const full = () => calls.filter(p => p === '/api/attendance').length;      // no ?start= — the whole table
  const windowed = () => calls.filter(p => p.indexOf('/api/attendance?start=') === 0).length;

  await API.tkBootstrap();
  ok('the first boot pulls the whole history once', full() === 1, 'got ' + full());
  ok('and the recent window alongside it', windowed() === 1, 'got ' + windowed());

  await API.tkBootstrap();          // the 30s poll tick
  await API.tkBootstrap();          // and the next one
  ok('two more poll ticks do NOT pull it again', full() === 1,
     'got ' + full() + ' full-history fetches. This is the single largest repeated payload in ' +
     'the portal and it grows with every workday of every employee — unguarded it was re-fetched ' +
     'and re-parsed every 30s for as long as a manager left the tab open.');
  ok('while the recent window IS re-pulled every tick — that is where new punches land',
     windowed() === 3, 'got ' + windowed());

  API.who('u2');                    // the Admin view switcher changes identity without reloading
  await API.tkBootstrap();
  ok('a different account hydrates its own history', full() === 2,
     'attendance is scoped per user, so a bare boolean would leave the staff workspace believing ' +
     "the admin's history had already been fetched");
}

// ══ 2. a collection read that never answers fails, instead of hanging on a skeleton ════════════
async function stalledRead() {
  console.log('\nA stalled collection read fails instead of hanging the tab forever\n');
  const TIMEOUT = num('_COLL_TIMEOUT_MS', 'the collection timeout');
  ok('the timeout is generous enough for a real programme on 4G', TIMEOUT >= 20000,
     'got ' + TIMEOUT + 'ms — cutting a working request off would trade a hang for a lie');

  const timers = [];
  let aborted = false, toasted = '';
  const API = new Function('timers', 'onAbort', 'onToast',
    'const _HR = {}, _COLL_TS = {}, _COLL_ERR = {}, _COLL_INFLIGHT = {};\n' +
    'const TK = { token: "t" };\n' +
    'let _collErrAt = 0;\n' +
    /* The bare binding AND the window property, because the code tests one and constructs the
       other — ('AbortController' in window) ? new AbortController() : null. In a browser those are
       the same thing. Under node they are not: node has its own global AbortController, so a fake
       placed only on `window` was ignored and a REAL controller was constructed, whose abort this
       test could not see. It reported green on an assertion it was not making. */
    'function AbortController() { this.signal = {}; this.abort = onAbort; }\n' +
    'const window = { AbortController: AbortController };\n' +
    'function setTimeout(fn, ms) { timers.push({ fn: fn, ms: ms }); return timers.length; }\n' +
    'function clearTimeout(i) { if (timers[i - 1]) timers[i - 1].cleared = true; }\n' +
    'function toast(m) { onToast(m); }\n' +
    'function _t2(en, vn) { return en; }\n' +
    'function _tkSessionExpired(){}\n' +
    'let fetchReject = null;\n' +
    'function fetch() { return new Promise(function (_, rej) { fetchReject = rej; }); }\n' +   // never answers
    take('function _tkCollLoadFailed(', '_tkCollLoadFailed') +
    line('const _COLL_TTL', 'the freshness window') +
    line('const _COLL_TIMEOUT_MS', 'the read deadline') +
    take('async function tkLoadColl(', 'tkLoadColl') +
    '\nreturn { tkLoadColl: tkLoadColl, TS: _COLL_TS, ERR: _COLL_ERR, INFLIGHT: _COLL_INFLIGHT,' +
    ' rejectFetch: function (e) { fetchReject(e); } };')(
      timers, function () { aborted = true; }, function (m) { toasted = m; });

  const p = API.tkLoadColl('pm_detail');
  const armed = timers.filter(t => !t.cleared);
  ok('the read arms a deadline', armed.length === 1 && armed[0].ms === TIMEOUT,
     'timers: ' + JSON.stringify(timers.map(t => t.ms)));

  armed[0].fn();                                   // the deadline passes
  ok('which aborts the request rather than waiting on it forever', aborted === true);

  API.rejectFetch(Object.assign(new Error('The user aborted a request.'), { name: 'AbortError' }));

  await p;
  ok("the caller's await RESOLVES — it is not left pending", true);
  ok('the collection is not marked as loaded, so pmTab reports it failed',
     !API.TS['pm_detail'],
     'pmTab computes _failed as (need).filter(c => !_COLL_TS[c]); a timestamp here would make ' +
     'the tab render an empty register as though it were a real answer');
  ok('and the failure is not a 403, so pmTab takes the Retry branch and not the access notice',
     (API.ERR['pm_detail'] || {}).status !== 403 && !!API.ERR['pm_detail']);
  ok('the timeout is recorded as a timeout', (API.ERR['pm_detail'] || {}).timedOut === true);
  ok('the person is told the server did not answer, not that their connection is down',
     /did not answer in time/.test(toasted),
     'got ' + JSON.stringify(toasted) + ' — "check your connection" is the right advice for a ' +
     'dead network and the wrong advice for a request that is merely taking too long');
  ok('the in-flight entry is released, so pressing Retry really re-fetches',
     !API.INFLIGHT['pm_detail']);
}

// ══ 3. the update check does not fire on every focus change ═══════════════════════════════════
async function updThrottle() {
  console.log('\nA focus change no longer costs two requests\n');
  const EVERY = num('_UPD_CHECK_MS', 'the update-check throttle');
  let now = 1000000, hits = 0, heals = 0;
  const API = new Function('clock', 'onFetch', 'onHeal',
    'let _updReloading = false;\n' +
    'const window = { _APP_VERSION: "v1" };\n' +
    'const Date = { now: clock };\n' +
    'function _healStaleShell() { onHeal(); }\n' +          // this is the /api/build call
    'function fetch() { onFetch(); return Promise.resolve({ ok: true, json: function () { return Promise.resolve({}); } }); }\n' +
    line('let _lastUpdCheck', 'the last-check stamp') +
    line('const _UPD_CHECK_MS', 'the update-check throttle') +
    take('async function _checkForUpdate(', '_checkForUpdate') +
    '\nreturn { _checkForUpdate: _checkForUpdate };')(
      function () { return now; }, function () { hits++; }, function () { heals++; });

  await API._checkForUpdate();
  ok('the first check goes to the network', hits === 1);

  now += 3000; await API._checkForUpdate();     // _onAppResume's own guard is only 3s
  now += 3000; await API._checkForUpdate();
  now += 3000; await API._checkForUpdate();
  ok('three more resumes inside the window cost nothing', hits === 1,
     'got ' + hits + ' — on a phone the on-screen keyboard opening and closing flips focus, so ' +
     'typing a search term could spend half a dozen round-trips announcing nothing');
  ok('and the stale-shell check is throttled with it', heals === 1,
     'got ' + heals + ' /api/build calls — it runs inside _checkForUpdate, so leaving it outside ' +
     'the throttle would halve the saving and nothing else would show it');

  now += EVERY; await API._checkForUpdate();
  ok('once the window passes it checks again', hits === 2);

  await API._checkForUpdate(true);
  ok('and the 4-minute schedule can force past the throttle', hits === 3,
     'a resume check a minute ago must not push the scheduled one out by another four');
}

// ══ 4. the poll fetches what the screen shows ═════════════════════════════════════════════════
function pollScope() {
  console.log('\nThe 30s poll pulls the roster only where it is on screen\n');
  const poll = take('function _armManagerPoll(', '_armManagerPoll');

  ok('the full bootstrap is behind the live-view test',
     /const _live = _MGR_POLL_LIVE\.indexOf\(_currentView\) >= 0;/.test(poll) &&
     /if \(_live\) \{\s*\n\s*try \{ await tkBootstrap\(\); \}/.test(poll),
     'off those views all four responses were parsed and thrown away');
  ok('and off them the bell still gets fresh leave',
     /\} else \{\s*\n\s*try \{ const _lv = await tkApi\('\/api\/leave'\); _DEMO_LEAVE = _lv\.leave; \}/.test(poll),
     'tkUpdateNotifications reads _DEMO_LEAVE; dropping it would freeze the bell on every screen ' +
     'that is not one of the five');
  ok('the approval registers are still refreshed, so the inbox badge is live everywhere',
     /\['claims', 'travel', 'payments', 'jobs', 'padr'\]\.map\(c => tkLoadColl\(c\)/.test(poll));

  /* The two lists are read out of the source and compared. Writing the expected views out by hand
     here would just be a third copy to drift, and the failure mode being guarded against is
     precisely two copies disagreeing. */
  const declared = (src.match(/const _MGR_POLL_LIVE = \[([^\]]*)\]/) || [])[1];
  if (declared == null) { console.error('Could not find _MGR_POLL_LIVE'); process.exit(2); }
  const listed = declared.split(',').map(x => x.trim().replace(/^'|'$/g, '')).filter(Boolean).sort();
  if (!listed.length) { console.error('_MGR_POLL_LIVE parsed as empty'); process.exit(2); }

  const sw = poll.slice(poll.indexOf('const v = _currentView;'));
  const repainted = (sw.match(/v === '([a-z-]+)'/g) || []).map(x => x.slice("v === '".length, -1)).sort();

  ok('every view that repaints on a tick is one the tick fetches for',
     repainted.length > 0 && repainted.join(',') === listed.join(','),
     'repaints: ' + repainted.join(', ') + '\n        fetches for: ' + listed.join(', ') +
     '\n        A view that repaints but is missing from _MGR_POLL_LIVE would redraw itself from ' +
     'data this tick declined to fetch — a screen that has quietly stopped updating rather than a ' +
     'visible bug.');
}

(async () => {
  await hydrateOnce();
  await stalledRead();
  await updThrottle();
  pollScope();
  console.log('\n  ' + pass + ' passed, ' + fail + ' failed\n');
  process.exit(fail ? 1 : 0);
})();
