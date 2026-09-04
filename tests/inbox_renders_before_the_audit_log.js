/* The Approval Inbox showed shimmer bars and never the approvals behind them.
 *
 * Two independent faults, and it took both to produce a PERMANENT skeleton rather than a slow one:
 *
 *   1. tkRenderInbox awaited the WHOLE audit collection before drawing anything —
 *        if (!(_HR.audit && _HR.audit.length)) { await tkLoadColl('audit'); }
 *      — the entire append-only tamper-evident chain, every approval and signature and sign-in the
 *      company has recorded, to display sixty rows of it on a tab that starts hidden. Measured:
 *      11 KB at 500 rows, 111 KB at 5,000, 444 KB at 20,000, 1.33 MB and 459 ms of server time at
 *      60,000. It only ever grows. tkLoadColl gives up after _COLL_TIMEOUT_MS = 30,000.
 *
 *   2. _armManagerPoll re-runs tkRenderInbox every 30,000 ms while the inbox is open, and the first
 *      line of tkRenderInbox blanked the panel to a skeleton. THE SAME NUMBER. So a render that hit
 *      the audit timeout was wiped and restarted by the next tick before it could ever paint, for
 *      as long as the tab stayed open.
 *
 * Either alone is a slow inbox. Together they are an inbox that never loads, which is what was
 * reported. Both halves are pinned here because fixing one and not the other leaves the failure one
 * slow collection away from coming back.
 *
 *   node tests/inbox_renders_before_the_audit_log.js
 */
const fs = require('fs');
const path = require('path');

const src = fs.readFileSync(path.join(__dirname, '..', 'templates', 'index.html'), 'utf8');

let pass = 0, fail = 0;
const ok = (n, c, extra) => {
  if (c) { pass++; console.log('  ok    ' + n); }
  else { fail++; console.log('  FAIL  ' + n + (extra ? '\n        ' + extra : '')); }
};
const fnBody = (name) => {
  const re = new RegExp('^\\s*(?:async\\s+)?function\\s+' + name + '\\s*\\(', 'm');
  const m = re.exec(src);
  if (!m) { console.error('could not find ' + name + ' — update the marker, do NOT delete this test.'); process.exit(2); }
  const from = m.index;
  const next = src.slice(from + 10).search(/\n(?:async )?function [A-Za-z_$]/);
  return src.slice(from, next < 0 ? from + 8000 : from + 10 + next);
};
/* Comments stripped before any "is this call still here" check. The fix's own comment QUOTES the
   line it removed, in order to explain it — and a grep over the raw text read that explanation as
   the code coming back. This test failed on its own documentation before it could ever fail on a
   regression. */
const codeOf = (name) => fnBody(name).replace(/\/\*[\s\S]*?\*\//g, '').replace(/^\s*\/\/.*$/gm, '');

// ══ 1. the queue does not wait for the log ═════════════════════════════════════════════════════
console.log('\nThe pending queue draws without the audit log\n');
{
  const b = codeOf('tkRenderInbox');
  ok('the render still loads the five registers it shows',
     /await Promise\.all\(\[tkLoadColl\('claims'\)/.test(b));
  ok('and does NOT await the audit collection', !/await tkLoadColl\('audit'\)/.test(b),
     'the whole chain is back on the path to first paint — 1.33 MB at 60,000 rows, to show 60');
  ok('the audit panel is left for its own loader',
     /_inboxAuditLoaded\(\) \? _inboxAuditTable\(\) : tkSkeleton\(\)/.test(b));
}

// ══ 2. a background refresh cannot blank a rendered screen ═════════════════════════════════════
console.log('\nA poll tick cannot wipe an inbox that is already drawn\n');
{
  const b = codeOf('tkRenderInbox');
  ok('the skeleton is only painted into an EMPTY panel',
     /if \(!root\.innerHTML\.trim\(\)\) root\.innerHTML = tkSkeleton\(\);/.test(b),
     'an unconditional skeleton means every 30-second poll tick restarts the screen, and any ' +
     'render slower than the interval can never finish being displayed');

  /* The two intervals that collided. If either moves, the collision moves with it — the point is
     that a render must not be able to outlast the tick that restarts it. */
  const poll = /\}, \(window\.matchMedia && matchMedia\('\(max-width:820px\)'\)\.matches\) \? 60000 : 30000\);/.test(src);
  ok('the manager poll still runs on its 30s / 60s cadence', poll);
  ok('and a collection load can still take as long as that whole interval',
     /const _COLL_TIMEOUT_MS = 30000;/.test(src),
     'the timeout and the poll interval are the same number — which is exactly why the skeleton ' +
     'reset had to become conditional rather than the timeout being nudged');
}

// ══ 3. the audit tab loads on demand, once, and says so when it cannot ═════════════════════════
console.log('\nThe Activity Log loads when its tab is opened\n');
{
  ok('opening the tab triggers the load',
     /if \(tab === 'audit'\) \{ try \{ _inboxLoadAudit\(\); \} catch \(e\) \{\} \}/.test(codeOf('tkInboxTab')));

  const l = codeOf('_inboxLoadAudit');
  ok('it does not re-fetch a log it already has', /if \(!_inboxAuditLoaded\(\)\)/.test(l));
  /* Anchored to the guard directly above it, so the assignment has to be UNCONDITIONAL. Checking
     only that the text appears somewhere passes on `if (false) b2.innerHTML = ...`, which is exactly
     the failure this line exists to catch — a load that fails and leaves the shimmer up for ever.
     Mutation found that; the first version of this assertion could not see its own defect. */
  ok('it fills the panel whatever happened',
     /if \(!b2\) return;[^\n]*\n\s*b2\.innerHTML = _inboxAuditLoaded\(\)/.test(l),
     'the panel fill is guarded or has moved away from the early-return — a failed load that ' +
     'leaves the skeleton up is the same defect one level down');
  ok('and offers a Retry that really re-runs it', /onclick="_inboxLoadAudit\(\)"/.test(l));
  ok('it survives the tab being left mid-load',
     /const b2 = document\.getElementById\('inbox-audit-body'\); if \(!b2\) return;/.test(l));

  /* `_HR.audit && _HR.audit.length` calls a loaded-but-empty log "not loaded" and re-fetches it on
     every render — the old condition did exactly that. */
  ok('"loaded" means the array exists, not that it has rows',
     /function _inboxAuditLoaded\(\) \{ return Array\.isArray\(_HR\.audit\); \}/.test(src),
     'an empty audit log would otherwise be re-fetched for ever');
}

console.log('\n  ' + pass + ' passed, ' + fail + ' failed\n');
process.exit(fail ? 1 : 0);
