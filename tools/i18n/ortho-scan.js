// My ORTHO list was hand-written, so it could only find spellings I had thought of. "khoẻ" was not
// on it, and "Sức khoẻ danh mục dự án" survived the whole pass.
//
// This derives the rule instead of listing words.
//
//   old style: mark on the SECOND vowel  -> hoá, khoá, xoá, thuỷ, luỹ, hoà, toà, khoẻ
//   new style: mark on the FIRST  vowel  -> hóa, khóa, xóa, thủy, lũy, hòa, tòa, khỏe
//
// So an old-style OPEN syllable is a plain o/u glide followed by an accented a/e/y that ends the
// syllable. Two conditions matter and both are easy to get wrong:
//
//  * the o/u must be a GLIDE, so a consonant has to precede it. In "của" the u is the nucleus of a
//    ua diphthong, not a glide, and "của" is spelled that way in both conventions.
//  * the syllable must be OPEN. "hoàn"/"toàn"/"khoán" carry the mark on the second vowel in BOTH
//    conventions, and rewriting them is how the first attempt at this broke 156 words.
const { load } = require('./vi.js');
const { entries } = load();

const ACC = 'àáảãạèéẻẽẹỳýỷỹỵÀÁẢÃẠÈÉẺẼẸỲÝỶỸỴ';
// "qu" is a single onset digraph -- the u there is part of the consonant, not a glide, so "quá"
// is spelled that way in both conventions. A word-initial glide ("uỷ nhiệm chi") has no consonant
// in front of it at all, so the preceding character may also be a boundary.
// The nucleus case needs no special handling: in "của" the mark already sits on the u, and this
// looks for a PLAIN o/u followed by an ACCENTED a/e/y, so "của" cannot match. Only "qu" has to be
// excluded by hand, and the lookbehind has to sit against the glide itself -- putting it in front
// of an alternation that can consume the q tests the wrong character and lets every "quá" through.
const OLD = new RegExp('(?<![qQ])[ouOU][' + ACC + '](?![a-zà-ỹA-ZÀ-Ỹ])', 'gu');

// The dictionary is only ONE of the two translation surfaces. A call site can also carry its own
// pair inline -- _t2('Cancel', 'Huỷ') -- and those strings are in no dictionary, so a gate that
// reads _VI alone passes a file that still contains the old spelling. That is exactly what
// happened: this scan reported the portal clean while _t2('Cancel', 'Hu\u1ef7') sat in it.
//
// Note the escape. The source writes some Vietnamese as \uXXXX, so a scanner that does not decode
// those sees pure ASCII and finds nothing -- silence for the wrong reason.
const fs2 = require('fs');
const path2 = require('path');
const SRC = fs2.readFileSync(path2.join(__dirname, '..', '..', 'templates', 'index.html'), 'utf8');
const CALL = /_t2\(\s*(['"])((?:\\.|(?!\1)[^\\])*)\1\s*,\s*(['"])((?:\\.|(?!\3)[^\\])*)\3\s*\)/g;
const unesc2 = s => s.replace(/\\u([0-9a-fA-F]{4})/g, (_, h) => String.fromCharCode(parseInt(h, 16)))
                     .replace(/\\(['"\\])/g, '$1');
const inline = [];
let cm;
while ((cm = CALL.exec(SRC))) {
  inline.push({ line: SRC.slice(0, cm.index).split('\n').length, key: unesc2(cm[2]), val: unesc2(cm[4]) });
}
console.log('surfaces: _VI dictionary (' + entries.length + ' entries) + _t2 inline pairs (' + inline.length + ')\n');

const hits = new Map();
for (const e of entries.concat(inline)) {
  let m;
  OLD.lastIndex = 0;
  while ((m = OLD.exec(e.val))) {
    const start = e.val.slice(0, m.index).match(/[a-zà-ỹA-ZÀ-Ỹ]*$/)[0];
    const word = start + m[0].replace(/^[^a-zà-ỹA-ZÀ-Ỹ]*/, '');
    if (!hits.has(word)) hits.set(word, []);
    hits.get(word).push({ line: e.line, key: e.key, val: e.val.slice(0, 52) });
    OLD.lastIndex = m.index + 1;   // allow overlap
  }
}
const rows = [...hits].sort((a, b) => b[1].length - a[1].length);
console.log('old-style OPEN syllables still present: ' + rows.length + ' distinct\n');
for (const [w, list] of rows) {
  list.forEach(h => console.log('  ' + w.padEnd(10) + ' line ' + h.line + '  ' + JSON.stringify(h.val)));
}
if (!rows.length) console.log('  none');

// A gate has to FAIL, not just report. Without this the scan printed the regression it had just
// found and exited 0, which is indistinguishable from a clean run to CI.
process.exit(rows.length ? 1 : 0);
