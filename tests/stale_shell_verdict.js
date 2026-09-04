/* The staleness decision, tested against the REAL function.
 *
 * `_staleVerdict` is lifted verbatim out of templates/index.html and evaluated here, so this file
 * cannot drift into testing a private copy of the logic: change the predicate in the page and this
 * test exercises the change. If the function is renamed or removed, extraction fails loudly rather
 * than silently testing nothing.
 *
 * The case that matters most is `worker current, page old`. The previous implementation compared
 * the service worker's cache name against the server's and nothing else. A worker updates on its
 * own schedule and activates immediately, so a device could hold a CURRENT worker in front of a
 * page loaded before the deploy — every version string agreed, the heal never ran, and the stale
 * screen stayed up. That row is marked below; it is the regression this file exists for.
 */
'use strict';
const fs = require('fs');
const path = require('path');

const HTML = path.join(__dirname, '..', 'templates', 'index.html');
const src = fs.readFileSync(HTML, 'utf8');

function lift(name) {
  const start = src.indexOf('function ' + name + '(');
  if (start === -1) throw new Error('cannot find function ' + name + ' in index.html');
  // Walk braces from the first { after the signature to find the true end of the body.
  const open = src.indexOf('{', start);
  let depth = 0, i = open;
  for (; i < src.length; i++) {
    if (src[i] === '{') depth++;
    else if (src[i] === '}') { depth--; if (depth === 0) { i++; break; } }
  }
  if (depth !== 0) throw new Error('unbalanced braces extracting ' + name);
  return src.slice(start, i);
}

const _staleVerdict = eval('(' + lift('_staleVerdict') + ')');

const NOW = 1787282451;
const OLD = 1787279652;

const cases = [
  // label,                                 serverAge, pageAge, serverBuild, myBuild,   expect
  ['everything current',                    NOW,  NOW,  'v305', 'v305',                 ''],
  ['WORKER CURRENT, PAGE OLD (regression)', NOW,  OLD,  'v305', 'v305',                 'page'],
  ['page old and worker old',               NOW,  OLD,  'v305', 'v304',                 'page'],
  ['page current, worker behind',           NOW,  NOW,  'v305', 'v304',                 'worker'],
  ['worker present but silent',             NOW,  NOW,  'v305', 'silent',               'worker-silent'],
  ['silent worker with a fresh page',       NOW,  NOW,  'v305', 'silent',               'worker-silent'],
  ['no worker yet (first ever load)',       NOW,  NOW,  'v305', 'none',                 ''],
  ['page NEWER than server (clock skew)',   OLD,  NOW,  'v305', 'v305',                 ''],
  ['server age unknown, builds agree',      null, NOW,  'v305', 'v305',                 ''],
  ['page age unknown, builds agree',        NOW,  null, 'v305', 'v305',                 ''],
  ['server build unknown, ages agree',      NOW,  NOW,  '',     'v304',                 ''],
];

let failed = 0;
for (const [label, serverAge, pageAge, serverBuild, myBuild, expect] of cases) {
  const got = _staleVerdict(serverAge, pageAge, serverBuild, myBuild);
  const ok = got === expect;
  if (!ok) failed++;
  // Node's console.log has no width specifiers (%-40s is printed literally, and the argument then
  // lands somewhere else in the line) — pad explicitly so the columns say what they appear to say.
  console.log('  ' + (ok ? 'ok  ' : 'FAIL') + ' ' + label.padEnd(40) +
              ' expected ' + JSON.stringify(expect).padEnd(16) +
              ' got ' + JSON.stringify(got));
}

/* A guard whose own subject can vanish is worthless: prove the truth table is discriminating by
   checking it does not simply return '' (or one constant) for everything. */
const verdicts = new Set(cases.map(c => _staleVerdict(c[1], c[2], c[3], c[4])));
if (verdicts.size < 3) {
  console.log('  FAIL the predicate returned only ' + verdicts.size + ' distinct verdicts across ' +
              cases.length + ' cases — it is not discriminating between them');
  failed++;
}

console.log('\n' + (cases.length - failed) + ' passed, ' + failed + ' failed');
process.exit(failed ? 1 : 0);
