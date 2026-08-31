#!/usr/bin/env node
//
// Translation defects that BREAK something, as opposed to reading oddly.
//
// The other checkers in here judge wording. These judge structure: a Vietnamese value has to carry
// the same machinery its English key does. If the English has a {0} and the Vietnamese does not,
// the number never appears. If the English has an <b> and the Vietnamese closes a tag it never
// opened, the markup escapes into the rest of the row. None of that is visible to a reader of the
// dictionary, and none of it is caught by "is this the right word".
//
//   node tools/i18n/integrity.js
//
// Exits non-zero if any check fires, so it can be a CI gate.
const { load } = require('./vi.js');
const { entries } = load();

let failures = 0;
const report = (title, rows, fmt) => {
  console.log('\n=== ' + title + ' ===');
  if (!rows.length) { console.log('  none'); return; }
  failures += rows.length;
  rows.forEach(r => console.log('  line ' + String(r.line).padStart(5) + '  ' + fmt(r)));
};

// ---------------------------------------------------------------- placeholders
// Every interpolation form the file actually uses. A value that drops one renders a sentence with
// a hole in it; a value that invents one prints the literal braces at the user.
const PH = /\{\d+\}|\{\{[^}]+\}\}|%[sd]|\$\{[^}]+\}/g;
const phSet = s => (s.match(PH) || []).slice().sort().join(',');
const phBad = entries.filter(e => phSet(e.key) !== phSet(e.val));
report('placeholders differ between English and Vietnamese', phBad,
  r => JSON.stringify(r.key.slice(0, 40)) + '  [' + (phSet(r.key) || '-') + ']  ->  ' +
       JSON.stringify(r.val.slice(0, 40)) + '  [' + (phSet(r.val) || '-') + ']');

// ---------------------------------------------------------------- markup
// Tag NAMES and their count, not the whole string: word order legitimately moves a <b> around, but
// an opened tag that is never closed is a defect in any order.
const tags = s => {
  const t = (s.match(/<\/?[a-zA-Z][a-zA-Z0-9]*/g) || []).map(x => x.toLowerCase());
  return t.slice().sort().join(',');
};
const tagBad = entries.filter(e => tags(e.key) !== tags(e.val));
report('HTML tags differ between English and Vietnamese', tagBad,
  r => JSON.stringify(r.key.slice(0, 40)) + '  [' + (tags(r.key) || '-') + ']  ->  [' + (tags(r.val) || '-') + ']');

// ---------------------------------------------------------------- entities
const ents = s => (s.match(/&[a-zA-Z]+;|&#\d+;/g) || []).slice().sort().join(',');
const entBad = entries.filter(e => ents(e.key) !== ents(e.val));
report('HTML entities differ between English and Vietnamese', entBad,
  r => JSON.stringify(r.key.slice(0, 40)) + '  [' + (ents(r.key) || '-') + ']  ->  [' + (ents(r.val) || '-') + ']');

// ---------------------------------------------------------------- untranslated
// Present in the dictionary but identical to the English. The DOM walker treats a key as handled
// once it is in _VI, so these are invisible to the "still English on screen" sweep -- they look
// translated to every tool and are English to every reader.
//
// Excluded: values that carry no letters at all (numbers, punctuation, symbols) and single tokens
// that are the same word in both languages by nature -- acronyms, units, product names.
const SAME_BY_NATURE = /^([A-Z0-9&./+-]{1,8}|PDF|CSV|XML|JSON|API|URL|ID|OK|VAT|GPS|PIN|KPI|OKR|SLA|BIM|ISO|EN|TCVN|QCVN|kg|mm|cm|m|m²|m³|kW|Pa|°C|%|Email|Fax|Zalo|Excel|Word|Teams|SharePoint|Outlook|Microsoft|Humiley)$/;
const untranslated = entries.filter(e =>
  e.key === e.val && /[a-zA-Z]{2}/.test(e.val) && !SAME_BY_NATURE.test(e.val.trim()));
report('in the dictionary but still English (key === value)', untranslated,
  r => JSON.stringify(r.val.slice(0, 60)));

// ---------------------------------------------------------------- whitespace
// A leading or trailing space that the English does not have shifts the text away from its icon or
// its colon. A doubled internal space is just sloppy.
const wsBad = entries.filter(e => {
  const kLead = /^\s/.test(e.key), vLead = /^\s/.test(e.val);
  const kTrail = /\s$/.test(e.key), vTrail = /\s$/.test(e.val);
  return kLead !== vLead || kTrail !== vTrail || /\S {2,}\S/.test(e.val);
});
report('leading/trailing/double whitespace differs', wsBad,
  r => JSON.stringify(r.key.slice(0, 34)) + '  ->  ' + JSON.stringify(r.val.slice(0, 34)));

// ---------------------------------------------------------------- trailing colon
// A label rendered next to a value needs its colon. Losing it is invisible in the dictionary and
// obvious on screen.
const colonBad = entries.filter(e => /:\s*$/.test(e.key) !== /:\s*$/.test(e.val));
report('trailing colon present on one side only', colonBad,
  r => JSON.stringify(r.key.slice(0, 40)) + '  ->  ' + JSON.stringify(r.val.slice(0, 40)));

console.log('\nentries examined: ' + entries.length + '   problems: ' + failures);
process.exit(failures ? 1 : 0);
