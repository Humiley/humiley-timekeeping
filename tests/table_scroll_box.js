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
    'const document = {\n' +
    '  getElementById: () => ({ querySelectorAll: () => WRAPS }),\n' +
    '  body: { classList: { contains: c => c === "exporting" && !!OPTS.exporting } },\n' +
    '};\n' +
    'const window = { innerHeight: OPTS.vh || 900,\n' +
    '  matchMedia: () => ({ matches: !!OPTS.phone }) };\n' +
    /* Lifted separately: `take` stops at the NEXT top-level declaration, so asking it for the const
       returns the const and nothing else — the function that uses it starts the next declaration. */
    line('const _TW_CAP_PX', 'the cap') +
    take('function _fitTableScroll(', '_fitTableScroll') +
    '\nreturn { _fitTableScroll, cap: _TW_CAP_PX };');
  const r = api(wraps, opts);
  r._fitTableScroll();
  return r;
};

// ══ every table, no exceptions ═════════════════════════════════════════════════════════════════
console.log('\nOne cap, every table\n');
{
  const ws = [wrap(89), wrap(300), wrap(560), wrap(920), wrap(2962), wrap(40000)];
  const { cap } = run(ws);
  ok('every table is capped, however short',
     ws.every(w => w.classList.contains('tw-tall')),
     'capped: ' + ws.map(w => w.classList.contains('tw-tall')).join(', ') +
     ' — a rule that skips short tables is a different rule per table');
  ok('and they are all capped to the SAME height',
     new Set(ws.map(w => w.style.maxHeight)).size === 1,
     'heights: ' + ws.map(w => w.style.maxHeight).join(', '));
  ok('which is the declared cap', ws[0].style.maxHeight === cap + 'px',
     'got ' + ws[0].style.maxHeight + ', cap is ' + cap);

  /* The point of a uniform cap: a 1-row register and a 135-row one occupy the same space, so the
     filter bar, the KPI strip and the next card are in the same place on every tab. */
  ok('a short register and a long one end up the same size',
     ws[0].style.maxHeight === ws[5].style.maxHeight);
}

// ══ the cap is a real ceiling, not a share of the screen ═══════════════════════════════════════
console.log('\nThe same on a laptop and on a large monitor\n');
{
  /* `big.cap === _capOf(big)` was here, which is x === x — it passed on anything. Assert the box
     the code actually produced instead. */
  const tall = [wrap(3000)];
  const big = run(tall, { vh: 2000 });
  ok('a 2000px-tall monitor does not get a 1240px table',
     tall[0].style.maxHeight === big.cap + 'px',
     'got ' + tall[0].style.maxHeight + ' — the ceiling is fixed, not a fraction of the viewport');
  const a = [wrap(3000)], b = [wrap(3000)];
  run(a, { vh: 900 }); run(b, { vh: 2000 });
  ok('the box is the same height on both', a[0].style.maxHeight === b[0].style.maxHeight,
     'got ' + a[0].style.maxHeight + ' vs ' + b[0].style.maxHeight +
     ' — a viewport-relative cap moves the layout under you when the window resizes');

  /* On a short window the ceiling would fill the screen, so the vh term pulls it DOWN — only ever
     down, never up. */
  const tiny = [wrap(3000)];
  run(tiny, { vh: 500 });
  ok('but a short window gets a smaller box, not a screen-filling one',
     parseInt(tiny[0].style.maxHeight, 10) < 560,
     'got ' + tiny[0].style.maxHeight);
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
