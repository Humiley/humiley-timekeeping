/* The win/loss reasons the FORM offers must be the ones the SERVER accepts.
 *
 * The list exists twice — tender_outcome.REASONS in Python, _EST_REASONS in the page — because the
 * form is rendered before any endpoint is called and cannot wait for the server to tell it what a
 * dropdown contains.
 *
 * That duplication has exactly one failure mode, and it is total: the server REFUSES a reason that
 * is not on its list, so a single option the page offers and the server does not know turns every
 * save from that dropdown into a 400 the estimator cannot do anything about. It would not be caught
 * by either side's own tests — each list is internally consistent — so it is caught here, by
 * comparing them.
 *
 * Order matters too. The list is presented to a person choosing from it, and the two sides drifting
 * into different orders is the same edit half-applied.
 *
 *   node tests/tender_reasons_cross_language.js
 */
const fs = require('fs');
const path = require('path');

const root = path.join(__dirname, '..');
const page = fs.readFileSync(path.join(root, 'templates', 'index.html'), 'utf8');
const py = fs.readFileSync(path.join(root, 'tender_outcome.py'), 'utf8');

let pass = 0, fail = 0;
const ok = (n, c, extra) => {
  if (c) { pass++; console.log('  ok    ' + n); }
  else { fail++; console.log('  FAIL  ' + n + (extra ? '\n        ' + extra : '')); }
};

console.log('\nThe reasons the form offers are the reasons the server accepts\n');

// ── the browser's list ──────────────────────────────────────────────────────────────────────────
const jsm = page.match(/const _EST_REASONS = \[([\s\S]*?)\];/);
if (!jsm) { console.error('_EST_REASONS is not in the page.'); process.exit(2); }
const js = (jsm[1].match(/'((?:[^'\\]|\\.)*)'/g) || []).map(x => x.slice(1, -1).replace(/\\'/g, "'"));

// ── the server's list ───────────────────────────────────────────────────────────────────────────
const pym = py.match(/^REASONS = \(([\s\S]*?)^\)/m);
if (!pym) { console.error('REASONS is not in tender_outcome.py.'); process.exit(2); }
const pyl = (pym[1].match(/"((?:[^"\\]|\\.)*)"/g) || []).map(x => x.slice(1, -1));

/* Both lists must be non-empty before comparing them. Two empty arrays are equal, and a regex that
   silently matched nothing would make this whole file report success while checking nothing —
   which is the defect this repo has hit more than once. */
ok('the page really has a list', js.length > 0, 'parsed 0 reasons from _EST_REASONS');
ok('the server really has a list', pyl.length > 0, 'parsed 0 reasons from REASONS');
ok('they are the same length', js.length === pyl.length,
   'page ' + js.length + ' vs server ' + pyl.length);

const onlyPage = js.filter(x => pyl.indexOf(x) < 0);
const onlyServer = pyl.filter(x => js.indexOf(x) < 0);
ok('every reason the form offers, the server accepts', onlyPage.length === 0,
   'the server would 400 every save choosing: ' + onlyPage.join(' | '));
ok('every reason the server accepts, the form offers', onlyServer.length === 0,
   'unreachable from the UI: ' + onlyServer.join(' | '));
ok('they are in the same order', js.join('␟') === pyl.join('␟'),
   '\n        page:   ' + js.join(' | ') + '\n        server: ' + pyl.join(' | '));

console.log('\n  ' + js.length + ' reasons compared');
console.log('  ' + pass + ' passed, ' + fail + ' failed\n');
process.exit(fail ? 1 : 0);
