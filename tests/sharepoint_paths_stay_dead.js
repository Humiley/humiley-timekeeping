/* SharePoint is gone. Nothing may write to it again.
 *
 * Leave and attendance used to be written to SharePoint lists. When the standalone Python backend
 * arrived, those call sites were not removed — they were fenced off behind `if (true) { ...;
 * return; }` with a comment saying SharePoint had been removed, and left in the page.
 *
 * That was survivable but not stable. `if (true)` reads like a pointless always-true condition,
 * and deleting it is the obvious cleanup — which would have put the SharePoint code back in
 * service against a backend that no longer exists: a leave request POSTed to a list nobody reads
 * while the portal recorded nothing, a check-in written to Attendance_Records, and the user told
 * in both cases that it worked. Failing in the direction that looks like success.
 *
 * SharePoint is now decommissioned and the branches are deleted outright, along with spGet, spPost
 * and spPatch. This file changed with them: it used to assert the guards were still in place, and
 * now asserts that neither the helpers nor the list names come back. The earlier version would
 * have passed forever on a file where the guards were removed correctly, which is why it could not
 * simply be left alone.
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

console.log('\nthe SharePoint helpers are gone');
['spGet', 'spPost', 'spPatch'].forEach(fn => t(fn + ' does not exist', () => {
  /* Definition OR call. Excluding `.spGet(` so a method on some unrelated object is not mistaken
     for one of these — the point is the global helper, not the four letters. */
  const n = (src.match(new RegExp('(?<![\\w$.])' + fn + '\\s*\\(', 'g')) || []).length;
  if (n) {
    throw new Error(fn + ' is back (' + n + ' occurrence(s)). SharePoint is decommissioned: a ' +
      'write there reaches nothing and reports success, and the portal records none of it.');
  }
}));

console.log('\nno SharePoint list is addressed any more');
t('the three list names appear in no call', () => {
  const bad = ['Leave_Requests', 'Attendance_Records', 'Approved_Locations']
    .filter(l => new RegExp("\\bsp[A-Za-z]*\\(\\s*'" + l + "'").test(src));
  if (bad.length) throw new Error('still written: ' + bad.join(', '));
});

console.log('\nand the guards they hid behind are gone with them');
t('no `if (true)` SharePoint fence remains', () => {
  const n = (src.match(/if \(true\) \{\s*\/\* always use standalone Python backend/g) || []).length;
  if (n) {
    throw new Error(n + ' fence(s) remain. They only existed to hold back the SharePoint code; ' +
      'with that deleted they are an always-true condition wrapping the only path there is.');
  }
});
t('the code they wrapped is still there', () => {
  /* The unwrap had to keep the body. If a fence was deleted along with what it guarded, these
     would be gone too — and the failure would be silent, because a check-in that never runs looks
     like a user who did not press the button. */
  ['async function doCheckin(', 'async function doCheckout(', 'async function submitLeave(']
    .forEach(sig => {
      if (src.indexOf(sig) < 0) throw new Error('missing ' + sig + ')');
    });
  ['_commitCheckin(', 'tkESign({', 'tkRenderLeaveView()'].forEach(needle => {
    if (src.indexOf(needle) < 0) throw new Error('the real path lost ' + needle);
  });
});

console.log('\n' + pass + ' passed, ' + fail + ' failed');
process.exit(fail ? 1 : 0);
