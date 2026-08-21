/* A performance index is a ratio of two things the project has recorded. When it has not recorded
 * them, CPI and SPI still hold a NUMBER — 1.00 from a fallback, or 0.00 from a zero numerator —
 * and every one of those reads as a finding: "exactly on budget", "perfectly on schedule",
 * "catastrophically behind". None is true. There is nothing to measure yet.
 *
 * The calculation was corrected first and the DELIVERY was not: `spiMeasurable` existed for an
 * hour with three occurrences, all inside _pmEvm, and no screen read it — so the Cost/EVM tab kept
 * printing SPI 1.00. A correct flag nobody consults changes nothing a user sees.
 *
 * This file therefore asserts the WIRING, not just the maths.
 *
 *   node tests/evm_index_honesty.js
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
  return src.slice(i, j < 0 ? i + 3000 : j);
};

// Scan CODE, not prose: the comments here quote the old expressions verbatim, as comments
// explaining a fix must. A check that reads documentation as code convicts the documentation.
const code = src
  .replace(/\/\*[\s\S]*?\*\//g, '')
  .replace(/<!--[\s\S]*?-->/g, '')
  .replace(/(^|[^:])\/\/.*$/gm, '$1');

const api = {};
new Function(
  "function _ragHex(){ return '#111'; }" +
  take('function _pmIndexRag(', '_pmIndexRag') +
  take('function _pmIndexTxt(', '_pmIndexTxt') +
  take('function _pmIndexHex(', '_pmIndexHex') +
  '\nObject.assign(this, { _pmIndexTxt, _pmIndexHex });').call(api);
const { _pmIndexTxt, _pmIndexHex } = api;

console.log('\nEVM index honesty\n');

/* ── the helper ─────────────────────────────────────────────────────────────── */
ok('a measured index prints to two decimals', _pmIndexTxt(0.87, true) === '0.87');
ok('an unmeasured index prints an em dash', _pmIndexTxt(1, false) === '—');
ok('an unmeasured 1.00 never prints as 1.00', _pmIndexTxt(1, false) !== '1.00');
ok('an unmeasured 0.00 never prints as 0.00', _pmIndexTxt(0, false) !== '0.00');
ok('a null index prints an em dash', _pmIndexTxt(null, false) === '—');
ok('an unmeasured index takes a neutral colour, not red or green',
   _pmIndexHex(0, false) === 'var(--text-light)',
   'red on an unmeasured index reads as a finding');
ok('a measured index still gets its RAG colour', _pmIndexHex(0.5, true) !== 'var(--text-light)');

/* ── the flags exist and mean what they say ─────────────────────────────────── */
const evm = take('function _pmEvm(', '_pmEvm');
ok('cpiMeasurable requires earned value AND actual cost',
   /const cpiMeasurable = ev > 0 && ac > 0 && bac > 0/.test(evm));
ok('spiMeasurable requires PV derived independently of EV',
   /const pvIndependent = \(phased != null\) \|\| \(tp != null\)/.test(evm) &&
   /const spiMeasurable = pvIndependent &&/.test(evm));
ok('eacMeasurable requires earned value', /const eacMeasurable = ev > 0 && ac > 0 && bac > 0/.test(evm));
['cpiMeasurable', 'spiMeasurable', 'eacMeasurable'].forEach(f =>
  ok(f + ' is returned to callers', new RegExp(f + '[,\\s}]').test(evm.slice(evm.indexOf('return {')))));

/* ── THE WIRING: no screen may print an index it did not measure ───────────── */
// This is the assertion that was missing when the flag sat unread for an hour.
const bare = [];
const RX = /\b(?:ev|e)\.(cpi|spi)\.toFixed\(2\)/g;
let m;
while ((m = RX.exec(code)) !== null) {
  bare.push(code.slice(Math.max(0, m.index - 70), m.index + 30).replace(/\s+/g, ' '));
}
ok('no screen prints CPI or SPI without consulting its flag', bare.length === 0,
   bare.join('\n        '));
ok('avgCpi / avgSpi are not printed bare either',
   !/avg(Cpi|Spi)\.toFixed\(/.test(code));

// each specific surface, named, so a regression says WHICH screen broke
const surfaces = [
  ['Cost / EVM tab', /_hrKpi\('CPI', _pmIndexTxt\(ev\.cpi, ev\.cpiMeasurable\)/],
  ['Cost / EVM tab (SPI)', /_hrKpi\('SPI', _pmIndexTxt\(ev\.spi, ev\.spiMeasurable\)/],
  ['Status PDF', /\['CPI {2}\/ {2}SPI', _pmIndexTxt\(ev\.cpi, ev\.cpiMeasurable\)/],
  ['client-headed progress report', /line\('CPI \/ SPI', _pmIndexTxt\(ev\.cpi, ev\.cpiMeasurable\)/],
  ['Closeout PDF', /\['Final CPI', _pmIndexTxt\(ev\.cpi, ev\.cpiMeasurable\)\]/],
  ['portfolio table', /_pmIndexTxt\(e\.cpi, e\.cpiMeasurable\)/],
  ['portfolio tiles', /tile\('Avg CPI', _pmIndexTxt\(avgCpi/],
];
surfaces.forEach(([name, rx]) => ok(name + ' consults the flag', rx.test(code)));

/* ── the portfolio average must not be dragged by unmeasured projects ───────── */
const port = take('function _pmPortfolioCard(', '_pmPortfolioCard');
ok('the portfolio counts CPI and SPI separately', /let cpiN = 0, spiN = 0/.test(port));
ok('cpiN and spiN are declared, not implicit globals', /let cpiN = 0, spiN = 0;/.test(port),
   'an undeclared counter becomes a global and the file still parses');
ok('the CPI average divides by the CPI count', /const avgCpi = cpiN \? cpiSum \/ cpiN : null/.test(port));
ok('the SPI average divides by the SPI count', /avgSpi = spiN \? spiSum \/ spiN : null/.test(port));
ok('it no longer divides by the unrelated `meas` counter',
   !/avgCpi = meas \? cpiSum \/ meas/.test(port),
   '`meas` asks whether the project has a budget and any signal — a different question');
ok('the portfolio states how many projects its averages cover', /Averages cover/.test(port));
ok('and says so plainly when none did', /No project has recorded enough to measure/.test(port));

/* ── the SPI chart must not draw a bar for an unmeasured project ────────────── */
ok('the SPI chart plots only projects that measured SPI',
   /_spiOk = top\.filter\(p => _pmEvm\(p\)\.spiMeasurable\)/.test(code),
   'a 1.00 column is indistinguishable from a project genuinely on schedule');

console.log('\n' + pass + ' passed, ' + fail + ' failed\n');
process.exit(fail ? 1 : 0);
