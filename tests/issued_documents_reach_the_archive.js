/* A decision and a confirmation letter are drawn in the BROWSER, so the browser is the only place
 * that can hand the archive the document that was actually issued.
 *
 * The server half is tested in tests/test_documents_get_a_sharepoint_home.py. This file exists for
 * the client half, which is the half that fails silently:
 *
 *   · _qdPdf and _xnPdf used to end at p.save(name) — the PDF went to the issuer's Downloads folder
 *     and nothing else ever saw it. If they stop RETURNING the bytes, _hrArchiveIssued receives
 *     undefined, returns null without a request, and every decision issues successfully while the
 *     company files nothing. No error anywhere.
 *   · a reprint re-renders from the record against TODAY's employee row. Filing a re-render instead
 *     of the issued bytes would archive a document that differs from the paper that was signed —
 *     which is the whole reason the archive exists.
 *   · _xnSubmit is shared by "Request letter" and "Issue letter". A request is not a document; if
 *     the issue check is dropped, an unissued request gets filed into the employee's HR folder.
 *
 *   node tests/issued_documents_reach_the_archive.js
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
  const i = src.indexOf('async function ' + name + '(');
  if (i < 0) {
    console.error('could not find ' + name + ' — update the marker, do NOT delete this test.');
    process.exit(2);
  }
  const ends = [src.indexOf('\nfunction ', i + 10), src.indexOf('\nasync function ', i + 10),
                src.indexOf('\n/* ', i + 10)].filter(x => x > 0);
  return src.slice(i, ends.length ? Math.min.apply(null, ends) : i + 6000);
};

// ══ 1. the printers hand back what they printed ════════════════════════════════════════════════
console.log('\nThe PDF that was issued is the PDF that is filed\n');
{
  ['_qdPdf', '_xnPdf'].forEach(fn => {
    const b = fnBody(fn);
    ok(fn + ' returns the bytes it printed',
       /return \{ name: name, data: p\.output\('datauristring'\) \};/.test(b),
       'without a return value the archive call receives undefined and quietly files nothing');
    ok(fn + ' still saves the file for the issuer',
       /if \(save\) p\.save\(name\);/.test(b),
       'the issuer must still get their copy — the archive is in addition, not instead');
  });
}

// ══ 2. the archiver ════════════════════════════════════════════════════════════════════════════
console.log('\nThe archive call itself\n');
{
  const b = fnBody('_hrArchiveIssued');
  ok('it posts to the issued-file endpoint', /'\/api\/hr\/issued-file'/.test(b));
  ok('it sends the kind, the record id and the printed bytes',
     /kind: kind, id: id, file: pdf\.data, name: pdf\.name/.test(b));
  ok('it does nothing when there are no bytes to file',
     /if \(!id \|\| !pdf \|\| !pdf\.data\) return null;/.test(b),
     'a missing return value from the printer must not become an empty upload');
  /* Filing must never be able to unmake the decision: it is issued, and every Art. 34/36/45 and
     122-127 check has already passed by the time the PDF exists. */
  ok('a failed upload cannot turn an issued decision into an error',
     /catch \(e\) \{ return null; \}/.test(b));
  ok('but it says when the document was only kept in the portal',
     /no HR SharePoint folder is set/.test(b) && /'warn'/.test(b),
     'silence here is how a company discovers a year later that nothing was ever filed');
  ok('and it does not re-announce a document that was already filed',
     /if \(r && r\.already\) return r;/.test(b));
}

// ══ 3. every issue path reaches it ═════════════════════════════════════════════════════════════
console.log('\nEvery path that issues a document files it\n');
{
  const qd = fnBody('_qdIssue');
  ok('issuing a decision files it',
     /_hrArchiveIssued\('decision', \(res\.decision \|\| \{\}\)\.id, pdf\)/.test(qd));
  ok('and it files the object _qdPdf returned, not a re-render',
     qd.indexOf('const pdf = await _qdPdf(res.document, true);') > 0 &&
     qd.indexOf('_qdPdf') < qd.indexOf('_hrArchiveIssued'),
     'a second render against today\'s employee row is a different document');

  const xs = fnBody('_xnSubmit');
  ok('issuing a letter from the draft screen files it',
     /_hrArchiveIssued\('letter'/.test(xs));
  ok('but REQUESTING one does not', /if \(issue\) await _hrArchiveIssued\('letter'/.test(xs),
     '_xnSubmit is shared by both buttons; without the guard an unissued request is filed into ' +
     'the employee\'s HR folder as though it were a document');

  const xi = fnBody('_xnIssue');
  ok('issuing a letter from the queue files it too',
     /_hrArchiveIssued\('letter'/.test(xi),
     'this is the path HR actually uses for a request somebody else raised');
}

// ══ 4. the reprint paths must NOT file ═════════════════════════════════════════════════════════
console.log('\nAnd a reprint files nothing\n');
{
  ['_qdReprint', '_xnReprint'].forEach(fn => {
    ok(fn + ' does not archive', !/_hrArchiveIssued/.test(fnBody(fn)),
       'a reprint is rebuilt from the record against TODAY\'s data — filing it would overwrite ' +
       'the archive with a document nobody signed');
  });
}

// ══ 5. the server route the client calls actually exists ═══════════════════════════════════════
console.log('\nAnd the endpoint is really wired\n');
{
  const app = fs.readFileSync(path.join(__dirname, '..', 'app.py'), 'utf8');
  ok('POST /api/hr/issued-file is routed',
     /if path == "\/api\/hr\/issued-file":\s*\n\s*return self\._guard\(lambda u: self\._hr_issued_file_ep\(u, body\), manager=True\)/.test(app),
     'a client that posts to a path with no route gets a 404 the catch above swallows');
}

console.log('\n  ' + pass + ' passed, ' + fail + ' failed\n');
process.exit(fail ? 1 : 0);
