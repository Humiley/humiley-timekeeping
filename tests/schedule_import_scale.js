/* "The system allows a maximum of only 240 tasks to be imported."
 *
 * It does not. There is no import cap anywhere. There is a WRITE RATE LIMIT — app.py's
 * `_rate_check("write", 240, 60)`, 240 writes a minute per IP, guarding a single-process server
 * against a write flood. A 275-task import is 275 writes in a few seconds, so from the 240th the
 * server answered 429, and the import loop was:
 *
 *     for (const t of rows) { try { ...POST... n++ } catch (e) { } }
 *
 * Every 429 went into that empty catch. The toast said "Imported 239 of 275" and nothing else, and
 * from outside that is indistinguishable from a 240-row product limit — which is exactly how it was
 * reported. The count was true and useless; the reason was the whole story and was thrown away.
 *
 * The fix is not a bigger number. It is a bulk write that lives inside the budget: pace under the
 * limit, treat 429 as "later" and retry, and never lose a row in silence.
 *
 *   node tests/schedule_import_scale.js
 */
const fs = require('fs');
const path = require('path');

const src = fs.readFileSync(path.join(__dirname, '..', 'templates', 'index.html'), 'utf8');
const appPy = fs.readFileSync(path.join(__dirname, '..', 'app.py'), 'utf8');

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

// ── the limit that was mistaken for a cap ───────────────────────────────────────────────────────
console.log('\nThere is no import cap — there is a write rate limit\n');

{
  const m = appPy.match(/_rate_check\("write", (\d+), (\d+)\)/);
  ok('the server\'s write limit is findable, and is a RATE not a total', !!m,
     'if this moved, the pacing below has to be re-derived from wherever it went');
  if (m) {
    console.log('        server allows ' + m[1] + ' writes / ' + m[2] + 's per IP');
    ok('and it is the number that was reported as a task cap', +m[1] === 240,
       'the user saw "Imported 239 of 275"');
  }
  ok('nothing anywhere caps how many tasks may be imported',
     !/rows\.slice\(0,\s*\d{2,}\)/.test(take('async function pmImportTasks(', 'pmImportTasks')),
     'a silent truncation would be the other explanation for the same symptom, and would be worse');
}

// ── the paced writer, RUN ───────────────────────────────────────────────────────────────────────
console.log('\nA bulk write that lives inside the budget\n');

const BULK = take('async function _pmBulkCreate(', '_pmBulkCreate');

/* A fake server with the REAL rule: 240 writes per 60s, sliding window, 429 beyond it. Time is
   simulated so the test does not actually wait — the writer's sleeps are what is under test, and a
   test that slept for them would take minutes. */
function makeServer(limit, windowMs) {
  const hits = [];
  let now = 0;
  return {
    tick: ms => { now += ms; },
    at: () => now,
    write() {
      while (hits.length && hits[0] < now - windowMs) hits.shift();
      if (hits.length >= limit) { const e = new Error('Too many requests'); e.status = 429; throw e; }
      hits.push(now);
      return { item: { id: 'i' + hits.length } };
    }
  };
}

/* Two servers, because there are two real paths and both must be exercised:
     · `bulk: true`  — the deployed server, which has /api/coll/<name>/bulk. Rows are written in
       chunks of 250 and the whole import is a couple of requests.
     · `bulk: false` — an OLDER server that 404s the bulk route, which a browser holding a cached
       shell can genuinely be talking to. The paced per-row writer has to carry it, rate limit and
       all. This is the path the "240 cap" bug lived on, so its assertions keep the timing checks. */
const run = (nRows, limit, refuseHard, opts) => {
  opts = opts || {};
  const srv = makeServer(limit, 60000);
  const F = new Function('srv', 'nRows', 'refuseHard', 'hasBulk',
    // setTimeout is replaced by an ADVANCE of the fake clock, so the pacing and the backoff are
    // exercised for real without the suite waiting for them.
    'const setTimeout = (fn, ms) => { srv.tick(ms || 0); fn(); };\n' +
    // Production: a bulk request costs ONE `write`, and its ROWS come out of a separate
    // bulkwrite bucket (3000/min). itemBudget models that bucket; opts.itemBudget drives the
    // deferral path deliberately.
    'let calls = 0, bulkCalls = 0;\n' +
    'let itemBudget = ' + (opts.itemBudget == null ? 3000 : opts.itemBudget) + ';\n' +
    'const bad = n => refuseHard && refuseHard.indexOf(n) >= 0;\n' +
    'async function tkApi(p, o) {\n' +
    '  calls++;\n' +
    '  if (/\\/bulk$/.test(p)) {\n' +
    '    if (!hasBulk) { const e = new Error("Not found."); e.status = 404; throw e; }\n' +
    '    bulkCalls++;\n' +
    '    itemBudget -= o.body.items.length;\n' +
    '    const created = [], failed = [];\n' +
    '    o.body.items.forEach((it, i) => {\n' +
    '      if (bad(it.name)) { failed.push({ index: i, status: 400, error: "Task name is required." }); return; }\n' +
    '      if (itemBudget < 0) { failed.push({ index: i, status: 429, error: "Too many requests" }); return; }\n' +
    '      created.push({ id: "b" + (i + bulkCalls * 1000) });\n' +
    '    });\n' +
    '    return { ok: true, created: created, failed: failed };\n' +
    '  }\n' +
    '  if (bad(o.body.name)) { const e = new Error("Task name is required."); e.status = 400; throw e; }\n' +
    '  return srv.write();\n' +   // concurrent calls are simultaneous: only the writer's sleeps move time
    '}\n' +
    'function _errMsg(e){ return e.message; }\n' +
    'function _t2(en, vn){ return en; }\n' +
    BULK + '\n' +
    'const rows = Array.from({length: nRows}, (_, i) => ({ name: "T" + i }));\n' +
    'let waits = 0;\n' +
    'return _pmBulkCreate("pm_tasks", rows, (d, t, w) => { if (w) waits++; }, { projectId: "P1" })\n' +
    '  .then(r => ({ r, calls, bulkCalls, waits, ms: srv.at() }));');
  return F(srv, nRows, refuseHard || null, opts.bulk !== false);
};

run(275, 240).then(o => {
  ok('all 275 rows are written, not 239',
     o.r.created.length === 275 && o.r.failed.length === 0,
     'created ' + o.r.created.length + ', failed ' + o.r.failed.length +
     ' — this is the reported bug, reproduced against the real 240/60s rule');
  ok('on a current server that is 2 requests, not 275',
     o.bulkCalls === 2 && o.calls === 2,
     o.calls + ' request(s), ' + o.bulkCalls + ' of them bulk');
  ok('and it finishes without waiting out the rate limit',
     o.ms < 5000,
     Math.round(o.ms / 1000) + 's of simulated time — the whole point of the bulk route');

  /* And when the ROW budget does run out mid-batch, the rows it deferred are finished by the paced
     writer rather than reported as failures. A 429 on a row means "later"; recording it as a
     refusal would lose it exactly the way the empty catch did, only with a better message. */
  return run(275, 240, null, { itemBudget: 200 });
}).then(o => {
  ok('rows a batch defers for budget are finished, not failed',
     o.r.created.length === 275 && o.r.failed.length === 0,
     'created ' + o.r.created.length + ', failed ' + o.r.failed.length +
     ' (' + o.calls + ' requests) — the deferred rows must come back through the paced writer');

  // Same file, older server. The paced writer has to carry it, rate limit and all.
  return run(275, 240, null, { bulk: false });
}).then(o => {
  ok('against an OLD server every row still lands, one request at a time',
     o.r.created.length === 275 && o.r.failed.length === 0,
     'created ' + o.r.created.length + ', failed ' + o.r.failed.length);
  ok('and that path really does wait out the limiter',
     o.ms > 30000,
     'wrote 275 in ' + Math.round(o.ms / 1000) + 's of simulated time; finishing instantly would ' +
     'mean the fake server is not enforcing the limit and this test proves nothing');

  return run(500, 240, null, { bulk: false });
}).then(o => {
  ok('a 500-task programme imports in full', o.r.created.length === 500 && !o.r.failed.length,
     'created ' + o.r.created.length + ', failed ' + o.r.failed.length);
  /* Pacing is not what makes the rows land — the retry is. Pacing shows up as how much refusal a
     legitimate import provokes: a writer that sprints into the limit still finishes, having been
     told "no" hundreds of times and slept off each one. */
  ok('and it barely troubles the limiter on the way',
     o.waits < 40,
     o.waits + ' rate-limit pauses for 500 rows — the writer is sprinting into the guard instead ' +
     'of staying under it');

  // A REAL refusal must not be retried forever, and must be reported with its reason — on both
  // paths, since the fast one gets its refusals back in a list rather than as a thrown error.
  return run(20, 240, ['T7', 'T13'], { bulk: false });
}).then(o => {
  ok('slow path: a row the server genuinely refuses is not retried', o.r.failed.length === 2,
     'failed ' + o.r.failed.length);
  return run(20, 240, ['T7', 'T13']);
}).then(o => {
  ok('a row the server genuinely refuses is not retried', o.r.failed.length === 2,
     'failed ' + o.r.failed.length + ' — a 400 will answer the same way however long you wait');
  ok('and it comes back with the row and the reason, not just a count',
     o.r.failed.every(f => f.row && f.row.name && /required/.test(f.why)),
     JSON.stringify(o.r.failed));
  ok('the other 18 still land', o.r.created.length === 18);
  rest();
});

function rest() {
console.log('\nAnd nothing is lost in silence\n');

// ── the fast path ──────────────────────────────────────────────────────────────────────────────
ok('a bulk endpoint is used first, in chunks',
   /tkApi\('\/api\/coll\/' \+ coll \+ '\/bulk'/.test(BULK) && /const CHUNK = 250;/.test(BULK),
   '500 tasks as two requests instead of 500 is the difference between seconds and two and a half ' +
   'minutes');
ok('the server caps a batch at the same number the client sends',
   /BULK_MAX = 250/.test(appPy),
   'a client chunk larger than the server cap makes every request 413 — the two numbers are one ' +
   'decision and have to be read together');
ok('per-row failures from the batch keep their row',
   /const row = slice\[f\.index\] \|\| \{\};/.test(BULK),
   'the server returns an index; without mapping it back the browser can only report a count');
ok('and a row deferred for budget is retried rather than recorded as failed',
   /if \(f\.status === 429\) later\.push\(row\);/.test(BULK),
   '429 means later; filing it under failures loses the row the same way the empty catch did');
ok('an old server (404/405) falls back to the paced writer instead of failing',
   /e\.status === 404 \|\| e\.status === 405/.test(BULK),
   'a cached shell can be newer than the server it talks to — "the import silently does nothing ' +
   'after a deploy" is worse than "the import is slower than it could be"');
ok('and the fallback discards what the fast path had banked',
   /created\.length = 0; failed\.length = 0;/.test(BULK),
   'otherwise rows created by the first chunk are counted twice');
ok('a 429 from the batch also falls through to the paced writer',
   /if \(e && e\.status === 429\)/.test(BULK),
   'that means the ROW budget is spent, not that bulk is unavailable — the paced writer knows how ' +
   'to wait');

ok('the writer distinguishes 429 from every other status',
   /e\.status === 429 && attempt < RETRIES/.test(BULK),
   'retrying a 400 forever is as wrong as dropping a 429');
ok('the backoff grows rather than hammering', /wait = Math\.min\(wait \* 2, 20000\)/.test(BULK));
ok('a refused row is pushed onto failed, never swallowed',
   /failed\.push\(\{ row: row, why: _errMsg\(e\) \}\);/.test(BULK));
ok('progress is reported while it runs, including while waiting',
   /onProgress\(created\.length, rows\.length, true\)/.test(BULK),
   'a paced 500-row import is minutes of apparently nothing happening');

const IMP = take('async function pmImportTasks(', 'pmImportTasks');
ok('the master import no longer has an empty catch',
   !/catch \(e\) \{ \}/.test(IMP.replace(/catch \(e\) \{ \}\s*\n\s*await tkLoadColl/, '')),
   'this is the line that turned a rate limit into a phantom product limit');
ok('it routes through the paced writer', /_pmBulkCreate\('pm_tasks', rows/.test(IMP));
ok('it warns before starting that a big file takes minutes',
   /takes about ' \+ Math\.ceil\(total \/ 200\)/.test(IMP),
   'a silent two-minute wait reads as a hung page, and people close the tab');
ok('a partial import explains itself instead of printing a bare count',
   // The failure branch must REACH the alert. Matching the alert's text alone passes on code that
   // still builds the message and never shows it.
   /if \(res\.failed\.length\) \{\s*(\/\/[^\n]*\n\s*)*await tkAlert\(\{ title: _t2\(n \+ ' of ' \+ total/.test(IMP) &&
   /The first reason was/.test(IMP),
   '"Imported 239 of 275" with no reason is what made this look like a cap');
ok('and it says that re-importing the rest will not duplicate what is already in',
   /are not duplicated by a second attempt/.test(IMP),
   'the obvious next move after a partial import is to run it again, and nothing said whether that ' +
   'was safe');
ok('the audit entry records the shortfall too',
   /' refused'/.test(IMP));

const PDI = take('async function pdImportRun(', 'pdImportRun');
ok('the detail import is paced the same way', /_pmBulkCreate\(_PD_COLL, bodies/.test(PDI),
   'a 400-line paste hits the same limit; it reported its failures but still lost the rows');
ok('and it still reports every failure it gets',
   /const failed = _res\.failed\.map/.test(PDI) && /Some rows were not imported/.test(PDI));

console.log('\n  ' + pass + ' passed, ' + fail + ' failed\n');
process.exit(fail ? 1 : 0);
}
