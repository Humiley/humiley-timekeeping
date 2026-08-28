#!/usr/bin/env node
//
// Vietnamese house-style consistency. Not "is this word right" — a native reader judges that — but
// "does the product spell and address the reader the same way throughout". With ~5800 entries
// written across many sessions, these split without anyone noticing, and a split is what makes a
// UI read as translated rather than written.
//
//   node tools/i18n/style.js
//
// Advisory. Each group below is a pair of spellings BOTH of which are correct Vietnamese; the
// defect is using both in one product, so the fix is to pick the majority and follow it.
const { load } = require('./vi.js');

// Vietnamese accent placement on <vowel-cluster>: "hoà" (old style) vs "hòa" (new style). Both are
// taught and both are correct. Mixing them inside one interface is the problem.
const ORTHO = [
  ['hoá', 'hóa'], ['hoà', 'hòa'], ['khoá', 'khóa'], ['thuỷ', 'thủy'], ['tuỳ', 'tùy'],
  ['quý', 'quí'], ['thuý', 'thúy'], ['loà', 'lòa'], ['xoá', 'xóa'], ['toà', 'tòa'],
  ['giý', 'giú'], ['huỷ', 'hủy'], ['nguỵ', 'ngụy'], ['suý', 'súy'], ['luỹ', 'lũy'],
];

// How the product addresses the reader. Mixing these is the most visible register slip.
const ADDRESS = [
  ['bạn', /\bbạn\b/gi],
  ['quý vị', /\bquý vị\b/gi],
  ['anh/chị', /\banh\/chị\b|\bAnh\/Chị\b/g],
];

const { entries } = load();
const vn = entries.filter(e => /[àáảãạăâèéêìíòóôơùúưỳýđ]/i.test(e.val));

console.log('=== orthography: both spellings in use ===');
let orthoSplit = 0;
for (const [a, b] of ORTHO) {
  const ra = new RegExp(a, 'gi'), rb = new RegExp(b, 'gi');
  const A = vn.filter(e => ra.test(e.val)), B = vn.filter(e => rb.test(e.val));
  if (!A.length || !B.length) continue;
  orthoSplit++;
  const minor = A.length <= B.length ? { w: a, list: A } : { w: b, list: B };
  const major = A.length <= B.length ? { w: b, n: B.length } : { w: a, n: A.length };
  console.log('\n  "' + a + '" x' + A.length + '   vs   "' + b + '" x' + B.length +
              '   -> majority is "' + major.w + '"');
  minor.list.slice(0, 6).forEach(e => console.log('     line ' + e.line + '  ' + JSON.stringify(e.val.slice(0, 58))));
  if (minor.list.length > 6) console.log('     ... and ' + (minor.list.length - 6) + ' more using "' + minor.w + '"');
}
if (!orthoSplit) console.log('  none — spelling is consistent');

console.log('\n=== how the reader is addressed ===');
for (const [name, re] of ADDRESS) {
  const hits = vn.filter(e => { re.lastIndex = 0; return re.test(e.val); });
  console.log('  ' + name.padEnd(10) + ' ' + hits.length + ' entries');
}

console.log('\n=== typography ===');
const dbl = vn.filter(e => /\S {2,}\S/.test(e.val));
console.log('  double spaces inside a value: ' + dbl.length);
dbl.slice(0, 5).forEach(e => console.log('     line ' + e.line + '  ' + JSON.stringify(e.val.slice(0, 56))));
const straight = vn.filter(e => /["']/.test(e.val) && !/[""'']/.test(e.val));
console.log('  straight quotes where the English uses curly: ' + straight.length);
straight.slice(0, 5).forEach(e => console.log('     line ' + e.line + '  ' + JSON.stringify(e.val.slice(0, 56))));
const spaceBefore = vn.filter(e => /\s[,.;:!?]/.test(e.val));
console.log('  space before punctuation: ' + spaceBefore.length);
spaceBefore.slice(0, 5).forEach(e => console.log('     line ' + e.line + '  ' + JSON.stringify(e.val.slice(0, 56))));

console.log('\nVietnamese entries examined: ' + vn.length);
