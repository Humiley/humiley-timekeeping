/* The SharePoint write paths are unreachable, and have to stay that way.
 *
 * Before the standalone Python backend, leave and attendance were written to SharePoint lists. Both
 * call sites are still in the page, each behind `if (true) { ...; return; }` with the comment
 * "always use standalone Python backend (SharePoint removed)".
 *
 * They are harmless while nothing reaches them, and they are NOT deleted here: removing them means
 * unwrapping an `if (true)` and everything after a `return` inside a 4 MB single-file app, which is
 * control-flow surgery for no functional gain. What is worth preventing is somebody tidying up the
 * `if (true)` — it reads like a pointless always-true condition, and deleting it is the obvious
 * "cleanup". That would make the SharePoint code live again, against a SharePoint that is no longer
 * configured:
 *
 *   - a leave request would be POSTed to a list nobody reads, with Status 'Pending', while the
 *     portal recorded nothing — and the user would be told it was submitted;
 *   - a check-in would be written to Attendance_Records instead of the portal.
 *
 * Both fail silently in the direction that looks like success, which is why a comment is not enough.
 *
 *   node tests/sharepoint_paths_stay_dead.js
 */
const fs = require('fs');
const path = require('path');

const src = fs.readFileSync(path.join(__dirname, '..', 'templates', 'index.html'), 'utf8');

let pass = 0, fail = 0;
function t(name, fn) {
  try { fn(); console.log('  ok    ' + name); pass++; }
  catch (e) { console.log('  FAIL  ' + name + '\n        ' + e.message); fail++; }
}

/* Is `call` positioned after a guard that returns unconditionally before it? */
function guardedBefore(callNeedle) {
  const at = src.indexOf(callNeedle);
  if (at < 0) return { found: false };
  const before = src.slice(0, at);
  const guard = before.lastIndexOf('if (true) {');
  if (guard < 0) return { found: true, guarded: false };
  const ret = before.indexOf('return;', guard);
  return { found: true, guarded: ret > guard, guardAt: guard };
}

console.log('\nthe SharePoint writes sit behind an unconditional guard');
[['leave submission', "spPost('Leave_Requests'"],
 ['check-in', "spGet('Approved_Locations')"]
].forEach(([label, needle]) => t(label, () => {
  const r = guardedBefore(needle);
  if (!r.found) return;   // deleted outright is a fine outcome — nothing to guard
  if (!r.guarded) {
    throw new Error('the SharePoint ' + label + ' path is reachable again. It writes to a ' +
      'SharePoint that is no longer configured and reports success either way — the portal ' +
      'records nothing. Delete the path, do not un-guard it.');
  }
}));

t('the guards still say why they are there', () => {
  const n = (src.match(/always use standalone Python backend \(SharePoint removed\)/g) || []).length;
  if (n < 2) {
    throw new Error('expected both `if (true)` guards to carry the explanation of what they hold ' +
      'back; found ' + n + '. Without it the condition reads as dead weight and gets tidied away.');
  }
});

t('no NEW SharePoint list is being written', () => {
  /* Counting call sites was the wrong instrument: the regex also matches the three function
     DEFINITIONS and the explanatory comment beside the leave fix, so the number moves for reasons
     that are not integrations. Which LISTS are addressed is the fact worth pinning — a new name
     here is a new integration against a backend that is gone. */
  const lists = [...new Set(
    [...src.matchAll(/\bsp(?:Get|Post|Patch)\(\s*'([A-Za-z_]+)'/g)].map(m => m[1])
  )].sort();
  const known = ['Approved_Locations', 'Attendance_Records', 'Leave_Requests'];
  const extra = lists.filter(l => known.indexOf(l) < 0);
  if (extra.length) {
    throw new Error('new SharePoint list(s) being addressed: ' + extra.join(', ') +
      '. SharePoint is not the backend any more — a write there reaches nothing and reports ' +
      'success, and the portal records none of it.');
  }
});

console.log('\n' + pass + ' passed, ' + fail + ' failed');
process.exit(fail ? 1 : 0);
