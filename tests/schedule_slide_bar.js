/* The Gantt's inset slide bar must be decided by what the ENGINE DID, not by what it claims to support.
 *
 * The first version gated the whole thing on `@supports selector(::-webkit-scrollbar)`, to stop
 * Firefox — which cannot hide one axis — from ending up with two bars. That test asks whether the
 * selector PARSES, not whether the rule is HONOURED, and it was only ever verified in a Blink
 * browser. Reported from a Safari desktop: the native full-width bar was still there AND the inset
 * one never appeared, because the whole block had been skipped. A capability test told us nothing
 * about the outcome.
 *
 * So the rules now apply everywhere and _schXBar measures whether the native bar actually went away,
 * standing down when it did not. These assertions exist to stop the gate coming back.
 *
 *   node tests/schedule_slide_bar.js
 */
const fs = require('fs');
const path = require('path');

const src = fs.readFileSync(path.join(__dirname, '..', 'templates', 'index.html'), 'utf8');

/* Scan the CODE, not the prose about it. The first run of this file failed on its own evidence: the
   comment explaining why the @supports gate was REMOVED contains the words `@supports
   selector(::-webkit-scrollbar)`, and the regex happily found them. A check that reads comments is
   measuring the wrong thing in the most misleading direction available — it convicts the fix. */
const code = src.replace(/\/\*[\s\S]*?\*\//g, '').replace(/(^|[^:])\/\/.*$/gm, '$1');

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

console.log('\nThe timeline slide bar decides from the outcome, not the browser\n');

// ── the capability gate must not return ─────────────────────────────────────────────────────────
ok('no @supports gate on ::-webkit-scrollbar',
   !/@supports[^{]*::-webkit-scrollbar/.test(code),
   'a Safari desktop got the native full-width bar AND no inset one, because the block was skipped');

// ── CSS must not own the row's display; JS does ─────────────────────────────────────────────────
ok('.sch-xrow starts hidden', /\.sch-xrow\{display:none\}/.test(code));
ok('no CSS rule turns .sch-xrow on',
   !/\.sch-xrow\{[^}]*display:\s*flex/.test(code),
   'if CSS shows the row, an engine that kept its own bar renders two');

// ── the JS side ─────────────────────────────────────────────────────────────────────────────────
const fn = take('function _schXBar(', '_schXBar');

ok('_schXBar measures the native horizontal bar',
   /vp\.offsetHeight\s*-\s*vp\.clientHeight\s*>\s*0/.test(fn),
   'without this it cannot tell whether ::-webkit-scrollbar{height:0} was honoured');
ok('and stands down when the engine kept it',
   /vp\.offsetHeight\s*-\s*vp\.clientHeight\s*>\s*0[^;]*\)\s*\{\s*row\.style\.display\s*=\s*'none'/.test(fn),
   'it must hide our bar rather than add a second one');
ok('_schXBar is what turns the row on',
   /row\.style\.display\s*=\s*'flex'/.test(fn));
ok('a hidden pane is not mistaken for "nothing to scroll"',
   /if \(!vp\.clientWidth\) return;/.test(fn),
   'a pane off screen measures zero, and pmSchedTab only flips display — the row would never come back');

// ── the two gates must say the same thing ───────────────────────────────────────────────────────
/* If the stylesheet suppresses the native bar somewhere the JS declines to put one back, the user
   gets no horizontal control at all. These two conditions have to be kept identical by hand, so
   assert they are. */
const cssGate = /@media \(min-width:821px\) and \(pointer:fine\)\{/.test(code);
ok('the stylesheet gate is min-width:821px and pointer:fine', cssGate);
ok('_schXBar mirrors that exact condition',
   /matchMedia\('\(min-width:821px\) and \(pointer:fine\)'\)/.test(fn),
   'CSS and JS disagreeing gives either a suppressed bar with no replacement, or two bars');

// ── the geometry contract ───────────────────────────────────────────────────────────────────────
ok('the inner width is sized from measured geometry, not plotW',
   /bar\.clientWidth \+ max/.test(fn),
   'matching the two scrollable distances is what makes a drag land where the eye expects');
ok('the gutter spacer is bound to LABW',
   /class="sch-xgut" style="width:' \+ LABW \+ 'px"/.test(src));

console.log('\n  ' + pass + ' passed, ' + fail + ' failed\n');
process.exit(fail ? 1 : 0);
