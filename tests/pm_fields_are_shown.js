/* A field a form asks for must appear on some screen.
 *
 * Four PMC forms collected long free text that no renderer ever printed. Each was proved dead by
 * grepping the whole repo for the key: one hit, the field spec that WRITES it, and nothing else.
 *
 *   pm_risks.mitigationActions     every screen and PDF reported the one-word strategy ("Mitigate")
 *                                  and none of them the plan behind it
 *   pm_lessons.situation           a lesson is a pair — what happened, and what to do next time.
 *                                  Only the recommendation was printed, so a reader got advice with
 *                                  the circumstances that earned it missing
 *   pm_stakeholders.engagementStrategy   the matrix above the register counts the engagement gaps
 *                                  "to close" and the form invites the plan for closing each
 *   pm_sitereports/pm_weekreports.safetyIncidents   the one that matters: an engineer typing
 *                                  "scaffold collapse, 1 minor injury" into a field labelled Safety
 *                                  incidents believes it is on the project record
 *
 * This test asserts the READ side, because the write side was never the problem.
 *
 *   node tests/pm_fields_are_shown.js
 */
const fs = require('fs');
const path = require('path');

const src = fs.readFileSync(path.join(__dirname, '..', 'templates', 'index.html'), 'utf8');

let pass = 0, fail = 0;
const ok = (n, c, extra) => {
  if (c) { pass++; console.log('  ok    ' + n); }
  else { fail++; console.log('  FAIL  ' + n + (extra ? '\n        ' + extra : '')); }
};

/* Count occurrences OUTSIDE the field specs, i.e. reads rather than the one declaration that
   writes. The specs live in the _QA table; everything after it is renderers. Anchor on a marker
   rather than a line number, because this file moves under you. */
const SPECS_END = src.indexOf('function _pmRowEditable(');
if (SPECS_END < 0) { console.error('Could not find the end of the field specs.'); process.exit(2); }
const readers = src.slice(SPECS_END);

console.log('\nEvery field these forms collect reaches a screen\n');

const FIELDS = [
  ['mitigationActions',  'the mitigation plan behind a risk\'s one-word strategy'],
  ['situation',          'the situation half of a lesson learned'],
  ['engagementStrategy', 'a stakeholder\'s engagement strategy'],
  ['safetyIncidents',    'the safety line on a site report'],
];
FIELDS.forEach(f => {
  const hits = (readers.match(new RegExp('\\br\\.' + f[0] + '\\b', 'g')) || []).length;
  ok(f[1] + ' is rendered', hits > 0,
     'zero readers of r.' + f[0] + ' — the form writes it and no screen shows it');
});

// -- both site reports, not just the daily one ----------------------------------------------------
/* The weekly report is a separate table with its own column list, and a fix applied to one of two
   near-identical renderers is how this class of defect comes back. */
{
  const daily = src.slice(src.indexOf("_pmTable('pm_sitereports'"), src.indexOf("_pmTable('pm_weekreports'"));
  const weekly = src.slice(src.indexOf("_pmTable('pm_weekreports'"), src.indexOf("_pmTable('pm_weekreports'") + 1400);
  ok('the DAILY site report shows safety incidents', /r\.safetyIncidents/.test(daily));
  ok('and so does the WEEKLY one', /r\.safetyIncidents/.test(weekly),
     'both forms collect it; fixing one renderer leaves the other exactly as it was');
}

// -- the safety line is not styled like every other column ----------------------------------------
/* Match what is actually EMITTED. The first version of this assertion looked for a closing quote
   straight after `600`, and the code emits `600">` — so it failed on correct code. A pattern that
   convicts the fix is worse than no pattern: it teaches you to relax the test. */
ok('a non-empty safety line is marked, not left to blend in',
   (readers.match(/color:#B45309;font-weight:600">'\s*\+\s*_pmLongCell\(r\.safetyIncidents/g) || []).length === 2,
   'expected the amber wrapper on BOTH site reports — a safety line that reads like the Weather ' +
   'column is one nobody scans for');

// -- and it still does not pretend to be the accident register ------------------------------------
ok('it is not presented as the statutory accident register',
   /osh_incident\.py is/.test(src),
   'Decree 39/2016 declaration runs off the OSH module and its clock does not start from a report line');

// -- the shared cell behaves ----------------------------------------------------------------------
{
  const take = (mark, what) => {
    const i = src.indexOf(mark);
    if (i < 0) { console.error('Could not find ' + what); process.exit(2); }
    const j = src.indexOf('\nfunction ', i + 10);
    return src.slice(i, j);
  };
  const F = new Function(
    'function _tkEscA(s){return String(s).replace(/"/g,"&quot;");}\n' +
    'function _pmEsc(s){return String(s).replace(/</g,"&lt;");}\n' +
    take('function _pmLongCell(', '_pmLongCell') + '\nreturn { _pmLongCell };')();

  ok('empty text renders an em dash, not an empty cell', F._pmLongCell('').indexOf('—') >= 0);
  ok('whitespace-only counts as empty', F._pmLongCell('   \n  ').indexOf('—') >= 0);
  ok('short text is shown whole and not truncated',
     F._pmLongCell('Netting installed', 60).indexOf('Netting installed') >= 0 &&
     F._pmLongCell('Netting installed', 60).indexOf('…') < 0);
  {
    const long = 'x'.repeat(200);
    const out = F._pmLongCell(long, 50);
    ok('long text is truncated in the cell', out.indexOf('…') >= 0);
    ok('and the WHOLE of it is on hover', out.indexOf('title="' + long + '"') >= 0,
       'truncating without a tooltip loses the half of the sentence that mattered');
  }
  ok('the text is escaped', F._pmLongCell('<script>alert(1)</script>').indexOf('&lt;script') >= 0,
     'these are free-text fields typed by site staff and stored verbatim');
}

console.log('\n  ' + pass + ' passed, ' + fail + ' failed\n');
process.exit(fail ? 1 : 0);
