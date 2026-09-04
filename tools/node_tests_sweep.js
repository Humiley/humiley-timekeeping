/* Run every tests/*.js that no CI step names.
 *
 * WHY THIS EXISTS. .github/workflows/ci.yml names node tests one step at a time, with a comment
 * saying what each one is for — which is worth keeping, because a red step then tells you what
 * broke without opening anything. The cost is that the list is hand-maintained, and a test file
 * that never gets added to it is not a test: it is a file that looks like one.
 *
 * That was not hypothetical. At the time this was written there were 67 test files and 42 CI
 * steps. Of the 25 unnamed files, THREE were red:
 *
 *   · tests/wbs_rollup.js and tests/schedule_export.js had been broken by a commit that gave
 *     _pmTaskPctRollWalk a new dependency (_pmLeafPct) without adding it to their lift lists —
 *     the same commit that added a whole feature, reviewed and merged with a green tick;
 *   · tests/perf_polling.js was looking for `let _attHydratedFor`, a guard that had been deleted
 *     along with the fetch it guarded, so take() exited 2 and nothing was told;
 *   · tests/vi_dictionary_is_lazy.js asserted index.html was under a remembered 3.8 MB and went
 *     red when the app grew, for reasons unrelated to the dictionary it is about.
 *
 * Every one of those was found by running the files by hand. A sweep costs one CI step and means
 * a new test file is exercised the moment it lands, whether or not somebody remembers the list.
 *
 *   node tools/node_tests_sweep.js
 */
const fs = require('fs');
const path = require('path');
const { execFileSync } = require('child_process');

const ROOT = path.join(__dirname, '..');
const ci = fs.readFileSync(path.join(ROOT, '.github', 'workflows', 'ci.yml'), 'utf8');

const named = new Set();
const re = /run:\s*node\s+(tests\/[\w./-]+\.js)/g;
let m;
while ((m = re.exec(ci))) named.add(m[1]);

const all = fs.readdirSync(path.join(ROOT, 'tests'))
  .filter(f => f.endsWith('.js'))
  .map(f => 'tests/' + f)
  .sort();
const sweep = all.filter(f => !named.has(f));

console.log(all.length + ' test files, ' + named.size + ' named as their own CI step, ' +
            sweep.length + ' swept here\n');

const failed = [];
sweep.forEach(f => {
  try {
    execFileSync('node', [f], { cwd: ROOT, stdio: 'pipe', timeout: 300000 });
    console.log('  ok    ' + f);
  } catch (e) {
    failed.push(f);
    const out = String((e.stdout || '') + (e.stderr || '')).trim().split('\n');
    console.log('  FAIL  ' + f + '   (exit ' + (e.status == null ? '?' : e.status) + ')');
    out.slice(-6).forEach(l => console.log('        ' + l));
  }
});

if (failed.length) {
  console.log('\n' + failed.length + ' of ' + sweep.length + ' swept test files failed:');
  failed.forEach(f => console.log('   ' + f));
  console.log('\nRun the file directly to see the whole output:  node ' + failed[0]);
  process.exit(1);
}
console.log('\nall ' + sweep.length + ' swept test files passed');
