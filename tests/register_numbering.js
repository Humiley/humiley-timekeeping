/* A register numbered 1, 2, 3 must read 1, 2, 3.
 *
 * The ITP register was showing its numbers out of order — 100, 87, 88, 89, 9, 90, 91, 95, 99 — and
 * the cause was one row nobody had numbered yet.
 *
 * `_pmSortRows` decides whether a column is numeric by asking whether EVERY cell parses as a
 * number. `_pmCell` renders an empty cell as the em dash the table actually prints, so a single
 * blank made that test fail, `allNum` went false, and the whole column fell back to
 * `localeCompare` — where "10" sorts before "2". One unnumbered row scrambled the numbering of
 * every other row. The date branch immediately above already allowed '—' for exactly this reason;
 * the numeric branch did not.
 *
 * This is shared by every pm_ register, so the same blank broke CR No., RISK No., ISS No., RFI No.,
 * QA ref, PKG No. and IPC No. in the same way.
 *
 * Two properties are held here, and the second is the one that was missing:
 *   1. numbers sort as numbers;
 *   2. a row with NO number does not change the order of the rows that HAVE one.
 *
 *   node tests/register_numbering.js
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

const API = new Function(
  'let _pmSort = {};\n' +
  'function _dateKey(v){ const s = String(v == null ? "" : v); return /^\\d{4}-\\d{2}-\\d{2}/.test(s) ? s : ""; }\n' +
  take('function _cmpNewest(', '_cmpNewest') +
  take('function _pmCell(', '_pmCell') +
  take('function _pmSortRows(', '_pmSortRows') +
  take('function _pmDocNoCmp(', '_pmDocNoCmp') +
  '\nreturn { _pmSortRows: _pmSortRows, _pmDocNoCmp: _pmDocNoCmp,' +
  ' setSort: (c, k, d) => { _pmSort[c] = { key: k, dir: d }; } };')();

/* The ITP No. column exactly as the register declares it — a render function, so _pmCell has to
   fall back to the rendered text and meets the em dash. Stubbing this as a plain field would test a
   column the app does not have. */
const NUMCOL = [{ label: 'ITP No.', sk: 'itpNo',
  render: r => '<span style="font-variant-numeric:tabular-nums">' + (r.itpNo || '—') + '</span>' }];
const RENDER_ONLY = [{ label: 'ITP No.',
  render: r => '<span style="font-variant-numeric:tabular-nums">' + (r.itpNo || '—') + '</span>' }];

const sorted = (cols, rows, dir, key) => {
  API.setSort('t', key || cols[0].sk || 'col0', dir);
  return API._pmSortRows('t', cols, rows).map(r => r.itpNo || '(blank)');
};
const rowsOf = (...ns) => ns.map(n => ({ itpNo: n === null ? '' : String(n) }));

// ══ numbers sort as numbers ════════════════════════════════════════════════════════════════════
console.log('\nA column of numbers sorts as numbers\n');
{
  const r = rowsOf(12, 3, 7, 1, 10, 11, 2, 9, 8, 4, 5, 6);
  ok('ascending runs 1 to 12, not 1, 10, 11, 12, 2',
     sorted(NUMCOL, r, 1).join(' ') === '1 2 3 4 5 6 7 8 9 10 11 12',
     'got ' + sorted(NUMCOL, r, 1).join(' '));
  ok('and descending runs 12 down to 1',
     sorted(NUMCOL, r, -1).join(' ') === '12 11 10 9 8 7 6 5 4 3 2 1',
     'got ' + sorted(NUMCOL, r, -1).join(' '));
  ok('past 99 too — 100 follows 99, it does not lead 9',
     sorted(NUMCOL, rowsOf(100, 9, 99, 10), 1).join(' ') === '9 10 99 100',
     'got ' + sorted(NUMCOL, rowsOf(100, 9, 99, 10), 1).join(' '));
}

// ══ the regression: one blank row ══════════════════════════════════════════════════════════════
console.log('\nA row nobody has numbered does not disturb the rows that ARE numbered\n');
/* Run this against BOTH column shapes, because a blank does not look the same in each and the bug
   lived on only one of them:
   · a column with `sk` reads the RAW field, so an empty one is '' — which the original condition
     already tolerated;
   · a RENDER-ONLY column goes through _pmCell's fallback, which strips the tags and hands back the
     EM DASH the table prints — and that is what made `allNum` go false.
   A first version of this file only exercised the `sk` shape, so the headline assertion passed for
   a reason that had nothing to do with the reported fault. The mutation run caught it: restoring
   the original condition left that test green. */
[['reading the raw field', NUMCOL, 'itpNo'],
 ['reading the rendered cell', RENDER_ONLY, 'col0']].forEach(([shape, COL, key]) => {
  const numbered = rowsOf(12, 3, 7, 1, 10, 11, 2, 9, 8, 4, 5, 6);
  const withBlank = numbered.concat(rowsOf(null));

  const a = sorted(COL, numbered, 1, key).join(' ');
  const b = sorted(COL, withBlank, 1, key).filter(x => x !== '(blank)').join(' ');
  ok('adding ONE unnumbered row leaves every other row where it was — ' + shape,
     a === b,
     'without the blank: ' + a + '\n        with the blank:    ' + b +
     '\n        A single blank used to make the column fall back to a TEXT sort, so one row nobody ' +
     'had got round to numbering scrambled the numbering of all the rest.');

  ok('the unnumbered row sorts LAST, not in front of number 1 — ' + shape,
     sorted(COL, withBlank, 1, key).pop() === '(blank)',
     'got ' + sorted(COL, withBlank, 1, key).join(' ') + ' — a record with no number belongs at ' +
     'the end of the register; treating a blank as zero puts it before the first real plan');
  ok('and it stays last when the sort is reversed — ' + shape,
     sorted(COL, withBlank, -1, key).pop() === '(blank)',
     'got ' + sorted(COL, withBlank, -1, key).join(' ') + ' — flipping the arrow must reorder the ' +
     'numbered rows, not promote the blank to the top');

  const many = rowsOf(87, 99, 9, 100, null, 90, null, 95);
  ok('the reported case — 87, 99, 9, 100, 90, 95 with two blanks — ' + shape,
     sorted(COL, many, 1, key).join(' ') === '9 87 90 95 99 100 (blank) (blank)',
     'got ' + sorted(COL, many, 1, key).join(' '));
});

// ══ document numbers with a prefix ═════════════════════════════════════════════════════════════
console.log('\nA document number reads prefix first, then its digits as a number\n');
{
  const cmp = API._pmDocNoCmp('itpNo');
  const order = xs => xs.slice().sort(cmp).map(x => x.itpNo || '(blank)').join(' ');

  ok('MEG-ITP-9 comes before MEG-ITP-10',
     order([{ itpNo: 'MEG-ITP-10' }, { itpNo: 'MEG-ITP-9' }, { itpNo: 'MEG-ITP-100' }]) ===
       'MEG-ITP-9 MEG-ITP-10 MEG-ITP-100');
  ok('the app\'s own zero-padded numbers are unaffected',
     order([{ itpNo: 'MEG-ITP-010' }, { itpNo: 'MEG-ITP-001' }, { itpNo: 'MEG-ITP-002' }]) ===
       'MEG-ITP-001 MEG-ITP-002 MEG-ITP-010');
  ok('two projects\' numbers group by their prefix',
     order([{ itpNo: 'WHC-ITP-1' }, { itpNo: 'MEG-ITP-2' }, { itpNo: 'MEG-ITP-1' }]) ===
       'MEG-ITP-1 MEG-ITP-2 WHC-ITP-1');
  ok('plain numbers typed by hand still order numerically',
     order(rowsOf(10, 2, 1)) === '1 2 10');
  ok('and an unnumbered record sorts LAST here too',
     order(rowsOf(2, null, 1)) === '1 2 (blank)');
}

// ══ the register uses it ═══════════════════════════════════════════════════════════════════════
console.log('\nThe ITP register opens in ITP-number order\n');
{
  ok('the table is sorted by the ITP number, not by planned date',
     /\], itp\.slice\(\)\.sort\(_pmDocNoCmp\('itpNo'\)\)\)\);/.test(src),
     'it used to open _cmpNewest(\'plannedStart\') — newest planned first, which reads as no order ' +
     'at all once the planned dates cluster into the same week');
  ok('the ITP No. header sorts the FIELD rather than the rendered text',
     /\{ label: 'ITP No\.', sk: 'itpNo', render:/.test(src));
  ok('and the timeline below still gets date order',
     /_pmItpTimeline\(itp\)/.test(src),
     'the table takes a COPY precisely so the timeline keeps its own ordering');
}

// ══ nothing else regressed ═════════════════════════════════════════════════════════════════════
console.log('\nThe other column types are untouched\n');
{
  const DATE = [{ label: 'Planned', sk: 'plannedStart' }];
  const drows = [{ plannedStart: '2026-08-20' }, { plannedStart: '2026-08-12' }, { plannedStart: '' },
                 { plannedStart: '2026-08-17' }];
  API.setSort('t', 'plannedStart', 1);
  const d = API._pmSortRows('t', DATE, drows).map(r => r.plannedStart || '(blank)');
  ok('dates still sort chronologically, oldest first when ascending',
     d[0] === '2026-08-12' && d[1] === '2026-08-17' && d[2] === '2026-08-20',
     'got ' + d.join(' '));
  ok('and an undated row is still last', d[3] === '(blank)', 'got ' + d.join(' '));

  const TEXT = [{ label: 'Title', sk: 'title' }];
  const trows = [{ title: 'Piping' }, { title: 'Ceiling' }, { title: '' }, { title: 'Rebar' }];
  API.setSort('t', 'title', 1);
  const t = API._pmSortRows('t', TEXT, trows).map(r => r.title || '(blank)');
  ok('text still sorts alphabetically', t[0] === 'Ceiling' && t[1] === 'Piping' && t[2] === 'Rebar',
     'got ' + t.join(' '));
  ok('with the empty one last', t[3] === '(blank)', 'got ' + t.join(' '));
}

console.log('\n  ' + pass + ' passed, ' + fail + ' failed\n');
process.exit(fail ? 1 : 0);
