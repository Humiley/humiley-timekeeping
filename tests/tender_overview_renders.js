/* The tender Overview screen actually renders — and reads the keys the SERVER really sends.
 *
 * A render that throws leaves an EMPTY PANEL and nobody reports it: that is how the Stages & Gates
 * tab sat blank in production for weeks. Worse for a dashboard, a field read under the wrong name
 * is `undefined`, every guard skips it, and the panel renders FINE with a fact quietly missing.
 * `cash.peak` did exactly that here — the server calls it `peakFunding` — and nothing would have
 * complained.
 *
 * So this drives tndTabOverview against a stub whose key names are asserted against the real
 * server modules (tender.cash_flow / risk_register / accuracy), and then checks the numbers it was
 * given actually appear on the page.
 *
 *   node tests/tender_overview_renders.js
 */
const fs = require('fs');
const path = require('path');
const { execFileSync } = require('child_process');

const root = path.join(__dirname, '..');
const src = fs.readFileSync(path.join(root, 'templates', 'index.html'), 'utf8');

let pass = 0, fail = 0;
const ok = (n, c, extra) => {
  if (c) { pass++; console.log('  ok    ' + n); }
  else { fail++; console.log('  FAIL  ' + n + (extra ? '\n        ' + extra : '')); }
};

console.log('\nThe tender Overview screen renders, from the keys the server really sends\n');

// ── the key names, taken from the Python that produces them ─────────────────────────────────────
const realKeys = JSON.parse(execFileSync('python3', ['-c', `
import json, inspect, re, sys
sys.path.insert(0, ${JSON.stringify(root)})
import tender
out = {}
for fn in ("cash_flow", "risk_register", "accuracy"):
    out[fn] = sorted(set(re.findall(r'"(\\w+)":', inspect.getsource(getattr(tender, fn)))))
print(json.dumps(out))
`], { encoding: 'utf8' }));

ok('cash flow really calls it peakFunding', realKeys.cash_flow.indexOf('peakFunding') >= 0,
   'got: ' + realKeys.cash_flow.join(', '));
/* The register itself carries `expectedValue`; its per-risk ROWS carry `expected`. A source
   scan finds both, which is how the wrong one got used — so name the one that matters. */
ok('the risk register really carries expectedValue',
   realKeys.risk_register.indexOf('expectedValue') >= 0);
ok('accuracy really carries stated/label/low', ['stated', 'label', 'low']
   .every(k => realKeys.accuracy.indexOf(k) >= 0));

/* The page must read those exact names. A dashboard reading `cash.peak` renders perfectly and
   silently omits the funding hole. */
ok('the page reads cash.peakFunding, not cash.peak',
   /cash\.peakFunding/.test(src) && !/cash\.peak[^FM]/.test(src),
   'the funding line would render blank');
ok('the page reads risk.expectedValue, not risk.expected',
   /risk\.expectedValue/.test(src) && !/risk\.expected\b(?!Value)/.test(src),
   'the exposure line would render blank');

// ── run the renderer ────────────────────────────────────────────────────────────────────────────
const start = src.indexOf('function tndTabOverview() {');
if (start < 0) { console.error('tndTabOverview is not in the page.'); process.exit(2); }
const end = src.indexOf('\n}\n', start);
const body = src.slice(start, end + 3);

let painted = '';
const env = {
  _tndSum: {
    quote: { gross: 1100000000, vat: 100000000, cogs: 700000000, lineCount: 2,
             grossMarginPct: 30 },
    pnl: { revenue: 1000000000, goodsCost: 700000000, cogs: 700000000,
           grossProfit: 300000000, opexTotal: 80000000, ebit: 220000000,
           cit: 44000000, netProfit: 176000000, netMarginPct: 17.6 },
    contribution: { rows: [
        { itemCode: 'A-1', desc: 'AHU', revenue: 600000000, cost: 300000000,
          profit: 300000000, marginPct: 50, sharePct: 100, belowCost: false },
        { itemCode: 'A-2', desc: 'Duct', revenue: 400000000, cost: 400000000,
          profit: 0, marginPct: 0, sharePct: 0, belowCost: false }],
      lineCount: 2, shareMeaningful: true, carriers: 1, carriersOf: 2, topShare: 80,
      concentrated: true, belowCost: [], belowCostCount: 0 },
    issue: { canIssue: false, missing: ['Amount in words'], warnings: ['thin margin'],
             signature: { required: true, signed: false, stale: false } },
    accuracy: { stated: true, label: 'Class 3', low: 900000000, high: 1200000000 },
    cash: { peakFunding: 450000000, peakMonth: 3 },
    risk: { expectedValue: 55000000, openCount: 4 },   // the register's own key
    fxExposure: { currency: 'USD', rows: [{ movePct: -10, marginPct: 12.5 }] },
    document: null,
  },
  _estCur: 'est-1',
  _estById: () => ({ quoteNo: 'QT-2026-1', client: 'Acme Co', validUntil: '2026-03-01',
                     status: 'Draft' }),
  _estSet: h => { painted = h; },
  _t: x => x,
  _estEsc: x => String(x == null ? '' : x),
  _tndMoney: n => '₫' + Number(n || 0).toLocaleString('en-US'),
  _tndNum: (n, d) => Number(n || 0).toFixed(d || 0),
  _tndPct: n => (n == null ? '—' : Number(n).toFixed(1) + '%'),
};
const names = Object.keys(env);
try {
  new Function(...names, body + '; return tndTabOverview;')(...names.map(k => env[k]))();
} catch (e) {
  console.log('  FAIL  the screen throws: ' + e.message);
  console.log('\n  ' + pass + ' passed, ' + (fail + 1) + ' failed\n');
  process.exit(1);
}

ok('it paints something at all', painted.length > 200, 'painted ' + painted.length + ' chars');

// ── the numbers it was given actually appear ────────────────────────────────────────────────────
const has = t => painted.indexOf(t) >= 0;
ok('the price to the customer', has('1,100,000,000'));
ok('the net profit after tax', has('176,000,000'));
ok('the gross margin', has('30.0%'));
ok('the cash needed to fund the job', has('450,000,000'),
   'peakFunding was read under the wrong name and vanished silently');
ok('the risk exposure', has('55,000,000'));
ok('the accuracy class', has('Class 3'));

ok('it says the quotation cannot be issued', has('Not ready to issue'));
ok('it lists what is missing', has('Amount in words'));
ok('it says a signature is required', /signature is required/i.test(painted));

ok('it names the line carrying the profit', has('A-1'));
ok('it warns that the profit is concentrated',
   /carry/.test(painted) && has('80%'));

ok('the document block names the customer', has('Acme Co') && has('QT-2026-1'));

// ── the honesty cases ───────────────────────────────────────────────────────────────────────────
env._tndSum.contribution.shareMeaningful = false;
env._tndSum.contribution.concentrated = false;
env._tndSum.contribution.rows.forEach(r => { r.sharePct = null; });
new Function(...names, body + '; return tndTabOverview;')(...names.map(k => env[k]))();
ok('a tender making no profit says so instead of printing shares',
   /makes no profit overall/.test(painted));

env._tndSum.issue = { canIssue: true, missing: [], warnings: [], signature: {} };
new Function(...names, body + '; return tndTabOverview;')(...names.map(k => env[k]))();
ok('a complete quotation says it can be issued', /can be issued/.test(painted));

env._tndSum.quote = null;
new Function(...names, body + '; return tndTabOverview;')(...names.map(k => env[k]))();
ok('an unpriced tender says so rather than rendering an empty page',
   /Nothing priced yet/.test(painted));

console.log('\n  ' + pass + ' passed, ' + fail + ' failed\n');
process.exit(fail ? 1 : 0);
