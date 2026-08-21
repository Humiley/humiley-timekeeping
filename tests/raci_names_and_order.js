/* The RACI matrix has to name the PERSON, and list deliverables in order.
 *
 * Reported from the live portal: a four-person team rendered as four columns all reading "NGUYEN".
 * The header took `name.split(' ')[0]` — the FIRST token — which in Vietnamese name order is the
 * FAMILY name, carried by roughly two in five people in the country. The matrix exists to say who
 * is Responsible for what; four identical columns cannot say it.
 *
 * The register holds BOTH name orders — _pmSamePerson exists because rows read "Trung Nguyen"
 * while employee records read "Nguyen Van Trung" — so neither end can be trusted blindly, and a
 * naive "take the last token" breaks the Western-order rows instead of the Vietnamese ones.
 *
 *   node tests/raci_names_and_order.js
 */
const fs = require('fs');
const path = require('path');

const src = fs.readFileSync(path.join(__dirname, '..', 'templates', 'index.html'), 'utf8');

let pass = 0, fail = 0;
const ok = (n, c, extra) => {
  if (c) { pass++; console.log('  ok    ' + n); }
  else { fail++; console.log('  FAIL  ' + n + (extra ? '\n        ' + extra : '')); }
};
const eq = (n, got, want) => ok(n, JSON.stringify(got) === JSON.stringify(want),
  'got ' + JSON.stringify(got) + '\n        want ' + JSON.stringify(want));

/* ── extract the helpers from the shipping file ─────────────────────────────── */
const grab = (startMark, endMark, what) => {
  const i = src.indexOf(startMark), j = src.indexOf(endMark, i);
  if (i < 0 || j < 0) { console.error('Could not find ' + what + ' — update the markers, do NOT delete this test.'); process.exit(2); }
  return src.slice(i, j);
};
const tokens = grab('function _pmNameTokens(', 'function _pmSamePerson(', '_pmNameTokens');
const names = grab('const _VN_FAMILY =', 'function _pmRaciMembers(', '_pmGivenName/_pmShortNames');
const cmp = grab('function _wbsCmp(', '\n}', '_wbsCmp') + '\n}';

const api = {};
new Function(tokens + cmp + names + '\nObject.assign(this, { _pmGivenName, _pmShortNames, _wbsCmp, _VN_FAMILY });').call(api);
const { _pmGivenName, _pmShortNames, _wbsCmp } = api;

console.log('\nRACI matrix — names and order\n');

/* ── Vietnamese order: family · middle · GIVEN ──────────────────────────────── */
eq('Nguyen Van Trung -> Trung', _pmGivenName('Nguyen Van Trung'), 'Trung');
eq('Nguyen Anh Giang -> Giang', _pmGivenName('Nguyen Anh Giang'), 'Giang');
eq('Nguyen An Dung -> Dung', _pmGivenName('Nguyen An Dung'), 'Dung');
eq('Tran Thi Mai Anh -> Anh', _pmGivenName('Tran Thi Mai Anh'), 'Anh');
eq('accents do not confuse the family test', _pmGivenName('Nguyễn Văn Trung'), 'Trung');
eq('Đặng is recognised as a family name', _pmGivenName('Đặng Quốc Bảo'), 'Bảo');

/* ── Western order, which the register also contains ────────────────────────── */
eq('Trung Nguyen -> Trung', _pmGivenName('Trung Nguyen'), 'Trung');
eq('Giang Nguyen -> Giang', _pmGivenName('Giang Nguyen'), 'Giang');
eq('Mary Tran -> Mary', _pmGivenName('Mary Tran'), 'Mary');

/* ── the bug itself: never the bare family name ─────────────────────────────── */
['Nguyen Van Trung', 'Nguyen Anh Giang', 'Nguyen An Dung', 'Trung Nguyen'].forEach(n => {
  ok('"' + n + '" never renders as "Nguyen"', _pmGivenName(n).toLowerCase() !== 'nguyen', _pmGivenName(n));
});
// the whole point, stated as the screenshot stated it
const TEAM = ['Nguyen Van Trung', 'Nguyen Anh Giang', 'Nguyen An Dung', 'Nguyen Duc Huy'];
const shorts = _pmShortNames(TEAM);
eq('four Nguyens become four distinct columns', shorts, ['Trung', 'Giang', 'Dung', 'Huy']);
ok('and none of them is "Nguyen"', shorts.every(s => s.toLowerCase() !== 'nguyen'));
eq('the four columns are unique', new Set(shorts.map(s => s.toLowerCase())).size, 4);

/* ── a collision on the GIVEN name is the same failure one step on ──────────── */
const DUP = ['Nguyen Van Trung', 'Tran Quoc Trung'];
const dupShort = _pmShortNames(DUP);
ok('two Trungs are told apart', dupShort[0] !== dupShort[1], JSON.stringify(dupShort));
ok('both still lead with the given name', dupShort.every(s => /^Trung/.test(s)), JSON.stringify(dupShort));
eq('a unique given name stays short', _pmShortNames(['Nguyen Van Trung', 'Tran Thi Mai']), ['Trung', 'Mai']);

/* ── junk in, no crash ──────────────────────────────────────────────────────── */
[undefined, null, '', '   ', 'Madonna', 'X'].forEach(v => {
  let threw = false, out;
  try { out = _pmGivenName(v); _pmShortNames([v]); } catch (e) { threw = true; }
  ok('junk name (' + JSON.stringify(v) + ') does not throw', !threw);
});
eq('a single-token name is returned as-is', _pmGivenName('Madonna'), 'Madonna');

/* ── deliverable order: numbers first, then letters ─────────────────────────── */
const REPORTED = ['6', 'E', '2', 'F', '1', '5', 'A', 'C', '4', 'D', 'B', '3'];
eq('the reported deliverable order sorts correctly', REPORTED.slice().sort(_wbsCmp),
   ['1', '2', '3', '4', '5', '6', 'A', 'B', 'C', 'D', 'E', 'F']);

/* ── the shipping code actually uses all of this ────────────────────────────── */
const raci = src.slice(src.indexOf('function _pmRaciMatrix('), src.indexOf('function pmRaciCycle('));
ok('the RACI matrix function was found', raci.length > 100);
ok('the header no longer takes token [0]', !/m\.split\(' '\)\[0\]/.test(raci),
   "split(' ')[0] is the family name in Vietnamese order");
ok('the header renders through _pmShortNames', /_pmShortNames\(members\)/.test(raci));
ok('the full name is kept on hover', /title="' \+ _pmEsc\(m\)/.test(raci));
ok('deliverables are sorted before rendering', /\.sort\(\(a, b\) => _wbsCmp\(/.test(raci));
ok('the sort does not mutate the shared register', /_pmScope\(_HR\.pm_deliverables\)\.slice\(\)/.test(raci),
   'sorting in place would reorder _HR.pm_deliverables for every other view');

console.log('\n' + pass + ' passed, ' + fail + ' failed\n');
process.exit(fail ? 1 : 0);
