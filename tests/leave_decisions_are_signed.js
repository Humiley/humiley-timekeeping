/* A leave decision goes through the signed flow, and nothing else offers one.
 *
 * After a staff member submitted leave, the page hand-built an approval card from the form values
 * and prepended it to the REQUESTER's own pending list — carrying Approve and Reject buttons. So
 * somebody who had just asked for leave was shown an Approve button on their own request.
 *
 * Clicking it called spPatch('Leave_Requests', 'new', {Status: 'Approved'}) — SharePoint, with a
 * literal id of 'new' — and then toasted "Leave approved". The portal was untouched: the request
 * was still pending, the balance not applied, nothing signed, no approver recorded. The only thing
 * that changed was that the employee had been told it was approved.
 *
 * The card is gone; the list is redrawn from what the server actually holds. This keeps it that
 * way, and keeps the SharePoint-writing handlers unreachable. They are still in the file — five
 * functions whose boundaries this codebase's size makes risky to splice — and they are harmless
 * while nothing calls them. What is NOT harmless is somebody wiring a button back to one, because
 * a leave decision would then bypass /api/esign, the three-level chain and the balance rule, and
 * would say so to nobody.
 *
 *   node tests/leave_decisions_are_signed.js
 */
const fs = require('fs');
const path = require('path');

const src = fs.readFileSync(path.join(__dirname, '..', 'templates', 'index.html'), 'utf8');

let pass = 0, fail = 0;
function t(name, fn) {
  try { fn(); console.log('  ok    ' + name); pass++; }
  catch (e) { console.log('  FAIL  ' + name + '\n        ' + e.message); fail++; }
}
const eq = (a, b, m) => { if (a !== b) throw new Error((m || '') + ' expected ' + JSON.stringify(b) + ', got ' + JSON.stringify(a)); };

/* Calls, not definitions: `foo(` preceded by something other than `function `. */
function callsOf(name) {
  const re = new RegExp('(?:^|[^\\w$.])' + name + '\\s*\\(', 'g');
  let n = 0, m;
  while ((m = re.exec(src))) {
    const before = src.slice(Math.max(0, m.index - 24), m.index + name.length + 1);
    if (/function\s+$/.test(src.slice(Math.max(0, m.index), m.index).slice(-9)) ) continue;
    if (/(?:async\s+)?function\s+$/.test(before.slice(0, before.length - name.length - 1))) continue;
    n++;
  }
  return n;
}

console.log('\nthe SharePoint leave handlers are reachable from nothing');
['viewLeaveDetail', 'approveLeaveCard', 'rejectLeaveCard', 'managerApprove', 'managerReject']
  .forEach(fn => t(fn + ' has no caller', () => {
    eq(callsOf(fn), 0,
      fn + ' is called again. It writes a leave decision to SharePoint and bypasses /api/esign, ' +
      'the three-level approval chain and the balance rule — and tells the user it succeeded. ' +
      'Route the decision through tkESign({ coll: \'leave\' }) instead.');
  }));

console.log('\nno approval control is built for the requester');
t('submitting leave does not create a card with Approve/Reject on it', () => {
  eq(/approveLeaveCard\(this/.test(src), false,
    'an Approve button is being built into a card again — check whose list it is prepended to');
  eq(/rejectLeaveCard\(this/.test(src), false, 'likewise Reject');
});
t('the leave view is redrawn from the server after a submission', () => {
  const i = src.indexOf("meaning: 'Submit — Leave '");
  if (i < 0) throw new Error('could not find the leave submission — has it been renamed?');
  const after = src.slice(i, i + 3000);
  if (after.indexOf('tkRenderLeaveView()') < 0) {
    throw new Error('the submission no longer redraws the list from the server; a hand-built card ' +
      'is how the Approve button reached the requester in the first place');
  }
});

console.log('\nand the decision path that IS used stays the signed one');
t("leave decisions go through tkESign({ coll: 'leave' })", () => {
  const n = (src.match(/coll:\s*'leave'/g) || []).length;
  if (n < 3) throw new Error('expected the signed leave flow to appear several times, found ' + n);
});

console.log('\n' + pass + ' passed, ' + fail + ' failed');
process.exit(fail ? 1 : 0);
