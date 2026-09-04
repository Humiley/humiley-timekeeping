/* Every table sits in a box of the same height, on every tab.
 *
 * This was asked for three times and I narrowed it twice. First "only tables much taller than the
 * viewport", then "only tables taller than the viewport" — both leave a page where each register
 * ends wherever its row count happens to land, which reads as a different rule per table and means
 * the thing you are looking for is never where the last one was. The rule is now unconditional:
 * one cap, every table, every tab.
 *
 * A register shorter than the box simply shows no scrollbar — there is nothing to scroll — so
 * uniformity costs a short table nothing.
 *
 * Two exemptions, both deliberate and both already reasoned about in the file:
 *   · PHONES — no persistent scrollbar to strand, and swiping the page is the natural gesture;
 *   · EXPORTING — a PDF must contain the whole table, not the visible window.
 *
 *   node tests/table_scroll_box.js
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

/* A stand-in for one .table-wrap. scrollHeight is the CONTENT height and does not change when the
   box is capped — which is what makes the decision stable across re-runs. */
const wrap = (contentPx) => ({
  scrollHeight: contentPx,
  style: { maxHeight: '', removeProperty() {} },
  dataset: {},
  classList: {
    _on: new Set(),
    toggle(c, v) { if (v) this._on.add(c); else this._on.delete(c); },
    contains(c) { return this._on.has(c); },
  },
});

const line = (mark, what) => {
  const i = src.indexOf(mark);
  if (i < 0) { console.error('Could not find ' + what); process.exit(2); }
  const j = src.indexOf('\n', i);
  const stmt = src.slice(i, j).replace(/\s*\/\/.*$/, '');
  if (!/;$/.test(stmt)) { console.error(what + ' is no longer one statement: ' + stmt); process.exit(2); }
  return stmt + '\n';
};
const run = (wraps, opts) => {
  opts = opts || {};
  const api = new Function('WRAPS', 'OPTS',
    /* documentElement is part of the stub because _fitTableScroll PUBLISHES the height it computed
       onto --scrollbox-h, which is what the chart boxes (.sch-vp/.itp-vp) read. Modelling it here
       means the test exercises that write instead of stepping around it. */
    'const ROOTVARS = {};\n' +
    'const document = {\n' +
    '  getElementById: () => ({ querySelectorAll: () => WRAPS }),\n' +
    '  documentElement: { style: {\n' +
    '    getPropertyValue: k => ROOTVARS[k] || "",\n' +
    '    setProperty: (k, v) => { ROOTVARS[k] = v; },\n' +
    '    removeProperty: k => { delete ROOTVARS[k]; },\n' +
    '  } },\n' +
    '  body: { classList: { contains: c => c === "exporting" && !!OPTS.exporting } },\n' +
    '};\n' +
    'const window = { innerHeight: OPTS.vh || 900,\n' +
    '  matchMedia: () => ({ matches: !!OPTS.phone }) };\n' +
    /* Lifted separately: `take` stops at the NEXT top-level declaration, so asking it for the const
       returns the const and nothing else — the function that uses it starts the next declaration. */
    line('const _TW_CAP_PX', 'the ceiling') +
    line('const _TW_CHROME_PX', 'the chrome allowance') +
    take('function _fitTableScroll(', '_fitTableScroll') +
    '\nreturn { _fitTableScroll, cap: _TW_CAP_PX, chrome: _TW_CHROME_PX, vars: ROOTVARS };');
  const r = api(wraps, opts);
  r._fitTableScroll();
  return r;
};

// ══ every table, no exceptions ═════════════════════════════════════════════════════════════════
console.log('\nOne cap, every table\n');
{
  const ws = [wrap(89), wrap(300), wrap(560), wrap(920), wrap(2962), wrap(40000)];
  const { chrome } = run(ws);
  const expect = 900 - chrome;      // the harness's default window is 900px tall
  ok('every table is capped, however short',
     ws.every(w => w.classList.contains('tw-tall')),
     'capped: ' + ws.map(w => w.classList.contains('tw-tall')).join(', ') +
     ' — a rule that skips short tables is a different rule per table');
  ok('and they are all capped to the SAME height',
     new Set(ws.map(w => w.style.maxHeight)).size === 1,
     'heights: ' + ws.map(w => w.style.maxHeight).join(', '));
  /* The height is COMPUTED from the window now, not read off the constant, so assert the number
     the rule produces rather than the constant it clamps with — comparing a box to _TW_CAP_PX
     passed only while the ceiling happened to be the term that won. */
  ok('which is the window minus the chrome above the table',
     ws[0].style.maxHeight === expect + 'px',
     'got ' + ws[0].style.maxHeight + ', expected ' + expect + 'px');

  /* The point of a uniform cap: a 1-row register and a 135-row one occupy the same space, so the
     filter bar, the KPI strip and the next card are in the same place on every tab. */
  ok('a short register and a long one end up the same size',
     ws[0].style.maxHeight === ws[5].style.maxHeight);

  /* The chart boxes read --scrollbox-h. If the table height is computed and that variable is not,
     Quality shows a chart and a table of two different heights on one screen. */
  const pub = run([wrap(3000)], { vh: 1000 });
  ok('the computed height is published for the chart boxes to read',
     pub.vars['--scrollbox-h'] === (1000 - pub.chrome) + 'px',
     'got ' + JSON.stringify(pub.vars));
  const phone = run([wrap(3000)], { vh: 900, phone: true });
  ok('and an uncapped mode clears it instead of pinning the charts to a stale number',
     phone.vars['--scrollbox-h'] === undefined, JSON.stringify(phone.vars));
}

/* ══ the box FILLS the window, under a ceiling ═════════════════════════════════════════════════
   This block used to assert the opposite: a fixed 560px ceiling, identical on a laptop and a
   2000px monitor, on the reasoning that a viewport-relative box moves the layout under you when
   the window resizes. That was reversed deliberately, by the owner, because 560 on an ordinary
   window left about a third of the screen empty beneath the card — and because the registers the
   fixed ceiling was protecting (a SECOND one, pushed off screen by a tall first) are now separate
   sub-tab pages and no longer share a scroll. The ceiling survives; it is just much higher and no
   longer the term that decides on an ordinary screen. */
console.log('\nThe box fills the window, under a ceiling\n');
{
  const laptop = [wrap(3000)], monitor = [wrap(3000)];
  run(laptop, { vh: 900 }); run(monitor, { vh: 1400 });
  ok('a taller window gets a taller box — that is the point of the change',
     parseInt(monitor[0].style.maxHeight, 10) > parseInt(laptop[0].style.maxHeight, 10),
     'got ' + laptop[0].style.maxHeight + ' on 900 vs ' + monitor[0].style.maxHeight + ' on 1400');
  ok('and it really does fill, rather than stopping a third of the way down',
     parseInt(laptop[0].style.maxHeight, 10) === 900 - run([wrap(10)], { vh: 900 }).chrome,
     'got ' + laptop[0].style.maxHeight + ' on a 900px window');
  ok('an ordinary window clears the old fixed 560 by a wide margin',
     parseInt(laptop[0].style.maxHeight, 10) > 560, 'got ' + laptop[0].style.maxHeight);

  /* A ceiling still, or a wall-mounted display would produce a two-thousand-pixel scroll box. */
  const huge = [wrap(6000)];
  const big = run(huge, { vh: 3000 });
  ok('a 3000px display stops at the ceiling instead of filling',
     huge[0].style.maxHeight === big.cap + 'px',
     'got ' + huge[0].style.maxHeight + ', ceiling is ' + big.cap);

  /* And a floor, so a short window does not produce a box with two rows in it. */
  const tiny = [wrap(3000)];
  run(tiny, { vh: 500 });
  ok('a very short window gets the floor, not a negative box',
     parseInt(tiny[0].style.maxHeight, 10) === 360, 'got ' + tiny[0].style.maxHeight);
}

// ══ the two exemptions ═════════════════════════════════════════════════════════════════════════
console.log('\nPhones and PDF exports are left alone\n');
{
  const ph = [wrap(3000)];
  run(ph, { phone: true });
  ok('a phone table is not capped', !ph[0].classList.contains('tw-tall'),
     'there is no persistent scrollbar to strand there, and swiping the page is the gesture');
  ok('and carries no inline height', !ph[0].style.maxHeight);

  const ex = [wrap(3000)];
  run(ex, { exporting: true });
  ok('an exporting table is not capped', !ex[0].classList.contains('tw-tall'),
     'a PDF must contain the whole table, not the window you happened to be looking at');
}

// ══ it un-caps again ═══════════════════════════════════════════════════════════════════════════
console.log('\nAnd it lets go when it should\n');
{
  const w = wrap(3000);
  run([w]);                                   // capped, dataset.twCap set
  ok('the cap is recorded so it can be undone later', w.dataset.twCap === '1');
  run([w], { phone: true });                  // same element, now on a phone-width window
  ok('rotating to a phone width releases the cap',
     !w.classList.contains('tw-tall') && !w.style.maxHeight && !w.dataset.twCap,
     'maxHeight=' + JSON.stringify(w.style.maxHeight) + ' twCap=' + w.dataset.twCap +
     ' — a stale inline height would leave the box the wrong size for the new viewport');

  /* An inline max-height put there by whoever BUILT the box (a dialog's own list) is a decision
     already taken about that table; the sweep must not overrule it. */
  const own = wrap(3000); own.style.maxHeight = '46vh';
  run([own]);
  ok('a box that came with its own height keeps it',
     own.style.maxHeight === '46vh' && !own.classList.contains('tw-tall'));
}

// ══ the CSS is there to act on it ══════════════════════════════════════════════════════════════
console.log('\nThe class actually scrolls\n');
{
  ok('.tw-tall scrolls vertically', /\.table-wrap\.tw-tall\{overflow-y:auto/.test(src));
  ok('and keeps the scroll inside the box',
     /\.table-wrap\.tw-tall\{[^}]*overscroll-behavior:contain/.test(src),
     'without this, reaching the end of the table starts scrolling the page');
  ok('the sticky header is still declared, so it pins to the box',
     /\.table-wrap thead th\{position:sticky;top:0/.test(src),
     'this is what makes a long register readable — the column names stay put');
  ok('exporting un-caps in CSS as well as in JS',
     /body\.exporting \.table-wrap\{max-height:none !important/.test(src));
}

console.log('\n  ' + pass + ' passed, ' + fail + ' failed\n');
process.exit(fail ? 1 : 0);
