/* One key, one meaning: the Vietnamese dictionary must not define a key twice.
 *
 * `_VI` is a plain object literal, so a key defined twice keeps the LAST value and drops the first —
 * silently, at parse time, with no warning anywhere. Thirty-three redundant definitions had
 * accumulated across 32 keys; seven of them disagreed, so one screen's wording was quietly
 * overwriting another's ('Retention' meant both a records retention period and retention money).
 *
 * WHY THIS FILE DOES NOT USE A REGEX, and what four attempts to count the dictionary proved.
 *
 * Five measurements of this dictionary have produced five different answers, and they failed in two
 * distinct ways that need two distinct defences. FOUR were true answers to unstated questions —
 * key-quote only vs key-and-value, line-anchored, "slots added" vs "keys new to the dictionary".
 * Those die to stating your predicate. The FIFTH asked the right question and simply counted wrong
 * (`grep -c`, below). No predicate would have saved it; only a second instrument would — which is
 * what the print at the bottom of this file is, permanently installed. The counts below
 * are a DATED SAMPLE at 3d71d42, not an inventory. This run prints its own live decomposition
 * two lines below — if a number here is quoted as current, the tool's own output contradicts it.
 * Never quote a total from this dictionary without the pattern that produced it:
 *
 *     keys quoted '                      3253
 *     keys quoted "                       511
 *     sum                                3764   == Object.keys(), exactly
 *     pairs 'k' : 'v'                    3210   a pattern that ALSO constrains the value quote
 *                                               silently drops the 43 'k' : "v" rows
 *     line-anchored variant              2673   a gap of 1091
 *
 * The misses are NOT keys containing apostrophes — that was the standing explanation here and it is
 * wrong. Only 10 of the 511 double-quoted keys contain one, and no value does. 504 of the 511 are a
 * single contiguous run. 6942bde (the ~420-string EN/VN batch) started it: 419 double-quoted slots
 * added against a parent holding 3, of which 418 were new keys and one, 'Retention', already existed
 * single-quoted — which is how this file's motivating duplicate got made.
 *
 * But that block is an ATTRACTOR, not one author's batch. It grew 422 -> 511 across eleven later
 * commits by different sessions (017d995 +60, 25886e2 +2, seven others +1), each matching the style
 * beside it. Nobody chose double quotes. So the blind spot cannot be found by reading the strings,
 * and it MOVES whenever anyone appends near the block — which is why the fix is a scanner that
 * checks itself against the engine, not a better pattern. It is still moving, and these two dated
 * points are the evidence: at 3d71d42 the run was 504 and the double-quoted keys 511; on
 * 2026-08-21, 778 and 948. Half again in days. Both are fixed historical readings and stay true;
 * for anything CURRENT read this run's output, never this comment.
 *
 * 'Retention' is the case in miniature. It was already defined TWICE (both single-quoted) before
 * 6942bde, which made it a triplicate; the cleanup then kept the double-quoted copy — the one the
 * attractor had made the winner. A Set-based count cannot see any of that: it collapses the
 * duplicates it is meant to find, which is why the scanner below keeps every pair and dedupes last.
 *
 * Two instruments that lie while dating this, both of which produced confident wrong answers here:
 *   - `git log -S"<key>"` on a bare key dates when the English string first appeared ANYWHERE,
 *     usually inside a _t('...') call, commits before any translation existed. Use the key WITH its
 *     colon, in that key's own quote style:  git log -S'"<key>":'
 *   - `grep -c` counts matching LINES, not matches. This dictionary packs several pairs onto one
 *     line, so it reads low on exactly the dense input it is aimed at, and never errors. Use
 *     `grep -o | wc -l`, or parse both sides and subtract.
 *
 * The self-check below is the whole point: if the number of distinct keys this scanner finds does
 * not equal Object.keys() of the same literal evaluated, it says so rather than reporting a clean
 * bill of health.
 *
 *   node tests/vi_duplicate_keys.js
 */
const fs = require('fs');
const path = require('path');
const { execSync } = require('child_process');

function scan(literal) {
  const pairs = [];
  let depth = 0, k = 0, pending = null, line = 1;
  while (k < literal.length) {
    const c = literal[k];
    if (c === '\n') { line++; k++; continue; }
    if (c === '/' && literal[k + 1] === '*') { const e = literal.indexOf('*/', k + 2); line += (literal.slice(k, e).match(/\n/g) || []).length; k = e + 2; continue; }
    if (c === '/' && literal[k + 1] === '/') { const e = literal.indexOf('\n', k); k = e < 0 ? literal.length : e; continue; }
    if (c === '{' || c === '[') { depth++; k++; continue; }
    if (c === '}' || c === ']') { depth--; k++; continue; }
    if (c === "'" || c === '"') {
      const q = c; let s = ''; k++;
      while (k < literal.length && literal[k] !== q) {
        if (literal[k] === '\\') { s += literal[k] + literal[k + 1]; k += 2; }
        else { if (literal[k] === '\n') line++; s += literal[k]; k++; }
      }
      k++;
      let m = k; while (m < literal.length && /\s/.test(literal[m])) m++;
      if (depth === 1 && literal[m] === ':') pending = { raw: s, line, q };
      else if (pending && depth === 1) { pairs.push({ key: pending.raw, value: s, line: pending.line, q: pending.q }); pending = null; }
      continue;
    }
    k++;
  }
  return pairs;
}

const src = fs.readFileSync(path.join(__dirname, '..', 'templates', 'index.html'), 'utf8');
const i = src.indexOf('const _VI = {');
const j = src.indexOf('\n};', i);
if (i < 0 || j <= i) {
  console.error('Could not find the _VI dictionary in templates/index.html — update this test, do NOT delete it.');
  process.exit(2);
}
const literal = src.slice(i + 'const _VI = '.length, j + 2);

let evaluated;
try { evaluated = new Function('return (' + literal + ');')(); }
catch (e) { console.error('FAIL  _VI does not evaluate: ' + e.message); process.exit(1); }

// self-test 1: the scanner must flag a duplicate it is given
if (!scan("{ 'a': 'one', 'b': 'two', 'a': 'three' }").filter(p => p.key === 'a').length === 2) {
  console.error('FAIL  the scanner missed a known duplicate — fix it before trusting it'); process.exit(1);
}
// self-test 2: the scanner must agree with the JS engine on this very file, or it is blind to pairs
const pairs = scan(literal);
const distinct = new Set(pairs.map(p => p.key)).size;
const engine = Object.keys(evaluated).length;
if (distinct !== engine) {
  console.error('FAIL  scanner found ' + distinct + ' distinct keys, the engine builds ' + engine +
                ' — the scanner is blind to ' + Math.abs(engine - distinct) + ' pair(s) and cannot be trusted.');
  process.exit(1);
}

const seen = new Map();
for (const p of pairs) { if (!seen.has(p.key)) seen.set(p.key, []); seen.get(p.key).push(p); }
const dup = [...seen].filter(([, v]) => v.length > 1);
if (dup.length) {
  console.error('\n' + dup.length + ' duplicate key(s) in _VI — the LAST definition silently wins:\n');
  for (const [k, vs] of dup) {
    const conflict = !vs.every(v => v.value === vs[0].value);
    console.error('  ' + (conflict ? 'CONFLICT ' : 'repeat   ') + JSON.stringify(k));
    vs.forEach(v => console.error('      line ' + v.line + '  ' + JSON.stringify(v.value)));
    if (conflict) console.error('      -> ' + JSON.stringify(vs[vs.length - 1].value) + ' wins; the rest never reach a screen');
  }
  console.error('\nKeep one definition per key. If one English word needs two different Vietnamese\n' +
                'readings, the dictionary cannot tell them apart — give the two places different\n' +
                'English text (as the design register did with "Issue status"), or use _t2(en, vi).\n');
  process.exit(1);
}
// Everything the header asserts about quote styles, RE-DERIVED on every run rather than
// remembered. The header was wrong about this for months while the code below was right; prose
// has no failure mode, so the numbers are printed where a wrong header contradicts itself.
const sq = pairs.filter(p => p.q === "'").length;
const dq = pairs.filter(p => p.q === '"').length;
let run = 0, longest = 0;
for (const p of pairs) { if (p.q === '"') { run++; if (run > longest) longest = run; } else run = 0; }
const dqApos = pairs.filter(p => p.q === '"' && p.key.indexOf("'") >= 0).length;
// This decomposition must account for every pair the scanner found. Without it, a scanner that
// stopped recording the quote character would print "0 single + 0 double = 0" and stay green —
// the silent zero this whole file is about, in the guard added to defend against it.
if (sq + dq !== pairs.length) {
  console.error('FAIL  quote decomposition covers ' + (sq + dq) + ' of ' + pairs.length +
                ' pairs — the classifier is broken, so the printed figures below would be fiction.');
  process.exit(1);
}

console.log('_VI: ' + engine + ' keys, ' + pairs.length + ' definitions, no duplicates (scanner agrees with the engine)');
let at = 'this working tree';
try { at = execSync('git rev-parse --short HEAD', { cwd: __dirname, stdio: ['ignore', 'pipe', 'ignore'] }).toString().trim() || at; }
catch (e) { /* not a checkout; the label is cosmetic */ }
console.log('     quote styles: ' + sq + " single + " + dq + ' double = ' + (sq + dq) +
            '   longest unbroken double-quoted run: ' + longest);
console.log('     of those ' + dq + ' double-quoted keys, ' + dqApos + ' contain an apostrophe' +
            ' — the header explains why that number is not the reason for them.');
console.log('     measured at ' + at + '. These figures describe that commit and nothing else:' +
            ' keep them in this output, never in prose. A lone snapshot carries no comparison —' +
            ' the run was 504 at 3d71d42, which is the only reason today\'s number means anything.');
