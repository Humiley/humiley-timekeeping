// Does the Ledger screen actually render? A render that throws leaves an empty panel and nobody
// reports it — that exact failure blanked the Stages & Gates tab in production for weeks.
const fs = require('fs');
const path = require('path');

const ROOT = path.join(__dirname, '..');
const page = fs.readFileSync(path.join(ROOT, 'templates', 'index.html'), 'utf8');

function take(name) {
  const start = page.indexOf(name);
  if (start < 0) throw new Error('not found in the page: ' + name);
  let d = 0;
  for (let i = page.indexOf('{', start); i < page.length; i++) {
    if (page[i] === '{') d++;
    else if (page[i] === '}' && --d === 0) return page.slice(start, i + 1);
  }
  throw new Error('unbalanced: ' + name);
}

const SUMMARY = {
  ok: true, period: '2026-05', periods: ['2026-04', '2026-05'], closedPeriods: ['2026-04'],
  closed: false, closedBy: '', closedAt: '',
  basis: 'Circular 200/2014/TT-BTC', entryCount: 6,
  trialBalance: {
    balanced: true, debit: 123500000, credit: 123500000, difference: 0, accounts: 6,
    rows: [
      { account: '642', name: 'Admin expense', classLabel: 'Operating expenses', class: 'expense',
        debit: 123500000, credit: 0, balance: 123500000, normalSide: 'debit' },
      { account: '334', name: 'Payable to employees', classLabel: 'Liabilities', class: 'liability',
        debit: 0, credit: 89500000, balance: 89500000, normalSide: 'credit' },
      { account: '331', name: 'Wrong side on purpose', classLabel: 'Liabilities', class: 'liability',
        debit: 5000000, credit: 0, balance: -5000000, normalSide: 'credit' },
    ],
  },
  result: { income: 0, expense: 123500000, profit: -123500000 },
  batches: [{ id: 'GL-202605-abc', memo: 'Payroll 2026-05', source_id: 'payrun:2026-05',
              kind: 'post', posted_at: '2026-06-01T09:00:00Z', posted_by: 'Finance Approver',
              debit: 123500000 }],
  pending: [
    // Payroll has no id: it posts by PERIOD, one run a month.
    { source: 'payrun', label: 'Payroll 2026-05', detail: '1 employee(s)' },
    // A claim posts by ID and carries its own caveats, which must reach the person clicking.
    { source: 'invoice', id: 'PA-7', label: 'Claim PA-7', detail: '2,000,000,000',
      warnings: ['The VAT on this claim was not priced against a recorded tax point'] },
  ],
};

// --- the page's own helpers, stubbed only where they touch the DOM or the network ---------------
const calls = [];
global._t = x => x;
global._crmEsc = x => String(x == null ? '' : x).replace(/</g, '&lt;');
global._tkEscA = x => String(x == null ? '' : x).replace(/"/g, '&quot;');
global._PAY_FMT = n => Number(n || 0).toLocaleString('en-US');
global._errMsg = e => String((e && e.message) || e);
global.tkSkeleton = () => '<div class="skeleton"></div>';
global._lvlRank = l => ({ staff: 1, editor: 2, manager: 3, management: 4, admin: 5 }[l] || 0);
global.tkApi = async (p) => { calls.push(p); return SUMMARY; };
global._glLoadAccount = async () => {};

const el = { innerHTML: '' };
global.document = { getElementById: (id) => (id === 'view-ledger' ? el : null) };

// The two module-level variables the renderer reads. take() cannot lift them — a `let` has no
// braces to brace-match — and eval-ing a `let` would scope it to this function anyway. They are
// globals because that is what the page's own top-level `let` becomes at runtime.
global._glPeriod = '';
global._glOpenAccount = '';
eval(take('async function tkRenderLedger()'));
eval(take('function glAccount(account)'));

(async () => {
  let failed = 0;
  const must = (label, cond, extra) => {
    if (!cond) { failed++; console.error('FAIL  ' + label + (extra ? '\n      ' + extra : '')); }
    else console.log('ok    ' + label);
  };

  for (const level of ['management', 'admin']) {
    global._userLevel = level;
    el.innerHTML = '';
    await tkRenderLedger();
    const h = el.innerHTML;
    must(level + ': the panel is not empty', h.length > 500, h.slice(0, 120));
    must(level + ': the trial-balance verdict is shown', h.includes('Balances'));
    must(level + ': every account appears', ['642', '334', '331'].every(a => h.includes(a)));
    must(level + ': the unposted document is named', h.includes('Payroll 2026-05'));
    must(level + ': the post button is offered', h.includes('glPost('));
    // Payroll by period (empty id), a claim by its own id — getting this wrong would post the
    // wrong document, or post nothing while reporting success.
    must(level + ': payroll posts by period, with no document id',
         h.includes('glPost("payrun","")'), h.match(/glPost\([^)]*\)/g));
    must(level + ': a claim posts by its own id',
         h.includes('glPost("invoice","PA-7")'), h.match(/glPost\([^)]*\)/g));
    must(level + ": the claim's caveat is shown before the button, not after",
         h.includes('recorded tax point'));
    must(level + ': an account on the wrong side is shown in red',
         h.includes('var(--danger)') && h.includes('-5,000,000'));
    must(level + ': the closed month is marked in the period list', h.includes('closed'));
    must(level + ': close is offered only to a Director',
         h.includes('glClose()') === (level === 'admin'),
         level + ' saw glClose: ' + h.includes('glClose()'));
  }

  // An unbalanced ledger has to SAY so — the whole reason the report exists.
  SUMMARY.trialBalance.balanced = false;
  SUMMARY.trialBalance.difference = 1000000;
  el.innerHTML = '';
  await tkRenderLedger();
  must('an unbalanced month says DOES NOT BALANCE', el.innerHTML.includes('DOES NOT BALANCE'));
  must('…and says by how much', el.innerHTML.includes('1,000,000'));

  // Nothing posted yet: the empty state must explain what can post, not just say "no data".
  SUMMARY.trialBalance = { balanced: true, debit: 0, credit: 0, difference: 0, accounts: 0, rows: [] };
  SUMMARY.batches = []; SUMMARY.pending = []; SUMMARY.entryCount = 0;
  el.innerHTML = '';
  await tkRenderLedger();
  must('the empty state explains what can post', el.innerHTML.includes('signed'));

  // A closed period offers no posting at all.
  SUMMARY.closed = true; SUMMARY.closedBy = 'Admin User'; SUMMARY.pending = [{ source: 'payrun', label: 'Payroll', detail: '' }];
  el.innerHTML = '';
  await tkRenderLedger();
  must('a closed period offers no Post button', !el.innerHTML.includes('glPost('));
  must('…and says it is closed', el.innerHTML.includes('is closed'));

  console.log(failed ? '\n' + failed + ' problem(s)' : '\nthe Ledger screen renders.');
  process.exit(failed ? 1 : 0);
})();
