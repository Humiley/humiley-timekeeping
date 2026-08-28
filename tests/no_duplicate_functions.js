/* index.html is ONE global scope, and a second `function foo` silently replaces the first.
 *
 * It shipped. `_engGateReadiness` was declared twice — once taking a stage ROW and returning
 * { done, total, pct, list, ticked }, once taking a project ID and returning a seven-element array
 * of exit checks. The second won for the whole file, so _engStageCard, engGateOpen and the Gate
 * Certificate PDF — all three of which call the row form — got the array. `rd.list.map(...)` threw
 * TypeError and left the Stages & Gates tab blank; the certificate printed "undefined of undefined".
 *
 * Nothing else could have caught it. Every test passed, the file parsed, and a thrown render is
 * simply an empty panel. The only visible symptom is a screen that does nothing.
 *
 *   node tests/no_duplicate_functions.js
 */
const fs = require('fs');
const path = require('path');

const FILES = ['templates/index.html'];
let pass = 0, fail = 0;
const ok = (n, c, extra) => {
  if (c) { pass++; console.log('  ok    ' + n); }
  else { fail++; console.log('  FAIL  ' + n + (extra ? '\n        ' + extra : '')); }
};

console.log('\nOne name, one function\n');

/* Only TOP-LEVEL declarations collide. A `function` nested inside another is scoped to it, so the
 * regex is anchored to column 0 — which is also how every top-level definition in this file is
 * written. Anchoring is the whole measurement: without it this counts inner helpers and reports
 * collisions that do not exist, and a test that cries wolf gets deleted. */
const DECL = /^(?:async\s+)?function\s+([A-Za-z_$][\w$]*)\s*\(/gm;

FILES.forEach(rel => {
  const src = fs.readFileSync(path.join(__dirname, '..', rel), 'utf8');
  const seen = new Map();
  let m;
  DECL.lastIndex = 0;
  while ((m = DECL.exec(src)) !== null) {
    const line = src.slice(0, m.index).split('\n').length;
    if (!seen.has(m[1])) seen.set(m[1], []);
    seen.get(m[1]).push(line);
  }
  const total = [...seen.values()].reduce((a, b) => a + b.length, 0);

  // The count is stated out loud. A regex that silently stopped matching would otherwise report
  // "no duplicates" while examining nothing — the exact failure this suite exists to prevent.
  ok(rel + ': found top-level function declarations to check', total > 500,
     'only ' + total + ' matched — the regex is not seeing the file, so a clean result means nothing');

  const dupes = [...seen.entries()].filter(e => e[1].length > 1);
  ok(rel + ': every top-level function name is unique',
     dupes.length === 0,
     dupes.map(d => d[0] + ' declared at lines ' + d[1].join(', ') +
       ' — the LAST one wins and every caller of the others silently gets the wrong shape').join('\n        '));
});

/* And the specific pair, by name, so a future edit that reintroduces exactly this one is named
 * rather than buried in a list. */
{
  const src = fs.readFileSync(path.join(__dirname, '..', 'templates', 'index.html'), 'utf8');
  const rowForm = (src.match(/^function _engGateReadiness\s*\(/gm) || []).length;
  ok('_engGateReadiness is declared exactly once', rowForm === 1,
     'found ' + rowForm + ' declarations');
  ok('and the project-wide exit checks have their own name',
     /^function _engGateExitChecks\s*\(/m.test(src));
  ok('its only caller was moved with it',
     /const rows = _engGateExitChecks\(pid\);/.test(src) &&
     !/_engGateReadinessPanel[\s\S]{0,120}_engGateReadiness\(pid\)/.test(src));
  // The three callers that were broken must still be asking for the ROW form. `(?<!function )` is
  // load-bearing: without it the DECLARATION `function _engGateReadiness(row)` counts as a fourth
  // caller, and the number the assertion is about stops being the number of call sites.
  const callers = (src.match(/(?<!function )_engGateReadiness\((?:row|r\.stage)/g) || []).length;
  ok('the three stage-row callers still call the stage-row function', callers === 3,
     'found ' + callers + ' — expected _engStageCard, engGateOpen and the Gate Certificate PDF');
}

console.log('\n  ' + pass + ' passed, ' + fail + ' failed\n');
process.exit(fail ? 1 : 0);
