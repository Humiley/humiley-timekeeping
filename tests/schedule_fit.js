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

const F = new Function(
  'const _SCH_LAB_MIN = 300, _SCH_PLOT_MIN = 300;\n' +
  take('function _schFitLab(', '_schFitLab') +
  take('function _schFitMin(', '_schFitMin') +
  take('function _pmWbsLevel(', '_pmWbsLevel') +
  take('function _pmWbsIndent(', '_pmWbsIndent') +
  '\nreturn { _schFitLab, _schFitMin, _pmWbsLevel, _pmWbsIndent };')();

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
  ok('which leaves the chart more room than the old 520 floor allowed', 914 - lab === 444);
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
const LV = [['', 1], ['1', 1], ['1.2', 2], ['1.10.2', 3], ['A.2.1', 3], ['1.2.3.4.5.6.7', 5], ['2.', 1], [null, 1]];
LV.forEach(pair => ok('level of ' + JSON.stringify(pair[0]) + ' is ' + pair[1],
                      F._pmWbsLevel(pair[0]) === pair[1], 'got ' + F._pmWbsLevel(pair[0])));
ok('the top of the tree is not indented', F._pmWbsIndent(1) === 0);
ok('each level steps in by the same amount',
   F._pmWbsIndent(3) - F._pmWbsIndent(2) === F._pmWbsIndent(2) - F._pmWbsIndent(1));
ok('the indent is bounded', F._pmWbsIndent(F._pmWbsLevel('1.2.3.4.5.6.7.8.9')) <= 70,
   'past a point the indent costs more name than the depth is worth');

{
  const tl = take('function _schTimeline(', '_schTimeline');
  ok('the timeline row indents by its level', /22 \+ _pmWbsIndent\(lv\)/.test(tl));
  ok('and the normaliser supplies one', /level: _pmWbsLevel\(t\.wbs\)/.test(src));
  const act = src.slice(src.indexOf("{ label: 'Task', sk: 'name', w: '46%'"),
                        src.indexOf("{ label: 'Assignee', sk: 'assignee'"));
  ok('the Activities table indents too', /_pmWbsIndent\(lv\)/.test(act));
  ok('but only draws the connector while the table is in WBS order',
     /!sk \|\| sk === 'wbs'/.test(act),
     'sorted by finish date the row above is not the parent');
}

console.log('\n  ' + pass + ' passed, ' + fail + ' failed\n');
process.exit(fail ? 1 : 0);
