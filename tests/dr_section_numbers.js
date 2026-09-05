/* The form's section numbers are the REPORT's section numbers.
 *
 * The site form now labels each section with the number it becomes in the printed document — 2.1
 * for management staff, 5.1 for work completed, and so on — so a foreman filling in a column of
 * headcounts can see it is table 2.1 of the report the client reads that evening.
 *
 * That is only worth showing while it is TRUE. The numbers live in dr_site.html and the headings
 * they claim to match live in index.html's exporter (`_drpHead`), in a different file, edited by
 * different work. Nothing but this connects them, and a form that confidently mislabels a section
 * is worse than one that labels nothing: somebody would file next-day inspection under 9.1 and
 * argue about it at the site meeting.
 */
const fs = require('fs');
const path = require('path');

const site = fs.readFileSync(path.join(__dirname, '..', 'templates', 'dr_site.html'), 'utf8');
const portal = fs.readFileSync(path.join(__dirname, '..', 'templates', 'index.html'), 'utf8');

// What the exporter actually prints at the top of each block.
const printed = new Map();
for (const m of portal.matchAll(/_drpHead\('([0-9][0-9.]*)\.?\s+([^']+)'\)/g)) {
  printed.set(m[1].replace(/\.$/, ''), m[2].trim());
}

// What the form claims.
const block = site.slice(site.indexOf('var SECTIONS = ['), site.indexOf('function sectionNo('));
const claimed = [...block.matchAll(/\['([a-zA-Z]+)','([^']+)','[a-z]+','([0-9.]+)'\]/g)]
  .map(m => ({ key: m[1], label: m[2], no: m[3] }));

let bad = 0;
function fail(msg) { bad++; console.log('  MISS  ' + msg); }

if (!printed.size) { fail('found no numbered headings in the exporter at all'); }
if (claimed.length !== 14) { fail('expected 14 numbered form sections, found ' + claimed.length); }

for (const c of claimed) {
  if (!printed.has(c.no)) {
    fail(c.key + ' claims section ' + c.no + ', which the report does not print');
  } else {
    console.log('  ok    ' + c.no.padEnd(4) + c.label + '  →  ' + printed.get(c.no));
  }
}

// Every number used once. Two sections claiming 5.1 is the shape that survives review.
const seen = new Set();
for (const c of claimed) {
  if (seen.has(c.no)) fail('section number ' + c.no + ' is claimed twice');
  seen.add(c.no);
}

// 5.2 is the Gantt: DRAWN by the portal from the progress figures, never filed by the site. It must
// stay absent from the form, and it must still exist in the report — if it ever stopped being
// printed, the gap in the form's index would be unexplained rather than deliberate.
if (seen.has('5.2')) fail('the form offers 5.2, but the Gantt is drawn, not filed');
if (!printed.has('5.2')) fail('the report no longer prints 5.2, so the gap in the form is now a hole');

if (bad) { console.log('\nFAIL ' + bad); process.exit(1); }
console.log('  ok    ' + claimed.length + ' sections, numbered as the report numbers them');


/* ── the index groups, and a group is one block ──────────────────────────────────────────────────
 * The report splits three of its numbers into sub-sections (2 Manpower, 5 Work progress, 9
 * Inspection). Rendered as a flat run of fourteen rows, the multi-column grid fills row by row and
 * put "2 Manpower" at the foot of one column with 2.1 at the head of the next — a heading pointing
 * at nothing. A part and its children are therefore ONE grid item.
 */
const menu = site.slice(site.indexOf('function viewMenu()'), site.indexOf('function sectionCount('));
const menuAll = site.slice(site.indexOf('var majors = {}'), site.indexOf('html += \'</ul>'));

let n3 = 0;
function w3(cond, why) { if (!cond) { n3++; console.log('  MISS  ' + why); } else console.log('  ok    ' + why); }

w3(/blocks\.push/.test(menuAll), 'the index is built as blocks before it is drawn');
w3(/b\.rows\.length > 1/.test(menuAll), 'a block knows whether it is a group');
w3(/byMajor\[major\]/.test(menuAll), 'sub-sections are collected under their major number');

// The three parts the report actually splits, and no others invented.
const parts = /var partOf = \{([^}]*)\}/.exec(menuAll);
w3(!!parts, 'the part names are declared in one place');
if (parts) {
  const keys = [...parts[1].matchAll(/'(\d+)'\s*:/g)].map(m => m[1]).sort();
  w3(JSON.stringify(keys) === JSON.stringify(['2', '5', '9']),
     'exactly 2, 5 and 9 are named as parts — found ' + JSON.stringify(keys));
}

// Every part name has Vietnamese, or half the index is bilingual and half is not.
for (const nm of ['Manpower', 'Work progress', 'Inspection']) {
  w3(site.includes('"' + nm + '":"'), nm + ' has a Vietnamese name');
}

/* ── the language switch shows both languages ────────────────────────────────────────────────── */
w3(/id="langEn"/.test(site) && /id="langVi"/.test(site),
   'both languages are on screen, not one button naming the other');
w3(/aria-pressed/.test(site), 'the current language is marked pressed, not merely styled');
w3(/viewBox="0 0 60 30"/.test(site), 'the GB flag is drawn inline');
w3(/M0 0h640v480H0z/.test(site), 'the VN flag is drawn inline');
// Comments stripped first: the page CONTAINS 🇻🇳 inside the comment explaining why it must not be
// USED, and the first version of this check duly failed on its own rationale.
const noComments = site.replace(/\/\*[\s\S]*?\*\//g, ' ').replace(/<!--[\s\S]*?-->/g, ' ');
w3(!/🇻🇳|🇬🇧/.test(noComments),
   'no emoji flags in the markup — they degrade to bare letter pairs on Windows Chrome');
w3(/aria-hidden="true"/.test(site), 'the flags are hidden from screen readers');

if (n3) { console.log('\nFAIL ' + n3); process.exit(1); }
console.log('\nOK (index + language)');
