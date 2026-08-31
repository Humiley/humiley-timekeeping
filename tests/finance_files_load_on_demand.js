/* The finance registers stop shipping every bill, and the documents still reach the dossier.
 *
 * claims, travel and payments each keep the bill or the invoice INLINE on the row — and a claim keeps
 * a receipt PER LINE — so listing them sent every document to draw a table of "Show" buttons. Same
 * defect that made the project Quality tab time out at 30s.
 *
 * The server half is tested in tests/test_coll_list_has_no_file_bytes.py. THIS file exists for the
 * client half, which is the half that fails SILENTLY and the reason this change was worth being
 * careful about:
 *
 *   · _recHasBill decides whether the Show button appears, and it decided by testing the bytes that
 *     are now gone. Left alone, every record WITH a document renders no button — which reads as "the
 *     invoice is lost", not "it loads when you open it".
 *   · the paid dossier and the SharePoint archive EMBED the invoice. If they run against a stripped
 *     record they produce a voucher with the document missing AND REPORT SUCCESS. That exact failure
 *     has shipped here before: a promise that resolved with nothing loaded dropped every attached PDF
 *     from a merged dossier on mobile while the export said it worked.
 *
 *   node tests/finance_files_load_on_demand.js
 */
const fs = require('fs');
const path = require('path');

const src = fs.readFileSync(path.join(__dirname, '..', 'templates', 'index.html'), 'utf8');

let pass = 0, fail = 0;
const ok = (n, c, extra) => {
  if (c) { pass++; console.log('  ok    ' + n); }
  else { fail++; console.log('  FAIL  ' + n + (extra ? '\n        ' + extra : '')); }
};
const fnBody = (name) => {
  const i = src.indexOf('function ' + name + '(');
  if (i < 0) { console.error('could not find ' + name + ' — update the marker, do NOT delete this test.'); process.exit(2); }
  const j = src.indexOf('\nfunction ', i + 10), k = src.indexOf('\nasync function ', i + 10);
  const ends = [j, k].filter(x => x > 0);
  return src.slice(i, ends.length ? Math.min.apply(null, ends) : i + 4000);
};

// ══ 1. the Show button survives the strip ══════════════════════════════════════════════════════
console.log('\nThe button still appears when there is a document\n');
{
  const has = new Function(fnBody('_recHasBill') + '\nreturn _recHasBill;')();
  ok('a row whose bytes were stripped still offers its bill', has({ hasFile: true }) === true,
     'the list sends hasFile in place of the payload; testing only the bytes hides the button on ' +
     'every record that HAS a document');
  ok('a LINE whose bytes were stripped counts too',
     has({ items: [{ category: 'Taxi', hasFile: true }] }) === true,
     'a claim carries a receipt per line, so the marker lands on the line as well as the row');
  ok('a record with no document still offers nothing', has({ title: 'x' }) === false);
  ok('and a record that still has its bytes is unaffected', has({ attachment: 'data:...' }) === true,
     'anything loaded another way, or an older cached row, must keep working');
  ok('a SharePoint-filed record still counts', has({ spUrl: 'https://x' }) === true);
}

// ══ 2. the hydrator ════════════════════════════════════════════════════════════════════════════
console.log('\nOne record, fetched only when it is needed\n');
{
  const body = fnBody('_finEnsureFiles');
  ok('it asks for the single-row route', /\/api\/coll\/' \+ encodeURIComponent\(coll\)/.test(body),
     'body:\n' + body.slice(0, 300));
  /* Writing it back into _HR is what lets _finBillsHtml, _claimItems and _finPaidDossierDoc keep
     reading a complete record with no change of their own. */
  ok('and writes the full record back into the cache', /list\[i\] = d\.item/.test(body),
     'without this every helper downstream would need its own fetch');
  ok('it does nothing when the bytes are already there', /if \(!needs\(r\)\) return r;/.test(body),
     'opening the same record twice must not re-download it');
  ok('a failed fetch returns the record rather than throwing', /catch \(e\) \{\}\s*\n\s*return r;/.test(body),
     'the existing "no file attached" paths then report honestly, which beats a rejected promise ' +
     'in the middle of building an approval pack');
}

// ══ 3. every flow that reads the bytes hydrates first ══════════════════════════════════════════
console.log('\nEvery flow that embeds a document fetches it first\n');
{
  const show = fnBody('tkFinShow');
  ok('the detail view hydrates before reading the record',
     /await _finEnsureFiles\(coll, id\);/.test(show) &&
     show.indexOf('_finEnsureFiles') < show.indexOf('_HR[coll]'),
     'it is the single gateway for every Show button in finance, so one await here covers the ' +
     'whole display path');

  const arch = fnBody('_finSpArchiveApproved');
  ok('the SharePoint archive hydrates before uploading',
     /_finEnsureFiles\(/.test(arch),
     'it uploads the actual bill; without the bytes it would file an empty attachment');

  const paid = fnBody('_finSpArchivePaid');
  ok('and the paid dossier hydrates before it is built',
     /_finEnsureFiles\(coll, item && item\.id\)/.test(paid) &&
     paid.indexOf('_finEnsureFiles') < paid.indexOf('_finPaidDossierDoc(item)'),
     'the dossier embeds the invoice. Built from a stripped record it produces a voucher with the ' +
     'document missing AND reports success — the failure this app has already shipped once');
}

// ══ 4. the server sends the marker these guards read ═══════════════════════════════════════════
console.log('\nAnd the server sends what they read\n');
{
  const app = fs.readFileSync(path.join(__dirname, '..', 'app.py'), 'utf8');
  /* Match the STRIP CONDITION, not the tuple. `("claims", "travel", "payments")` appears five times
     in app.py — write-guards, scoping, this — so a bare search for it passes while the strip itself
     is gone. A mutation proved that: pointing the strip at a different collection left this green. */
  ok('the finance collections are stripped',
     /name in \("claims", "travel", "payments"\):\s*\n\s*items = \[self\._strip_file_bytes/.test(app),
     'the strip condition no longer names the finance collections');
  ok('line items are stripped too, not just the row',
     /out\["items"\] = \[/.test(app) && /hasFile=True/.test(app),
     'a claim keeps a receipt per line; stripping only the row leaves most of the payload behind');
  ok('and the marker is the one _recHasBill tests', /out\["hasFile"\]/.test(app));
}

console.log('\n  ' + pass + ' passed, ' + fail + ' failed\n');
process.exit(fail ? 1 : 0);
