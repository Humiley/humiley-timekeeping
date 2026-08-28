# Vendored third-party libraries

Everything in this directory is served from our own origin instead of a CDN.

Not for speed. A script loaded from a third party executes with **full page privileges** — it can
read the DOM, the session, and anything a signed-in person can see. This portal holds payroll,
e-signatures, labour contracts and HR records, so "whatever that host returns today" is not an
acceptable input. Self-hosting also removes an availability dependency: an export no longer fails
because someone's network blocks a CDN.

The tags and the lazy loader in `templates/index.html` keep an `integrity` hash on each file. Being
same-origin they need no `crossorigin` attribute. The hash is cheap and still catches a corrupted or
wrongly-swapped file in our own tree.

## What is here

| File | Library | Version | Licence |
|---|---|---|---|
| `jspdf.umd.min.js` | jsPDF | 2.5.1 | MIT |
| `html2canvas.min.js` | html2canvas | 1.4.1 | MIT |
| `xlsx.full.min.js` | SheetJS (xlsx) | 0.18.5 | Apache-2.0 |
| `pdf.min.js` | PDF.js | 3.11.174 | Apache-2.0 |
| `pdf.worker.min.js` | PDF.js worker | 3.11.174 | Apache-2.0 |
| `chart.umd.min.js` | Chart.js | see tag in index.html | MIT |
| `msal-browser.min.js` | MSAL Browser | see tag in index.html | MIT |
| `tk-font-brand.js` | Carlito subset for PDFs | — | OFL, see `tk-font-brand.OFL.txt` |

## SRI hashes (sha384, as used in `index.html`)

```
jspdf.umd.min.js    sha384-JcnsjUPPylna1s1fvi1u12X5qjY5OL56iySh75FdtrwhO/SWXgMjoVqcKyIIWOLk
html2canvas.min.js  sha384-ZZ1pncU3bQe8y31yfZdMFdSpttDoPmOZg2wguVK9almUodir1PghgT0eY7Mrty8H
xlsx.full.min.js    sha384-vtjasyidUo0kW94K5MXDXntzOJpQgBKXmE7e2Ga4LG0skTTLeBi97eFAXsqewJjw
pdf.min.js          sha384-/1qUCSGwTur9vjf/z9lmu/eCUYbpOTgSjmpbMQZ1/CtX2v/WcAIKqRv+U1DUCG6e
pdf.worker.min.js   sha384-SnzOobpRMLXZ52iJvZm/C0fYw0OQemTXzTjIsdsfMcrCtCEe9qgzxTd3RSklO5x2
```

## Verifying a file already here

```bash
openssl dgst -sha384 -binary static/vendor/xlsx.full.min.js | openssl base64 -A
```

## Upgrading, or adding another

Fetch it, then **check it against a source that is not the download itself** before committing.
A hash computed from a file you just downloaded only proves you hashed what you received; if the
response was altered, the hash certifies the alteration. cdnjs publishes an SRI value per file:

```bash
LIB=xlsx VER=0.18.5 FILE=xlsx.full.min.js
curl -sS -o "/tmp/$FILE" "https://cdnjs.cloudflare.com/ajax/libs/$LIB/$VER/$FILE"
echo "mine : sha512-$(openssl dgst -sha512 -binary "/tmp/$FILE" | openssl base64 -A)"
curl -sS "https://api.cdnjs.com/libraries/$LIB/$VER?fields=sri" | python3 -m json.tool
```

Compare **sha512 to sha512** — cdnjs publishes sha512 and `index.html` uses sha384, and comparing
one to the other reports a mismatch on files that are perfectly fine. Only once they agree, take the
sha384 of the same bytes and put it in `index.html`.

Then, because the file is a new cache key for nobody and an old one for everybody:

- bump `CACHE` in `static/sw.js` (CI requires it for any deployed file anyway), and
- load the page and confirm the library actually arrives. A wrong hash does not raise an error
  anywhere a user would see; the browser silently refuses the script and the feature that needed
  it goes quietly dead. `window.jspdf`, `window.XLSX`, `window.html2canvas`, `window.pdfjsLib`.

## leaflet/ and fonts/ — vendored to get them off the boot path

Two things used to be fetched from someone else's server on **every page load**:

| was | now | why |
|---|---|---|
| `unpkg.com` Leaflet js+css | `leaflet/` | 162 KB downloaded by every session for a map only the GPS check-in screen opens |
| `fonts.googleapis.com` + `fonts.gstatic.com` Poppins | `fonts/` | a request for the CSS, and only once it arrived could the browser learn the font URLs and open a second connection to a second origin |

Both were costing a DNS lookup, a TCP connection and a TLS handshake to an origin the browser had no
connection to yet — and on the network these users are actually on, an origin that is sometimes slow
and sometimes unreachable. `tests/boot_no_third_party.js` fails if either comes back.

**Leaflet** is loaded by `_tkLoadLeaflet()` the first time a map opens, not by a `<script>` tag. It
keeps Leaflet's own `images/` folder layout, because `leaflet.css` asks for `images/marker-icon.png`
**relative to itself** — flatten it and every default marker 404s while the map still looks fine
otherwise. Both files carry the same sha384 pins the old CDN tags did, set as properties on the
injected elements; `tests/test_shell.py` checks the loader carries exactly two.

**Poppins** is `latin` + `latin-ext` only, five weights, with Google's `unicode-range` declarations
kept verbatim so a browser still downloads only the subset the page's characters need. Google also
offers `devanagari` — 192 KB this app never renders — and it is deliberately not here.

Two things to know before touching the font:

- Poppins has **no Vietnamese subset**, and never did on Google either. Vietnamese diacritics have
  always fallen back to a system face. Vendoring did not change that and re-pointing at Google would
  not fix it; only a different typeface would.
- `.woff2` must stay in `CONTENT_TYPES` and **out of** `GZIP_TYPES` in `app.py`. Served as
  `application/octet-stream` the `<link rel=preload as=font>` becomes a type mismatch and the browser
  throws the preload away and fetches the file a second time; gzipped, it spends CPU to grow, because
  woff2 is already Brotli-compressed inside.

To refresh either, download, **verify the sha384 against the pin already in the tree**, and only then
replace the bytes — the pins in `index.html` are the record of what was reviewed.

## Why not npm

There is no build step here — `templates/index.html` is served as authored, and `mobile/` is the only
npm tree. A package manager would add a toolchain to maintain for five files that change once a year.
