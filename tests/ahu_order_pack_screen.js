// The handover verdict must reach a SCREEN, not just an endpoint.
//
// #202 shipped /api/ahu/order/<id>/pack with nothing drawing it, and said so. This is the half that
// answers somebody's question. The same gap #173 and #175 existed to close for the stall alert and
// the KPI trend — three times is enough to make it a test.
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

const NOTE = 'Every unit must be ready, not most of them — a package is handed over whole.';

const BLOCKED = {
  order: { poNumber: 'PO-2026-0417' },
  unitCount: 3,
  status: 'NOT_READY',
  ready: false,
  why: ['AHU-B-02 — Not dispatched.', 'AHU-B-02 — 1 non-conformance(s) still open.',
        'AHU-B-03 — Gates not signed: G6.'],
  counts: { ready: 1, blocked: 2, dispatched: 1, unroutable: 0, openNcr: 1 },
  units: [
    { unitId: 'u1', pin: 'AHU-B-01', tag: 'T1', stage: 7, stageTitle: 'Dispatch',
      ready: true, blockers: [] },
    { unitId: 'u2', pin: 'AHU-B-02', tag: 'T2', stage: 5, stageTitle: 'Assembly',
      ready: false, blockers: ['Not dispatched.', '1 non-conformance(s) still open.'] },
    { unitId: 'u3', pin: 'AHU-B-03', tag: 'T3', stage: 6, stageTitle: 'Test',
      ready: false, blockers: ['Gates not signed: G6.'] },
  ],
  note: NOTE,
};

const READY = {
  order: { poNumber: 'PO-READY' }, unitCount: 2, status: 'READY', ready: true, why: [],
  counts: { ready: 2, blocked: 0, dispatched: 2, unroutable: 0, openNcr: 0 },
  units: [
    { unitId: 'u1', pin: 'R-1', tag: 'T1', stage: 7, stageTitle: 'Dispatch', ready: true, blockers: [] },
    { unitId: 'u2', pin: 'R-2', tag: 'T2', stage: 7, stageTitle: 'Dispatch', ready: true, blockers: [] },
  ],
  note: NOTE,
};

const EMPTY = {
  order: { poNumber: 'PO-EMPTY' }, unitCount: 0, status: 'NOTHING_TO_REVIEW', ready: false,
  why: ['No units are registered against this order, so there is nothing to review.'],
  counts: { ready: 0, blocked: 0, dispatched: 0, unroutable: 0, openNcr: 0 },
  units: [], note: NOTE,
};

(async () => {
  const box = { innerHTML: '' };
  global.document = { getElementById: (id) => (id === 'ahu-order-pack' ? box : null) };
  global._ahuEsc = (v) => String(v == null ? '' : v);
  global._ahuA = (v) => String(v == null ? '' : v);
  global._ahuCard = (h) => '<div class="card">' + h + '</div>';
  global._ahuBadge = (t, c) => '<span class="badge" data-c="' + c + '">' + t + '</span>';

  eval(take('async function ahuOrderPack('));

  // ── not ready ────────────────────────────────────────────────────────────────────────────────
  global.tkApi = async () => BLOCKED;
  await ahuOrderPack('ord-1');
  let h = box.innerHTML;

  must('the panel draws at all', h.length > 400, h.slice(0, 160));
  must('the verdict is stated in words, not left to a colour',
       h.includes('Not ready to hand over'));
  must('the order is named', h.includes('PO-2026-0417'));

  // THE thing this module is written around: "ready" over nothing is the failure mode, so the count
  // the verdict was computed over has to sit next to the verdict.
  must('the unit count the verdict was computed over is shown', h.includes('over 3 unit(s)'));

  must('every reason is listed', BLOCKED.why.every(w => h.includes(w)),
       BLOCKED.why.filter(w => !h.includes(w)).join(' | '));
  must('each unit gets a row', h.includes('AHU-B-01') && h.includes('AHU-B-02') &&
       h.includes('AHU-B-03'));
  must('a ready unit is badged ready', /AHU-B-01[^]*?Ready</.test(h));
  must('a blocked unit shows how many blockers', h.includes('2 blocker(s)'));
  // Strip style="…" first. A bare /\d+%/ matches `width:100%` in the table CSS and fails on
  // rendering that is perfectly correct — the rule is about a COMPLETENESS figure shown to a
  // reader, not about stylesheet units. The first version of this assertion got that wrong.
  const text = h.replace(/style="[^"]*"/g, '');
  must('no completeness percentage survives to the screen',
       !/\d+\s*%/.test(text), (text.match(/\d+\s*%/g) || []).join(' '));
  must('the note travels with the table', h.includes('handed over whole'));

  // ── ready ────────────────────────────────────────────────────────────────────────────────────
  global.tkApi = async () => READY;
  box.innerHTML = '';
  await ahuOrderPack('ord-2');
  h = box.innerHTML;
  must('a ready order says so', h.includes('Ready to hand over'));
  must('…and lists no blockers', !h.includes('What is holding it'));

  // ── nothing to review — a THIRD state, not a red one ─────────────────────────────────────────
  global.tkApi = async () => EMPTY;
  box.innerHTML = '';
  await ahuOrderPack('ord-3');
  h = box.innerHTML;
  must('an empty order is NOT drawn as "not ready"', !h.includes('Not ready to hand over'));
  must('…it says nothing to review', h.includes('Nothing to review'));
  must('…in its own colour, not the blocked red', h.includes('#A16207'));
  must('…and still says it was computed over zero units', h.includes('over 0 unit(s)'));

  // ── the endpoint failing must not blank the screen ───────────────────────────────────────────
  global.tkApi = async () => { throw new Error('boom'); };
  box.innerHTML = '';
  await ahuOrderPack('ord-4');
  must('a failed request explains itself rather than leaving an empty panel',
       box.innerHTML.includes('Could not build the handover pack') &&
       box.innerHTML.includes('boom'));

  console.log(failed ? '\n' + failed + ' problem(s)' : '\nthe handover pack reaches the screen.');
  process.exit(failed ? 1 : 0);
})();
