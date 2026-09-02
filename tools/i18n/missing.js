#!/usr/bin/env node
//
// Which strings does the code ASK to translate, and then not find?
//
// This exists because every other Vietnamese check walks the rendered DOM, and a DOM sweep only
// ever sees the screens it happens to open. A string on a view nobody visited — or an error state
// nobody triggered — is invisible to it. That is not a hypothetical: the entire General Ledger
// module rendered in English while the duplicate-key gate and both orthography gates stayed green,
// because a MISSING key is not a MALFORMED one and nothing was looking for it. 45 strings, one of
// the most consequential screens in the product, found only by asking the question this way round.
//
// `_t('X')` returns X unchanged when X is not a key, so a call whose argument has no entry is a
// GUARANTEED English render — provable from the source, without navigating anywhere.
//
//   node tools/i18n/missing.js
//
// Two categories, because they are different defects and only one is fixable by translating:
//
//   MISSING KEY   a self-contained literal with no dictionary entry. Add the translation. The gate
//                 FAILS on any of these that is not explicitly allowed below.
//
//   CONCATENATED  toast('Checked in at ' + time) hands _t() a string built at runtime, which can
//                 never match a key no matter what the dictionary contains. Adding a key does not
//                 fix it; the message has to be restructured so the English part is translated on
//                 its own. Held at a baseline count so the backlog cannot quietly grow.
const fs = require('fs');
const path = require('path');
const { load } = require('./vi.js');

const REPO = path.resolve(__dirname, '..', '..');
const src = fs.readFileSync(path.join(REPO, 'templates', 'index.html'), 'utf8');

const VI = Object.create(null);
for (const e of load().entries) VI[e.key] = e.val;

const unesc = s => s.replace(/\\u([0-9a-fA-F]{4})/g, (_, h) => String.fromCharCode(parseInt(h, 16)))
                    .replace(/\\n/g, '\n').replace(/\\(['"\\])/g, '$1');

// A literal written with an HTML entity has two lives. `toast('… by L&amp;D.')` inside an onclick
// attribute is DECODED by the browser before the JS runs, so _t() actually receives the "L&D."
// form. Checking both spellings removes that false positive structurally, rather than by putting
// a real-looking string on an allowlist and hoping the next reader understands why.
const decodeEntities = s => s.replace(/&amp;/g, '&').replace(/&lt;/g, '<').replace(/&gt;/g, '>')
                             .replace(/&quot;/g, '"').replace(/&#39;/g, "'").replace(/&nbsp;/g, ' ');

const translated = raw => VI[raw] !== undefined || VI[decodeEntities(raw)] !== undefined;

// Strings that are correct to leave in English, each with the reason. A bare list rots: anything
// here that LATER gains a translation is reported as stale and fails the gate, so the exemptions
// cannot outlive their justification.
const ALLOWED = new Map([
  ['PDF', 'the same word in Vietnamese'],
  ['was', 'a mid-sentence fragment; the surrounding sentence is assembled at the call site'],
  ['month', 'a mid-sentence fragment in a composed tender label'],
  ['margin', 'a mid-sentence fragment in a composed tender label'],
]);

// Was 15. All fifteen have been restructured onto _tp(), so the correct floor is now ZERO: any new
// concatenated message is a regression, not a backlog item. Raising this number again should take
// an argument, not a commit.
const CONCAT_BASELINE = 0;

const CALLS = [
  ['_t', /(?<![\w$])_t\(\s*(['"])((?:\\.|(?!\1)[^\\])*)\1\s*(\)|\+)/g],
  // _tp(template, ...values) is the fix for a message that carries a value: the whole sentence is
  // the key and the TRANSLATION places {0}/{1}. Its first argument is looked up exactly like _t's,
  // so it is scanned the same way -- and it must be, or moving a message onto _tp would hide it
  // from this gate rather than fix it.
  ['_tp', /(?<![\w$])_tp\(\s*(['"])((?:\\.|(?!\1)[^\\])*)\1\s*(,|\)|\+)/g],
  ['toast', /(?<![\w$])toast\(\s*(['"])((?:\\.|(?!\1)[^\\])*)\1\s*(,|\)|\+)/g],
];

const VN = /[àáảãạăằắẳẵặâầấẩẫậèéẻẽẹêềếểễệìíỉĩịòóỏõọôồốổỗộơờớởỡợùúủũụưừứửữựỳýỷỹỵđĐ]/;
const missing = new Map();
const concat = new Map();
let scanned = 0;

for (const [fn, re] of CALLS) {
  re.lastIndex = 0;
  let m;
  while ((m = re.exec(src))) {
    const raw = unesc(m[2]);
    const follow = m[3];
    scanned++;
    if (!raw.trim()) continue;
    if (VN.test(raw)) continue;                 // already Vietnamese at the call site
    if (raw.startsWith('<')) continue;          // a markup blob, not a phrase
    if (!/[A-Za-z]{3}/.test(raw)) continue;     // codes, numbers, punctuation
    if (translated(raw)) continue;
    const line = src.slice(0, m.index).split('\n').length;
    const bucket = follow === '+' ? concat : missing;
    if (!bucket.has(raw)) bucket.set(raw, { fn, lines: [] });
    bucket.get(raw).lines.push(line);
  }
}

// exemptions that have since been translated are stale and must be removed
const stale = [...ALLOWED.keys()].filter(k => translated(k));
const blocking = [...missing].filter(([t]) => !ALLOWED.has(t));

console.log('translate-calls scanned: ' + scanned);
console.log('  self-contained literals with no entry : ' + missing.size +
            '  (' + (missing.size - blocking.length) + ' allowed)');
console.log('  concatenated, untranslatable as written: ' + concat.size +
            '  (baseline ' + CONCAT_BASELINE + ')');

if (blocking.length) {
  console.log('\n=== MISSING TRANSLATION — these render English in Vietnamese mode ===');
  for (const [text, info] of blocking.sort((a, b) => b[1].lines.length - a[1].lines.length)) {
    console.log('  ' + info.fn.padEnd(6) + ' line ' + String(info.lines[0]).padStart(6) + '  ' +
                JSON.stringify(text.slice(0, 90)));
  }
  console.log('\n  Add each to static/i18n/vi.js, or — if it is genuinely correct in English —');
  console.log('  add it to ALLOWED in this file WITH the reason.');
}

if (stale.length) {
  console.log('\n=== STALE EXEMPTION — allowed here, but now translated ===');
  stale.forEach(k => console.log('  ' + JSON.stringify(k) + '  — remove it from ALLOWED'));
}

let grew = [];
if (concat.size > CONCAT_BASELINE) {
  grew = [...concat].sort((a, b) => a[1].lines[0] - b[1].lines[0]);
  console.log('\n=== CONCATENATED BACKLOG GREW (' + concat.size + ' > ' + CONCAT_BASELINE + ') ===');
  console.log('  A literal joined to data with + can never match a dictionary key. Write it as');
  console.log("  toast(_t('Checked in at ') + time) when the literal is the WHOLE English part;");
  console.log('  restructure the message when English continues between the data.');
  grew.forEach(([t, i]) => console.log('  ' + i.fn.padEnd(6) + ' line ' + String(i.lines[0]).padStart(6) +
                                       '  ' + JSON.stringify(t.slice(0, 74))));
}

const fail = blocking.length || stale.length || concat.size > CONCAT_BASELINE;
console.log(fail ? '\nFAIL' : '\nok — every translate-call resolves, or is accounted for');
process.exit(fail ? 1 : 0);
