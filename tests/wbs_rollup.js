/* The Work Breakdown Structure has to answer from the Master Schedule — date and status included.
 *
 * The register printed `d.percentComplete`, `d.due` and `d.status` straight off the deliverable
 * record. Only the percentage was ever derived from linked activities, and only into the project
 * KPI. So a master schedule could move every activity in a package and the WBS went on showing a
 * typed number, a date nobody had revisited, and "Not started".
 *
 * Reported as: "the completion percentage, due date and status are not automatically updated in the
 * Work Breakdown Structure when changes are made in the Master Schedule."
 *
 * The three rules that make the derivation safe, each asserted below:
 *   · a package with NO linked activity is untouched, and says so (`from: 'typed'`)
 *   · the derived date is the LAST finish, and the typed due survives beside it as the commitment
 *   · 'Accepted' is a signature. A schedule may complete a package; only a person accepts one.
 *
 *   node tests/wbs_rollup.js
 */
const fs = require('fs');
const path = require('path');

const src = fs.readFileSync(path.join(__dirname, '..', 'templates', 'index.html'), 'utf8');

let pass = 0, fail = 0;
const ok = (n, c, extra) => {
  if (c) { pass++; console.log('  ok    ' + n); }
  else { fail++; console.log('  FAIL  ' + n + (extra ? '\n        ' + extra : '')); }
};

const take = (mark, what) => {
  const i = src.indexOf(mark);
  if (i < 0) { console.error('Could not find ' + what + ' — update the marker, do NOT delete this test.'); process.exit(2); }
  const j = src.indexOf('\nfunction ', i + 10);
  if (j < 0) { console.error('Could not find the end of ' + what + '.'); process.exit(2); }
  return src.slice(i, j);
};

const F = new Function(
  take('function _pmDateDiff(', '_pmDateDiff') +
  take('function _pmPct(', '_pmPct') +
  take('function _pmStatusFromPct(', '_pmStatusFromPct') +
  take('function _pmTaskWeight(', '_pmTaskWeight') +
  take('function _pmActivityPct(', '_pmActivityPct') +
  take('function _pmDelivBuckets(', '_pmDelivBuckets') +
  take('function _pmDelivRoll(', '_pmDelivRoll') +
  '\nreturn { _pmDelivBuckets, _pmDelivRoll, _pmTaskWeight };')();

// One month of work each, so weights are equal and a mean is easy to reason about by hand.
const act = (o) => Object.assign({ start: '2026-07-01', finish: '2026-07-31', pctComplete: 0 }, o);

console.log('\nA work package answers from the activities that deliver it\n');

// -- nothing linked: bit-for-bit what it showed before ---------------------------------------------
{
  const d = { id: 'D1', due: '2026-08-31', percentComplete: 40, status: 'In progress' };
  const r = F._pmDelivRoll(d, [], 'P');
  ok('an unlinked package keeps its typed percentage', r.pct === 40);
  ok('and its typed due date', r.due === '2026-08-31');
  ok('and its typed status', r.status === 'In progress');
  ok('and says the values are typed', r.from === 'typed' && r.n === 0,
     'the register prints this: "0% / Not started" with no explanation is the complaint');
}

// -- the percentage ---------------------------------------------------------------------------------
{
  const d = { id: 'D1', percentComplete: 0, status: 'Not started' };
  const r = F._pmDelivRoll(d, [act({ pctComplete: 100 }), act({ pctComplete: 0 })], 'P');
  ok('two equal activities at 100 and 0 give 50', Math.round(r.pct) === 50, 'got ' + r.pct);
  ok('and the basis is the schedule', r.from === 'activities' && r.n === 2);
}
{
  // Unequal spans must weigh unequally, or a one-day snag counts as much as a three-month pour.
  const d = { id: 'D1' };
  const long = act({ start: '2026-07-01', finish: '2026-09-28', pctComplete: 0 });   // 90 days
  const short = act({ start: '2026-07-01', finish: '2026-07-10', pctComplete: 100 }); // 10 days
  const r = F._pmDelivRoll(d, [long, short], 'P');
  ok('activities are weighted by their span, not counted', Math.round(r.pct) === 10,
     'a 10-day activity finished out of 100 days is 10%, got ' + Math.round(r.pct));
}
{
  // An actual finish outranks a typed number — _pmActivityPct's own ladder, reached through here.
  const r = F._pmDelivRoll({ id: 'D1' }, [act({ pctComplete: 0, actualFinish: '2026-07-20' })], 'P');
  ok('an activity with an actual finish counts as complete however it was typed', r.pct === 100);
}

// -- the date ----------------------------------------------------------------------------------------
{
  const d = { id: 'D1', due: '2026-08-31' };
  const r = F._pmDelivRoll(d, [act({ finish: '2026-07-31' }), act({ finish: '2026-09-30' })], 'P');
  ok('the package is not delivered until its LAST activity is', r.due === '2026-09-30',
     'got ' + r.due);
  ok('the commitment survives beside the forecast', r.committed === '2026-08-31',
     'overwriting one with the other loses the variance, which is the number a PM is looking for');
  ok('and the slip is counted in days', r.slip === 30, 'got ' + r.slip);
}
{
  const r = F._pmDelivRoll({ id: 'D1', due: '2026-12-31' }, [act({ finish: '2026-09-30' })], 'P');
  ok('finishing early is not reported as a slip', r.slip === 0);
}
{
  const r = F._pmDelivRoll({ id: 'D1' }, [act({ finish: '2026-09-30' })], 'P');
  ok('with no commitment there is no slip to report', r.slip === 0 && r.due === '2026-09-30');
}
{
  // A milestone carries one date. Reading only `finish` would give the package no date at all.
  const r = F._pmDelivRoll({ id: 'D1' }, [{ start: '2026-09-15', finish: '' }], 'P');
  ok('a one-date activity still dates the package', r.due === '2026-09-15');
}

// -- the status ---------------------------------------------------------------------------------------
{
  const S = (pct, typed) => F._pmDelivRoll({ id: 'D1', status: typed }, [act({ pctComplete: pct })], 'P').status;
  ok('every activity done reads Completed', S(100, 'Not started') === 'Completed');
  ok('some work done reads In progress', S(35, 'Not started') === 'In progress');
  ok('no work done reads Not started', S(0, 'In progress') === 'Not started',
     'the status follows the schedule in BOTH directions or it is not derived');
  ok('but Accepted is never taken away by the schedule', S(0, 'Accepted') === 'Accepted',
     'a schedule can complete a package; only a person accepts one');
  ok('and Accepted survives completion too', S(100, 'Accepted') === 'Accepted');
}

// -- bucketing ------------------------------------------------------------------------------------------
{
  const by = F._pmDelivBuckets([
    act({ id: 't1', delivId: 'D1' }), act({ id: 't2', delivId: 'D2' }),
    act({ id: 't3', delivId: '' }), act({ id: 't4' })
  ]);
  ok('activities bucket by the package they deliver', (by.D1 || []).length === 1 && (by.D2 || []).length === 1);
  ok('and unlinked activities are keyed nowhere', !('' in by),
     'a package whose own id were falsy would otherwise absorb every unassigned activity');
}

// -- the wiring that makes any of it visible -----------------------------------------------------------
console.log('\nAnd the register can actually reach it\n');
ok('the Scope tab loads the activities it derives from',
   /fn: 'pmRenderScope', need: \['pm_projects', 'pm_deliverables', 'pm_tasks'\]/.test(src),
   '_pmScopeFor returns [] for a register that was never fetched — every package would read "nothing linked"');
{
  const scope = take('function pmRenderScope(', 'pmRenderScope');
  ok('the register derives per package', /_pmDelivRoll\(d, _bk\[d\.id\] \|\| \[\], pid\)/.test(scope));
  ok('Due, Progress and Status all read the derived values',
     /sk: '_due'/.test(scope) && /sk: '_pct'/.test(scope) && /sk: '_status'/.test(scope),
     'sorting a column on the typed field while showing the derived one is its own bug');
  ok('nothing is written back to the record', !/tkApi\(/.test(scope) && !/_HR\.pm_deliverables\[/.test(scope),
     'derive on read — a stored copy drifts the moment the schedule moves');
  ok('a package with no links is labelled, not silently zero', /_t\('typed'\)/.test(scope));
  ok('and a project with no links at all is told why', /Nothing is linked to the Master Schedule yet\./.test(scope));
  ok('every row offers the way to link', /onclick="pmDelivLink/.test(scope));
}
{
  const save = take('async function pmDelivLinkSave(', 'pmDelivLinkSave');
  ok('only changed activities are written',
     /const was = b\.dataset\.was === '1', now = !!b\.checked;/.test(save) && /if \(was !== now\)/.test(save),
     'PATCH on /api/coll replaces the whole item — rewriting untouched rows is not a no-op');
  ok('and the PATCH carries the whole object',
     /Object\.assign\(\{\}, t, \{ delivId: c\.deliv \}\)/.test(save),
     'a partial body would blank every other field on the activity');
  const all = take('function pmDelivLinkAll(', 'pmDelivLinkAll');
  ok('"select all" only ticks what the filter is showing',
     /if \(l\.style\.display === 'none'\) return;/.test(all),
     'ticking rows the user cannot see is how the wrong half of a programme gets linked');
}

console.log('\n  ' + pass + ' passed, ' + fail + ' failed\n');
process.exit(fail ? 1 : 0);
