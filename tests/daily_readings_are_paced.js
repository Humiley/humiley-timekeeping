/* A day's readings all arrive, even when there are four hundred of them.
 *
 * app.py refuses every non-GET past 240 writes in 60 seconds per client IP (ratelimit.py) — a fair
 * guard on a single-process server. Both daily-progress tables sent one PATCH per changed row as
 * fast as the round trip allowed and treated any failure as final, so a site engineer filling in a
 * 400-activity programme and pressing File progress met the ceiling at row 240 and was shown 160
 * failures, with an afternoon of readings to type again. Nothing was wrong with the readings and
 * nothing was wrong with the server: the client simply sprinted into a budget it could have walked
 * inside. _pmBulkCreate learnt this on the importer — "a 500-line programme is a legitimate 500
 * writes" — and these two paths, which a site engineer uses every day rather than once, did not.
 *
 * This runs the REAL _pdFileReadings against a fake server implementing ratelimit.py's actual rule,
 * on a virtual clock, so "it waits long enough" is measured rather than asserted.
 *
 *   node tests/daily_readings_are_paced.js
 */
const fs = require('fs');
const path = require('path');

const src = fs.readFileSync(path.join(__dirname, '..', 'templates', 'index.html'), 'utf8');

/* RED UNTIL PROVEN GREEN. Every timer in this file is fake, so if the driver below ever stops
   advancing the clock while work is still outstanding, node's event loop is empty and the process
   exits 0 having printed one heading. An exit code that means "passed" when nothing ran is the
   failure this repo keeps re-finding, so the exit code starts at 1 and is only cleared by reaching
   the end. */
process.exitCode = 1;

let pass = 0, fail = 0;
const ok = (n, c, extra) => {
  if (c) { pass++; console.log('  ok    ' + n); }
  else { fail++; console.log('  FAIL  ' + n + (extra ? '\n        ' + extra : '')); }
};

function take(name) {
  const re = new RegExp('\\n(?:async )?function ' + name + '\\s*\\(');
  const i = src.search(re);
  if (i < 0) {
    console.error('could not find ' + name + ' — update the marker, do NOT delete this test.');
    process.exit(2);
  }
  const from = i + 1;
  const ends = ['\nfunction ', '\nasync function ', '\nconst ', '\n/* ']
    .map(m => src.indexOf(m, from + 10)).filter(x => x > 0);
  return src.slice(from, ends.length ? Math.min.apply(null, ends) : from + 5000);
}

/* A virtual clock. Real sleeps would make this file take minutes and would measure the runner's
   mood rather than the code; a fake timer that ADVANCES time is what turns "it retried" into "it
   retried late enough that the window had moved". */
function makeWorld(opts) {
  const O = opts || {};
  const LIMIT = O.limit === undefined ? 240 : O.limit;
  const WINDOW = 60000;
  let now = 0;
  const pending = [];
  const hits = [];                       // ms of each ACCEPTED write, exactly as ratelimit.py records
  const world = {
    calls: 0, refusals: 0, inflight: 0, maxInflight: 0,
    now: () => now,
    setTimeout(fn, ms) { pending.push({ at: now + (+ms || 0), fn: fn }); return pending.length; },
    /* Drive `p` to completion on the virtual clock.
       Draining "until no timers are left" is not enough and was the first version's bug: the code
       under test is a chain of awaits, so there are moments with nothing scheduled and plenty still
       to do. Stopping there left the caller awaiting a promise nothing would ever resolve, node
       found an empty event loop, and the process exited 0 after printing one heading. So the driver
       watches the PROMISE, not the timer queue. */
    async run(p) {
      let done = false, out, err;
      p.then(v => { done = true; out = v; }, e => { done = true; err = e; });
      for (let guard = 0; guard < 500000; guard++) {
        for (let k = 0; k < 50; k++) await Promise.resolve();   // let the await chain move
        if (done) { if (err) throw err; return out; }
        if (!pending.length) throw new Error('deadlock: nothing pending and the work is unfinished');
        pending.sort((a, b) => a.at - b.at);
        const t = pending.shift();
        now = Math.max(now, t.at);
        t.fn();
      }
      throw new Error('the virtual clock never settled — a retry loop is not terminating');
    },
    tkApi(pathStr, opt) {
      // The call's OWN sequence number, captured at issue time. Reading world.calls inside the
      // callback instead counts every request the batch has issued in the meantime, so with six in
      // flight "every third request fails" became "all of them fail" — a fixture fault that reads
      // exactly like a defect in the code under test.
      const seq = ++world.calls;
      world.inflight++;
      world.maxInflight = Math.max(world.maxInflight, world.inflight);
      return new Promise((resolve, reject) => {
        // The round trip. 120ms is optimistic for this portal, which is the point: the faster the
        // network, the sooner an unpaced loop reaches the ceiling.
        world.setTimeout(() => {
          world.inflight--;
          if (O.failEvery && seq % O.failEvery === 0) {
            const e = new Error('Server exploded'); e.status = 500; reject(e); return;
          }
          while (hits.length && hits[0] <= now - WINDOW) hits.shift();
          if (hits.length >= LIMIT) {
            world.refusals++;
            const e = new Error('Too many requests'); e.status = 429; reject(e); return;
          }
          hits.push(now);                       // a REFUSAL does not extend the window — ratelimit.py
          resolve({ item: { _rev: 99 } });
        }, 120);
      });
    },
  };
  return world;
}

const API = world => new Function('W',
  'const tkApi = W.tkApi;\n' +
  'const setTimeout = W.setTimeout;\n' +
  'const _errMsg = e => (e && e.message) || String(e);\n' +
  take('_pdFileReadings') +
  '\nreturn _pdFileReadings;')(world);

const jobs = n => {
  const out = [];
  for (let i = 0; i < n; i++) out.push({ r: { id: 'r' + i, name: 'Activity ' + i, _rev: 1 }, log: [{ d: '2026-09-04', pct: 50 }] });
  return out;
};

(async () => {
  // ══ 1. the finding ═══════════════════════════════════════════════════════════════════════════
  console.log('\nA 400-activity programme files completely\n');
  {
    const W = makeWorld();
    const fn = API(W);
    const js = jobs(400);
    const res = await W.run(fn('pm_tasks', js));
    ok('every reading is filed', res.ok === 400 && res.failed.length === 0,
       'ok ' + res.ok + ', failed ' + res.failed.length +
       (res.failed.length ? ' — first: ' + res.failed[0] : ''));
    ok('and each row keeps the reading it filed', js.every(j => j.r.log === j.log));
    ok('and the SERVER\'s _rev, so the next save of the day does not self-409',
       js.every(j => j.r._rev === 99),
       'tkApi sends If-Match from the row it is handed; a stale _rev is a 409 waiting to happen');
    ok('it took real time rather than sprinting', W.now() > 60000,
       'finished in ' + W.now() + 'ms of virtual time — under one window means it never paced');
    /* THE POINT OF THE GAP, and the assertion that was missing when this file was first written:
       completion alone does not test the pacing, because the retry recovers from any amount of
       over-running. What the gap buys is that the ceiling is never MET — the server sends no
       refusals at all, so nobody waits and nothing is re-sent. Simulated over 400 rows through the
       real sliding window, the inherited 900 ms gap produces 356 writes/min and 114 refusals; the
       1500 ms gap produces 224/min and none. */
    ok('and the server never had to refuse a single write', W.refusals === 0,
       W.refusals + ' refusals — the client is issuing writes faster than 240/min and leaning on ' +
       'the retry to clean up after itself');
  }

  // ══ 2. the same run against the old unpaced loop, so the fixture is known to bite ═════════════
  console.log('\nThe limit is real — an unpaced loop loses readings on this same fixture\n');
  {
    const W = makeWorld();
    const js = jobs(400);
    let ok0 = 0; const failed0 = [];
    for (const j of js) {
      await W.run(W.tkApi('/api/coll/pm_tasks/' + j.r.id, { method: 'PATCH' })
        .then(() => { ok0++; }, e => { failed0.push(e.status); }));
    }
    ok('the unpaced loop is refused partway through', failed0.length > 0,
       'if this passes with 0 failures the fake limiter is not limiting, and section 1 proves nothing');
    ok('and it is the rate limit doing it', failed0.every(s => s === 429));
    ok('losing most of the afternoon', ok0 <= 260 && failed0.length >= 140,
       'filed ' + ok0 + ', lost ' + failed0.length);
  }

  // ══ 2b. and when the ceiling IS met anyway, the readings still all arrive ═════════════════════
  console.log('\nA tighter budget is a delay, not a loss\n');
  {
    /* Pacing alone left the retry untested: at 224 writes/min against a 240/min budget the server
       never refuses, so every mutation of the retry survived — the code was there and nothing ran
       it. The rate limit is per IP, though, and this company shares one office connection: a
       colleague filing their own schedule, or an import running, and the budget available to this
       browser is a fraction of 240. That is the case the retry exists for, so it is the case tested
       here — half the budget, and every reading must still arrive. */
    const W = makeWorld({ limit: 120 });
    const fn = API(W);
    const js = jobs(200);
    const res = await W.run(fn('pm_tasks', js));
    ok('the server does refuse this time', W.refusals > 0,
       'with no refusals the retry below is not being exercised and its tests prove nothing');
    ok('and every reading still arrives', res.ok === 200 && res.failed.length === 0,
       'ok ' + res.ok + ', failed ' + res.failed.length +
       (res.failed.length ? ' — first: ' + res.failed[0] : ''));
    ok('by waiting longer each time rather than hammering', W.calls < 200 * 4,
       'took ' + W.calls + ' requests for 200 rows — a flat retry interval re-sends into a budget ' +
       'that has not moved yet and spends its attempts before the window does');
  }

  // ══ 3. a real refusal is not retried for ever ═════════════════════════════════════════════════
  console.log('\nA 500 is a refusal, not a delay\n');
  {
    const W = makeWorld({ failEvery: 3 });
    const fn = API(W);
    const js = jobs(9);
    const res = await W.run(fn('pm_tasks', js));
    ok('the failing rows are reported', res.failed.length === 3,
       'got ' + res.failed.length + ': ' + JSON.stringify(res.failed));
    ok('named, so somebody knows which to re-enter', res.failed.every(f => /^Activity \d+: /.test(f)),
       JSON.stringify(res.failed));
    ok('and it is not re-sent — a 500 would only answer the same way more slowly',
       W.calls === 9, 'got ' + W.calls + ' requests for 9 rows');
    ok('while the rest are filed', res.ok === 6);
  }

  // ══ 4. bounded concurrency ═══════════════════════════════════════════════════════════════════
  console.log('\nIt does not open four hundred sockets\n');
  {
    const W = makeWorld();
    const fn = API(W);
    await W.run(fn('pm_tasks', jobs(100)));
    ok('at most a small batch is in flight at once', W.maxInflight <= 6,
       'peak ' + W.maxInflight + ' concurrent writes');
    ok('but more than one, or pacing would just be a slow serial loop', W.maxInflight > 1);
  }

  // ══ 5. nothing to do ═════════════════════════════════════════════════════════════════════════
  console.log('\nAnd an empty batch is free\n');
  {
    const W = makeWorld();
    const fn = API(W);
    const res = await W.run(fn('pm_tasks', []));
    ok('no requests, no waiting', W.calls === 0 && res.ok === 0 && res.failed.length === 0);
  }

  console.log('\n' + pass + ' passed, ' + fail + ' failed\n');
  process.exitCode = fail ? 1 : 0;          // clears the pessimistic 1 set at the top
})().catch(e => { console.error('\nthe harness itself failed: ' + (e && e.stack || e)); process.exitCode = 1; });
