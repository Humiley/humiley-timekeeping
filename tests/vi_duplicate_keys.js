/* One key, one meaning: the Vietnamese dictionary must not define a key twice.
 *
 * `_VI` is a plain object literal, so a key defined twice keeps the LAST value and drops the first —
 * silently, at parse time, with no warning anywhere. Thirty-three redundant definitions had
 * accumulated across 32 keys; seven of them disagreed, so one screen's wording was quietly
 * overwriting another's ('Retention' meant both a records retention period and retention money).
 *
 * WHY THIS FILE DOES NOT USE A REGEX. The check that was supposed to catch this used
 * /'key'\s*:\s*'value'/ and saw 3,246 pairs where the engine builds 3,764 — blind to 516 of them,
 * because values contain apostrophes and quotes and nested braces that a flat pattern cannot track.
 * It reported "0 duplicates" for months. So this scans character by character, honouring JS string
 * rules, and then CHECKS ITSELF against the engine: if the number of distinct keys it finds does not
 * equal Object.keys() of the same literal evaluated, the scanner is wrong and says so rather than
 * reporting a clean bill.
 *
 *   node tests/vi_duplicate_keys.js
 */
const fs = require('fs');
const path = require('path');

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
      if (depth === 1 && literal[m] === ':') pending = { raw: s, line };
      else if (pending && depth === 1) { pairs.push({ key: pending.raw, value: s, line: pending.line }); pending = null; }
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
console.log('_VI: ' + engine + ' keys, ' + pairs.length + ' definitions, no duplicates (scanner agrees with the engine)');
