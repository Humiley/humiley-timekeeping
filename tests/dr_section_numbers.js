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

console.log(bad ? '\nFAIL ' + bad : '\nOK — ' + claimed.length + ' sections, numbered as the report numbers them');
process.exit(bad ? 1 : 0);
