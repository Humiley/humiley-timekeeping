/* What the boot path issues, and in what order.
 *
 * Sign-in was four serial round trips before the screen had any data: /api/config, then /api/me,
 * then four parallel calls, then /api/portal. Measured through a delay-injecting proxy with six
 * warm connections: 332 ms at 60 ms RTT, 727 ms at 150 ms, 1068 ms at 250 ms.
 *
 * /api/portal needs nothing from tkBootstrap — only TK.token — so it now overlaps instead of
 * queueing behind it. Two things make that safe, and both are asserted here because both are
 * invisible in a passing app:
 *
 *   · it must be issued AFTER the login. On the fresh demo path TK.token does not exist until
 *     tkLoginDemo resolves, and tkLoadPortal reads the token when it issues the fetch — so moving
 *     it one line too far up sends a request with `Bearer undefined`, which returns 401, which
 *     tkLoadPortal swallows. The portal flags then silently fall back for the whole session:
 *     canPay and canPublishDocs go undefined and the buttons they gate quietly disappear.
 *   · it must still be AWAITED before doLogin returns, or _applyRole runs against a half-loaded
 *     portal.
 *
 * The half deliberately NOT done is also pinned: issuing /api/config and the /api/me restore probe
 * together pins a token snapshot, and the session self-heal can swap the token underneath it —
 * destroying a freshly healed session and dropping the user on the login screen. If someone tries
 * it later, the assertion below is where they will find out why it was rejected.
 *
 *   node tests/boot_request_order.js
 */
const fs = require('fs');
const path = require('path');

const src = fs.readFileSync(path.join(__dirname, '..', 'templates', 'index.html'), 'utf8');

let pass = 0, fail = 0;
const ok = (n, c, extra) => {
  if (c) { pass++; console.log('  ok    ' + n); }
  else { fail++; console.log('  FAIL  ' + n + (extra ? '\n        ' + extra : '')); }
};

const i = src.indexOf('async function doLogin');
if (i < 0) {
  console.error('could not find doLogin — update the marker, do NOT delete this test.');
  process.exit(2);
}
const body = src.slice(i, src.indexOf('\nasync function ', i + 20));

console.log('\nThe portal fetch overlaps the bootstrap instead of queueing behind it\n');
{
  const iLogin = body.indexOf('await tkLoginDemo(role);');
  const iStart = body.indexOf('const _pPortal = tkLoadPortal();');
  const iBoot = body.indexOf('await tkBootstrap();');
  const iAwait = body.indexOf('await _pPortal;');

  ok('the portal fetch is started, not awaited in place', iStart > 0,
     'doLogin no longer starts /api/portal as its own step');
  ok('it starts before tkBootstrap is awaited', iStart > 0 && iBoot > 0 && iStart < iBoot,
     'started after the bootstrap it is meant to overlap, which is the serial version again');
  ok('but only after the login has established a token', iLogin > 0 && iStart > iLogin,
     'tkLoadPortal reads TK.token when it issues the fetch. Before the login resolves that is ' +
     'undefined, the request 401s, tkLoadPortal swallows it, and canPay / canPublishDocs stay ' +
     'undefined for the whole session — buttons vanish and nothing errors');
  ok('and it is still awaited before doLogin returns', iAwait > 0 && iAwait > iBoot,
     '_applyRole would otherwise run against a half-loaded portal');
}

console.log('\nAnd the auth probe is still strictly ordered\n');
{
  /* Not a style preference: see the header. If this ever becomes a Promise.all, the person doing it
     needs to have thought about the self-heal swapping TK.token mid-flight. */
  const auth = src.slice(src.indexOf('async function initAuth'));
  const head = auth.slice(0, 4000);
  ok('/api/config and the /api/me probe are not issued together',
     !/Promise\.all\(\[[^\]]*\/api\/config[^\]]*\/api\/me/.test(head),
     'the restore probe pins a token snapshot; the session self-heal can replace the token ' +
     'underneath it, which destroys a freshly healed session and shows the login screen. If this ' +
     'is being changed deliberately, prove the self-heal case first and then rewrite this test');
}

console.log('\n  ' + pass + ' passed, ' + fail + ' failed\n');
process.exit(fail ? 1 : 0);
