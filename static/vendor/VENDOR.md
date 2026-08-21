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

## Why not npm

There is no build step here — `templates/index.html` is served as authored, and `mobile/` is the only
npm tree. A package manager would add a toolchain to maintain for five files that change once a year.
