/* 100% means 100% everywhere, including once daily progress exists.
 *
 * _pmTaskPctRoll answers with a percentage AND where it came from. For a long time `from` had three
 * values — 'children', 'detail', 'typed' — and code downstream branched on them. Daily progress on
 * the Master Schedule added a FOURTH, 'daily', and the branches did not move:
 *
 *   · _pmDelivRoll composed two ladders on the test `from === 'typed'`, consulting _pmActivityPct —
 *     the half that knows an activity carrying an actual finish or status Completed is done however
 *     it was estimated — only when the roll-up bottomed out at a typed number. An activity FINISHED
 *     on site and carrying an older reading of 60 stopped reaching that branch. It contributed 60,
 *     not 100, to its work package, to project earned value, to CPI/SPI and to the RAG colour, and
 *     went on doing so until somebody filed a fresh 100 — while its own row read "Completed".
 *
 *   · the Activities table's % column fell through to the detail branch, so three daily readings on
 *     an activity with no detail schedule at all printed "rolled up" under the tooltip "Rolled up
 *     from 3 detail items": a false statement about provenance, in the column a PM reads to decide
 *     whether a number can be trusted.
 *
 * The through-line is not "we forgot 'daily'". It is that both sites tested for what a value is NOT.
 * `from !== 'typed'` silently absorbs every value invented afterwards, and absorbs it into whichever
 * branch happens to be last. So the fix names what each value IS, and this file pins BOTH halves of
 * that: the answers, and the fact that a leaf estimate is still an estimate.
 *
 *   node tests/pct_from_fourth_value.js
 */
const fs = require('fs');
const path = require('path');

const src = fs.readFileSync(path.join(__dirname, '..', 'templates', 'index.html'), 'utf8');

let pass = 0, fail = 0;
const ok = (n, c, extra) => {
  if (c) { pass++; console.log('  ok    ' + n); }
  else { fail++; console.log('  FAIL  ' + n + (extra ? '\n        ' + extra : '')); }
};
const eq = (n, got, want) => ok(n, got === want, 'got ' + JSON.stringify(got) + ', want ' + JSON.stringify(want));

function take(name) {
  const re = new RegExp('\\n(?:const |)(?:async )?function ' + name.replace(/\$/g, '\\$') + '\\s*\\(');
  const i = src.search(re);
  if (i < 0) {
    console.error('could not find ' + name + ' — update the marker, do NOT delete this test.');
    process.exit(2);
  }
  const from = i + 1;
  const ends = ['\nfunction ', '\nasync function ', '\nconst ', '\n/* ']
    .map(m => src.indexOf(m, from + 10)).filter(x => x > 0);
  return src.slice(from, ends.length ? Math.min.apply(null, ends) : from + 4000);
}

const NEEDED = ['_pmLeafPct', '_pmTaskPctRollWalk', '_pmWbsChildIndex', '_pmWbsChildren',
                '_pdLog', '_pdAcc', '_pdReadPct', '_pmActivityPct', '_pmTaskWeight',
                '_pmTaskPctFinal', '_pmDelivBuckets', '_pmDelivRoll', '_pmStatusFromPct'];
const bodies = NEEDED.map(take).join('\n');

const PRELUDE = `
  const _pmPct = v => { const n = Math.round(+v || 0); return n < 0 ? 0 : (n > 100 ? 100 : n); };
  const _pdQtyPlan = () => 0;
  const _pmToday = () => TODAY;
  const _pdWeight = t => (t && +t.w) || 1;
  const _pdTaskPct = (t, pid) => DETAIL[(t && (t.wbs || t.name)) || ''] || null;
  const _pmWbsKidIdx = new WeakMap();
  const _pmDateDiff = (a, b) => Math.round((Date.parse(b) - Date.parse(a)) / 86400000);
  // The memoised entry point is a thin wrapper over the walk; the walk is what every branch below
  // actually exercises, and lifting the memo would make results depend on call order.
  const _pmTaskPctRoll = (t, all, pid) => _pmTaskPctRollWalk(t, all, pid, 0);
  const _PM_DELIV_SIGNED = ['Submitted', 'Accepted'];
`;
const build = (todayVal, detail) => new Function('TODAY', 'DETAIL', PRELUDE + bodies +
  '\nreturn { roll: _pmTaskPctRollWalk, deliv: _pmDelivRoll, act: _pmActivityPct, leaf: _pmLeafPct };'
)(todayVal, detail);

const TODAY = '2026-09-04';
const D = { due: '2026-09-30', percentComplete: 0, status: 'In progress' };

// ══ 1. the four values, named ══════════════════════════════════════════════════════════════════
console.log('\nWhat `from` can be\n');
{
  const M = build(TODAY, { '9.9': { pct: 33, n: 4 } });
  const kids = [{ id: 'p', wbs: '1' }, { id: 'k', wbs: '1.1', pctComplete: 50 }];
  eq("a leaf nobody has filed against is 'typed'",
     M.roll({ id: 'x', wbs: '2', pctComplete: 20 }, [], 'P', 0).from, 'typed');
  eq("a leaf with a dated reading is 'daily'",
     M.roll({ id: 'x', wbs: '2', log: [{ d: '2026-09-02', pct: 60 }] }, [], 'P', 0).from, 'daily');
  eq("an activity the site reports against in detail is 'detail'",
     M.roll({ id: 'x', wbs: '9.9' }, [], 'P', 0).from, 'detail');
  eq("a summary activity is 'children'", M.roll(kids[0], kids, 'P', 0).from, 'children');
  eq('and a daily reading reports HOW MANY readings, not how many detail items',
     M.roll({ id: 'x', wbs: '2', log: [{ d: '2026-09-01', pct: 10 }, { d: '2026-09-02', pct: 60 }] },
            [], 'P', 0).n, 2);
}

// ══ 2. the confirmed defect: a finished activity is 100 in its package ═════════════════════════
console.log('\nA finished activity counts as finished\n');
{
  const M = build(TODAY, {});
  const stale = { d: '2026-09-01', pct: 60 };

  const byStatus = { id: 'a', wbs: '1', delivId: 'D', status: 'Completed', pctComplete: 0,
                     log: [stale], start: '2026-08-01', finish: '2026-09-03' };
  eq('status Completed, carrying an older reading of 60 -> 100',
     M.deliv(D, [byStatus], 'P', [byStatus]).pct, 100);

  const byFinish = { id: 'b', wbs: '1', delivId: 'D', actualFinish: '2026-09-03', pctComplete: 0,
                     log: [stale], start: '2026-08-01', finish: '2026-09-03' };
  eq('an actual finish date, same reading -> 100',
     M.deliv(D, [byFinish], 'P', [byFinish]).pct, 100);

  ok('and it counts toward the package\'s "done" tally',
     M.deliv(D, [byFinish], 'P', [byFinish]).done === 1);

  // The regression, stated as the number it produced. Before the fix the package read the reading.
  ok('the pre-fix answer (60) is gone',
     M.deliv(D, [byStatus], 'P', [byStatus]).pct !== 60);
}

// ══ 3. the half a careless fix breaks ══════════════════════════════════════════════════════════
console.log('\nAn unfinished activity still reports what the site filed\n');
{
  const M = build(TODAY, {});
  // `from === 'typed' || from === 'daily'` would have been the one-word fix. It sends this activity
  // to _pmActivityPct, which for an unfinished leaf answers with pctComplete — the stale 0 the
  // daily table exists to replace. The package would read 0 while the schedule reads 60.
  const t = { id: 'c', wbs: '1', delivId: 'D', status: 'In progress', pctComplete: 0,
              log: [{ d: '2026-09-02', pct: 60 }], start: '2026-08-01', finish: '2026-09-30' };
  eq('a daily reading of 60 on an unfinished activity reaches its package as 60',
     M.deliv(D, [t], 'P', [t]).pct, 60);
  ok('not as the typed 0 it has never been updated to', M.deliv(D, [t], 'P', [t]).pct !== 0);
}

// ══ 4. nothing above the leaf was disturbed ════════════════════════════════════════════════════
console.log('\nEvidence beneath an activity still outranks a stamp on it\n');
{
  const M = build(TODAY, { '5': { pct: 40, n: 7 } });

  // A parent marked Completed while its sub-tasks are at 50 is a data error, and the sub-tasks are
  // the evidence. Children win — that is the whole first rule of the ladder.
  const kids = [{ id: 'p', wbs: '1', delivId: 'D', status: 'Completed' },
                { id: 'k1', wbs: '1.1', pctComplete: 50 }, { id: 'k2', wbs: '1.2', pctComplete: 50 }];
  eq('a summary activity stamped Completed still reads its sub-tasks',
     M.deliv(D, [kids[0]], 'P', kids).pct, 50);

  // Measured quantities outrank a completion stamp too, and did before this change.
  const meas = { id: 'm', wbs: '5', delivId: 'D', status: 'Completed' };
  eq('an activity measured on site at 40% is not promoted to 100 by its status',
     M.deliv(D, [meas], 'P', [meas]).pct, 40);
}
{
  /* And the 'detail' clause is not decoration. Dropping it gives the same ANSWER — _pmActivityPct
     asks _pdTaskPct first and grades the result 'measured', so the completion branch is never
     reached either way — which makes it exactly the kind of line somebody deletes as redundant.
     What it actually saves is the second _pdTaskPct call, and _pdTaskPct scans the detail rows. On
     a package of 300 measured activities that is 300 avoidable scans per render, so the reason is
     counted here rather than asserted in prose. */
  let calls = 0;
  const M2 = new Function('TODAY', 'DETAIL', 'COUNT', PRELUDE.replace(
      'const _pdTaskPct = (t, pid) => DETAIL[(t && (t.wbs || t.name)) || \'\'] || null;',
      'const _pdTaskPct = (t, pid) => { COUNT(); return DETAIL[(t && (t.wbs || t.name)) || \'\'] || null; };')
    + bodies + '\nreturn { deliv: _pmDelivRoll };')(TODAY, { '5': { pct: 40, n: 7 } }, () => calls++);
  const meas2 = { id: 'm', wbs: '5', delivId: 'D', status: 'Completed' };
  M2.deliv(D, [meas2], 'P', [meas2]);
  eq('a measured activity is looked up in the detail rows ONCE per roll-up, not twice', calls, 1);
}

// ══ 5. the column says which source it means ═══════════════════════════════════════════════════
console.log('\nThe Activities % column names its source honestly\n');
{
  /* The real render lambda, lifted from the table spec and executed — not a source-text match. A
     check that only grepped for the word 'daily' would pass on a branch placed after the one it is
     supposed to precede. */
  const marker = "        const ro = _pmTaskPctRoll(r, allTasks, pid);\n";
  const i = src.indexOf(marker);
  if (i < 0) { console.error('could not find the % column render — update the marker.'); process.exit(2); }
  const end = src.indexOf('\n      } },', i);
  const body = src.slice(i, end);
  const render = new Function('r', 'allTasks', 'pid', '_pmTaskPctRoll', '_pmPct', '_t', '_tkEscA',
                              body + '\n');
  const call = (roVal, row) => render(row || {}, [], 'P', () => roVal,
                                      v => Math.round(+v || 0), x => x, x => x);

  const daily = call({ pct: 60, from: 'daily', n: 3 });
  ok('a daily-reported activity is labelled daily progress', /daily progress/.test(daily), daily);
  ok('and is NOT called a detail item', !/detail item/.test(daily), daily);
  ok('its tooltip counts READINGS', /3 daily readings/.test(daily), daily);

  const det = call({ pct: 40, from: 'detail', n: 7 });
  ok('a detail-fed activity still says rolled up', /rolled up/.test(det) && /7 detail items/.test(det), det);
  const kid = call({ pct: 50, from: 'children', n: 2 });
  ok('a summary activity still says from sub-tasks', /from sub-tasks/.test(kid), kid);
  const typed = call({ pct: 0, from: 'typed', n: 0 }, { pctComplete: 25 });
  eq('a typed activity prints the typed figure with no provenance line', typed, '25%');
}

// ══ 6. the shape of the test, not just its answers ═════════════════════════════════════════════
console.log('\nThe branch names what a value IS\n');
{
  const i = src.indexOf('function _pmTaskPctFinal(');
  const body = src.slice(i, src.indexOf('\n}', i) + 2);
  ok('_pmDelivRoll no longer decides by what `from` is NOT',
     !/from !== 'typed'/.test(body) && !/r\.from === 'typed' \?/.test(body), body);
  ok('it names the two derived sources explicitly',
     /from === 'children'/.test(body) && /from === 'detail'/.test(body), body);
  ok('and asks _pmActivityPct for its own grading rather than copying the test',
     /basis === 'complete'/.test(body) && !/actualFinish/.test(body), body);
}

console.log('\n' + pass + ' passed, ' + fail + ' failed\n');
process.exit(fail ? 1 : 0);
