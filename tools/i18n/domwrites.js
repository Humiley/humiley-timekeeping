#!/usr/bin/env node
//
// English written STRAIGHT into the DOM, with no translate-call on the line.
//
// Every other gate here checks strings the code ASKS to translate. These never ask:
//
//   st.innerHTML = '✓ Checked in at ' + t + '</span> — you may check out when you leave';
//
// No _t(), so tools/i18n/missing.js has nothing to look at; the key is not absent from the
// dictionary, it was never requested. This is the same shape as the General Ledger gap — a whole
// class of string sitting outside what the checks examine.
//
// The DOM walker rescues SOME of these at runtime, because it translates text nodes by exact match.
// So a line here is only a real defect when the text it writes has no dictionary entry, and the
// report separates those two cases rather than treating every hit as a bug.
//
//   node tools/i18n/domwrites.js            report
//   node tools/i18n/domwrites.js --gate     exit 1 if any UNTRANSLATED write exists
const fs = require('fs');
const path = require('path');
const { load } = require('./vi.js');

const REPO = path.resolve(__dirname, '..', '..');
const src = fs.readFileSync(path.join(REPO, 'templates', 'index.html'), 'utf8');
const VI = Object.create(null);
for (const e of load().entries) VI[e.key] = e.val;

const decode = s => s.replace(/&amp;/g, '&').replace(/&lt;/g, '<').replace(/&gt;/g, '>')
                     .replace(/&quot;/g, '"').replace(/&#39;/g, "'").replace(/&nbsp;/g, ' ');
const translated = s => VI[s] !== undefined || VI[decode(s)] !== undefined;

const SINK = /\.(innerHTML|textContent|innerText)\s*=/;
// [A-Z][A-Za-z] required the first TWO characters to be letters, so any sentence opening with
// "A " or "I " was skipped -- a hole found by injecting one and watching the gate stay green.
const PHRASE = /(['"])([A-Z](?:[A-Za-z]|\s[a-z])[^'"]{13,}?)\1/g;
const VN = /[àáảãạăằắẳẵặâầấẩẫậèéẻẽẹêềếểễệìíỉĩịòóỏõọôồốổỗộơờớởỡợùúủũụưừứửữựỳýỷỹỵđĐ]/;

const hits = [];
src.split('\n').forEach((line, i) => {
  if (!SINK.test(line)) return;
  if (/_t2?\(|_tp\(/.test(line)) return;              // the line does ask for a translation
  if (/^\s*(\/\/|\*|\/\*)/.test(line)) return;        // a comment, not code
  PHRASE.lastIndex = 0;
  let m;
  while ((m = PHRASE.exec(line))) {
    // A literal inside an HTML attribute escapes its quotes (onclick="…\'Design Projects\'…"),
    // so the capture keeps a trailing backslash and every lookup for it misses. Strip that before
    // deciding anything -- otherwise the scanner invents misses for strings that ARE translated.
    const p = m[2].replace(/\\+$/, '').trim();
    if (VN.test(p)) continue;
    if (!/\s/.test(p)) continue;                      // one token: a class, an id, a code
    if (/^[A-Z0-9_\-\s]+$/.test(p)) continue;         // SHOUTY constant
    if (/[<>{}]/.test(p)) continue;                   // a markup fragment, not a sentence
    // check the RAW literal as well as the trimmed one. A toast prefix is keyed WITH its trailing
    // space ("Reminder sweep failed: "), so looking up only the trimmed form invents a miss that
    // the missing-key gate correctly does not report.
    hits.push({ line: i + 1, text: p, ok: translated(p) || translated(m[2]) });
    break;
  }
});

const bad = hits.filter(h => !h.ok);
console.log('DOM writes carrying English with no translate-call: ' + hits.length);
console.log('  in the dictionary — the DOM walker rescues them : ' + (hits.length - bad.length));
console.log('  NOT in the dictionary — English on screen        : ' + bad.length + '\n');
bad.forEach(h => console.log('  line ' + String(h.line).padStart(6) + '  ' + JSON.stringify(h.text.slice(0, 78))));

if (process.argv.includes('--gate')) process.exit(bad.length ? 1 : 0);
