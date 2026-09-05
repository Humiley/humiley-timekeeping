/* Waiting for the sign-in code.
 *
 * The mail leaves the server in under a second; the rest is Exchange handing off, and Gmail will
 * sometimes hold a first message from a new sender or file it as spam. None of that is ours to
 * speed up — but everything a person needs WHILE waiting is, and none of it was there: the only
 * control on the code screen was "use another address", so a slow mail meant starting over.
 *
 * Two things this pins, both found by driving the screen rather than reading it:
 *   1. there is a resend, it counts down, and the countdown is armed when the code is REQUESTED;
 *   2. api() surfaces the server's `message`, not just `error`. A failed send answers
 *      {"ok": false, "message": …} carrying the one sentence that explains it, and reading only
 *      `error` showed "HTTP 502" instead — throwing away the reason on the exact path the
 *      synchronous sender was written to report honestly.
 */
const fs = require('fs');
const path = require('path');

const P = path.join(__dirname, '..', 'templates', 'dr_site.html');
const src = fs.readFileSync(P, 'utf8');

let bad = 0;
function want(cond, what) {
  if (!cond) { bad++; console.log('  MISS  ' + what); } else { console.log('  ok    ' + what); }
}

// ── 1. the client reads the server's reason ─────────────────────────────────────────────────────
const api = /if \(!r\.ok\) \{[\s\S]{0,200}?new Error\(([^)]*)\)/.exec(src);
want(!!api, 'api() still builds an Error from the response');
if (api) {
  want(/j\.error/.test(api[1]), 'api() reads j.error');
  want(/j\.message/.test(api[1]), 'api() reads j.message — a failed send explains itself there');
  want(api[1].indexOf('j.message') > api[1].indexOf('j.error'),
       'error wins over message when both are present');
}

// ── 2. the resend exists and is driven by a clock ───────────────────────────────────────────────
want(/id="resend"/.test(src), 'the code screen offers a resend');
want(/_resendAt/.test(src) && /_resendTick/.test(src), 'the resend is on a countdown');
want(/setInterval\(_resendTick/.test(src), 'the countdown actually ticks');
want(/b\.disabled = true;[\s\S]{0,120}\+ 's\)'/.test(src),
     'the button is disabled while the countdown runs');

// The clock has to start when the code was ASKED FOR. Armed on render instead, a mistyped code
// redraws the screen and silently restarts the wait — the person waits 45s again for a mail that
// was sent two minutes ago.
want(/if \(!_resendAt\) _resendAt = Date\.now\(\)/.test(src),
     'rendering the screen does not restart a countdown already running');
const codeReq = src.indexOf("api('/api/dr/site/code'");
want(codeReq > 0 && /_resendAt = Date\.now\(\)/.test(src.slice(codeReq, codeReq + 400)),
     'requesting a code arms the countdown');

// ── 3. the throttle answer comes from the server ────────────────────────────────────────────────
want(/r\.throttled/.test(src), 'a throttled resend shows the server\'s own wait, not a guess');

// ── 4. somewhere to look while waiting ──────────────────────────────────────────────────────────
want(/spam or junk folder/.test(src), 'the screen says where a slow mail usually is');
want(/thư rác/.test(src), 'and says it in Vietnamese too');

console.log(bad ? '\nFAIL ' + bad : '\nOK');
process.exit(bad ? 1 : 0);
