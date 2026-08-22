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

/* Pulled by regex, not by take(): take() slices from its marker to the next '\nfunction ', so a
   const declared immediately above _pmDelivRoll drags that whole function along with it and the
   harness then declares it twice. */
const SIGNED = (src.match(/const _PM_DELIV_SIGNED = \[[^\]]*\];/) || [])[0];
if (!SIGNED) { console.error('Could not find _PM_DELIV_SIGNED.'); process.exit(2); }

const F = new Function(
  take('function _pmDateDiff(', '_pmDateDiff') +
  take('function _pmPct(', '_pmPct') +
  take('function _pmStatusFromPct(', '_pmStatusFromPct') +
  take('function _pmTaskWeight(', '_pmTaskWeight') +
  take('function _pmActivityPct(', '_pmActivityPct') +
  // The real ladder every other screen uses. _pmDelivRoll calls it now, so the register and the
  // Activities tab cannot print two different percentages for the same activity.
  take('function _pdWeight(', '_pdWeight') +
  take('function _pmWbsChildren(', '_pmWbsChildren') +
  take('function _pmTaskPctRoll(', '_pmTaskPctRoll') +
  // NOTE: this slice runs to the next '\nfunction ', which is _pmDelivRoll — so it already carries
  // the `const _PM_DELIV_SIGNED` declared between them. Injecting SIGNED here as well is a
  // redeclaration and a SyntaxError. SIGNED is asserted against `src` instead, below.
  take('function _pmDelivBuckets(', '_pmDelivBuckets') +
  take('function _pmDelivRoll(', '_pmDelivRoll') +
  '\nreturn { _pmDelivBuckets, _pmDelivRoll, _pmTaskWeight, _pmTaskPctRoll, _PM_DELIV_SIGNED };')();

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
  /* BOTH rungs of the composed ladder, and each one is a branch the other cannot reach.
     _pmTaskPctRoll stops at the typed number and would call these 0; _pmActivityPct has no children
     step and would call the parent above 0. Neither alone answers a work package. */
  const r = F._pmDelivRoll({ id: 'D1' }, [act({ pctComplete: 0, actualFinish: '2026-07-20' })], 'P', []);
  ok('an activity with an actual finish counts as complete however it was typed', r.pct === 100,
     '_pmTaskPctRoll alone reports ' + F._pmTaskPctRoll(act({ pctComplete: 0, actualFinish: '2026-07-20' }), [], 'P').pct);
  const c = F._pmDelivRoll({ id: 'D1' }, [act({ pctComplete: 0, status: 'Completed' })], 'P', []);
  ok('and so does one whose status says Completed', c.pct === 100);
  /* The composition must not OVERRIDE the roll-up: a parent whose children are half done stays at
     half even if somebody ticked the parent itself Completed — children win, that is the rule. */
  const p = act({ wbs: '9', pctComplete: 0, status: 'Completed', start: '2026-01-01', finish: '2026-12-31' });
  const all9 = [p, act({ wbs: '9.1', pctComplete: 0, start: '2026-01-01', finish: '2026-06-30' }),
                   act({ wbs: '9.2', pctComplete: 0, start: '2026-07-01', finish: '2026-12-31' })];
  ok('but a summary ticked Completed does not override children reporting nothing',
     Math.round(F._pmDelivRoll({ id: 'D1' }, [p], 'P', all9).pct) === 0,
     'children win; the actualFinish rung is only reached when the roll-up bottomed out at typed');
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
  ok('the register derives per package, and hands it the whole activity list',
     /_pmDelivRoll\(d, _bk\[d\.id\] \|\| \[\], pid, _bkAll\)/.test(scope),
     'without the 4th argument _pmTaskPctRoll cannot find a summary activity\'s children');
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

// -- the register and the Schedule tab must reach the SAME percentage ------------------------------
/* _pmDelivRoll used to call _pmActivityPct, whose ladder is detail-rows -> actualFinish -> typed.
   Every other screen calls _pmTaskPctRoll, whose FIRST rule is that WBS children win. A summary
   activity therefore read 100% on the Activities tab and contributed 0% to its work package — and
   this change puts that number on the register labelled "from the schedule". */
console.log('\nOne percentage, on the register and on the Schedule tab\n');
{
  const parent = act({ wbs: '1.4', name: 'MEP', start: '2026-01-01', finish: '2026-12-31', pctComplete: 0, delivId: 'D1' });
  const kids = [act({ wbs: '1.4.1', start: '2026-01-01', finish: '2026-06-30', pctComplete: 100 }),
                act({ wbs: '1.4.2', start: '2026-07-01', finish: '2026-12-31', pctComplete: 100 })];
  const all = [parent].concat(kids);
  const schedule = F._pmTaskPctRoll(parent, all, 'P').pct;
  const pkg = F._pmDelivRoll({ id: 'D1' }, [parent], 'P', all);
  ok('a summary activity carries its children into the package',
     Math.round(pkg.pct) === 100 && schedule === 100,
     'Schedule tab says ' + schedule + '%, the register says ' + Math.round(pkg.pct) + '%');

  // Link the parent AND its children — which "Select all shown" after typing 1.4 does in one click.
  const both = F._pmDelivRoll({ id: 'D1' }, all, 'P', all);
  ok('linking a parent and its children counts the work once, not twice',
     both.n === 1 && Math.round(both.pct) === 100,
     'kept ' + both.n + ' top-level activities');
}
{
  // A half-done parent, so the assertion above cannot pass on a constant.
  const parent = act({ wbs: '2', start: '2026-01-01', finish: '2026-12-31', pctComplete: 0, delivId: 'D1' });
  const all = [parent,
    act({ wbs: '2.1', start: '2026-01-01', finish: '2026-06-30', pctComplete: 100 }),
    act({ wbs: '2.2', start: '2026-07-01', finish: '2026-12-31', pctComplete: 0 })];
  ok('and a half-finished summary reads half, not all or nothing',
     Math.round(F._pmDelivRoll({ id: 'D1' }, [parent], 'P', all).pct) === 50);
}
{
  // Siblings are NOT descendants of each other and must both count.
  const a = act({ wbs: '3.1', pctComplete: 100 }), b = act({ wbs: '3.2', pctComplete: 0 });
  const r = F._pmDelivRoll({ id: 'D1' }, [a, b], 'P', [a, b]);
  ok('two siblings are two activities', r.n === 2 && Math.round(r.pct) === 50);
}

// -- a governance status is not a measurement --------------------------------------------------------
console.log('\nSubmitted and Accepted are acts of a person\n');
{
  const S = (pct, typed) => F._pmDelivRoll({ id: 'D1', status: typed }, [act({ pctComplete: pct })], 'P', []).status;
  ok('Submitted survives the schedule completing the work', S(100, 'Submitted') === 'Submitted',
     'only somebody can submit a package for acceptance, and only somebody can withdraw it');
  ok('Submitted survives the schedule showing no progress', S(0, 'Submitted') === 'Submitted');
  ok('both signed statuses are protected, not just Accepted',
     /'Submitted'/.test(SIGNED) && /'Accepted'/.test(SIGNED),
     'the shipping list is ' + SIGNED);
  ok('an unsigned status still follows the schedule', S(100, 'In progress') === 'Completed');
}
ok('and Completed is a status the deliverable form can actually hold',
   /options: \['Not started', 'In progress', 'Completed', 'Submitted', 'Accepted'\]/.test(src),
   'the register would otherwise display a value the edit form silently replaces on save');

// -- the date says where it came from ------------------------------------------------------------------
console.log('\nThe Due column is honest about its source\n');
{
  const r = F._pmDelivRoll({ id: 'D1', due: '2026-08-31' }, [act({ start: '', finish: '' })], 'P', []);
  ok('undated activities fall back to the commitment', r.due === '2026-08-31');
  ok('and it is NOT labelled as coming from the schedule', r.dueFrom === 'typed',
     'printing "from the schedule" over a typed date is the false provenance this change exists to remove');
}
{
  const r = F._pmDelivRoll({ id: 'D1', due: '2026-08-31' }, [act({ finish: '2026-09-30' })], 'P', []);
  ok('a dated activity is labelled as the schedule', r.dueFrom === 'activities');
}
{
  // Handed over three weeks after the plan: the real date is the one it happened on.
  const r = F._pmDelivRoll({ id: 'D1', due: '2026-08-31' },
                           [act({ finish: '2026-08-31', actualFinish: '2026-09-21', pctComplete: 100 })], 'P', []);
  ok('an ACTUAL finish outranks the planned one', r.due === '2026-09-21', 'got ' + r.due);
  ok('so a package delivered late reports the slip instead of 0d', r.slip === 21, 'got ' + r.slip);
}

console.log('\n  ' + pass + ' passed, ' + fail + ' failed\n');
process.exit(fail ? 1 : 0);
