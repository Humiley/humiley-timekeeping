// The comparison a user reads on screen and the one stored in the record must be the same answer.
//
// There are two implementations of "what moved between these two prices": tender.compare_revisions
// in Python, and _tndDiff in the page. The page renders the tab; the server's copy is what the
// summary endpoint returns and what anybody reads back later. They were keyed identically and
// identically wrong — keyed on id alone, dropping id-less lines — and once the server was fixed the
// page would have kept quietly disagreeing with it. A diff that says a line vanished in one place
// and says "unexplained" in the other is worse than either answer on its own.
//
// So this does not re-state the expected numbers in JavaScript. It runs BOTH implementations over
// the same fixtures and compares them. If either side changes its keying, its sort or its
// arithmetic without the other, this fails.
const fs = require('fs');
const path = require('path');
const { execFileSync } = require('child_process');

const ROOT = path.join(__dirname, '..');

// --- lift _tndDiff out of the page, by brace matching rather than by a line number ---------------
const page = fs.readFileSync(path.join(ROOT, 'templates', 'index.html'), 'utf8');
const start = page.indexOf('function _tndDiff(before, after) {');
if (start < 0) {
  console.error('_tndDiff is no longer in templates/index.html under that name.');
  console.error('If it was renamed, rename it here too — do not delete this test: the two');
  console.error('implementations disagreeing silently is the whole thing it exists to catch.');
  process.exit(1);
}
let depth = 0, end = -1;
for (let i = page.indexOf('{', start); i < page.length; i++) {
  if (page[i] === '{') depth++;
  else if (page[i] === '}' && --depth === 0) { end = i + 1; break; }
}
const _tndDiff = new Function(page.slice(start, end) + '; return _tndDiff;')();

// --- fixtures: the shapes that used to lose a line -----------------------------------------------
const rev = (net, lines, margin) => ({ net, grossMarginPct: margin || 0, lines });
const L = (id, desc, qty, unitCost, net) => ({ id, desc, qty, unitCost, net });

const CASES = {
  'a rate moved': [
    rev(100, [L('L1', 'Pump', 1, 100, 100)]),
    rev(130, [L('L1', 'Pump', 1, 130, 130)]),
  ],
  'two rows share an id': [
    rev(100, [L('L1', 'Pump', 1, 50, 50), L('L1', 'Pump (imported twice)', 1, 50, 50)]),
    rev(60, [L('L1', 'Pump', 1, 60, 60)]),
  ],
  'an id-less line vanished': [
    rev(100, [L('', 'Nameless package', 1, 100, 100)]),
    rev(0, []),
  ],
  'id-less lines merely reordered': [
    rev(150, [L('', 'Alpha', 1, 100, 100), L('', 'Beta', 1, 50, 50)]),
    rev(150, [L('', 'Beta', 1, 50, 50), L('', 'Alpha', 1, 100, 100)]),
  ],
  'neither id nor description': [
    rev(80, [L('', '', 1, 80, 80)]),
    rev(0, []),
  ],
  'two lines moved by exactly the same amount': [   // the tie both sorts have to break identically
    rev(200, [L('B2', 'Beta', 1, 100, 100), L('A1', 'Alpha', 1, 100, 100)]),
    rev(240, [L('B2', 'Beta', 1, 120, 120), L('A1', 'Alpha', 1, 120, 120)]),
  ],
  'a discount no line explains': [
    rev(100, [L('L1', 'Pump', 1, 100, 100)], 25),
    rev(90, [L('L1', 'Pump', 1, 100, 100)], 16.67),
  ],
  'a line added and a line removed at once': [
    rev(100, [L('L1', 'Pump', 1, 100, 100)]),
    rev(140, [L('L2', 'Fan', 1, 140, 140)]),
  ],
  'nothing at all': [rev(0, []), rev(0, [])],
};

// --- the same fixtures through the server's copy -------------------------------------------------
const script = `
import json, sys
sys.path.insert(0, ${JSON.stringify(ROOT)})
import tender
cases = json.load(sys.stdin)
print(json.dumps({k: tender.compare_revisions(a, b) for k, (a, b) in cases.items()}))
`;
const python = JSON.parse(execFileSync('python3', ['-c', script], {
  input: JSON.stringify(CASES), encoding: 'utf8',
}));

// --- compare -------------------------------------------------------------------------------------
// Compared as numbers, not as text: Python writes 100.0 where JSON.stringify writes 100, and a raw
// string compare would fail on a pair of answers that agree perfectly.
const norm = (v) =>
  Array.isArray(v) ? v.map(norm)
  : v && typeof v === 'object'
    ? Object.fromEntries(Object.keys(v).sort().map((k) => [k, norm(v[k])]))
    : typeof v === 'number' ? Math.round(v * 1e6) / 1e6
    : v;

let failed = 0;
for (const [label, [before, after]] of Object.entries(CASES)) {
  const js = norm(_tndDiff(before, after));
  const py = norm(python[label]);
  if (JSON.stringify(js) !== JSON.stringify(py)) {
    failed++;
    console.error(`\nthe screen and the record disagree — ${label}`);
    console.error('  page  :', JSON.stringify(js));
    console.error('  server:', JSON.stringify(py));
  }
}

// Fixtures that produced no rows would let this pass while examining nothing.
const total = Object.values(python).reduce((n, c) => n + c.rows.length, 0);
if (total < 8) {
  console.error(`\nthe fixtures only produced ${total} rows between them — this test is not`);
  console.error('looking at enough movement to prove the two implementations agree.');
  process.exit(1);
}

if (failed) {
  console.error(`\n${failed} of ${Object.keys(CASES).length} cases disagree.`);
  process.exit(1);
}
console.log(`_tndDiff and tender.compare_revisions agree on ${Object.keys(CASES).length} cases (${total} rows).`);
