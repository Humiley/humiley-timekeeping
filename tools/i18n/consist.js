// One English term, two Vietnamese words. This is the defect a native reader notices fastest
// after spelling: the same button called "Duyệt" on one screen and "Phê duyệt" on the next reads
// as two different products. Detectable mechanically, unlike tone.
//
// Compares SHORT keys only (<= 4 words). Long sentences legitimately vary; a label must not.
//
// ADVISORY, and most of what it prints is fine. The same English word often means two different
// things here -- "Hold" is a pause on one screen and an ITP hold point on another, "check-in" is
// the attendance verb in one place and a time column in another -- and those SHOULD differ. Read
// each hit in its own context before changing anything; do not sweep this list.
const { load } = require('./vi.js');
const { entries } = load();

const norm = s => s.toLowerCase().replace(/[: ]/g, ' ').replace(/\s+/g, ' ').trim()
                    .replace(/\(s\)$/, '').replace(/[.…]+$/, '').trim();

const byEn = new Map();
for (const e of entries) {
  const k = norm(e.key);
  if (!k || k.split(' ').length > 4) continue;
  if (!byEn.has(k)) byEn.set(k, new Map());
  const m = byEn.get(k);
  const v = e.val.trim();
  if (!m.has(v)) m.set(v, []);
  m.get(v).push(e.line);
}
const rows = [];
for (const [en, m] of byEn) {
  if (m.size < 2) continue;
  // ignore pairs that differ only by case or trailing punctuation
  const shapes = new Set([...m.keys()].map(v => v.toLowerCase().replace(/[.:…]+$/, '').trim()));
  if (shapes.size < 2) continue;
  rows.push({ en, variants: [...m.entries()].map(([v, ls]) => ({ v, n: ls.length, line: ls[0] })) });
}
rows.sort((a, b) => b.variants.length - a.variants.length || a.en.localeCompare(b.en));
console.log('English terms with more than one Vietnamese rendering: ' + rows.length + '\n');
for (const r of rows.slice(0, 60)) {
  console.log('  "' + r.en + '"');
  r.variants.forEach(x => console.log('       ' + JSON.stringify(x.v).padEnd(34) + ' x' + x.n + '  (line ' + x.line + ')'));
}
if (rows.length > 60) console.log('\n  ... and ' + (rows.length - 60) + ' more');
