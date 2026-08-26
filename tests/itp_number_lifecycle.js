/* Where an ITP number comes from, and what it costs to change one.
 *
 * Two things the owner asked for, and they pull in opposite directions:
 *
 *   · the number should be AUTOMATIC when a plan is created — nobody should have to think of one;
 *   · the register should be CONSOLIDATED to 1..N — the numbers already there have gaps.
 *
 * The first is a convenience. The second rewrites document numbers that appear on issued, approved
 * inspection plans and on the contractor's paperwork, so it is deliberate, previewed, and keeps the
 * number each plan was issued under.
 *
 *   node tests/itp_number_lifecycle.js
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
  const ends = ['\nfunction ', '\nasync function ', '\nconst ', '\nlet ']
    .map(e => src.indexOf(e, i + 10)).filter(x => x > 0);
  return src.slice(i, Math.min.apply(null, ends));
};

const PID = 'P1';
const api = rows => new Function('ROWS',
  'const _HR = { pm_quality_itp: ROWS, pm_tasks: [] };\n' +
  'const _pmScopeFor = (c, pid) => (_HR[c] || []).filter(x => x.projectId === pid);\n' +
  'function _pdTaskRef(t){ return String((t && (t.wbs || t.name)) || "").trim(); }\n' +
  take('function _pmDocNoCmp(', '_pmDocNoCmp') +
  take('function _pmItpRenumberPlan(', '_pmItpRenumberPlan') +
  '\nreturn { plan: pid => _pmItpRenumberPlan(pid) };')(rows);

const reg = (...nos) => nos.map((n, i) => ({ id: 'r' + i, projectId: PID,
  itpNo: n === null ? '' : String(n), title: 'Plan ' + (n === null ? 'unnumbered' : n) }));

// ══ the number arrives with the form ═══════════════════════════════════════════════════════════
console.log('\nA new plan is numbered before anyone types anything\n');
{
  const qa = take('function tkQuickAdd(', 'tkQuickAdd');
  ok('creating a record pre-fills the register\'s number field',
     /if \(!id && typeof _PM_NUMSPEC !== 'undefined' && _PM_NUMSPEC\[spec\.coll\]/.test(qa),
     'the number used to be injected at SAVE time, so the field sat empty in the form and read as ' +
     '"think of a number yourself"');
  ok('it fills the field the register actually numbers on',
     /const _nf = _PM_NUMSPEC\[spec\.coll\]\.f;/.test(qa));
  ok('it never overwrites something already there',
     /if \(!String\(_pre\[_nf\] \|\| ''\)\.trim\(\)\) \{/.test(qa),
     'a caller-supplied seed, or a number typed before the form re-rendered, must win');
  ok('and it only happens on CREATE, never when editing',
     /if \(!id && typeof _PM_NUMSPEC/.test(qa),
     'pre-filling on edit would offer to change the number of an issued plan by accident');
  ok('the quality register is excluded, because its tag depends on a field in the form',
     /spec\.coll !== 'pm_quality'/.test(qa),
     'an NCR numbered at form-open would say QA and be wrong the moment the type was chosen');
  ok('leaving it blank still works — save fills it',
     /if \(!_qaEditId\) _pmAutoNumber\(spec\.coll, data\);/.test(src),
     'the form pre-fill is a convenience on top of the save-time rule, not a replacement for it');
}

// ══ what the consolidation would do, before it does it ═════════════════════════════════════════
console.log('\nConsolidating says exactly what it will change\n');
{
  const A = api(reg(87, 88, 90, 92, 95, 99, 100));
  const p = A.plan(PID);
  ok('a gappy register maps onto 1..N in the order it is displayed',
     p.map(m => m.from + '\u2192' + m.to).join(' ') === '87→1 88→2 90→3 92→4 95→5 99→6 100→7',
     'got ' + p.map(m => m.from + '\u2192' + m.to).join(' '));

  const B = api(reg(1, 2, 3));
  ok('a register that already reads 1, 2, 3 has nothing to change',
     B.plan(PID).length === 0, 'got ' + JSON.stringify(B.plan(PID).map(m => m.from + '->' + m.to)));

  const C = api(reg(1, 5, 3));
  const cp = C.plan(PID);
  ok('only the rows that actually move are listed',
     cp.length === 2 && cp.every(m => m.from !== m.to),
     'got ' + JSON.stringify(cp.map(m => m.from + '->' + m.to)) +
     ' — 1 is already 1 and must not appear in a preview of changes');

  const D = api(reg(9, 87, null, 100));
  const dp = D.plan(PID);
  ok('an unnumbered plan is given one, and sorts last',
     dp.length === 4 && dp[3].from === '' && dp[3].to === '4',
     'got ' + JSON.stringify(dp.map(m => (m.from || '(blank)') + '->' + m.to)));

  /* Stored back-to-front AND numerically apart, so the two orders give different answers.
     Following the STORED order would map 100 to 1 and 9 to 2 — renumbering by whatever order the
     rows happened to come back from the database, which is not an order anybody has looked at. */
  const E = api(reg(100, 9));
  ok('the mapping follows the DISPLAYED order, not the stored order',
     E.plan(PID).map(m => m.from + '\u2192' + m.to).join(' ') === '9\u21921 100\u21922',
     'got ' + E.plan(PID).map(m => m.from + '\u2192' + m.to).join(' ') +
     ' \u2014 the register shows 9 above 100, so 9 must become 1');

  const F = api(reg(2, 1));
  ok('and a register already in order, however it happens to be stored, moves nothing',
     F.plan(PID).length === 0,
     'got ' + JSON.stringify(F.plan(PID).map(m => m.from + '->' + m.to)) +
     ' \u2014 sorted, 1 is first and 2 is second, which is what they already are');
}

// ══ the safeguards ═════════════════════════════════════════════════════════════════════════════
console.log('\nRewriting an issued number is deliberate, and answerable afterwards\n');
{
  const fn = take('async function pmItpRenumber(', 'pmItpRenumber');
  ok('it is behind manager level', /if \(!_requireLevel\('manager'\)\) return;/.test(fn),
     'this rewrites the whole register, it is not an edit to one plan');
  ok('nothing is written before the preview is confirmed',
     fn.indexOf('const go = await new Promise') < fn.indexOf("method: 'PATCH'"),
     'the mapping must be on screen before the first write, not after it');
  ok('the preview lists every change, old beside new',
     /plan\.map\(m => '<tr/.test(fn) && /_crmEsc\(m\.from \|\| '\\u2014'\)/.test(fn) && /_crmEsc\(m\.to\)/.test(fn));
  ok('cancelling writes nothing', /if \(!go\) return;/.test(fn));
  ok('an empty register is refused rather than "successfully" renumbered',
     /if \(!all\.length\)/.test(fn));
  ok('and a register already in order says so instead of rewriting it',
     /if \(!plan\.length\)/.test(fn));

  /* Match the WHOLE guarded statement, not just the assignment. A regex for
     `body.itpNoPrev = m.from;` alone still matches `if (false) body.itpNoPrev = m.from;` — it would
     pass on the line after somebody disabled it, which is the one thing it exists to notice. Same
     reason the audit assertion below carries its `if (ok)`. */
  ok('the number the plan was ISSUED under is kept, and only when not already recorded',
     /if \(!String\(m\.row\.itpNoPrev \|\| ''\)\.trim\(\) && m\.from\) body\.itpNoPrev = m\.from;/.test(fn),
     'the paperwork was issued under the FIRST number; a later consolidation must not replace it ' +
     'with whatever the register happened to read last week, and disabling the line must not pass');
  ok('what is kept is the number it HAD, never the one it is being given',
     /body\.itpNoPrev = m\.from;/.test(fn) && !/body\.itpNoPrev = m\.to;/.test(fn));
  ok('the whole thing lands in the audit log',
     /if \(ok\) tkAudit\('ITP register renumbered'/.test(fn),
     'the `if (ok)` is part of the assertion: without it this passes on an audit call somebody has ' +
     'switched off');
  ok('failures are reported rather than swallowed',
     /bad\.push\(/.test(fn) && /bad\.length \? toast/.test(fn.replace(/\s+/g, ' ')) ||
     /if \(bad\.length\) toast/.test(fn));

  ok('nothing but the number is touched',
     /Object\.assign\(\{\}, m\.row, \{ itpNo: m\.to \}\)/.test(fn),
     'the row is spread and only itpNo replaced — status, dates, files and signatures ride through ' +
     'unchanged, and the server-side keep-if-unsaid guard covers anything the row is missing');
}

// ══ the trail is visible, not only stored ══════════════════════════════════════════════════════
console.log('\nThe original number stays on the screen\n');
{
  ok('the register prints the issued number under the current one',
     /_t\('was'\) \+ ' ' \+ _pmEsc\(r\.itpNoPrev\)/.test(src),
     'a consolidated register showing only its new numbers cannot be reconciled against a signed ' +
     'plan or a contractor transmittal');
  ok('and only where it actually differs',
     /String\(r\.itpNoPrev\)\.trim\(\) !== String\(r\.itpNo \|\| ''\)\.trim\(\)/.test(src),
     'printing "was 7" under the number 7 is noise');
  ok('the button is offered only to those who may use it',
     /_pmSeeAll\(\) && itp\.length > 1/.test(src));
  ok('and is absent when there is nothing to renumber',
     /itp\.length > 1\s*\n?\s*\?/.test(src) || /itp\.length > 1$/m.test(src.split('\n').find(l => l.indexOf('itp.length > 1') >= 0) || ''),
     'a control whose press changes nothing is noise');
}

console.log('\n  ' + pass + ' passed, ' + fail + ' failed\n');
process.exit(fail ? 1 : 0);
