/* The Daily Report's printed column headings must actually be visible.
 *
 * This defect has landed TWICE, in two different renderers, and both times the exported PDF came
 * out with every column-heading row BLANK — a white band where "Report Items / Quantity / Unit /
 * Notes" should be. It is invisible in review because nothing about the markup looks wrong, and it
 * is invisible in the app because the bug is only in the export.
 *
 * The cause is one rule in the global theme:
 *
 *     th{background:transparent !important; border-bottom:1px solid var(--line) !important;}
 *
 * It exists so ordinary portal tables have flat headers, and it is on the ELEMENT — so it applies
 * to any `th` the daily report prints, however the report styles it. The report's header is a solid
 * green band with WHITE text, so losing the background does not merely change a colour: it makes the
 * text invisible against the page.
 *
 *   attempt 1  a stylesheet rule `.dr-table th { background:#00B060 }`  — lost to the !important
 *   attempt 2  an inline `style="background:#00B060"`                   — lost to it as well,
 *              because a stylesheet !important beats a plain inline declaration
 *
 * Only `!important` ON THE INLINE STYLE wins, which is what the quotation letterhead already does
 * and what this asserts.
 *
 * The second half of this file matters as much as the first: it checks that the global rule is still
 * there. If somebody removes it, this workaround is no longer needed, and a test that kept passing
 * would be asserting a defence against a problem that no longer exists — a check examining nothing.
 * It fails instead, so the decision gets made rather than inherited.
 *
 *   node tests/dr_print_header_visible.js
 */
const fs = require('fs');
const path = require('path');

const src = fs.readFileSync(path.join(__dirname, '..', 'templates', 'index.html'), 'utf8');

let pass = 0, fail = 0;
const ok = (n, c, extra) => {
  if (c) { pass++; console.log('  ok    ' + n); }
  else { fail++; console.log('  FAIL  ' + n + (extra ? '\n        ' + extra : '')); }
};

console.log('\nThe printed daily report has visible column headings\n');

// ── the premise: the rule this guards against is still in the stylesheet ────────────────────────
const GLOBAL = /\bth\s*\{[^}]*background\s*:\s*transparent\s*!important/;
ok('the global `th{background:transparent !important}` rule is still present',
   GLOBAL.test(src),
   'It is gone. That is good news, but it means the !important below is no longer load-bearing: ' +
   'check whether the daily report still needs it, and update or delete this file deliberately.');

// ── the header builder, and what it must declare ────────────────────────────────────────────────
const m = src.match(/function _drpTh\(t, num\)\s*\{([\s\S]*?)\n\}/);
ok('the print renderer\'s header builder _drpTh exists', !!m,
   'It was renamed or removed. Point this test at whatever builds the printed <th> now — do not ' +
   'delete the test, because the collision it guards is a property of the global stylesheet, not ' +
   'of this function.');

if (m) {
  // The style string is BUILT BY CONCATENATION — `'…background:' + _DRP.green + ' !important;…'` —
  // so a regex looking for "background:" followed by "!important" has to see past the quotes and
  // the `+`. Flattening the fragments first is what makes this check actually look at the
  // declaration rather than at one half of it. (The first version of this test matched
  // /background:[^;'"]*!important/ and failed on correct code, because the quote ended the class.)
  const body = m[1].replace(/['"]\s*\+\s*/g, '').replace(/\s*\+\s*['"]/g, '').replace(/['"]/g, '');
  ok('it emits a <th>', /<th\b/.test(body));
  // The two declarations that must survive the cascade. Written as "background:<something>
  // !important" so the colour can change without this test caring.
  ok('its background is declared !important', /background\s*:[^;'"]*!important/.test(body),
     'A plain `background:` here loses to the global rule and the band prints white.');
  ok('its text colour is declared !important', /color\s*:[^;'"]*!important/.test(body),
     'White text on a band that lost its background is invisible either way — pin both.');
  // The global rule also forces a border-bottom, which draws a hairline through the green band.
  ok('it overrides the forced border-bottom too',
     /border-bottom\s*:\s*none\s*!important/.test(body),
     'The same global rule sets `border-bottom: … !important`, which prints a line across the ' +
     'green header band.');
  // The portal's own th styling is uppercase, letter-spaced and grey. That is right for a register
  // and wrong for this document, and it is NOT !important — so it is reset plainly here. Asserted
  // because losing it is a silent change in what the client receives.
  ok('it resets the portal\'s uppercase register styling',
     /text-transform\s*:\s*none/.test(body) && /letter-spacing\s*:\s*normal/.test(body),
     'Without these the printed headings come out UPPERCASE AND LETTER-SPACED like an internal ' +
     'register rather than like the report the client has always received.');
}

// ── and the screen's own table, which hit attempt 1 ─────────────────────────────────────────────
// The screen now uses the portal's plain `.table-wrap` table on purpose, so it has no green band to
// lose. Assert that, so a future change back to a coloured on-screen header has to come past here.
ok('the on-screen report uses the portal table rather than a coloured header of its own',
   !/\.dr-table\s+th\s*\{/.test(src),
   'A `.dr-table th` rule is back. If the screen needs a coloured header again it has to win the ' +
   'same cascade fight — add the !important and extend this test to cover it.');

console.log('\n  ' + pass + ' passed, ' + fail + ' failed\n');
process.exit(fail ? 1 : 0);
