#!/usr/bin/env node
//
// `_t2(en, vn)` is the second translation surface, and until now nothing checked it.
//
// Every other tool in here reads the `_VI` dictionary. But a call site can also carry its own pair
// inline — `_t2('No AOP set for this year yet…', 'Chưa có AOP…')` — and those strings are in no
// dictionary at all. Two consequences:
//
//   * a "is this English string translated?" probe that only consults _VI reports these as MISSING
//     when they are fine. That false alarm is how this file came to exist.
//   * nothing was comparing the two surfaces, so the same English could say one thing through _VI
//     and something else through _t2, and no checker would notice.
//
//   node tools/i18n/t2.js
const fs = require('fs');
const path = require('path');
const { load } = require('./vi.js');

const src = fs.readFileSync(path.join(__dirname, '..', '..', 'templates', 'index.html'), 'utf8');
const { entries } = load();
const VI = new Map(entries.map(e => [e.key, e.val]));

// _t2('...', '...') / _t2("...", "...") — quote styles may differ between the two arguments, and an
// argument may contain escaped quotes of its own.
const CALL = /_t2\(\s*(['"])((?:\\.|(?!\1)[^\\])*)\1\s*,\s*(['"])((?:\\.|(?!\3)[^\\])*)\3\s*\)/g;
const unesc = s => s.replace(/\\(['"\\])/g, '$1').replace(/\\u([0-9a-fA-F]{4})/g,
  (_, h) => String.fromCharCode(parseInt(h, 16)));

const pairs = [];
let m;
while ((m = CALL.exec(src))) {
  pairs.push({ line: src.slice(0, m.index).split('\n').length, en: unesc(m[2]), vn: unesc(m[4]) });
}
console.log('_t2 call sites parsed: ' + pairs.length + '\n');

let problems = 0;
const report = (title, rows, fmt) => {
  console.log('=== ' + title + ' ===');
  if (!rows.length) { console.log('  none\n'); return; }
  problems += rows.length;
  rows.forEach(r => console.log('  line ' + String(r.line).padStart(5) + '  ' + fmt(r)));
  console.log('');
};

// 1. the Vietnamese argument is empty, or is just the English again
report('_t2 whose Vietnamese is missing or identical to the English',
  pairs.filter(p => !p.vn.trim() || p.vn === p.en),
  r => JSON.stringify(r.en.slice(0, 60)));

// 2. the same English rendered differently by two _t2 call sites
const byEn = new Map();
for (const p of pairs) {
  if (!byEn.has(p.en)) byEn.set(p.en, new Map());
  const g = byEn.get(p.en);
  if (!g.has(p.vn)) g.set(p.vn, []);
  g.get(p.vn).push(p.line);
}
const split = [...byEn].filter(([, g]) => g.size > 1);
console.log('=== the same English rendered two ways by two _t2 call sites ===');
if (!split.length) console.log('  none\n');
else {
  problems += split.length;
  for (const [en, g] of split) {
    console.log('  ' + JSON.stringify(en.slice(0, 62)));
    for (const [vn, lines] of g) console.log('       ' + JSON.stringify(vn.slice(0, 50)) + '  lines ' + lines.join(', '));
  }
  console.log('');
}

// 3. THE ONE THAT MATTERS: _t2 and _VI disagree about the same English
const disagree = pairs.filter(p => VI.has(p.en) && VI.get(p.en) !== p.vn);
report('_t2 and the _VI dictionary disagree about the same English', disagree,
  r => JSON.stringify(r.en.slice(0, 52)) + '\n           _t2: ' + JSON.stringify(r.vn.slice(0, 46)) +
       '\n           _VI: ' + JSON.stringify(VI.get(r.en).slice(0, 46)));

console.log('_t2 pairs: ' + pairs.length + '   problems: ' + problems);
process.exit(problems ? 1 : 0);
