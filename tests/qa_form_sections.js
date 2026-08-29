/* A long form split into sections must still SAVE every field it collects.
 *
 * The Estimate form asks forty-one questions in one flat column. Grouping them is layout — but the
 * form renderer had no idea what a section was, and three separate places walk `spec.fields`
 * assuming every entry is a field with a `k`:
 *
 *   the renderer      a marker rendered as an input would produce <input id="qa-undefined">
 *   the save loop     `data[f.k] = v` on a marker writes data[undefined] into EVERY saved record
 *   the required gate `data[spec.fields[0].k]` — a spec opening with a marker would test
 *                     data[undefined], find it blank, and reject every save; or, worse, be given a
 *                     value and wave a blank record through
 *
 * None of those would throw. So this test EXECUTES _qaGroup rather than grepping for it, and reads
 * the est_projects spec out of the file to prove no field was lost in the reshuffle — a dropped
 * field is one that silently stops being saved.
 *
 *   node tests/qa_form_sections.js
 */
const fs = require('fs');
const path = require('path');

const src = fs.readFileSync(path.join(__dirname, '..', 'templates', 'index.html'), 'utf8');

let pass = 0, fail = 0;
const ok = (n, c, extra) => {
  if (c) { pass++; console.log('  ok    ' + n); }
  else { fail++; console.log('  FAIL  ' + n + (extra ? '\n        ' + extra : '')); }
};

console.log('\nA sectioned form still collects every field\n');

// ── lift _qaGroup out of the page and run it ────────────────────────────────────────────────────
const start = src.indexOf('function _qaGroup(fields, html) {');
if (start < 0) { console.error('_qaGroup is not in the page.'); process.exit(2); }
const end = src.indexOf('\n}\n', start);
const body = src.slice(start, end + 3);
// _t and _crmEsc are the page's; the grouping logic is what is under test.
const _qaGroup = new Function('_t', '_crmEsc', body + '; return _qaGroup;')(
  s => s, s => String(s).replace(/&/g, '&amp;').replace(/</g, '&lt;'));

const F = [
  { k: 'title' }, { k: 'client' },
  { sec: 'The customer' }, { k: 'addr' }, { k: 'mst' },
  { sec: 'The job', open: true }, { k: 'site' },
];
const H = F.map(f => (f.sec ? '' : '<i id="' + f.k + '">'));
const out = _qaGroup(F, H);

ok('every field survives the grouping', ['title', 'client', 'addr', 'mst', 'site']
  .every(k => out.indexOf('<i id="' + k + '">') >= 0),
  'a field vanished: ' + out);

ok('the fields before the first marker stay outside any section',
  out.indexOf('<i id="title">') < out.indexOf('<details'),
  'the first fields were swallowed into a collapsed section');

ok('each marker opens a section', (out.match(/<details/g) || []).length === 2);

ok('every section is closed', (out.match(/<details/g) || []).length ===
  (out.match(/<\/details>/g) || []).length,
  'unbalanced <details> — the rest of the form renders inside the last section');

ok('every section body is closed', (out.match(/<div class="qa-sec-b">/g) || []).length ===
  2 && (out.match(/<\/div><\/details>/g) || []).length === 2);

ok('a section marked open renders open', /<details class="qa-sec" open>/.test(out));
ok('a section not marked open renders collapsed',
  /<details class="qa-sec"><summary/.test(out));

ok('the section title is shown', out.indexOf('The customer') >= 0 && out.indexOf('The job') >= 0);

ok('a marker never becomes an input', out.indexOf('qa-undefined') < 0 &&
  out.indexOf('undefined') < 0, out);

// a spec with no sections at all must be untouched — every other form in the app is one
const plain = _qaGroup([{ k: 'a' }, { k: 'b' }], ['<i id="a">', '<i id="b">']);
ok('a form with no sections is unchanged', plain === '<i id="a"><i id="b">', plain);

// ── the three walkers that would treat a marker as a field ──────────────────────────────────────
ok('the renderer skips markers',
  /if \(f\.sec\) return '';/.test(src),
  'the field map has no marker branch — a heading would render as an input');

ok('the save loop skips markers',
  /if \(f\.sec\) return;\s*\/\/ a section heading has no `k`/.test(src),
  'tkQuickAddSave would write data[undefined] into every saved record');

ok('the required-field gate takes the first REAL field',
  /const _req = spec\.fields\.filter\(f => !f\.sec\)\[0\];/.test(src),
  'the gate still reads spec.fields[0], which may be a section marker');

// ── nothing was lost when the Estimate form was reshuffled ──────────────────────────────────────
const specStart = src.indexOf("title: 'Estimate', coll: 'est_projects'");
if (specStart < 0) { console.error('The est_projects spec moved.'); process.exit(2); }
const specEnd = src.indexOf("  },", src.indexOf("{ k: 'note', label: 'Notes', type: 'textarea' }]", specStart));
const spec = src.slice(specStart, specEnd);
const keys = (spec.match(/\{ k: '(\w+)'/g) || []).map(m => m.slice(6, -1));

/* Written out rather than counted. A count passes while two fields swap identities, and the whole
   point of the reshuffle was moving them around. */
const EXPECTED = [
  'title', 'client', 'costingType', 'dueDate', 'estimator',
  'clientAddress', 'clientTaxCode', 'clientAttn', 'clientContact', 'clientRef',
  'projectName', 'projectCode', 'site', 'contractType', 'pmProjectId',
  'scope', 'exclusions', 'exclusionsNone', 'assumptions',
  'siteOverhead', 'overheadPct', 'riskPct', 'profitPct', 'profitBasis',
  'quoteNo', 'issueDate', 'validUntil', 'validityDays', 'amountInWords', 'intro',
  'preparedBy', 'approvedBy',
  'bankName', 'bankAccount', 'bankSwift',
  'outcomeReason', 'decidedOn', 'quotedPrice', 'winningPrice',
  'estNo', 'status', 'dateIssued', 'note',
];
const missing = EXPECTED.filter(k => keys.indexOf(k) < 0);
const surprise = keys.filter(k => EXPECTED.indexOf(k) < 0);
ok('every Estimate field is still on the form', missing.length === 0,
  'LOST — these fields would silently stop saving: ' + missing.join(', '));
ok('no field was invented', surprise.length === 0, surprise.join(', '));
ok('no field is asked for twice', keys.length === new Set(keys).size,
  'a duplicate id means one of the two never reaches the record');

ok('the five that open a bid come first',
  keys.slice(0, 5).join(',') === 'title,client,costingType,dueDate,estimator',
  'got: ' + keys.slice(0, 5).join(','));

/* The save gate treats the FIRST field as the required one. If the reshuffle put something
   optional there, creating a tender would demand it. */
ok('the required field is still the job name', keys[0] === 'title');

const secs = (spec.match(/\{ sec: '/g) || []).length;
ok('the rest is grouped into sections', secs >= 5, 'only ' + secs + ' section(s)');

console.log('\n  ' + pass + ' passed, ' + fail + ' failed\n');
process.exit(fail ? 1 : 0);
