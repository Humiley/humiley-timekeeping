/* The ITP timeline scrolls in a box, like every other long thing on the page.
 *
 * It was the one chart in the app that never got one. A project with 120 inspection plans rendered
 * roughly 3,400px of Gantt straight down the page: the legend, the card under it and the tab you
 * were actually reading were all pushed off screen, and there was no way to move within the chart
 * without moving the whole page. The Schedule tab's Gantt has had a box since it was built; this one
 * was simply missed.
 *
 * Three things are held here:
 *   1. the box EXISTS, and is the same height as a register table — Quality stacks a table directly
 *      on top of this chart, so two different heights read as two different rules;
 *   2. the MONTH AXIS pins while the rows scroll. A Gantt with no visible months is not a smaller
 *      Gantt, it is an unreadable one: a bar's position means nothing without the scale;
 *   3. the three columns stay ALIGNED. Labels, bars and dates are three separate columns that only
 *      line up because their header cells occupy the same 31px. Change one and every row in the
 *      chart points at the wrong plan.
 *
 * This renders the REAL _pmItpTimeline and asserts on what it produced. An easier habit in this
 * suite is to regex the source for the class name, which passes just as happily when the element
 * carrying it is never emitted.
 *
 *   node tests/itp_timeline_scroll_box.js
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
  const ends = ['\nfunction ', '\nasync function ', '\nconst ', '\nlet ']
    .map(e => src.indexOf(e, i + 10)).filter(x => x > 0);
  return src.slice(i, Math.min.apply(null, ends));
};
/* `take` stops at the next TOP-LEVEL declaration, so it hands back only the const when you ask it
   for one. Single statements need lifting on their own. */
const line = (mark, what) => {
  const i = src.indexOf(mark);
  if (i < 0) { console.error('Could not find ' + what); process.exit(2); }
  const stmt = src.slice(i, src.indexOf('\n', i)).replace(/\s*\/\/.*$/, '');
  if (!/;$/.test(stmt)) { console.error(what + ' is no longer one statement: ' + stmt); process.exit(2); }
  return stmt + '\n';
};

// ── render the real thing ──────────────────────────────────────────────────────────────────────
const ITPS = [];
for (let i = 1; i <= 120; i++) {
  const d = new Date(Date.UTC(2026, 5, 1 + i));   // Jun 2026 on, so the axis spans several months
  const iso = d.toISOString().slice(0, 10);
  ITPS.push({ itpNo: 'MEG-ITP-' + i, title: 'Inspection plan ' + i, plannedStart: iso,
              plannedFinish: iso, status: i % 3 === 0 ? 'Approved' : 'Draft' });
}

const HTML = new Function('ITPS',
  "const _pmItpRange = 'ALL';\n" +
  "const _pmEsc = s => String(s == null ? '' : s).replace(/&/g,'&amp;').replace(/</g,'&lt;');\n" +
  "const _tkEscA = s => _pmEsc(s).replace(/\"/g,'&quot;');\n" +
  "const _pmFmt = d => String(d || '');\n" +
  "const _t = s => s;\n" +
  "const _pmToday = () => '2026-07-01';\n" +
  "const _pmDateDiff = (a,b) => (a && b) ? Math.round((new Date(b) - new Date(a)) / 86400000) : 0;\n" +
  take('function _pmItpTimeline(', '_pmItpTimeline') +
  '\nreturn _pmItpTimeline(ITPS);')(ITPS);

/* The fixture has to actually contain the case the assertions describe — a chart with two rows
   would satisfy every claim below while proving nothing about a register that needs a box. */
{
  const rows = (HTML.match(/border-bottom:1px solid var\(--soft-bg\)/g) || []).length;
  if (rows < 200) { console.error('fixture built only ' + rows + ' chart rows; expected 120 plans across three columns'); process.exit(2); }
  if (!/Jul/.test(HTML) || !/Aug/.test(HTML)) { console.error('fixture spans too few months to test the month axis'); process.exit(2); }
}

const attrs = (cls) => {
  const out = [];
  const re = new RegExp('<div class="([^"]*\\b' + cls + '\\b[^"]*)"([^>]*)>', 'g');
  let m; while ((m = re.exec(HTML))) out.push({ cls: m[1], rest: m[2] });
  return out;
};
const styleOf = (rest) => { const m = /style="([^"]*)"/.exec(rest || ''); return m ? m[1] : ''; };
const px = (style, prop) => {
  const m = new RegExp('(?:^|;)\\s*' + prop + ':\\s*(-?[\\d.]+)px').exec(style);
  return m ? parseFloat(m[1]) : 0;
};

// ══ 1. the box exists at all ═══════════════════════════════════════════════════════════════════
console.log('\nThe chart is in a scroll box\n');
{
  const vp = attrs('itp-vp');
  ok('the timeline is rendered inside a viewport element', vp.length === 1,
     'found ' + vp.length + ' — a class named in the stylesheet and never emitted caps nothing');
  const st = styleOf(vp[0] && vp[0].rest);
  /* overflow:auto, not overflow-x:auto. A Gantt runs off the page in BOTH directions — the months go
     right as the rows go down — so capping the height while only the x-axis scrolls would clip the
     bottom of the chart with no way to reach it. overflow-x:auto was the declaration here before. */
  ok('and that box scrolls on both axes', /(^|;)\s*overflow:\s*auto/.test(st),
     'style was: ' + st + ' — a height cap with only overflow-x set CLIPS the rows it hides');
  ok('the box is reachable from the keyboard', / tabindex="0"/.test(vp[0].rest),
     'a scroll region only a mouse wheel can move is unreachable for anyone tabbing');
  ok('and it is announced', / role="group"/.test(vp[0].rest) && /aria-label="[^"]+"/.test(vp[0].rest));
  ok('its label is translated, not left English-only',
     /'Scroll the ITP timeline':\s*'[^']+'/.test(src),
     'every other aria-label in this file has a _VI entry');
}

// ══ 2. one height for every scroll box in the app ══════════════════════════════════════════════
console.log('\nThe same height as a register table\n');
{
  const K = new Function(line('const _TW_CAP_PX', 'the table cap') + 'return _TW_CAP_PX;')();
  const m = /--scrollbox-h:\s*(\d+)px/.exec(src);
  ok('the stylesheet declares one shared box height', !!m, 'no --scrollbox-h in the stylesheet');
  ok('and the tables and the Gantts agree on it', m && +m[1] === K,
     'stylesheet says ' + (m && m[1]) + 'px, _TW_CAP_PX says ' + K + ' — Quality stacks a table ' +
     'directly on this chart, so two numbers here are two visibly different boxes on one screen');
  ok('both Gantt viewports read that variable',
     /\.sch-vp,\.itp-vp\{max-height:var\(--scrollbox-h\)\}/.test(src));
  /* The Schedule Gantt used to carry max-height:520px inline. An inline declaration beats the class,
     so leaving it behind would have left the two charts different heights while the stylesheet
     claimed otherwise. */
  ok('and the Schedule Gantt no longer overrides it inline',
     !/style="overflow:auto;max-height:\d+px"/.test(src),
     'an inline max-height wins over the shared rule, so the variable would be decorative');
}

// ══ 3. the month axis pins ═════════════════════════════════════════════════════════════════════
console.log('\nThe months stay above the bars\n');
{
  const hd = attrs('itp-hd');
  ok('all three columns emit a header cell', hd.length === 3,
     'found ' + hd.length + ' — labels, bars and dates each need one or the band has a hole in it');
  ok('and the stylesheet pins them to the top of the box',
     /\.itp-vp \.itp-hd\{position:sticky;top:0/.test(src));
  ok('with a background, so rows do not scroll through the pinned band',
     /\.itp-vp \.itp-hd\{[^}]*background:/.test(src));
  /* z-index has to clear the chart's own layers: bars sit at 2 and the dashed today line at 3. */
  const z = /\.itp-vp \.itp-hd\{[^}]*z-index:(\d+)/.exec(src);
  ok('and it sits above the bars and the today line', z && +z[1] > 3,
     'z-index is ' + (z && z[1]) + '; bars are z-index:2 and the today marker is z-index:3');
  /* The two reasons the pin did NOT hold when this was first written, both invisible in the source
     and both found by measuring it in a browser.
     1. A flex item stretches to the cross size of the LINE, so each column was 535px tall while
        holding 3,381px of rows. Sticky cannot leave its containing block, so the axis pinned for
        514px and then slid away — a header that works until the moment you need it.
     2. Padding on a scroll container is INSIDE the scrollport and scrolls away with the content,
        leaving a 10px strip above the pinned band with rows running through it. */
  const vpStyle = styleOf(attrs('itp-vp')[0] && attrs('itp-vp')[0].rest);
  ok('the columns size to their content, not to the height of the box',
     /align-items:\s*flex-start/.test(vpStyle),
     'style: ' + vpStyle + ' — stretched to the line, a column is only as tall as the BOX, and the ' +
     'sticky axis stops pinning as soon as you scroll past that');
  ok('and the box has no top padding for rows to scroll through',
     /(^|;)\s*padding:\s*0 /.test(vpStyle),
     'style: ' + vpStyle + " — a scroll container's padding-top is inside the scrollport, so it " +
     'scrolls away and uncovers a strip above the pinned months');
  /* An INLINE position beats the class, so this is the way the pin dies silently. */
  ok('no header cell carries an inline position that would beat the class',
     hd.length === 3 && hd.every(h => !/(^|;)\s*position:/.test(styleOf(h.rest))),
     'inline styles: ' + hd.map(h => styleOf(h.rest)).join(' | '));
}

// ══ 4. the three columns still line up ═════════════════════════════════════════════════════════
console.log('\nAnd the columns still line up\n');
{
  const hd = attrs('itp-hd');
  /* THE BOX MODEL IS THE WHOLE ASSERTION, so state it before doing any arithmetic. The stylesheet
     sets `*{box-sizing:border-box}`, which means a declared height ALREADY INCLUDES the padding.
     The first version of this test added height + padding — the content-box sum — and so read
     `height:15px;padding-bottom:6px` as 21px. The browser measured 15px, and the bar column sat 6px
     above its own labels down the entire chart. The test agreed with the bug because it was doing
     the arithmetic for a box model this page does not use. */
  ok('the page really is border-box, which is what the sum below depends on',
     /\*\{[^}]*box-sizing:border-box/.test(src),
     'if this ever changes to content-box, the padding stops being inside the height and every ' +
     'number in this section means something different');
  const occupied = hd.map(h => {
    const s = styleOf(h.rest);
    // border-box: padding lives INSIDE height. Only margin adds to the space a cell occupies.
    return px(s, 'height') + px(s, 'margin-bottom') + px(s, 'margin-top');
  });
  ok('every header cell occupies the same vertical space',
     occupied.length === 3 && new Set(occupied).size === 1,
     'occupied: ' + occupied.join(', ') + 'px — the labels, the bars and the dates are three ' +
     'separate columns; if their headers differ every row points at the wrong plan');
  /* 31 = the 21px band + the 10px that moved in from the scroll container's padding-top, so the
     breathing room above the axis is part of what gets pinned. */
  ok('and it is the 31px the rows were laid out against', occupied[0] === 31,
     'got ' + occupied[0] + 'px');
  ok('the room above the axis is carried by the header, not by the box',
     hd.every(h => px(styleOf(h.rest), 'padding-top') === 10),
     'padding-top: ' + hd.map(h => px(styleOf(h.rest), 'padding-top')).join(', ') +
     ' — carried by the box instead, it scrolls away and rows show above the pinned months');
  /* Padding has to FIT INSIDE that height, or the month text has no room left to draw in. */
  const pad = hd.map(h => px(styleOf(h.rest), 'padding-bottom'));
  ok('and any padding fits inside it rather than adding to it',
     pad.every((p, i) => p < occupied[i]),
     'padding: ' + pad.join(', ') + ' against heights ' + occupied.join(', '));
  /* A sticky element paints its background over its padding box and NOT over its margin, so a
     margin-bottom here leaves a transparent slot for rows to show through under the pinned months. */
  const month = hd.filter(h => /padding-bottom|margin-bottom/.test(styleOf(h.rest)));
  ok('the month row spaces itself with padding, not margin',
     month.length === 1 && !/margin-bottom/.test(styleOf(month[0].rest)),
     'styles: ' + month.map(h => styleOf(h.rest)).join(' | ') + ' — a sticky background does not ' +
     'cover a margin, so rows would show through the gap under the pinned months');
}

// ══ 5. a PDF still gets the whole chart ════════════════════════════════════════════════════════
console.log('\nExporting still captures every row\n');
{
  ok('the box un-caps while exporting',
     /body\.exporting \.itp-vp\{max-height:none !important;overflow:visible !important\}/.test(src),
     'html2canvas renders the visible window, so a capped box silently drops every row below it');
  /* Un-capping the box alone is not enough: the card around it clips. */
  ok('and the card around it stops clipping too',
     /body\.exporting \.itp-cap\{overflow:visible !important/.test(src),
     'otherwise the chart is cut off at the card edge instead of the box edge');
  ok('the card is actually tagged for that rule', attrs('card itp-cap').length === 1,
     'the rule needs an element to act on');
}

// ══ 6. both scrollbars are left in place ═══════════════════════════════════════════════════════
console.log('\nBoth scrollbars are left in place\n');
{
  /* .sch-vp deliberately kills its horizontal bar because it has the inset .sch-xbar proxy under it.
     This chart has no proxy, so the same treatment would leave the months to the right reachable
     only by guessing they are there. */
  const m = /\.itp-vp::-webkit-scrollbar\{width:11px;height:(\d+)px\}/.exec(src);
  ok('the horizontal bar is NOT suppressed the way the Schedule Gantt suppresses its own',
     m && +m[1] > 0,
     'height is ' + (m && m[1]) + ' — .sch-vp sets height:0 because .sch-xbar replaces it; there is ' +
     'no replacement here');
  ok('a flick past the end does not become the browser back gesture',
     /\.itp-vp\{[^}]*overscroll-behavior:contain/.test(src));
}

console.log('\n  ' + pass + ' passed, ' + fail + ' failed\n');
process.exit(fail ? 1 : 0);
