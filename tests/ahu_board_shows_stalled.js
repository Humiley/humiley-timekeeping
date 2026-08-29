// The board must SHOW what has stopped, not merely receive it.
//
// /api/ahu/board returns a `stalled` block. A JSON field nobody renders makes nothing easier to
// monitor — which was the entire point of adding it — and a render that throws leaves an empty
// panel that nobody reports, exactly as the Stages & Gates tab blanked in production for weeks.
//
// So this drives the real ahuRenderBoard() against a real payload and reads the HTML back.
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

const BOARD = {
  units: [
    { unitId: 'u1', pin: 'PIN-0001', tag: 'AHU-A', family: 'modular', stage: 3,
      stageTitle: 'Assembly', progress: 40, signed: 12, total: 30, next: ['WS-05'],
      nextTitle: 'Panel fit', failed: [], running: [], openNcr: 0 },
    { unitId: 'u2', pin: 'PIN-0002', tag: 'AHU-B', family: 'hygienic', stage: 2,
      stageTitle: 'Framing', progress: 20, signed: 6, total: 30, next: ['WS-02'],
      nextTitle: 'Frame', failed: [], running: [], openNcr: 0 },
  ],
  stalled: {
    threshold: 7,
    stalled: [{ unitId: 'u1', pin: 'PIN-0001', days: 19, lastCode: 'WS-04' }],
    neverStarted: [], undateable: [],
  },
};

(async () => {
  const root = { dataset: {}, innerHTML: '' };
  global.document = {
    getElementById: (id) => (id === 'ahu-board-root' ? root : null),
  };
  global.tkApi = async () => BOARD;
  global.tkSkeleton = () => '';
  global._AHU = { stageFilter: 0, process: { stages: [] } };
  global._ahuProcess = async () => ({ stages: [] });
  global._ahuBoardTick = () => {};
  global._ahuEsc = (v) => String(v == null ? '' : v);
  global._ahuA = (v) => String(v == null ? '' : v);
  global._ahuCard = (h) => '<div class="card">' + h + '</div>';
  global._ahuBadge = (t) => '<span class="badge">' + t + '</span>';
  global._ahuBar = () => '<div class="bar"></div>';
  global._ahuEmpty = (a, b) => a + b;
  global._ahuFlowStrip = () => '';
  global._t = (s) => s;
  global.ahuRenderSopKpi = () => {};   // the SOP KPI panel fills itself in later

  eval(take('async function ahuRenderBoard()'));
  await ahuRenderBoard();
  const h = root.innerHTML;

  must('the board renders at all', h.length > 500, h.slice(0, 200));
  must('there is a counter for what has stopped', h.includes('No movement'));
  must('…carrying the threshold, so the number means something', h.includes('(7d+)'));
  // Precise on purpose. An `|| h.includes('>1<')` fallback here passed on almost any HTML — the
  // count 1 appears all over a board of two units — which is a check that examines nothing.
  must('…and the count sits in that tile, not merely somewhere on the page',
       /No movement \(7d\+\)<\/div><div[^>]*>1<\/div>/.test(h),
       (h.match(/No movement[^]{0,120}/) || ['(tile not found)'])[0]);
  must('the STOPPED unit is badged on its own row, not just totalled',
       h.includes('No movement 19d'));
  must('…and the row is still the right unit', h.includes('PIN-0001'));
  must('a unit that is moving carries no such badge',
       (h.match(/No movement \d+d/g) || []).length === 1);

  // The counter must go quiet when nothing has stopped — a red figure that is always red is one
  // people stop reading.
  BOARD.stalled = { threshold: 7, stalled: [], neverStarted: [], undateable: [] };
  root.innerHTML = '';
  await ahuRenderBoard();
  const h2 = root.innerHTML;
  must('with nothing stopped the counter still shows, reading zero', h2.includes('No movement'));
  must('…and no row is badged', !/No movement \d+d/.test(h2));

  // A server that has not been redeployed yet returns no `stalled` block at all. The board must
  // still draw rather than throw — the whole screen is worth more than one counter.
  delete BOARD.stalled;
  root.innerHTML = '';
  await ahuRenderBoard();
  must('an older server with no stalled block does not break the board',
       root.innerHTML.includes('PIN-0001'));

  console.log(failed ? '\n' + failed + ' problem(s)' : '\nthe board shows what has stopped.');
  process.exit(failed ? 1 : 0);
})();
