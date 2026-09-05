/* Every string the site form shows has Vietnamese.
 *
 * The page carries its own dictionary rather than fetching the portal's, and `t()` falls back to the
 * KEY when there is no translation — so a missing entry is not an error, a blank or a crash. It is
 * one English sentence sitting in an otherwise Vietnamese screen, on a form filled in by a crew in
 * Dong Nai, reported by nobody.
 *
 * `_VI` in the portal is one shared object where a duplicate key silently wins; this dictionary has
 * the same shape and the same hazard, so duplicates are checked here too.
 */
const fs = require('fs');
const path = require('path');

const src = fs.readFileSync(path.join(__dirname, '..', 'templates', 'dr_site.html'), 'utf8');

// The dictionary, and every key in it.
const dictStart = src.indexOf('var VI = {');
const dictEnd = src.indexOf('\n};', dictStart);
if (dictStart < 0 || dictEnd < 0) { console.error('FAIL: cannot find the VI dictionary'); process.exit(1); }
const dict = src.slice(dictStart, dictEnd);

const keys = [];
for (const m of dict.matchAll(/"((?:[^"\\]|\\.)*)"\s*:/g)) keys.push(m[1].replace(/\\"/g, '"'));
const keySet = new Set(keys);

let bad = 0;
const fail = m => { bad++; console.log('  MISS  ' + m); };

// ── duplicates: the later entry wins and the earlier meaning is gone ─────────────────────────────
const seen = new Set(), dupes = new Set();
for (const k of keys) { if (seen.has(k)) dupes.add(k); seen.add(k); }
if (dupes.size) fail('duplicate keys — the later one silently wins: ' + [...dupes].join(', '));
else console.log('  ok    ' + keys.length + ' keys, none duplicated');

// ── every t('…') has an entry ────────────────────────────────────────────────────────────────────
const body = src.slice(dictEnd);
const used = new Set();
for (const m of body.matchAll(/\bt\(\s*'((?:[^'\\]|\\.)*)'\s*\)/g)) used.add(m[1].replace(/\\'/g, "'"));
for (const m of body.matchAll(/\bt\(\s*"((?:[^"\\]|\\.)*)"\s*\)/g)) used.add(m[1].replace(/\\"/g, '"'));

const missing = [...used].filter(k => !keySet.has(k));
if (missing.length) {
  fail(missing.length + ' string(s) shown with no Vietnamese:');
  missing.slice(0, 12).forEach(k => console.log('          ' + JSON.stringify(k.slice(0, 88))));
} else {
  console.log('  ok    all ' + used.size + ' translated strings have an entry');
}

// ── field labels and section names come from tables, not from t() at the call site ──────────────
const tables = [];
const fieldsBlock = src.slice(src.indexOf('var FIELDS = {'), src.indexOf('var DOC_GROUPS'));
for (const m of fieldsBlock.matchAll(/\['(\w+)','([^']+)'/g)) tables.push(m[2]);
const secBlock = src.slice(src.indexOf('var SECTIONS = ['), src.indexOf('function sectionNo('));
for (const m of secBlock.matchAll(/\['\w+','([^']+)'/g)) tables.push(m[1]);

const tblMissing = [...new Set(tables)].filter(k => !keySet.has(k));
if (tblMissing.length) {
  fail(tblMissing.length + ' field/section label(s) with no Vietnamese: ' +
       tblMissing.map(k => JSON.stringify(k)).join(', '));
} else {
  console.log('  ok    all ' + new Set(tables).size + ' field and section labels are translated');
}

// Guards the guard: the extractor must actually be finding strings.
if (used.size < 20) fail('only ' + used.size + ' t() calls found — the extractor is not working');
if (keys.length < 40) fail('only ' + keys.length + ' dictionary keys found — the parser is not working');

console.log(bad ? '\nFAIL ' + bad : '\nOK — the site form is fully bilingual');
process.exit(bad ? 1 : 0);
