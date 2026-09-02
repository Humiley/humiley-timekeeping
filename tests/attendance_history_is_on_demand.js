/* Attendance history is fetched by the screens that read it, not by every sign-in.
 *
 * It used to hydrate in the background on every boot, for every account. Measured against the real
 * server at 40 staff x 250 days: 85,827 bytes on the wire, 3,748,910 bytes of JSON to parse and
 * hold, 77.1 ms of single-threaded server time — where employees, leave, zones and portal together
 * are 2,029 bytes and 4.6 ms. It grows by headcount x every workday and most sessions never read a
 * row of it.
 *
 * THE FAILURE THIS FILE EXISTS TO PREVENT is not the fetch coming back wrong. It is a screen that
 * reads _DEMO_ATTENDANCE without asking for history first: it renders perfectly, from the two-month
 * boot window, and simply shows less than it should. A chart with fewer bars. A report missing the
 * months before last. An export that quietly stops at the window. Nothing throws, nothing is empty,
 * and the number on the screen is wrong — which is the shape of defect this codebase has shipped
 * more than once.
 *
 * So every function that touches _DEMO_ATTENDANCE must either call _attEnsureHistory or be named
 * below with the reason it does not need to. Adding a reader and no guard fails this test.
 *
 *   node tests/attendance_history_is_on_demand.js
 */
const fs = require('fs');
const path = require('path');

const src = fs.readFileSync(path.join(__dirname, '..', 'templates', 'index.html'), 'utf8');

let pass = 0, fail = 0;
const ok = (n, c, extra) => {
  if (c) { pass++; console.log('  ok    ' + n); }
  else { fail++; console.log('  FAIL  ' + n + (extra ? '\n        ' + extra : '')); }
};

/* Functions that read attendance but genuinely cannot need anything older than the boot window.
   Each entry states the rule that makes it safe, and the rule is checked below — an exemption
   nobody can verify is just a way of turning the test off. */
const WINDOW_ONLY = {
  tkRenderZones:      { why: 'today only', proof: /r\.date === today/ },
  _tkMyOpenRow:       { why: 'today or yesterday, to find an open shift', proof: /r\.date === t \|\| r\.date === y/ },
  tkRenderDashboard:  { why: 'filters to today before using it', proof: /att\.filter\(r => r\.date === today\)/ },
  loadManagerView:    { why: "today's rows for the manager's own crew", proof: /r\.date === today && inTeam\(r\)/ },
  tkAmendAttendance:  { why: 'looks up one row by id, from a row already on screen', proof: /find\(r => r\.id === attId\)/ },
  _armManagerPoll:    { why: 'builds a change signature; it displays nothing and must stay cheap, ' +
                             'because it runs every 30 seconds', proof: /const sig = _currentView/ },
  _tkMergeAttendance: { why: 'this is the merge itself', proof: /_DEMO_ATTENDANCE = localExtra\.concat/ },
  tkBootstrap:        { why: 'assigns the boot window', proof: /att\.attendance\.map/ },
  tkCheckIn:          { why: 'unshifts the row it has just created', proof: /_DEMO_ATTENDANCE\.unshift/ },
  _commitCheckin:     { why: 'unshifts the row it has just created', proof: /_DEMO_ATTENDANCE\.unshift/ },
  doCheckout:         { why: "finds today's open row, which it wrote itself", proof: /&& !r\.out\)/ },
  tkOtDecide:         { why: 'looks up one row by id to invalidate that month of overtime',
                        proof: /find\(x => x\.id === attId\)/ },
};

// ── attribute every read to the function it sits in ────────────────────────────────────────────
const lines = src.split('\n');
const DECL = /^\s*(?:async\s+)?function\s+([A-Za-z_$][\w$]*)\s*\(/;
const readers = new Map();          // fn -> [line numbers]
let cur = null, declSeen = 0;
lines.forEach((l, i) => {
  const m = DECL.exec(l);
  if (m) cur = m[1];
  // The array's own declaration sits at top level, so the "last function seen" rule would blame
  // whichever function happens to precede it. It is not a reader.
  if (/^\s*let\s+_DEMO_ATTENDANCE\s*=/.test(l)) { declSeen++; return; }
  if (l.includes('_DEMO_ATTENDANCE') && cur) {
    if (!readers.has(cur)) readers.set(cur, []);
    readers.get(cur).push(i + 1);
  }
});

const fnBody = (name) => {
  const re = new RegExp('^\\s*(?:async\\s+)?function\\s+' + name.replace(/\$/g, '\\$') + '\\s*\\(', 'm');
  const m = re.exec(src);
  if (!m) return '';
  const from = m.index;
  const next = src.slice(from + 10).search(/\n(?:async )?function [A-Za-z_$]/);
  return src.slice(from, next < 0 ? from + 6000 : from + 10 + next);
};

console.log('\nEvery screen that reads attendance either asks for history or says why not\n');
ok('the declaration was found and skipped exactly once', declSeen === 1,
   'found ' + declSeen + ' declarations of _DEMO_ATTENDANCE; if this is 0 the skip pattern has ' +
   'stopped matching and a top-level statement is being blamed on whichever function precedes it');
ok('the scan found the readers at all', readers.size >= 15,
   'only ' + readers.size + ' functions matched — the attribution broke, and this file would then ' +
   'pass by examining nothing');

const missing = [];
for (const [fn, at] of readers) {
  if (WINDOW_ONLY[fn]) continue;
  if (!/_attEnsureHistory\(/.test(fnBody(fn))) missing.push(fn + ' (line ' + at[0] + ')');
}
ok('no reader is left without one', missing.length === 0,
   'these read _DEMO_ATTENDANCE, are not exempt, and never ask for history — they will render ' +
   'from the two-month boot window and silently show less than they should:\n        ' +
   missing.join('\n        '));

console.log('\nAnd every exemption states a rule that is actually in the code\n');
let checked = 0;
for (const [fn, rule] of Object.entries(WINDOW_ONLY)) {
  if (!readers.has(fn)) continue;             // renamed or gone; the reader scan above governs
  checked++;
  ok(fn + ' — ' + rule.why, rule.proof.test(fnBody(fn)),
     'the exemption claims "' + rule.why + '" but the code no longer matches ' + rule.proof +
     '. If the function changed, it may now need history: re-check it rather than editing ' +
     'the pattern to fit.');
}
ok('the exemptions were really checked, not skipped', checked >= 6,
   'only ' + checked + ' exemptions matched a reader; an allow-list nobody verifies is a way of ' +
   'turning this test off');

// ── the boot path itself ───────────────────────────────────────────────────────────────────────
console.log('\nAnd boot does not fetch it\n');
{
  const boot = fnBody('tkBootstrap');
  ok('boot still fetches the recent window', /\/api\/attendance\?start=' \+ _attStart/.test(boot));
  ok('boot does NOT fetch the whole table', !/tkApi\('\/api\/attendance'\)/.test(boot),
     'the unconditional hydrate is back on the sign-in path');
  ok('and nothing schedules one behind first paint',
     !/requestIdleCallback/.test(boot) || !/\/api\/attendance'\)/.test(boot),
     'a deferred hydrate is still a hydrate: every sign-in pays 85 KB and 77 ms of server time');
}

// ── the guard's own failure modes ──────────────────────────────────────────────────────────────
console.log('\nThe guard itself\n');
{
  const g = fnBody('_attEnsureHistory');
  ok('one flight, however many screens ask at once', /if \(!_attHistoryFlight\)/.test(g),
     'four charts on one screen would otherwise fetch the table four times');
  ok('it is keyed to the account, not a bare boolean', /_attHistoryFor === who/.test(g),
     'the Admin view switcher changes identity without reloading the page, so a boolean would ' +
     'leave the staff workspace reading the admin\'s history');
  /* Without this the re-invoked caller asks again, gets true again, and fetches for ever. */
  ok('a recent failure stops the retry loop', /_attHistoryFailedAt < 60000\) return false/.test(g),
     'on failure the callback re-invokes the screen, which calls this again — without the cooldown ' +
     'that is an infinite fetch loop, not a degraded screen');
  ok('and the caller is re-invoked whether it worked or not',
     /_attHistoryFlight\.then\(\(\) => \{ try \{ again\(\); \} catch/.test(g),
     'a screen that returned early and is never called back is a screen that never renders');
}

// ── and the guard actually behaves, not just reads correctly ──────────────────────────────────
/* Everything above is a source assertion, and a source assertion cannot tell a working state
   machine from a broken one. This runs the real function. */
console.log('\nRunning the real guard\n');
(async () => {
  // The real function body, given its own copy of the state the file declares beside it.
  const src2 = 'let _attHistoryFor = null, _attHistoryFlight = null, _attHistoryFailedAt = 0;\n' +
               fnBody('_attEnsureHistory') +
               '\nreturn { ensure: _attEnsureHistory, loaded: () => _attHistoryFor };';
  const mk = (api) => new Function('TK', 'tkApi', '_tkMergeAttendance', src2)(
    { user: { id: 'HML-001' } }, api, () => {});

  {   // one flight for many callers, and it stops asking once loaded
    let calls = 0;
    let resolve;
    const api = () => { calls++; return new Promise(r => { resolve = r; }); };
    const g = mk(api);
    const a = g.ensure(), b = g.ensure(), c = g.ensure();
    ok('three screens asking at once produce one fetch', calls === 1 && a && b && c,
       'calls=' + calls);
    resolve({ attendance: [] });
    await new Promise(r => setTimeout(r, 5));
    ok('and afterwards the guard stands aside', g.ensure() === false && calls === 1,
       'calls=' + calls + ' — a loaded history must not be re-fetched by the next screen');
  }

  {   // the failure path: the screen still renders, and it does not spin
    let calls = 0;
    const api = () => { calls++; return Promise.reject(new Error('offline')); };
    const g = mk(api);
    let reInvoked = 0;
    g.ensure(() => { reInvoked++; g.ensure(() => reInvoked++); });
    await new Promise(r => setTimeout(r, 20));
    ok('a failed fetch still calls the screen back', reInvoked >= 1,
       'the screen returned early and would never render');
    ok('and the screen does not fetch for ever', calls === 1,
       calls + ' fetches — the re-invoked caller asked again and got true again, which is an ' +
       'infinite loop on a flaky connection, not a degraded screen');
    ok('nothing was marked as loaded', g.loaded() === null,
       'a failed fetch must not claim the history arrived');
  }

  console.log('\n  ' + pass + ' passed, ' + fail + ' failed\n');
  process.exit(fail ? 1 : 0);
})();
