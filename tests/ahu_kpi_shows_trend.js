// The KPI panel must SHOW the trend, not merely receive it.
//
// /api/ahu/kpi returns a `trend` block. Exactly the gap #170 had: a series nobody renders answers
// nobody's question. The figure says where the factory is; only the strip says which way it is
// going, which is the sole reason a target exists.
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

let failed = 0;
function must(what, cond, extra) {
  if (cond) { console.log('  ok   ' + what); return; }
  failed++;
  console.log('  FAIL ' + what + (extra ? '\n       ' + extra : ''));
}

const KPI = {
  units: 12, meeting: 1, ofTargets: 5, notMeasured: 3,
  kpis: [
    { kpi: 'First-Pass Yield (FPY)', key: 'firstPassYield', target: '>= 97%', owner: 'QA/QC',
      n: 12, pct: 91.7, met: false },
    { kpi: 'On-Time Delivery (OTD)', key: 'onTimeDelivery', target: '>= 95%', owner: 'PMO',
      n: 8, pct: 100.0, met: true, late: [] },
    { kpi: 'Thermal Bridging Class', status: 'NOT_MEASURED',
      why: 'no test for it exists in the production route' },
  ],
  trend: {
    minN: 5,
    firstPassYield: [
      { month: '2026-06', n: 9, good: 9, pct: 100.0, enough: true },
      { month: '2026-07', n: 2, good: 1, pct: 50.0, enough: false },
      { month: '2026-08', n: 12, good: 11, pct: 91.7, enough: true },
    ],
    onTimeDelivery: [{ month: '2026-08', n: 8, good: 8, pct: 100.0, enough: true }],
    unbucketed: { firstPassYield: 0, onTimeDelivery: 0 },
  },
};

(async () => {
  const root = { innerHTML: '' };
  global.document = { getElementById: (id) => (id === 'ahu-sop-kpi' ? root : null) };
  global.tkApi = async () => KPI;
  global._ahuEsc = (v) => String(v == null ? '' : v);
  global._ahuA = (v) => String(v == null ? '' : v);
  global._ahuCard = (h) => '<div class="card">' + h + '</div>';

  eval(take('function _ahuTrendStrip('));
  eval(take('async function ahuRenderSopKpi()'));
  await ahuRenderSopKpi();
  const h = root.innerHTML;

  must('the panel renders', h.length > 500, h.slice(0, 200));
  must('the yield figure is still there', h.includes('91.7'));

  // Four bars, not three: 2026-08 appears in BOTH series, once for yield and once for delivery.
  // The first version of this assertion expected three and was simply wrong about the fixture.
  must('every month of every series gets a bar',
       (h.match(/title="2026-0[678]/g) || []).length === 4,
       (h.match(/title="2026[^"]*"/g) || []).join(' | '));
  must('…including all three months of the yield series',
       h.includes('title="2026-06') && h.includes('title="2026-07') &&
       (h.match(/title="2026-08/g) || []).length === 2);
  must('the months are labelled', h.includes('>06<') && h.includes('>07<') && h.includes('>08<'));

  // THE judgement, carried through to the screen: a thin month keeps its slot and is drawn hollow.
  must('a month with too few units says so in its tooltip',
       h.includes('n=2 (below 5, too few to read)'));
  must('…and is drawn hollow rather than as a solid bar people would read',
       /2026-07[^"]*"[^>]*>\s*<div[^>]*border:1px dashed/.test(h.replace(/\n/g, '')),
       (h.match(/title="2026-07[^]{0,200}/) || ['(not found)'])[0]);
  must('a readable month is solid', /2026-08[^"]*"[^>]*>\s*<div[^>]*background:#/.test(h.replace(/\n/g, '')));

  // Every bar carries its count, readable or not — the number that says how much to trust the point.
  must('every bar carries its sample size', (h.match(/n=\d+/g) || []).length >= 4);

  must('the KPI with no series gets no strip, rather than an empty box',
       (h.match(/height:60px/g) || []).length === 2);

  // An older server, or one KPI without a key, must not break the panel.
  delete KPI.trend;
  root.innerHTML = '';
  await ahuRenderSopKpi();
  must('a server with no trend block still renders the KPI panel',
       root.innerHTML.includes('91.7') && !root.innerHTML.includes('height:60px'));

  console.log(failed ? '\n' + failed + ' problem(s)' : '\nthe KPI panel shows the trend.');
  process.exit(failed ? 1 : 0);
})();
