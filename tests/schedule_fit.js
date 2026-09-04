/* "Fit" has to actually fit, and the gutter has to be spendable out of the PANE.
 *
 * plotW is chosen while the HTML string is built — from the number of months and nothing else,
 * because the pane the chart lands in does not exist yet to be measured. So Fit asked for a 520px
 * minimum plot beside a 470px label gutter: 990px of demand, measured against a 914px pane. It
 * overflowed by 76px, and the moment a Gantt overflows the frozen gutter (position:sticky;left:0,
 * opaque background) paints straight over the bars sliding underneath it.
 *
 * That is what "many timeline progress lines are hidden behind the task name columns" was: not a
 * drawing bug, a width the builder was in no position to decide. _schFitPlot decides it again from
 * measured geometry once the pane is real.
 *
 * The arithmetic is testable without a browser, so it is tested with the real numbers off a real
 * screen rather than with round ones invented to match the formula.
 *
 *   node tests/schedule_fit.js
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
  const j = src.indexOf('\nfunction ', i + 10);
  if (j < 0) { console.error('Could not find the end of ' + what + '.'); process.exit(2); }
  return src.slice(i, j);
};

/* The floors come OUT OF THE SHIPPING FILE. The first version of this harness declared its own
   `const _SCH_LAB_MIN = 300, _SCH_PLOT_MIN = 300` and every assertion below then tested the test's
   arithmetic: change the real constants to 400/200 and all thirteen still passed. That is the exact
   defect shape this repo keeps hitting — a check that reports success about something it never
   looked at — committed inside the check written to prevent it. */
const CONSTS = (src.match(/const _SCH_LAB_MIN = \d+, _SCH_PLOT_MIN = \d+;/) || [])[0];
if (!CONSTS) { console.error('Could not find the _SCH_LAB_MIN/_SCH_PLOT_MIN declaration.'); process.exit(2); }

const F = new Function(
  CONSTS + '\n' +
  take('function _schFitLab(', '_schFitLab') +
  take('function _schFitMin(', '_schFitMin') +
  take('function _pmWbsLevel(', '_pmWbsLevel') +
  take('function _pmWbsIndentPx(', '_pmWbsIndentPx') +
  take('function _pmWbsIndent(', '_pmWbsIndent') +
  take('function _pmWbsIndentFor(', '_pmWbsIndentFor') +
  '\nreturn { _schFitLab, _schFitMin, _pmWbsLevel, _pmWbsIndentPx, _pmWbsIndent, _pmWbsIndentFor,' +
  '  LAB_MIN: _SCH_LAB_MIN, PLOT_MIN: _SCH_PLOT_MIN };')();

console.log('\nFit fits, and the gutter is spent out of the pane\n');

// -- the case that was reported ------------------------------------------------------------------
/* Measured in the browser on the screen the complaint came from: a 914px pane, _pdLabW chose 470,
   Fit asked for a 520px plot. 470 + 520 = 990 > 914 -> it scrolled by 76px, and everything that
   scrolled went under the gutter. */
{
  const lab = F._schFitLab(470, 914);
  ok('the reported screen keeps its full 470px gutter', lab === 470,
     'a 914px pane can afford it - got ' + lab);
  ok('and Fit no longer overflows it', F._schFitMin(lab, 520, true) <= 914,
     'demanded ' + F._schFitMin(lab, 520, true) + 'px of a 914px pane');
  /* NOT "the chart got wider" — it did not. flex:1 gave the plot 914-470=444 under the old code
     too; what it could not do was FIT, so the 76px it overflowed slid under the frozen gutter. The
     honest statement of the fix is the one above: demand <= pane. */
  ok('the floors are the shipping ones, not this file\'s', F.LAB_MIN === 300 && F.PLOT_MIN === 300,
     'if these change in index.html this test must be re-reasoned, not silently re-based');
}

// -- it only ever gives width BACK ----------------------------------------------------------------
ok('a wide monitor never widens the gutter past what the builder chose',
   F._schFitLab(470, 1600) === 470,
   'growing it would move a column the user is reading');
ok('a phone gutter is never inflated to the desktop minimum',
   F._schFitLab(176, 375) === 176,
   '_pdLabW already chose 176 for this width; 300 would cover the whole chart');

// -- and it stops giving back before the gutter stops being a name column -------------------------
{
  const lab = F._schFitLab(470, 700);
  ok('a 700px pane hands 70px back to the chart', lab === 400, 'got ' + lab);
  ok('a 560px pane stops at the floor rather than crushing the name', F._schFitLab(470, 560) === 300);
  ok('and then Fit is honest about still needing to scroll', F._schFitMin(300, 520, true) > 560,
     'if it claimed to fit here the bars would hide behind the gutter again');
}

// -- Wide is meant to overflow; the fit pass must not "fix" it ------------------------------------
ok('Wide keeps the builder plot width', F._schFitMin(470, 1320, false) === 1790,
   'scrolling IS the point of Wide - collapsing it to the pane would silently disable the button');
ok('Fit and Wide differ on the same inputs', F._schFitMin(470, 1320, true) !== F._schFitMin(470, 1320, false));

// -- every alignment point must read the same variable --------------------------------------------
/* The gutter is decided twice - once by the builder, once by _schFitPlot - so anything positioned
   at the gutter has to READ it rather than bake in the builder's number. One hardcoded `left:470px`
   overlay and the gridlines are out of register with the bars they annotate the moment it shrinks. */
{
  const tl = take('function _schTimeline(', '_schTimeline');
  ok('_schTimeline defines the gutter as a CSS variable', /const LABV = 'var\(--labw,/.test(tl));
  ok('the card publishes --labw', /--labw:' \+ LABW \+ 'px/.test(tl));
  ok('nothing is positioned at a hardcoded gutter width',
     !/(width|left):' \+ LABW \+ 'px/.test(tl),
     'it would stay put while --labw moved');
  ok('the header cell, the row label, the gridline overlay and the slide-bar spacer all read it',
     (tl.match(/LABV/g) || []).length >= 5);
  ok('the pane publishes what the builder chose',
     /data-labw="' \+ LABW \+ '"/.test(tl) && /data-plotw="' \+ plotW \+ '"/.test(tl));
  ok('and which mode it is in', /data-fit="' \+ \(_pdWide \? '0' : '1'\) \+ '"/.test(tl));
}

// -- the zero-width trap, again --------------------------------------------------------------------
{
  const fp = take('function _schFitPlot(', '_schFitPlot');
  ok('a pane that is off screen is not read as "no room"',
     /const pane = vp\.clientWidth; if \(!pane\) return;/.test(fp),
     'a hidden pane measures zero, and pmSchedTab only flips display - see _schXBar');
  ok('it writes nothing it did not change',
     /getPropertyValue\('--labw'\) !== lab \+ 'px'/.test(fp) && /Math\.abs\(parseFloat\(inner\.style\.minWidth/.test(fp));
}
// -- and the ordering that makes the slide bar measure the right geometry --------------------------
ok('_schFitPlot runs before _schXBar in the fit pass',
   /_schFitPlot\(\); \} catch \(e\) \{\} try \{ _schXBar\(\)/.test(src),
   'the bar sizes itself from measured overflow, so it must see the width the fit pass left behind');

// -- the folder tree --------------------------------------------------------------------------------
console.log('\nWBS depth is visible in the shape of the list\n');
const LV = [['', 1], ['1', 1], ['1.2', 2], ['1.10.2', 3], ['A.2.1', 3], ['1.2.3.4.5.6.7', 7], ['2.', 1], [null, 1]];
LV.forEach(pair => ok('level of ' + JSON.stringify(pair[0]) + ' is ' + pair[1],
                      F._pmWbsLevel(pair[0]) === pair[1], 'got ' + F._pmWbsLevel(pair[0])));

/* The reported defect: the level cap was 5 and it was doing two jobs — bounding the indent AND
   reporting the depth — so on a real programme 1.4.8.2.1, 1.4.8.2.1.1 and 1.4.8.2.1.1.1 all came
   back as 5 and every surface drew them at the same offset. Depth is a fact; the indent is a
   budget, and the budget belongs to the column paying it. */
ok('a seven-level code is seven levels deep, not five',
   F._pmWbsLevel('1.4.8.2.1.1.1') === 7);
['table', 'gutter', 'narrow', 'dialog'].forEach(where => {
  const off = [];
  for (let l = 1; l <= 7; l++) off.push(F._pmWbsIndentPx(l, where));
  ok('on the ' + where + ', all seven of those levels get a DIFFERENT offset',
     new Set(off).size === 7, where + ' -> ' + off.join(','));
  ok('the ' + where + ' starts the tree at zero and steps evenly',
     off[0] === 0 && off[2] - off[1] === off[1] - off[0]);
});
ok('the top of the tree is not indented', F._pmWbsIndent(1) === 0);
ok('each level steps in by the same amount',
   F._pmWbsIndent(3) - F._pmWbsIndent(2) === F._pmWbsIndent(2) - F._pmWbsIndent(1));
/* Bounded still — but per surface, because that is who pays. Eight steps, then it stops: a
   malformed twelve-dot code cannot walk the name off the screen. */
['table', 'gutter', 'narrow', 'dialog'].forEach(where =>
  ok('the ' + where + ' indent is bounded at eight steps',
     F._pmWbsIndentPx(12, where) === F._pmWbsIndentPx(9, where) &&
     F._pmWbsIndentPx(9, where) > F._pmWbsIndentPx(8, where),
     where + ' -> L8 ' + F._pmWbsIndentPx(8, where) + ', L9 ' + F._pmWbsIndentPx(9, where) +
     ', L12 ' + F._pmWbsIndentPx(12, where)));

/* The indent is spent out of the gutter, and the phone gutter is 176px of which the delivery cell
   takes 74. A level-4 row at the Activities table's step would leave the name ~18px — one character
   and an ellipsis, measured in the browser. */
{
  const deep = F._pmWbsLevel('1.4.4.3');            // level 4
  ok('a narrow gutter pays a token indent, not the full one',
     F._pmWbsIndentFor(deep, true) < F._pmWbsIndentFor(deep, false),
     'got ' + F._pmWbsIndentFor(deep, true) + ' narrow vs ' + F._pmWbsIndentFor(deep, false) + ' wide');
  ok('and it is capped hard enough to leave a readable name',
     F._pmWbsIndentFor(F._pmWbsLevel('1.2.3.4.5.6.7.8.9'), true) <= 32,
     'the phone name budget is ~76px before the indent');
  /* These used to be the same number. They are not any more, and that is the point: a 46%-wide
     Task column and a label gutter cannot afford the same step, and pricing both from one constant
     is what left Activities too faint to read while the gutter could not afford to go deeper. */
  ok('the wide gutter pays LESS than the Activities table, which has the room',
     F._pmWbsIndentFor(deep, false) < F._pmWbsIndent(deep),
     'gutter ' + F._pmWbsIndentFor(deep, false) + ' vs table ' + F._pmWbsIndent(deep));
  ok('and the table step really did grow — the complaint was that it was too small to see',
     F._pmWbsIndent(2) >= 16, 'one level in is ' + F._pmWbsIndent(2) + 'px');
  ok('level 1 is never indented either way',
     F._pmWbsIndentFor(1, true) === 0 && F._pmWbsIndentFor(1, false) === 0);
}

{
  const tl = take('function _schTimeline(', '_schTimeline');
  ok('the timeline row indents by its level, priced against the gutter it spends',
     /22 \+ _pmWbsIndentFor\(lv, NARROW\)/.test(tl));
  ok('and the connector is dropped when the gutter is narrow',
     /lv > 1 && !NARROW \? '<span aria-hidden/.test(tl),
     'the glyph plus its gap costs ~11px of a 176px gutter');
  ok('and the normaliser supplies one', /level: _pmWbsLevel\(t\.wbs\)/.test(src));
  const act = src.slice(src.indexOf("{ label: 'Task', sk: 'name', w: '46%'"),
                        src.indexOf("{ label: 'Assignee', sk: 'assignee'"));
  ok('the Activities table indents too', /_pmWbsIndent\(lv\)/.test(act));
  ok('but only draws the connector while the table is in WBS order',
     /!sk \|\| sk === 'wbs'/.test(act),
     'sorted by finish date the row above is not the parent');
  /* Every surface that indents a name also ellipsis-clips it, so every one of them owes the reader
     the whole name on hover. The Gantt's left column is a FIXED 334px, so the indent comes straight
     out of the only column that can absorb it. */
  const gStart = src.indexOf("let leftRows = '<div style=\"height:' + HDR");
  if (gStart < 0) { console.error('Could not find the Gantt left column builder.'); process.exit(2); }
  const gantt = src.slice(gStart, src.indexOf('class="pm-gantt-left"'));
  ok('the Gantt column indents by level, at the GUTTER price — its left column is a fixed 334px',
     /padding-left:' \+ _pmWbsIndentPx\(_pmWbsLevel\(t\.wbs\), 'gutter'\)/.test(gantt));
  ok('and gives the truncated name a tooltip',
     /<span title="' \+ _tkEscA\(t\.name \|\| ''\) \+ '" style="font-size:11\.5px;overflow:hidden;text-overflow:ellipsis/.test(gantt),
     'it was indented without one — an indent that hides a name and offers no way to read it');
}
/* Re-showing a hidden pane fires no childList mutation, so nothing re-ran the sizing pass: resize
   the window on Activities, switch to Timeline, and the gutter kept the old viewport's width. */
{
  const tab = take('function pmSchedTab(', 'pmSchedTab');
  ok('switching schedule panes re-runs the sizing pass', /_fitTablesSoon\(\)/.test(tab),
     'a hidden pane measures zero, so _schFitPlot and _schXBar both stood down while it was off screen');
}

console.log('\n  ' + pass + ' passed, ' + fail + ' failed\n');
process.exit(fail ? 1 : 0);
