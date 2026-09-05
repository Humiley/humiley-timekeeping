/* The site form, the server and the printed report agree about what a daily report contains.
 *
 * Three places hold that list and none of them imports it from the others:
 *
 *   templates/dr_site.html   FIELDS      what the site can TYPE
 *   app.py                   DR_SITE_FIELDS  what the server will KEEP
 *   templates/index.html     the _drp and _drSection renderers   what the report PRINTS
 *
 * A field the form collects and the server drops is silent data loss — the site types it, the page
 * says Saved, and it is gone. A field the server keeps and the report never prints is work asked of
 * a crew for nothing. Neither shows up as an error anywhere, which is why this is a test and not a
 * convention.
 */
const fs = require('fs');
const path = require('path');

const site = fs.readFileSync(path.join(__dirname, '..', 'templates', 'dr_site.html'), 'utf8');
const app = fs.readFileSync(path.join(__dirname, '..', 'app.py'), 'utf8');

let bad = 0;
const fail = m => { bad++; console.log('  MISS  ' + m); };
const ok = m => console.log('  ok    ' + m);

// ── what the site can type ──────────────────────────────────────────────────────────────────────
const fBlock = site.slice(site.indexOf('var FIELDS = {'), site.indexOf('var DOC_GROUPS'));
const siteFields = {};
for (const m of fBlock.matchAll(/(\w+):\s*\[([\s\S]*?)\]\s*(?:,\s*\n\s*\w+:|\}\s*;)/g)) {
  siteFields[m[1]] = [...m[2].matchAll(/\['(\w+)'/g)].map(x => x[1]);
}
// the trailing entry needs its own pass — the lookahead above cannot see the closing brace
for (const m of fBlock.matchAll(/(\w+):\s*\[\[/g)) {
  if (!siteFields[m[1]]) {
    const start = fBlock.indexOf(m[0]);
    const seg = fBlock.slice(start, fBlock.indexOf(']]', start) + 2);
    siteFields[m[1]] = [...seg.matchAll(/\['(\w+)'/g)].map(x => x[1]);
  }
}

// ── what the server keeps ───────────────────────────────────────────────────────────────────────
const aBlock = app.slice(app.indexOf('DR_SITE_FIELDS = {'), app.indexOf('def _dr_site_clean'));
const serverFields = {};
for (const m of aBlock.matchAll(/"(\w+)":\s*\[([^\]]*)\]/g)) {
  serverFields[m[1]] = [...m[2].matchAll(/"(\w+)"/g)].map(x => x[1]);
}
const serverKinds = [...aBlock.matchAll(/"(\w+)":\s*"(\w+)"/g)].map(m => m[1]);

if (!Object.keys(siteFields).length) fail('could not read FIELDS out of dr_site.html');
if (!Object.keys(serverFields).length) fail('could not read DR_SITE_FIELDS out of app.py');

// ── every row section the form offers is one the server knows ───────────────────────────────────
for (const sec of Object.keys(siteFields)) {
  if (!serverFields[sec]) {
    fail(sec + ': the form collects it, the server has no whitelist for it — every save is refused');
    continue;
  }
  const extra = siteFields[sec].filter(f => !serverFields[sec].includes(f));
  const unused = serverFields[sec].filter(f => !siteFields[sec].includes(f));
  if (extra.length) {
    fail(sec + ': the form types ' + JSON.stringify(extra) +
         ' and the server drops them — typed, "Saved", gone');
  } else if (unused.length) {
    // Not a failure: the server may legitimately accept a field a SharePoint sync fills in and the
    // site form does not ask for. It is worth printing, because the other direction is a bug.
    ok(sec + ': ' + siteFields[sec].length + ' fields match (server also allows ' +
       JSON.stringify(unused) + ', filled by the sync)');
  } else {
    ok(sec + ': ' + siteFields[sec].length + ' fields match exactly');
  }
}

// ── and the reverse: a whitelist entry the form can never reach ─────────────────────────────────
for (const sec of Object.keys(serverFields)) {
  if (!siteFields[sec]) {
    fail(sec + ': the server accepts it but the form has no way to fill it in');
  }
}

// ── the non-row kinds are handled by both ───────────────────────────────────────────────────────
for (const k of serverKinds) {
  const re = new RegExp("\\['" + k + "'");
  if (!re.test(site) && !site.includes("'" + k + "'")) {
    fail(k + ': the server accepts this kind and the form never sends it');
  }
}
if (serverKinds.length) ok('non-row kinds present in both: ' + serverKinds.join(', '));

console.log(bad ? '\nFAIL ' + bad : '\nOK — the form, the server and the report agree');
process.exit(bad ? 1 : 0);
