/* A sort arrow must never be separated from its label by a BREAKING space.
 *
 * Reported from a screenshot: the Work Breakdown Structure's header rendered stacked vertically.
 * Measured in the browser — every `th` was 55px tall with TWO line boxes, the label on the first and
 * the bare "⇅" on the second. The header cells are 11px uppercase with .6px letter-spacing, and the
 * WBS column had 27px of content width; the plain space in `' \u21C5'` was a legal break opportunity,
 * so the glyph wrapped and every other header in the row grew to match it.
 *
 * Nothing about it looked wrong in the source. It is one character.
 *
 * Two renderers carry the same header: _pmTable (every Projects / PMC register) and the eng_* one.
 * They were written apart and both had it, so assert BOTH — fixing one and leaving the other is the
 * shape this repo keeps repeating.
 *
 *   node tests/table_header_one_line.js
 */
const fs = require('fs');
const path = require('path');

const src = fs.readFileSync(path.join(__dirname, '..', 'templates', 'index.html'), 'utf8');

let pass = 0, fail = 0;
const ok = (n, c, extra) => {
  if (c) { pass++; console.log('  ok    ' + n); }
  else { fail++; console.log('  FAIL  ' + n + (extra ? '\n        ' + extra : '')); }
};

/* Scan the CODE. The comment that explains the fix contains the words "a plain space", and a regex
   looking for the defect would happily convict the explanation. */
const code = src.replace(/\/\*[\s\S]*?\*\//g, '').replace(/(^|[^:])\/\/.*$/gm, '$1');

console.log('\nA sort arrow stays on its label\'s line\n');

// The glyphs, written both ways in this file: \uXXXX escapes in _pmTable, literals in the eng one.
const ARROWS = ['\\u21C5', '\\u25B2', '\\u25BC', '\u21C5', '\u25B2', '\u25BC'];

// -- the defect itself ---------------------------------------------------------------------------
ARROWS.forEach(a => {
  const bad = new RegExp("' " + a.replace(/[\\^$*+?.()|[\]{}]/g, '\\$&'));
  ok('no arrow is introduced by a plain space: ' + JSON.stringify(a), !bad.test(code),
     'that space is a wrap opportunity — the glyph drops to its own line and the whole header row follows');
});

// -- and the fix is present in BOTH renderers, not just the one that was reported ------------------
const RENDERERS = [
  ['_pmTable', "const arrow = active ? (so.dir > 0 ? '\\u00A0\\u25B2'"],
  ['the eng_* register', "const arrow = active ? (so.dir > 0 ? '\\u00A0\u25B2'"],
];
RENDERERS.forEach(r => ok(r[0] + ' binds the active arrow with \\u00A0', src.indexOf(r[1]) >= 0,
                          'searched for: ' + r[1]));
ok('_pmTable binds the inactive arrow too',
   src.indexOf('font-weight:400">\\u00A0\\u21C5</span>') >= 0,
   'the idle \u21C5 is the one on screen for every column that is not the sort key — i.e. almost all of them');
ok('and so does the eng_* register',
   src.indexOf('font-weight:400">\\u00A0\u21C5</span>') >= 0);

// -- every SORT-HEADER arrow is accounted for -------------------------------------------------------
/* State the predicate the count actually holds. The first version of this block counted every arrow
   GLYPH in the file and failed on five that have nothing to do with sorting — "\u25B2 3 vs last
   month" on a KPI card, its two _VI translation keys, and an attendance percentage. \u25B2 means two
   different things here, and a count that cannot tell them apart measures the wrong population.
   So count the construct instead: a sort header is emitted by `const arrow = active ? …`. */
{
  const decls = code.split('const arrow = active ?').slice(1).map(t => t.slice(0, 220));
  ok('exactly the two known renderers emit sort arrows (' + decls.length + ' found)',
     decls.length === 2,
     'a third table renderer needs the same \\u00A0 — add it above rather than relaxing this count');
  decls.forEach((d, i) => {
    ok('renderer ' + (i + 1) + ' binds every one of its arrows with a non-breaking space',
       !/'\s[\u21C5\u25B2\u25BC]/.test(d) && !/'\s\\u2(1C5|5B2|5BC)/.test(d),
       d.replace(/\s+/g, ' ').slice(0, 160));
    ok('renderer ' + (i + 1) + ' actually uses \\u00A0', /\\u00A0/.test(d) || /\u00A0/.test(d));
  });
}

// -- the stylesheet must not be the thing holding it together --------------------------------------
ok('the fix does not depend on a global th{white-space:nowrap}',
   !/\bth\{[^}]*white-space:\s*nowrap/.test(code),
   'that would stop legitimate wrapping of long labels and widen tables that fit today — the arrow ' +
   'is the only thing that must not break, and \\u00A0 says exactly that and nothing more');

console.log('\n  ' + pass + ' passed, ' + fail + ' failed\n');
process.exit(fail ? 1 : 0);
